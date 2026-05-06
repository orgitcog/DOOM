#!/usr/bin/env python3
"""
DOOM AI Player - Integrated DSPU Server (skillm + llama.cpp)
=============================================================
Full composition: /dspu-architecture-design ( /nn [ /ggml-spec | /llama-cpp-spec ] -> /llamacpu -> /skillm )

This server integrates three AI modes:
  1. HEURISTIC: Pure rule-based reactive AI (fastest, no inference)
  2. SKILLM:    Tactical decision engine using skillm action vocabulary (fast, no LLM)
  3. LLM:       Full GGUF/llama.cpp inference for creative/adaptive play (slowest)

The default mode is SKILLM, which provides intelligent gameplay without
requiring LLM inference latency. LLM mode can be enabled for research
or when a fine-tuned DOOM-specific model is available.
"""

import os
import sys
import json
import socket
import struct
import time
from pathlib import Path

# Add the ai directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from skillm_doom import DoomTactician, create_tactician
from ai_server import (
    DoomAIBrain, DoomAIServer, SOCKET_PATH, MODEL_PATH,
    heuristic_decide, ACTION_MAP
)


class IntegratedDoomAI:
    """
    Unified AI brain that composes all three decision modes.
    
    Architecture:
      Mode selection is itself a skillm CLASSIFY operation:
        CLASSIFY(state) -> mode ∈ {HEURISTIC, SKILLM, LLM}
      
      Then the selected mode's pipeline runs:
        HEURISTIC: state -> rule_table -> ticcmd_t
        SKILLM:    state -> tactician.decide() -> ticcmd_t  
        LLM:       state -> tokenize -> llama.cpp -> decode -> ticcmd_t
    """
    
    MODE_HEURISTIC = "heuristic"
    MODE_SKILLM = "skillm"
    MODE_LLM = "llm"
    
    def __init__(self, mode=None, model_path=None):
        self.mode = mode or self.MODE_SKILLM
        self.tactician = create_tactician()
        self.llm_brain = None
        
        if self.mode == self.MODE_LLM:
            self.llm_brain = DoomAIBrain(model_path or MODEL_PATH, use_llm=True)
        
        print(f"[DOOM-AI] Integrated server initialized in {self.mode.upper()} mode")
    
    def decide(self, state):
        """Route decision to the appropriate mode."""
        if self.mode == self.MODE_HEURISTIC:
            return heuristic_decide(state)
        elif self.mode == self.MODE_SKILLM:
            return self.tactician.decide(state)
        elif self.mode == self.MODE_LLM:
            if self.llm_brain:
                return self.llm_brain.decide(state)
            else:
                return self.tactician.decide(state)
        else:
            return heuristic_decide(state)


class IntegratedServer(DoomAIServer):
    """Extended server that uses the integrated AI brain."""
    pass


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="DOOM AI Player - Integrated DSPU Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  heuristic  - Simple reactive rules (fastest, ~0ms per decision)
  skillm     - Tactical decision engine with action vocabulary (fast, ~1ms)
  llm        - Full GGUF/llama.cpp inference (slow, ~50-500ms per decision)

Examples:
  %(prog)s --mode skillm              # Default: tactical AI
  %(prog)s --mode llm --model path.gguf  # LLM-powered AI
  %(prog)s --mode heuristic           # Simple reactive AI
        """
    )
    parser.add_argument("--mode", choices=["heuristic", "skillm", "llm"],
                        default="skillm", help="AI decision mode")
    parser.add_argument("--model", default=MODEL_PATH, help="GGUF model path (for LLM mode)")
    parser.add_argument("--socket", default=SOCKET_PATH, help="Unix socket path")
    args = parser.parse_args()
    
    # Override global socket path
    import ai_server
    ai_server.SOCKET_PATH = args.socket
    
    brain = IntegratedDoomAI(mode=args.mode, model_path=args.model)
    server = IntegratedServer(brain)
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[DOOM-AI] Shutting down...")
        server.stop()


if __name__ == "__main__":
    main()
