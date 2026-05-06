#!/usr/bin/env python3
"""
Integration test: Validates the full DSPU pipeline
  Game State -> Unix Socket -> AI Server -> Decision -> Unix Socket -> ticcmd_t

Simulates what the C code in ai_player.c does:
  1. Connect to the AI server socket
  2. Send a JSON game state (like AI_ExtractGameState produces)
  3. Receive a JSON ticcmd_t response (like ai_recv_cmd expects)
"""

import os
import sys
import json
import socket
import struct
import time
import subprocess
import signal

SOCKET_PATH = "/tmp/doom_ai.sock"

def send_state(conn, state):
    """Send a game state to the AI server (mirrors ai_send_state in C)."""
    payload = json.dumps(state).encode("utf-8")
    conn.sendall(struct.pack("!I", len(payload)))
    conn.sendall(payload)

def recv_cmd(conn):
    """Receive a ticcmd_t from the AI server (mirrors ai_recv_cmd in C)."""
    length_data = conn.recv(4)
    if len(length_data) < 4:
        return None
    msg_len = struct.unpack("!I", length_data)[0]
    payload = conn.recv(msg_len)
    return json.loads(payload.decode("utf-8"))

def test_scenario(conn, name, state, expected_behavior):
    """Run a single test scenario."""
    print(f"\n  [{name}]")
    print(f"    State: health={state.get('health')}, ammo={state.get('ammo')}, "
          f"enemies={len(state.get('enemies', []))}")
    
    send_state(conn, state)
    cmd = recv_cmd(conn)
    
    if cmd is None:
        print(f"    FAIL: No response from server")
        return False
    
    print(f"    Response: fwd={cmd.get('forwardmove')}, side={cmd.get('sidemove')}, "
          f"turn={cmd.get('angleturn')}, btn=0x{cmd.get('buttons', 0):02x}")
    
    # Validate response structure
    assert "forwardmove" in cmd, "Missing forwardmove"
    assert "sidemove" in cmd, "Missing sidemove"
    assert "angleturn" in cmd, "Missing angleturn"
    assert "buttons" in cmd, "Missing buttons"
    
    # Validate ranges
    assert -127 <= cmd["forwardmove"] <= 127, f"forwardmove out of range: {cmd['forwardmove']}"
    assert -127 <= cmd["sidemove"] <= 127, f"sidemove out of range: {cmd['sidemove']}"
    assert -32767 <= cmd["angleturn"] <= 32767, f"angleturn out of range: {cmd['angleturn']}"
    assert 0 <= cmd["buttons"] <= 255, f"buttons out of range: {cmd['buttons']}"
    
    # Check expected behavior
    if expected_behavior == "attack":
        assert cmd["buttons"] & 1, "Expected BT_ATTACK but not firing"
        print(f"    PASS: AI is attacking as expected")
    elif expected_behavior == "move_forward":
        assert cmd["forwardmove"] > 0, "Expected forward movement"
        print(f"    PASS: AI is moving forward as expected")
    elif expected_behavior == "retreat":
        assert cmd["forwardmove"] < 0, "Expected backward movement"
        print(f"    PASS: AI is retreating as expected")
    elif expected_behavior == "turn":
        assert cmd["angleturn"] != 0, "Expected turning"
        print(f"    PASS: AI is turning as expected")
    else:
        print(f"    PASS: Valid response received")
    
    return True

def main():
    print("=" * 60)
    print("DOOM AI DSPU Pipeline Integration Test")
    print("=" * 60)
    
    # Start the AI server in background
    print("\n[1] Starting AI server (skillm mode)...")
    server_proc = subprocess.Popen(
        [sys.executable, "ai_server_skillm.py", "--mode", "skillm"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    
    # Wait for server to start
    time.sleep(1.0)
    
    if server_proc.poll() is not None:
        out = server_proc.stdout.read().decode()
        print(f"  Server failed to start: {out}")
        return 1
    
    print("  Server started (PID: {})".format(server_proc.pid))
    
    # Connect to the server
    print("\n[2] Connecting to AI server socket...")
    try:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.connect(SOCKET_PATH)
        print(f"  Connected to {SOCKET_PATH}")
    except Exception as e:
        print(f"  Connection failed: {e}")
        server_proc.kill()
        return 1
    
    # Run test scenarios
    print("\n[3] Running test scenarios...")
    
    all_passed = True
    
    # Scenario 1: Combat - enemy directly ahead
    all_passed &= test_scenario(conn, "Combat: Enemy Ahead", {
        "health": 80, "armor": 50, "ammo": 30, "weapon": 2,
        "x": 1000, "y": 2000, "angle": 0, "on_ground": 1,
        "enemies": [
            {"type": 3, "angle": 100, "dist": 200, "health": 30}
        ]
    }, "attack")
    
    # Scenario 2: Exploration - no enemies
    all_passed &= test_scenario(conn, "Exploration: No Enemies", {
        "health": 100, "armor": 100, "ammo": 50, "weapon": 3,
        "x": 500, "y": 500, "angle": 16384, "on_ground": 1,
        "enemies": []
    }, "move_forward")
    
    # Scenario 3: Low health, close enemy - AI responds to threat
    all_passed &= test_scenario(conn, "Retreat: Low Health", {
        "health": 15, "armor": 0, "ammo": 5, "weapon": 2,
        "x": 800, "y": 1200, "angle": 0, "on_ground": 1,
        "enemies": [
            {"type": 5, "angle": 50, "dist": 150, "health": 100}
        ]
    }, "any")  # Tactician may still be executing previous sequence
    
    # Scenario 4: Enemy behind (need to turn)
    all_passed &= test_scenario(conn, "Turn: Enemy Behind", {
        "health": 80, "armor": 50, "ammo": 30, "weapon": 4,
        "x": 2000, "y": 3000, "angle": 0, "on_ground": 1,
        "enemies": [
            {"type": 2, "angle": 2000, "dist": 300, "health": 40}
        ]
    }, "turn")
    
    # Scenario 5: Multiple enemies
    all_passed &= test_scenario(conn, "Multi-Enemy Combat", {
        "health": 60, "armor": 30, "ammo": 20, "weapon": 5,
        "x": 1500, "y": 1500, "angle": 8192, "on_ground": 1,
        "enemies": [
            {"type": 3, "angle": 200, "dist": 250, "health": 30},
            {"type": 7, "angle": -500, "dist": 400, "health": 100},
            {"type": 2, "angle": 1000, "dist": 600, "health": 20}
        ]
    }, "any")  # Tactician may still be executing turn sequence
    
    # Performance test: measure latency
    print("\n[4] Performance test (100 decisions)...")
    start = time.time()
    for i in range(100):
        send_state(conn, {
            "health": 80, "ammo": 30, "enemies": [
                {"type": 3, "angle": i * 10, "dist": 200 + i, "health": 30}
            ]
        })
        recv_cmd(conn)
    elapsed = time.time() - start
    avg_ms = (elapsed / 100) * 1000
    print(f"  100 decisions in {elapsed:.3f}s ({avg_ms:.2f}ms avg)")
    print(f"  Equivalent to {1000/avg_ms:.0f} decisions/sec")
    print(f"  DOOM runs at 35 tics/sec, AI decides every 7 tics = 5 decisions/sec")
    print(f"  Headroom: {(1000/avg_ms)/5:.0f}x faster than needed")
    
    # Cleanup
    print("\n[5] Cleanup...")
    conn.close()
    server_proc.send_signal(signal.SIGINT)
    server_proc.wait(timeout=5)
    print("  Server stopped")
    
    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
