#!/usr/bin/env python3
"""
DOOM AI Player - GGUF/llama.cpp Inference Server
=================================================
DSPU Back-End: Receives game state observations over a Unix socket,
runs CPU-only inference via llama-cpp-python, and returns action commands.

Composition: /dspu-architecture-design ( /nn [ /ggml-spec | /llama-cpp-spec ] -> /llamacpu -> /skillm )

The server implements the skillm action vocabulary for DOOM:
  NAVIGATE_FWD, NAVIGATE_BWD, NAVIGATE_LEFT, NAVIGATE_RIGHT,
  STRAFE_LEFT, STRAFE_RIGHT, MUTATE_FIRE, CREATE_USE, COMPOSE_WPN_X
"""

import os
import sys
import json
import socket
import struct
import threading
import time
from pathlib import Path

# --- Configuration ---
MODEL_PATH = os.environ.get(
    "DOOM_AI_MODEL",
    str(Path(__file__).parent.parent / "ai" / "model" / "doom-ai.gguf")
)
# Fallback to the bundled TinyStories model for testing
if not os.path.exists(MODEL_PATH):
    MODEL_PATH = "/home/ubuntu/skills/llamacpu/model/tinystories-gpt-0_1-3m_Q4_K_M.gguf"

SOCKET_PATH = "/tmp/doom_ai.sock"
N_CTX = 512
N_THREADS = 2
MAX_TOKENS = 10
TEMPERATURE = 0.0  # Deterministic for reproducible gameplay

# --- skillm Action Vocabulary for DOOM ---
# Maps action tokens to ticcmd_t field values
# ticcmd_t: { forwardmove: i8, sidemove: i8, angleturn: i16, buttons: u8 }
# buttons: BT_ATTACK=1, BT_USE=2, BT_CHANGE=4, weapon_bits=3..5

ACTION_MAP = {
    "NAVIGATE_FWD":    {"forwardmove":  50, "sidemove": 0, "angleturn": 0, "buttons": 0},
    "NAVIGATE_BWD":    {"forwardmove": -50, "sidemove": 0, "angleturn": 0, "buttons": 0},
    "NAVIGATE_LEFT":   {"forwardmove":   0, "sidemove": 0, "angleturn": 1200, "buttons": 0},
    "NAVIGATE_RIGHT":  {"forwardmove":   0, "sidemove": 0, "angleturn": -1200, "buttons": 0},
    "STRAFE_LEFT":     {"forwardmove":   0, "sidemove": -40, "angleturn": 0, "buttons": 0},
    "STRAFE_RIGHT":    {"forwardmove":   0, "sidemove":  40, "angleturn": 0, "buttons": 0},
    "MUTATE_FIRE":     {"forwardmove":   0, "sidemove": 0, "angleturn": 0, "buttons": 1},
    "ATTACK_FWD":      {"forwardmove":  30, "sidemove": 0, "angleturn": 0, "buttons": 1},
    "CREATE_USE":      {"forwardmove":   0, "sidemove": 0, "angleturn": 0, "buttons": 2},
    "COMPOSE_WPN_1":   {"forwardmove":   0, "sidemove": 0, "angleturn": 0, "buttons": 4 | (0 << 3)},
    "COMPOSE_WPN_2":   {"forwardmove":   0, "sidemove": 0, "angleturn": 0, "buttons": 4 | (1 << 3)},
    "COMPOSE_WPN_3":   {"forwardmove":   0, "sidemove": 0, "angleturn": 0, "buttons": 4 | (2 << 3)},
    "IDLE":            {"forwardmove":   0, "sidemove": 0, "angleturn": 0, "buttons": 0},
}

# --- Heuristic AI (Rule-Based Fallback) ---
# When the LLM output is not parseable, use a simple reactive policy
def heuristic_decide(state):
    """
    Simple reactive AI that doesn't need LLM inference.
    Uses direct game state to make decisions.
    """
    cmd = {"forwardmove": 0, "sidemove": 0, "angleturn": 0, "buttons": 0}
    
    health = state.get("health", 100)
    ammo = state.get("ammo", 50)
    enemies = state.get("enemies", [])
    
    if enemies:
        # Find closest enemy
        closest = min(enemies, key=lambda e: e.get("dist", 9999))
        angle_to_enemy = closest.get("angle", 0)
        dist = closest.get("dist", 9999)
        
        # Turn toward enemy
        if abs(angle_to_enemy) > 200:
            cmd["angleturn"] = 800 if angle_to_enemy > 0 else -800
        elif abs(angle_to_enemy) > 50:
            cmd["angleturn"] = 400 if angle_to_enemy > 0 else -400
        
        # Fire if roughly facing enemy
        if abs(angle_to_enemy) < 300 and ammo > 0:
            cmd["buttons"] |= 1  # BT_ATTACK
        
        # Approach if far, retreat if too close and low health
        if dist > 300:
            cmd["forwardmove"] = 50
        elif dist < 100 and health < 40:
            cmd["forwardmove"] = -40
            cmd["sidemove"] = 30  # Strafe while retreating
        else:
            cmd["forwardmove"] = 20
            # Strafe to avoid projectiles
            cmd["sidemove"] = 25 if (int(time.time() * 2) % 2 == 0) else -25
    else:
        # No enemies visible: explore
        cmd["forwardmove"] = 50
        # Slight random turning to explore
        cmd["angleturn"] = 200 if (int(time.time()) % 3 == 0) else 0
    
    return cmd


# --- LLM-Based AI ---
class DoomAIBrain:
    """
    DSPU Execution Fabric: Wraps llama-cpp-python for DOOM decision-making.
    Implements the /nn [ /ggml-spec | /llama-cpp-spec ] -> /llamacpu pipeline.
    """
    
    def __init__(self, model_path, use_llm=True):
        self.use_llm = use_llm
        self.llm = None
        
        if use_llm:
            try:
                from llama_cpp import Llama
                print(f"[DOOM-AI] Loading model: {model_path}")
                self.llm = Llama(
                    model_path=model_path,
                    n_ctx=N_CTX,
                    n_threads=N_THREADS,
                    verbose=False
                )
                print(f"[DOOM-AI] Model loaded successfully")
            except Exception as e:
                print(f"[DOOM-AI] Failed to load LLM: {e}")
                print(f"[DOOM-AI] Falling back to heuristic AI")
                self.use_llm = False
    
    def format_prompt(self, state):
        """
        DSPU Front End: Convert game state to inference prompt.
        Encodes the observation as a structured text prompt.
        """
        parts = []
        parts.append("You are an AI playing DOOM. Choose ONE action from: "
                     "NAVIGATE_FWD, NAVIGATE_BWD, NAVIGATE_LEFT, NAVIGATE_RIGHT, "
                     "STRAFE_LEFT, STRAFE_RIGHT, MUTATE_FIRE, ATTACK_FWD, CREATE_USE, IDLE")
        parts.append(f"\nState: Health={state.get('health', 100)}, "
                     f"Ammo={state.get('ammo', 50)}, "
                     f"Armor={state.get('armor', 0)}")
        
        enemies = state.get("enemies", [])
        if enemies:
            parts.append(f"Enemies({len(enemies)}):")
            for e in enemies[:3]:  # Limit to 3 closest
                parts.append(f"  {e.get('type','unknown')} angle={e.get('angle',0)} dist={e.get('dist',0)}")
        else:
            parts.append("No enemies visible.")
        
        parts.append("\nAction:")
        return "\n".join(parts)
    
    def decide(self, state):
        """
        DSPU Pipeline: Observation -> Inference -> Action Decode.
        Returns a ticcmd_t-compatible dict.
        """
        if not self.use_llm or self.llm is None:
            return heuristic_decide(state)
        
        prompt = self.format_prompt(state)
        
        try:
            output = self.llm(
                prompt,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                stop=["\n", ".", ","]
            )
            text = output["choices"][0]["text"].strip().upper()
            
            # Try to parse the action from LLM output
            for action_name in ACTION_MAP:
                if action_name in text:
                    return ACTION_MAP[action_name].copy()
            
            # LLM didn't produce a valid action, use heuristic
            return heuristic_decide(state)
            
        except Exception as e:
            print(f"[DOOM-AI] Inference error: {e}")
            return heuristic_decide(state)


# --- Socket Server ---
class DoomAIServer:
    """
    DSPU Interface: Unix socket server that bridges DOOM C engine to Python AI.
    Protocol: 4-byte length prefix + JSON payload.
    """
    
    def __init__(self, brain):
        self.brain = brain
        self.running = False
    
    def start(self):
        # Remove stale socket
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(SOCKET_PATH)
        self.sock.listen(1)
        self.running = True
        
        print(f"[DOOM-AI] Server listening on {SOCKET_PATH}")
        print(f"[DOOM-AI] Waiting for DOOM engine connection...")
        
        while self.running:
            try:
                conn, _ = self.sock.accept()
                print(f"[DOOM-AI] DOOM engine connected")
                self.handle_connection(conn)
            except Exception as e:
                if self.running:
                    print(f"[DOOM-AI] Accept error: {e}")
    
    def handle_connection(self, conn):
        """Handle a single DOOM engine connection."""
        try:
            while self.running:
                # Read 4-byte length prefix
                length_data = self.recv_exact(conn, 4)
                if not length_data:
                    break
                
                msg_len = struct.unpack("!I", length_data)[0]
                if msg_len > 65536:
                    print(f"[DOOM-AI] Message too large: {msg_len}")
                    break
                
                # Read JSON payload
                payload = self.recv_exact(conn, msg_len)
                if not payload:
                    break
                
                state = json.loads(payload.decode("utf-8"))
                
                # Run AI decision
                cmd = self.brain.decide(state)
                
                # Send response
                response = json.dumps(cmd).encode("utf-8")
                conn.sendall(struct.pack("!I", len(response)))
                conn.sendall(response)
                
        except (BrokenPipeError, ConnectionResetError):
            print(f"[DOOM-AI] DOOM engine disconnected")
        except Exception as e:
            print(f"[DOOM-AI] Connection error: {e}")
        finally:
            conn.close()
    
    def recv_exact(self, conn, n):
        """Receive exactly n bytes."""
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data
    
    def stop(self):
        self.running = False
        self.sock.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)


def main():
    import argparse
    global SOCKET_PATH
    
    parser = argparse.ArgumentParser(description="DOOM AI Player - GGUF Inference Server")
    parser.add_argument("--model", default=MODEL_PATH, help="Path to GGUF model file")
    parser.add_argument("--heuristic", action="store_true", help="Use heuristic AI only (no LLM)")
    parser.add_argument("--socket", default=SOCKET_PATH, help="Unix socket path")
    args = parser.parse_args()
    
    SOCKET_PATH = args.socket
    
    brain = DoomAIBrain(args.model, use_llm=not args.heuristic)
    server = DoomAIServer(brain)
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[DOOM-AI] Shutting down...")
        server.stop()


if __name__ == "__main__":
    main()
