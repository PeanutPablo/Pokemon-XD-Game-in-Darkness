# ENTITY_NAVIGATION_ARCHITECTURE.md

Authoritative ownership map for every overworld entity category the
companion navigates. Written **2026-08-06** as the Phase 1 deliverable of
the entity-navigation audit and revision pass.

Supersedes `ENTITY_NAVIGATION.md` as the architecture record. That document
remains accurate as a *history* of how the feature was built and which
hypotheses were abandoned; it is no longer accurate about what the code
does today (e.g. it still describes `WarpEntitySource` and hand-curated
`ELEVATORS`/`ITEMS` dictionaries as live categories).

Read alongside [`ENTITY_NAVIGATION_AUDIT.md`](ENTITY_NAVIGATION_AUDIT.md),
which groups the defects below by root cause and sequences the fixes.

> ## ⚠ Revised 2026-08-09 — read this first
>
> **§3.1 describes code that production does not run.** The Phase 2 NPC
> source was reverted in `phase1b_app.build_overworld_sources` on
> 2026-08-06 and has not been restored. Production runs the pre-Phase-2
> `NPCEntitySource`, with every Phase 1 defect (N1-N7) live. See
> [ENTITY_NAVIGATION_AUDIT.md](ENTITY_NAVIGATION_AUDIT.md) §0.2 for the
> per-symptom mapping and §0.3 for the fact that the interaction
> diagnostic has never produced a single line.
>
> Three things below are now **superseded by evidence**, not merely
> re-stated:
>
> - **§4's first Phase 4 candidate is disproven and its second is
>   answered.** There are no unparsed `common.rel` interaction types. The
>   missing object system is the 241 marker-`0x0100` records, whose
>   `+0x0A` is an index into the *owning room script's* function table —
>   241 of 241 verified. New §7 below; full treatment in
>   [INTERACTABLE_OBJECTS.md](INTERACTABLE_OBJECTS.md).
> - **§3.3's treasure record is now fully resolved**, including the two
>   general flags that carry collected and spawn state, and the item id.
>   New §8 below. This supersedes the "opened state is the actor's `disp`
>   byte" conclusion, which is true but cannot distinguish collected from
>   unspawned.
> - **§3.3's "record `+0x02` is a strong candidate for the approach angle
>   — UNVERIFIED"** is **verified**: it is the object's Y rotation, read
>   with `lha` and fed to `peopleSetRot`.

---

## 0. Scope and method

Everything below was established by one of:

- **Static disassembly** of the verified vanilla US XD build
  (`GXXE01` rev 0) in `xd-decomp/build/GXXE01/asm/`, with the symbol names
  taken from `xd-decomp/config/GXXE01/symbols.txt`.
- **Offline analysis** of the project owner's own extracted assets
  (`Companion/_dialogue_extraction/`): 177 `.ccd` collision files, the
  `common.rel` interaction table, and the room scripts under `rooms/`.
- **Log evidence** from `Companion/logs/battle_narrator_phase1b.log`
  (367 MB, sessions through 2026-08-06 11:37).

Nothing here is inferred from the project owner's verbal description of
what they saw in game. Where a claim rests only on the current code's own
assumption rather than on engine evidence, it is marked
**UNVERIFIED** and treated as a defect, not as documentation.

XG caveat unchanged: these are vanilla-XD addresses and structures. The
architectural *shape* (which table owns what) is what this document
asserts; every absolute address still needs live confirmation against XG.

---

## 1. The engine's own ownership chain

Two entirely separate chains produce everything the navigator announces.
Conflating them is the source of most of the defects in §3.

### 1a. The "people" chain — NPCs **and** ground pickups

```
current floor id  (0x80814AB6)
  -> floor_data record            (scan floor_data_root for +0x02 == floor id)
       +0x0C -> floor_character array header
                  -> count, then N x 0x24-byte STATIC character records
       +0x2C -> the floor's groupID (language-indexed)
  -> people_work runtime array    (0x804EBBB8 count / 0x804EBBBC base,
                                   0x1B0 stride)  <- LIVE ACTORS
       +0x00 occupied      +0x0D disp (visible)
       +0x08 model ptr     (-> +0x18 = live world position)
       +0x10 flags         (bit 0 set == not talkable)
       +0x14 identity_a == the floor's groupID
       +0x18 identity_b == resID
       +0x40 rot.y         +0x178 live talk distance
```

`floorCharacterBiosFindByResID(groupID, resID)` (0x80122778) resolves a
live actor back to its static record, and it is the authority on identity:

- it **rejects** the actor outright unless `groupID` equals the *current
  floor's* group id (`floorDataBiosGetGroupID`, floor_data `+0x2C`);
- otherwise `floorDataBiosGetCharInfo` does
  `record = charArrayBase + resID * 0x24`, bounds-checked against the
  array count.

**So `identity_b` is literally the index into the current room's
`floor_character` array** — the mapping this project already uses is
correct — but **`identity_a` must be compared against the floor's group
id, not merely tested for non-zero**, which is what the code does today.

Ground pickups reuse the same runtime array. `_floorInitTresure`
(0x8011F838) walks `floor_tresure_list`, and for every record belonging to
the current room it allocates a people actor whose
`resID = 0x7FFF0000 | ordinal`, where `ordinal` counts only that room's
own treasure records in table order. `floorEventGetTresureList` reverses
that mapping and validates the `0x7FFF` marker. That is an exact,
authoritative identity for every pickup in the room.

### 1b. The "interaction point" chain — warps, doors, elevators, PCs, signs

```
common.rel interaction table   (rel pointer 62 = table, 63 = count)
   0x1C stride, marker +0x08 == 0x0596
   +0x0A script type: 0x04 warp, 0x05 door, 0x06 elevator,
                      0x0C text/sign, 0x0D cutscene warp, 0x0E PC
   +0x02 owning room id
   +0x07 region_index
      |
      v
room .ccd file, top-level entries (0x40 bytes each)
   +0x2C / +0x30 -> interactable triangle lists
   each 0x34-byte triangle carries the region_index it belongs to
   (+0x32 for slot 0x2C, +0x30 for slot 0x30)
```

These are **regions**, not points. The player triggers them by walking
into them anywhere.

Two structural facts established offline this pass:

- **Every one of the 2,259 CCD top-level entries across all 177 rooms has
  an identity transform** (position `0,0,0`, rotation `0,0,0`, scale
  `1,1,1` in the leading 0x24 bytes). So static `.ccd` vertices *are*
  world coordinates. This closes a real hypothesis — that region positions
  were in object space — as **disproven**. It does **not** license
  assuming the runtime transform stays identity for objects a script
  moves.
- **No interaction index ever appears in both slot `+0x2C` and slot
  `+0x30`, in any room.** Merging the two slots into one index namespace
  (which `parse_interactable_region_centers` does) therefore never
  collides. Also **disproven** as a defect. Recorded so it is not
  re-investigated.

### 1c. Runtime collision-object enable state

`GScolsys2SetObjEnable` / `GScolsys2GetObjEnable` toggle whether a
top-level CCD entry participates in collision. Room scripts drive this.
`collision_object_enable.StaticObjectEnableState` currently answers
"everything is always enabled" — an honest placeholder, and the reason
§4's bridge behaviour is wrong.

---

## 2. The game's own interaction test

`peopleTalkCheck` (0x802A3444, called from `updateChat` in `heroMove.s`)
is the single authority on whether pressing A will do anything. Decoded
this pass, in order:

**Phase 2 status (2026-08-06): gates 1-9 and 11-12 are now implemented in
`talk_predicate.py`.** The "Implemented today?" column below is the Phase 1
record of what was missing, kept because it is what the fixes were scoped
against. Gate 10 belongs to treasure and is Phase 3.

| # | Gate | Source | Implemented at Phase 1? |
|---|---|---|---|
| 1 | actor slot occupied | `people_work +0x00` | yes |
| 2 | actor is not the hero | pointer identity | n/a |
| 3 | actor displayed | `people_work +0x0D` | yes |
| 4 | `peopleBiosCheckFlag(actor, 1)` is **false** | `people_work +0x10` bit 0 | **no** |
| 5 | `floorCharacterBiosGetTalkStartType != 3` | `floor_character +0x01`, `(byte >> 3) & 3` | **no** |
| 6 | `dist3D(heroPos, neckPos) <= heroColBall + talkDistance + npcColBall` | see below | **no — different formula** |
| 7 | `abs(angle(heroRot, neckPos)) <= radians(40)` | `people_work +0x40` | yes (`talk_cone_degrees`) |
| 8 | on push-box floors, hero and target must be on the same height band | `gimmickBoxIsPushBoxFloor` | **no** |
| 9 | unless `floorCharacterBiosGetTalkWallThrough`, a wall check applies | `floor_character +0x00` bit 3 | **no** |
| 10 | for treasure kind 1, the player must additionally be within a cone of the **box's own facing** | `peopleBiosGetRot` vs `peopleVecCalcRotY` | **no** |

Gate 6's terms, each confirmed by disassembly:

- `neckPos` = `peopleGetNeckPos` = the **neck bone's X/Z**
  (`peopleGetPartsPos` with `peopleInfoBiosGetNeckIndex`, `people_info
  +0x01`) with **Y overwritten by the actor's own base position Y**. It is
  *not* the model origin.
- `heroColBall`, `npcColBall` = `peopleInfoBiosGetColBallSize` =
  `people_info +0x10`.
- `talkDistance` = `peopleGetTalkDistance` = **`people_work +0x178`**, a
  live per-actor field — **not** `people_info +0x24`, which is what this
  project reads. Whether `+0x178` is initialised from `people_info +0x24`
  is **UNVERIFIED**; Phase 2 must establish it rather than assume it.

The project currently approximates all of gate 6 as
`horizontal(hero, modelOrigin) <= people_info[+0x24] + 1.5`.

The `0.3` constant recorded in `profile.talk_cone_degrees`' docstring as
part of the distance rule does **not** appear in the distance sum in the
disassembly; the sum is exactly the three terms above. That docstring
needs correcting in Phase 2.

---

## 3. Per-source ownership map

Fields are those required by the audit brief. "Reader" is the class that
produces `Entity` records today.

### 3.1 NPC — **rebuilt in Phase 2 (2026-08-06)**

| Field | Value |
|---|---|
| User-facing category | `npc` ("NPCs"); role NPCs move to `interact` |
| Engine owner | `people_work` (live actors) — authoritative; `floor_character` supplies metadata only |
| Static resource | `floor_data +0x0C` -> 0x24-byte records, correlated by `(groupID, resID)` |
| Live runtime structure | `people_work`, 0x1B0 stride |
| Identity key | `("npc", groupID, resID)` — see [ENTITY_IDENTITY_MODEL.md](ENTITY_IDENTITY_MODEL.md) |
| World-position source | live `model +0x18`, every query, never cached. A static record with no live actor publishes **nothing** |
| Interaction-position source | neck reference `(neckJoint.x, actorBase.y, neckJoint.z)` via `model_parts.NeckPositionResolver`; falls back to the actor position on a failed read |
| Interaction distance | `heroColBall + live talkDistance(+0x178) + npcColBall`, 3-D |
| Name/label source | role (from the talk script) > `floor_character +0x08` name id -> `entity_names` > a remembered bare letter |
| Active/enabled flag | `people_work +0x0D` (disp), `+0x10` bit 0, `floor_character +0x01` talk-start type |
| Story/script dependency | scripts set `disp`, move actors, set `+0x10` bit 0 and talk-start type |
| Update frequency | every `entities()` call |
| Cache lifetime | live state: none. `floor_character` array and `peopleInfoData`: per room / per table identity |
| Invalidation triggers | room change rebuilds static metadata and resets letters; generation advances when an identity's `(slot, model)` binding changes |
| Current reader | `entity_sources.LiveNPCEntitySource` over `people_runtime.PeopleRuntimeSource` |
| Known defects | none open. Unverified INPUTS remain: the floor group-id language slot, the `talk_<N>` correspondence, and the JObj neck walk — all logged by the diagnostic, none guessed |
| Confidence | ownership High; predicate High; neck walk Medium (statically traced, degrades safely) |
| Live evidence | pending Phase 2 live validation |

Phase 1 defects N1-N7 are all closed:

| Was | Now |
|---|---|
| N1 `identity_a != 0` only | `groupID` must be one of the current floor's group ids |
| N2 four talk gates unimplemented | full predicate in `talk_predicate.py`; permanently-blocked NPCs are not offered at all |
| N3 interaction point = model origin | neck reference, separate from the world position |
| N4 letters recomputed every call | `LetterRegistry` remembers them for the room visit |
| N5 `"NPC A"` | `"A"` |
| N6 static `people_info +0x24` | live `people_work +0x178` |
| N7 people-info read by array index | linear search on the record's own `+0x04` id, as `peopleInfoBiosGetPtr` does |

### 3.1a Talk predicate

`talk_predicate.evaluate` reproduces `peopleTalkCheck` gate by gate and
reports *which* gate rejected a candidate. Three states are kept distinct:

- **exists** - a live actor correlated with its static record;
- **navigable** - exists and is not permanently blocked (a distant NPC is
  navigable);
- **interactable** - the complete predicate passes.

Gates that cannot be verified (facing unreadable, room geometry missing,
push-box floor) are reported as UNKNOWN and **never** counted as passes.
The navigator then says "In range" rather than "Interaction available".

Gate 12 (a following partner blocking the line, `peopleInsideCheck`)
defaults to *not blocking*, because the engine skips it entirely when the
hero has no partner and that is the ordinary overworld state. Documented as
an approximation rather than modelled: defaulting the other way would
suppress every interaction cue in the game on an unverified assumption.

### 3.2 Poké Mart clerk / Pokémon Center nurse ("interact")

| Field | Value |
|---|---|
| User-facing category | `interact` ("Interactables") |
| Engine owner | **none** — this is not an engine concept |
| Identity key | `(floor_id, index)` inherited from the NPC source |
| Label source | a Python dict keyed on **floor id**: `{0x85: "Pokemon Center nurse", 0x86: "Pokemon Mart clerk"}` |
| Current reader | `FilteredEntitySource` in `phase1b_app.entity_nav_factory` / `overworld_entity_sources` (duplicated verbatim in both) |
| Status | **FIXED in Phase 2 (2026-08-06).** Role now resolves from the NPC's own talk script id (`floor_character +0x14`) against `Companion/assets/npc_roles.json`, derived from the game's own room scripts: a talk function reaching `Dialogs::openPokemartMenu` is a clerk, one reaching `Character::101` (`useHealingMachine`) is a nurse. 15 rooms, 16 role NPCs; Agate's Mart resolves to exactly one clerk and Agate's Centre to exactly one nurse. The same lookup now drives the passive Mart beacon, replacing `profile.pokemart_room_ids`. |
| Known defects (Phase 1, now closed) | **R1 — the reported duplicate-clerk bug.** The predicate is `entity.identity[1] in role_rooms`, and `Entity.identity` is `("npc", floor_id, index)`, so `identity[1]` is the **floor id**. Every NPC standing in `M3_shop_1F` (0x86) is relabelled "Pokemon Mart clerk"; every NPC in `M3_pc_1F` (0x85) becomes "Pokemon Center nurse". It also misses every Mart and Center outside Agate. |
| Confidence | that this is wrong: **Certain** (code + log + the room-id table) |
| Live evidence | `2026-08-05 21:58:44.847 ENTITY NAV Interactables. 3 available. Pokemon Mart clerk. 11 o'clock, distance 26.` then three separate bearings/distances (27, 30, 16) all labelled identically |

`npc_beacons.NPC.people_info_id` exists specifically to replace this
heuristic with a shared people-info type id, and its own docstring already
records that the room-id guess "mislabels every other NPC in those two
rooms and misses every other Pokemon Center". Whether role NPCs actually
cluster by `people_info_id` is **UNVERIFIED** and is Phase 2 work.

### 3.3 Item / treasure pickup

| Field | Value |
|---|---|
| User-facing category | `item` ("Items") |
| Engine owner | `floor_tresure_list` (`0x804E88F4`, count at `0x804E88F0`, 0x1C stride) — the symbol name is authoritative, from `symbols.txt` |
| Static resource | same table, built at room load by `_floorInitTresure` |
| Live runtime structure | a **people actor** per record, `resID = 0x7FFF0000 \| ordinal` |
| Identity key | **should be** `(floor_id, ordinal)`; **is** `("item", room_id, kind, x, y, z)` |
| World-position source | record `+0x10/+0x14/+0x18` (the spawn point `peopleSetPos` writes); the live actor position is available and unused |
| Interaction-position source | as §2; kind 1 additionally requires approaching from the box's own facing (record `+0x02` is a strong candidate for that angle — **UNVERIFIED**) |
| Name/label source | none; a generic `"Item"` string |
| Opened/collected state | **`floorEventSetTresureDisp(ordinal, disp)` -> `peopleSetDisp` -> `people_work +0x0D`.** The opened/collected/unspawned state is the actor's `disp` byte — the same field already read for NPCs |
| Story/script dependency | `floorEventChangeTresure(index, itemId, b)` rewrites `+0x0C` (item id) and `+0x01` at runtime |
| Update frequency | every `entities()` call |
| Cache lifetime | `_previous`/`_opened` dicts, cleared only on room change |
| Invalidation triggers | room change only |
| Current reader | `treasure_entities.LiveTreasureEntitySource` |
| Known defects | **I1 — wrong kind bits.** `_floorInitTresure` and `peopleTalkCheck` both read the kind as `extrwi r0, r0, 3, 24`, i.e. **`(byte >> 5) & 7`**; the code reads `byte & 0x7`. **I2 — wrong kind set.** The engine's placeable kinds are **1, 2, 3** (model resources `0x02F80400` / `0x02F90400` / `0x02FA0400`); the code filters to `(1, 2, 4)`. **I3** opened state is *inferred* from "the record vanished from the table" instead of read from `disp`. **I4** identity embeds raw float coordinates. **I5** position is the static spawn point, not the live actor position. **I6** `POKESPOT_ROOMS` hardcodes three room ids, three labels and three flag numbers. |
| Confidence | ownership chain High (fully disassembled); current implementation Low |
| Live evidence | `2026-08-06 11:36:15.223 ENTITY NAV Items. 3 available. Item. 4 o'clock, distance 244, below.`; the string `(opened)` appears **0 times** in the entire 367 MB log |

### 3.4 Warp / cutscene warp

| Field | Value |
|---|---|
| User-facing category | `warp` ("Warps") |
| Engine owner | `common.rel` interaction table, script types 0x04 / 0x0D |
| Static resource | `common.rel` + the room's `.ccd` interactable triangles |
| Live runtime structure | none read |
| Identity key | `("warp", record index)` — stable and authoritative |
| World-position source | **centroid of every vertex of every triangle sharing the region index** |
| Interaction-position source | same centroid (see defect P1) |
| Name/label source | `room_names[target_room_id]`; duplicates get an A/B/C suffix |
| Active/enabled flag | **none read** — a warp disabled by `GScolsys2SetObjEnable` still announces |
| Update frequency | every call; per-room centroids memoised in `_centers` for the process lifetime |
| Cache lifetime | permanent (static geometry — acceptable) |
| Invalidation triggers | none |
| Current reader | `authoritative_warps.AuthoritativeWarpEntitySource` |
| Known defects | **P1** (below), plus no enable-state check |
| Confidence | identity and destination High; **position Low** |
| Live evidence | `2026-08-06 11:34:27.735 ENTITY NAV to house in Agate Village, 1st floor B. 12 o'clock, distance 366, above.` |

### 3.5 Door, elevator, PC, sign

Identical ownership to §3.4, differing only in the `common.rel` script
type (0x05 / 0x06 / 0x0E / 0x0C) and the label. All five share defect
**P1**. Doors are discovered and beaconed but deliberately excluded from
the entity-nav cycle (2026-08-05, project owner's request). The PC type's
own parameters are documented by `Pokemon-XD-Code` as "unused in XD", so
`AuthoritativePCEntitySource` relies only on room id + region index.

Live evidence of the position problem in these categories:

- `2026-08-05 22:57:33.076 ENTITY NAV Interactables. 1 available. PC. 10 o'clock, distance 232, below.`
- `2026-08-06 11:33:43.715 ENTITY NAV Elevator to Cipher Lab lab, basement level 3. 6 o'clock, distance 437, above.`

#### Defect P1 — the centroid is not an interaction point

Measured across all 843 interaction regions in the 177 extracted rooms:

| Measurement | Median | p90 | Max |
|---|---:|---:|---:|
| Centroid to the nearest point of its own region | 0.00 u | 3.54 u | **168.9 u** |
| Centroid to the farthest point of its own region | 18.40 u | 30.68 u | **340.9 u** |

- **842 of 843 regions** are large enough that a player standing
  legitimately inside the region can be more than 10 game units — one full
  interaction radius — from the announced point.
- **210 of 843 regions** have a centroid lying *outside* the region by
  more than the 1.5-unit "same position" threshold; **11** by more than a
  full interaction radius, worst case 168.9 units of empty space
  (`D3_out` region 1).
- The two regions in `D1_labo_B1` — the Cipher Lab basement where the
  "distance 437" elevator above was logged — each have a 7.5-unit
  centroid-outside-region gap.

The engine treats these as areas you enter anywhere. The correct
interaction position is therefore **the nearest point on the region to the
player**, recomputed per query — not a fixed centroid. This is one bug,
not five, and fixing it once fixes warps, doors, elevators, PCs and signs
together.

### 3.6 Healing station

| Field | Value |
|---|---|
| Engine owner | **none** |
| Static resource | `npc_beacons.HEALING = {0x8A: Position(-89.0, 0.0, -42.9)}` — one hand-captured coordinate, from the project owner standing next to a bed |
| Known defects | **H1** a single hardcoded room/coordinate pair; no engine ownership; no state; will never generalise. `HEALING_SERVICE_SCRIPT_TRACE.md` already identifies the real owner (class 35 `Character`, method 101 `useHealingMachine`) and it is not wired in |
| Confidence | Very low |

### 3.7 Gateon Port bridges

| Field | Value |
|---|---|
| User-facing category | **none — bridges are not in entity navigation at all** |
| Engine owner | general flag **968**, consumed by `M6_out`'s `pier_def`, which calls `GScolsys2SetObjEnable` on CCD entries **23–31** |
| Static resource | `M6_out.ccd`; `M6_out` room script (extracted, `rooms/M6_out.txt`) |
| Live runtime structure | the `GScolsys2` enable records near `0x80445C20` — **traced statically, never live-validated** |
| Identity key | none defined |
| World-position source | `_RAW_PAD_TRANSITIONS` — **16 hardcoded coordinate boxes** in `gateon_bridge.py` |
| Active/enabled flag | not read; `StaticObjectEnableState` answers "always enabled" |
| Current reader | `gateon_bridge.GateonBridgeReader` — a passive announcer only |
| Confidence | flag/script ownership High; positions Low; live enable state Unverified |

> **Corrected and superseded 2026-08-09.** A `bridge` entity-navigation
> category shipped the same day; see
> [GATEON_BRIDGE_ACCESSIBILITY.md](GATEON_BRIDGE_ACCESSIBILITY.md). The
> table below is right, but the sentence "they are the bridge's *blocking*
> geometry" is **wrong**: entries 23–31 are the bridge **segments**, and
> **`enable == 1` means that direction is CONNECTED.** Settled against two
> independent sources — the script's own table and the `ALIGNMENTS` prose
> written from the real game — which agree **12/12** under that reading and
> **0/12** under the other. Positions, deck names and compass directions
> are all derived from `M6_out.ccd`; the state table is parsed from the
> room script; `_RAW_PAD_TRANSITIONS` is no longer used for connections.

Established offline this pass, from `M6_out.ccd` (63 entries) and
`rooms/M6_out.txt`:

- Entries **23–31** carry pointers only at slot `+0x28` (the hit
  model) and `+0x34`. **They have no walk model.** ~~They are the bridge's
  *blocking* geometry.~~ (See the correction above.)
- Entries **44–62** carry pointers only at slot `+0x24` (the walk model).
  Entries 58 and 59 — which `gateon_bridge.py` names as the southern and
  northern decks — are in this group, consistent with
  `walk_height_candidates` returning `entry_index`.
- `pier_def` **never toggles 58 or 59.** The walkable deck surface exists
  in every alignment; only the blockers move.

The per-state enable table, read directly out of the extracted script
(`1` = enabled):

| flag 968 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 |
|---:|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 1 | 0 | 0 | 1 | 1 | 0 | 0 | 1 |
| 1 | 0 | 0 | 1 | 0 | 1 | 0 | 1 | 1 | 0 |
| 2 | 1 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 1 |
| 3 | 1 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 0 |

Because this table is *parseable from the extracted script*, and the
segment geometry is *parseable from the room's own `.ccd`*, bridge
endpoints can be derived generically. **No Gateon coordinate needs to be
hardcoded.** The 16 coordinate boxes currently in `gateon_bridge.py` are
the thing to remove, not to extend.

Consequence for routing, stated plainly: with `StaticObjectEnableState`
returning "enabled" for every entry, `build_room_geometry` includes all
nine blockers in all four alignments. Pathfinding at Gateon Port is
therefore wrong in every alignment — it sees blockers that are currently
retracted.

`ACCESSIBILITY_COVERAGE_MATRIX.md`'s "Gateon Port changing bridge" entry
still reads "Unknown — reachability not established". That is stale: the
reader shipped, has tests (`test_gateon_bridge.py`), and fired live on
2026-08-05. Correcting it is Phase 5 work.

---

## 4. Categories that do not exist yet

Requested in the audit brief, with no current owner in the codebase:
Purify Chamber (a `purify_chamber.py` module exists but feeds no entity
source), Snag Machine, televisions, rest beds, PokéSpot food plates
(partially present as a hardcoded special case inside the item source),
computers/terminals distinct from the PC type, storage, switches and
consoles, bridge connection points, bridge controls.

Whether these share one ownership chain is the Phase 4 question. The two
candidates worth testing first, in order:

1. **`common.rel` interaction types not yet parsed.** Six of the type
   values are parsed today (0x04, 0x05, 0x06, 0x0C, 0x0D, 0x0E). The
   others are unenumerated. If a television or a bed is an interaction
   point, it is already in a table this project can read.
2. **People actors with no `floor_character` record.** `peopleTalkCheck`'s
   own fallback branch — the one that handles treasure — is reached
   exactly when `floorCharacterBiosFindByResID` returns null. Anything
   else that lands in that branch is a non-character interactable the
   engine already knows how to talk to.

Neither is assumed. Both are cheap to enumerate offline before any code is
written.

---

## 5. Cross-cutting structural issues

- **The source map is duplicated verbatim.** `entity_nav_factory` and
  `overworld_entity_sources` in `phase1b_app.py` build the same seven
  sources with the same wiring, ~45 lines apart. Any fix must be applied
  twice or they silently diverge.
- **One failing source silences every category.** `EntityNavigator`
  has no per-source error isolation; `phase1b_lifecycle.poll_entity_nav`
  catches `MemoryError` and calls `clear()` on the whole navigator. A
  transient failure in, say, the sign source discards the player's
  category and selection.
- **Beacon eligibility is not separable from navigation eligibility.**
  `WarpAugmentedNPCSource` synthesises an `NPC(visible=True, talk_id=1)`
  for *every* entity a wrapped source returns, so anything a source
  reports beacons. There is no way to keep an entity in the list while
  silencing it — which is exactly what an opened item box needs.
- **`Entity` cannot express state.** It has `category`, `identity`,
  `label`, `position`, `interaction_distance`, `subtype`, `metadata`. It
  cannot say "exists but is not interactable", "still a landmark but
  should not beacon", or "interaction point differs from world position".
  Those distinctions are what the audit brief requires and they have
  nowhere to live today.
- **Category count.** Six categories cycle today (`npc`, `item`,
  `interact`, `elevator`, `warp`, `sign`). The brief warns against
  category proliferation; §4's additions must fold into existing
  categories rather than adding one per object type. A concrete proposal
  belongs in Phase 4, after §4's enumeration says what actually exists.

---

## 6. Confidence summary

| Area | Confidence | Basis |
|---|---|---|
| People/actor ownership chain | High | full disassembly of 8 functions |
| Treasure ownership chain | High | `_floorInitTresure`, `floorEvent*Tresure`, symbol names |
| `peopleTalkCheck` gate list | High | full disassembly |
| CCD region geometry is world-space | High | all 2,259 entries measured |
| Centroid-as-interaction-point is wrong | High | all 843 regions measured |
| Duplicate-clerk root cause | Certain | code + room id table + log |
| Treasure kind bit positions | High | two independent call sites agree |
| `people_work +0x178` vs `people_info +0x24` | Unverified | needs live check; diagnostic has **never run** |
| Treasure record `+0x02` as approach angle | **High** (2026-08-09) | `lha` → `peopleSetRot`, traced |
| Treasure collected/spawn flags (`+0x06`/`+0x08`) | **High** (2026-08-09) | `GSflagTest` branches in `_floorInitTresure` |
| Room-script interaction records (§7) | **High** (2026-08-09) | 241/241 resolve, 0 out of range; every publishable record's region exists in its room's geometry |
| Room-script semantic classification | **High** for the 7 traced classes | direct-call markers, each verified exclusive per record across all 241 |
| Activation state for room-script objects | **Unresolved** | see INTERACTABLE_OBJECTS.md §9 |
| Method byte as press-A discriminator | **High** (2026-08-09) | consistent across all 832 records, both marker families |
| Live `GScolsys2` enable records | Unverified | static trace only, never read live |
| Whether role NPCs cluster by `people_info_id` | Moot | superseded by the talk-script role table |

---

## 7. The room-script interaction chain (added 2026-08-09)

§4's first Phase 4 candidate — "unparsed `common.rel` interaction types"
— is **disproven**. All 591 marker-`0x0596` records use the six already-
parsed script values; there is no seventh type.

The missing system is the **other 241 records**, which carry marker
`0x0100`:

```
common.rel interaction record, 0x1C stride
   +0x08 marker == 0x0100          (not 0x0596)
   +0x0A index into the OWNING ROOM SCRIPT's own function table
   +0x02 owning room id       +0x07 region_index       +0x00 method
      |
      +--> rooms/<code>.scd function table (declaration order == index)
      |       the named handler IS the object's semantic identity
      +--> the same .ccd interactable triangle lists §1b already parses
```

Verified as a falsifiable prediction against the owner's 425 extracted
room scripts: **241 of 241 resolve to a named function, 0 out of range.**
The names are `watch_tv`, `check_bookshelf`, `tako_machine`, `esa_set`,
`check_snatchmachine`, `bed_recovery`, `check_shrine`, `crane_move_*`,
`hero_fall`, `pier_trouble` — the object classes the brief asks for, in
the game's own words.

Because these carry `(room_id, region_index)`, §1b's machinery already
positions them; only the semantic classification is new work, and it is
the existing `build_npc_role_table.py` technique pointed at interaction
functions instead of talk functions.

**`+0x00` (method) is the press-A discriminator**, consistent across both
marker families and all 832 records: method 3 = stand inside and press A
(sign, PC, `watch_tv`, every bed, `esa_set`, `check_shrine`); methods 1
and 2 = fires on entry (warp, elevator, door, `booth_battle_*`,
`hero_fall`).

Three current hardcodes are directly replaced: the `0x87` Relic Stone
relabel (`check_shrine` in `M3_shrine_1F`), `POKESPOT_ROOMS` (`esa_set` in
`esaba_A/B/C`, gated on general flag 1404 — not the three hardcoded flag
numbers), and `npc_beacons.HEALING` (room 0x8A is `M5_apart_1F`, whose
only record is `check_mana_bed` — that "Healing station" is a **bed**).

**IMPLEMENTED in Phase 4 (2026-08-09)** by `interactables.py` and
`interactable_roles.py`, fed by the generated `assets/interactables.json`.
Classification uses each handler's own **direct** standard-library calls
(transitive reachability over-attributes through shared room helpers);
positions use `region_geometry.Region.nearest_point`, not the centroid.
Full enumeration, per-category breakdown and results:
[INTERACTABLE_OBJECTS.md](INTERACTABLE_OBJECTS.md).

**Not in this table: the Purify Chamber.** No marker-`0x0100` record
resolves to a purify handler in any room, so its entry point is owned
elsewhere — the `common.rel` PC type or an NPC talk script. Open question,
not a gap to guess at.

---

## 8. The treasure record, fully resolved (added 2026-08-09)

Re-disassembled from
`xd-decomp/build/GXXE01/asm/game/pxdvs/app/floor/`:
`_floorInitTresure` (0x8011F838), `floorEventGetTresureList` (0x80121260),
`floorEventSetTresureDisp` (0x80121310), `floorEventChangeTresure`
(0x801213B0).

| Offset | Field | Evidence |
|---|---|---|
| +0x00 bits 5-7 | kind | `extrwi r0, r0, 3, 24` = `(byte >> 5) & 7`, two call sites |
| +0x01 | script-writable byte | `stb r5, 0x1(r4)` |
| +0x02 | s16 **facing** | `lha` → int→float → `peopleSetRot` |
| +0x04 | u16 room id | compared to the floor's own `+0x02` |
| +0x06 | u16 **collected flag** | `GSflagTest` set ⇒ `floorEventCtrlTresure(…, 0)` |
| +0x08 | u16 **spawn flag** | `GSflagTest` clear ⇒ `peopleSetDisp(…, 0)` |
| +0x0C | item id | `stw r0, 0xC(r4)` in `floorEventChangeTresure` |
| +0x10/14/18 | float x, y, z | → `peopleSetPos` |

Kind dispatch, branch by branch: 1 → model `0x02F80400`, 2 →
`0x02F90400`, 3 → `0x02FA0400`; kind 0 and kind ≥ 4 select no model.
**Placeable kinds are 1, 2, 3** — `TREASURE_KINDS = (1, 2, 4)` is wrong on
both the bits and the set.

Identity, two authoritative keys:

- actor `resID` = `0x7FFF0000 | ordinal`, ordinal counting only this
  room's records in table order, masked to 9 bits (`clrlwi r27, r3, 23`);
- `peopleBiosSetTresureID(globalIndex)` puts the **global table index** on
  the actor. That is the better identity — stable across rooms, does not
  renumber.

Treasure actors also get `peopleSetFlagOn(…, 4)` (actor flag bit 2) and
`peopleAddCollision`, so **they block pathfinding** — which the router
does not currently model.

**Why this supersedes the disp-only conclusion.** Reading `people_work
+0x0D` is correct, but `disp == 0` cannot distinguish "already collected"
from "has not spawned yet", and the brief requires those to behave
differently. The two flag ids give the reason directly, read through the
existing `GeneralFlagReader`, and work with no live actor at all.

### 8a. The state machine — `floorEventCtrlTresure` (0x80121934)

Traced 2026-08-09. One function owns every treasure transition:

| Mode | Meaning | kind 1 | kinds 2/3 |
|---|---|---|---|
| 0 | "this has been taken" | `peopleSetMotion(.., 2, ..)` (open pose) **and `peopleSetFlagOn(actor, 1)`** | **`peopleSetDisp(actor, 0)`** |
| 1 | "available" | motion 0 | motion 0 |
| 2 | pick it up | early-return if `GSflagTest(+0x06)`; opening motion + sound `0x461`; then mode 0; then **`GSflagOn(+0x06)`**; then `floorEventGetTresure(category, item id, +0x01)` | as above without the motion |
| ≥3 | nothing | | |

`heroMove` (0x8014FE14) drives mode 2: A press → `peopleCheckTresure` →
`floorEventCtrlTresure(.., 2)`. So the **collected flag is written by the
engine at pickup**, and mode 2 refuses to run twice.

**This is what kinds 1, 2 and 3 mean**, read off mode 0 rather than
inferred from appearance:

- **kind 1 keeps its actor and changes pose.** It also gets
  `peopleSetFlagOn(actor, 1)` — bit 0 of `people_work +0x10`, precisely
  the flag that makes `peopleTalkCheck` skip an actor. A collected kind 1
  is still standing there, opened, and no longer interactable. That is an
  **item box**, and it is why "Opened item box" may remain a landmark.
- **kinds 2 and 3 are hidden outright.** Nothing remains to navigate to.
  Those are **loose pickups** — ground items, sparkles, dropped and story
  items.
- Kind 0 and kinds 4–7 select no model and are not placeable.

Byte `+0x00` carries two 3-bit fields, not one: bits 5–7 are the placement
kind (`extrwi r0, r0, 3, 24`), bits 2–4 are a **pickup category** passed to
`floorEventGetTresure` (`extrwi r3, r0, 3, 27`). The second is read and
carried in metadata; its value set is not yet decoded.

### 8b. The treasure interaction predicate — NOT the NPC one

`peopleTalkCheck`'s treasure branch (0x802A3684) is reached exactly when
`floorCharacterBiosFindByResID` returns NULL. Differences from the
character path, all from that branch:

| Gate | Characters | Treasure |
|---|---|---|
| displayed, talk-flag bit 0, distance, hero facing cone | apply | **apply** |
| talk-start type | applies | n/a — no static record |
| **wall check** | applies unless `talkWallThrough` | **skipped entirely** — the branch forces the wall flag to 0 |
| **box approach angle** | n/a | **kind 1 only**: `peopleBiosGetRot` → `peopleVecCalcRotY`, rejected beyond the threshold |

The box approach angle's argument order is not established, so the source
reports it UNKNOWN and downgrades the wording to "In range" rather than
promising a press will land.
