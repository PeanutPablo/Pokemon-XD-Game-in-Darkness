# Entity Navigation ("Item Navigation")

> **Superseded as an architecture record, 2026-08-06.** The authoritative
> ownership map is now
> [ENTITY_NAVIGATION_ARCHITECTURE.md](ENTITY_NAVIGATION_ARCHITECTURE.md),
> and the current defect list is
> [ENTITY_NAVIGATION_AUDIT.md](ENTITY_NAVIGATION_AUDIT.md). This document
> is retained as **build history** — an accurate record of how the feature
> was built and which hypotheses were abandoned along the way. It is no
> longer accurate about what the code does: the `WarpEntitySource` "warp
> table" category and the hand-curated `ELEVATORS`/`ITEMS`/`DOORS`
> per-floor dictionaries it describes have all been replaced.

## Status

Implemented and live-confirmed on 2026-07-26 for verified vanilla US XD, `GXXE01` revision 0. Pokémon XG compatibility remains unverified.

Read-only, hotkey-driven selection and description of nearby overworld entities: NPCs, items, and elevators. The feature never sends input, never touches the emulated controller, and never moves the player toward anything — it only selects and describes.

**Note on scope:** the original plan (see earlier drafts of this document / IMPLEMENTATION_ATTRIBUTION.md) was NPCs first, then a separately-verified treasure/item table as slice 2. That plan changed live, twice, based on what was actually found:

1. A generic in-memory table at `0x804E88F0`/`0x804E88F4` (labeled "treasures" by an unverified pre-existing diagnostic script, `probe_overworld_entities.py`) was investigated in detail (stride, count, field layout all reverse-engineered — see "Investigation notes" below for the record). Live testing across three different floors repeatedly found this table's positions coincide with elevators/floor-transition points, not pickup-able items. This was **not shipped** as a production category.
2. Codex's `npc_beacons.py` was found to already contain a more reliable, independently-verified mechanism: hand-curated, per-floor `ELEVATORS`/`ITEMS` lookup dictionaries (keyed by floor ID), injected into `NPCMemorySource.npcs()` as synthetic entries carrying their own `category`/`label` fields (e.g. floor `0x8A` → item "PDA" at a specific verified position). This is narrower (only covers floors Codex has manually mapped) but is actual verified ground truth, unlike the generic-table guess. **This is what shipped** for the item/elevator categories, by explicit instruction, reusing Codex's data rather than duplicating or second-guessing it.

Internally the feature is called `entity navigation`/`entity navigator` (see `battle_narrator/entity_nav.py`, `entities.py`, `entity_sources.py`); "item navigation" is the user-facing name.

## Hotkeys

Defaults (all foreground-scoped to `Dolphin.exe`, all require a modifier, same chord infrastructure as the existing HP-summary hotkey):

| Action | Default chord |
|---|---|
| Select next entity | `Control+Period` |
| Select previous entity | `Control+Comma` |
| Select next category | `Control+Shift+Period` |
| Select previous category | `Control+Shift+Comma` |
| Repeat current selection | `Control+Slash` |

Configurable at startup, e.g.:

```powershell
python Companion/run_battle_narrator.py --entity-next-hotkey alt+period
```

`hotkeys.py`'s `KEY_CODES` table was extended with `period`/`comma`/`slash` (`VK_OEM_PERIOD`/`COMMA`/`2`) to support this; the modifier-required chord-parsing logic itself was not changed.

## Context safety (full signature, not one flag)

The navigator only acts while `context_valid` is true, computed each poll from:

- **Window list is empty** (`window_manager` + `window_list_offset` head pointer reads `0`) — live-confirmed empty during ordinary free-roam, and non-empty during the party-switch menu, the Bag/party menu, and dialogue (all of which use the same window-node system as the rest of this project's menu/dialogue readers).
- **Dialogue is not active** (`dialogue_reader.active`, passed in from the lifecycle each poll) — explicit and redundant with the window check by design, for legibility.

Any transition from valid to invalid context, or a change in `current_floor_id`, clears category/selection state entirely (silently — no speech on the reset itself, only on the next deliberate hotkey press). This was live-confirmed for: opening/closing NPC dialogue, opening/closing an ordinary menu, and changing rooms.

**Known limitation, stated plainly:** loading screens and cutscenes that do not open a window and do not change `current_floor_id` are not independently detected. In practice this is bounded by the existing MemoryError-isolation convention already used throughout this codebase (a transient invalid read clears state rather than propagating), but it was not exhaustively live-tested against every possible transition.

An important correction made during live testing: the lifecycle's `GSMSG_WAITING`/`ACTIVE` states do **not** correspond to "not in battle"/"in battle" — `manager_root` (GSmsg) and `dialogue_manager_root` are the same address, so `ACTIVE` is the normal overworld steady state too. Entity nav is polled in both states (matching `poll_npc_sounds`'s placement exactly); battle/menu suppression is achieved entirely by the window-open/dialogue signals above, not by lifecycle-state gating.

## Selection model

- **Player pose**: reused directly from `npc_beacons.NPCMemorySource.player_pose()` — not recomputed. This is the same position/camera-yaw source already shipped for NPC proximity beacons.
- **Stable identity**: `(category, floor_id, npc_index)`, never a raw list index.
- **Ordering**: distance-sorted, **frozen at category activation** (or explicit category switch). Cycling filters this frozen identity order down to entities still live-present, without reordering — so walking a few steps never makes next/prev skip unpredictably. A full rebuild only happens on activation, category switch, or "everything in the frozen list vanished."
- **Categories**: only categories with at least one currently valid entity are offered; switching skips empty ones; if every category is empty, the navigator announces "No navigable entities nearby." once per press, never repeatedly during polling (polling itself never speaks — every utterance is the direct result of one hotkey press).

## Direction and distance (exact transform, as required)

**Design confirmed live, and clarified by explicit instruction (2026-07-26):** this game's camera does not rotate with the character. Live testing proved this directly: the hero model's own rotation changed by roughly 0.7 radians across an in-place character turn while the camera yaw read bit-identical before and after. This was briefly (mis)treated as a bug and "fixed" to use the model's own rotation instead — but that produced a direction reading that changes purely because the player turned in place, without moving. The project owner clarified this is **not** the wanted behavior: direction should be a fixed, compass-style reading anchored to the room's camera, with the player as the center of the "clock" — an entity's reported direction should depend only on its position relative to the player, never on which way the player happens to be facing. Concretely: if an entity reads "3 o'clock" while the player faces north, it should still read "3 o'clock" if the player turns to face east, west, or south without moving; only walking relative to the entity should change it (e.g., walking past it should eventually flip it toward the opposite clock position). This is exactly what the original camera-yaw basis (reused unmodified from `npc_beacons.NPCSoundReader.spatial_values`) already provides, since the camera itself does not rotate — the reversion restored the original implementation.

- `forward = (-sin(yaw), -cos(yaw))`, `right = (cos(yaw), -sin(yaw))` in the (x, z) plane, where `yaw` is the active camera's fixed yaw for the current room (radians) — not the hero model's own rotation and not world north.
- For an entity at `(dx, dz) = (entity.x − player.x, entity.z − player.z)`: `angle = degrees(atan2(dx·right + dz·rightz, dx·forward + dz·forwardz)) mod 360`. `0°` = 12 o'clock (straight ahead), `90°` = 3 o'clock, `180°` = 6 o'clock, `270°` = 9 o'clock. `clock = round(angle / 30) mod 12`, `0` displayed as `12`.
- Below `entity_nav_same_position_threshold` (1.5 game units, uncalibrated) horizontal distance, "same position" is spoken instead of an unstable clock direction.
- **Distance is the raw horizontal game-unit distance, rounded to the nearest integer — spoken as "distance N", deliberately not "meters".** No game-unit-to-real-world calibration has been verified anywhere in this project; a neutral scale was used rather than false precision.
- Vertical relationship ("above"/"below") is appended only when `|entity.y − player.y|` exceeds `entity_nav_vertical_threshold` (3.0 game units, uncalibrated) — an explicit, documented, but likewise uncalibrated threshold.

## Speech

Every utterance is interrupting (`SpeechEventClass.ENTITY_NAV`, new enum value, added to the coordinator's interrupt set) so rapid cycling never queues stale selections. Nothing is spoken from unchanged polling — only from a deliberate hotkey press.

Format: `"{Category}. [{Name}. ]{clock} o'clock, distance {N}[, above|below]. {In|Out of} interaction range."` (interaction-range clause included whenever the source provides an interaction distance, for both named and unnamed entities, a deliberate consistency choice). Unnamed NPCs (no verified name resolved) simply omit the name segment — no name is ever invented.

Category switch/activation speaks the category header and the closest entity as **one combined utterance** (not two sequential `emit()` calls), matching the existing multi-line-combined-utterance convention from `BATTLE_HP_SUMMARY.md` — two separate interrupting emits in the same tick would otherwise let the second cut off the first before it could be heard.

Repeat on a since-vanished selection clears it and speaks exactly `"Selected entity is no longer available."`; all-categories-empty speaks exactly `"No navigable entities nearby."`.

## NPC category

Reuses `NPCMemorySource` (npc_beacons.py) via a new adapter, `NPCEntitySource` (entity_sources.py) — no duplicated memory-reading logic. Filters to `npc.category == "npc"` (excluding the synthetic elevator/item entries described below) and `visible and talk_id` (matching the existing beacon system's own interactability filter), deduplicating by `(floor_id, index)` identity.

## Item and elevator categories

Both reuse the same reused source, `CategoryFilteredEntitySource` (entity_sources.py), parameterized by category (`"item"` or `"elevator"`). This filters `NPCMemorySource.npcs()` down to the synthetic entries Codex's `npc_beacons.py` injects from its own verified, hand-curated per-floor `ELEVATORS`/`ITEMS` dictionaries (keyed by floor ID, e.g. floor `0x8A` → item "PDA" at `(-30.0, 15.0, -104.0)`). Unlike the NPC category, the label is taken directly from `npc.label` (these entries carry their own verified name) rather than resolved from a name-ID string table.

**Coverage is intentionally narrow, not exhaustive**: only floors already present in Codex's `ELEVATORS`/`ITEMS` dictionaries produce item/elevator entities. A floor with a real elevator or item that hasn't been manually added there will show 0 available for that category — this is expected, not a bug, and matches "No navigable entities nearby." behavior correctly rather than fabricating a position.

**No live collected-state check.** These are static hardcoded positions, not tied to any in-game "has this been picked up" flag. Live testing confirmed an item's beacon (and therefore its entity-nav entry) keeps reporting as present even after the player has actually collected it in-game. This is a real, known limitation of the underlying data, not something entity navigation's own code can fix.

**`ITEMS` is currently empty.** Its one entry (floor `0x8A`, labeled "PDA") was found live to be incorrect and was removed at the project owner's explicit instruction, along with the test that asserted it (`test_pda_item_uses_verified_room_and_pickup_zone_center` in `test_npc_beacons.py`). The "item" category will report 0 available everywhere until a correct entry is added back to `npc_beacons.ITEMS`.

That same position (`Position(-30.0, 15.0, -104.0)`) was moved into `ELEVATORS` instead, at floor `0x8A`, per the project owner's follow-up instruction — it's apparently an elevator at that spot, not an item. `ELEVATORS` now has three entries (floors `0x8A`/`0x8C`/`0x8D`), all with `y=15.0`, consistent with the other two.

## Healing and door categories

Two more reused-mechanism categories, `"healing"` and `"door"`. `npc_beacons.py`'s `ENTITY_SOUND_FILES` had reserved sound files for both from early on, but no corresponding lookup dictionaries existed yet — `HEALING` and `DOORS` (both mirroring `ELEVATORS`/`ITEMS` exactly) were added from scratch. Wired into `NPCMemorySource.npcs()` and `CategoryFilteredEntitySource` identically to elevator/item — no new code path, just new data plus new category keys.

`HEALING`'s one entry (floor `0x8A`, a bed) needed a position correction the same day it was added: the first captured position (`-105.1, 0.0, 15.9`) was reported live as incorrect by the project owner after they'd walked away from the bed and noticed the reported distance didn't match reality. Corrected to `(-89.0, 0.0, -42.9)`, their position while standing at the actual bed.

`DOORS`' one entry (floor `0x8F`, position `(7.9, 0.0, -7.3)`) is a map-exit door the project owner was standing next to; captured live, not yet independently re-verified.

## Elevator cross-reference investigation (no reliable shared identifier found)

When a fourth elevator (floor `0x8B`) was encountered live, an attempt was made to find a shared marker/pattern across all `ELEVATORS` entries using the generic warp table (see "Warp category" below) as a cross-reference, to see if elevators could eventually be found generically instead of one at a time. Result, reported honestly rather than forcing a pattern: the warp table's `0x44` marker byte matched closely (4.6 game units) for floor `0x8D` but not for `0x8A` or `0x8C` (54-56 units away — too far to be the same object). An X=0 coordinate pattern held for `0x8B`/`0x8C`/`0x8D` but not `0x8A`. **No reliable universal identifier was found; elevators (and now doors) still need to be added one at a time as they're encountered.**

## Warp category *** UNVERIFIED / TENTATIVE ***

**Added back at explicit instruction after initially being set aside — treat every position from this category with the caveat below.** Reads a generic in-memory table (`WarpEntitySource`, `entity_sources.py`) at `warp_count_root`/`warp_data_root` (`0x804E88F0`/`0x804E88F4`), originally labeled "treasures" by a pre-existing, unverified diagnostic script (`Companion/probe_overworld_entities.py`). Kept as its own `"warp"` category, separate from `"elevator"` (which reuses Codex's independently-verified per-floor `ELEVATORS` lookup) since the two data sources have not been shown to agree or overlap.

Reverse-engineered structure:

- 116 active-looking records (count read via the same double-indirection pattern as the already-verified `people_info_count_root`/`people_info_root`), 28-byte (`0x1C`) stride.
- Per-record layout: `+0x00` a 4-byte marker (top byte `0x24` for most records, `0x44` for a few — a type discriminator whose exact meaning was never confirmed; both types were found to coincide with elevators in live testing, so it does NOT reliably mean item-vs-elevator), `+0x04` a sequential-looking ID, `+0x08` always zero in every sample seen, `+0x0C` a small varying integer of unknown meaning, `+0x10`/`+0x14`/`+0x18` an X/Y/Z position.
- Live testing walked to the nearest same-floor record on four separate occasions across three different floors (138, 140, 141) using this table's positions. **All four times, the position corresponded to an elevator/floor-transition point, not a pickup-able item.**
- No name is resolved (none identified), no interaction-distance field was identified either (interaction-range wording never appears for this category), and no collected-state field was ever identified for any record, since no genuine item was confirmed among the ones tested.

**Important correction on confidence, made explicitly by the project owner:** the 4 tested records were only ever selected by "nearest to the player" — a small, non-random sample of a 115+-entry table. This is real evidence that *some* entries are transition points, but it is **not** evidence that the whole table is exclusively transition points. The table may well be a **mixed** collection — some genuine items, some elevators/doors/other triggers — and the 4 samples tested so far simply happened to land on the transition-point kind. Do not read "Warp" entries as confidently non-item; the honest state is "type per entry unconfirmed, category label is a placeholder," not "confirmed non-treasure."

**Bug found and fixed the same day this shipped:** the table has no floor-ID field at all, and turned out to be a single global table for the whole game — live testing found "Warps. 115 available." (115 of 116 records) regardless of which floor the player was actually on, since nothing scoped the read to the current room. Fixed by bounding to `profile.warp_max_distance` (120.0 game units, the same default already used for NPC proximity beacons) as a practical stand-in for floor scoping, since no better signal was found.

## Live evidence (2026-07-26, floor 140/141, six valid NPCs)

- Activation: `"NPCs. 6 available. NPC. 3 o'clock, distance 35. Out of interaction range."`
- Named NPC resolved: `"NPC. Aidan. 12 o'clock, distance 80. Out of interaction range."`
- Forward cycling through all six distinct entities, then forward wraparound back to the exact first entity.
- Reverse cycling correctly wrapped from the first entity to the sixth (Aidan).
- Repeat while walking toward a selected NPC: distance dropped `110 → 74` with direction held steady, confirming live re-evaluation (not a frozen snapshot).
- Interaction range: `"NPC. 2 o'clock, distance 3. In interaction range."`, correctly distinct from the out-of-range wording.
- Dialogue open: hotkey press produced no speech (suppressed). Dialogue close: navigation resumed with a fresh category re-activation (dialogue is a context-invalidating event, not merely a stale-index situation).
- Ordinary menu (party/Bag) open: hotkey press produced no speech (suppressed, via the same window-open signal — not battle-specific). Menu close: navigation resumed.
- Room/map change: stale selection cleared (user-confirmed live).
- Facing-direction investigation: selected an NPC (`"NPCs. 7 available. NPC. 11 o'clock, distance 48. Out of interaction range."`), then turned the character in place without walking, then repeated: `"NPC. 6 o'clock, distance 43. Out of interaction range."` with the (since-reverted) model-rotation-based reader. This confirmed the camera genuinely does not rotate with the character, but the project owner clarified the direction-changes-on-turn-in-place behavior itself was undesirable — see "Direction and distance" above. Reverted to the original camera-based reading, which does not change on an in-place turn by design.

## Automated verification

28 new tests in `Companion/tests/test_entity_nav.py`, covering activation, closest-first ordering, next/previous, forward/reverse wraparound, direction math at all four cardinal clock positions plus a facing-rotation check, the "same position" threshold, distance/interaction-range wording, unnamed-NPC fallback, duplicate/invalid-NPC source-level filtering, stable identity across minor movement, map-change reset, disappearance handling, dialogue/window-open suppression, Dolphin-foreground enforcement (real `WindowsForegroundHotkey`, not a fake), interrupting-speech behavior, multi-category switching (a synthetic profile, since only `npc` ships this slice), and the corrected lifecycle-wiring expectation (polled in both `GSMSG_WAITING` and `ACTIVE`).

Additional tests cover the item/elevator category filtering and label passthrough (`CategoryFilteredEntitySourceTests`), the exclusion of synthetic elevator/item entries from the NPC category, and the warp table's double-indirected count/stride/empty-slot/distance-bound handling (`WarpEntitySourceTests`, including a regression test for the "115 available" global-table bug).

Full suite: **235 passing** at time of writing (includes concurrent Codex work in the same session; re-verified after each shared-file change; one prior Codex test asserting the now-removed incorrect PDA entry was removed alongside it).

## Door removed from the cycle (2026-08-05)

`"door"` is no longer one of the categories the entity-nav hotkeys page
through, at the project owner's request. It is gone from
`profile.entity_nav_category_keys` and both label tuples (all three are
positional and must stay index-aligned — dropping an entry from one alone
would silently relabel every category after it), and from the `sources`
dict in `phase1b_app.py`.

Doors are **not** gone as a concept: `door_source` is still built from the
authoritative interaction table and still feeds the passive door beacon
(`sounds/doors.wav`). The change is only to what the cycle offers.

Narrowed 2026-08-10: a door sharing its collision region with a warp — a
building entrance, which in this game's data is both records at once — is
published with `metadata["beacon"] = False` and makes no sound, because
the warp on the same region already does. 72 of 150 doors are attached
that way; the other 78 beacon as before. See NPC_PROXIMITY_SOUNDS.md.

## Scope exclusions

No healing, store, or Pokémon-box category yet. No automated movement or pathfinding — out of scope for this feature entirely, by explicit instruction. Item/elevator coverage is limited to whatever floors Codex's `ELEVATORS`/`ITEMS` dictionaries in `npc_beacons.py` already list (see above) — extending coverage means adding to those dictionaries, not changing anything in this feature's own code. Warp coverage is generic (any floor with active records in the table) but unverified as to whether it actually represents warps, elevators, or something else — see the caveat above.

## Attribution

NPC category implemented by **Claude (Sonnet 5)** on 2026-07-26 at the project owner's request, following a detailed specification. Item/elevator categories implemented the same day, reusing Codex's (OpenAI) verified `ELEVATORS`/`ITEMS` per-floor data in `npc_beacons.py` directly, not duplicating or re-deriving it. Warp category (tentative/unverified) implemented the same day at explicit instruction, from Claude's own independent investigation of the generic table. Also built on top of Codex's NPC/player-pose infrastructure (`npc_beacons.py`) — reused, not modified.
