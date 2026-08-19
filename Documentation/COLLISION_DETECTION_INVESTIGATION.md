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

## Runtime object-enable state — RESOLVED 2026-08-13

Phase C above ("add moving or toggleable collision objects only after their
transforms and enable bits are verified") and the "confirm door
enable/disable behavior" validation item are both settled. The structure was
re-derived from `GScolsys2.s` rather than carried forward from the earlier
partial note, and it is now read live.

### Why it mattered

The companion shipped `StaticObjectEnableState`, answering "everything is
always enabled". That is not a neutral placeholder: it **reinstates collision
objects the running game has switched off**, i.e. it invents walls. Agate's
Relic Stone cave was the symptom — the cave mouth outdoors sealed into a
26-tile pocket, and the interior split so that entrance→shrine-exit produced
a confident route ending **180.4 units** from the exit.

The walls themselves are real. All 22 boundary edges out of the `M3_out`
pocket that refuse as wall-blocked do so against genuine geometry: an exact
segment-to-triangle distance agrees with the swept test's longest-XZ-edge
approximation on **22 of 22**, so none is an approximation artifact. Six
triangles across the two rooms — one 2-triangle object outdoors, two more
inside — are the entire defect.

### Structure

`GScolsys2` @ **0x80445C20**:

| Offset | Field | Notes |
| --- | --- | --- |
| `+0x000` | `CCD_FILEHEAD* curCCD` | NULL ⇒ `GetObjEnable` returns 1 |
| `+0x004` | `GSCOLSYS2_FLOOR floor` | 0xDC0 bytes |
| `  +0x000` | `GSCOLSYS2_OBJ obj[64]` | stride `0x28` |
| `    +0x00` | `f32[9]` | transform, copied from the CCD entry |
| `    +0x24` | `u16 flags` | **bit 0 SET = DISABLED** |
| `  +0xA00` | `<other>[48]` | stride `0x14`; unrelated to object enable |
| `+0xDC4` | `s32 curFloor` | valid only when `0` |
| `+0xDC8` | `GSgfxVF*` | |
| `+0xDCC` | `void* displayList` | `GSgfxDLFree`d by `UnloadCCD` |

- **Object count** is `*(u32*)(curCCD + 0x04)` — the same `entry_count` the
  companion's own parser already reads out of the `.ccd`.
- **Index mapping is the identity.** `GScolsys2LoadCCD` walks the CCD entry
  array (stride `0x40`) and the OBJ array (stride `0x28`) in lockstep,
  writing entry *i* into record *i*.
- **One record serves both model slots.** `GScolsys2WalkGetHeight` (walk
  model, CCD `+0x24`) and the hit-model sweep (`+0x28`/`+0x34`) each loop
  *i* over `[0, count)`, call `GScolsys2GetObjEnable(i, …)` and `continue`
  when it reports 0, *before* examining any geometry. Filtering only the wall
  slot would mismodel the engine.
- **`+0xDC4` is not a bank selector.** `GScolsys2GetCurFloor` accepts it only
  when exactly `0` (`cmpwi 0; blt fail` then `cmpwi 1; blt ok`), and the only
  write to it in the module is `GScolsys2Init` storing `0`. The `* 0xDC0`
  scaling in the accessors is vestigial.

### Semantics

`GetObjEnable(index, out_u8)` stores the **inverse** of bit 0: bit set → `0`,
bit clear → `1`. The out-parameter means *enabled*; the stored bit means
*disabled*. `SetObjEnable(index, enable)` clears bit 0 when `enable != 0`
(`rlwinm r0, r0, 0, 16, 30`, preserving every other bit) and sets it
otherwise. Return codes: `0` ok, `1` no CCD loaded, `2` index out of range —
and on both error paths the out-parameter is **left untouched**, which is why
the companion raises rather than defaulting when it cannot answer.

### Lifetime

`GScolsys2LoadCCD` stores `0` into `obj[i].flags` for all `count` objects, so
**every object starts enabled on room load** and the room script's
`preprocess` then disables what story state calls for. `GScolsys2UnloadCCD`
only nulls `curCCD`, leaving the flag words stale — safe precisely because
the next `LoadCCD` rewrites them. State can also change **mid-room** at any
time (Gateon Port's piers), so a snapshot is never valid indefinitely.

`_gscolsysMakeStateData`/`_gscolsysRestoreStateData` are registered with
`floorRegisterModule`: mode 3 serialises exactly 64 `u16` flag words
(size `0x84` = 4 + 64×2) and modes 1/2 `memcpy` the whole `0xDC0` floor block.
Enable state therefore **survives save/load**. The mode-3 loop stores to
`GScolsys2 + 0x28 + i*0x28`, which is `floor + i*0x28 + 0x24` — an independent
confirmation of both the stride and the flags offset.

### Verification

The address is not trusted on the strength of documentation. `profile.py`
carries a new `engine_signatures` entry for `GScolsys2GetObjEnable` at
`0x80117BAC`, whose first four instructions **are** the address
(`lis r5, GScolsys2@ha` carries `0x8044`; `addi r6, r5, GScolsys2@l` carries
`0x5C20`). Those bytes were confirmed against the shipped
`orig/GXXE01/sys/main.dol` at file offset `0x114B0C`, and decode to
`0x80445C20`. A build that moved the global fails the signature instead of
silently reading whatever now sits there.

### Corrections to the earlier note

The 2026-08-01 note recorded "0x28-byte per-object records and bit 0 of
`u16 +0x24`", which is right, but it did not establish the record **base**
(`+0x04`, not `+0x00`), the **capacity** (64), the **index mapping**
(identity with the file's entry index), or that **walk and hit share one
record**. Those are the four facts a live implementation actually needs, and
none had been pinned.

### Live confirmation — 2026-08-13, CONFIRMED

Read out of a running game, in `M3_out` with the cave open:

```
05:45:48.915  COLLISION enable-state ... floor=0x84 disabled=33
05:45:48.928  NAVIGATION room load floor=0x84 room=M3_out walk_triangles=570
              wall_triangles=1095 ... disabled_objects=33
```

Five independent predictions, all met:

| prediction | observed |
| --- | --- |
| the global is readable at `0x80445C20` | snapshot taken, no read error |
| object 33 reports **disabled** | `disabled=33` |
| wall triangles drop by exactly 2 | 1097 → **1095** |
| the cave pocket joins a **1861**-node component | `build_ok … nodes=1861` |
| `cause=disconnected` / partial routes stop | last occurrences 00:52 and 01:27, i.e. **before** the fix; none after |

The 1861 figure had been derived statically from the `.ccd` before the game
was ever run, and the live flood reproduced it exactly. `LiveObjectEnableState`
is therefore **live-validated**, not merely derived.

This is evidence about the *mechanism*, not a rule about Agate. Nothing in the
companion knows that object 33 is a cave doorway; it knows that CCD entry 33
reported its disabled bit set. The same code path is what Gateon Port's piers
will exercise.

### Still open
- Whether a save/load path can present a floor state whose flags disagree
  with what the room script would set on a fresh load.
- The `<other>[48]` array at floor `+0xA00` (stride `0x14`, bit 0 of the
  `u16` at `+0x10`, cleared for all 48 by `LoadCCD`) is unidentified.

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