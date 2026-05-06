# DOOM AI Player - DSPU Architecture

> CPU-only GGUF/llama.cpp inference integrated into the DOOM game loop as an AI player.

## Architecture

```
Composition: /dspu-architecture-design ( /nn [ /ggml-spec | /llama-cpp-spec ] -> /llamacpu -> /skillm )
```

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DOOM Game Loop (35 Hz)                       │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │ G_BuildTiccmd│───▶│ AI_BuildTiccmd│───▶│ ticcmd_t injection   │  │
│  └──────────────┘    └───────┬───────┘    └──────────────────────┘  │
│                              │                                       │
│         ┌────────────────────┼────────────────────┐                 │
│         │  DSPU Front End    │   (ai_player.c)    │                 │
│         │  AI_ExtractGameState: health, ammo,     │                 │
│         │  enemies[], position, angle             │                 │
│         └────────────────────┼────────────────────┘                 │
└──────────────────────────────┼──────────────────────────────────────┘
                               │ Unix Socket (JSON, length-prefixed)
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    DSPU Execution Fabric (Python)                     │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │ Mode Selection (⊕ choice):                                      ││
│  │   HEURISTIC ⊕ SKILLM ⊕ LLM                                     ││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                      │
│  ┌─────────────┐  ┌──────────────────┐  ┌────────────────────────┐ │
│  │  Heuristic  │  │ skillm Tactician │  │  llama.cpp (GGUF)      │ │
│  │  (rules)    │  │ (action vocab)   │  │  CPU-only inference    │ │
│  │  ~0ms       │  │  ~0.1ms          │  │  ~50-500ms             │ │
│  └─────────────┘  └──────────────────┘  └────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Build DOOM with AI Player

```bash
cd linuxdoom-1.10
make clean && make
```

The build produces `linux/linuxxdoom` with the `-DDOOM_AI_PLAYER` flag.

### 2. Start the AI Server

```bash
# Default: skillm tactical AI (fast, no LLM needed)
python3 ai/ai_server_skillm.py --mode skillm

# Or: Full LLM inference (requires GGUF model)
python3 ai/ai_server_skillm.py --mode llm --model path/to/model.gguf

# Or: Simple heuristic (fastest, minimal logic)
python3 ai/ai_server_skillm.py --mode heuristic
```

### 3. Run DOOM with AI Player

```bash
./linux/linuxxdoom -ai -iwad doom.wad
```

The `-ai` flag activates the AI player on the console player slot.

## AI Modes

| Mode | Latency | Intelligence | Requirements |
|------|---------|-------------|--------------|
| `heuristic` | ~0ms | Basic reactive | None |
| `skillm` | ~0.1ms | Tactical (combat/explore) | None |
| `llm` | ~50-500ms | Adaptive/creative | GGUF model file |

## skillm Action Vocabulary

The AI uses 10 primitive verbs from the skillm procedural language model:

| Verb | DOOM Semantics | ticcmd_t Effect |
|------|---------------|-----------------|
| NAVIGATE | Move through world | forwardmove, angleturn |
| MUTATE | Fire weapon | buttons = BT_ATTACK |
| CREATE | Use/activate | buttons = BT_USE |
| COMPOSE | Multi-action (strafe+fire) | Combined fields |
| DISCOVER | Scan for entities | angleturn sweep |
| OBSERVE | Check state (idle) | All zero |
| CLASSIFY | Assess threat level | Internal only |
| ORCHESTRATE | Multi-step plan | Sequence of actions |
| INSPECT | Read entity state | Internal only |
| DESTROY | Sustained attack | Repeated MUTATE |

### Semiring Algebra

Actions compose via the semiring `(R, ⊕, ⊗, 0, 1)`:
- **⊗ (pipeline)**: Execute actions in sequence
- **⊕ (choice)**: Select one action based on condition

Example combat policy:
```
combat = (face_enemy ⊗ fire) ⊕ (dodge ⊗ retreat)
```

## Files

| File | Purpose |
|------|---------|
| `ai/ai_server.py` | LLM inference server (GGUF/llama.cpp) |
| `ai/ai_server_skillm.py` | Integrated server (all 3 modes) |
| `ai/skillm_doom.py` | skillm action vocabulary & tactician |
| `ai/test_pipeline.py` | Integration test suite |
| `linuxdoom-1.10/ai_player.h` | C header for game loop integration |
| `linuxdoom-1.10/ai_player.c` | C implementation (state extraction, socket IPC) |
| `docs/dspu-architecture.md` | Full DSPU architecture design document |

## Protocol

Communication between DOOM (C) and the AI server (Python) uses Unix sockets with a simple protocol:

```
[4 bytes: message length (network byte order)] [N bytes: JSON payload]
```

**Request** (DOOM → AI):
```json
{
  "health": 80, "armor": 50, "ammo": 30, "weapon": 2,
  "x": 1000, "y": 2000, "angle": 16384, "on_ground": 1,
  "enemies": [
    {"type": 3, "angle": 200, "dist": 250, "health": 30}
  ]
}
```

**Response** (AI → DOOM):
```json
{"forwardmove": 50, "sidemove": 0, "angleturn": -400, "buttons": 1}
```

## Performance

Tested on the sandbox environment:
- **100 decisions in 0.008s** (0.08ms average)
- **12,618 decisions/sec** throughput
- DOOM needs only 5 decisions/sec (35 tics / 7 tic interval)
- **2,524x headroom** over game requirements

## Dependencies

- Python 3.11+ with `llama-cpp-python` (for LLM mode only)
- GCC with X11 development headers (for building DOOM)
- Any GGUF model file (for LLM mode; bundled TinyStories for testing)
