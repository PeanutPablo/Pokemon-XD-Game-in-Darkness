# ENTITY_POSITION_AND_INTERACTION_POINTS.md

Where each entity *is*, versus where the player must *stand* to use it.
**Phase 2, 2026-08-06. Revised 2026-08-09.** NPCs complete *in code*;
other categories carry the Phase 1 findings pending their phases.

> **⚠ §2 describes code production does not run** (reverted 2026-08-06).
> Production publishes the **static spawn position** and the **stale
> static visible bit** whenever no live actor is found for a
> `floor_character` record — which is the direct mechanism behind "entity
> navigation says an NPC is directly ahead and there is nobody there".
> `npc_beacons.py:342-363`.
>
> Measured consequence of the old range rule, 2026-08-06 → 2026-08-09:
> **2396** "Out of interaction range" against **4** "Interaction
> available", and all four of those were Items. Not one NPC in three days
> was ever reported interactable, including at 10-11 units from a clerk.
> Omitting both collision-ball terms under-reports range by ~7 units.

---

## 1. Why these are two different things

A blind player steered to an entity's model origin has been steered to the
right place only if the game measures interactions from that origin. For
NPCs it does not, and for CCD-region entities it does not even come close.
`Entity` therefore carries the world position in `position` and the
interaction reference in `metadata["interaction_position"]`.

## 2. NPCs

### World position — the live actor

`people_work +0x08` (model) `+0x18`. Read every query, never cached.

`floor_character +0x18` is the **scripted spawn point** and is now used for
nothing except a diagnostic drift measurement. Publishing it was how a
cutscene that walked a group out of a building left every bearing pointing
at where they started.

A static record with no live actor publishes **nothing at all**. This is
the structural fix for "entity navigation says an NPC is directly ahead"
when there is nobody there.

### Interaction position — the neck reference

`peopleTalkCheck` measures to `peopleGetNeckPos`, which is:

```
peopleGetPartsPos(group, res, peopleInfoBiosGetNeckIndex(info), out)
out.y = peopleBiosGetPosPtr(actor).y        <- Y from the ACTOR base
```

so the interaction point is **(neck joint X, actor base Y, neck joint Z)**
— not the model origin, and not a purely horizontal quantity.

`peopleGetPartsPos` reaches the joint through `GSmodelGetPart` →
`GSpartGetTransform`, which an external read-only companion cannot call.
It does not need to. Those calls *refresh* the joint's world matrix, and
the game refreshes it every rendered frame anyway; the value they return
is read straight back out of the JObj:

```
.L_80100394:  lfs f29, 0x50(r30)
              lfs f28, 0x60(r30)
              lfs f27, 0x70(r30)
```

which is the translation column of a 3×4 row-major matrix based at `+0x44`.

`model_parts.NeckPositionResolver` implements this:

| Step | Source |
|---|---|
| model → root JObj | `model +0x14` if `model[0x00] & 0x80` else `model +0x0C` (`modelGetRenderJObj`) |
| part index | `neckIndex + 1` if `model[0x00] & 0x20000` else `neckIndex` (`GSmodelGetPart`) |
| index → JObj | pre-order walk counting every node; `+0x08` next, `+0x10` child, do not descend when `+0x14 & 0x1000` (`HSD_JObjWalkTree0`) |
| JObj → position | `+0x50`/`+0x60`/`+0x70`, or `+0x38..0x40` when `+0x14 & 0x00600000` (blending) |

A negative `neckIndex` is the engine's own "no neck joint" case and falls
back to the actor base position — that is the engine's behaviour, not a
degradation.

**Measured live 2026-08-09, and the walk was wrong.** Offsets against a
4.0 collision ball: 0.18, 0.20, 0.50, **11.32**, **40.92** — with one actor
moving 0.50 → 11.32 in five seconds. Re-tracing the chain found three
divergences from the engine, all now corrected in `model_parts.py`:

| # | Divergence | Engine |
|---|---|---|
| 1 | the walk followed the **root's sibling chain** | `GSpartGetJObjPtr` calls `HSD_JObjWalkTree` (0x80252E40), which reads `root->child` and **never** `root->next`. An index past this model returned a joint from the *next model in memory* instead of failing — the shape of a 40-unit offset |
| 2 | the blend position was used on the **joint's** bits alone | `GSpartGetTransform` reads `+0x38` only inside the `GSmodelIsBlending(model)` branch (`model_flags & 0x80`); with blending off it always reads `+0x50/+0x60/+0x70` |
| 3 | a stale matrix was read as if current | the engine rebuilds via `HSD_JObjSetupMatrixSub` when `!(flags & 0x00800000) && (flags & 0x40)`. A read-only reader cannot rebuild, so that state now resolves to **None** |

Also settled while tracing, so they are not re-investigated:

- **No parent composition is needed.** `peopleGetPartsPos` calls
  `GSpartGetTransform(part, out, 0, 0)`; both trailing zeros skip the
  `parentList` block, and the value stored is the joint's own cached world
  translation.
- **The live pointer is the right object.** `peopleGetPartsPos` takes the
  model from `people_work +0x08` — the same pointer this project already
  resolves.
- **Part index 0 is the root**, both via `GSpartGetJObjPtr`'s short-circuit
  and via the counting callback.

**Status: corrected against the engine, live-validation pending.** The
resolver returns `None` on any failure and the source falls back to the
actor position. The collision-ball sanity bound in `LiveNPCEntitySource`
**stays** on top of this as corruption protection — it is not the fix, and
it was never tuned to hide the error.

**Expected magnitude, stated so it can be falsified:** for a standing
humanoid the neck joint sits nearly above the root, so `neck_offset` should
be well under one game unit, against a threshold around 10. If live
measurement confirms that, the neck reference is a correctness improvement
rather than the dominant fix, and the two corrections below matter more.
If it is larger — a clerk leaning over a counter, a non-humanoid actor —
the reference earns its cost. That is a measurement, not a prediction to
be assumed either way.

### Interaction *distance* — the real threshold

```
dist3D(heroPos, neckPos) <= heroColBallSize + talkDistance + npcColBallSize
```

| Term | Source | Previously |
|---|---|---|
| `heroColBallSize` | hero's `people_info +0x10` | absent |
| `talkDistance` | **live** `people_work +0x178` | static `people_info +0x24` |
| `npcColBallSize` | NPC's `people_info +0x10` | absent |
| allowance | none | `+ 1.5` |
| metric | 3-D | horizontal |

With realistic collision balls (~3.5 each) the old rule under-reported
range by roughly 7 units — the navigator said "out of interaction range"
where the game would have talked. `Entity.interaction_distance` now carries
the computed threshold, so downstream readers never re-derive it.

`profile.people_info_talk_distance_offset` (+0x24) is retained and logged
beside the live value. **Whether the static field initialises the live one
is unverified.** The diagnostic logs `talk_live=` and `talk_static=` on
every sample so the relationship can be established rather than assumed.

### What drives what

| Output | Position used | Why |
|---|---|---|
| clock direction | model position | where the NPC visibly is; a sub-unit joint offset must not swing a bearing |
| distance | model position | consistent with the bearing it is spoken beside |
| in-range / "Interaction available" | **neck reference, 3-D** | this is what the game tests |
| audio beacon | model position | unchanged; the beacon locates the character |
| final approach guidance | **neck reference** | the last few units are exactly where the difference matters |

Direction and distance stay on the model position deliberately: they are
descriptive, and jitter there is audible on every press. Eligibility uses
the authoritative reference, where being right matters and no smoothing is
applied. No smoothing has been added yet — it would be tuning ahead of
measurement, and the resolver's fallback already prevents a failed read
from producing a jumping target.

## 3. CCD-region entities — unchanged, still defective

Warps, doors, elevators, PCs and signs still announce the **centroid** of
their interaction region. Measured over all 843 regions in the 177
extracted rooms:

| Measurement | Median | p90 | Max |
|---|---:|---:|---:|
| centroid → nearest point of its own region | 0.00 u | 3.54 u | 168.9 u |
| centroid → farthest point of its own region | 18.40 u | 30.68 u | 340.9 u |

842 of 843 regions are large enough that a player standing legitimately
inside can be more than a full interaction radius from the announced
point. The fix — nearest point on the region, recomputed per query — is
**Phase 3b** and was explicitly out of scope for this phase.

## 4. Items and everything else

Unchanged in code from Phase 1: the item source still reads the treasure
kind from the wrong bits, still positions from the static spawn record,
and still infers opened state from a record vanishing. All **Phase 3**.

**Position sources, resolved 2026-08-09** (see
[ENTITY_NAVIGATION_ARCHITECTURE.md](ENTITY_NAVIGATION_ARCHITECTURE.md)
§8). The brief's instruction not to force every item through one formula
is correct, and the engine says why:

| Item form | World position | Interaction reference |
|---|---|---|
| item box (kind 1) | live actor model position | actor position **plus the box's own facing** — record `+0x02` is the s16 Y rotation fed to `peopleSetRot`, now **verified**, so the approach cone has an authoritative source |
| other placeable kinds (2, 3) | live actor model position | actor position, standard talk threshold |
| loose / story-spawned | live actor model position | actor position |
| **PokéSpot plate** | *not a treasure record at all* — an `esa_set` interaction region | nearest point on its region, method 3 |

Record `+0x10/14/18` is the **spawn** point written by `peopleSetPos` at
room load, not where the object is now. It is the same class of mistake as
publishing `floor_character +0x18` for an NPC, and it is what the item
source currently publishes.

Treasure actors also carry `peopleAddCollision`, so an item box is a
**physical obstacle** the router should route around rather than through.

## 5. Room-script interactables (Phase 4)

Same region geometry as warps and signs, so the same defect P1 applies and
the same fix cures it. The interaction reference is the **nearest point on
the region**, and the method byte says what to do on arrival: method 3 =
stand inside and press A; methods 1 and 2 = arriving *is* the interaction,
so no facing check and no talk cone apply.

---

## Region-backed navigation: areas, not centroids (2026-08-12)

**Every region-backed destination now routes to its interaction REGION, and
`VERIFIED` means an ordinary walkable route reaches that region.**

### What an interaction region is

A region is an AREA -- a trigger volume the player walks into -- held as its
own triangles by `region_geometry.Region`. Its centroid survives only as a
stable anchor for ordering and diagnostics. It is not, and must not become
again, the authoritative destination: measured over all 843 regions in 177
rooms, 210 have a centroid lying OUTSIDE their own geometry, worst case
168.9 units of empty space (`D3_out` index 1; `D1_out` index 2 is 161.9).

**Corrected 2026-08-12:** those two worst cases are NOT disjoint volumes, as
first assumed. Measured, both are a single connected region -- a long
concave strip -- whose centroid falls in the empty middle. Genuine
multi-volume regions do exist and were measured separately: **126 of 843
(14.9%)** have more than one component (124 with two, 2 with four, worst
`M1_pc_1F` index 3 and `D1_out` index 1). Their centroids sit much closer to
their geometry (0.7-15.1 units), so the two defects are independent:
concavity produces the extreme centroid errors, fragmentation produces the
"which volume am I being sent to" problem.

Spoken direction and distance already use `Region.nearest_point` relative to
the player (Phase 3b, 2026-08-10). Routing now uses the same geometry.

### Sources carrying their region

All five region-backed sources in `authoritative_warps.py` publish
`metadata["region"]`, which `AudioGuideReader` passes to
`NavigationService` and on to `pathfinding.flow_field_toward`:

| source | category |
|---|---|
| `AuthoritativeWarpEntitySource` | warp / exit |
| `AuthoritativeDoorEntitySource` | door |
| `AuthoritativeElevatorEntitySource` | elevator |
| `AuthoritativePCEntitySource` | PC |
| `AuthoritativeTextEntitySource` | sign |

True point-backed entities (NPCs) are deliberately unchanged; they route
against the real arrival radius instead.
`tests/test_authoritative_warps.py::RegionCarriedEndToEndTests` fails if a
source stops carrying its region, because a source that omits it silently
downgrades to the point path and nothing else would notice.

### Acceptance is connectivity, not distance

`pathfinding.destination_target_tiles` derives ARRIVAL TILES from the
region's triangles (or the arrival radius for a point). A route is accepted
only when an ordinary walkable path -- same walk layers, wall tests,
collision radius, corner rules, floor support -- reaches one of them, and
the field is then re-seeded there so the route is continuous into the
region. `REACHABILITY_FALLBACK_MAX_OFFSET` and every distance-based
acceptance rule are **retired**.

Why: measured over all 3230 interaction-point pairs, the old 64-unit rule
accepted 2024 routes of which only 265 were locally useful. Above the real
4-unit arrival radius, distance carries no signal at all -- the hit rate is
5-11% in every band, and 74.4% of reseeds landing within 8 units of their
destination were still on the far side of a wall.

### Coverage is intentionally lower

Routed coverage fell from 69.3% to roughly 43% of interaction pairs. That
drop is the false routing being removed, not capability being lost. The
invariant that matters is zero known false `VERIFIED` routes.

### Known outcomes worth remembering

- `M3_cave_1F_1` (Relic Stone cave) refuses toward the shrine exit with
  `cause=disconnected`; the pair that genuinely connects still routes.
- `D1_garage_1F`'s basement warps refuse: no walk surface exists beneath
  either region anywhere in that room. They are the stairs to another
  floor, and the old rule "worked" by guiding 70 units to the south wall.
- Cross-level destinations remain diagnosed, not solved.
