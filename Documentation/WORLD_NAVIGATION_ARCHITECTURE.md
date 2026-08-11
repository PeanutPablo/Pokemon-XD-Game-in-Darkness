# World navigation architecture — ownership investigation

**Date:** 2026-07-31
**Question:** Is the apparent "missing floor" in the terraced/cliff region of
`M3_out` (A) genuinely missing walkable geometry in the game's data, or
(B) an incomplete understanding of the game's world representation?

**Answer: (B), decisively.** The `.ccd` collision file contains a complete,
authoritative, explicitly-layered walkable-surface model. This project has
never parsed it. No data is missing; a pointer slot was never read.

---

## 1. The CCD container: six model slots, not one

`GScolsys2LoadCCD` (`0x80118154`) loads a `CCD_FILEHEAD`; `_offsetCCD`
(`0x80117F74`) relocates its pointers. Disassembly of `_offsetCCD` gives the
container layout unambiguously:

- file head `+0x00` = entry array, `+0x04` = entry count
- entry stride `0x40` (`addi r4, r4, 0x40`)
- each entry holds **six** model pointers, relocated at
  `+0x24`, `+0x28`, `+0x2C`, `+0x30`, `+0x34`, `+0x38`

Each model head has a `(triangle_array, triangle_count)` pair at `+0x00`/`+0x04`.
Triangle stride is `0x34`: three vertices (`0x00`–`0x23`), normal
(`0x24`–`0x2F`), then two metadata bytes at `+0x30` and `+0x31`.

### Slot → model type (from the game's own code)

| Slot | Model type | Established by |
|---|---|---|
| `+0x24` | `CCD_WALKMDL_HEAD` — **walk model** | `drawWalkMdl(CCD_WALKMDL_HEAD*)` called with `lwz r3, 0x24(r29)` in two independent draw routines (`GScolsys2Draw.s:267/272`, `513/518`); `GScolsys2WalkGetHeight` reads `lwz r29, 0x24(r30)` |
| `+0x28` | `CCD_HITMDL_HEAD` — collision/walls | `drawHitMdl(CCD_HITMDL_HEAD*)` called with `lwz r3, 0x28(r29)` |
| `+0x2C` | `CCD_THRUMDL_HEAD` — pass-through/event regions | `GScolsys2Thru.s` reads `0x2c` |
| `+0x30` | `CCD_CHECKMDL_HEAD` — interaction/check regions | `GScolsys2Check.s` reads `0x30` |
| `+0x34` | `CCD_HITMDL_HEAD` — second hit model | `drawHitMdl` called with `lwz r3, 0x34(r29)` |
| `+0x38` | sun/lighting model | `GScolsys2Sun.s` reads `0x38` |

**This project reads `+0x28` (walls) and `+0x2C`/`+0x30` (interaction regions,
via `authoritative_warps.parse_interactable_region_centers`). It has never
read `+0x24`.** The warp/door/PC features working correctly in-game
independently corroborates the `+0x2C`/`+0x30` semantics above.

---

## 2. The walk model is a real, layered walkable surface

`GScolsys2WalkGetHeight` (`0x801193C4`) is the game's own ground query:

- skips entries whose object is disabled (`GScolsys2GetObjEnable`)
- reads slot `+0x24`, iterates its triangles (stride `0x34`)
- transforms vertices by the object matrix, does a point-in-polygon test
- accumulates **up to 8 stacked candidate surfaces** for one XZ position
  (`cmpwi r24, 0x8`), each a `0xC`-byte record: `float height`, then metadata
- decodes byte `+0x30` as two 4-bit values (`0xF` → `0xFFFF` sentinel) and
  byte `+0x31` as two 4-bit values

`GScolsys2WalkGetLayer` (`0x8011908C`) calls `WalkGetHeight`, selects the
candidate whose height is **closest to the query Y**, and returns that
triangle's byte-`+0x31` nibble pair as two output bytes.

So the engine natively supports multiple walkable surfaces stacked at the
same XZ, disambiguated by height plus a per-triangle layer ID. That is
exactly the representation a terraced area requires.

### Measured against the real failing region (`M3_out.ccd`)

Walk model: **570 triangles, 559 upward-facing** (versus 4 upward-facing in
the wall slot we do parse). Layer pairs from byte `+0x31`:

| layerA | layerB | count | meaning |
|---|---|---|---|
| 0 | 0 | 84 | surface on layer 0 |
| 0 | 1 | 8 | **transition, layer 0 ↔ 1** |
| 1 | 1 | 151 | surface on layer 1 |
| 1 | 2 | 8 | **transition, layer 1 ↔ 2** |
| 2 | 2 | 142 | surface on layer 2 |
| 2 | 3 | 22 | **transition, layer 2 ↔ 3** |
| 3 | 3 | 142 | surface on layer 3 |
| 3 | 4 | 4 | **transition, layer 3 ↔ 4** |
| 4 | 4 | 9 | surface on layer 4 |

Per-layer height bands (overlapping, which is why height alone cannot
disambiguate them and why our height-continuity heuristic failed):
layer 0 `-6.22…120.00`, layer 1 `0.87…41.00`, layer 2 `43.19…92.16`,
layer 3 `81.68…121.19`, layer 4 `105.85…160.00`.

Emulating `WalkGetHeight` at the exact positions captured from live watcher
logs during the reported failures:

| Position (live) | Player Y | Walk-model height | Δ | Layer |
|---|---|---|---|---|
| guide start (ground) | −0.02 | −0.03 | 0.01 | 0 → 0 |
| climb start | −0.03 | −0.03 | 0.00 | **0 → 1 (transition/ramp)** |
| mid-climb | 16.36 | 16.36 | 0.00 | 1 → 1 |
| plateau top | 40.00 | 40.00 | 0.00 | 1 → 1 |
| stuck-at-wall spot | 40.00 | 40.00 | 0.00 | 1 → 1 |

Every position the player actually stood on has real walk-model floor
directly underfoot, matching their true Y to within 0.01 units. The ramp the
player climbed is an explicit layer-0→1 transition triangle.

Across all 177 `.ccd` files: slot `+0x24` holds **26,088 upward-facing
triangles in 167 files**, versus 289 in slot `+0x28`. Its `collision_type`
values occupy a distinct namespace (`0xFF00`, `0xFF01`, `0xFF11`, `0xFF22`,
`0xFF33`) from the wall slot's `0x0001`–`0x0007`.

---

## 3. Deliverable — subsystem ownership table

| Subsystem | Purpose | Authoritative? | Contains height? | Contains walkability? | Loaded from | Evidence | Ruled in/out |
|---|---|---|---|---|---|---|---|
| **Walk model (CCD `+0x24`)** | The walkable ground surface, layered | **Yes — this is the owner** | **Yes**, exact (Δ ≤ 0.01 at every live position) | **Yes**, explicitly, with layer IDs and inter-layer transitions | `<room>.ccd`, slot `+0x24`, via `GScolsys2LoadCCD` | `drawWalkMdl(CCD_WALKMDL_HEAD*)`; `GScolsys2WalkGetHeight` reads `0x24`; `GScolsys2WalkGetLayer`; 570 tris / 5 layers in `M3_out` | **RULED IN — explains the terraced area completely** |
| Hit model (CCD `+0x28`) | Player collision / walls | Yes, for blocking only | Incidentally (wall extents) | No — obstacles, not surfaces | `<room>.ccd` `+0x28` | `drawHitMdl`; 1097 wall tris vs 4 floor tris in `M3_out` | Ruled out as floor owner (correctly used today for wall blocking) |
| Hit model 2 (CCD `+0x34`) | Second collision model (distinct purpose not established) | Unknown | Incidentally | No | `<room>.ccd` `+0x34` | `drawHitMdl` with `lwz r3, 0x34`; identical tri counts to `+0x28` in aggregate scan | Ruled out as floor owner; purpose **unresolved** |
| Thru model (CCD `+0x2C`) | Pass-through / event regions | Yes, for events | No | No | `<room>.ccd` `+0x2C` | `GScolsys2Thru.s` reads `0x2c`; already consumed by our warp code | Ruled out as floor owner |
| Check model (CCD `+0x30`) | Interaction / check regions | Yes, for interactions | No | No | `<room>.ccd` `+0x30` | `GScolsys2Check.s` reads `0x30`; our `parse_interactable_region_centers` uses it and works live | Ruled out as floor owner |
| Sun model (CCD `+0x38`) | Lighting / shadow | Yes, for lighting | No | No | `<room>.ccd` `+0x38` | `GScolsys2Sun.s` reads `0x38` | Ruled out |
| Object enable state | Runtime enable/disable of CCD objects | **Yes, gates all of the above at runtime** | No | Indirectly (disabled objects are skipped) | Runtime global `GScolsys2` (`≈0x80445C20`), per-object `0x28`-byte record; bit 0 of `u16 +0x24` = disabled | `GScolsys2GetObjEnable`/`SetObjEnable`; `SetObjEnable` called from `script.s`; `WalkGetHeight` skips disabled objects | **RULED IN as a required modifier** — static geometry alone is not the whole truth |
| Room asset loader (`floorRead.s`) | Streams per-room assets (fsys/deck/ant/GSW/rel/GFL/BGM) | Yes, for loading | No | No | Disc `<room>.fsys` | `floorReadResourceID`, `floorRead*Pre/PostFunc` | Ruled out — loader, not a geometry owner |
| Room script (TCOD, fsys type 7) | Scripted events, can toggle collision objects | Yes, for dynamic state | No | Indirectly, via `SetObjEnable` | `<room>.fsys` entry type 7 | `script.s` calls `GScolsys2SetObjEnable` | Ruled out as floor owner; **relevant to dynamic changes** |
| Interaction-point table | Warps/doors/elevators/PCs/signs | Yes, for those entities | No | No | `common.rel` + CCD region centroids | `authoritative_warps.py`, working live | Ruled out |
| People/NPC movement | NPC walking, `peopleWalkToXYZ`, random walk | Yes, for NPCs | Consumes walk model | Consumes, does not own | Runtime | `people.s` calls `GScolsys2WalkGetHeight` and `GScolsys2WalkGetLayer` | Ruled out as owner — but confirms the walk model is *the* navigation substrate the engine itself uses |
| Player movement | Hero locomotion | Yes, for the player | Consumes walk model | Consumes, does not own | Runtime | `heroMove.s` calls `GScolsys2WalkGetHeight` | Ruled out as owner — same corroboration |

---

## 4. Conclusion

The `.ccd` data is **not incomplete**. It contains a first-class, layered,
engine-authoritative walkable-surface model with explicit inter-layer
transitions, and both the player's own locomotion (`heroMove.s`) and NPC
movement (`people.s`) navigate using it. Our pathfinding failed in the
terraced region because it was reading the wall model and inferring ground
from a default-walkable fallback, never reading the walk model at all.

**Consequences for work already done:**

- The default-walkable model in `pathfinding.py`, the height-continuity
  tolerance, and `nearest_supported_floor_distance` were all compensating for
  a parse gap. They become unnecessary once `+0x24` is read.
- **No supplemental navigation source is required.** The precondition the
  project owner set ("only if `.ccd` is confirmed incomplete") is not met.
  `traversal_log.py` (built earlier this session, standalone and unwired) is
  therefore **not justified** and should be shelved rather than developed —
  inferring walkability from player trails would be strictly worse than
  reading the authoritative surface the engine itself uses.
- Route-progress validation and route confidence (also built this session)
  remain worthwhile as safety nets, but should not be load-bearing.

## 5. Explicitly unresolved (not guessed)

- **Byte `+0x30` nibbles**: all `0xF` (sentinel) in `M3_out`; meaning
  undetermined. Other rooms show non-sentinel values (`0x1F00`, `0xF000`,
  `0x0F00` in the aggregate scan) and need examination.
- **`layerA`/`layerB` transition semantics**: inferred as "this triangle
  joins these two layers" from the data pattern (transitions always join
  adjacent layer numbers, counts are small, and the climb-start position sits
  on a 0→1 pair). Strongly supported, but no consumer has been disassembled
  that uses the pair for connectivity specifically.
- **Purpose of the second hit model (`+0x34`)** versus `+0x28`.
- **Object enable state address** identified from disassembly
  (`GScolsys2` global, `≈0x80445C20`) but **not yet verified against live
  memory**.
- **10 of 177 `.ccd` files have no `+0x24` walk model** — not investigated.
- Whether the object matrix (`GScolsys2GetObjMatrix`) meaningfully transforms
  walk geometry in practice; the emulation above ignored it and still matched
  live positions to 0.01, but that does not prove it is always identity.

---

## 6. Implementation (2026-08-01 / 2026-08-02)

The investigation above was acted on: navigation now routes on the walk
model. Summary of the shipped architecture and everything live testing
forced to change.

### Module roles after the rewrite

| Module | Role |
|---|---|
| `collision_probe.parse_walk_model_triangles` | Parses CCD **+0x24** into `WalkTriangle` (vertices, normal, `layer_a`, `layer_b`, `raw_metadata_byte`, `entry_index`). Independent of the hit-model parser by design — a shared-code mistake between these two slots is exactly the failure this whole effort came from. |
| `collision_probe.parse_environment_triangles` | Parses CCD **+0x28** (`CCD_HITMDL_HEAD`) — obstacles/walls only. **Never a floor source.** |
| `pathfinding.walk_height_candidates` | Companion to `GScolsys2WalkGetHeight`: every distinct walkable height at an XZ, capped at 8 (the engine's own cap), height-deduplicated, carrying layer identity. |
| `pathfinding.resolve_node` | Companion to `GScolsys2WalkGetLayer`: picks by nearest height to a **known real Y**. Returns `None` when there is no coverage — no invented surfaces. |
| `pathfinding._connected_walk_candidate` | Connectivity gate. **Layer-set intersection first**; `HEIGHT_CONTINUITY_TOLERANCE` applies only *after* that, as a defensive check inside an already layer-validated relationship. |
| `collision_object_enable` | Interface for runtime object-enable state. Ships as `StaticObjectEnableState` (everything enabled). |

The flow field is keyed by **node = `(tile, layer_set)`**, not bare tile,
since one XZ tile can carry several layers with entirely different
connectivity.

**Removed:** the default-walkable/default-open model, inferred floor
heights, `nearest_supported_floor_distance`, and `RouteConfidence.UNCERTAIN`
— all of which existed solely to compensate for not reading +0x24. A route
that builds is now `VERIFIED`; there is no "succeeded but built on
inference" state. `traversal_log.py` is **shelved** (see §7).

### Constants recalibrated from live measurement

Every one of these was an uncalibrated guess that live testing disproved.

| Constant | Was | Now | Evidence |
|---|---|---|---|
| `HEIGHT_CONTINUITY_TOLERANCE` | 6.0 | **10.0** | Measuring every same-layer, wall-unblocked, adjacent tile pair in real `M3_out` found a genuine climbable slope with steps up to **7.40**; 6.0 rejected real terrain. Next same-layer cluster jumps to 22.04, so 10.0 keeps real defensive value. |
| `SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS` | `TILE_SIZE*3` (24) | **`TILE_SIZE*20` (160)** | Measured movement ≈17 u/s walking, 32–38 running. 24 units = **0.7–1.4 s** — less than reaction time to a new audio cue. Both live failures fired here at 24.07 / 26.01. |
| `WAYPOINT_STABLE_RADIUS_RATIO` | 0.5 (4.0 u) | **0.9 (7.2 u)** | Closest approaches across four live waypoints were 4.72 / 4.30 / 6.36 / 8.57 — never inside 4.0, so the waypoint never advanced and the stall timer killed the route. All four waypoint centres were verified genuinely standable. 7.2 stays below the 8.0 spacing, so it cannot skip a hop. |
| `MAX_ROUTE_REBUILDS_PER_ACTIVATION` | 1, lifetime | **1, replenishing** | Was a never-resetting per-activation count: a whole journey got one recovery. Live, rebuild #1 at t=5.0 s → permanent abandonment at t=9.7 s, despite a waypoint genuinely being reached at t=5.7 s in between. Now resets whenever a waypoint is reached. |

### Node identity defect (live-confirmed)

`(tile, layer_set)` is **not well-defined from position alone**: one tile can
hold triangles with different layer nibbles, so the key depends on which XZ
point inside the tile is sampled. The flood fill samples tile centres;
`resolve_node` samples where the player stands.

Confirmed in `M3_out` at tile `(15,-21)`: centre → layers `{3}` at height
`120.005`; the player 3.6 units away → layers `{3,4}` at the **same** height.
The field held `((15,-21),{3})`, the player resolved to `((15,-21),{3,4})` →
spurious *"player node not linked to destination."*

Fixed by `NavigationService._field_node_at`: match on **tile + nearest real
height**, which is stable regardless of layer tagging. Layer identity still
governs graph *connectivity* — it simply stopped being a lookup key.

### Live validation result

The original terraced route **passes**. Log shows `AUDIO GUIDE Arrived.`
(2026-08-02 14:17:22), and the project owner confirmed it reaches the
destination consistently. Watcher evidence from that run:

- real walk-model floor under **every** sampled position (`dy=0.000`)
- correct layer transitions followed: `L0 → TRANS[0,1] → L1`
- wall checks clear; `conf=verified` throughout
- first genuine waypoint advance in the feature's history
- **no** unsupported-floor fallback, **no** missing-geometry fallback

### Known-open (not defects, deliberately deferred)

- **Redundant waypoints.** Measured on a real route: 5 nodes, path length
  32.0 vs straight-line 32.0 (**1.00×**), **3/3** interior waypoints
  collinear. Line-of-sight route simplification remains unimplemented;
  `reconstruct_route` is shaped so it can slot in.
- **First-waypoint instability across re-toggles**, reported live.
  **Not reproduced**: the flow field is deterministic (6/6 identical builds),
  and the first waypoint is stable across ±3 units *and* across a tile
  boundary at the tested position. Leading hypothesis is equal-cost **branch
  points** where two adjacent tiles each have a different but equally optimal
  next hop. Unconfirmed — needs the player's position at the moment it
  happens.
- **Dynamic object-enable state is NOT live-validated.** A narrow read at the
  disassembly-traced `≈0x80445C20` returned mapped memory, but the byte
  pattern did not clearly match the traced bit-flag layout — inconclusive, so
  the static implementation ships and the runtime mapping remains unguessed.
- **3 rooms fail walk-model parsing outright** (`M6_pc_1F`, `M6_tower_3F`,
  `M6_tower_4F` — non-finite vertex values), plus the 10 with no `+0x24` at
  all. All load as an honest empty result; none are investigated.

## 6a. Work of 2026-08-03 (recovered from code, previously undocumented)

A whole navigation session landed on 2026-08-03 with no entry in any
document — found by reading the shipped code against §6's "known-open"
list, which still described several of these as unimplemented. Recorded
here from the code and its own docstrings.

| Change | Effect |
|---|---|
| `pathfinding.simplify_route` | **Closes §6's known-open item 1.** Collapses runs of *exactly collinear* waypoints, keeping turns, both endpoints, every layer change, and an intermediate node whenever a straight run exceeds the span. Deliberately NOT the line-of-sight shortcutting originally proposed: collinear collapse keeps the "consecutive waypoints are joined by a straight line of walkable tiles" guarantee true **by construction**, since dropping a node that lies exactly on the line between two already-validated hops adds no new geometry. |
| `pathfinding.waypoint_span_for_route` | Replaced a fixed 32-unit waypoint span. Rooms' walk-model diagonals were measured at 84 units (`M6_crab_B1`) to 2621 (`D5_out`) — a 31× spread — so one fixed span meant 38% of the diagonal in the smallest rooms against 1–2% in the largest (~80 waypoint cues in one crossing). Now targets ~8 waypoints per route, clamped to 16–80 units. |
| `MAX_TILES` 20000 → 32000 | Measured the true reachable node count of every room with the cap lifted. `M6_out` (Gateon Port) floods to **24555 nodes** — so the old bound made **every route request in Gateon Port fail outright** and fall back to direct guidance. Nothing else came close; the next largest is `D3_out` at 14900. |
| `WAYPOINT_PROGRESS_TIMEOUT` retired | Elapsed time is no longer a failure trigger at all. It fired while the player stood still (live: 0.00 and 0.65 units of displacement) and — the project owner's point — **this game has no turn-to-face action**, so time spent not closing distance carries no information about reachability. `SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS` is now the sole detector. |
| `STALL_MOVEMENT_EPSILON` | Supporting fix for the same report: the stall timer only accrues while the player is genuinely moving. |
| Committed waypoint sequence | Fixes a live ping-pong: on a U-shaped route the two arms lie in adjacent tile rows whose flow-field hops point in **opposite** directions. Walking the boundary (z ≈ −120.5 against a row edge at exactly −120.0), sub-tile drift flipped which row the player resolved to and re-derivation handed back the opposite arm — eight reversals in seventy seconds. The sequence is now committed when the route is built and advanced by cursor. |

Also recorded only in `npc_beacons.py`'s comments and nowhere else: **the
field camera's yaw is not constant within a room.** Every floor loads a
field-camera list, and where it holds more than one entry the engine blends
their yaws by inverse-square distance to the player, every frame. Gateon
Port is noted as holding eight, spanning 67°. The engine side is visible in
`floorFieldCamera.s` (`gFieldCameraList`/`gNumFieldCameras`, stride 0x34,
`_floorFieldCameraDetectMode`, `floorFieldCameraBlend`,
`_floorFieldCameraCalculatePathParams`). The 8-cameras/67° figure itself has
no recorded derivation — treat it as an unverified note until re-measured.

## 6b. Waypoint capture ignored height (2026-08-04, fixed)

Live failure, floor 0x84 `M3_out`, 00:09:57–00:10:44:

```
00:10:00.849 player=(83.09, 40.00, 91.65) node=((10,11),{1}) -> wp=((2,11),{1})
00:10:06.622 player=(19.23, -5.04, 98.97) node=((2,12),{0})  -> wp=((2,15),{1})
```

The player fell off the terrace (layer 1 y=40.00 → layer 0 y=−5.04) and the
guide **credited them with reaching the waypoint above their head**, because
capture compared `_distance_xz` only. Tile (2,11) genuinely carries both
surfaces (verified against the room's walk model: −4.41 layers [0], 39.66
layers [1]); their XZ distance to the waypoint centre was **7.01 against a
7.20 capture radius**. The committed sequence then marched on along the
upper terrace: route length *grew* (54 → 61 → 65 → 66), six polls reported
the player unlinked, and at 00:10:13.407 the beacon aimed at `((0,16),{1})`
while the player stood at `((0,16),{0})` — the tile they were already in,
one layer up. The guide only gave up **160.5 units of walking later**.

Fixed by `WAYPOINT_CAPTURE_HEIGHT_TOLERANCE` (reuses
`HEIGHT_CONTINUITY_TOLERANCE`'s measured 10.0). Being inside the XZ window
but outside the height tolerance is now positive evidence the player has
left the route's surface, so the sequence recommits from where they actually
are instead of advancing. `_field_node_at` gained the same bound — unbounded
"nearest height" was answering a query 500 units below the field with "you
are standing on the surface above you". `audio_guide`'s arrival check had
the identical blind spot (`relative_geometry`'s `vertical` was computed and
discarded) and is now gated too.

## 6c. What the 2026-08-04 measurements did and did not establish

Rebuilt the failing route offline against the real `.ccd` and confirmed the
reproduction is exact — **2968 field nodes, 54-hop chain, first waypoint
`((2,11),{1})`, all matching the live log**.

**Established:**

- **The route was geometrically sound.** Sampling the straight line of every
  hop against interpolated height: 1 of 53 hops leaves walkable ground, and
  that gap is 0.7 units at a ramp transition. Per waypoint leg: 1 of 18.
- **Simplification is not degrading safety.** 0 of 18 legs has a worse
  unsupported stretch than the hops it replaced. The by-construction
  guarantee holds empirically.
- **Grid resolution, all 163 routable rooms, 226,916 tiles touched by walk
  geometry:** 85.5% fully walkable, 5.1% partially walkable, 9.4% have a
  centre that is not standable at all (so they can never become nodes).
  Worst rooms for partial coverage: `D3_ship_B1_2` (41%), `M3_houseB_1F`
  (33%), `D5_factory_2F` (31%, plus 29% centre-empty).

**Not established — do not build on these:**

- **A reliable "distance from the nearest drop-off" metric.** Three
  successive definitions gave 58%, 32% and 15% of `M3_out`'s nodes bordering
  a drop; each correction (excluding walls, then testing the wall *before*
  the missing ground, since an indoor floor mesh simply ends at the wall)
  moved the answer by a factor of two. The final version still fails its own
  sanity check — it calls 28.6% of the Agate Pokémon Centre's interior
  "bordering a drop", which is impossible. The likely cause is
  `_segment_blocked` requiring **all five** sample lines to be blocked, so a
  partially-covered wall reads as open ground with nothing behind it.
- **Therefore: clearance-aware routing is NOT justified on this evidence.**
  Under the least-wrong metric the current route touches a drop edge on 2 of
  54 hops and a penalty removes them for +10% walking distance — a marginal
  gain resting on a measurement that is known to be wrong. Revisit only with
  a drop-off test that passes the indoor sanity check.
- **Why the player left the route.** Two position samples 5.8 seconds apart
  cannot locate the fall; at the measured 17–35 units/s that is 100–200
  units of unobserved travel. The capture bug explains what the guide did
  *after* the fall, not what caused it.

## 6f. DEGENERATE WALK MODELS — 30% of rooms (live-caught 2026-08-04)

**Live failure.** `D1_garage_1F` (Cipher Lab garage, floor 0x1),
11:45–11:47. Navigation was toggled on toward a warp and then failed its
progress check **five consecutive times**, each at almost exactly the
`SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS` limit:

```
11:46:05  best_distance=22.07  cumulative_displacement=160.11
11:46:18  best_distance=11.19  cumulative_displacement=161.11
11:46:33  best_distance=12.87  cumulative_displacement=160.17
11:46:49  best_distance=15.54  cumulative_displacement=160.53
11:47:05  best_distance=13.90  cumulative_displacement=161.26
11:47:12  best_distance=19.41  rebuild_attempts=1 -> abandoned
          "Walkable route could not be verified; guiding directly."
```

The project owner walked ~800 units in 67 seconds and never got closer than
11 units to any waypoint. The failure detection worked correctly; what it
was detecting was a route that could not be walked.

### Cause: the walk model carries no structure indoors

Measured across every `.ccd` in the game:

| Walk model | Rooms |
|---|---|
| Fails to parse | 0 |
| Empty (0 triangles) | 9 |
| **Degenerate (≤ 8 triangles)** | **42** |
| Substantive (> 8, median 106) | 118 |

**51 of 169 rooms — 30% — have no usable floor detail**, and 38 of those
have *exactly 2* walk triangles: a single flat quad.

Crucially **this data is not broken.** An indoor room's floor genuinely *is*
one flat rectangle, so two triangles describe it perfectly. All the
structure — counters, machinery, furniture, interior walls — lives in the
hit model instead (`D1_garage_1F`: walk=2, wall=140; `M2_hotel_1F`: walk=2,
wall=420).

The affected list is not obscure. It includes `M3_pc_1F` (Agate Pokémon
Center), `M3_cave_1F_1`/`_2`, most shops, most houses, `M2_hotel_1F`, all
nine Mt. Battle rest rooms, and `D1_garage_1F`.

### Why this breaks routing specifically

§6's rewrite made the walk model the sole source of walkability, which is
right for `M3_out` (570 triangles, terraced, outdoor) — the room every
constant was tuned against. Indoors that inverts: the walk model says "this
entire rectangle is floor" and the *only* thing standing between the flood
fill and a route through a solid counter is `_segment_blocked`'s
wall-crossing test.

That test is deliberately **permissive**: `GAP_SAMPLE_OFFSETS` opens a
tile-to-tile edge if **any one** of five sampled lines is clear. That rule
exists for a real, live-caught reason — a genuine ~2-unit doorway in
`M3_out` fell exactly between tile-centre rows and was being walked past.
But "one clear line opens the edge" is far too weak to be the primary
structural gate in a cluttered indoor room, which is exactly the load it
carries in 30% of the game.

So the guide confidently routes through furniture, the player cannot follow,
and the progress backstop eventually gives up — which is the honest outcome,
but only after ~13 seconds of walking per attempt.

### Compounding factor: cross-level destinations

The same session's first attempt (11:43:31) failed differently — *"No
walkable path found; guiding directly"* — against a warp announced as
`distance 74, below`. The second target was `distance 175, above`. With a
single-plane walk model, `resolve_node` has exactly one height candidate, so
a destination on another vertical level snaps onto that plane and the route
aims at the XZ *underneath* the real target.

`NavigationService` is intra-room by design, but "intra-room" is not the same
as "single level" — a room can have levels the walk model does not
distinguish.

### Not yet fixed — deliberately

The obvious move (require *all* sample lines clear when the walk model is
degenerate) trades this defect straight back for the doorway bug the
permissive rule was introduced to fix. A defensible fix needs a real swept
test against the player's actual collision radius rather than a sampled
line, and that should be designed rather than tuned by ear.

Recorded here rather than patched, because the current behaviour at least
fails honestly and falls back to direct guidance.

## 6g. THE SWEPT-CIRCLE PLAN, TESTED BEFORE BUILDING — AND CORRECTED

The obvious fix for §6f was: replicate the engine's own movement test —
sweep a ball of `colBallSize` against the hit model, exactly as
`heroMove.s:1186-1196` does (`peopleInfoBiosGetPtr` →
`peopleInfoBiosGetColBallSize` → `GScolsys2HitCollision`) — and use it
everywhere, indoors and out.

Measured first. **It would have broken outdoor routing outright.**

### Live measurement: the radius is 4.0

Read from the live `peopleInfo` table (279 records, via the same
double-indirection `npc_beacons.py` uses):

| colBallSize | records |
|---|---|
| 4.00 | **224** |
| 3.50 | 14 |
| 0.00 | 23 |
| 1/2/3/5/6/7.5/9/15 | 1–6 each |

`talkDistance` is 3.00 for 278 of 279, confirming the static default the
healing trace records, with live per-actor overrides living elsewhere
(`people_work + 0x178`).

**Caveat: the hero's own record has not been pinned.** Its people-info ID
comes from a runtime `HEROMOVE_MEMBER` (`getObjID` in `heroMove.s`), not a
constant. 4.00 is overwhelmingly likely but is not yet *the hero's*
confirmed value.

### Why the global swept test fails outdoors

Clearance from each tile centre on the **live-proven terrace route** in
`M3_out` to the nearest vertical hit-model triangle:

```
min 0.10   p10 0.99   median 3.98
tiles failing a swept radius 4.0: 22 / 38
```

Two thirds of a route that demonstrably works would be rejected.

Height filtering does **not** rescue it — restricting walls to those whose Y
span overlaps the player's body at that point changes 22/38 to 21/38. (It is
still worth noting that `_segment_blocked` currently ignores Y entirely, so
a wall far above the player's head does participate in blocking. That is a
real defect; it simply is not *this* one.)

The actual reason is that **outdoors, hugging geometry is normal**. The hit
model's near-vertical triangles there are terrain sides — cliff faces,
terrace edges, the sides of the very ramp the route climbs. Walking within a
fraction of a unit of a cliff face is ordinary, correct play. The walk model
already answers "may I stand here"; the wall triangles are scenery you are
entitled to brush against.

### Indoors the same test is not just safe but necessary

Sampling the floor at 2-unit resolution and asking how much remains clear at
each radius:

| Room | r=1.0 | r=2.0 | r=3.0 | r=4.0 |
|---|---|---|---|---|
| `M3_pc_1F` | 92.2% | 85.1% | 77.3% | **70.6%** |
| `D1_garage_1F` | 91.3% | 82.3% | 73.9% | **65.3%** |
| `M2_shop_1F` | 92.5% | 85.2% | 78.0% | **71.1%** |

At radius 4.0 roughly two thirds of each indoor floor stays clear — plenty
to route through, while finally excluding the furniture the flood fill
currently walks straight through.

### The corrected design

Not one global test, and **not a second engine**: one flow field, one
service, with the *authority for passability chosen per room* from a
measurable property of that room's own data — walk-model richness.

| Room type | Authority | Wall test |
|---|---|---|
| Rich walk model (118 rooms, median 106 triangles) | walk model | permissive, as today |
| Degenerate walk model (51 rooms, ≤8 triangles) | **hit model** | **swept circle, radius from `colBallSize`** |

This is deliberately low-risk in the direction that matters: outdoor rooms
keep exactly today's behaviour, so the live-proven terrace route is
preserved by construction rather than by re-tuning, while the 30% of rooms
that currently have no real structural gate finally get one.

Open before implementing: the hero's own `colBallSize` record; whether the
indoor grid resolution (currently a global 8.0, versus a median indoor room
of 14.6 × 17.8 tiles) needs deriving from that radius; and the cross-level
case from §6f, which none of this addresses.

## 6h. TWO-AUTHORITY PASSABILITY — IMPLEMENTED (2026-08-04)

One engine, one flow field, one waypoint system, one progress validator, one
speech layer. The only thing that varies per room is **which model answers
"can the player move from here to there"**.

| Room class | Authority | Wall test |
|---|---|---|
| walk model > 8 triangles (118 rooms) | `WALK_MODEL` | `_segment_blocked`, untouched |
| walk model ≤ 8 triangles (51 rooms) | `HIT_MODEL` | `_swept_circle_blocked` at radius 4.0 |

### Rich rooms are preserved by construction, not by retuning

`_try_edge` branches on `geometry.authority` before any swept code is
reachable, and `_segment_blocked` was not modified. A test asserts the
stronger property directly: it monkeypatches `_swept_circle_blocked` to
record calls, builds the live-proven `M3_out` terrace route, and requires
**zero** invocations. Behaviour there cannot drift, because the new code is
not on that path at all.

### Configuration, not literals

- `DEGENERATE_WALK_MODEL_MAX_TRIANGLES = 8` — documented as a **proxy**, not
  the final classifier. Triangle count correlates with "does the walk model
  describe structure or only the floor plane"; it does not measure it.
- `ROOM_AUTHORITY_OVERRIDES = {}` — per-room escape hatch, empty by design.
- `DEFAULT_COLLISION_RADIUS = 4.0` — live-read (224 of 279 `peopleInfo`
  records), **not yet confirmed as the hero's own record**, and configurable
  per geometry for exactly that reason.
- `WALL_HEIGHT_BAND = 12.0` — keeps another floor's furniture out of this
  floor's obstacle set. The rich path still ignores height entirely; that
  is preserved, not propagated.

Grid resolution is deliberately **unchanged**. Changing authority and
resolution together would make any behaviour change unattributable.

### Validation

| Room | Authority | Nodes | Rejected edges | Route |
|---|---|---|---|---|
| `M3_out` | walk_model | 2968 | 2193 | **38 hops** (unchanged) |
| `D1_garage_1F` | hit_model | 184 | 185 | **7 hops** |
| `M3_pc_1F` | hit_model | 85 | 104 | **24 hops** |
| `M2_shop_1F` | hit_model | 100 | 109 | **23 hops** |

`D1_garage_1F` uses the exact player and target positions from the failing
live log of 2026-08-04 11:45–11:47 — the session where the guide failed
progress validation five times and abandoned the route. 768 tests pass.

### Measured connectivity, reported honestly

Connected components over the real edge predicate, per floored tile:

| Room | Floored tiles | Largest component | Next | Tail |
|---|---|---|---|---|
| `M3_pc_1F` | 168 | 85 (51%) | 33 | ~50 singletons |
| `D1_garage_1F` | 454 | 184 (41%) | 42 | 15, 10, 10, 9, … |
| `M2_shop_1F` | 180 | 100 (56%) | 26 | ~30 singletons |

Each room has one dominant open region, one secondary pocket, and a fringe
of individually-standable but hemmed-in tiles. The denominator counts every
tile with floor under it, including floor beneath counters and behind
service areas the player was never able to reach — so a dominant component
around half of that is plausible rather than obviously wrong. It is **not**
independently confirmed as correct.

The fringe singletons are a resolution artefact: a tile centre must sit ≥4.0
units from any obstacle, and centres are locked to an 8.0-unit lattice, so a
corridor the player fits through can still have no usable centre. Halving
the tile size does not fix it (`M3_pc_1F` 23.7% → 28.7% reachable from a
fixed seed), which is why resolution is a *separate* investigation rather
than an obvious win.

Also caught by this: a first validation attempt used the walk quad's
bounding-box corners as endpoints and reported `M3_pc_1F` unroutable. The
corners are behind the counter. The endpoint choice was wrong, not the room
— which is precisely the confusion `diagnose_unreachable` exists to prevent.

### Requirement 9 — attributable indoor failures

`diagnose_unreachable` returns one of `target_projection`,
`start_projection`, `radius_clearance`, `grid_alignment` (the tile centre is
blocked but a point inside the same tile is clear), `height_layer`, or
`floor_support`, with a sentence. `NavigationService` logs it on every
failed build alongside room, triangle counts, authority, and radius.

### Out of scope, recorded

The cross-level case from §6f is untouched. `height_layer` reports it rather
than solving it.

## 6i. THREE SEEDING BUGS, AND WHAT IS NOW THE BINDING CONSTRAINT

§6h fixed passability, and `D1_garage_1F` still failed live three more
times. Each log named its own cause on the first line — the main practical
argument for having built the diagnostics.

**1. `cause=target_projection`.** Routing failed *before* passability was
ever consulted. The garage's floor quad spans z −67.7…77.5 at y=0, while two
of its three interactable regions sit at z=−100.5 and z=−119.1, 47–48 units
below — the stairwell to the basement, which the flat walk model does not
cover. `resolve_node`'s ring search reaches 16 units; the gap is 33+.

→ `resolve_destination_node` projects an off-floor destination to the
nearest real floor within `DESTINATION_PROJECTION_MAX_RING` (8 tiles). It
runs only after the normal resolve has already failed, so it can turn a
failure into a route and can never move a destination that already works.

**2. Field built, player still unlinked.** The projected seed landed in a
pocket disconnected from where the player stood. "Nearest floor to the
target" and "floor the player can reach" are different tiles.

→ `flow_field_toward` tries the direct seed first, and only if the origin is
missing from the result floods from the *player*, takes the reachable tile
closest to the true target, and rebuilds seeded there. The second flood is
paid only by off-floor destinations.

**3. Still unlinked, with the seed in the ADJACENT tile.** The player's own
tile was being excluded: its centre lies within the collision radius of a
wall, so the flood refused to enter the one tile there was direct evidence
was standable — the player was in it. Their real position was 4.4 units
off-centre in an 8-unit tile, and only the centre is tested.

→ `exempt_tiles` in `flow_field_from`/`_try_edge`. Standing somewhere is
evidence it is occupiable. `resolve_destination_node` also now skips tiles
the player could not stand on, rather than seeding inside a counter.

A fourth bug sat underneath the first two and is worth recording separately:
`begin()` builds the route at activation, *before* any `next_waypoint`
supplies a player position, so the reachability fallback was reading a value
that is always `None` at the one moment it matters. `begin()`/`update()` now
take the player position from the audio guide, which has the pose at both
call sites. Live symptom: `flow_field_nodes=5`.

### Resolution is now the binding constraint

Both logged failure positions route. But:

- the garage's largest connected component is **41%** of its floored tiles;
- the second live position sat in a **six-tile pocket** — it routes 8 units,
  then hands off to the direct beacon.

A tile centre must clear obstacles by the player's full radius (4.0) while
centres are locked to an 8.0-unit lattice, so a corridor the player fits
through can have no usable centre. **Halving the tile size does not fix it**
(`M3_pc_1F` 23.7% → 28.7% reachable from a fixed seed), so this is not a
one-line constant change — it needs its own scoped design, and it touches
outdoor rooms too.

Passability is no longer the thing standing between an indoor room and real
navigation. Grid representation is.

## 6j. THE RADIUS WAS WRONG, AND TWO BUGS SAT UNDER THE RESOLUTION STORY

§6i named grid resolution as the binding constraint. That was **half
right**. Resolution is real and is now fixed. But before it could be
addressed, three things underneath it had to be corrected — and one of them
was not a resolution problem at all, it was a wrong constant that had been
flagged as unverified since §6g and shipped anyway.

### The last live session did not fail the way the handoff described

Read first, per the standing rule. Across the whole 60 MB tail of
`battle_narrator_phase1b.log` (2026-07-30 → 2026-08-04 12:41), the **only**
`cause=` ever emitted is `target_projection`, 22 times. `radius_clearance`,
`grid_alignment` and `floor_support` have never once fired in real play —
including `grid_alignment`, the diagnostic built specifically to detect the
resolution symptom.

The final session's pattern is unambiguous:

```
target_projection_offset=0.0    nodes=184   <- routes fine
target_projection_offset=75.1   nodes=184   <- routes fine
target_projection_offset=59.2   nodes=5     <- the "six-tile pocket"
target_projection_offset=59.2   nodes=6     <- again, 12:40:52
```

and the failing lines name the destination: `(72.99, −48.24, −119.07)`,
player at `y=0.00`. That is the basement stairwell, 48 units below the
floor. The six-tile pocket was never a lattice artefact — it was §6f's
cross-level case, converted by §6i's projection fallback from an honest
"no route" into a confident route into the south wall.

### Bug 1 — `resolve_destination_node` ignored height entirely

The ring search is purely horizontal. It projected a destination **48.2
units below** the floor onto the floor plane, 59.1 units sideways, and
seeded in a connected component the player cannot reach. Nearly 5×
`HEIGHT_CONTINUITY_TOLERANCE`, the module's own definition of one connected
surface.

→ `DESTINATION_PROJECTION_MAX_VERTICAL_GAP`, reusing that same constant so
projection and connectivity agree about what a level is. Applied to the
**lateral ring search only** — the direct branch moves the destination
nowhere, and guarding it broke `M3_out`'s worldmap exit, which legitimately
sits well above the terrace it belongs to. Caught by the suite, not shipped.

→ Refusing is not enough on its own, so `flow_field_toward` now falls
through to its reachability search when there is no seed at all, guiding to
the reachable point nearest the stairwell — what a sighted player does.
Bounded by the projection's own reach, so a destination with no floor within
`DESTINATION_PROJECTION_MAX_RING` on *any* level still gets nothing rather
than a confident route toward somewhere this room does not contain.

### Bug 2 — `exempt_tiles` let the flood enter through a wall

§6i's exemption ("standing somewhere is evidence it is occupiable") skipped
**both** the occupancy test and the wall-crossing test. Measured: edges
`(9,−8)→(8,−7)` and `(8,−8)→(8,−7)` are both genuinely swept-blocked, yet
the player's tile joined the pocket anyway. So `origin_node in
field.node_height` reported `True` for a tile they could not reach from the
seed, the reachability fallback never fired, and the log could not show why
— `reseeded_for_reachability` was computed but never printed.

→ The exemption now covers occupancy only. "You are standing here" is
evidence about the tile, not about the route into it. `reseeded` and
`relocated` are now in the route-build log line.

### Bug 3 — the collision radius was 4.0 and the hero's is 3.5

`DEFAULT_COLLISION_RADIUS = 4.0` was the `peopleInfo` table's dominant value
(224 of 279 records), adopted because the hero's own record could not be
indexed — the player's people-info ID comes from a runtime `HEROMOVE_MEMBER`.
§6g and the backlog both flagged it as unconfirmed. It shipped, and it was
wrong.

It can be pinned **behaviourally** without indexing anything. Every position
the engine ever let the player occupy is at least `colBallSize` from any
swept wall, so the closest observed approach is a direct upper bound. Over
the 311 distinct player positions logged for `D1_garage_1F`:

| | |
|---|---|
| minimum clearance ever observed | **3.495** |
| positions closer than 3.0 | 0 / 311 (0.0%) |
| positions closer than 3.5 | 86 / 311 (27.7%) — all in [3.495, 3.5) |
| positions closer than 4.0 | **211 / 311 (67.8%)** |

The floor is hard and is reached at **two independent contact points** — the
south wall at z=−52.2 (the player pressed against it, z pinned at −48.76
while x slid along) and a separate obstacle near (16.5, −22.1). The 0.005
shortfall against 3.50 is measurement error: logged positions are rounded to
two decimals and the swept test approximates each triangle by its longest XZ
edge. 3.50 is a real value in the table (14 records), so this corroborates a
record the hero plausibly has rather than fitting an arbitrary number.

**Two thirds of the positions the player was actually standing in were being
classified as inside an obstacle.** That is the true origin of much of the
indoor fragmentation attributed to resolution in §6h–6i: free space eroded
by 0.5 units everywhere, which is exactly enough to sever marginal corridors
no matter how finely they are sampled — and it is why halving the tile size
did not help.

### Then the resolution fix itself: relocate the node, don't shrink the tile

The graph may only place one node per tile, and it placed it at the centre.
Free space is not aligned to the lattice, so a corridor the player fits
through can miss every centre. Halving `TILE_SIZE` moved `M3_pc_1F` from
23.7% to 28.7% because density was never the problem — *placement* was.

`_best_clearance_point` samples each tile on a fixed 5×5 sub-grid
(`NODE_RELOCATION_OFFSETS`, ±0.375 of a tile, including the exact centre)
and puts the node at the roomiest point. `diagnose_unreachable` already
sub-sampled this way to tell `grid_alignment` from `radius_clearance`; the
graph now *uses* the point that diagnostic finds instead of only reporting
that it exists. Node count, `MAX_TILES` and every per-tile diagnostic stay
directly comparable, which shrinking the tile would have destroyed.

Relocating always beat relocating only when the centre fails, measured:

| Room | centres only | relocate if centre fails | relocate always |
|---|---|---|---|
| `D1_garage_1F` | 196 | 230 | **230** |
| `M3_pc_1F` | 85 | 97 | **113** |
| `M2_shop_1F` | 101 | 122 | **147** |
| `M2_hotel_1F` | 75 | 161 | **185** |

The extra gain is in *edges*, not occupancy: a tile whose centre is fine can
still have a blocked edge that a relocated point opens.

### Result

Largest connected component per floored tile, before → after (both changes):

| Room | before (r=4.0, centres) | after (r=3.5, relocated) |
|---|---|---|
| `D1_garage_1F` | 184 (40.5%) | **230 (50.7%)** |
| `M3_pc_1F` | 85 (50.6%) | **113 (67.3%)** |
| `M2_shop_1F` | 100 (55.6%) | **147 (81.7%)** |
| `M2_hotel_1F` | 73 (16.9%) | **185 (42.8%)** |

End-to-end against the real session: replaying **all 311** distinct logged
`D1_garage_1F` player positions, every one now routes — both to the basement
stairwell that produced the six-node pocket and to an ordinary in-room
destination. 311/311, zero unlinked, zero unseeded.

**`M3_out` is untouched by construction.** `node_point` returns the tile
centre unconditionally under `WALK_MODEL` authority, so relocation is not
merely disabled there, it is unreachable — the same structural guarantee as
the swept predicate. Verified: 2968 nodes (identical to §6h's table),
`relocated_nodes=0`, every node point equal to its tile centre, and a test
asserts that directly. Build cost: hit-model rooms 77–152 ms cold and
31–56 ms warm (the relocation memo is per-room and lives as long as the
cached geometry); `M6_out` and `M3_out` unchanged at 1.58 s and 0.23 s.

786 tests pass (was 774).

### Still open

- The radius is a bound from one room's live positions, not a read of the
  hero's `peopleInfo` record. A direct read should supersede it and should
  agree.
- Cross-level routing still is not *solved* — it is now diagnosed
  (`height_layer`) and degraded gracefully rather than faked.
- `_wall_spans_height` still has no minimum obstacle height: a 0.5-unit lip
  blocks exactly like a wall. Not indicted by any measurement here — the
  garage's blockers are all 34 units tall — but it remains unverified.
- The `M2_hotel_1F` largest component is 42.8%. Better than 16.9%, still not
  obviously right.

## 7. traversal_log.py — shelved

Built 2026-07-31 on the assumption that floor data was genuinely missing.
That premise is false (see §1–4), so inferring walkability from player trails
would be strictly worse than reading the surface the engine itself walks on.
The module is kept (documented, independently tested, zero importers) and
explicitly marked shelved. **Do not wire it into `NavigationService` without a
fresh, separate justification.**
