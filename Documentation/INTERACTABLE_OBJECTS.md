# INTERACTABLE_OBJECTS.md

The ownership chain for every non-character, non-pickup interactable object
in the overworld: televisions, beds, PokéSpot plates, the Snag Machine,
machines, consoles, bookshelves, the Relic Stone, and the Gateon Port pier
controls.

**Written 2026-08-09** as a Phase 1 (audit) deliverable; **implemented the
same day in Phase 4.** Everything here was derived offline from the project
owner's own extracted `common.rel` and room scripts — no live memory, no
input, no room-specific list typed in by hand.

> ## Phase 4 result (2026-08-09)
>
> `interactables.py` + `interactable_roles.py` ship this system, fed by
> `assets/interactables.json`, which `build_interactable_table.py`
> **generates** from the extraction. Classification comes from each
> handler's own **direct** standard-library calls, never from its name.
>
> | Class | Records | Label |
> |---|---:|---|
> | television | 17 | "Television" |
> | healing | 10 | "Healing machine" |
> | fall (hazard) | 8 | "Hole" |
> | bed | 5 | "Bed" |
> | plate | 3 | "PokeSpot plate" |
> | vending | 1 | "Vending machine" |
> | shrine | 1 | "Relic Stone" |
> | *unclassified* | 196 | "Interactable" (press-A only; walk-in suppressed) |
>
> The finding that could not have come from a name: **`tako_machine` is a
> healing machine** — six records calling `Character::101`
> (`useHealingMachine`) and `Player::countPartyPkm` exactly as the Pokémon
> Centre handlers do.
>
> Two markers had to be **tightened after a false positive**: keyed on
> handler *name*, `Character::76` also matched a `check_bookshelf` variant
> and `Player::countPurfiedPkm` also matched `talk_131_beedy`. Re-checked
> per record, both are now conjunctions. Had they shipped, a bookshelf
> would have been announced as a hole and a fortune-teller as the Relic
> Stone.

Read alongside
[ENTITY_NAVIGATION_ARCHITECTURE.md](ENTITY_NAVIGATION_ARCHITECTURE.md) §7
and [ENTITY_NAVIGATION_AUDIT.md](ENTITY_NAVIGATION_AUDIT.md) §0.5.

---

## 1. The question this answers

Pass 1 of the audit named two candidate owners for these objects and said
neither was assumed and both were cheap to enumerate. They were enumerated.

**Candidate 1 — unparsed `common.rel` interaction types: disproven.**
All 832 records in the interaction table were classified. The 591 records
carrying the `0x0596` common-script marker use exactly six script values,
and all six are already parsed:

| script | meaning | records | rooms | method byte |
|---|---|---:|---:|---|
| 0x04 | warp | 271 | 140 | 1 |
| 0x05 | door | 150 | 63 | 1, 2 |
| 0x06 | elevator | 46 | 31 | 2 |
| 0x0C | text / sign | 89 | 39 | 3 |
| 0x0D | cutscene warp | 9 | 5 | 1, 2 |
| 0x0E | PC | 26 | 26 | 3 |

There is no seventh type. No television, bed or plate is hiding in this
family.

**Candidate 2 — the other 241 records: this is the system.**

---

## 2. The ownership chain

```
common.rel interaction table   (rel pointer 62 = table, 63 = count)
  0x1C stride
  +0x08 marker == 0x0100        <- NOT the 0x0596 common-script marker
  +0x0A  index into the OWNING ROOM SCRIPT's own function table
  +0x02  owning room id
  +0x07  region_index
  +0x00  method (trigger style)
     |
     +--> room script (rooms/<room code>.scd)
     |      function table, declaration order == index order
     |      the named handler IS the object's semantic identity
     |
     +--> room .ccd, interactable triangle lists at +0x2C / +0x30
            each 0x34-byte triangle carries its region_index
            -> the object's world region
```

**Verification.** The mapping was stated as a falsifiable prediction — every
`+0x0A` value must be less than its own room's declared function count —
and tested against the owner's 425 extracted room scripts:

```
marker-0x0100 records: 241
  resolved to a named function : 241
  index out of function range  : 0
  no extracted script          : 0
```

241 of 241, zero failures. The names are not generic — they are
`watch_tv`, `check_bookshelf`, `bed_recovery`, `check_snatchmachine`. A
wrong index would produce arbitrary names like `preprocess` or `sound` at
random; it produces object handlers every time.

**This is the same shape as the NPC role table**
(`build_npc_role_table.py`, `assets/npc_roles.json`), which resolves an
NPC's role from its own talk script id. The object table is that generator
pointed at interaction records instead of talk records.

---

## 3. What is actually there

89 distinct handlers across 241 records. Grouped by what a blind player
would do with them, not by internal name.

### 3.1 Televisions — 17 records

| Handler | Records | Rooms |
|---|---:|---|
| `watch_tv` | 14 | `M1_houseA_1F`, `M1_houseA_2F`, `M1_houseB_1F`, `M1_houseC_1F`, `M2_building_4F`, `M2_houseA_1F`, … |
| `watch_tv_l` | 1 | `M6_crab_2F` |
| `watch_tv_r` | 1 | `M6_crab_2F` |
| `watch_monitor_tv` | 1 | `S3_labo_1F` |

All method 3 (press A). `M6_crab_2F` proves two televisions can share one
room and must stay distinguishable — the left/right split is the game's
own, not a label this project would have to invent.

### 3.2 Beds and healing — 9 records

| Handler | Records | Room |
|---|---:|---|
| `bed_recovery` | 1 | `D3_ship_bridge` |
| `bed_de_kaihuku` | 1 | `M3_houseC_2F` |
| `ev_bed` | 2 | `M1_houseB_1F` |
| `check_mana_bed` | 1 | `M5_apart_1F` (0x8A) |
| `recover` | 1 | `M2_building_3F` |
| `recovery_m2_enter_1f` | 1 | `M2_enter_1F` |
| `recovery_d5_factory_2f` | 1 | `D5_factory_2F` |
| `recovery_s2_building_1f_2` | 1 | `S2_building_1F_2` |

**This replaces `npc_beacons.HEALING = {0x8A: Position(-89.0, 0.0, -42.9)}`
outright**, and corrects it: room 0x8A is `M5_apart_1F`, whose only
interaction record is `check_mana_bed`. The hand-captured "Healing station"
is a **bed**. The label was wrong as well as the ownership.

Pokémon Centre healing is a *different* system — an NPC talk script
reaching `Character::101` (`useHealingMachine`), already covered by
`npc_roles.json`. Both should surface under one user-facing "Healing"
concept while keeping separate owners.

### 3.3 PokéSpot food plates — 3 records

| Handler | Records | Rooms |
|---|---:|---|
| `esa_set` | 3 | `esaba_A` (0x5A), `esaba_B` (0x5B), `esaba_C` (0x5C) |

Method 3. The handler body (extracted, `rooms/esaba_A.txt`) gates on
general flag **1404** and calls `UnknownClass60::16` / `::19`.

`treasure_entities.POKESPOT_ROOMS` used to hardcode those three room ids,
three English labels, **and three flag numbers (1248/1249/1250)**, reached
through a treasure-kind branch (`kind == 4`) the engine never produces.
**Deleted in Phase 3 (2026-08-09)** along with the rest of that special
case. Plates are not treasure records at all; they are these `esa_set`
interaction regions, gated on general flag **1404**, and they belong to
Phase 4.

### 3.4 Machines, consoles and story devices — ~30 records

| Handler | Records | Rooms | Likely object |
|---|---:|---|---|
| `tako_machine` | 6 | `D1_labo_1F`, `D1_labo_B1`, `D6_dome_1F`, `D6_fort_1F`, `D6_fort_2F_2`, `M5_labo_1F` | a recurring lab machine |
| `crane_move_*` (16 handlers) | 20 | `S3_labo_B1up`, `D6_fort_5F` | crane control console |
| `check_snatchmachine` | 1 | `M5_labo_1F` (0x8C) | **the Snag Machine** |
| `ev_factory_stop_1` | 1 | `D5_factory_top` | factory control |
| `auto_sales` | 1 | `M2_out` | vending machine |
| `check_white_board` / `white_board_check` | 2 | `M5_labo_2F`, `M1_gym_1F` | whiteboard |
| `check_shrine` | 1 | `M3_shrine_1F` (0x87) | **the Relic Stone** |

`check_shrine` replaces the `current_floor_id == 0x87` Relic Stone relabel
in `phase1b_app.py` with the object's own record.

`check_snatchmachine` is the brief's "Snag Machine from the beginning of
the story", owned, positioned and gateable without a single typed-in
coordinate.

### 3.5 Readables — 11 records

`check_bookshelf` (×7), `serch_bookshelf` (×2), `chobin_book`,
`kaminco_book`, plus `key_101_dr_fad` / `key_101_dr_fad2`,
`check_kakureon`, `mana_secret_diary`-style story readables.

All method 3. These are landmarks with content, structurally identical to
the existing `sign` category.

### 3.6 Doors, elevators and gates the room script owns — ~15 records

`auto_door`, `auto_door_check`, `check_door`, `under_door`,
`apart_door_check` / `apart_door_open`, `labo_door_check` /
`labo_door_open`, `open_klein_door`, `check_klein_door`, `lock_door`,
`center_elevator_open`, `leftup_elevator_open`, `door_hoseb`.

These are doors and elevators that the `common.rel` door/elevator types do
**not** cover — the current door and elevator sources miss them entirely.
Note the paired `_check` (method 3) / `_open` (method 2) shape: the same
physical door has a press-A record and a walk-into record.

### 3.7 Mt. Battle — 109 records

`booth_battle_1` … `booth_battle_10` (99 records, method 1) and
`uketuke_warp` (10 records, method 2) across the ten `D2_*` zone rooms.
Method 1 means these fire on entry, not on A — they are hazards to *avoid*
stepping into as much as destinations, which is a genuine accessibility
distinction the navigator can now make.

### 3.8 Gateon Port — 5 records

`pier_trouble` (×2, method 2), `door_hoseb`, `ev_mechakyogre_check`,
`crabcrab_in_col` — all in `M6_out`. See
[GATEON_BRIDGE_ACCESSIBILITY.md](GATEON_BRIDGE_ACCESSIBILITY.md).

### 3.9 Hazards — 15 records

`hero_fall` (×8, `D6_fort_6F`), `fall_box` (×4) and `hot_not_approach`
(×3, `D6_fort_2F_1`). Method 1/2. A blind player has no way to see a hole;
`hero_fall` regions are arguably the highest-value entries in the whole
table and they are currently invisible to every system in this project.

### 3.10 Not in this table

**The Purify Chamber is absent.** No marker-0x0100 record in any room
resolves to a purify handler. Its entry point is therefore owned elsewhere
— most likely the `common.rel` PC type (0x0E) or an NPC talk script. That
is an open question, not a gap to fill by guessing;
[PC_AND_PURIFY_CHAMBER_RESEARCH.md](PC_AND_PURIFY_CHAMBER_RESEARCH.md)
holds what is already known and `purify_chamber.py` exists but feeds no
entity source.

---

## 4. The method byte

`+0x00` is consistent across **both** marker families and all 832 records:

| Method | Trigger | Examples |
|---|---|---|
| 1 | walk in, fires immediately | warp, cutscene warp, `booth_battle_*`, `hero_fall`, `crabcrab_in_col` |
| 2 | walk in, fires immediately | elevator, door, `uketuke_warp`, `auto_door`, `fall_box`, `*_open` |
| 3 | stand inside, **press A** | sign, PC, `watch_tv`, `check_bookshelf`, `esa_set`, every bed, `check_shrine`, `check_snatchmachine`, `*_check` |

That signs and PCs — the two already-parsed press-A types — both land on
method 3, and every already-parsed walk-in type lands on 1 or 2, is the
cross-check that makes this trustworthy rather than a pattern read into
the data.

Accessibility consequences:

- The navigator can say **"press A"** versus **"walk into it"** from game
  data, never from a per-object guess.
- Method 1/2 objects need no facing check and no talk cone — arriving *is*
  the interaction.
- Method 1/2 hazards (`hero_fall`, `booth_battle_*`) should be announced
  as things to avoid, and must never be routed *through*.

---

## 5. Proposed category design

The brief warns against category proliferation. Six categories cycle
today (`npc`, `item`, `interact`, `elevator`, `warp`, `sign`). This
proposal keeps six and folds everything above into them, grouping by what
the player does rather than by handler name:

| Category | Contains | Change |
|---|---|---|
| **NPCs** | live characters | unchanged |
| **Items** | pickups (boxes, loose, sparkly) | unchanged owner, corrected decode |
| **Interactables** | every method-3 object: televisions, beds, plates, machines, consoles, bookshelves, PCs, the Snag Machine, the Relic Stone, role NPCs | grows from 4 hardcoded cases to the whole method-3 set |
| **Exits** | warps, cutscene warps, doors, elevators, `uketuke_warp`, script-owned doors | **merges** today's `warp` + `elevator`, and absorbs §3.6 |
| **Signs** | readables — signs, bookshelves, whiteboards, diaries | grows |
| **Hazards** | `hero_fall`, `fall_box`, `hot_not_approach`, `booth_battle_*` | **new**, and the only addition |

Net: six categories before, six after. Elevators stop being their own
category (they are exits, and the player asks "how do I leave this floor",
not "where is an elevator specifically"); hazards take the freed slot
because nothing else in this project warns about a hole in the floor.

**Not proposed:** separate categories for televisions, beds, plates, the
Purify Chamber or the Snag Machine. Each is one or a handful of objects
per room; making the player cycle past four empty categories to reach the
one with something in it is a cost paid on every press.

Subtype survives in `Entity.subtype` and in the spoken label, so
"Television", "Bed", "PokéSpot plate", "Snag Machine" are all still
spoken — they simply are not separate *cycles*.

**This is a proposal, not a decision.** It needs the project owner's
agreement before Phase 4 builds to it, and the Hazards category in
particular is a judgement call about how a blind player wants to be told
about a fall they cannot see.

---

## 6. Labels

Per the brief, accessibility-owned generic **object-class** labels are
permitted; room lists and coordinates are not. The classification input is
the game's own handler name, so no label below is a transcription of
on-screen text:

| Handler family | Label |
|---|---|
| `watch_tv`, `watch_tv_l/r`, `watch_monitor_tv` | "Television" |
| `*bed*`, `recover`, `recovery_*` | "Bed" / "Healing machine" |
| `esa_set` | "PokéSpot plate" |
| `check_snatchmachine` | "Snag Machine" |
| `check_shrine` | "Relic Stone" |
| `tako_machine`, `crane_move_*`, `ev_factory_stop_1` | "Machine" / "Control console" |
| `auto_sales` | "Vending machine" |
| `*bookshelf*`, `*book`, `*white_board*` | "Bookshelf" / "Whiteboard" |
| `hero_fall`, `fall_box` | "Hole" |
| `booth_battle_*` | "Battle booth" |
| unmatched handler | **no entity published** |

The last row is the rule that keeps this honest: an unclassified handler
produces nothing rather than a generic "Interactable" at a place the
player cannot use. Silence over a confidently wrong target.

---

## 9. Activation state — UNRESOLVED, and what ships anyway

The Phase 4 brief requires an object to appear only when its interaction is
currently meaningful, and to be suppressed when activation cannot be
resolved. Activation **is** unresolved: most handlers open with a `getFlag`
guard whose flag would have to be read out of each function's own opcode
stream, and the CCD object-enable state that gates the regions themselves
is still the `StaticObjectEnableState` placeholder.

What ships is bounded by that honestly:

- **The record proves the dispatch.** A 0x0100 record means the engine runs
  that room handler when the player interacts at that region. That is a
  fact about the world, independent of what the handler then decides to do.
- **The risk is therefore an object that says nothing**, not an object in
  the wrong place — a materially smaller failure than a wrong position,
  which is what the "confidently wrong target" rule exists to prevent.
- **Walk-in records are suppressed unless they are a known hazard**, so no
  unclassified trigger is ever offered as a destination.

Two classes are held back *because* their activation matters:

- **Snag Machine** (`check_snatchmachine`, `M5_labo_1F`). Its direct calls
  are only `Array::get`, `Character::talk` and `getFlag` — it examines and
  speaks, gated on a flag. It is a story object whose availability changes,
  so it is left **unclassified** and publishes as a generic
  "Interactable" rather than being named before its guard is traced.
- **`crane_move_*`** (20 records). These handlers make **no direct
  standard-library calls at all** — they are dispatchers. Classifying them
  would require the transitive analysis that produced the
  `center_elevator_open` false positive, so they publish as generic
  press-A "Interactable" and are named nowhere.

## 7. What is still unknown

| Question | Status |
|---|---|
| Does a marker-0x0100 record's handler run on A, or is method 3 also used for something else? | method byte is consistent across 832 records; **not live-confirmed** |
| Is `+0x0A` really the runtime function index, or a file-order index that the loader remaps? | 241/241 resolve, but this is **static evidence only** |
| Which handlers are conditional (story-gated) and which always exist? | requires reading each handler's own `getFlag` guards — the same technique `esa_set` was read with |
| Where does the Purify Chamber's entry point live? | **open** |
| Do method-1/2 regions need enable-state (`GScolsys2`) before they can be trusted? | almost certainly yes for `M6_out`; see the bridge document |

None of these is guessed into a plan. Each is an offline experiment of the
same kind that produced §2.
