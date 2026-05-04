# DOOM Engine — Formal Specification in Z++

> **Z++** extends classical Z notation with object-oriented constructs (classes, inheritance, methods).  
> This document specifies the core abstract machine of the DOOM engine.  
> Mathematical symbols are rendered in standard Unicode; a LaTeX rendering tool is recommended for print.

---

## Notation Conventions

| Symbol | Meaning |
|---|---|
| `ℤ` | Integers |
| `ℕ` | Natural numbers (ℤ≥0) |
| `𝔹` | Booleans {true, false} |
| `ℙ X` | Power set of X |
| `X ⇸ Y` | Partial function from X to Y |
| `X → Y` | Total function from X to Y |
| `seq X` | Finite sequence of X |
| `#s` | Length of sequence s |
| `dom f` | Domain of function f |
| `ran f` | Range of function f |
| `⊕` | Function overriding |
| `⟨x, y⟩` | Ordered pair |
| `{x : T | P}` | Set comprehension |
| `∀ x : T • P` | Universal quantification |
| `∃ x : T • P` | Existential quantification |
| `pre Op` | Precondition of operation Op |
| `[S]` | State schema reference |

---

## Part I — Primitive Types and Domains

### 1.1 Basic Types

```
FIXED   == ℤ                      -- 16.16 fixed-point integer (32-bit)
ANGLE   == ℤ                      -- Binary Angle Measurement (32-bit)
BYTE    == 0..255
LUMPNUM == ℕ
LUMPNAME == seq₁ BYTE             -- up to 8 characters
MOBJTYPE ::= MT_PLAYER | MT_POSSESSED | MT_SHOTGUY | MT_VILE
           | MT_UNDEAD | MT_FATSO | MT_CHAINGUY | MT_TROOP
           | MT_SERGEANT | MT_HEAD | MT_BOSS | MT_SPIDER
           | MT_CACODEMON | MT_BRUISER | MT_SKULL | MT_BARREL
           | MT_ROCKET | MT_PLASMA | MT_BFG | MT_MISC_ITEM  -- ... etc.
SKILL   ::= sk_baby | sk_easy | sk_medium | sk_hard | sk_nightmare
GAMEMODE ::= shareware | registered | commercial | retail | indetermined
GAMESTATE ::= GS_LEVEL | GS_INTERMISSION | GS_FINALE | GS_DEMOSCREEN
TAG     == ℕ                      -- memory purge tag
```

### 1.2 Fixed-Point Constants

```
FRACBITS  : ℕ  ==  16
FRACUNIT  : FIXED  ==  2^FRACBITS          -- represents 1.0
MAPFRAC   : FIXED  ==  FRACUNIT            -- 1 world unit

-- Arithmetic
FixedMul : FIXED × FIXED → FIXED
FixedMul(a, b) == (a * b) / FRACUNIT       -- truncated toward zero

FixedDiv : FIXED × FIXED ⇸ FIXED
pre FixedDiv(a, b) == b ≠ 0
FixedDiv(a, b) == (a * FRACUNIT) / b
```

### 1.3 Angle Arithmetic

```
-- Full circle = 2^32 BAM units
ANG45  : ANGLE == 0x20000000
ANG90  : ANGLE == 0x40000000
ANG180 : ANGLE == 0x80000000

FINEANGLES : ℕ == 8192
FINEMASK   : ℕ == FINEANGLES - 1

finesine    : (0 .. FINEANGLES + FINEANGLES/4 - 1) → FIXED
finecosine  : (0 .. FINEANGLES - 1) → FIXED

-- finecosine is finesine shifted by FINEANGLES/4
AngleSine(a : ANGLE) : FIXED ==
    finesine( (a >> (32 - 13)) & FINEMASK )

AngleCosine(a : ANGLE) : FIXED ==
    finecosine( (a >> (32 - 13)) & FINEMASK )
```

---

## Part II — Zone Memory Allocator

### 2.1 Memory Block

```
class MemBlock
  size    : ℕ₁          -- bytes, including header
  tag     : TAG
  user    : ℕ ⇸ ℕ       -- optional back-pointer (address → address)
  id      : ℕ           -- must equal ZONEID (0x1d4a11) when allocated
  content : seq BYTE    -- payload, #content = size - sizeof(header)

PU_STATIC    : TAG == 1
PU_SOUND     : TAG == 2
PU_MUSIC     : TAG == 3
PU_LEVEL     : TAG == 50
PU_LEVSPEC   : TAG == 51
PU_PURGELEVEL: TAG == 100
PU_CACHE     : TAG == 101

IsPurgeable(b : MemBlock) : 𝔹 == b.tag ≥ PU_PURGELEVEL
IsFree(b : MemBlock)      : 𝔹 == b.user = ∅ ∧ b.tag = 0
```

### 2.2 Zone Heap

```
class ZoneHeap
  blocks : seq MemBlock             -- doubly-linked list modelled as sequence
  size   : ℕ₁                       -- total heap size in bytes

  invariant
    -- blocks cover the full heap without gaps
    (∀ i : 1..#blocks • blocks(i).size > 0) ∧
    (Σ b : ran blocks • b.size) = size ∧
    -- ZONEID correct on all allocated blocks
    (∀ i : 1..#blocks • ¬IsFree(blocks(i)) ⇒ blocks(i).id = 0x1d4a11)
```

### 2.3 Z_Malloc

```
Z_Malloc ──────────────────────────────────────────
  ΔZoneHeap
  reqsize? : ℕ₁
  tag?     : TAG
  ptr?     : ℕ ⇸ ℕ           -- optional back-pointer slot
  result!  : ℕ                -- address of allocated block

pre Z_Malloc ==
  reqsize? > 0 ∧ tag? ≥ PU_STATIC

post Z_Malloc ==
  -- A block of at least reqsize? bytes exists in updated heap
  ∃ b : ran blocks' •
    b.size ≥ reqsize? ∧ b.tag = tag? ∧ b.id = 0x1d4a11
    ∧ (ptr? ≠ ∅ ⇒ b.user = ptr?)
    ∧ result! = address(b.content)

-- If no free block large enough, purgeable blocks are evicted first:
evict ──────────────────────────────────────
  ΔZoneHeap
  needed? : ℕ₁
  -- Nulls back-pointers for evicted cache blocks
  ∀ b : ran blocks | IsPurgeable(b) ∧ FreeableFor(b, needed?) •
    (b.user ≠ ∅ ⇒ *(b.user) := 0) ∧ b.tag := 0
```

### 2.4 Z_FreeTags

```
Z_FreeTags ──────────────────────────────────────────
  ΔZoneHeap
  lowtag?  : TAG
  hightag? : TAG
pre  lowtag? ≤ hightag?
post blocks' = { b : ran blocks | b.tag < lowtag? ∨ b.tag > hightag? }
```

---

## Part III — WAD Filesystem

### 3.1 WAD File

```
class WadHeader
  identification : seq BYTE   -- "IWAD" or "PWAD"
  numlumps       : ℕ
  infotableofs   : ℕ          -- byte offset to directory

class FileLump
  filepos : ℕ
  size    : ℕ
  name    : seq BYTE          -- padded to 8 bytes, NUL-terminated

class LumpInfo
  name     : LUMPNAME
  handle   : ℕ                -- file descriptor
  position : ℕ                -- byte offset within file
  size     : ℕ
```

### 3.2 WAD System State

```
class WadSystem
  lumpinfo  : seq LumpInfo     -- merged directory across all loaded WADs
  lumpcache : LUMPNUM ⇸ ℕ     -- lump number → heap address (or ∅)
  numlumps  : ℕ

  invariant
    numlumps = #lumpinfo ∧
    dom lumpcache ⊆ 0..numlumps - 1
```

### 3.3 Lump Access Operations

```
W_GetNumForName ─────────────────────────────────
  ΞWadSystem                   -- read-only
  name? : LUMPNAME
  result! : LUMPNUM
pre  ∃ i : dom lumpinfo • lumpinfo(i).name = name?
post result! = max { i : dom lumpinfo | lumpinfo(i).name = name? }
     -- highest index wins (PWAD override semantics)

W_CacheLumpNum ──────────────────────────────────
  ΔWadSystem, ΔZoneHeap
  lump? : LUMPNUM
  tag?  : TAG
  result! : ℕ                  -- pointer to lump data in heap

pre  lump? ∈ dom lumpinfo

post
  -- If already cached, return existing pointer
  (lump? ∈ dom lumpcache ⇒
      result! = lumpcache(lump?) ∧ WadSystem' = WadSystem)
  ∧
  -- If not cached, allocate zone block and read file
  (lump? ∉ dom lumpcache ⇒
      ∃ addr : ℕ •
        Z_Malloc(lumpinfo(lump?).size, tag?, addr_of(lumpcache(lump?)))
        ∧ ReadFile(lumpinfo(lump?), addr)
        ∧ lumpcache' = lumpcache ⊕ {lump? ↦ addr}
        ∧ result! = addr)
```

---

## Part IV — Map Geometry

### 4.1 Vertex and Line

```
class Vertex
  x : FIXED
  y : FIXED

class SideDef
  textureoffset : FIXED
  rowoffset     : FIXED
  toptexture    : ℕ         -- index into texture table
  midtexture    : ℕ
  bottomtexture : ℕ
  sector        : Sector

class LineDef
  v1         : Vertex
  v2         : Vertex
  dx         : FIXED  == v2.x - v1.x
  dy         : FIXED  == v2.y - v1.y
  flags      : ℕ
  special    : ℕ
  tag        : ℕ
  sides      : seq SideDef   -- #sides ∈ {1, 2}
  frontsector : Sector
  backsector  : Sector ⇸ Sector   -- ∅ if one-sided

  invariant
    (#sides = 1 ⇒ backsector = ∅) ∧
    (#sides = 2 ⇒ backsector ≠ ∅)
```

### 4.2 Sector

```
class Sector
  floorheight   : FIXED
  ceilingheight : FIXED
  floorpic      : ℕ           -- flat lump index
  ceilingpic    : ℕ
  lightlevel    : 0..255
  special       : ℕ
  tag           : ℕ
  thinglist     : seq MapObj  -- linked list of mobjs in sector
  lines         : seq LineDef

  invariant
    floorheight ≤ ceilingheight ∧
    lightlevel ∈ 0..255
```

### 4.3 BSP Tree

```
NF_SUBSECTOR : ℕ == 0x8000   -- high bit marks subsector child

class SubSector
  sector    : Sector
  numlines  : ℕ
  firstline : ℕ               -- index into segs array

class BspNode
  x, y, dx, dy : FIXED        -- partition line
  rightbox      : FIXED × FIXED × FIXED × FIXED  -- TBLR bounding box
  leftbox       : FIXED × FIXED × FIXED × FIXED
  rightchild    : ℕ            -- index; if NF_SUBSECTOR bit set → subsector
  leftchild     : ℕ

-- Recursive visitor type
BspChild ::= SubSectorLeaf ⟪SubSector⟫ | NodeBranch ⟪BspNode⟫

ChildOf(n : BspNode, side : {left, right}) : BspChild ==
  let c == if side = right then n.rightchild else n.leftchild
  in  if c & NF_SUBSECTOR ≠ 0
      then SubSectorLeaf(subsectors(c & ¬NF_SUBSECTOR))
      else NodeBranch(nodes(c))
```

---

## Part V — Thinker and Map Object

### 5.1 Thinker

```
class Thinker
  function : (Thinker → 𝔹)    -- action function; returns false to request removal

class ThinkerList
  head : seq Thinker           -- modelled as ordered sequence; runtime is circular DLL

  Tick(list : ThinkerList) : ThinkerList ==
    { t : ran list.head | list.head(t).function(t) = true }
    -- thinkers returning false are removed
```

### 5.2 Actor Flags (mobjflag_t)

```
MF_SPECIAL    : ℕ == 0x000001   -- calls P_SpecialThing on touch
MF_SOLID      : ℕ == 0x000002   -- blocks movement
MF_SHOOTABLE  : ℕ == 0x000004   -- can take damage
MF_NOSECTOR   : ℕ == 0x000008   -- not linked in sector list
MF_NOBLOCKMAP : ℕ == 0x000010   -- not linked in blockmap
MF_AMBUSH     : ℕ == 0x000020   -- deaf monster
MF_NOGRAVITY  : ℕ == 0x000200   -- floats (cacodemons, etc.)
MF_FLOAT      : ℕ == 0x004000   -- active floater, adjusts z
MF_MISSILE    : ℕ == 0x010000   -- projectile
MF_SHADOW     : ℕ == 0x040000   -- spectre fuzz rendering
MF_CORPSE     : ℕ == 0x100000   -- slides off ledges
MF_COUNTKILL  : ℕ == 0x400000   -- counts toward kill total
MF_COUNTITEM  : ℕ == 0x800000   -- counts toward item total
MF_NOTDMATCH  : ℕ == 0x2000000  -- not spawned in deathmatch
```

### 5.3 FSM State

```
class State
  sprite    : ℕ                    -- sprite number
  frame     : ℕ                    -- frame index (may have FF_FULLBRIGHT)
  tics      : ℤ                    -- duration; -1 means hold forever
  action    : (MapObj → Unit) ⇸ (MapObj → Unit)   -- optional action function
  nextstate : ℕ                    -- index into states table; S_NULL = 0 → remove
```

### 5.4 MapObj (mobj_t)

```
class MapObj extends Thinker
  -- Position and momentum (all FIXED)
  x, y, z       : FIXED
  momx, momy, momz : FIXED

  -- Orientation
  angle         : ANGLE

  -- Physical dimensions
  radius        : FIXED
  height        : FIXED

  -- Sector geometry contact
  floorz        : FIXED
  ceilingz      : FIXED

  -- Visual
  sprite        : ℕ
  frame         : ℕ

  -- Type info
  type          : MOBJTYPE
  info          : MobjInfo          -- pointer to mobjinfo[type]

  -- Finite state machine
  state         : State
  tics          : ℤ                 -- remaining tics in current state

  -- Flags and health
  flags         : ℕ
  health        : ℤ

  -- AI
  movedir       : 0..7
  movecount     : ℕ
  target        : MapObj ⇸ MapObj   -- chase/attack target; ∅ if none
  reactiontime  : ℕ
  threshold     : ℕ

  -- Player link
  player        : Player ⇸ Player   -- ∅ if not a player avatar

  invariant
    (flags & MF_SOLID ≠ 0 ∧ flags & MF_MISSILE = 0 ⇒ radius > 0 ∧ height > 0) ∧
    (health ≤ 0 ⇒ flags & MF_SHOOTABLE = 0) ∧
    floorz ≤ z ∧ z + height ≤ ceilingz + height   -- relaxed for missiles
```

### 5.5 MapObj Operations

```
-- Advance FSM by one tic
P_MobjThinker ────────────────────────────────────
  ΔMapObj
  pre  tics ≠ -1 ∨ state.action ≠ ∅
  post
    -- Decrement tic counter
    tics' = tics - 1 ∧
    -- If tics expired, advance to next state
    (tics' < 0 ⇒ state' = states(state.nextstate) ∧ tics' = state'.tics) ∧
    -- Call action function if present
    (state.action ≠ ∅ ⇒ state.action(this)) ∧
    -- Apply momentum
    x' = x + momx ∧ y' = y + momy ∧ z' = z + momz

-- Apply damage
P_DamageMobj ─────────────────────────────────────
  ΔMapObj
  damage? : ℕ₁
  inflictor? : MapObj
  source? : MapObj
  pre  flags & MF_SHOOTABLE ≠ 0
  post
    health' = health - damage? ∧
    (health' ≤ 0 ⇒ P_KillMobj(this, source?))
```

---

## Part VI — Player

### 6.1 Weapon State

```
WEAPON ::= wp_fist | wp_pistol | wp_shotgun | wp_chaingun
         | wp_missile | wp_plasma | wp_bfg | wp_chainsaw
         | wp_supershotgun

AMMO   ::= am_clip | am_shell | am_cell | am_misl | am_noammo

class WeaponInfo
  ammo       : AMMO
  upstate    : ℕ
  downstate  : ℕ
  readystate : ℕ
  atkstate   : ℕ
  flashstate : ℕ
```

### 6.2 Player

```
MAXHEALTH : ℕ == 100
MAXARMOR  : ℕ == 200

class Player
  mo        : MapObj              -- body in the world
  health    : ℤ                   -- may be > MAXHEALTH (soulsphere)
  armortype : 0..2               -- 0=none, 1=green, 2=blue
  armorpoints : 0..MAXARMOR

  -- Inventory
  readyweapon   : WEAPON
  pendingweapon : WEAPON ⇸ WEAPON  -- ∅ if no change requested
  weaponowned   : WEAPON ⇸ 𝔹
  ammo          : AMMO → ℕ
  maxammo       : AMMO → ℕ

  -- Power-ups (tics remaining; 0 = inactive)
  powers        : ℕ → ℕ           -- indexed by pw_* constants

  -- View
  viewz         : FIXED            -- eye height = mo.z + viewheight
  viewheight    : FIXED
  deltaviewheight : FIXED
  bob           : FIXED

  -- Status
  damagecount   : ℕ               -- red pain flash tics
  bonuscount    : ℕ               -- yellow bonus flash tics
  attackdown    : 𝔹
  usedown       : 𝔹

  invariant
    health ≤ 200 ∧
    armorpoints ≤ MAXARMOR ∧
    (∀ a : AMMO • ammo(a) ≤ maxammo(a)) ∧
    weaponowned(readyweapon) = true ∧
    viewheight > 0
```

### 6.3 Tic Command

```
class TicCmd
  forwardmove : -50..50     -- *2048 = fixed velocity
  sidemove    : -50..50
  angleturn   : ℤ           -- <<16 for angle delta
  buttons     : BYTE        -- BT_ATTACK | BT_USE | BT_CHANGE | BT_SPECIAL
  chatchar    : BYTE
  consistancy : ℕ           -- CRC for net game integrity check

-- Button constants
BT_ATTACK  : ℕ == 1
BT_USE     : ℕ == 2
BT_CHANGE  : ℕ == 4        -- weapon change
BT_SPECIAL : ℕ == 128
```

---

## Part VII — Renderer

### 7.1 View Parameters

```
class ViewParams
  x, y, z   : FIXED          -- camera position
  angle     : ANGLE           -- yaw
  cos, sin  : FIXED           -- derived from angle

  -- Screen geometry
  width     : ℕ₁              -- SCREENWIDTH
  height    : ℕ₁              -- SCREENHEIGHT
  centerx   : ℕ               -- width / 2
  centery   : ℕ               -- height / 2 (+ bobbing)
  projection: FIXED           -- centerx * FRACUNIT (90° FOV)

  -- Scale tables (per column x ∈ 0..width-1)
  distscale : ℕ → FIXED       -- per-column cos correction

  invariant
    centerx = width / 2 ∧
    ∀ x : 0..width-1 •
      distscale(x) = FixedDiv(projection,
                       FixedMul(projection, cos) - FixedMul(x - centerx, sin))
```

### 7.2 Visplane

```
class Visplane
  height     : FIXED
  picnum     : ℕ              -- flat lump index
  lightlevel : 0..255
  minx, maxx : ℕ
  top        : ℕ → BYTE      -- per-column top clip (SCREENWIDTH entries)
  bottom     : ℕ → BYTE      -- per-column bottom clip

  invariant
    minx ≤ maxx ∧
    ∀ x : minx..maxx • top(x) ≤ bottom(x)
```

### 7.3 Renderer Invariant

```
RenderInvariant ──────────────────────────────────
  -- After R_RenderPlayerView completes:

  -- 1. Every pixel column is covered by at most one wall or sky
  ∀ x : 0..SCREENWIDTH-1 •
    #{ s : drawsegs | s.x1 ≤ x ≤ s.x2 ∧ IsSolid(s) } ≤ 1

  -- 2. Visplanes do not overlap within the same column for same height
  ∀ p1, p2 : visplanes | p1 ≠ p2 ∧ p1.height = p2.height ∧ p1.picnum = p2.picnum •
    ∀ x : (p1.minx .. p1.maxx) ∩ (p2.minx .. p2.maxx) •
      p1.top(x) > p2.bottom(x) ∨ p2.top(x) > p1.bottom(x)

  -- 3. All sprites are drawn in back-to-front (painter's algorithm) order
  ∀ i, j : 1..#vissprites | i < j •
    vissprites(i).scale ≤ vissprites(j).scale   -- closer = larger scale
```

---

## Part VIII — Network Protocol

### 8.1 DoomCom Structure

```
MAXNETNODES : ℕ == 8
BACKUPTICS  : ℕ == 12

class DoomData
  checksum      : ℕ          -- high bit = retransmit request
  retransmitfrom : BYTE
  starttic      : BYTE
  player        : BYTE
  numtics       : BYTE
  cmds          : 1..BACKUPTICS → TicCmd

class DoomCom
  id            : ℕ           -- must equal DOOMCOM_ID = 0x12345678
  intnum        : ℕ           -- DOS interrupt number (unused on Linux)
  command       : {CMD_SEND, CMD_GET}
  remotenode    : ℤ           -- -1 = no packet
  datalength    : ℕ
  numnodes      : 1..MAXNETNODES
  ticdup        : ℕ
  deathmatch    : 𝔹
  savegame      : ℤ           -- -1 = new game, 0..5 = load slot
  episode       : 1..3
  map           : 1..9
  skill         : SKILL
  consoleplayer : 0..3
  numplayers    : 1..4
  data          : DoomData
```

### 8.2 Network State

```
class NetState
  maketic      : ℕ            -- next tic number to build
  gametic      : ℕ            -- last tic executed
  nettics      : 0..MAXNETNODES-1 → ℕ  -- highest tic received from each node
  netcmds      : (0..3) × (0..BACKUPTICS-1) → TicCmd

  invariant
    gametic ≤ maketic ∧
    ∀ n : 0..doomcom.numnodes-1 • nettics(n) ≥ gametic
    -- all nodes must have sent tics up to gametic
```

### 8.3 NetUpdate

```
NetUpdate ───────────────────────────────────────
  ΔNetState
  newcmd?  : TicCmd        -- this player's current input

  post
    -- Record local command
    netcmds'(consoleplayer, maketic mod BACKUPTICS) = newcmd? ∧
    maketic' = maketic + 1 ∧
    -- Broadcast to all peers
    ∀ node : 0..numnodes-1 | node ≠ consoleplayer •
      Send(node, doomdata(maketic, consoleplayer, newcmd?))

TryRunTics ──────────────────────────────────────
  ΔNetState
  -- Can advance if all nodes have delivered tic 'gametic'
  pre  ∀ n : 0..numnodes-1 • nettics(n) ≥ gametic
  post gametic' = gametic + 1 ∧ G_Ticker(netcmds(_, gametic))
```

---

## Part IX — Game State Machine

### 9.1 Game State

```
class GameState
  state      : GAMESTATE
  episode    : 1..3
  map        : 1..9
  skill      : SKILL
  tic        : ℕ              -- gametic
  players    : 0..3 → Player
  numplayers : 1..4
  deathmatch : 𝔹

  -- Level state (valid only when state = GS_LEVEL)
  level      : LevelState ⇸ LevelState

  invariant
    (state ≠ GS_LEVEL ⇒ level = ∅) ∧
    (state = GS_LEVEL ⇒ level ≠ ∅) ∧
    ∀ i : 0..numplayers-1 • players(i).health > -50
    -- player is "dead" at 0 but body persists; -50 triggers respawn in NM
```

### 9.2 State Transitions

```
G_DeferedInitNew ────────────────────────────────
  ΔGameState
  skill?   : SKILL
  episode? : 1..3
  map?     : 1..9
  post
    state' = GS_LEVEL ∧
    skill' = skill? ∧ episode' = episode? ∧ map' = map? ∧
    level' = LoadLevel(episode?, map?)

ExitLevel ───────────────────────────────────────
  ΔGameState
  pre  state = GS_LEVEL
  post
    (IsLastMapInEpisode(episode, map) ⇒ state' = GS_FINALE) ∧
    (¬IsLastMapInEpisode(episode, map) ⇒ state' = GS_INTERMISSION ∧
        map' = map + 1)

G_Ticker ────────────────────────────────────────
  ΔGameState
  cmds? : 0..numplayers-1 → TicCmd
  pre  state = GS_LEVEL
  post
    tic' = tic + 1 ∧
    -- Process player commands
    (∀ i : 0..numplayers-1 • G_BuildTiccmd(players'(i), cmds?(i))) ∧
    -- Advance physics
    P_Ticker(level') ∧
    -- Advance HUD
    ST_Ticker ∧ HU_Ticker ∧ AM_Ticker
```

---

## Part X — System-Level Properties

### 10.1 Determinism

```
Determinism ─────────────────────────────────────
  -- Theorem: given identical initial state and identical ticcmd sequences,
  -- all nodes produce identical GameState at every tic.

  ∀ g₁, g₂ : GameState | g₁ = g₂ •
  ∀ cmds : seq (0..numplayers-1 → TicCmd) •
  ∀ n : ℕ •
    ApplyTics(g₁, cmds, n) = ApplyTics(g₂, cmds, n)

  -- This holds because:
  -- (a) All arithmetic uses fixed_t (no FPU)
  -- (b) P_Random() advances a shared deterministic RNG index
  -- (c) TicCmd fully encodes all player input
```

### 10.2 Memory Safety

```
MemorySafety ────────────────────────────────────
  -- Theorem: Z_Malloc never returns a pointer into an existing live block.

  ∀ h : ZoneHeap • ∀ size : ℕ₁ • ∀ tag : TAG •
    let addr == Z_Malloc(size, tag, ∅) in
    ∀ b : ran h.blocks | ¬IsFree(b) •
      ¬Overlaps(addr, size, address(b.content), b.size - sizeof(MemBlock))

  -- Cache eviction preserves safety:
  -- Evicted blocks null their back-pointer, so stale pointers == NULL.
  ∀ b : ran blocks | IsPurgeable(b) ∧ b.user ≠ ∅ •
    after_evict: *(b.user) = 0
```

### 10.3 Render Completeness

```
RenderCompleteness ──────────────────────────────
  -- Theorem: every pixel in the viewport is written exactly once per frame
  -- (modulo the sky, which uses a flat-colour fallback).

  ∀ x : 0..SCREENWIDTH-1 •
  ∀ y : 0..SCREENHEIGHT-1 •
    ∃! painter : {wall, flat, sprite, sky} •
      Writes(painter, x, y)
```

### 10.4 BSP Correctness

```
BspCorrectness ──────────────────────────────────
  -- Theorem: BSP front-to-back traversal visits every subsector visible
  -- from viewpoint (x, y) in strictly increasing distance order.

  ∀ vp : ViewParams •
  ∀ ss₁, ss₂ : SubSector |
      Visible(vp, ss₁) ∧ Visible(vp, ss₂) ∧ VisitOrder(ss₁) < VisitOrder(ss₂) •
    MinDistance(vp, ss₁) ≤ MinDistance(vp, ss₂)
```

---

## Appendix A — State Table Summary

| Schema | State variables | Key invariants |
|---|---|---|
| `ZoneHeap` | `blocks`, `size` | Blocks cover heap; ZONEID on allocated |
| `WadSystem` | `lumpinfo`, `lumpcache`, `numlumps` | Cache domain ⊆ lump range |
| `MapObj` | position, momentum, FSM state, flags, health | floor ≤ z; dead ⇒ not shootable |
| `Player` | health, armor, ammo, weapons, powers | ammo ≤ maxammo; readyweapon owned |
| `NetState` | `maketic`, `gametic`, `netcmds` | gametic ≤ maketic; all nodes ≥ gametic |
| `GameState` | `state`, episode, map, skill, players, level | level present iff GS_LEVEL |
| `ViewParams` | camera pos/angle, screen geometry, scale tables | distscale derived from projection |

---

## Appendix B — Glossary

| Term | Definition |
|---|---|
| **BAM** | Binary Angle Measurement — 32-bit unsigned angle where 2³² = 360° |
| **fixed_t** | 32-bit signed integer representing a 16.16 fixed-point number |
| **FRACUNIT** | 65536 — represents 1.0 in fixed-point |
| **lump** | Named binary data entry inside a WAD archive |
| **mobj** | Map Object — the universal actor type |
| **tic** | One simulation step, 1/35 second |
| **thinker** | Any active object with a per-tic callback |
| **ticcmd** | One player's input snapshot for one tic |
| **visplane** | A horizontal surface (floor/ceiling) region at constant height, texture, and light |
| **vissprite** | A billboard sprite projected and clipped for a single frame |
| **WAD** | Where's All the Data — id Software's archive format |
| **Z++** | Extension of Z notation adding classes, inheritance, and method signatures |
