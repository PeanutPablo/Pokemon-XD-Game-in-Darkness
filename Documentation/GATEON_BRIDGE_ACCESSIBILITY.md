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
> **§2.2 below is corrected by this work.** Entries 23-31 are not the
> bridge's blocking geometry. **`enable == 1` means that direction is
> CONNECTED.** See §2.4 for how that was settled — it is the one fact here
> that could have walked a blind player off a pier if taken backwards.

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

### 2.4 The polarity — settled, not assumed

**`enable == 1` on entries 23-31 means that direction is CONNECTED.**

Reading it backwards would send a blind player at a wall in every
alignment, so it was decided against two sources produced independently of
one another:

1. `pier_def`'s own table (§2.1) — the game's script;
2. the `ALIGNMENTS` prose in `gateon_bridge.py` — written by whoever built
   that reader, from the actual running game.

Deriving each alignment's connections from geometry and comparing against
that prose, over 4 states × (northern deck, southern deck, centre
passage):

| Reading | Agreement |
|---|---:|
| `enable == 1` means **connected** | **12 / 12** |
| `enable == 1` means **blocked** | **0 / 12** |

The geometry corroborates it independently: the two long 68.4-unit
structures (east, north) are the directions with a real gap to cross, and
the short ~5-unit plates (west, south) bridge a step. Those are bridge
parts, not barriers.

`test_bridge_connections.PolarityTests` pins both halves — 12 and 0 — so
if the two sources ever stop agreeing, the category fails loudly rather
than quietly inverting.

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

**Routing is still not alignment-aware — unchanged, and deliberately so.**
`StaticObjectEnableState.is_enabled` returns `True` unconditionally, so
`build_room_geometry` treats all nine segments' hit models as present in
all four alignments. The 2026-08-09 work did **not** touch this: what a
present segment's hit model means for *walkability* is a separate question
from what it means for *connectivity*, and it is not settled. Guessing it
would be the one way to make routing worse than it already is.

Practical consequence for the player, stated plainly: **use the plain
beacon (ctrl+shift+g) for bridge connections, not the routed guide
(ctrl+shift+n)**, until this is resolved. The beacon points straight at
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
   changes. Two observations settle the polarity beyond the 12/12
   agreement, and settle it *in the game* rather than against a document.
2. **Live-validate the `GScolsys2` enable records** — the gate on routing.
   Read the nine records for entries 23-31 in one known alignment and
   confirm they match §2.1's row.
3. **Establish the file-entry → enable-record mapping.** Almost certainly
   the identity mapping, but it must be *shown*. Until it is,
   `StaticObjectEnableState` stays the honest placeholder it is.
4. **Settle what a present segment's hit model does to walkability**, then
   wire enable state into `build_room_geometry` and into cache
   invalidation so an alignment change rebuilds the route.
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
