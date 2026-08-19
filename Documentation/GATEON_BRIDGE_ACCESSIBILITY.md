# GATEON_BRIDGE_ACCESSIBILITY.md

Gateon Port's moving bridges: what owns them, what is proven, what is
hardcoded, and what has to happen before they become navigable
destinations.

**Written 2026-08-09** as a Phase 1 (audit) deliverable; **revised the same
day** when bridge connection points were pulled forward and shipped as
their own entity-navigation category at the project owner's request.

> ## Shipped 2026-08-09 — `bridge` entity-navigation category
>
> `bridge_connections.py` publishes one entity per connection the pier's
> **current** alignment offers, updated live from general flag 968 on every
> query. Stale connections disappear on rotation; the alignment change
> advances a generation. Nothing is hardcoded — the state table is
> **parsed** from the extracted room script, and the decks, the compass
> directions and the positions are **derived** from `M6_out.ccd`.
>
> **POLARITY CORRECTED 2026-08-18 — see §2.4.** From 2026-08-09 to
> 2026-08-18 this document and the reader both claimed `enable == 1` means
> CONNECTED. It means **BLOCKED**, so for nine days the category listed
> exactly the directions the player could not cross. §2.2's original
> description of entries 23-31 as the bridge's *blocking* geometry was
> right.

> The audit brief refers to "Codex's Gateon Port/bridge documentation."
> **No such document exists in this repository.** It was looked for in
> both audit passes. All bridge knowledge in the project lives in
> `gateon_bridge.py`'s module docstring, the extracted `M6_out` script
> under `Research/GateonBridge/`, and
> [ENTITY_NAVIGATION_ARCHITECTURE.md](ENTITY_NAVIGATION_ARCHITECTURE.md)
> §3.7. This document is the missing record. If a Codex bridge document
> exists outside the repository, it should be merged here rather than kept
> separately.

---

## 1. Ownership chain

```
general flag 968            (four values: 0, 1, 2, 3)
   |
   +-- read by M6_out's `pier_def`
   |      -> GScolsys2SetObjEnable(CCD entry, 0|1) x9, entries 23-31
   |
   +-- written by M6_out's `pier_move`
          -> selected by which control pad the player stands on
```

Room: `M6_out`, floor id **0x99**.

## 2. What is proven

### 2.1 The state table — independently re-verified

Read directly out of the owner's own extracted script
(`Research/GateonBridge/extracted/M6_out_7_M6_out.txt`, `pier_def` at
`0x22F7`). Each entry is a `UnknownClass46::16(enable, objectIndex, …)`
call — the script-level `GScolsys2SetObjEnable`. `1` = enabled:

| flag 968 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 |
|---:|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 1 | 0 | 0 | 1 | 1 | 0 | 0 | 1 |
| 1 | 0 | 0 | 1 | 0 | 1 | 0 | 1 | 1 | 0 |
| 2 | 1 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 1 |
| 3 | 1 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 0 |

The flag-0 row was re-read opcode by opcode this pass and matches. The
table is **parseable from the script**, so it never needs to be typed in.

### 2.2 Geometry, from `M6_out.ccd` (63 entries)

- Entries **23-31** carry pointers only at `+0x28` (hit model) and
  `+0x34`. **They have no walk model.** ~~They are the bridge's *blocking*
  geometry.~~ **Corrected 2026-08-09: they are the bridge *segments*.** See
  §2.4.
- Entries **44-62** carry pointers only at `+0x24` (the walk model).
- `pier_def` **never toggles 58 or 59.** The two decks exist in all four
  alignments; only the segments around them change.

Measured extents, which is what makes the structure legible:

| Entry | Centre (x, z) | Span | Role |
|---|---|---|---|
| 23 | (−174.2, 110.0) | 68.4 × 20 | north deck, **east** — long span |
| 24 | (−240.0, 175.8) | 20 × 68.4 | north deck, **north** — long span |
| 25 | (−240.0, 78.4) | 20 × 0 | north deck, **south** — short plate |
| 27 | (−271.6, 110.0) | 0 × 20 | north deck, **west** — short plate |
| 28 | (−208.4, −90.0) | 0 × 20 | south deck, **east** |
| 29 | (−240.0, −58.4) | 20 × 0 | south deck, **north** |
| 30 | (−240.0, −121.6) | 20 × 0 | south deck, **south** |
| 31 | (−271.6, −90.0) | 0 × 20 | south deck, **west** |
| 26 | (−240.0, 10.0) | 34 × 0.4 | the **passage between the two decks** |

The two decks are walk entries **59** (centre −240, +110) and **58**
(centre −240, −90), each a 53.4-unit square at walk height ≈ −0.5.

Every one of the eight deck segments stands exactly **4.9 units** off its
deck's own edge; the passage (26) stands **53 units** off the nearer deck.
That order-of-magnitude separation is what lets the passage be told from a
deck connection without a threshold written by hand.

### 2.3 Everything is derivable

- **Which deck a segment belongs to** — nearest deck footprint, with the
  4.9 / 53 separation above deciding the passage.
- **Its compass direction** — the sign of the dominant axis between the
  segment centroid and its deck centroid.
- **Which deck is "northern"** — the one at greater Z. This reproduces
  `gateon_bridge.py`'s hardcoded `{58: "southern", 59: "northern"}`
  exactly, which is now a regression test rather than production data.
- **The state table** — parsed from `pier_def` in the extracted script.

So no Gateon coordinate, room list or direction is written into the
companion.

### 2.4 The polarity — got wrong, then settled

**`enable == 1` on entries 23-31 means that direction is BLOCKED.**

This is the one fact here that walks a blind player into a wall if taken
backwards, and it *was* taken backwards, from 2026-08-09 until the project
owner reported it on 2026-08-18: the `bridge` category listed precisely
the closed directions in every alignment, and autowalk was pointed at one
(`21:29:12`, "Autowalk on, Southern bridge, south connection", while
segment 30 was enabled).

**Why the original argument failed.** It rested on `pier_def`'s table
agreeing 12/12 with the `ALIGNMENTS` prose in `gateon_bridge.py`, treated
as an independent observation of the running game. It is not independent:
the prose is a field-for-field restatement of the enable bits — state 0's
"north and west" is exactly `{24, 27}`, state 1's "south and west" exactly
`{25, 27}`, "centre open" exactly `26 == 1`. A table restated in words
agrees with itself whichever way it was read, so 12/12 was guaranteed and
carried no information. Two descriptions of one source are one source.

**What actually settles it**, all from the room's own collision data:

| Evidence | Consequence |
|---|---|
| Entries 23-31 contribute **0 triangles to the walk model**; only the decks (58, 59) and the ground mesh (45) are walkable | A thing you cannot stand on is not a connection |
| **Seven of the nine are collapsed planes** (entry 27 spans x −271.6..−271.6; entry 30 spans z −121.6..−121.6; entry 26 is 0.4 deep). The other two are closed volumes | A plane with no footprint is a gate across an opening, not a surface |
| The call is `GScolsys2SetObjEnable(1, obj)` — it switches a collision **blocker on** | The engine's own verb agrees |
| `pier_def` **never toggles 58 or 59** | The decks exist in every alignment; only the blockers move |

The first and last of those were already written down in
[ENTITY_NAVIGATION_ARCHITECTURE.md](ENTITY_NAVIGATION_ARCHITECTURE.md)
§3.7 *when the wrong conclusion was drawn from them*.

**The puzzle only works this way round.** Crossing between the two piers
passes three gates in a line at x = −240: the northern deck's south gate
(25, z 78.4), the centre passage (26, z 10), and the southern deck's north
gate (29, z −58.4). Under `1 == blocked`, alignment 0 opens all three and
the other three alignments do not. Under `1 == connected`, **no alignment
ever opened all three**, which would have made the two piers permanently
uncrossable — a fact visible in the table the whole time.

`test_bridge_connections.PolarityTests` now pins the collision-data facts
themselves. The 12/12 comparison is kept as
`test_the_retired_prose_cannot_decide_the_polarity`, labelled as the trap
it was, so it is not reinstated as evidence a third time.

### 2.5 Open is not enough: connections that lead nowhere

Added 2026-08-18 with the polarity fix, from the project owner's request
that the category list "only the places where the bridge is currently
connected".

A pier's **interior-facing** gate — the one pointing at the other pier,
derived from the two decks' own positions rather than named — opens onto
the centre passage and nothing else. It is published only when the passage
is open too. The passage is published only when at least one interior gate
is open, since otherwise it cannot be reached from either deck.

Without that rule, three of the four alignments announce somewhere to walk
that goes nowhere: alignment 1 leaves the passage open with neither gate
onto it, and alignments 2 and 3 each leave exactly one interior gate open
against a blocked passage.

What the category publishes per alignment, after both fixes:

| flag 968 | Published |
|---:|---|
| 0 | Northern east, Northern south, **Centre passage**, Southern north, Southern south |
| 1 | Northern east, Northern north, Southern east, Southern west |
| 2 | Northern north, Northern west, Southern south |
| 3 | Northern west, Southern east, Southern west |

Alignment 0 is the one that lets you cross between the piers.

### 2.3 The pier is also an interaction-region owner

Room `M6_out` holds five marker-`0x0100` interaction records
([INTERACTABLE_OBJECTS.md](INTERACTABLE_OBJECTS.md) §3.8):

| Handler | Records | Method |
|---|---:|---|
| `pier_trouble` | 2 | 2 (walk-in) |
| `door_hoseb` | 1 | 3 (press A) |
| `ev_mechakyogre_check` | 1 | 3 |
| `crabcrab_in_col` | 1 | 1 |

`pier_trouble` × 2, method 2, is the first evidence in this project that
the pier has *its own* interaction regions with real, `.ccd`-resolvable
positions — i.e. bridge-related positions that are derivable rather than
guessed. Whether `pier_trouble` is the control pad, a blocked-crossing
message, or something else is **not yet established**; it is a lead, not a
conclusion.

## 3. What is hardcoded and must go

| Location | What | Why it is wrong |
|---|---|---|
| `gateon_bridge._RAW_PAD_TRANSITIONS` | **16 coordinate boxes** | typed-in world coordinates; derivable from `pier_move` plus the room's `.ccd` |
| `gateon_bridge.{58: "southern", 59: "northern"}` | deck naming | `pier_def` never touches 58/59 — unverified as the alignment carrier |
| `gateon_bridge.ALIGNMENTS` prose | per-state wording | *acceptable* — accessibility-owned wording over a state read live from flag 968 |

## 4. What is not proven

| Claim | Status |
|---|---|
| the live `GScolsys2` enable records sit near `0x80445C20`, 0x28-byte stride, bit 0 of `u16 +0x24` = disabled | **static trace only, never read live** |
| the mapping from a `.ccd` file entry index to its runtime enable record | **never established** — this is the actual blocker |
| entries 23-31 are the north/south bridge blockers in the arrangement `ALIGNMENTS` describes | inferred from the state table, **not observed** |
| `pier_trouble` is the control pad | **unknown** |
| any bridge state transition has ever been observed by this project | **no** — all 17 `GATEON BRIDGE` lines in the log report alignment 0 |

## 4a. What the category does (shipped 2026-08-09)

`bridge_connections.BridgeConnectionEntitySource`, category key `bridge`,
spoken as "Bridges" / "Bridge".

| Property | Value |
|---|---|
| Published | one entity per segment the **current** alignment enables — 4 or 5 at a time, never all nine |
| Identity | `("bridge", ccd entry index)` |
| Label | derived: `"Northern bridge, east connection"`, `"Centre passage"` |
| World position | the segment's own geometric centre, at its **deck's walk height** — not the hit model's Y, which is a 50-unit-tall wall and would report every connection as "above" |
| Interaction position | **nearest point of the segment to the player**, recomputed per query — for the 68-unit east span that is 34 units from the centre |
| Interaction radius | **none.** These are walk-into, not press-A; inventing a radius would let entity nav promise "Interaction available" for something A does nothing to |
| Update | flag 968 re-read every query; a rotation advances `generation` and replaces the published set wholesale |
| Off the pier | publishes nothing, so the category is skipped by the cycle everywhere else |
| On failure | publishes nothing — unreadable flag, an alignment `pier_def` does not define, or a layout that could not be derived all produce silence |

Worked example, standing on the northern pier, from the real extracted
data:

```
flag 968 = 0   Northern bridge, west connection    centre (-271.6, 110.0)  walk-to (-271.6, 110.0)
               Northern bridge, north connection   centre (-240.0, 175.8)  walk-to (-240.0, 141.6)
               Southern bridge, east connection    centre (-208.4, -90.0)  walk-to (-208.4, -80.0)
               Southern bridge, west connection    centre (-271.6, -90.0)  walk-to (-271.6, -80.0)

flag 968 = 3   Northern bridge, east connection    centre (-174.2, 110.0)  walk-to (-208.4, 110.0)
               Northern bridge, north connection   centre (-240.0, 175.8)  walk-to (-240.0, 141.6)
               Centre passage                      centre (-240.0,  10.0)  walk-to (-240.0,   10.2)
               Southern bridge, north connection   centre (-240.0, -58.4)  walk-to (-240.0, -58.4)
               Southern bridge, south connection   centre (-240.0,-121.6)  walk-to (-240.0,-121.6)
```

Both audio-guide modes work on a selected bridge connection with no extra
wiring, because the guide reads entity navigation's own selection.

## 5. Consequences today

**Routing now reads the engine's enable state (2026-08-13) — but the Gateon
cross-check has not been run live.**

`StaticObjectEnableState.is_enabled` used to return `True` unconditionally,
so `build_room_geometry` treated all nine segments' hit models as present in
all four alignments. `LiveObjectEnableState` now reads `GScolsys2`'s own
per-object flags, and `NavigationService` invalidates cached geometry and
discards an active route when they change, so an alignment change rebuilds
the graph instead of steering on stale geometry. The structure and its
verification are in COLLISION_DETECTION_INVESTIGATION.md §"Runtime
object-enable state"; `M6_out` is the game's heaviest user of the mechanism
(200 `SetObjEnable` calls, more than the next six rooms combined).

Two things are still **not** settled, and neither is guessed:

- **What a present segment's hit model means for walkability**, as distinct
  from connectivity. Reading the enable bit answers "is this object
  considered", not "does considering it block a step". That question is
  unchanged by this work.
- **Live confirmation *here*.** The mechanism itself is live-validated as of
  2026-08-13, but in Agate, not Gateon (`M3_out` object 33; see
  COLLISION_DETECTION_INVESTIGATION.md §"Live confirmation"). Agate's toggle
  is applied at room load; **Gateon is the only place that toggles objects
  mid-session**, so §7's comparison against `pier_def`/flag 968 remains the
  outstanding oracle for the invalidation path specifically — see step 2.

Practical consequence for the player, stated plainly: **use the plain
beacon (ctrl+g) for bridge connections, not the routed guide
(ctrl+n)**, until this is resolved. The beacon points straight at
the connection and cannot mis-route; the router may refuse or detour
because it believes segments are in the way.

**Bridge controls are still not entities.** Only connection points ship.
`pier_trouble` (§2.3 of [INTERACTABLE_OBJECTS.md](INTERACTABLE_OBJECTS.md))
is the lead for the control pads, and `_RAW_PAD_TRANSITIONS`' 16
coordinate boxes are still in `gateon_bridge.py`, still to be removed.

**Invalidation on a state change is handled** for the connection
entities — the alignment is re-read every query, disabled segments simply
stop being published, and `generation` advances so a consumer holding a
stale selection can tell. It is **not** handled for routing geometry,
because routing does not consume the alignment at all yet.

## 6. Phase 5 plan

~~3. Parse the state table from the script~~ — **done.**
~~4. Derive endpoints from entries 23-31's own geometry~~ — **done.**
~~5. Verify or drop the 58/59 deck naming~~ — **done**, derived from Z and
now a regression test.
~~7. Publish bridge entities~~ — **done** for connection points.
~~8. Correct the coverage matrix~~ — **done.**

Remaining, ordered so nothing is built on an unverified layer:

1. **Live-validate the connection points.** Stand on a pier, cycle the
   `bridge` category, walk to one announced connection, confirm you can
   actually cross there. Then change the alignment and confirm the list
   changes. **Never done, and skipping it is what let the inverted
   polarity ship for nine days** — the 12/12 document agreement was
   allowed to stand in for it. The discriminating check is one minute:
   in alignment 0 you should be able to walk straight through the middle
   from one pier to the other (Centre passage is listed); in alignments 2
   and 3 you should not, and no interior connection is offered.
2. **Live-validate the `GScolsys2` enable records** — the gate on routing.
   Read the nine records for entries 23-31 in one known alignment and
   confirm they match §2.1's row.
3. ~~**Establish the file-entry → enable-record mapping.**~~ **Done
   2026-08-13, statically.** It *is* the identity mapping, and it is now
   shown rather than assumed: `GScolsys2LoadCCD` walks the CCD entry array
   (stride `0x40`) and the OBJ array (stride `0x28`) in lockstep, writing
   entry *i* into record *i*, and both the walk and hit loops call
   `GScolsys2GetObjEnable(i, …)` with that same *i*. Still owed: the live
   read in step 2.
4. ~~**Settle what a present segment's hit model does to walkability.**~~
   **Answered 2026-08-18: an enabled segment BLOCKS.** See §2.4. The
   enable state was already wired into `build_room_geometry` and into
   cache invalidation (an alignment change rebuilds the route); what was
   missing was the meaning of the bit, which is now settled. Worth
   re-checking that routing consumes it with the same sense the entity
   category now does.
5. **Bridge controls.** Investigate `pier_trouble`'s two method-2 regions
   in `M6_out`; if they are the control pads, publish them and delete
   `_RAW_PAD_TRANSITIONS`' 16 coordinate boxes.

## 7. Wording, when there is state to speak

Candidate only — not committed, because the destinations are not yet
authoritative:

- "Bridge connection" / "Bridge to *destination*" for an endpoint;
- "Bridge control" for the pad;
- one announcement on an alignment change, not a repeated status.

The existing `alignment_text()` wording is already state-driven from a
live flag and can be kept.

## 8. Standing constraint

**No Gateon coordinate is to be hardcoded.** Every position must come from
the room's own `.ccd`, its interaction regions, its warp destinations, or
the live enable state. The 16 coordinate boxes in `gateon_bridge.py` are
the thing to remove, not the thing to extend.
