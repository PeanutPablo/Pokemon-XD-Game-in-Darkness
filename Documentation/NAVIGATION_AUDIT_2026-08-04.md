# Navigation and waypoint system — independent audit

**Date:** 2026-08-04 (evening)
**Scope:** everything behind the routed guide — `pathfinding.py`,
`navigation_service.py`, `audio_guide.py`, and the CCD data they read.
**Method:** read the shipped code and `WORLD_NAVIGATION_ARCHITECTURE.md`
without assuming either is correct, then re-measure every load-bearing claim
against the 177 real `.ccd` files and against every player position the live
log has ever recorded.

Two reported symptoms drove this: **the guide routes through walls**, and
**the guide sends the player back and forth when the destination is only a
short way ahead.** Both reproduce from data. Both have identified causes.
One of those causes is a documented conclusion in
`WORLD_NAVIGATION_ARCHITECTURE.md` §6g that this audit finds is not
supported by the measurement it cites.

---

## 0. Before anything else: the live failures were produced by stale code

Every route-build line in the log, up to and including 17:51 today, reads
`radius=4.00` and carries no `reseeded=`/`relocated=` fields:

```
2026-08-04 17:51:03.610 NAVIGATION route build floor=0xA room=D1_labo_B3
   authority=walk_model radius=4.00 nodes=2688 ... duration=0.1570s
```

The shipped `pathfinding.py` has had `DEFAULT_COLLISION_RADIUS = 3.5` since
13:15 today, and `navigation_service.py` has logged `reseeded`/`relocated`
since 14:20. The companion process has been running since before 12:22 and
has never been restarted, so **none of today's afternoon failures exercised
the radius correction or node relocation from §6j.**

Restarting the companion is the cheapest possible first action. It will not
fix the two structural defects below, but it changes what the next live
session is evidence *about*.

`radius=` in the route-build line is a reliable version stamp. It is worth
checking before treating any future live report as evidence against the
current code.

---

## 1. The collision radius is 3.50, and this is now corroborated four ways

§6j pinned the hero's `colBallSize` behaviourally at 3.5 from 311 logged
positions in one room, because the hero's own `peopleInfo` record cannot be
indexed. That method generalises, so this audit ran it across every room the
log holds positions for — measuring each position's distance to the nearest
hit-model triangle whose Y span covers the player:

| Room | positions | min clearance | < 3.0 | < 3.5 | < 4.0 |
|---|---|---|---|---|---|
| `D1_garage_1F` | 469 | **3.495** | 0 | 24% | 69% |
| `D1_labo_B1` | 38 | **3.496** | 0 | 21% | 63% |
| `D1_labo_B2` | 68 | **3.351** | 0 | 28% | 60% |
| `D1_labo_B3` | 41 | **2.684** | 1 | 15% | 51% |

Four independent rooms, four independent geometries, and the distribution
bottoms out at the same value each time. **3.50 is confirmed.** 4.00 is
refuted independently in each room — between 51% and 69% of positions the
player genuinely occupied would be classified as inside an obstacle.

The two sub-3.5 outliers (3.351, 2.684 — one position each) are consistent
with the known approximation error: logged positions are rounded to two
decimals, and the swept test models each triangle by its longest XZ edge,
which overstates a triangle's extent near its corners.

Also settled by the same pass: **`collision_type` does not discriminate
passability.** Types 0–7 all appear, and in every room the closest observed
approach to *every* type is the same ~3.5. No type is ever walked through.
Whatever the field means (material, footstep sound, render hint), it is not
a "the player may pass this" flag, and treating all vertical hit triangles
as blocking is correct.

---

## 2. Defect A — routing through walls: the authority classifier is wrong,
and the reason it exists does not hold

### 2.1 What the classifier does today

`classify_authority` gives a room the strict swept-circle test only when its
walk model has **≤ 8 triangles**. Above that, the room keeps
`_segment_blocked` — which opens a tile-to-tile edge if **any one of five
sampled lines** is clear.

`DEGENERATE_WALK_MODEL_MAX_TRIANGLES`'s own docstring already calls the
count "a PROXY, not the final classifier." Live data now indicts it
directly. These are the rooms the player has actually been navigating in
today:

| Room | walk tris | wall tris | authority today | walk area per triangle |
|---|---|---|---|---|
| `D1_labo_B3` | 76 | 948 | `walk_model` | 2278 |
| `D1_labo_B2` | 14 | 416 | `walk_model` | 4156 |
| `D1_labo_B1` | 1010 | 880 | `walk_model` | 388 |
| `M3_out` (outdoor, proven) | 570 | 1097 | `walk_model` | 363 |
| `D1_garage_1F` | 2 | 140 | `hit_model` | 15099 |

`D1_labo_B2` clears the threshold by **six triangles**. Its walk model is a
floor plane (4156 units² per triangle, single layer); all 416 of its
structural triangles are in the hit model — and it gets the permissive
outdoor test. `D1_labo_B3` is the same story at 76 triangles.

Across all 177 rooms, **171 have exactly one walk-model layer.** Only
`M3_out` (5), `D5_factory_top` (3), `M5_labo_1F` (2) and `M6_tower_1F` (2)
have more. The layer-set connectivity machinery — the core of the 2026-08-01
rewrite — is doing real work in four rooms and is a no-op in the other 173.

### 2.2 The cost, measured

Rebuilding the same routes with the swept test instead:

| Room | nodes today (permissive) | nodes with swept r=3.5 + relocation |
|---|---|---|
| `D1_labo_B3` | **2688** | **61** |
| `D1_labo_B2` | 934 | 158 |
| `M3_out` | 2968 | 1837 |

In `D1_labo_B3` the guide is routing over a graph **44× larger than the
space the player can actually occupy.** That is the through-walls report,
quantified. It is not a tuning problem; the room's only structural gate is a
test that opens an edge on one clear line out of five, and that room's
structure is entirely in the model that test barely consults.

### 2.3 Why the protection this classifier provides is not needed

§6g concluded that a global swept test "would have broken outdoor routing
outright," from this measurement on the live-proven `M3_out` terrace route:

> Clearance from each **tile centre** on the route to the nearest vertical
> hit-model triangle: min 0.10, median 3.98, **22 of 38 tiles failing a
> swept radius 4.0**.

That measurement is of **tile centres**, not of player positions. A tile
centre 0.10 units from a cliff face is not evidence that the player walked
0.10 units from a cliff face — it is evidence that *the tile centre is not
standable*, which is exactly the condition node relocation (§6j) was built
to fix. The conclusion drawn from it — "hugging geometry is normal
outdoors" — has no supporting player-position measurement anywhere in the
project. Every player position that *has* been measured (§1 above) obeys the
3.5 bound.

Both inputs to that measurement have since been corrected, and both
corrections were deliberately withheld from `WALK_MODEL` rooms by
construction. Re-running it with the corrections applied:

| `M3_out`, live-proven terrace journey | nodes | relocated | hops | length |
|---|---|---|---|---|
| current (permissive, centres) | 2968 | 1 | 10 | 82.4 |
| swept r=4.0, centres (the §6g measurement) | 1595 | 1588 | 8 | 68.1 |
| **swept r=3.5 + relocation** | **1837** | **1762** | **13** | **122.9** |

**The outdoor route survives.** It gets longer (122.9 vs 82.4 units) because
it now goes *around* what it previously cut through. The premise that
sweeping is unsafe outdoors is not supported at the corrected radius.

A per-triangle alternative was tried first and is recorded as **failed**:
classifying each wall triangle as "interior obstacle" (walkable floor on
both sides at the same height) versus "terrain edge" separates `M6_out`
cleanly (30 interior of 900) but misclassifies `M3_out`'s ramp flanks as
interior and would reject 10 of that route's 17 hops. It is not a usable
discriminator. Recorded so it is not re-attempted.

### 2.4 Honest uncertainty

61 nodes for `D1_labo_B3` may be too few, not just 2688 too many. Both
numbers are flood-reachable counts from the same destination, so the
comparison is like-for-like, and the specific journey tested still routes
(9 hops, 83.7 units — shorter than the permissive route's 10 hops / 105.1,
so the permissive graph was also detouring). But the true usable node count
lies somewhere between the two and this audit has not established where.
That is the question a resolution pass should answer, and it should be
answered *after* the passability test is right, not before.

---

## 3. Defect B — back and forth: the waypoint cursor cannot skip a waypoint
it has already walked past

### 3.1 The mechanism

`next_waypoint` commits a waypoint sequence when the route is built and then
advances it **only** by `route.waypoint_cursor += 1`, and only when the
player comes within `WAYPOINT_STABLE_RADIUS_RATIO * tile_size` = **7.2
units** of the *current* waypoint (`navigation_service.py:1023`).

There is no look-ahead. Nothing asks "is a later waypoint in this sequence
now closer than the current one," and nothing asks "have I already passed
this one." So a player who walks a slightly different line and misses
waypoint N by 8 units gets a beacon that now points **behind them**. They
turn around, capture it, and the next waypoint sends them forward again.
That is the reported back-and-forth exactly.

The only escape is `SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS`, which needs
**160 units** of travel before it fires — 5 to 9 seconds of walking at the
measured 17–35 units/s.

Committing the sequence was itself a correct fix for a real U-turn failure
(§6a); the defect is that commitment was implemented as "advance by one, or
not at all."

### 3.2 It reproduces in the log

Replaying every guide activation and comparing the aim point against the
direction the player was actually travelling — counting only polls where the
player had moved at least 1 unit, and only aim points more than 120° behind
their travel direction:

```
121 guide activations, 33 with three or more waypoint changes
25 backward-aim events, spread across 15 separate activations
```

Roughly **half of all substantive journeys contain at least one moment where
the guide turns the player around.** Supporting counters over the same span:
**4374** polls reporting "player node not linked to destination", and
**207** progress-validation failures.

Some doubling back is legitimate — a real route around an obstacle does
reverse. But the signature here is the aim flipping to behind the player
*immediately after they moved*, which a genuine route reversal does not
produce.

### 3.3 A contributing factor: the camera basis rotates while you walk

Every direction cue — pan and pitch in `guide_values`, the clock positions
in entity nav — is expressed in **camera space**, correctly, because this
game has no turn-to-face action and stick input is camera-relative.

But the field camera's yaw is **not constant within a room**. Each floor
loads a field-camera list, and where it holds more than one entry the engine
blends their yaws by inverse-square distance to the player, every frame
(`floorFieldCamera.s`; `npc_beacons.player_pose` reads the blended value
live each poll, which is right). `WORLD_NAVIGATION_ARCHITECTURE.md` §6a
notes Gateon Port holds eight cameras spanning 67°, though that figure has
no recorded derivation and should be re-measured.

The consequence: holding one stick direction while walking a straight line
does not keep you on a straight line, because the mapping from stick to
world rotates underneath you. Small drift is expected, and small drift is
precisely what makes a player miss a 7.2-unit capture window. This does not
cause the back-and-forth on its own — the cursor defect does — but it makes
the miss that triggers it far more likely, and it is worth measuring
directly (log camera yaw per poll; check whether backward-aim events cluster
in multi-camera rooms).

---

## 4. On "route backwards, simulate many times, pick the fastest and most
accurate"

Two halves, answered separately.

**The backwards part is already the design and is correct.**
`flow_field_from` seeds at the destination and floods outward with
`next_hop` pointing back toward it, so every reachable tile in the room
simultaneously knows its own optimal route to the entity. This is strictly
better than tracing forward from the player: it is one pass instead of one
per query, and it stays valid as the player moves.

**Running it repeatedly would return the identical answer.** Dijkstra is
deterministic and already optimal for the graph it is given. §6a records
this being tested — six identical builds — during the first-waypoint
instability investigation. Repetition cannot help.

**What the request is actually pointing at is real, and the diagnosis is
better than the proposed mechanism.** The single route produced is optimal
in the wrong metric. `uniform_edge_cost` is pure tile-hop distance
(`pathfinding.py:1058`): no clearance term, no turn penalty, no term for how
followable a route is by ear. "Fastest" is achieved; "most accurate" is
never measured. So the productive form of "generate several and pick the
best" is **several genuinely different candidates, not several identical
ones**:

- flood once per cost function — shortest, maximum-clearance (prefer the
  middle of corridors), fewest-turns — which is three floods, not N;
- score each on followability: minimum clearance along the path, number of
  direction changes, and how much of it runs within a tile of an obstacle;
- pick the best-scoring, not the shortest.

That gives what was asked for, in a form where the repetition does work.
It is a later step than the two defects above, and would be premature until
the graph being searched is correct.

---

## 5. Recommended order of work

Deliberately ordered so each step is independently verifiable and the next
one's evidence is not contaminated by the last one's bug.

1. **Restart the companion.** Zero cost. Puts the radius fix and node
   relocation into play and makes the next live session evidential.
2. **Make the swept circle the single passability test everywhere, at
   r=3.5, with relocation on** — deleting `PassabilityAuthority`,
   `classify_authority`, `DEGENERATE_WALK_MODEL_MAX_TRIANGLES`,
   `ROOM_AUTHORITY_OVERRIDES` and `_segment_blocked`. Keep the walk model as
   the sole authority on *floor support and layer connectivity*, which is
   what §1–§4 of `WORLD_NAVIGATION_ARCHITECTURE.md` actually established;
   the hit model becomes the sole authority on *obstruction*. Regression
   bar: `M3_out`'s terrace journey must still route (it does — §2.3), and
   every one of the 469 logged `D1_garage_1F` positions must still route.
   The existing test that asserts zero swept calls in `M3_out` is asserting
   the defect and should be replaced with one asserting the route survives.
3. **Give the waypoint cursor look-ahead.** On each poll, scan forward in
   the committed sequence and advance to the furthest waypoint whose
   preceding leg the player has demonstrably passed. This keeps the U-turn
   protection commitment provides (never re-derive from the live node) while
   removing the "walk back to a waypoint you already overshot" failure.
   Regression bar: replay the 25 logged backward-aim events; none should
   survive.
4. **Then, and only then, re-open grid resolution** (§2.4) with a correct
   passability test underneath it, and the multi-cost candidate scoring in
   §4 on top of it.
5. **Separately: measure the camera-yaw drift** (§3.3) before deciding
   whether it needs compensating.

## 6. Implemented (2026-08-04, late)

Steps 2 and 3 of §5 are done. Step 1 is the user's (the launcher now does it
automatically — see §6.4). **784 tests pass.**

### 6.1 One passability test, every room

`PassabilityAuthority`, `classify_authority`,
`DEGENERATE_WALK_MODEL_MAX_TRIANGLES`, `ROOM_AUTHORITY_OVERRIDES`,
`_segment_blocked` and `GAP_SAMPLE_OFFSETS` are **deleted**. The walk model
keeps sole authority over floor support and layer connectivity; the hit
model is now the sole authority over obstruction, via a swept circle at the
hero's radius. Node relocation applies everywhere, not only indoors.
`_swept_points_blocked` was factored out to take raw points, so the same
primitive serves both tile edges and arbitrary line-of-sight segments.

Regression bars, all met:

| Bar | Result |
|---|---|
| `M3_out` terrace journey still routes | **yes** — and a test asserts the swept test really is invoked there, so it survives because it passes, not because it is skipped |
| Every logged player position still routes | **631/631** across `D1_garage_1F` (469), `D1_labo_B1` (48), `D1_labo_B2` (68), `D1_labo_B3` (46) |
| Every logged `M3_out` position clears 3.5 | **yes**, min 3.498 — now a test |

Two tests asserted the old defect and were **inverted**, not deleted:
`test_swept_test_is_never_used_in_a_rich_room` (required the swept predicate
to be unreachable outdoors) and
`test_relocation_never_happens_in_a_rich_walk_model_room` (required outdoor
nodes to stay pinned to tile centres — the pinning that produced §2.3's
circular measurement in the first place).

### 6.2 The staircase theory — BUILT, THEN REVERTED. It was wrong.

**Status: reverted at the project owner's instruction. Do not rebuild it.**

§3 originally diagnosed the west-east-west report as waypoint overshoot.
The project owner corrected that: what they meant was a waypoint to the
west, then one to the east, then west again. That pointed at a second
mechanism, which was implemented and then also rejected. Recorded in full,
because the measurement behind it is real and will otherwise be re-derived.

**The theory.** An optimal path on a square grid whose bearing is not a
multiple of 45° must alternate between orthogonal and diagonal steps.
`simplify_route` kept a waypoint at every one of those alternations, since
each has a non-zero cross product and it only collapsed exactly-collinear
runs. So a nearly straight walk was announced as a zigzag.

**The measurement, which stands.** On real routes:

| Route | path vs straight line | waypoint bearing swings |
|---|---|---|
| `D1_labo_B3` | 1.08× | −55 +45 0 +45 −45 −45 |
| `D1_labo_B1` | 1.41× | +13 −45 0 +45 −90 −45 |

Two left-right reversals apiece on walks that are essentially straight. The
staircase is genuinely present in the waypoint sequence.

**The fix worked, on its own terms.** A greedy line-of-sight string pull
(possible only because universal passability supplied the swept test the
old code said it lacked), plus raising `WAYPOINT_SPAN_MIN` from 2 tiles to 4
so node-placement jitter could not dominate a leg's bearing, took audible
reversals to **zero on all four routes measured**.

**And it was still not what the project owner was hearing.** So the
staircase is a real property of the waypoint sequence that is *not* the
cause of the reported symptom. Both changes are reverted; `simplify_route`
is back to the collinear-only collapse and `WAYPOINT_SPAN_MIN` back to 2
tiles.

**Two candidate explanations for west-east-west are now ruled out** — the
overshoot of §3.1 and the staircase above — and no third has been
identified. See §6.7: the log cannot currently distinguish them, which is
now the binding constraint on diagnosing this at all.

### 6.3 The cursor can now skip a waypoint already passed

**Kept, but on its own evidence only** — not as an explanation of the
west-east-west report, which §6.2 leaves unexplained.

`_advance_past_reached_waypoints` advances the committed cursor past every
waypoint whose `cost_so_far` is no lower than the player's own — an exact
test using data already in hand, not a geometric guess, and it cannot
oscillate because the field is fixed for the route's lifetime and the cursor
only increases. It never re-derives the sequence, so §6a's U-turn protection
is intact.

Two follow-on defects surfaced while testing it, both fixed:

- moving the cursor was not enough on its own — `current_waypoint_node` is
  otherwise only reassigned inside the capture branch, so the guide kept
  aiming at the waypoint it had just decided the player was past (the aim
  stayed pinned at x=17.0 while the player walked to x=148.0);
- getting *past* a waypoint has to count as progress the same way reaching
  one does, or the look-ahead silently swallows the confirmation cue and the
  rebuild-budget replenishment from §6a.

### 6.4 The launcher now stops what is already running

`Start Battle Narrator.bat` kills any Python process whose command line
references this project before starting a new one (verified: it matches the
venv stub and its child, and nothing else on the machine). This is §0's
finding made structural — a stale process cannot silently keep running.

The route-build log line now carries `passability=swept` where it used to
carry `authority=walk_model`/`hit_model`, so the build's identity is
readable straight from the log.

### 6.5 A pre-existing bug found by an optimisation that should have been free

`_best_clearance_point` seeded its search with `best = None` and took
offsets starting at −0.375, so the **first** sample — the tile's corner —
won every tie. On any tile with uniform clearance (all of open ground, where
it is infinite everywhere) the node was placed at the corner rather than the
centre: the exact opposite of what the function's own comment claimed. It
survived because `NODE_RELOCATION_OFFSETS` reads centre-first and the
comment asserted the loop did too.

It was caught only because an "empty obstacle ring ⇒ clearance is infinite
everywhere ⇒ return the centre" short-circuit, which is provably equivalent,
changed `M6_out`'s node count. Now fixed by seeding with the centre.

A second, earlier optimisation (`RELOCATION_SKIP_CLEARANCE`, "skip the scan
when the centre is comfortably clear") was **removed**: once
`wall_candidates_around` was memoized it saved nothing measurable, and it
changed `D1_labo_B2` from 175 nodes to 176. A shortcut that changes the
answer has to earn it.

### 6.6 Cost, stated plainly

`wall_candidates_around` was memoized after profiling showed it was the
single largest cost in a flood fill (794,449 calls, 5.4 s of 18 s). Even so,
route builds are slower than before, because a real swept collision test is
genuinely more work than five sampled lines:

| Room | nodes | cold | warm |
|---|---|---|---|
| `M6_out` (largest in the game) | 21485 | **4.0 s** | 2.3 s |
| `D3_out` | 14830 | 4.4 s | 1.7 s |
| `M3_out` | 1637 | 1.1 s | 0.4 s |
| `D1_labo_B1` | 324 | 0.2 s | 0.2 s |

`M6_out` was ~1.58 s before. The route is built synchronously on guide
activation, so in Gateon Port that is ~4 seconds of silence on the first
activation in a session (subsequent ones in the same room are warm). The
comparison is not like-for-like — the old 1.58 s bought a route through
walls — but it is a real regression in responsiveness and is the most
likely thing to be noticed next. Not addressed here.

### 6.7 What could not be verified offline

An end-to-end replay of the logged sessions **cannot** confirm the
backward-aim fix, and the attempt was discarded rather than reported. The
log records a player position only when the waypoint changes, and never
records the destination at all, so a replay has to fabricate both the target
and the travel direction between sparse samples. The harness scored 61% of
polls as "backward" with every fix disabled — measuring its own noise.

The mechanism is instead covered by a direct test
(`WaypointOvershootTests`), and the geometry claim by the swing measurements
in §6.2, which use real route geometry rather than fabricated movement.

**This is now the binding constraint, not a nice-to-have.** Two theories of
the west-east-west report have been built and rejected (§3.1, §6.2), and the
log cannot distinguish a third from either of them, because it does not
record what the guide was aiming at or where it was trying to go. What is
needed, per waypoint change and per poll where the aim moves:

- the destination the route was built for;
- the aim point actually handed to the audio guide;
- the player's position and resolved node;
- the committed sequence index, and whether it moved this poll.

Until that exists, any further theory of this symptom is guesswork that
costs a build-and-revert cycle to test.

## 6h. THE ROUTER IS NOW TRUTHFUL: connectivity, not distance (2026-08-12)

The §6.2/§6.3 work above bounded the reachability fallback at 64 units. Two
further audits killed that idea and replaced it.

### The split audit — how much of the old behaviour was misleading

Reproducing the pre-bound rule offline over all **3230** interaction-point
pairs:

| | |
|---|---|
| previously false-routed | **1070** |
| always failed | 0 |
| resolve/projection failure | 14 |

`always failed = 0` is the finding, not a clean bill: **the old fallback
never failed.** It took the nearest reachable node with no ceiling, and the
player's own field is never empty, so it always returned something. There
was no such thing as an honest refusal on that path.

Not one of the 1070 ended within 32 units of where it claimed to go —
median **135.4**, max **1678.2**, closest miss **59.0**. And **190 had zero
hops**: the guide announced a walkable route and pointed at the tile the
player was already standing on, up to 1546 units from the target.

### Bucket 3 — the accepted routes were no better

Of the 2024 routes the 64-unit bound *accepted*, measured against each
destination's real interaction region:

| distance to region | useful / total |
|---|---|
| ≤4 | 103 / 103 (100%) |
| 4–8 | 46 / 480 (9.6%) |
| 8–16 | 54 / 478 (11.3%) |
| 16–32 | 22 / 440 (5.0%) |
| >32 | 40 / 523 (7.6%) |

**265 of 2024 (13.1%) were locally useful; 1759 were on the far side of a
wall.** Above the real 4-unit arrival radius, distance carries no signal —
the >32 band scores better than 16–32. In the 8–32 marginal band, 842 of 918
were locally disconnected, and the blocker was a **wall in 837 of them**.

Every candidate ceiling — 16, 32 or 64 units, measured to the anchor or to
the region — misled the player in **79–87%** of the routes it accepted.

### What replaced it

`REACHABILITY_FALLBACK_MAX_OFFSET` is **deleted**. A reseed is accepted only
when an ordinary walkable path reaches the destination's own arrival tiles —
the region's triangles for a region-backed destination
(`region_geometry.Region`, already in production since 2026-08-10), or the
tiles within the real `ARRIVAL_RADIUS` for a point destination. Same walk
layers, wall tests, collision radius, corner rules and floor support as the
flood fill; no second projection underneath. The field is then re-seeded on
that arrival tile, so the accepted route is continuous into the region
rather than ending short and hoping the beacon covers it.

Tile intersection, not proximity, decides what counts as an arrival tile.
The lattice is 8 units and a node sits up to ~5.7 units from a given point
in its tile, so a 4-unit proximity test reported **zero** reachable nodes
touching the cave region the player was standing in; tile intersection
correctly identifies the two cave regions that genuinely connect.

### Garage — investigated, not exempted

Both `D1_garage_1F` basement warps now **refuse**. This room's walk model has
no surface beneath either region and no reachable node shares a tile with
them: they are the stairs to another floor. The old rule "worked" by guiding
70 units to a spot by the south wall and reporting `VERIFIED`. The room's
in-room region still routes. No room is special-cased.

### Cave — preserved as the canonical regression

`M3_cave_1F_1` still refuses toward the shrine exit with `cause=disconnected`,
and the pair that genuinely connects (regions 1↔2) still routes.

## 7. Explicitly not established

- Whether 61 nodes is the right answer for `D1_labo_B3`, or merely a better
  wrong answer than 2688 (§2.4).
- What `collision_type` (hit model) and `raw_metadata_byte` (walk model,
  `0xFF` in every room sampled) actually mean. Only that the former does not
  gate passability (§1).
- Whether the second hit model (CCD `+0x34`) matters. Still unread,
  unchanged since §1 of `WORLD_NAVIGATION_ARCHITECTURE.md` flagged it.
- The Gateon Port "eight cameras, 67°" figure, which remains underived.
- Whether camera-yaw drift measurably contributes to waypoint misses (§3.3)
  — the mechanism is real, the magnitude is unmeasured.
- Cross-level routing within one room, untouched and still only diagnosed
  (`height_layer`), exactly as §6f/§6j left it.
- **What actually causes the west-east-west waypoints.** Two theories built
  and rejected (§3.1 overshoot, §6.2 staircase). No third proposed. Blocked
  on the logging in §6.7.
- Whether the backward-aim fix works in real play — see §6.7. The mechanism
  is tested; the live outcome is not measurable from the current log.
- Whether ~4 s of silence on the first Gateon Port activation (§6.6) is
  acceptable in practice.
- Grid resolution (§2.4), deliberately left for after this lands live.
- The multi-cost candidate scoring of §4, which only makes sense on a graph
  that is already correct.
