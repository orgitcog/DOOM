# DOOM Source Code — Comprehensive Overview

> Released by id Software (John Carmack) on 23 December 1997.  
> GNU General Public License v2.0 · Copyright © ZeniMax Media Inc.

---

## Background

This repository contains the official open-source release of **DOOM** (v1.10), the landmark 1993 first-person shooter developed by id Software.  The release is the Linux port (`linuxdoom-1.10`) accompanied by:

- A standalone **sound server** process (`sndserv/`)
- DOS **network driver** utilities (`ipx/`, `sersrc/`)

The game still requires original DOOM WAD data files at runtime.  The DOS code was not released because of a proprietary sound library; this Linux port uses the X11 display system and OSS audio.

---

## Repository Layout

```
DOOM/
├── linuxdoom-1.10/   # Complete game engine — ~14 000 lines of C
│   ├── Makefile
│   └── *.c / *.h     # ~90 source files, grouped by prefix
│
├── sndserv/          # External sound-server process (Linux OSS)
│   ├── soundsrv.c    # Main server loop
│   ├── linux.c       # OSS /dev/dsp driver
│   ├── wadread.c     # Reads sound lumps directly from WAD
│   └── Makefile
│
├── ipx/              # DOS IPX LAN setup utility (not used on Linux)
│   ├── IPXSETUP.C
│   └── IPXNET.C
│
├── sersrc/           # DOS serial (null-modem) setup utility
│   └── SERSETUP.C
│
├── README.TXT        # John Carmack's release notes
└── LICENSE.TXT       # GNU GPL v2
```

---

## Key Technologies

| Technology | Detail |
|---|---|
| **Language** | C (with C++ style comments; compiles with `gcc` or `g++`) |
| **Build** | GNU `make` — single `Makefile`, output to `linux/` subdirectory |
| **Display** | X11 via `libX11` + `libXext` — 8-bit palettised 320×200 framebuffer |
| **Audio** | Separate `sndserv` process; IPC via socket; OSS `/dev/dsp` |
| **Math** | 16.16 fixed-point integers throughout (`fixed_t = int`) |
| **Data** | WAD archive format — a flat lump directory used as a virtual filesystem |
| **Networking** | UDP sockets; lockstep `ticcmd_t` synchronisation across up to 4 players |
| **Geometry** | Pre-compiled BSP trees for fast visibility + rendering order |

---

## Source File Prefix Guide

Every file in `linuxdoom-1.10/` belongs to one of the following subsystems, identified by its two-letter prefix:

| Prefix | Subsystem | Key files |
|---|---|---|
| `d_` | Driver / Main loop | `d_main.c`, `d_net.c`, `d_items.c` |
| `i_` | Platform interface (HAL) | `i_main.c`, `i_video.c`, `i_sound.c`, `i_system.c`, `i_net.c` |
| `r_` | Renderer | `r_main.c`, `r_bsp.c`, `r_segs.c`, `r_plane.c`, `r_things.c`, `r_draw.c` |
| `p_` | Play (game logic / physics) | `p_tick.c`, `p_map.c`, `p_mobj.c`, `p_enemy.c`, `p_user.c`, `p_inter.c` |
| `g_` | Game state machine | `g_game.c` |
| `m_` | Miscellaneous utilities | `m_fixed.c`, `m_random.c`, `m_menu.c`, `m_cheat.c`, `m_bbox.c` |
| `s_` | Sound mixer | `s_sound.c`, `sounds.c` |
| `w_` | WAD virtual filesystem | `w_wad.c` |
| `z_` | Zone memory allocator | `z_zone.c` |
| `v_` | Video (high-level) | `v_video.c` |
| `f_` | Finale / wipe effects | `f_finale.c`, `f_wipe.c` |
| `hu_` | Heads-Up Display | `hu_stuff.c`, `hu_lib.c` |
| `st_` | Status bar | `st_stuff.c`, `st_lib.c` |
| `wi_` | Intermission screen | `wi_stuff.c` |
| `am_` | Automap | `am_map.c` |
| (none) | Core data tables | `info.c`, `tables.c`, `doomdef.h`, `doomstat.h`, `doomdata.h` |

---

## Subsystem Descriptions

### `d_` — Entry Point & Game Loop

`i_main.c` contains `main()`, which immediately calls `D_DoomMain()` in `d_main.c`.  
`D_DoomMain` parses command-line arguments, initialises all subsystems, loads WAD files, and then enters the **main game loop** `D_DoomLoop`.

The loop runs at **35 Hz** (one "tic" per 1/35 s):

```
D_DoomLoop:
  forever:
    TryRunTics()   // advance simulation
    D_Display()    // render frame
```

`d_net.c` implements the lockstep network protocol.  Each tic, every node broadcasts its `ticcmd_t` (player input) to all peers.  The simulation only advances when all inputs have been received, ensuring perfect determinism.

---

### `i_` — Platform Interface (Hardware Abstraction Layer)

The `i_` layer is the only place where OS-specific code lives.  Porting DOOM means re-implementing these six files:

| File | Responsibility |
|---|---|
| `i_main.c` | `main()`, signal handling |
| `i_video.c` | Open X11 window, flush 8-bit framebuffer to screen, handle palette |
| `i_sound.c` | Connect to `sndserv` IPC, send sound play requests |
| `i_system.c` | Clock (`I_GetTime`), fatal error (`I_Error`), quit |
| `i_net.c` | UDP socket creation, `doomcom_t` setup |

---

### `r_` — Renderer (Software Rasteriser)

DOOM's renderer is a **column-based software rasteriser** built on a BSP tree.  It never uses floating-point; all scale and distance calculations use 16.16 fixed-point.

**Rendering pipeline per frame:**

1. **`r_main.c`** — Set up view frustum, angle tables, scale tables
2. **`r_bsp.c`** — Traverse BSP tree front-to-back; clip segs against the horizontal "solidsegs" array
3. **`r_segs.c`** — Draw visible wall segments as vertical columns (upper/mid/lower textures)
4. **`r_plane.c`** — Collect and render visplanes (floors and ceilings as horizontal spans)
5. **`r_things.c`** — Sort and draw sprites (billboards) with occlusion against the silhouette arrays built during wall rendering
6. **`r_draw.c`** — Low-level pixel-column and pixel-span writers; apply lightmap (`lighttable_t`)

Textures are composited on demand from WAD patches by `r_data.c` using a column-based layout (`post_t` / `column_t`).

---

### `p_` — Play Subsystem (Game Logic)

All actor behaviour, physics, and level interaction live here.

**Thinker system (`d_think.h`):**  
Every active object in the world is a `thinker_t` — a node in a doubly-linked list.  Each tic, `P_Ticker` walks the list and calls each thinker's `function` pointer.  `mobj_t` (map object) embeds a `thinker_t` as its first field, enabling safe casting.

**Map Objects (`p_mobj.c`):**  
`mobj_t` is the universal actor type for players, monsters, projectiles, pickups, and decorations. It stores:
- 16.16 fixed-point 3-D position (`x, y, z`)
- Momentum (`momx, momy, momz`)
- FSM state pointer (`state_t*`) driving sprite animation
- Flags bitmask (`mobjflag_t`) with 26 defined flags
- Links into sector list and 128×128 blockmap grid

**Collision detection (`p_map.c`, `p_maputl.c`):**  
Movement is validated against the blockmap (a 2-D grid of lines and things).  Line-of-sight is checked by tracing a ray through BSP leaves (`p_sight.c`).

**Monster AI (`p_enemy.c`):**  
Each monster FSM state table (in `info.c`) specifies frame, duration, and action function pointer.  Behaviour ranges from roaming (`A_Chase`) through ranged attack (`A_PosAttack`, etc.) to pain and death states.

**Sector specials (`p_spec.c`, `p_doors.c`, `p_floor.c`, etc.):**  
Doors, lifts, crushers, and light effects are implemented as `thinker_t` objects attached to sectors, advancing one step per tic.

---

### `g_` — Game State Machine

`g_game.c` is the top-level game state manager.  It drives the `gamestate_t` enum:

```
GS_LEVEL → GS_INTERMISSION → GS_FINALE → GS_DEMOSCREEN
```

It also handles:
- Demo recording and playback (writing/reading `ticcmd_t` streams)
- Save game serialisation (via `p_saveg.c`)
- Skill/episode/map selection
- Cheats routing

---

### `m_` — Utility Library

| File | Detail |
|---|---|
| `m_fixed.c` | `FixedMul`, `FixedDiv` — 32-bit 16.16 arithmetic |
| `m_random.c` | 256-entry lookup table; `P_Random()` for game logic; `M_Random()` for visuals |
| `m_bbox.c` | Axis-aligned bounding box expand/contains/overlap |
| `m_cheat.c` | Cheat code KMP state machines |
| `m_argv.c` | Command-line argument store and lookup |
| `m_misc.c` | `doom.cfg` load/save, screenshot BMP writer |
| `m_swap.c` | `SHORT()` / `LONG()` byte-order macros |
| `m_menu.c` | Full in-game menu system with item, slider, and list widgets |

---

### `w_` — WAD Virtual Filesystem

A WAD file begins with a 12-byte header (`wadinfo_t`) pointing to a flat directory of lumps (`filelump_t[]`).  `W_InitMultipleFiles` merges multiple WAD files into a unified lump table.  Lookups are by 8-character name (`W_GetNumForName`).  Loaded lumps are cached in the zone allocator under `PU_CACHE` so they are evicted transparently under memory pressure.

---

### `z_` — Zone Memory Allocator

A classic **tagged heap** with a doubly-linked free list.  Each allocation carries a purge tag:

| Tag | Meaning |
|---|---|
| `PU_STATIC` (1) | Permanent — never purged |
| `PU_LEVEL` (50) | Freed when the level exits |
| `PU_LEVSPEC` (51) | Level-specific thinker |
| `PU_CACHE` (101) | Purgeable — evicted by `Z_Malloc` on out-of-memory |

Cache entries store a back-pointer (`void**`) so that when a block is evicted, the caller's pointer is automatically NULLed.

---

### `s_` / `sndserv/` — Audio

`s_sound.c` maintains an array of sound channels.  When a sound is triggered it allocates a channel, looks up the lump number from `sounds.c`, and sends a request to `sndserv` via a Unix socket.  `sndserv` reads the raw 8-bit PCM from the WAD lump and writes it to `/dev/dsp`.  Music is handled similarly via OPL FM or a MIDI device.

---

## Core Data Structures at a Glance

| Structure | File | Purpose |
|---|---|---|
| `ticcmd_t` | `d_ticcmd.h` | One player's input for one tic; the unit of network exchange |
| `thinker_t` | `d_think.h` | Base class for all active objects; doubly-linked list node + function pointer |
| `mobj_t` | `p_mobj.h` | Map object / actor; extends `thinker_t` |
| `sector_t` | `r_defs.h` | Room-like convex region with floor/ceiling heights and lighting |
| `line_t` | `r_defs.h` | A wall segment (one or two-sided); triggers specials |
| `seg_t` | `r_defs.h` | A rendered portion of a `line_t` |
| `node_t` | `r_defs.h` | BSP tree node with partition line and child bounding boxes |
| `subsector_t` | `r_defs.h` | Convex BSP leaf; references a sector |
| `visplane_t` | `r_defs.h` | A floor/ceiling region at a constant height/texture/light |
| `vissprite_t` | `r_defs.h` | A sprite billboard clipped to screen columns |
| `state_t` | `info.h` | One frame in an actor's FSM; sprite + duration + action function |
| `mobjinfo_t` | `info.h` | Actor type definition (health, speed, flags, state table entries) |
| `memblock_t` | `z_zone.h` | Zone allocator heap block header |
| `lumpinfo_t` | `w_wad.h` | WAD lump directory entry (name, file handle, offset, size) |
| `doomcom_t` | `d_net.h` | Shared memory between DOOM and a network driver |
| `doomdata_t` | `d_net.h` | One UDP network packet (tic commands + checksum) |

---

## Build Instructions

```bash
cd linuxdoom-1.10
mkdir linux
make
# Produces: linux/linuxxdoom

# Build sound server separately
cd ../sndserv
make
# Produces: sndserv binary
```

Requirements: `gcc`, `libX11-dev`, `libXext-dev`.

Run with: `./linux/linuxxdoom -iwad /path/to/doom.wad`

---

## Notable Design Choices

| Decision | Rationale |
|---|---|
| Fixed-point math (16.16) | No FPU guarantee on 1993 hardware; ensures demo determinism |
| Deterministic RNG (lookup table) | Enables perfect demo playback and network lockstep |
| External sound server | Separates latency-sensitive audio from the game loop; portability |
| BSP pre-processing | Eliminates runtime visibility sorting; O(n) traversal per frame |
| Blockmap | O(1) broad-phase collision; 128×128 unit cells |
| Zone allocator with purge tags | Manual lifetime management without GC; evicts cached WAD data automatically |
| 8-bit palettised framebuffer | 64 KB screen buffer; palette tricks for lighting and translation |
