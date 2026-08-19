# Region-aware routing — live test plan

**Prepared 2026-08-12. NOT STARTED.** The watcher must not be launched until
the project owner says they are ready.

One action at a time. Each step is a single guide activation toward a single
entity, followed by a stop. Do not chain steps.

## Before starting

1. Launch via `Start Battle Narrator.bat` on the Desktop — it now stops any
   companion already running, so the session cannot be measuring stale code.
2. Confirm the build from the log's first route line. It must read
   `passability=swept radius=3.50`. If it reads `radius=4.00` or carries
   `authority=`, the process is stale and nothing below is evidence.

## What to capture per step

The `NAVTRACE` lines already carry most of this. For each activation record:

| field | source |
|---|---|
| entity category and label | `AUDIO GUIDE` speech line |
| region identity | `metadata["region"]` index |
| selected region component | route build line |
| nearest target point | entity position (already `Region.nearest_point`) |
| player node / component | `NAVTRACE build_ok start_direct` |
| destination component | `target_final` |
| route confidence | `NavigationResult.confidence` |
| final arrival | `AUDIO GUIDE Arrived.` or the fallback line |

## The steps, in priority order

These are ordered by the user-facing failures that drove this work.

1. **Indoor door.** Any building interior with a door out. Expect a routed
   path that ends inside the door's trigger volume, then `Arrived.`
2. **Indoor elevator.** Expect the same. Elevators were previously routed to
   a centroid that could sit outside the region.
3. **PC.** A Pokémon Centre PC. Point-like region; checks the arrival-tile
   path for a small region.
4. **Sign.** Checks that a sign's region is reached rather than approached.
5. **Warp / exit.** A building entrance. Note that 72 of 150 doors share a
   region with a warp, so both entities may name the same place.
6. **Large or disjoint interaction region, if one is reachable.** `D1_out`
   index 2 and `D3_out` index 1 are the known pathological ones — centroids
   161.9 and 168.9 units outside their own geometry. If either is reachable
   in play, confirm the guide points at the region and not at empty space.
7. **A previously troublesome indoor route.** `D1_labo_B1` or `D1_labo_B3`,
   where the old rule false-routed 75 of 91 and 31 of 36 pairs.

## What counts as success

- Every routed guidance ends inside or at the destination's region.
- Anything the graph cannot connect says **"No walkable path found; guiding
  directly."** exactly once and hands to the beacon.
- No `VERIFIED` route ends anywhere other than the destination region.

## What counts as a defect worth stopping for

- A routed path that ends short of the region and still announces arrival.
- The guide pointing at empty space for a region-backed entity.
- A destination the player can plainly walk to being refused.
- A multi-second stall on activation (see the known `M6_out` cost).

## Known-expected refusals — not defects

- `D1_garage_1F`'s two basement warps. No walk surface exists beneath either
  region in that room; they are the stairs down.
- `M3_cave_1F_1`'s shrine exit. The cave's passage reads as disconnected
  pockets in the collision data. This is a real remaining limitation, and
  investigating the cave's wall semantics is deliberately deferred.
