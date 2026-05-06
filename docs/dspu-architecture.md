# DSPU Design: DOOM AI Player (GGUF/llama.cpp Inference)

## Design summary

This Domain-Specific Processing Unit (DSPU) architecture integrates a CPU-only GGUF/llama.cpp inference engine directly into the DOOM game loop. It acts as an autonomous AI player by composing the `nn` (neural network representation), `ggml-spec` (tensor operations), `llama-cpp-spec` (minimal inference engine), and `llamacpu` (CPU execution) skills, mapped into the game's action space via `skillm` (procedural language model). The DSPU observes the game state, processes it through a quantized language model (e.g., Qwen2-0.5B or TinyStories), and synthesizes a sequence of `ticcmd_t` commands to control the player avatar in real-time, all within the strict lockstep constraints of the DOOM engine.

## Context and workload

- **Domain:** Real-time first-person shooter AI (DOOM engine).
- **Input data:** Game state (player position, health, ammo, visible entities, incoming projectiles) serialized as text or structured tokens.
- **Output data:** `ticcmd_t` structs containing `forwardmove`, `sidemove`, `angleturn`, and `buttons` (attack, use, weapon change).
- **Runtime context:** Executes within the `TryRunTics` / `NetUpdate` loop of `linuxdoom-1.10`, running on the host CPU alongside the game simulation.
- **Optimization goal:** Latency (must generate commands fast enough to maintain playability, ~28ms per tic target), memory footprint (minimal impact on the game engine), and determinism (integration with the lockstep network model).

## Architecture overview

```text
DOOM-AI-DSPU
├── Front End (Observation)
│   ├── State Extractor (reads mobj_t, player_t)
│   ├── Tokenizer (converts state to prompt/tokens)
│   └── Context Window Manager (maintains history)
├── Execution Fabric (Inference)
│   ├── GGML Tensor Core (CPU-optimized ops: MUL_MAT, GET_ROWS)
│   ├── llama.cpp Engine (manages weights and KV cache)
│   └── skillm Sequence Generator (maps logits to action verbs)
├── Back End (Action)
│   ├── Action Decoder (translates skillm verbs to DOOM semantics)
│   ├── Ticcmd Builder (populates ticcmd_t fields)
│   └── Command Buffer (injects into localcmds / netcmds)
└── Memory and Data Movement
    ├── GGUF Model Weights (memory-mapped)
    ├── KV Cache (SRAM/RAM)
    └── Scratchpad (intermediate activations)
```

## Data representation

- **State Observation:** Structured text prompt describing the immediate environment (e.g., "Health: 100, Ammo: 50, Enemies: Imp at 45 degrees, Distance 200").
- **Action Vocabulary (`skillm`):**
  - `NAVIGATE(angle, distance)` -> translates to `angleturn` and `forwardmove`.
  - `MUTATE(attack)` -> translates to `BT_ATTACK`.
  - `COMPOSE(strafe, attack)` -> translates to `sidemove` and `BT_ATTACK`.
  - `CREATE(interact)` -> translates to `BT_USE`.
- **Game Command:** DOOM `ticcmd_t` struct (forward/side movement, angle delta, buttons).

## Datapath

1. **Observation Phase:** At the start of a decision cycle (e.g., every 10 tics to save compute), the State Extractor reads the player's `mobj_t` and surrounding sector data.
2. **Encoding:** The state is formatted into a prompt and tokenized.
3. **Inference Phase:** The GGML engine performs the forward pass. `MUL_MAT` and `GET_ROWS` dominate the compute time.
4. **Decoding:** The model outputs a token sequence representing a `skillm` action (e.g., `NAVIGATE_FORWARD_ATTACK`).
5. **Actuation Phase:** The Action Decoder translates the action into specific values for `cmd->forwardmove`, `cmd->angleturn`, and `cmd->buttons`.
6. **Injection:** The populated `ticcmd_t` is written to the game's local command buffer (`localcmds`) during `NetUpdate` or `G_BuildTiccmd`.

## Memory hierarchy

- **Storage:** GGUF model file on disk.
- **Main Memory:** Memory-mapped (mmap) weights to avoid loading the entire model into RAM at once.
- **Hot Memory:** KV Cache for the current context window, keeping the state history accessible for the autoregressive generation.
- **Registers/L1 Cache:** Used heavily by GGML's SIMD (e.g., AVX2/NEON) routines during matrix multiplication.

## ISA or command model

The DSPU abstracts the DOOM engine's low-level inputs into a higher-level semantic ISA based on `skillm`:

| `skillm` Verb | DOOM Translation | `ticcmd_t` Fields Modified |
|---|---|---|
| `NAVIGATE_FWD` | Move forward | `forwardmove > 0` |
| `NAVIGATE_BWD` | Move backward | `forwardmove < 0` |
| `NAVIGATE_LEFT` | Turn left | `angleturn > 0` |
| `NAVIGATE_RIGHT` | Turn right | `angleturn < 0` |
| `STRAFE_LEFT` | Strafe left | `sidemove < 0` |
| `STRAFE_RIGHT` | Strafe right | `sidemove > 0` |
| `MUTATE_FIRE` | Shoot weapon | `buttons |= BT_ATTACK` |
| `CREATE_USE` | Interact (doors/switches) | `buttons |= BT_USE` |
| `COMPOSE_WPN_X`| Change weapon | `buttons |= BT_CHANGE`, `buttons |= X << BT_WEAPONSHIFT` |

## Component counts

| Subsystem | Count parameter | Candidate value | Rationale | Scaling risk |
|---|---:|---:|---|---|
| Inference Threads | T | 2-4 | Utilize multi-core CPU without starving the main game thread | Context switching overhead |
| Context Window | C | 512 tokens | Keep memory and latency low; DOOM state is highly transient | Forgetting long-term goals (e.g., keys) |
| Decision Rate | R | 1 Hz (35 tics) | LLM inference is too slow for 35Hz; hold commands between decisions | Reaction time to fast projectiles |
| Model Parameters | P | 0.5B - 1.1B | Fits in RAM, fast CPU inference | Suboptimal decision making |

## Emulator/simulator model

The integration into the DOOM loop acts as a functional simulator:

```c
// Inside G_BuildTiccmd or NetUpdate
void AI_BuildTiccmd(ticcmd_t* cmd) {
    static int tic_counter = 0;
    static ticcmd_t last_cmd = {0};

    // Only run inference every N tics to accommodate CPU speed
    if (tic_counter % AI_DECISION_INTERVAL == 0) {
        char* state_prompt = AI_ExtractGameState();
        char* action_str = llama_generate(ctx, state_prompt);
        AI_DecodeActionToTiccmd(action_str, &last_cmd);
    }
    
    // Apply the sustained action for the duration of the interval
    memcpy(cmd, &last_cmd, sizeof(ticcmd_t));
    tic_counter++;
}
```

## Verification and benchmarks

1. **Unit Tests:** Verify that `AI_DecodeActionToTiccmd` correctly populates `ticcmd_t` fields for all `skillm` verbs.
2. **Inference Benchmarks:** Measure tokens/second using `llamacpu` standalone to ensure the chosen model (e.g., Qwen2-0.5B) can meet the latency budget.
3. **Integration Tests:** Run DOOM with the AI player in a simple test map (e.g., E1M1 start room) and observe if it can navigate and fire.
4. **Trace Replay:** Record the AI's generated `ticcmd_t` sequence and replay it as a standard DOOM demo (`.lmp`) to verify determinism and sync.

## Implementation roadmap

1. **Phase 1: Minimal Inference Engine:** Compile `llama.cpp` as a static library or integrate `llamacpu` directly into the DOOM build system (`Makefile`).
2. **Phase 2: State Extraction:** Write C functions to traverse the DOOM blockmap/sectors and generate a concise text representation of the player's surroundings.
3. **Phase 3: Game Loop Integration:** Hook into `G_BuildTiccmd` to inject commands. Implement a threaded or asynchronous inference queue to prevent the game from freezing during token generation.
4. **Phase 4: Prompt Engineering & Testing:** Refine the prompt format and test with small models to achieve coherent behavior.

## Risks and open questions

- **Latency:** LLM inference, even with small models, takes tens to hundreds of milliseconds per token. DOOM expects a new `ticcmd_t` every 28ms (35Hz). The AI must either generate actions asynchronously or the game must be slowed down/paused during inference.
- **Asynchronous Synchronization:** If inference runs on a background thread, the game state will have advanced by the time the action is ready. The AI might react to outdated information.
- **Model Capability:** Can a sub-1B parameter model accurately translate spatial coordinates and game state into logical movement and combat decisions without fine-tuning?
- **Determinism:** `llama.cpp` must be configured for deterministic output (temperature = 0) if the AI is to be used in demo recording or network play.
