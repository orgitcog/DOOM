# DOOM Engine — Technical Architecture

> All diagrams use [Mermaid](https://mermaid.js.org/) syntax.  
> View in GitHub, VS Code with the Mermaid extension, or at [mermaid.live](https://mermaid.live).

---

## 1. Repository Structure

```mermaid
graph TD
    ROOT["DOOM/"]
    ROOT --> LD["linuxdoom-1.10/<br/>(game engine)"]
    ROOT --> SND["sndserv/<br/>(sound server)"]
    ROOT --> IPX["ipx/<br/>(DOS IPX driver)"]
    ROOT --> SER["sersrc/<br/>(DOS serial driver)"]
    ROOT --> README["README.TXT"]
    ROOT --> LICENSE["LICENSE.TXT"]

    LD --> MK["Makefile"]
    LD --> SRC["~90 .c/.h source files"]

    SND --> SC["soundsrv.c"]
    SND --> LC["linux.c (OSS /dev/dsp)"]
    SND --> WR["wadread.c"]
```

---

## 2. High-Level Subsystem Map

```mermaid
graph LR
    subgraph HAL ["Platform Layer (i_*)"]
        IV[i_video.c<br/>X11 display]
        IS[i_sound.c<br/>sndserv IPC]
        ISY[i_system.c<br/>clock / exit]
        IN[i_net.c<br/>UDP sockets]
        IM[i_main.c<br/>main()]
    end

    subgraph CORE ["Core Engine"]
        DM[d_main.c<br/>D_DoomMain / D_DoomLoop]
        GG[g_game.c<br/>game state machine]
        DN[d_net.c<br/>network lockstep]
    end

    subgraph RENDER ["Renderer (r_*)"]
        RM[r_main.c<br/>view setup]
        RB[r_bsp.c<br/>BSP traversal]
        RS[r_segs.c<br/>wall columns]
        RP[r_plane.c<br/>visplanes]
        RT[r_things.c<br/>sprites]
        RD[r_draw.c<br/>pixel writers]
        RDA[r_data.c<br/>texture cache]
    end

    subgraph PLAY ["Play Subsystem (p_*)"]
        PT[p_tick.c<br/>thinker list]
        PM[p_map.c<br/>collision]
        PO[p_mobj.c<br/>actors]
        PE[p_enemy.c<br/>monster AI]
        PU2[p_user.c<br/>player movement]
        PI[p_inter.c<br/>damage / pickup]
        PS[p_spec.c<br/>sector specials]
        PP[p_setup.c<br/>level load]
    end

    subgraph MEM ["Memory & Data"]
        ZZ[z_zone.c<br/>zone allocator]
        WW[w_wad.c<br/>WAD filesystem]
        INFO[info.c<br/>actor state tables]
        TAB[tables.c<br/>trig LUTs]
    end

    subgraph HUD ["HUD & UI"]
        ST[st_stuff.c<br/>status bar]
        HU[hu_stuff.c<br/>messages / chat]
        AM[am_map.c<br/>automap]
        MM[m_menu.c<br/>menus]
        WI[wi_stuff.c<br/>intermission]
        FF[f_finale.c<br/>finale]
    end

    subgraph AUDIO ["Audio"]
        SS[s_sound.c<br/>channel mixer]
        SRV[sndserv/<br/>sound server]
    end

    IM --> DM
    DM --> GG
    DM --> DN
    DM --> RENDER
    DM --> PLAY
    DM --> HUD
    DM --> AUDIO
    GG --> PLAY
    GG --> HUD

    RENDER --> MEM
    PLAY --> MEM
    AUDIO --> SS
    SS --> SRV
    SRV -->|OSS| DEV["/dev/dsp"]
    IV -->|framebuffer| X11["X11 window"]
    IN -->|UDP| NET["Network"]
```

---

## 3. Main Game Loop

```mermaid
sequenceDiagram
    participant OS as OS (i_main.c)
    participant DM as D_DoomMain
    participant NET as NetUpdate (d_net.c)
    participant GG as G_Ticker (g_game.c)
    participant PT as P_Ticker (p_tick.c)
    participant RND as R_RenderPlayerView
    participant HUD as HUD/ST draw
    participant IV as I_FinishUpdate (i_video.c)

    OS->>DM: main() → D_DoomMain()
    DM->>DM: Init all subsystems
    DM->>DM: W_InitMultipleFiles (load WADs)
    loop D_DoomLoop — 35 Hz
        DM->>NET: TryRunTics()
        NET->>NET: Build ticcmd_t from local input
        NET->>NET: Send/receive ticcmd_t packets
        NET->>GG: G_Ticker() [once per tic]
        GG->>PT: P_Ticker()
        PT->>PT: Walk thinker list, call each function
        PT-->>GG: return
        GG-->>NET: return
        NET-->>DM: return
        DM->>RND: R_RenderPlayerView()
        RND->>RND: r_bsp → r_segs → r_plane → r_things
        RND-->>DM: return
        DM->>HUD: ST_Drawer, HU_Drawer
        DM->>IV: I_FinishUpdate()
        IV->>IV: XPutImage to X11
    end
```

---

## 4. Game State Machine

```mermaid
stateDiagram-v2
    [*] --> GS_DEMOSCREEN : startup
    GS_DEMOSCREEN --> GS_LEVEL : G_DeferedInitNew / G_LoadGame
    GS_LEVEL --> GS_INTERMISSION : ExitLevel (special line trigger)
    GS_INTERMISSION --> GS_FINALE : last map in episode
    GS_INTERMISSION --> GS_LEVEL : WI_checkForAccelerate → next map
    GS_FINALE --> GS_DEMOSCREEN : F_Ticker completes
    GS_LEVEL --> GS_DEMOSCREEN : quit / demo end

    note right of GS_LEVEL
        P_Ticker runs every tic
        Renderer active
        HUD + StatusBar active
    end note
    note right of GS_INTERMISSION
        WI_Ticker
        Stats display
    end note
```

---

## 5. Renderer Pipeline (per frame)

```mermaid
flowchart TD
    A[R_RenderPlayerView] --> B[R_SetupFrame<br/>compute view angles & scale tables]
    B --> C[R_ClearClipSegs<br/>reset solidsegs array]
    C --> D[R_ClearDrawSegs<br/>reset drawsegs]
    D --> E[R_ClearPlanes<br/>reset visplanes]
    E --> F[R_ClearSprites<br/>reset vissprites]
    F --> G[R_RenderBSPNode<br/>BSP front-to-back traversal]

    G --> H{leaf node?}
    H -- yes --> I[R_Subsector<br/>add segs to drawsegs<br/>add planes to visplanes]
    H -- no --> G

    I --> J[R_DrawPlanes<br/>render all visplanes<br/>horizontal span drawing]
    J --> K[R_DrawMasked<br/>draw sprites & masked textures<br/>sorted back-to-front]
    K --> L[framebuffer complete]

    style A fill:#2d6a9f,color:#fff
    style L fill:#2d9f5a,color:#fff
```

---

## 6. BSP Tree Structure

```mermaid
graph TD
    subgraph WAD ["WAD Lumps (loaded by p_setup.c)"]
        VERTEXES --> MAP
        LINEDEFS --> MAP
        SIDEDEFS --> MAP
        SECTORS --> MAP
        SEGS --> MAP
        SSECTORS --> MAP
        NODES --> MAP
        THINGS --> MAP
        MAP["runtime map arrays"]
    end

    subgraph BSP ["BSP Tree (node_t)"]
        N0["node_t<br/>partition line<br/>left bbox | right bbox"]
        N0 --> N1["node_t (left)"]
        N0 --> N2["node_t (right)"]
        N1 --> SS1["subsector_t<br/>(NF_SUBSECTOR flag)"]
        N1 --> N3["node_t"]
        N2 --> SS2["subsector_t"]
        N2 --> SS3["subsector_t"]
        N3 --> SS4["subsector_t"]
        N3 --> SS5["subsector_t"]
    end

    SS1 --> S1["sector_t<br/>floor/ceiling height<br/>light level<br/>mobj list"]
    SS2 --> S1
    SS3 --> S2["sector_t"]

    MAP --> BSP
```

---

## 7. Actor (mobj_t) Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Spawn : P_SpawnMobj()
    Spawn --> Active : thinker linked into list
    Active --> Active : P_MobjThinker() each tic\nadvance FSM state\napply momentum\ncheck collisions

    Active --> Pain : take damage < threshold
    Pain --> Active : pain state expires

    Active --> Dead : health ≤ 0\nP_KillMobj()
    Dead --> Corpse : death animation plays
    Corpse --> [*] : P_RemoveMobj()\nunlinked from thinker list\nunlinked from sector & blockmap

    note right of Active
        state_t* drives sprite frame
        action function called each state
        e.g. A_Chase, A_PosAttack
    end note
```

---

## 8. Thinker System

```mermaid
graph LR
    subgraph ThinkerList ["Thinker Doubly-Linked List (thinkercap)"]
        CAP["thinkercap\n(sentinel)"] <-->|prev/next| T1
        T1["thinker_t\n(mobj_t: player)"] <-->|prev/next| T2
        T2["thinker_t\n(mobj_t: imp)"] <-->|prev/next| T3
        T3["thinker_t\n(floormove_t)"] <-->|prev/next| T4
        T4["thinker_t\n(vldoor_t)"] <-->|prev/next| CAP
    end

    PT["P_Ticker()"] -->|iterates| ThinkerList
    T1 -->|function ptr| F1["P_MobjThinker"]
    T2 -->|function ptr| F2["P_MobjThinker"]
    T3 -->|function ptr| F3["T_MoveFloor"]
    T4 -->|function ptr| F4["T_VerticalDoor"]
```

---

## 9. WAD Filesystem

```mermaid
graph TD
    subgraph WAD_FILE ["doom.wad (binary file)"]
        HDR["Header\nidentification[4] = 'IWAD'\nnumlumps\ninfotableofs"]
        DIR["Lump Directory\nfilelump_t[numlumps]\n  filepos | size | name[8]"]
        L1["PLAYPAL lump\n(14×256 palette entries)"]
        L2["E1M1 map marker"]
        L3["THINGS lump"]
        L4["LINEDEFS lump"]
        L5["TEXTURE1 lump"]
        L6["FLAT lump..."]
        LN["... N lumps total"]
    end

    HDR -->|infotableofs| DIR
    DIR --> L1
    DIR --> L2
    DIR --> L3
    DIR --> L4
    DIR --> L5
    DIR --> L6
    DIR --> LN

    W_WAD["w_wad.c\nW_InitMultipleFiles()\nW_GetNumForName()\nW_CacheLumpNum()"]
    ZZ["z_zone.c\nlumpcache[]"]

    W_WAD -->|fills| ZZ
    W_WAD -->|reads| WAD_FILE
```

---

## 10. Zone Memory Allocator

```mermaid
graph LR
    subgraph HEAP ["Zone Heap (mainzone)"]
        MB0["memblock_t\nPU_STATIC\nsize | user | tag | id\nnext → | ← prev"]
        MB1["memblock_t\nPU_LEVEL\n(level geometry)"]
        MB2["memblock_t\nPU_CACHE\n(WAD lump)\nuser = &lumpcache[n]"]
        MB3["memblock_t\nFREE\nuser = NULL"]
        MB4["memblock_t\nPU_CACHE\n(texture)"]
        MB0 <-->|linked list| MB1
        MB1 <-->|linked list| MB2
        MB2 <-->|linked list| MB3
        MB3 <-->|linked list| MB4
    end

    ZM["Z_Malloc(size, tag, &ptr)"]
    ZM -->|tag < 100: never evict| MB0
    ZM -->|tag >= 100: evict if OOM| MB2
    ZM -->|on evict: *user = NULL| MB2
```

---

## 11. Network Lockstep Protocol

```mermaid
sequenceDiagram
    participant P1 as Player 1 node
    participant P2 as Player 2 node
    participant P3 as Player 3 node

    Note over P1,P3: Each tic (1/35 s)

    P1->>P1: Sample keyboard/mouse → ticcmd_t[tic N]
    P2->>P2: Sample keyboard/mouse → ticcmd_t[tic N]
    P3->>P3: Sample keyboard/mouse → ticcmd_t[tic N]

    P1->>P2: doomdata_t {starttic=N, cmds[...]}
    P1->>P3: doomdata_t
    P2->>P1: doomdata_t
    P2->>P3: doomdata_t
    P3->>P1: doomdata_t
    P3->>P2: doomdata_t

    Note over P1,P3: TryRunTics() blocks until all cmds[N] received

    P1->>P1: G_Ticker(ticcmd[P1,N], ticcmd[P2,N], ticcmd[P3,N])
    P2->>P2: G_Ticker(ticcmd[P1,N], ticcmd[P2,N], ticcmd[P3,N])
    P3->>P3: G_Ticker(ticcmd[P1,N], ticcmd[P2,N], ticcmd[P3,N])

    Note over P1,P3: All nodes run identical simulation → identical state
```

---

## 12. Sound Architecture

```mermaid
graph TD
    subgraph GAME ["Game Process"]
        SS["s_sound.c\nS_StartSound(mobj, sfx_id)"]
        IC["i_sound.c\nI_StartSound()"]
        SOCK["Unix socket / pipe"]
    end

    subgraph SNDSERV ["sndserv process"]
        SL["soundsrv.c\nmain loop"]
        WR["wadread.c\nread PCM from WAD"]
        LX["linux.c\nwrite to /dev/dsp"]
    end

    SS -->|channel alloc| IC
    IC -->|send sound request| SOCK
    SOCK -->|IPC| SL
    SL -->|lump lookup| WR
    WR -->|8-bit PCM| LX
    LX -->|OSS write| DSP["/dev/dsp\n(hardware)"]
```

---

## 13. Key Data Structure Relationships

```mermaid
erDiagram
    mobj_t {
        thinker_t thinker
        fixed_t x
        fixed_t y
        fixed_t z
        fixed_t momx
        fixed_t momy
        fixed_t momz
        mobjtype_t type
        state_t state
        int flags
        int health
        mobj_t target
        mobj_t tracer
    }
    thinker_t {
        thinker_t prev
        thinker_t next
        think_t function
    }
    sector_t {
        fixed_t floorheight
        fixed_t ceilingheight
        short lightlevel
        short special
        mobj_t thinglist
        line_t lines
    }
    line_t {
        vertex_t v1
        vertex_t v2
        short flags
        short special
        side_t sidenum
        sector_t frontsector
        sector_t backsector
    }
    subsector_t {
        sector_t sector
        short numlines
        short firstline
    }
    node_t {
        fixed_t x
        fixed_t y
        fixed_t dx
        fixed_t dy
        fixed_t bbox
        unsigned children
    }
    state_t {
        spritenum_t sprite
        int frame
        int tics
        actionf_t action
        statenum_t nextstate
    }
    mobjinfo_t {
        int doomednum
        int spawnstate
        int spawnhealth
        int speed
        int radius
        int height
        int flags
    }

    mobj_t ||--|| thinker_t : "embeds (first field)"
    mobj_t }o--|| sector_t : "linked via snext/sprev"
    mobj_t }o--|| state_t : "current state"
    mobj_t }o--|| mobjinfo_t : "type info"
    sector_t ||--o{ line_t : "lines[]"
    line_t ||--|| sector_t : "frontsector"
    line_t ||--o| sector_t : "backsector (2-sided)"
    subsector_t }o--|| sector_t : "sector"
    node_t ||--o| node_t : "children (or subsector)"
    node_t ||--o| subsector_t : "children (leaf)"
    state_t ||--o| state_t : "nextstate"
```

---

## 14. Fixed-Point Arithmetic

```mermaid
graph LR
    subgraph FP16 ["fixed_t (32-bit int)"]
        HI["bits 31..16\ninteger part"]
        LO["bits 15..0\nfractional part"]
    end

    HI ---|"×65536 = FRACUNIT"| LO

    MUL["FixedMul(a,b)\n= (long long)a * b >> 16"]
    DIV["FixedDiv(a,b)\n= (long long)a << 16 / b\n(with overflow guard)"]
    UNIT["FRACUNIT = 1<<16 = 65536\n≡ 1.0"]

    FP16 --> MUL
    FP16 --> DIV
    FP16 --> UNIT
```

All world coordinates, scales, and trigonometric values use `fixed_t`.  The angle type `angle_t` is a 32-bit **Binary Angle Measurement** (BAM): `0x40000000` = 90°.  Sine/cosine are pre-computed into `finesine[]` / `finecosine[]` tables (8192 entries) in `tables.c`.

---

## 15. Sprite & Texture Pipeline

```mermaid
flowchart LR
    WAD["WAD lump\n(patch_t format)"] --> RC["R_InitSprites()\nR_InitTextures()\nr_data.c"]
    RC --> SD["spritedef_t[]\nnumframes\nspriteframe_t[]"]
    RC --> TEX["texture_t[]\npatch columns\ncomposited on demand"]

    SD --> RT["R_Things\nR_ProjectSprite\nbuild vissprite_t"]
    TEX --> RS["R_Segs\nR_RenderSegLoop\ndraw wall columns"]

    RT --> RD["R_DrawSprite\nR_DrawColumn\n(r_draw.c)"]
    RS --> RD
    RD --> FB["8-bit framebuffer\n(screens[0])"]
    FB --> IV["I_FinishUpdate\nXPutImage"]
```

---

## 16. Component Dependency Graph

```mermaid
graph BT
    ZZ[z_zone] --> WW[w_wad]
    ZZ --> PP[p_setup]
    WW --> PP
    WW --> RD2[r_data]
    WW --> SS2[s_sound]

    TAB[tables] --> RM[r_main]
    MFX[m_fixed] --> RM

    PP --> PT[p_tick]
    PP --> RM

    PT --> PE[p_enemy]
    PT --> PM[p_map]
    PT --> PS[p_spec]

    RM --> RB[r_bsp]
    RD2 --> RB
    RB --> RS[r_segs]
    RB --> RP[r_plane]
    RS --> RDRAW[r_draw]
    RP --> RDRAW
    RT[r_things] --> RDRAW

    GG[g_game] --> PT
    GG --> WI[wi_stuff]
    GG --> FF[f_finale]

    DM[d_main] --> GG
    DM --> RM
    DM --> SS2
    DM --> IV[i_video]

    DN[d_net] --> DM
    IN2[i_net] --> DN
```
