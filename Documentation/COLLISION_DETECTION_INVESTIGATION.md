# Collision Detection Investigation

## Status

Research only. No collision accessibility feature was enabled by this investigation.

Investigated and documented by **Codex (OpenAI)** on **2026-07-26**.

## Outcome

Pokémon XD has two confirmed collision systems relevant to overworld navigation:

1. **Environment collision**, backed by the room's `.ccd` data and checked by `GScolsys2HitCollision`.
2. **Human collision**, backed by a 48-slot per-floor table and checked by `GScolsys2HumanCollision`.

The room `.ccd` file is sufficiently understood to build a read-only wall and obstacle detector in the companion. The game's exact per-frame collision result is not presently a stable memory field: the engine returns it directly to player-movement code. Reading it exactly would require a game/Dolphin hook, which is outside the current read-only companion design.

The recommended first implementation is therefore a companion-side capsule sweep against locally parsed `.ccd` triangles, with dynamic people handled separately. It must initially be described as an obstacle/proximity aid, not guaranteed route guidance, until triangle types, slopes, steps, moving collision objects, and XG-added rooms have been validated.

## Evidence and confidence

### Confirmed primary evidence

- `Pokemon-XD-Code/Objects/file formats/XGCollisionData.swift` parses the actual `.ccd` structure.
- `xd-decomp/config/GXXE01/symbols.txt` identifies the verified US XD collision routines and globals.
- Disassembly of the verified US XD build was inspected for the environment and human collision routines.
- This project's prior local asset extraction used the same `.ccd` layout to locate real interaction regions for elevators and the P★DA room. That validates the parser against rooms used by the running game.

### Important scope limit

The addresses below are for vanilla US Pokémon XD, `GXXE01`, revision 0. XG is a modification. Names, logic, and file formats are strong architectural evidence, but no absolute address is assumed XG-safe without live validation.

## Static `.ccd` format

The `.ccd` file contains collision triangles and interaction-region triangles in the same container. It is not the visible model and is distinct from `.rdat`.

### Header

| Offset | Size | Meaning |
|---|---:|---|
| `0x00` | 4 | top-level entry-list offset |
| `0x04` | 4 | top-level entry count |

Each top-level entry is `0x40` bytes.

### Triangle-list pointers

Within each top-level entry, pointer fields are scanned from `+0x24` through `+0x3C`, inclusive, in four-byte steps. A nonzero pointer refers to a small list header:

| List-header offset | Size | Meaning |
|---|---:|---|
| `+0x00` | 4 | triangle-data offset |
| `+0x04` | 4 | triangle count |

Pointer slots `+0x2C` and `+0x30` are marked interactable by the reference parser. They represent regions such as warps, doors, PCs, and other scripted interaction points. The other populated slots contain ordinary collision sections or other collision categories whose exact semantics still need classification.

### Triangle record

Each triangle record is `0x34` bytes:

| Offset | Meaning |
|---|---|
| `+0x00` | vertex 1: three big-endian floats |
| `+0x0C` | vertex 2: three big-endian floats |
| `+0x18` | vertex 3: three big-endian floats |
| `+0x24` | normal: three big-endian floats |
| `+0x30` / `+0x32` | two 16-bit fields: type and interaction index |

For pointer slot `+0x30`, type is at triangle `+0x32` and interaction index at `+0x30`. For all other slots, type is at `+0x30` and interaction index at `+0x32`.

For interactable sections, the interaction index maps to the room's `common.rel` interaction-point region index. There is no separate axis-aligned trigger-box format in this parser; regions are represented by triangles.

## Live engine routines in vanilla US XD

| Symbol | Address | Observed purpose |
|---|---:|---|
| `GScolsys2GetCCDFileHead` | `0x80117EE0` | gets the loaded room CCD head |
| `GScolsys2GetCurFloor` | `0x80117EF0` | gets the current floor collision state |
| `GScolsys2LoadCCD` | `0x80118154` | loads room collision |
| `GScolsys2WalkGetLayer` | `0x8011908C` | selects a walk layer |
| `GScolsys2WalkGetHeight` | `0x801193C4` | obtains walking height |
| local `checkHitCollision` | `0x8011A280` | core environment collision check and correction |
| `GScolsys2HitNpcCollision` | `0x8011A42C` | sweeps against the NPC collision-model selection |
| `GScolsys2HitCollision` | `0x8011A5C4` | sweeps against normal environment collision |
| `GScolsys2HumanGetHumanRadius` | `0x8011ADA4` | reads an enabled human slot's radius |
| `GScolsys2HumanCollision` | `0x8011B638` | sweeps against registered people/humans |
| `GScolsys2HumanAddCurrentFloor` | `0x8011B8C4` | registers a human collision entry |
| `floorCharacterBiosGetIsHit` | `0x801226BC` | reports a character hit state |
| `peopleBiosSetCollision` | `0x80297588` | people collision control |
| `peopleSetCollision` | `0x8029E050` | people collision control |
| `peopleAddCollision` | `0x8029E09C` | registers people collision |
| `GScolsys2` | `0x80445C20` | collision-system singleton, size `0xDD0` |

### Environment sweep semantics

Disassembly supports this effective signature:

```text
GScolsys2HitCollision(start, end, radius, correctedPosition) -> hit
```

- `start` and `end` are three-float vectors.
- `radius` is a float.
- The fourth argument receives a corrected/contact position.
- It first requires a loaded CCD.
- It subdivides a long movement so collision cannot be skipped by one large step.
- It calls the core collision routine for intermediate positions.
- It returns `1` for a hit and `0` for no hit.
- The core routine accounts for enabled collision objects and object transforms, and performs repeated correction attempts.

`GScolsys2HitNpcCollision` follows the same sweep pattern but selects the alternate NPC collision-model pointer.

### Human sweep semantics

Disassembly supports this effective signature:

```text
GScolsys2HumanCollision(humanIndex, start, end, correctedPosition) -> resultCode
```

The result is not boolean:

| Result | Meaning from control flow |
|---:|---|
| `1` | no current floor |
| `4` | invalid or disabled human slot |
| `6` | human collision detected |
| `7` | clear/no human collision |

The current-floor human table begins at floor-state offset `+0xA00`, has 48 entries, and uses a `0x14`-byte stride. Confirmed fields from registration and radius access are:

| Slot offset | Meaning |
|---|---|
| `+0x00` | identifier field 1 |
| `+0x04` | identifier field 2 |
| `+0x08` | collision radius |
| `+0x0C` | second collision dimension/parameter; exact name unresolved |
| `+0x10` | flags; bit 0 enables the slot |

## What the companion can and cannot read

### Durable and usable

- current room/floor identity;
- player world position and camera orientation, already production-validated;
- static room `.ccd` triangles extracted locally;
- interaction-region indexes and triangle positions;
- potentially the loaded current-floor pointer, enabled collision objects, and human slots after XG-specific pointer discovery.

### Ephemeral

The exact return from `GScolsys2HitCollision` or `GScolsys2HumanCollision` exists in a CPU register at the call boundary. Player movement consumes it immediately. No persistent, universal “player is pressing into a wall” field has been confirmed.

The external companion uses read-only process memory and cannot call these game functions or intercept every return. Dolphin debugger breakpoints can validate behavior manually, but are not a production accessibility channel.

### Why position alone is insufficient

A stationary player could be holding a direction into a wall, not touching the controller, in dialogue or a menu, stopped by an NPC, or stopped by a scripted state. Therefore, “position did not change” cannot by itself be announced as collision. Reliable blocked-movement speech also needs verified directional input or a predictive geometry query.

## Recommended implementation route

### Phase A: local static geometry

1. Parse the current room's `.ccd` locally using the confirmed layout.
2. Keep only compact derived collision metadata on the user's machine; do not package extracted game assets.
3. Build a spatial index for nearby triangles.
4. Model the player as a horizontal capsule/cylinder, using a live or empirically validated radius.
5. Sweep from the current position toward a proposed short movement and report the nearest blocking surface.
6. Reuse the existing foreground, dialogue, menu, and floor-transition gates.

This can support a wall-proximity cue or an explicit “check ahead” command before universal controller intent is solved.

### Phase B: directional intent

Determine the actual controller direction in a mapping-independent way. Candidate sources, in preferred order:

1. a verified in-game movement/input vector in XG memory;
2. Dolphin's emulated controller state, if a stable read-only address can be found;
3. Windows controller input only when the user's Dolphin mapping is known to match it.

Keyboard or XInput polling alone is not universal because Dolphin may use arbitrary mappings, controller types, or accessibility software.

### Phase C: dynamic collision

Add people using the current-floor human table. Add moving or toggleable collision objects only after their transforms and enable bits are verified in XG. A static `.ccd` solver alone can otherwise report an open door as closed, miss a moving obstruction, or disagree with the game.

## Required validation before navigation claims

- Classify collision type values and identify which sections block horizontal movement.
- Validate player radius, step height, slopes, ledges, stairs, and floor-layer selection.
- Confirm coordinate transforms for dynamic collision objects.
- Confirm door enable/disable behavior.
- Confirm the human table pointer and slot ownership in XG.
- Compare predicted results with real movement at known walls, corners, open doors, stairs, and NPCs.
- Confirm behavior across XG-added or modified rooms.
- Suppress alerts in dialogue, battle, loading, cutscenes, menus, and whenever Dolphin is unfocused.

Until those checks pass, collision output must not be represented as safe pathfinding or proof that a route is traversable.

## Manual debugger validation recipe

For a diagnostic session on a matching executable:

1. Use a known wall and a known open space.
2. Observe calls to `GScolsys2HitCollision` and `GScolsys2HumanCollision`.
3. Record start, proposed end, radius, corrected position, and return value.
4. Repeat at a wall, corner, stair, door, and NPC.
5. Correlate the result with the final player position.

For XG, find the corresponding functions by code signature rather than copying the vanilla addresses.

## Unresolved questions

- Which `.ccd` pointer slots and type values are horizontally solid, walkable, camera-only, or otherwise special?
- Where does XG keep its current-floor collision pointer and any durable movement-intent vector?
- Is `floorCharacterBiosGetIsHit` useful for the player or only character-local scripted hit state?
- Does player movement preserve a corrected-position or collision-category field in a stable hero structure?
- How are doors and other enabled collision models linked to the companion's already identified entities?
- Can the human collision table be mapped reliably to the existing NPC records?

## Handoff

The static format is ready for a small parser/probe. The next highest-value experiment is not a full navigation system: parse one known room, log nearby solid candidates, and compare a short capsule sweep with the player's behavior at one wall and one open direction. Do not ship collision announcements until type classification and false-positive suppression are validated.

Signed: **Codex (OpenAI)** — **2026-07-26**