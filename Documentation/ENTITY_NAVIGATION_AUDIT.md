# ENTITY_NAVIGATION_AUDIT.md

Phase 1 audit of overworld entity navigation and interactable objects.
**Pass 1: 2026-08-06. Pass 2 (re-audit): 2026-08-09.** No production code
was changed in either pass.

**Read [§0](#0-pass-2-re-audit-2026-08-09) first.** It supersedes the
status claims below: the Phase 2 NPC source that the rest of this document
describes as landed is **not what production runs**, and the single most
important fact about the current navigator is not in §1-§7.

---

## 0. Pass 2 re-audit, 2026-08-09

Commissioned because entity navigation is still reporting entities at
incorrect locations, still reporting duplicate clerks, and still saying
"NPC A". This pass re-derived the ownership chains from the engine rather
than trusting Pass 1's conclusions, and re-read the production wiring
rather than the module that was written to replace it.

### 0.1 Baseline

```
Ran 1115 tests in 21.522s
OK
TOTAL_RUN=1115 FAIL=0 ERR=0 SKIP=0
```

Same throwaway runner as Pass 1 (`Companion` on `sys.path`,
`loader.discover(tests_dir, top_level_dir=tests_dir)`, under
`Companion\.venv\Scripts\python.exe`). 1007 → 1106 (Phase 2) → **1115**
(Codex's menu/PDA work since).

### 0.2 The headline finding: production never ran Phase 2

`phase1b_app.build_overworld_sources` was reverted to the pre-Phase-2 NPC
path on 2026-08-06 and **has not been restored since**
([phase1b_app.py:406-439](../Companion/battle_narrator/phase1b_app.py)).
`LiveNPCEntitySource` is imported and never constructed;
`PeopleRuntimeSource` is constructed and handed only to the diagnostic.

So every symptom in the current report is a symptom of the code Pass 1
already indicted, still running:

| Reported symptom | Production line responsible | Certainty |
|---|---|---|
| Three Agate Mart clerks | `role_rooms = {0x85: …, 0x86: …}` matched against `entity.identity[1]`, which is the **floor id** — `phase1b_app.py:429` | Certain (code + log) |
| "NPC A" wording | `f"NPC {letters[npc.identity]}"` — `entity_sources.py:125` | Certain |
| NPC announced where nobody is | `NPCMemorySource.npcs()` falls back to the **static spawn position** and the **stale static visible bit** when no live actor is found — `npc_beacons.py:342-363` | Certain |
| "In range" but A does nothing / never in range | old rule `horizontal(hero, modelOrigin) <= people_info[+0x24] + 1.5`, four talk gates unimplemented | Certain |

The revert is recorded honestly in
[ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md)'s handoff and in the
source comment, with a correct reason: `LiveNPCEntitySource` is strictly
*more* selective, so one wrong offset empties the NPC category entirely,
and that is what the project owner hit mid-dungeon. **Nothing here argues
for flipping it back blind.** It argues that the fix is a source that
cannot empty the category — see §0.7.

### 0.3 The validation mechanism has never run

`--interaction-diagnostics` is not passed by
`Launch Pokemon XD Accessible.cmd`, and the production log contains
**zero** occurrences of `INTERACTION DIAG`, `NPC SOURCE rejected`,
`NPC SOURCE excluded`, `neck=`, or `talk_live=` across the whole
2026-08-06 → 2026-08-09 window.

Consequence: every "the diagnostic will settle this" claim in the Phase 2
documents is still open. Nothing in Phase 2 has one byte of live evidence
behind it. The three questions it was built to answer —
`neck_offset=`, `talk_live=` vs `talk_static=`, and `talk_sct=` — are
exactly as unanswered as they were on 2026-08-06.

### 0.4 Log evidence, 2026-08-06 → 2026-08-09

144 MB tail of `Companion/logs/battle_narrator_phase1b.log`.

**Duplicate clerks, reproduced after the revert.** Agate Mart, three
physically distinct NPCs, identical label, no disambiguation:
```
2026-08-07 11:46:02.343  ENTITY NAV Pokemon Mart clerk.  2 o'clock, distance 75. Out of interaction range.
2026-08-07 11:46:03.428  ENTITY NAV Pokemon Mart clerk.  2 o'clock, distance 27. Out of interaction range.
2026-08-07 11:46:04.434  ENTITY NAV Pokemon Mart clerk. 11 o'clock, distance 11. Out of interaction range.
```

**"NPC A" wording, reproduced.**
```
2026-08-08 16:55:03.191  ENTITY NAV NPCs. 4 available. NPC A. 2 o'clock, distance 56. Out of interaction range.
2026-08-08 16:55:09.161  ENTITY NAV NPC C. 11 o'clock, distance 71. Out of interaction range.
```

**Interaction range is broken, quantitatively.** Over three days:

| Phrase | Count |
|---|---:|
| `Out of interaction range` | 2396 |
| `In range but facing away` | 54 |
| `Interaction available` | **4** |

All four "Interaction available" lines are Items. **Not one NPC in three
days of play was ever reported as interactable**, including at distance
10-11 units from a Mart clerk the player was standing at. This is the
measured shape of defect N6: the old rule omits both collision-ball terms
(~3.5 each), so it under-reports range by roughly 7 units — which is most
of a real interaction radius.

**Opened items still never happen.** `(opened)` appears **0 times**,
consistent with Pass 1's finding over the older 367 MB. The opened-state
path has now never fired in any session in the project's history.

**CCD-region positions still absurd.**
```
2026-08-08 13:27:48.037  ENTITY NAV Interactables. 1 available. PC. 1 o'clock, distance 167.
2026-08-08 16:57:13.424  ENTITY NAV Warp to house in Gateon Port D. 10 o'clock, distance 634, below.
2026-08-08 17:00:05.200  ENTITY NAV Items. 1 available. Item. 11 o'clock, distance 487. Out of interaction range.
```

**Bridges.** 17 `GATEON BRIDGE` lines, still no observed state change.

### 0.5 New engine findings — the room-script interaction chain

Pass 1 listed "enumerate the unparsed `common.rel` interaction types" as
the first Phase 4 experiment. It was run this pass, offline, over the
owner's own extracted `common.rel`. Two results, one negative and one
large:

**Negative — there are no unparsed types.** All 832 records, 591 with the
`0x0596` common-script marker:

| script | meaning | records | rooms | methods |
|---|---|---:|---:|---|
| 0x04 | warp | 271 | 140 | 1 |
| 0x05 | door | 150 | 63 | 1, 2 |
| 0x06 | elevator | 46 | 31 | 2 |
| 0x0C | text/sign | 89 | 39 | 3 |
| 0x0D | cutscene warp | 9 | 5 | 1, 2 |
| 0x0E | PC | 26 | 26 | 3 |

The hypothesis that televisions or beds hide in an unparsed common type is
**disproven**. Recorded so it is not re-investigated.

**Large — the other 241 records are the missing object system.** They
carry marker `0x0100` instead of `0x0596`, and `+0x0A` is an index into
the **owning room script's own function table**, not a common script id.
Tested against the owner's 425 extracted room scripts: **241 of 241
resolve to a named function, 0 out of range.** The names are the object
classes the brief asks for, in the game's own words —
`watch_tv` (×14), `check_bookshelf` (×7), `tako_machine` (×6),
`esa_set` (×3, the PokéSpot plates), `check_snatchmachine` (the Snag
Machine), `crane_move_*` (×20), `bed_recovery` / `bed_de_kaihuku` /
`ev_bed` / `check_mana_bed`, `recover` / `recovery_*`, `check_shrine`
(the Relic Stone), `pier_trouble` (Gateon), `auto_sales`,
`ev_factory_stop_1`.

Full enumeration and the proposed category design:
[INTERACTABLE_OBJECTS.md](INTERACTABLE_OBJECTS.md).

Three consequences that matter immediately:

1. **Position is already solved for these.** They carry the same
   `(room_id, region_index)` pair as warps and signs, so
   `parse_interactable_region_centers` already positions them — once
   defect P1 is fixed.
2. **Three current hardcodes have a real owner.** The `0x87` Relic Stone
   relabel is `check_shrine` in `M3_shrine_1F`. `POKESPOT_ROOMS`'
   three room ids are `esa_set` in `esaba_A/B/C`, whose real gate is
   general flag **1404**, not the three hardcoded flag numbers. And
   `HEALING = {0x8A: …}` is `M5_apart_1F`, whose only interaction record
   is **`check_mana_bed`** — that hand-captured "Healing station" is a
   **bed**, mislabelled as well as unowned.
3. **`+0x00` (the "method" byte) is the press-A discriminator.** Method 3
   is every press-A object (sign, PC, `watch_tv`, `check_bookshelf`,
   `esa_set`, the beds); methods 1 and 2 are every walk-into trigger
   (warp, elevator, `booth_battle_*`, `auto_door`, `fall_box`). It is
   consistent across both marker families and all 832 records. The
   navigator can therefore say "walk into it" versus "press A" from game
   data, and beacon policy can differ per trigger style.

### 0.6 New engine findings — the treasure record is fully resolved

Re-disassembled `_floorInitTresure` (0x8011F838), `floorEventGetTresureList`
(0x80121260), `floorEventSetTresureDisp` (0x80121310) and
`floorEventChangeTresure` (0x801213B0) from
`xd-decomp/build/GXXE01/asm/game/pxdvs/app/floor/`. The 0x1C-byte record:

| Offset | Field | Evidence |
|---|---|---|
| +0x00 bits 5-7 | kind | `extrwi r0, r0, 3, 24` — **`(byte >> 5) & 7`**, at two call sites |
| +0x01 | script-writable byte | `stb r5, 0x1(r4)` in `floorEventChangeTresure` |
| +0x02 | s16 **facing** | `lha r4, 0x2(r30)` → int→float → `peopleSetRot` |
| +0x04 | u16 room id | compared against the floor's own `+0x02` |
| +0x06 | u16 **collected flag** | `GSflagTest` → set ⇒ `floorEventCtrlTresure(…, 0)` (disable) |
| +0x08 | u16 **spawn flag** | `GSflagTest` → clear ⇒ `peopleSetDisp(…, 0)` (hidden) |
| +0x0C | item id | `stw r0, 0xC(r4)` in `floorEventChangeTresure` |
| +0x10/14/18 | float x, y, z | → `peopleSetPos` |

Kind dispatch, decoded branch by branch: kind 1 → model `0x02F80400`,
kind 2 → `0x02F90400`, kind 3 → `0x02FA0400`; kind 0 and kind ≥ 4 select
**no** model. Placeable kinds are **1, 2, 3**. `TREASURE_KINDS = (1, 2, 4)`
in `treasure_entities.py` is wrong on both the bit positions and the set,
so the PokéSpot `kind == 4` branch is reading a kind the engine never
produces — which is consistent with §0.5's finding that plates are not
treasure records at all.

Identity, both keys confirmed:
- the actor's `resID` is `0x7FFF0000 | ordinal`, ordinal counting **only
  this room's** records in table order, masked to 9 bits
  (`clrlwi r27, r3, 23` in `floorEventGetTresureList`);
- the actor additionally carries `peopleBiosSetTresureID(globalIndex)` —
  the **global** table index. That is the better identity: it is stable
  across rooms and does not renumber.

Treasure actors are also marked: `peopleSetFlagOn(…, 4)` sets actor flag
bit 2, and `peopleAddCollision` gives them collision — so they block
pathfinding, which the router does not currently know.

**This supersedes Pass 1's answer to Cause E.** Reading the actor's `disp`
byte is correct but insufficient: `disp == 0` cannot distinguish "already
collected" from "has not spawned yet", and the brief requires those to be
different states with different behaviour. The record's two flag ids give
the reason directly, are readable through the existing
`GeneralFlagReader`, and work without a live actor at all.

Pass 1's "record `+0x02` is a strong candidate for the approach angle —
UNVERIFIED" is now **verified**: it is the object's Y rotation, fed
straight to `peopleSetRot`.

### 0.7 What changed in the plan

Pass 1's phase order stands. Three revisions:

**Phase 2 becomes "restore without the cliff", not "flip the switch."**
The reason the live source was reverted is that it can return zero
entities, and it does so silently. Before it is re-enabled it needs:
a shadow mode that runs both sources and logs the diff without speaking;
per-rule rejection counters visible in the ordinary production log (not
behind an off-by-default flag); and a fallback that keeps the previous
source's output when the live source publishes nothing in a room where
the static table says characters exist. Validity **rule 6** (the actor
vs static `people_info_id` cross-check) deserves particular scrutiny — it
is a project-invented consistency check the engine does not perform, and
it is the single rule most able to empty the category if
`people_work +0x1C` is not what the profile assumes.

**Phase 3 gains the flag pair and loses the disp-only theory** (§0.6),
and the PokéSpot plates move out of Phase 3 entirely into Phase 4, where
their real owner is.

**Phase 4 is no longer an open question.** §0.5 answers it. The work is a
generator in the shape of the existing `build_npc_role_table.py`, walking
room-script *interaction* functions instead of talk functions and
classifying them by the standard-library calls they reach.

### 0.9 Phase 3 outcome (2026-08-09)

Causes **D** (wrong kind bits), **E** (opened/collected/spawned inferred
rather than read) and **F** (beacon welded to navigation) are **closed**.
`treasure_entities.py` was rewritten against the traced state machine —
see [ENTITY_NAVIGATION_ARCHITECTURE.md](ENTITY_NAVIGATION_ARCHITECTURE.md)
§8a/§8b. `POKESPOT_ROOMS` and its `kind == 4` branch are **deleted**:
plates are room-script interaction regions, not treasure records
([INTERACTABLE_OBJECTS.md](INTERACTABLE_OBJECTS.md) §3.3). Suite 1200 →
**1226**.

Still open from §0.5: cause **C** (CCD-region centroids, Phase 3b) and the
Phase 4 object table.

### 0.10 Phase 4 outcome (2026-08-09)

The Phase 4 object table shipped. 241 records classified from traced
behaviour into 7 semantic classes plus a generic press-A bucket; hazards
got their own category; region positions use nearest-point rather than the
centroid, which closes cause **C** for this source (the warp/door/elevator/
PC/sign sources still use centroids -- Phase 3b remains open for them).

`region_geometry.py` is the shared helper those sources should adopt.

### 0.8 Explicitly not done in this pass

- No production code changed. No test added or removed. Suite still 1115.
- No live memory read, no input sent, no Dolphin interaction.
- No battle system touched, read, or referenced.

---

## Pass 1 — 2026-08-06

> **Phase 2 landed 2026-08-06** *(and was reverted in production the same
> day — see §0.2)*. Causes **A** (role keyed on the room id),
> **B** (interaction point and predicate), **I/X1** (duplicated source map)
> and **J** (letters and wording) are closed for NPCs. Causes **C**
> (CCD-region centroids), **D**/**E**/**F** (items, opened state, beacon
> eligibility), **G** (the `Entity` state model beyond NPCs) and **H**
> (bridges) remain open and are unchanged below. Suite 1007 → **1106**.
> New deliverables: [ENTITY_IDENTITY_MODEL.md](ENTITY_IDENTITY_MODEL.md),
> [ENTITY_POSITION_AND_INTERACTION_POINTS.md](ENTITY_POSITION_AND_INTERACTION_POINTS.md),
> [INTERACTION_DIAGNOSTIC.md](INTERACTION_DIAGNOSTIC.md).

Companion document:
[`ENTITY_NAVIGATION_ARCHITECTURE.md`](ENTITY_NAVIGATION_ARCHITECTURE.md)
holds the per-source ownership map. This document holds the baseline, the
source inventory with authority ratings, the hardcoding audit, the log
review, the root-cause grouping, and the sequenced plan.

---

## 1. Baseline

Full suite, run before anything was read or changed:

```
Ran 1007 tests in 20.176s
OK
TOTAL_RUN=1007 FAIL=0 ERR=0 SKIP=0
```

Invoked with a throwaway runner that puts `Companion` on `sys.path` and
calls `loader.discover(tests_dir, top_level_dir=tests_dir)` under
`Companion\.venv\Scripts\python.exe`. Neither obvious invocation works —
`tests/` has no `__init__.py` and the tests import `battle_narrator.*`.

**No `CLAUDE.md` exists** anywhere in the project tree. The instruction to
read it could not be honoured because there is nothing to read; the living
documents under `Documentation/` were read instead.

**There is no separate Codex Gateon Port/bridge document.** All bridge
knowledge in the repository lives in `gateon_bridge.py`'s module docstring
and a stale cross-reference in the coverage matrix. That gap is itself a
finding (see §5, defect **B4**).

---

## 2. Source inventory and authority rating

Every source feeding entity navigation today, with what it actually is.

| # | Source class | Category | Kind | Authority |
|---|---|---|---|---|
| 1 | `NPCEntitySource` -> `NPCMemorySource` | `npc` | live + static | **Partially authoritative.** Correct table, correct index mapping, but 4 of the engine's 10 talk gates unimplemented and the interaction point is the wrong body reference |
| 2 | `TalkedNPCEntitySource` | `npc` | session-local | Accessibility-owned; not game state. Fine as designed |
| 3 | `FilteredEntitySource` (role NPCs) | `interact` | **inferred** | **Not authoritative — actively wrong.** Keys role identity on the room id |
| 4 | `LiveTreasureEntitySource` | `item` | live | **Not authoritative.** Right table, wrong field decode |
| 5 | `AuthoritativeWarpEntitySource` | `warp` | static | **Authoritative for identity/destination, not for position** |
| 6 | `AuthoritativeElevatorEntitySource` | `elevator` | static | as #5 |
| 7 | `AuthoritativeDoorEntitySource` | `door` (beacon only) | static | as #5 |
| 8 | `AuthoritativePCEntitySource` | `interact` | static | as #5, plus the type's parameters are documented "unused in XD" |
| 9 | `AuthoritativeTextEntitySource` | `sign` | static | as #5 |
| 10 | `CategoryFilteredEntitySource("healing")` -> `npc_beacons.HEALING` | `interact` | **hardcoded** | **Not authoritative.** One room, one hand-captured coordinate |
| 11 | `FilteredEntitySource` (Relic Stone) | `interact` | **hardcoded** | **Not authoritative.** Room `0x87` sign relabelled by room id |
| 12 | `GateonBridgeReader` | — (announcer) | **hardcoded** | Flag ownership authoritative; 16 coordinate boxes are not |
| 13 | `WarpEntitySource` | — | dead | **Unreferenced.** Superseded; still present in `entity_sources.py` |
| 14 | `npc_beacons.ITEMS` | — | dead | Empty dict, still wired into `npcs()` |

Two further wrappers are structural, not sources: `WarpAugmentedNPCSource`
(injects an entity stream into the beacon reader as synthetic NPCs) and
`RecategorisedNPCSource` (relabels in place). Both are sound ideas; the
first is where beacon eligibility gets welded to navigation eligibility
(§5, **X3**).

---

## 3. Hardcoding and heuristic audit

Required by the brief. Everything below is a room id, coordinate, count,
label or flag written into source rather than derived.

| Location | What | Verdict |
|---|---|---|
| `phase1b_app.py` x2 | `role_rooms = {0x85: "Pokemon Center nurse", 0x86: "Pokemon Mart clerk"}` | **Remove.** Root cause of the duplicate-clerk report |
| `phase1b_app.py` x2 | Relic Stone gate: `current_floor_id == 0x87` | **Remove.** Same class of guess |
| `profile.py` | `pokemart_room_ids = (0x86,)` | **Remove.** Beacon-side twin of the same guess |
| `npc_beacons.py` | `HEALING = {0x8A: Position(-89.0, 0.0, -42.9)}` | **Replace** with the owner in `HEALING_SERVICE_SCRIPT_TRACE.md` |
| `npc_beacons.py` | `ITEMS = {}` | **Delete.** Dead |
| `treasure_entities.py` | `POKESPOT_ROOMS` — 3 room ids, 3 labels, 3 flag numbers | **Replace.** PokéSpot plates are a real object class; find their owner |
| `treasure_entities.py` | `TREASURE_KINDS = (1, 2, 4)` | **Wrong values and wrong bits** — see I1/I2 |
| `gateon_bridge.py` | `_RAW_PAD_TRANSITIONS` — 16 coordinate boxes | **Remove.** Derivable from script + `.ccd` |
| `gateon_bridge.py` | `{58: "southern", 59: "northern"}` | **Verify or remove.** `pier_def` never touches 58/59 |
| `gateon_bridge.py` | `ALIGNMENTS` prose per state | Acceptable as accessibility-owned wording **if** the state itself is read live, which it is (flag 968) |
| `entity_sources.py` | `TalkHistory.STORY_PROGRESS_FLAG = 964` | Acceptable — a flag id, read live |
| `authoritative_warps.py` | interaction script type constants | Acceptable — structural, from `XGInteractionPoint` |

Accessibility-owned generic labels ("Item box", "Television", "Bed"…) are
explicitly permitted by the brief and are **not** in scope for removal.
The distinction being applied: a *label for an object class* is fine; a
*room id, coordinate, count or per-room list* is not.

---

## 4. Log review

`Companion/logs/battle_narrator_phase1b.log`, 367 MB, sessions through
2026-08-06 11:37.

**Duplicate Poké Mart clerks — reproduced.**
```
2026-08-05 21:58:44.847  ENTITY NAV Interactables. 3 available. Pokemon Mart clerk. 11 o'clock, distance 26. Out of interaction range.
2026-08-05 21:59:16.737  ENTITY NAV Interactable. Pokemon Mart clerk. 11 o'clock, distance 27. Out of interaction range.
2026-08-05 21:59:21.233  ENTITY NAV Interactable. Pokemon Mart clerk.  5 o'clock, distance 30. Out of interaction range.
2026-08-05 21:59:24.458  ENTITY NAV Interactable. Pokemon Mart clerk.  2 o'clock, distance 16. Out of interaction range.
```
Three physically distinct NPCs at three bearings, all with the identical
label and no disambiguation. `0x86` is `M3_shop_1F` per
`Companion/assets/room_ids.json` — the Agate Village Poké Mart.

**Entities announced far from the player, in the CCD-region categories.**
```
2026-08-05 22:57:33.076  ENTITY NAV Interactables. 1 available. PC. 10 o'clock, distance 232, below.
2026-08-06 11:33:43.715  ENTITY NAV Elevator to Cipher Lab lab, basement level 3. 6 o'clock, distance 437, above.
2026-08-06 11:34:27.735  ENTITY NAV to house in Agate Village, 1st floor B. 12 o'clock, distance 366, above.
```
Room at 11:33 was floor 8, `Cipher Lab lab, basement`. Three elevators all
announcing the same destination at 143 / 287 / 437 units apart.

**Items never disappear and never report as opened.**
```
2026-08-06 11:29:35.504  ENTITY NAV Items. 5 available. Item. 2 o'clock, distance 19, above.
2026-08-06 11:33:38.528  ENTITY NAV Items. 5 available. Item. 4 o'clock, distance 39.
```
The count holds at 5 across the session. The substring `(opened)` — the
only label `LiveTreasureEntitySource` can produce for a collected pickup —
appears **0 times in the entire 367 MB log**, across every session. The
opened-state path has never once fired.

**Unnamed NPC wording, as reported.**
```
2026-08-06 11:35:08.954  ENTITY NAV NPCs. 14 available. NPC I. 6 o'clock, distance 39, below.
2026-08-06 11:36:01.471  ENTITY NAV NPCs.  1 available. NPC A. 3 o'clock, distance 140.
```

**Bridge state never observed changing.** Every `GATEON BRIDGE` line in
the log reports alignment 0. There is no live evidence of a state
transition, of stale endpoints, or of the pathfinder disagreeing with the
bridge — those remain predicted from the script and `.ccd`, not observed.

**Not found in the logs:** any record of an interaction failing after
"Interaction available" was spoken. `INTERACTION READY` lines exist
(`Press A to interact with Item.`, 2026-08-06 11:30) but nothing records
whether the subsequent A press landed. The audit brief's requested
position-validation framework — announced position, player position,
interaction position, distance, source record, and whether a normal A
press succeeded — **does not exist and needs building**. That is the one
place where the existing evidence is genuinely insufficient, and it is
Phase 7 work.

---

## 5. Root-cause grouping

Every reported symptom, grouped by the single underlying cause. Fixing the
cause fixes every symptom under it.

### Cause A — role identity is keyed on the room id
*Reported symptom: three clerks in the Agate Poké Mart.*

`entity.identity` is `("npc", floor_id, index)`; the predicate tests
`identity[1]`, which is the floor id. Every NPC in the room is relabelled.
Also misses every Mart and Center outside Agate. Defect **R1**.
Confidence: **certain**.

### Cause B — the interaction point is not where the game measures from
*Reported symptom: "NPC is directly ahead and in range, but pressing A finds nothing."*

Four independent contributors, all in `peopleTalkCheck` (§2 of the
architecture doc):

- **N3** the game measures to the **neck bone's X/Z**, not the model
  origin;
- **N6** the live talk distance is `people_work +0x178`, not
  `people_info +0x24`; the radius formula is
  `heroColBall + talkDistance + npcColBall`, not `talkDistance + 1.5`;
- **N2** four gates are unimplemented — `people_work +0x10` bit 0,
  talk-start-type 3, the push-box height band, and the wall check — so
  actors the game will *never* talk to are offered as targets;
- **I-kind-1** item boxes additionally require approaching from the box's
  own facing, which nothing models.

Confidence: **high** (all engine-traced). Which contributor dominates in
practice is unmeasured — that is what the Phase 7 validation harness is
for.

### Cause C — a region's centroid is announced as its interaction point
*Reported symptoms: warps/elevators/PCs/signs at wrong or absurd distances.*

Defect **P1**. Measured over all 843 regions in all 177 rooms: 842 are
large enough that a player legitimately inside can be >10 units (one full
interaction radius) from the announced point; 210 have a centroid outside
their own region by more than the 1.5-unit "same position" threshold; 11
by more than a full interaction radius, worst case 168.9 units of empty
space. Median distance from the centroid to the region's farthest point is
18.4 units.

One bug, five categories. Confidence: **high** (measured, not inferred).

Two adjacent hypotheses were tested and **disproven** this pass, and are
recorded so they are not re-investigated:
- CCD vertices are in object space, not world space — **no**; all 2,259
  top-level entries in all 177 rooms carry an identity transform.
- Merging CCD slots `+0x2C` and `+0x30` into one index namespace corrupts
  centroids — **no**; no index appears in both slots in any room.

### Cause D — treasure records are decoded with the wrong bits
*Reported symptoms: items at positions with nothing there; wrong item counts.*

- **I1** the engine reads the kind as `(byte >> 5) & 7` (`extrwi r0, r0,
  3, 24`, confirmed at two independent call sites); the code reads
  `byte & 0x7`.
- **I2** the engine's placeable kinds are 1, 2, 3; the code filters to
  1, 2, 4.

Together these select a near-arbitrary subset of the table. Confidence:
**high**.

### Cause E — opened/collected/spawned state is inferred, not read
*Reported symptoms: collected items still listed and still beaconing; opened boxes announced as available.*

The authoritative state is the pickup actor's `disp` byte
(`people_work +0x0D`), written by
`floorEventSetTresureDisp -> peopleSetDisp`. The code instead infers
"opened" from the record vanishing from the static table — a condition
that, per the log, **has never once occurred in any session**. The same
`disp` field is already read for NPCs a few lines away.

This also covers loose/story-spawned items (the PDA case): a pickup that
has not spawned yet is an actor with `disp == 0`, which is readable, not
guessable. Confidence: **high**.

### Cause F — beacon eligibility is welded to navigation eligibility
*Reported symptom: an opened box should stay as a landmark but stop beaconing.*

`WarpAugmentedNPCSource` synthesises `NPC(visible=True, talk_id=1)` for
every entity a wrapped source returns, so appearing in a source *is*
beaconing. There is no way to express "listed but silent". Defect **X3**.
Confidence: **certain** (structural).

### Cause G — the `Entity` model cannot carry state
*Underlies E and F and blocks the brief's required distinctions.*

`Entity` has no fields for active/visible/interactable/spawned/collected/
opened/enabled, no beacon policy, no separate interaction position, and no
runtime generation. Defect **X4**.

### Cause H — runtime collision-object enable state is a stub
*Reported symptom class: bridges.*

**FIXED 2026-08-13, live-validated.** `StaticObjectEnableState`
answered "always enabled". At Gateon Port, flag 968 drives
`GScolsys2SetObjEnable` on CCD entries 23–31 (the bridge's hit models; the
walk decks 44–62 are never toggled). With everything reported enabled,
`build_room_geometry` included all nine blockers in all four alignments, so
routing was wrong in every alignment. Defect **B1**.

`LiveObjectEnableState` now reads the engine's own `obj[i].flags` bit 0 and
`NavigationService.refresh_enable_state` invalidates cached geometry and
discards any active route when the signature changes, so an alignment change
rebuilds rather than steering on stale geometry. The structure, its
derivation and its verification are in COLLISION_DETECTION_INVESTIGATION.md
§"Runtime object-enable state". **Confirmed against a running game
2026-08-13** in `M3_out` (object 33 reported disabled; the statically
predicted 1861-node component reproduced exactly; the `disconnected`/partial
failures stopped). The Gateon cross-check against `pier_def`/flag 968 remains
worth running as an independent second oracle, because Agate does not
exercise a **mid-session** toggle and Gateon does.

This was never Gateon-specific: the same stub sealed Agate's Relic Stone cave
mouth into a 26-tile pocket (`M3_out` object 33) and split the cave interior
(`M3_cave_1F_1` objects 4 and 5). 27 of 212 room scripts toggle collision
objects.

Bridges also have no entity-nav presence at all (**B2**), positions come
from 16 hardcoded coordinate boxes (**B3**), and there is no bridge
documentation and a stale coverage-matrix entry (**B4**).

### Cause I — structural duplication and coarse error isolation
- **X1** `entity_nav_factory` and `overworld_entity_sources` build the
  same seven sources twice, ~45 lines apart.
- **X2** one source raising `MemoryError` clears the entire navigator,
  discarding the player's category and selection.

### Cause J — wording
- **N5** unnamed NPCs speak as `"NPC A"`; the brief requires `"A"`.
- **N4** letters are recomputed from the live set on every `entities()`
  call, so one NPC despawning silently renames every letter after it. They
  are also assigned *before* the role-NPC split, so the visible sequence
  can skip letters.

---

## 6. Prioritised plan

Ordered so each phase's foundation exists before the phase that needs it.
No phase starts before the previous one has passing tests.

**Phase 2 — canonical NPC source.** Causes A, B, J.
Compare `identity_a` against the floor group id; implement the four
missing talk gates; move the interaction point to the neck reference and
the radius to the engine's own three-term formula; verify whether
`people_work +0x178` is initialised from `people_info +0x24`; replace the
room-id role heuristic — first testing whether `people_info_id` clusters
role NPCs, and leaving role identity **unresolved rather than guessed** if
it does not; make letters stable for the room visit and drop the `"NPC "`
prefix. Regression: the Agate Poké Mart must stop reporting three clerks
while two genuinely separate NPCs in one room stay separate.

**Phase 2b — the `Entity` model.** Cause G, and only the fields Phases
2–5 actually justify: interaction position separate from world position,
an active/interactable/beacon triple, and a runtime generation. Nothing
speculative.

**Phase 3 — containers and loose items.** Causes D, E, F.
Fix the kind bits and kind set; read opened/collected/spawned from the
pickup actor's `disp`; identity becomes `(floor_id, ordinal)`; position
becomes the live actor position; label becomes "Item box" / "Opened item
box"; separate beacon eligibility from list membership; investigate
treasure record `+0x02` as the kind-1 approach angle; replace
`POKESPOT_ROOMS`.

**Phase 3b — interaction points for CCD regions.** Cause C.
Nearest-point-on-region, recomputed per query, shared by warp, door,
elevator, PC and sign. This is a self-contained change with a large
measured payoff and no dependency on Phases 2 or 3 — it can run in
parallel if that is preferred.

**Phase 4 — generic interactables.** Enumerate the unparsed `common.rel`
interaction types and the non-character actors that reach
`peopleTalkCheck`'s fallback branch, **before** writing any code. Propose
the category design from what is actually found. Fold new objects into
existing categories rather than adding one per type.

**Phase 5 — Gateon Port bridges.** Causes H, B1–B4.
Live-validate the `GScolsys2` enable records; parse the state->enable
table from the extracted script; derive endpoints from entries 23–31's own
geometry; delete the 16 coordinate boxes; verify or drop the 58/59 deck
mapping; wire enable state into `build_room_geometry`; write
`GATEON_BRIDGE_ACCESSIBILITY.md` and correct the coverage matrix.

**Phase 6 — associated menus.** Per-object interfaces, on the shared menu
infrastructure, once the objects themselves are correct.

**Phase 7 — validation harness and live regression.** Build the
position-validation logger the brief specifies (announced position, player
position, interaction position, distance, source record, whether a normal
A press succeeded) — it does not exist, and without it the relative weight
of Cause B's four contributors stays unmeasured. Then one entity category
or state transition at a time, with exact spoken output recorded.

**Deferred deliverables.** `ENTITY_IDENTITY_MODEL.md`,
`ENTITY_POSITION_AND_INTERACTION_POINTS.md`,
`ENTITY_STATE_AND_BEACON_POLICY.md`, `INTERACTABLE_OBJECTS.md` and
`GATEON_BRIDGE_ACCESSIBILITY.md` are written as Phases 2–5 land. Writing
them now would document implementations that do not exist.

---

## 7. Explicitly not done in this phase

- No production code changed. No test added or removed. Suite still 1007.
- No live memory read, no input sent, no Dolphin interaction.
- No battle system touched, read, or referenced.
