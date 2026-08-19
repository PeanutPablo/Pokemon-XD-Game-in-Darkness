# ACCESSIBILITY_COVERAGE_MATRIX.md

**Status:** Living document. Created 2026-07-29, seeded from verified repository state (code in `Companion/battle_narrator/`, tests in `Companion/tests/`, and dated entries in `IMPLEMENTATION_ATTRIBUTION.md`) — not from `INDEX.md`/`UNKNOWNS_AND_BLOCKERS.md`, both of which are stale (dated 2026-07-25, predating almost everything below; see [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md)'s risks section).

This is the authoritative inventory of known game states, screens, mechanics, and their accessibility coverage. It is **not**, and is not intended to be, a complete inventory of the whole game — new sections and rows are added as they're discovered through play, per [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md)'s discovery-driven cycle. A long list of "Unknown" rows is expected and correct, not a gap to rush to close.

**Accessibility status values:** Unknown · Discovered · Investigating · Blocked by story progression · Partially accessible · Implemented · Live-tested · Regression-tested · Blocked technically · Deferred. These are not strictly sequential — "Implemented," "Live-tested," and "Regression-tested" are each recorded explicitly per the three-part completion rule; a row can be "Implemented" without yet being "Live-tested."

**Discovery/reachability status values (refined 2026-07-29 — "story-locked" is no longer used as a catch-all):** Unknown (reachability not established from any available record) · Known but not yet reached · Previously reached but no reusable save exists · Currently reachable (available now, repeatable/durable access — e.g. shops, PC) · Reached and awaiting accessibility audit (confirmed present in the current live save, not yet investigated) · Blocked by story progression (confirmed to require further story advancement not yet completed) · Blocked technically. Reachability is only asserted here when it can be verified from repository state, prior session records, or the project owner's own direct report — never guessed. Where none of those establish it, the entry says so explicitly and stays unresolved until reported.

Severity levels (see [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md) for full definitions): **0** hard blocker · **1** possible but unreasonable · **2** incomplete but usable · **3** polish.

---

## Field exploration

### Player position/camera reading (foundation)
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: Implemented, Live-tested, Regression-tested
- Current limitation: none known; this is the foundation every entity-nav/beacon/teleport feature builds on
- Severity: N/A (foundation, not a player-facing gap)
- Story requirement: none
- Reproduction steps: N/A
- Relevant save/save-state: none needed
- Technical findings: `NPCMemorySource.player_pose()`/`hero_model_address()` in `npc_beacons.py`
- Implementation status: Implemented
- Live-test status: Live-tested (used continuously throughout this project)
- Regression-test status: Regression-tested
- Last verified date: 2026-07-29 (in active use)
- Remaining work: none
- Notes: camera-anchored, not character-facing-anchored, per explicit project-owner instruction

### NPC proximity sound beacons
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested. **Pitch-shift quality reworked 2026-07-30, not yet perceptually validated** — see Notes.
- Current limitation: coverage/quality of individual beacon sounds is subjective and may need future tuning
- Severity: 3
- Story requirement: none
- Reproduction steps: walk near any NPC
- Relevant save/save-state: none needed
- Technical findings: `npc_beacons.py`, `NPC_PROXIMITY_SOUNDS.md`. **2026-07-30:** `SpatialWavePlayer._pitch_shift_constant_duration` (shared by this feature, `terrain_footsteps.py`'s step/blocked tones, and `audio_guide.py`'s guide tone) replaced its FFT bin-interpolation approach with time-domain WSOLA (`_pitch_shift_wsola`: linear resample for the real pitch change, then cross-correlation-matched overlap-add to restore the original duration) — the old method interpolated the real/imaginary parts of the spectrum independently, which does not preserve phase relationships between frequency bins and was the likely source of a "low quality... when changing pitch" complaint. WSOLA was chosen over a phase vocoder because every sound this renders is a short (0.05–0.3s) tonal/percussive clip, exactly the material WSOLA suits best, for much less implementation risk than STFT phase unwrapping. The old FFT method is kept as a guarded fallback (`_pitch_shift_fft_fallback`) for inputs too short for even one WSOLA analysis frame, and both paths reject non-finite/empty output rather than ever returning corrupted audio. `numpy` (already an undeclared real dependency of the pre-existing pitch-shift code) was added to `requirements.txt`.
- Implementation status: Implemented. **2026-08-10, both by project-owner request:** elevators gained their own beacon (`sounds/elevators.wav`, added to `PASSIVE_BEACON_SOUND_FILES` and wired into `npc_sound_factory`'s source chain — all 46 elevator records in the game resolve), and doors that share a collision region with a warp stopped beaconing. The latter is a doubled-cue fix: in this game's data a building entrance is both a Door record and a Warp record on the same region, so both played from the identical point; 72 of 150 doors are attached this way, the other 78 still beacon. Implemented as `metadata["beacon"] = False` in `AuthoritativeDoorEntitySource` (which now takes the warp records), not as a drop — beacon eligibility is not navigation eligibility, per `WarpAugmentedNPCSource`'s existing contract.
- Live-test status: Live-tested (the beacon feature itself, 2026-07-28). **The WSOLA pitch-shift rework itself is NOT yet live-tested** — automated tests can confirm length/finiteness/frequency-ratio correctness (and do: a pure-tone test verifies the dominant frequency shifts by the requested ratio) but cannot judge perceptual quality; a live listening comparison against the old method is still pending.
- Regression-test status: Regression-tested (`test_npc_beacons.py`, `test_npc_interactions.py`, `test_npc_sounds.py`; new `PitchShiftTests` class: length preservation, frequency-ratio correctness via a fresh FFT check, unity-pitch short-circuit, short-clip fallback, silence-in/silence-out, no NaN/Inf across a range of pitches and lengths)
- Last verified date: 2026-07-28 (beacon feature); 2026-07-30 (pitch-shift rework, regression-tested only)
- Remaining work: live-listen to old vs. new pitch-shift quality and confirm it actually sounds better, not just numerically correct
- Notes: the beacons were muted for a period at the project owner's request ("turn the sounds off") back when every category shared one loud tone; **that is no longer true** — they were re-enabled on 2026-08-05 once each category got its own sound from `sounds/` (see NPC_PROXIMITY_SOUNDS.md). The pitch-shift rework benefits this feature, `terrain_footsteps.py`, and `audio_guide.py` uniformly, since all three share `SpatialWavePlayer`.

### Entity navigation (NPC/door/elevator/warp/healing/item/pc/sign categories)
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested for all except `sign` (implemented 2026-07-29, not yet live-tested)
- Current limitation: `sign` category's message content isn't spoken yet (position/presence only); healing-spot coverage remains a single old hand-scanned entry, not comprehensive
- Severity: 2
- Story requirement: none
- Reproduction steps: activate entity-nav, cycle categories
- Relevant save/save-state: none needed
- Technical findings: `entity_nav.py`, `entity_sources.py`, `authoritative_warps.py`, `treasure_entities.py`, `npc_beacons.py`; full-game 177-room `.ccd` extraction done; all six known `common.rel` interaction types (Warp/Door/Elevator/CutsceneWarp/PC/Text) now have a category. **NPC presence bug fixed 2026-07-29**: `NPCMemorySource` previously trusted only `floor_character`'s static "visible" bit, which does not track story state and could report a story-hidden/absent named character (e.g. a kidnapped NPC) as present and in interaction range. Now cross-references the live `people` runtime-actor table's own model-visibility bit, which is confirmed to track true presence — see [PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md) entry 9 for the full technical writeup.
- Implementation status: Implemented
- Live-test status: Live-tested for npc/door/elevator/warp/healing (15-step protocol) plus item and pc (both confirmed 2026-07-29 via real in-game checks); NPC presence fix live-reverified 2026-07-29 against the running game with the production code path
- Regression-test status: Regression-tested (`test_entity_nav.py`, `test_authoritative_warps.py`, `test_treasure_entities.py`, `test_npc_beacons.py::NPCMemorySourceTests`)
- Last verified date: 2026-07-29
- Remaining work: live-confirm `sign`; investigate resolving sign message content; comprehensive healing-spot coverage remains open (see dedicated entry below)
- Notes: elevator/door categories fully replaced hand-scanned data this session with authoritative CCD-derived positions

**Entity-navigation audit, Phase 1 + Phase 2 (2026-08-06) — supersedes the status above for the NPC category.**

- **Phase 1 (audit only, no code changed).** See [ENTITY_NAVIGATION_ARCHITECTURE.md](ENTITY_NAVIGATION_ARCHITECTURE.md) and [ENTITY_NAVIGATION_AUDIT.md](ENTITY_NAVIGATION_AUDIT.md). Found: the "three Agate clerks" report is a role predicate keyed on the FLOOR ID; NPC interaction points and range use the wrong body reference, the wrong distance metric and the wrong threshold, with four of the game's ten talk gates unimplemented; warp/door/elevator/PC/sign positions are region CENTROIDS, and across all 843 regions in 177 rooms **842** are large enough that a player standing legitimately inside can be more than a full interaction radius from the announced point; the item source reads the treasure kind from the wrong bits; opened-state is inferred from a condition that has fired **zero times in 367 MB of logs**.
- **Phase 2 (NPC category rebuilt).** Accessibility status: **Regression-tested, NOT yet live-tested.** The NPC source is now driven by the live `tagPeopleWork` pool (`people_runtime.py`), keyed on the engine's own `(groupID, resID)`, positioned from the live model, gated by a full `peopleTalkCheck` reproduction (`talk_predicate.py`), and labelled from the NPC's own talk script id against a table derived from the game's room scripts (`npc_roles.py`). Unnamed NPCs speak as "A", not "NPC A". A development-only interaction diagnostic (`--interaction-diagnostics`) scores predictions against real A presses — see [INTERACTION_DIAGNOSTIC.md](INTERACTION_DIAGNOSTIC.md).
- Live-test status for the NPC category: **pending.** Requires a narrator restart; nothing in Phase 2 has been confirmed against the running game.
- Still open after Phase 2: CCD-region centroid positions (Phase 3b), items/containers/opened state (Phase 3), generic interactables (Phase 4), Gateon bridges (Phase 5).

**Re-audit Pass 2 (2026-08-09) — corrects the Phase 2 status above.**

- **Phase 2 is not in production.** `phase1b_app.build_overworld_sources` was reverted to the pre-Phase-2 `NPCEntitySource` on 2026-08-06 and has not been restored. Accessibility status for the NPC category is therefore **as it was before Phase 2**: room-id role labelling (three Agate clerks), "NPC A" wording, static spawn positions when no live actor is found, and the old horizontal range rule. `LiveNPCEntitySource` is imported and never constructed.
- **Interaction range is measurably broken.** 2026-08-06 → 2026-08-09 production log: 2396 "Out of interaction range" against **4** "Interaction available", all four Items. No NPC was reported interactable in three days, including at 10-11 units from a Mart clerk.
- **The interaction diagnostic has never run.** `--interaction-diagnostics` is not in the launcher; the log contains zero diagnostic lines. Every Phase 2 unverified input remains unverified.
- **New, offline:** the room-script interaction system is identified and verified (241/241 records resolve to named handlers in their owning room script) — see [INTERACTABLE_OBJECTS.md](INTERACTABLE_OBJECTS.md). The treasure record is fully resolved including separate collected (`+0x06`) and spawn (`+0x08`) flags. The hardcoded "Healing station" at room 0x8A is `M5_apart_1F`'s `check_mana_bed` — a **bed**, mislabelled.
- Suite: **1115 passing**, unchanged by this pass.

### Room-script interactable objects and hazards (Phase 4)
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: **Implemented, Regression-tested, NOT yet live-tested** (2026-08-09)
- Technical findings: the 241 marker-`0x0100` `common.rel` records resolve to named handlers in their owning room script (241/241). `interactable_roles.py` classifies each handler from its **own direct** standard-library calls; `build_interactable_table.py` generates `assets/interactables.json`. Traced classes: television 17, healing machine 10, hole 8, bed 5, PokeSpot plate 3, vending machine 1, Relic Stone 1; the remaining 196 press-A records publish as a generic "Interactable" and unclassified walk-in records are suppressed. **`tako_machine` is a healing machine**, traced not guessed. Positions use `region_geometry.Region.nearest_point`, never the centroid.
- Current limitation: **activation state is unresolved** — see INTERACTABLE_OBJECTS.md §9. Snag Machine and the crane consoles are deliberately left generic pending guard tracing.
- Regression-test status: Regression-tested (`test_interactables.py`, 48 tests, 12 against the real generated asset)
- Remaining work: activation guards; adopting `region_geometry` in the warp/door/elevator/PC/sign sources (Phase 3b); associated menus (Phase 6)

### Hazards (fall regions)
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: **Implemented, Regression-tested, NOT yet live-tested** (2026-08-09)
- Technical findings: eight `hero_fall` regions in `D6_fort_6F`, classified by `Character::76` + `UnknownClass38::42`. Own `hazard` cycling category; never beacons, never carries interaction wording, never offered as a destination.
- Current limitation: only proven falls are classified. `fall_box` and `hot_not_approach` are hazard candidates with no shared marker and are suppressed. No automatic proximity warning — entity-nav cycling only, by design for this phase.
- Severity: this is the first warning of any kind for holes a blind player cannot perceive

### Item/treasure entity-nav category (ground pickups)

**Phase 3 rebuild, 2026-08-09 — Implemented, Regression-tested, NOT yet
live-tested.** `treasure_entities.py` was rewritten against the traced
state machine (`_floorInitTresure` 0x8011F838, `floorEventCtrlTresure`
0x80121934). Kind is `(byte >> 5) & 7` and placeable kinds are 1/2/3;
**kind 1 is an item box** (keeps its actor and changes pose when taken),
**kinds 2/3 are loose pickups** (hidden when taken). Collected and spawned
are separate general flags at `+0x06` and `+0x08`, so both are answerable
without a live actor and a scripted spawn or collection appears with no
room reload. Labels are "Item box" / "Opened item box" / "Item"; the
contained item id is read and carried in metadata but deliberately not
spoken, since the game does not reveal it before pickup. Beacon
eligibility is now separate from navigation eligibility, so an opened box
stays as a landmark and goes silent. `POKESPOT_ROOMS` and its `kind == 4`
branch are deleted. 37 regressions in `test_treasure_entities.py`; suite
1226. **Live validation pending** — no box has been opened or item
collected with this build running.

- Primary workstream: Navigation and spatial awareness
- Discovery status: Currently reachable (applies game-wide, no story gate)
- Accessibility status: Live-tested, Regression-tested
- Current limitation: the `item` entity-nav category was an empty stub before this pass (`ITEMS = {}`, hand-curated and never populated). An earlier session (2026-07-27) investigated a candidate live table and rejected it after four live tests all resolved to elevators instead of items — this pass found that rejection was about reading the *right* table with the *wrong* field offsets, not the wrong table.
- Severity: 1-2 (a sighted player can simply see and walk up to ground items; no equivalent existed for a blind player at all until this pass)
- Story requirement: none
- Reproduction steps: activate entity-nav, switch to the `item` category
- Relevant save/save-state: none captured
- Technical findings: same live runtime interaction-record array already used for warps/doors/elevators (count at `0x804E88F0`, base pointer at `0x804E88F4`, `0x1C`-byte stride) but read through the game's own runtime field layout (confirmed via static disassembly of `_floorInitTresure`, the room-load-time treasure initializer) rather than the on-disk `common.rel` layout the other categories use — the two differ (e.g. room ID lives at a different offset in each), which is exactly why the earlier attempt found the wrong objects. Runtime layout: `+0x00` byte's low 3 bits = "kind" (only 1/2/4 are treated as placeable pickups by `_floorInitTresure`), `+0x04` = room ID, `+0x10`/`+0x14`/`+0x18` = X/Y/Z position.
- Implementation status: Implemented (`treasure_entities.LiveTreasureEntitySource`, wired into `entity_nav_factory`'s `"item"` source, replacing the empty `CategoryFilteredEntitySource` stub)
- Live-test status: **Live-tested (2026-07-29)** — confirmed via the narrator's own log: items detected correctly across multiple different rooms, distance tracked accurately and monotonically as the project owner walked toward one (84→72→82→72→19→13→8 units), correctly flipping to "In interaction range" on arrival.
- Regression-test status: Regression-tested (`test_treasure_entities.py`, 7 tests; 399 total passing)
- Last verified date: 2026-07-29
- Remaining work: kind=4 confirmed "Item Box" directly by the project owner (2026-07-29) — now labeled accordingly. Kinds 1/2 remain unconfirmed; a cross-check against the one already-known healing-spot position found no matching record in that room at all, ruling out "kind 1/2 = healing" for that sample (see the new Healing-spot-source-investigation entry below).
- Notes: this also plausibly resolves the earlier-deferred "Room or area treasure" gap in one step, since it required no new offline extraction — pure live read, same pattern already proven safe throughout this project

### PC entity-nav category
- Primary workstream: Navigation and spatial awareness
- Discovery status: Currently reachable (applies game-wide, no story gate)
- Accessibility status: Live-tested, Regression-tested
- Current limitation: uses the interaction-table type `0xE` ("PC"), the same proven mechanism as Door/Elevator/Warp — but `Pokemon-XD-Code` documents this specific type's own parameters as "unused in XD" (as opposed to Colosseum), so reliability of anything beyond position remains a caveat even though the position itself is now confirmed.
- Severity: 1-2
- Story requirement: none
- Reproduction steps: activate entity-nav, switch to the `pc` category
- Relevant save/save-state: none captured
- Technical findings: `authoritative_warps.PCRecord`/`parse_pc_records`/`AuthoritativePCEntitySource`, same on-disk `common.rel` interaction table and CCD-centroid resolution as Door/Elevator/Warp
- Implementation status: Implemented
- Live-test status: **Live-tested (2026-07-29)** — the project owner confirmed the reported PC location was a real, correct PC.
- Regression-test status: Regression-tested (`PCRecordTests`, `AuthoritativePCEntitySourceTests` in `test_authoritative_warps.py`; 407 total passing)
- Last verified date: 2026-07-29
- Remaining work: none currently open
- Notes: requested alongside healing-spot coverage by the project owner as part of the "grab every entity/treasure" priority

### Sign/text entity-nav category
- Primary workstream: Navigation and spatial awareness
- Discovery status: Currently reachable (applies game-wide, no story gate)
- Accessibility status: Implemented — **not yet live-tested**
- Current limitation: same interaction-table pattern as Door/Elevator/PC (type `0xC`, ~89 records game-wide), announced generically as "Sign" — the record's own secondary field (`message_field`) is a candidate message/string ID but is not yet confirmed to resolve through any specific string table, so sign *contents* are not spoken, only presence/position.
- Severity: 2-3 (signs are informational, not usually blocking, but still something a sighted player notices)
- Story requirement: none
- Reproduction steps: activate entity-nav, switch to the `sign` category
- Relevant save/save-state: none captured
- Technical findings: `authoritative_warps.TextRecord`/`parse_text_records`/`AuthoritativeTextEntitySource`
- Implementation status: Implemented
- Live-test status: **Not yet live-tested**
- Regression-test status: Regression-tested (`TextRecordTests`, `AuthoritativeTextEntitySourceTests` in `test_authoritative_warps.py`; 407 total passing)
- Last verified date: 2026-07-29 (implementation + tests only)
- Remaining work: live-confirm position accuracy against a real sign; investigate whether `message_field` resolves through the same general string table (`common.rel` REL pointer 136) already used for move/ability/speaker names, to eventually speak sign contents
- Notes: last of the six known `common.rel` interaction types to be wired into entity-nav (Warp/Door/Elevator/CutsceneWarp/PC/Text all now covered)

### Healing-spot source investigation (partially resolved — mechanism for PC-based healing found and confirmed already narrated)
- Primary workstream: Navigation and spatial awareness
- Discovery status: Currently reachable (healing spots exist game-wide; one entry already hand-scanned in `npc_beacons.HEALING`; a second, mechanism-confirmed sample now exists at room `0x8C`)
- Accessibility status: **Partially resolved.** The dialogue exchange that actually performs and confirms healing is already narrated with zero code changes needed. Discovering healing-machine PCs in advance (an entity-nav "this PC heals" label) is still open.
- Current limitation: the existing `HEALING` dict has exactly one hand-scanned entry (floor `0x8A`) — nowhere near comprehensive. The project owner asked to also track healing stations properly; a live cross-check this session found that entry's position does **not** match any record in the same live treasure/kind table used for items (nearest record was 33+ units away, clearly a different object), ruling out "healing uses the same kind-1/2 mechanism as items" for that sample.
- Severity: 1-2
- Story requirement: none
- Reproduction steps: Walk up to the PC in room `0x8C` (`M5_labo_1F`) and interact with it; the healing prompt and result are spoken automatically.
- Relevant save/save-state: none captured
- Technical findings: healing spots are confirmed **not** part of the `_floorInitTresure`-driven kind={1,2,4} table (at least not in room `0x8A`). Second live cross-check (2026-07-29, room `0x8C`, after the project owner healed at the PC they had just confirmed): a proximity scan against every other known table in that room (treasure/item, doors, warps, elevator, signs, floor_character NPCs) found nothing genuinely beside the PC, ruling out all six known interaction-table types and the treasure/kind table as a *separate* healing object in that room.
  **Follow-up live capture (same day, later pass):** the project owner healed again while a purpose-built monitor (party HP, active window/menu IDs, player position, 10 samples/sec) watched live memory, and simultaneously the narrator's own log was cross-referenced. The narrator's `DIALOGUE` speech class (`dialogue.py`, already wired unconditionally into the lifecycle poll loop — the same reader that narrates ordinary NPC conversations) already spoke both halves of the exchange in real time: `"There is a POKéMON HEALING MACHINE. Want to use it?"` at 19:52:08.597, then `"All the party POKéMON were healed to full health."` at 19:52:10.295. These timestamps line up exactly with the live window-ID transitions the monitor captured: menu `82` (`dialogue_window_id`) alone → `82`+`53` (`new_game_confirmation_menu_id`, the same generic Yes/No overlay type used elsewhere) layered on top while the Yes/No prompt was up → back to `82` alone for the result line → closed. This is the exact same PC interaction record already tracked by `AuthoritativePCEntitySource` for this room (`secondary_field=0`), not a separate object — the "healing machine" is this PC's own dialogue-driven interaction, not a distinct physical entity standing beside it.
  Checked whether `secondary_field=0` reliably flags a PC as a healing machine: 8 of the 26 PC records game-wide share that exact value across scattered rooms (`0x07`, `0x33`, `0x4C`, `0x4F`, `0x49`, `0x59`, `0x8C`, `0x9A`), which is at least consistent with a shared "no special configuration" default, but there is no second confirmed healing PC to cross-check against yet, and `Pokemon-XD-Code`'s own documentation already flags this field as unused in XD for gameplay — so this is **not** being treated as a confirmed signal, only a lead. Also confirmed the original `0x8A` hand-scanned healing entry has **no PC record in that room at all** — so whatever mechanism triggers healing there is still genuinely different from this room's PC-based one; today's finding does not explain it.
- Implementation status: No code change needed for the core accessibility gap (narration already works via the existing generic dialogue pipeline). Not implemented: any entity-nav-level "this is a healing PC" label for advance discovery.
- Remaining work: (1) get a second confirmed healing-PC sample (ideally including the still-unexplained `0x8A` case) to test the `secondary_field=0` lead before ever encoding it as a rule; (2) decide whether advance discovery of healing PCs (vs. discovering them by walking up and hearing the dialogue, which already works) is worth pursuing given the low severity.
- Notes: resolved the core "is this silent" question — it isn't, this was already accessible. The narrower "find it in advance" and "explain the different `0x8A` mechanism" threads remain open and are not being guessed at.

**2026-07-30 follow-up — Agate Village Pokémon Center (`M3_pc_1F`, room 0x85), a second, architecturally different healing mechanism, static-only so far:** the project owner asked to investigate the Pokémon Center the same way as the shop (see "Shops" above). Extracted `M3_pc_1F.fsys` directly off disc (same `DolphinTool.exe extract -s` technique) and disassembled its script the same way. Found the receptionist's own talk function, `talk_124_pc_f` (character `pc_f` — the room's own asset bundle also contains a `pc_f_0000` model, same confirmation pattern as the shop's `shop_m_0000`): `Character::talk(50401, mode=8)` ("Would you like me to heal your Pokémon?"), then on yes `Character::talk(50402)` + `Character::101` (the heal effect) + a `Player::countPartyPkm()==1` special case, then `Character::displayMsgWithSpeciesSound(50403/50404/50407)` for the result message (paired with a Pokémon cry sound).

Unlike the shop, this is **architecturally identical to the already-confirmed room-0x8C PC-based healing above**: `Character::talk` is ordinary field dialogue (dialogue_type=3), and the yes/no at step 1 is the exact same "dialogue-triggered Yes/No, parent = `dialogue_window_id`" shape already found, fixed, and tested for room 0x8C (`test_dialogue_triggered_yes_no_uses_active_local_prompt`, `test_phase1e_menus.py`). This is a *different room, different NPC-based trigger* (a receptionist character, not a PC terminal object) reaching the same conclusion independently: **no new code should be needed** for the Agate Village Pokémon Center either. Could not locate the exact text for messages 50401-50409 in any already-extracted `.fsys` (checked `common.fsys`, `fight_common.fsys`, `pocket_menu.fsys`, `battle_disk.fsys`, `pokemonchange_menu.fsys`, and the room's own local table) — left unresolved since it's not actually needed: `dialogue.py` reads whatever's rendered directly, not by message-ID lookup.

- Implementation status (Agate Village PC): No code change made or expected to be needed, same reasoning as the room-0x8C case — pending live confirmation, not yet tested live this pass.
- Remaining work (Agate Village PC): live-verify by healing there and confirming the exchange narrates correctly with zero code changes, the same way room 0x8C's case was confirmed with a live monitor + log cross-reference.

### Entity-nav refresh hotkey — **REMOVED 2026-08-16**
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: **Removed.** The action and its hotkey are gone from `entity_nav.py`, `profile.py` and `phase1b_app.py`.
- Current limitation: n/a
- Severity: 3
- Story requirement: none
- Technical findings: held `ctrl+shift+slash`. **It had never once run in production.** `WindowsForegroundHotkey._pressed` tested only that every key in its chord was down, so `ctrl+slash` (repeat) matched every `ctrl+shift+slash` press too, and `poll_once` checked repeat first in the same `elif` chain. Found 2026-08-16 while re-binding autowalk onto that chord; the underlying chord-matching defect was fixed the same day (a chord now requires the modifiers it does NOT name to be up — `ExactChordTests` in `test_cli_defaults.py`).
- Implementation status: Removed at the project owner's request, in preference to rehoming it, once told what it had been for.
- Live-test status: N/A — and note the earlier "Live-tested" claim on this row was never true of the feature itself; the entity-nav validation it leaned on never exercised this hotkey.
- Regression-test status: `RefreshTests` replaced by `RefreshRemovalTests` (`test_entity_nav.py`), which asserts the action is gone, that only the five remaining hotkeys are polled, and that what replaces it works: re-activating a category picks up an entity that appeared after activation.
- Last verified date: 2026-08-16
- Remaining work: none
- Notes: its purpose — reaching entities that appeared after a category was activated, which next/prev cannot, since they cycle the order frozen at activation — is still served by switching category away and back, because `_activate_category` re-reads the live list every time.

### Overworld NPC dialogue (scripted + free-roam) and speaker names
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Current limitation: none currently open (two real bugs found and fixed this session — see [PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md) #1, #2)
- Severity: was 0 while broken; now resolved
- Story requirement: none
- Technical findings: `dialogue.py`, `entity_names.py`'s `ScriptedSpeakerNameTable`; savedata-based player-name chain; `msgctrlSetValue(89,...)` speaker-name global
- Implementation status: Implemented
- Live-test status: Live-tested
- Regression-test status: Regression-tested (`test_dialogue.py`, `test_entity_names.py`)
- Last verified date: 2026-07-28
- Remaining work: none currently open
- Notes: `OVERWORLD_NPC_DIALOGUE_VERTICAL_SLICE.md` has the original architecture; superseded fixes are in `IMPLEMENTATION_ATTRIBUTION.md`'s 2026-07-28 entries

### Teleport to entity-nav selection
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: Partially accessible
- Current limitation: warp/door/elevator/healing-category teleports confirmed working live; NPC-category approach-position fix has **not** been live-confirmed since it was applied
- Severity: 1 (independence feature, not a blocker — entity-nav+beacons remain the fallback)
- Story requirement: none
- Reproduction steps: select an NPC in entity-nav, press `ctrl+t`
- Relevant save/save-state: none captured
- Technical findings: `teleport.py`, `MemoryReader.write_bytes` (the project's only write path)
- Implementation status: Implemented
- Live-test status: Partially live-tested (warp confirmed; NPC-category fix unconfirmed — this is open task #61 in the working session's task list)
- Regression-test status: Regression-tested (`test_teleport.py`, `test_memory.py`)
- Last verified date: 2026-07-27 (warp only)
- Remaining work: live-confirm the NPC-category approach-position fix
- Notes: the project's first and only memory write; explicitly entity-nav-restricted, never free-form coordinates

### Audio guide (hot/cold tone toward selection)
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: **Regression-tested (2026-07-30, walkability model pivoted same day after a live reproduction); intra-room obstacle-aware routing implemented but NOT YET live-tested since the pivot** — do not consider the routing behavior confirmed until the project owner walks through the live-validation scenarios below
- Current limitation: no automatic multi-room routing, unchanged by design — doors/warps are themselves selectable categories, so cross-room guidance composes manually.
- Severity: 2 (unchanged from the original straight-line guide; the new routing is additive, gracefully degrading to the prior behavior when unreachable)
- Story requirement: none
- Technical findings: `audio_guide.py`'s `AudioGuideReader` is now a thin consumer of a new, reusable `navigation_service.NavigationService`, itself built on a new `pathfinding.py` (destination-origin flow field over walkable tiles, uniform-cost/Dijkstra-shaped search for future weighted-cost readiness, 8-directional with corner-cut prevention, height-continuity tolerance for stacked floors). Several real bugs were found and fixed via live measurement against actual `.ccd` data before this shipped: (1) floor classification originally used `abs(normal[1]) >= threshold` (matching `terrain_footsteps.find_ground_triangle`'s own convention), which admits downward-facing ceiling/underside triangles as "floor" — fixed to require an upward-facing normal specifically; (2) real floor triangles (~1.5 units) are far smaller than the pathfinding tile size (8 units), so a strict point-in-triangle test against a tile's center point routinely missed real coverage. **Architecture pivot (same day, after the first ship-as-is attempt failed live):** the project owner tried the routing feature and reported "no walkable path found for any of the destinations I've tried, even the one where I was right in front of it." Checked the log directly: room `M3_out` (Agate Village) has only 4 upward floor triangles against 1097 wall triangles, all 4 clustered in one small isolated patch nowhere near where the player or NPCs actually stand — confirming the earlier bulk-scan finding was a real, live-reproducible failure, not a theoretical edge case. Root cause: the `.ccd` "environment collision" data is overwhelmingly wall/obstacle geometry, not a general ground mesh, in most rooms — the same data this project's already-proven `predict_forward_collision`/blocked-movement feature relies on, which only ever needed walls. **Walkability was pivoted to default-open**: a tile with no floor-triangle coverage is now walkable by default (inheriting whatever height is already known), with walls as the primary gate via `_segment_blocked` instead of floor-triangle presence; real floor data, where present, is still used for precise height. This required a follow-up fix: unconstrained default-open let the flood-fill wander unboundedly across empty space, so `RoomWalkableGeometry.bounds` (the XZ bounding box of ALL triangles in the room, floor+wall combined, plus a `BOUNDS_MARGIN` of 3 tiles) now caps expansion to roughly the room's own modeled extent. A separate bug was also caught in the same log check: `NavigationService.update()`'s "no route yet" branch retried every single poll with no cooldown (unlike the drift-rebuild branch), spamming rebuild attempts every ~50ms — fixed to respect `MIN_REBUILD_INTERVAL` there too. Re-verified directly against the real `M3_out.ccd` data after the pivot: flooding from a destination now reaches a real, contiguous 217-tile connected region (not a 1-4-tile fragment), and multiple plausible in-village player positions successfully route to it. `collision_probe.py`'s `_ray_segment_distance` was promoted to a public `ray_segment_distance` and `terrain_footsteps.py`'s `_load_room_triangles` to `load_room_triangles`, both reused rather than re-implemented. Route waypoint direction (pan) and "hot/cold" intensity (pitch/gain) were deliberately decoupled (`guide_values()` gained an optional `proximity_distance` override) so following a routed detour doesn't cause the tone to swing cold→hot on every single tile hop — intensity reflects the whole remaining route distance (`FlowField.cost_so_far`), not the next waypoint's own distance.
**Same-day follow-up #1: "worked at first, then reverted to no walkable path."** Added targeted debug logging to `NavigationService.next_waypoint` and asked the project owner to reproduce it; the log showed the destination's flow field consistently confined to a small, fully-walled pocket. Live-cross-checked against `M3_out.ccd` directly and initially concluded this was a warp positioned inside a different room's interior (out of scope by design) — the project owner correctly challenged this ("why would warps be considered cross room? they're detected by the map?"): a warp's recorded position is resolved from the CURRENT room's own CCD data (via `parse_interactable_region_centers`), not the destination room's, so reaching the trigger itself is ordinary intra-room routing, not cross-room. Re-investigated with the corrected understanding and found the REAL cause: a genuine ~2-unit-wide doorway gap in the wall around the move tutor's house (confirmed directly — open at z=38–39, solid from z=40–58) fell entirely BETWEEN two tile-row centers (8 units apart, at the pathfinding tile size), so `_segment_blocked`'s single tile-center-to-tile-center line test walked past it on both sides without ever sampling the one spot a real player could walk through. **Fixed**: `_segment_blocked` now samples 5 parallel lines across each tile-to-tile edge (offsets reaching to just under half a tile's width, chosen so two adjacent rows' sampling ranges overlap with no blind strip between them) instead of one — an edge is blocked only if every sampled line is blocked. Re-verified directly against the real `M3_out.ccd` data using the project owner's own logged position: the destination's flow field now reaches a real 9752-tile connected region (not a 6-tile pocket), and the player's actual logged position successfully routes to it in 22 hops. A performance cost came with the fix (profiled and reduced by memoizing `_triangle_longest_edge_xz`, a fixed per-triangle property that was being recomputed on every one of tens of thousands of redundant calls): route-build time on this specific room rose from ~7ms to ~270ms, a one-time cost per activation/rebuild (not per poll) — a real, honestly-reported tradeoff for correctly connecting a genuinely much larger walkable area, not hidden as a free win.

**Same-day follow-up #2: "the pitch/rate doesn't change... unless I'm really close to the target."** A real bug, not just tuning: `guide_values()`'s proximity calc normalized `remaining_distance` (introduced earlier the same day) against `AudioGuideReader.max_distance` (a fixed 120, originally tuned for direct straight-line NPC distances) — a genuinely long routed trip (confirmed live: `M3_out`'s own flow field spans 9752 tiles) easily exceeds 120 units of remaining distance for nearly its whole length, so the "hot/cold" gradient stayed clamped near "cold" until the last ~120 units. **Fixed**: `NavigationResult` gained `route_initial_distance` (the route's remaining distance as it stood the first time it resolved a real player position, captured once and held fixed for that route's lifetime); `AudioGuideReader` now normalizes against `max(max_distance, route_initial_distance)` instead of the fixed constant alone, used consistently for both the gain calc and the repeat-cadence interval. Short trips (already under 120 units) are unaffected — closer targets still sound more urgent immediately, per the pre-existing `test_repeat_interval_shrinks_when_closer`. A first attempt at this fix (a pre-divided 0..1 ratio instead of exposing the raw baseline) was caught as wrong by that same test failing, since normalizing every trip to its own length erases the "closer = more urgent from the first poll" property for ordinary short-range guidance — corrected before shipping.

**Same-day follow-up #3: pitch repurposed from proximity to forward/backward facing.** The project owner pointed out a design issue, not a bug: pitch and the repeat-rate/gain were both signaling proximity — redundant "double dipping." Their proposal: pitch should instead signal whether the target is roughly ahead (10-2 o'clock) or roughly behind (4-8 o'clock). **Implemented as a continuous signal**, not the five-clock-position bins described, and said so directly rather than silently picking one: a hard-binned version would "step" audibly right at the unhandled 3/9 o'clock boundary between the two bins. `guide_values()` now computes `facing = forward / horizontal` (reusing the same values already computed for `pan`) and sets `pitch = 2.0 ** facing` — a full octave up when dead ahead, a full octave down when directly behind, passing smoothly through neutral (1.0) at the sides. Gain remains the sole proximity signal, unchanged in role. `GuideValuesTests` rewritten for the new contract (pitch depends on facing, not distance; `proximity_distance` now overrides gain only); the progressive-warming regression test from follow-up #2 (originally named for pitch) renamed and updated to check gain instead, since that's the responsibility that actually moved.
**2026-07-31 follow-up #4: route-progress validation, route confidence, waypoint adjacency, and a waypoint-reached cue.** The project owner reported the guide "telling me to go right, but I can't," then separately that pitch felt inverted. Both were investigated live before any code changed. **Pitch was NOT inverted** — a live diagnostic constructing synthetic reference points at exactly camera-relative 12/3/6/9 o'clock and comparing `guide_values` against the already-proven `entity_nav.clock_position` returned 12 o'clock → 2.000, 6 o'clock → 0.500, sides → 1.000 exactly, matching the intended "high = hold up" convention; reported as a non-bug rather than "fixed." The real problem was captured by a live watcher: the guide held ONE waypoint fixed for ~18 seconds while the player covered ~40×50 world units, ending in a 6-second dead stop against a wall `_segment_blocked` independently confirmed is real — and `routed_pitch` pinned at 1.99–2.0 (maximum "perfectly aligned") that entire time, i.e. sounding maximally confident precisely while zero progress was being made. Dumping every triangle in that XZ footprint found 20 triangles, ALL near-vertical walls in three stacked height bands (a terraced cliff), **zero** floor triangles, and none in the gap between the floor/wall normal thresholds — so this is missing ground data, not a misclassification. Per the project owner's explicit direction (progress validation FIRST, not a learned height map): `pathfinding.py` gained `flow_field_from(blocked_tiles=...)` and `nearest_supported_floor_distance()` (real floor-coverage distance, independent of the default-walkable fallback, for confidence only — walkability rules unchanged); `navigation_service.py` gained a `RouteConfidence` enum (VERIFIED/UNCERTAIN/FAILED/DIRECT_FALLBACK) and per-waypoint progress tracking that fails a waypoint on stall (4.0s without a ≥1.0-unit improvement) or on ≥3 tiles of cumulative displacement without improvement (covering "moved substantially without progress" and "repeatedly crossing around the waypoint"), then rebuilds ONCE avoiding the failed tile before abandoning collision-based routing for that activation entirely; `audio_guide.py` speaks a distinct one-shot *"Walkable route could not be verified; guiding directly."* and damps pitch's dynamic range 50% toward neutral whenever confidence is UNCERTAIN, so the tone never sounds fully confident about a route built on inferred rather than confirmed ground. Confidence is recomputed each poll against the player's OWN remaining route, not the whole flooded field (which floods far more than anyone walks and would report UNCERTAIN always, carrying no information). **Waypoint adjacency guarantee** (project owner's follow-up requirement that consecutive waypoints be joined by a straight line of nothing but walkable tiles): hysteresis previously advanced to `next_hop[player_tile]`, which after a fast poll could skip several tiles and hand back a waypoint whose straight line from the previous one was never validated — it now advances exactly one hop from the *current waypoint*, and since every `next_hop` edge was individually validated by `_try_edge` during the flood fill, the requirement now holds by construction (pinned by a test asserting every consecutive pair is both `next_hop`-linked and geometrically adjacent). A distinct **waypoint-reached sound** was added (`263124__mossy4__sine-octaves-up-beep.wav`, the one unclaimed file in `assets/npc_sounds_loud/`), firing on the single poll the waypoint advances. Separately, `traversal_log.py` (new) implements conservative walked-EDGE recording — verified A→B tile pairs only, never a filled walkable area, rejecting teleports/warps/room transitions/large jumps/cutscenes/scripted movement/battles/menus/dialogue/collision-stuck samples, with no disk persistence — **deliberately not wired into routing**, per the instruction not to build learned-map routing until progress validation and conservative recording are separately proven.

- Implementation status: Implemented — `pathfinding.py` (new), `navigation_service.py` (new), `audio_guide.py` (updated to consume `NavigationService`, and to give pan/pitch/gain each one distinct job), `collision_probe.py`/`terrain_footsteps.py` (two functions promoted to public for reuse), `npc_beacons.py`'s pitch shift also reworked in the same pass (see its own entry below), `traversal_log.py` (new, standalone, not wired into routing). `numpy` and `pygame` added to `requirements.txt`.
- Live-test status: **Not yet live-tested since the narrow-gap fix, the hot/cold scaling fix, or the pitch/facing redesign** (the pivot version WAS live-tested and correctly diagnosed as broken for the first two — that's what led to all three fixes). Pending a guided walkthrough: a clear straight route, a target behind one wall, a route requiring a turn, a doorway/narrow passage (now specifically expected to work, including the move tutor's house case that originally failed), standing near a tile boundary (waypoint-hysteresis stability check), a LONG route where gain should now audibly warm up well before the final stretch, turning to check pitch rises when the target swings toward "ahead" and falls toward "behind," approaching the real destination (fine-guidance/arrival handoff), and an unreachable/deliberately-failed path (one-shot fallback message) if safely available.
- Regression-test status: Regression-tested — `test_pathfinding.py` (13 tests: wall-forced detours, a fully-enclosed unreachable destination, corner-cut prevention via an actual blocking wall, height-continuity tolerance, narrow corridor, `MAX_TILES` bound, a narrow gap between tile-row centers found via multi-sample offsets, a fully solid wall still correctly blocking), `test_navigation_service.py` (22 tests, including the 2026-07-31 progress-validation set: steady improvement surviving past the stall timeout, stationary-player abandonment after two failures, sideways movement failing before the stall timeout, the failed tile excluded from the rebuild, VERIFIED vs UNCERTAIN confidence by real floor support, and the waypoint-adjacency invariant), `test_audio_guide.py` (26 tests, including facing-based pitch coverage, a long-route progressive-gain-warming test, UNCERTAIN pitch damping, the distinct progress-invalidated message kept separate from the geometry-unreachable one, and the waypoint-reached cue firing only on advance), `test_traversal_log.py` (12 tests: valid edge recording, every exclusion category, room transitions, large jumps, breadcrumb retracing, and explicitly that a thin trail is never extrapolated into a walkable area). Full suite: 613 passing (run via the project's own `.venv`, not system Python, so the `numpy`-backed pitch tests execute for real). One pre-existing test (`test_gain_warms_progressively_...`) was rewritten to walk in realistic small steps rather than one large synthetic jump — the new validation correctly treats a big unexplained jump as a suspicious non-walking event, so the old test had been quietly depending on unrealistic movement.
- Last verified date: 2026-07-31 (regression tests + live investigation of the terraced-cliff region and the pitch convention; the 2026-07-31 progress-validation/confidence/adjacency/waypoint-cue work is **not yet live-tested** — the narrator has been restarted so it is live, and a detailed watcher is ready)
- Remaining work: **live-validate the 2026-07-31 progress-validation work on the same terraced/cliff route** — specifically that the guide stops insisting on a bad waypoint within a short bounded period, speaks the new message once, and that the waypoint-reached cue and UNCERTAIN pitch damping are audible and not annoying in practice (all proven in tests, none confirmed live). The underlying "this region has no real floor data at all" problem is unchanged and still unsolved — this pass makes the guide honest about it rather than confidently wrong; a conservative traversal-edge source (`traversal_log.py`) exists and is tested but is deliberately not yet consulted by routing. Also still pending: live-validate the routing, hysteresis, hot/cold-across-a-long-route, and pitch/facing behavior in an actual play session; genuine cross-room routing (continuing PAST a door/warp into the new room, not just reaching the door itself, which already works) remains a real, separate, larger feature — investigated its data requirements this same session: warps/elevators carry a `target_room_id` today, but the destination LANDING POSITION is not resolvable anywhere in this codebase yet (`target_entry_id`/`target_elevator_id` are raw indices into a per-room `.rel` "entry locations" table that no existing parser reads; doors carry no destination room ID at all in current parsing). This is a real blocker for cross-room routing, not just unscheduled work — flagged clearly rather than assumed solvable by reusing existing data. A breadcrumb/turn-point waypoint reduction (only announcing a new direction where the route turns ≥90°, discussed with the project owner as a refinement of the already-deferred "route simplification" item) remains proposed but not implemented. Route-build performance on very large open areas (~270ms measured on `M3_out` after the gap fix) may be worth optimizing further if it proves noticeable in practice.
- Notes: `ctrl+g` toggles the guide for the current entity-nav selection. `navigation_service.NavigationService` and `pathfinding.py` were built as reusable, `AudioGuideReader`-independent infrastructure per the project owner's explicit direction, so future features (autowalk, breadcrumb guidance, spoken turn directions — none started this pass) can consume navigation information without depending on the audio guide specifically.


**2026-08-02 follow-up #5 — SUPERSEDES the default-walkable descriptions above.** An ownership investigation (see `WORLD_NAVIGATION_ARCHITECTURE.md`) established that the "missing floor data" premise underlying follow-ups #3 and #4 was **wrong**. CCD slot **+0x24** (`CCD_WALKMDL_HEAD`) is the engine's own walkable-ground model, read by `GScolsys2WalkGetHeight` and consumed by both real player locomotion (`heroMove.s`) and NPC locomotion (`people.s`). It carries per-triangle **layer identity** and explicit **transition triangles** between layers. This project had simply never parsed it — it read only +0x28 (`CCD_HITMDL_HEAD`, obstacles). Measured: **26,088 upward-facing triangles across 167 rooms in +0x24 vs 289 in +0x28**; in `M3_out`, 570 walk triangles across 5 layers with explicit 0↔1, 1↔2, 2↔3, 3↔4 transitions. So: **+0x24 is authoritative walk geometry; +0x28 is hit/obstacle geometry only and must never be treated as a floor source; layers — not height proximity — govern terraces** (`M3_out`'s layers 1/2/3 have overlapping height bands, which is precisely why the old height-continuity heuristic could not disambiguate them). Navigation was rewritten accordingly: `collision_probe.parse_walk_model_triangles` + `WalkTriangle` (Phase 1), `walk_height_candidates`/`resolve_node` mirroring `GScolsys2WalkGetHeight`/`WalkGetLayer` (Phase 2), a flow field keyed by **node = (tile, layer_set)** with layer-set intersection as the connectivity gate (Phase 3), and removal of the default-walkable model, inferred floor heights, `nearest_supported_floor_distance`, and `RouteConfidence.UNCERTAIN` — all of which existed only to compensate for the parse gap (Phase 4). `traversal_log.py` is **shelved**: its motivating premise no longer holds. Runtime object-enable state is isolated behind `collision_object_enable.ObjectEnableState` and ships as `StaticObjectEnableState`; a narrow live read at the traced `≈0x80445C20` was **inconclusive**, so dynamic geometry remains **not live-validated** (Phase 5). **[UPDATED 2026-08-13: superseded. The always-enabled default was not a neutral placeholder — it rebuilt walls the running game had switched off, which is what made Agate's Relic Stone cave unroutable (`M3_out` object 33; `M3_cave_1F_1` objects 4 and 5 — six triangles in total). The 2026-08-02 probe was inconclusive because the record base is `GScolsys2 + 0x04`, not `+0x00`. `LiveObjectEnableState` now reads the engine's own per-object flags and `NavigationService` invalidates geometry and discards stale routes when they change; the address is pinned by a new `GScolsys2GetObjEnable` engine signature matched against the shipped `main.dol`. Live-validated the same day in `M3_out`: the engine reported object 33 disabled, wall triangles fell 1097 → 1095, and the cave pocket became the 1861-node component that had been predicted statically before the game was run. Still owed: the Gateon oracle, the only place objects toggle mid-session. See COLLISION_DETECTION_INVESTIGATION.md §"Runtime object-enable state" and §"Live confirmation".]** Live testing then forced four evidence-based recalibrations, each with a regression test proven to fail against the old value: `HEIGHT_CONTINUITY_TOLERANCE` 6.0→10.0 (a real climbable slope has 7.40-unit steps); `SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS` 24→160 units (24 was 0.7–1.4s at the measured 17–38 units/s, less than reaction time); `WAYPOINT_STABLE_RADIUS_RATIO` 0.5→0.9 (live closest approaches were 4.72/4.30/6.36/8.57, never inside the 4.0 window, so waypoints never advanced); and `MAX_ROUTE_REBUILDS_PER_ACTIVATION` changed from a never-resetting lifetime count to one that **replenishes when a waypoint is reached** (a whole journey previously got one recovery; live, it abandoned 9.7s in despite real progress at 5.7s). A separate structural defect was found and fixed: `(tile, layer_set)` is not well-defined from position alone — one tile can hold differently-tagged triangles, so the flood fill (tile centres) and `resolve_node` (real position) could disagree, producing a spurious "player node not linked"; confirmed live at `M3_out` tile (15,-21) where the centre resolves to {3} and a point 3.6 units away resolves to {3,4} at the *same* height 120.005. Fixed via `NavigationService._field_node_at` (match on tile + nearest real height).
- Live-test status: **PASSED for the original terraced route.** `AUDIO GUIDE Arrived.` logged 2026-08-02 14:17:22, and the project owner confirmed it reaches the destination consistently. Watcher evidence: real walk-model floor under every sampled position (`dy=0.000`), correct `L0 → TRANS[0,1] → L1` transitions followed, wall checks clear, `conf=verified` throughout, first genuine waypoint advance, and no unsupported-floor or missing-geometry fallback. Full suite 653 passing.
- Known-open (not defects, deliberately deferred): **redundant waypoints** — measured 5 nodes over a path of length 32.0 vs straight-line 32.0 (1.00x) with **3/3 interior waypoints collinear**; line-of-sight route simplification remains unimplemented. **First-waypoint instability across re-toggles**, reported live but **not reproduced** (flow field deterministic 6/6; waypoint stable across ±3 units and across a tile boundary at the tested position); leading hypothesis is equal-cost branch points, unconfirmed pending the player's position at the moment it occurs. **3 rooms fail walk-model parsing outright** (`M6_pc_1F`, `M6_tower_3F`, `M6_tower_4F` — non-finite vertices) plus 10 with no +0x24 at all; all load as an honest empty result, none investigated.

### Autowalk (`ctrl+shift+/`)
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Implementation status: **Implemented 2026-08-16, NOT yet live-tested.** The project owner reversed the standing rejection of autowalk ("you may void the read only philosophy for this time") after an investigation established that the game contains the mechanism already. `heroMove.s` reads the stick through one private accessor, `_getStickData` (0x8014E7F8), whose first act is to test a flag at `HeroMove+0x3AE` (HeroMove = 0x804479F0, pinned by the `lis`/`addi` pair at the top of both accessors) and, when set, return four stored bytes (+0x3AF..+0x3B2) while branching past every `GSinputGetLeftStick*Data` call, the D-pad translation and the camera-type checks. The engine drives this itself: `_heroMoveSlowStopFactor` (0x8014EDF4) samples the live stick, decays it over successive frames through `_setStickData` (0x8014E7D4), and clears the flag — the deceleration when the game takes control. So autowalk pushes the engine's own stick and lets ordinary locomotion do the walking: collision, walk-model height/layer resolution, animation, footsteps, warp triggers, encounter steps and talk cones all behave exactly as under a real player, and **nothing writes the player's position** (unlike `teleport.py`, which does and therefore bypasses all of it). New: `hero_stick.py` (the writer, plus a local byte-signature check of both accessors), `autowalk.py` (`AutowalkReader`, steering and stopping only). Changed: `movement_input.py` gained `is_movement_requested()` (stick **or** D-pad, level state) as the abort signal, leaving `is_direction_held()` untouched for `BlockedMovementReader`; `profile.py`, `phase1b_app.py`, `phase1b_lifecycle.py` wired following the standard reader pattern. Routing is `NavigationService`'s, unchanged — autowalk holds its **own** instance rather than the guide's, since a service owns one active route and sharing would make each feature silently retarget and clear the other's.
- Sign convention is cross-verified from two independent directions: `_getStickData`'s D-pad branch stores Y = −0x38 for PAD_BUTTON_UP and X = −0x38 for LEFT, and `movement_input.py`'s live 2026-08-03 measurement independently found stick Y negative for up with positive X toward the camera's right. 0x38 (56) is also exactly the full deflection that session measured.
- Safety model: it moves only on `VERIFIED` or `PARTIAL` confidence, and `PARTIAL` speaks its measured shortfall before continuing. `DIRECT_FALLBACK` is a refusal, deliberately — a straight line is useful advice to a person who can feel their way around a wall, but handed to a stick it is an instruction to walk into that wall. It stops on player movement input (the primary, deliberate abort), loss of free-roam context, room/floor change, selection change or target loss, no progress for 2.5s, and a 90s hard ceiling; every stop releases the override, and `clear()` releases unconditionally whether or not the reader believes it is active.
- Live-test status: **First live run 2026-08-17 -- the override works, and it found a routing defect.** Two activations in `M6_out` (Gateon Port) toward the world-map exit; the player was walked, and both times arrived in the parts shop instead. The override itself is therefore live-proven: the engine accepted the stick bytes and moved the character under normal locomotion. What failed was underneath it -- see the trigger-avoidance entry below. Autowalk's own stop conditions behaved correctly throughout, releasing on the room change (`AUTOWALK CLEAR reason=autowalk read failure`, the hero model being torn down mid-transition). Still unmeasured live: arrival, the approach taper, the blocked timeout, and the input abort.
- Earlier live-test status (superseded): **Not started.** The address block was read read-only on a live GXXE01 process (mapped, flag 0, sticks idle) but emulation was paused at the time, so nothing behavioural has been confirmed — no write has ever been made to these addresses on a running game. `Companion/_probe_hero_stick.py` exists to do exactly that check, and the first live run should be a short, deliberately boring one (see its docstring).
- Regression-test status: Regression-tested — `test_autowalk.py`, 39 tests: stick geometry in all four camera directions plus a rotated camera, full-deflection magnitude and the approach taper, activation refusals (no selection, not free-roaming, signature mismatch), and every stop condition, including that `DIRECT_FALLBACK` and `FAILED` never produce a single stick write, that oscillating without improving still counts as blocked, that input held from before activation does not instantly cancel but input held past the grace period does, and that a non-D-pad button (pressing A to talk to whatever you were walked to) is not read as a request to stop. `hero_stick` is covered for one-write hold, flag-only release, clamping, a release that cannot raise, and a failed signature check that is not cached (so a still-booting game does not lose the feature for the session). Full suite: 1591 passing, 2 pre-existing failures in `test_passability.DestinationProjectionTests` that reproduce with this change reverted.
- Hotkey moved 2026-08-16 (same day, project owner's request): `ctrl+w` → `ctrl+shift+/`. `ctrl+w` is now unbound and was deliberately not reused for anything else — a key that has meant "walk me there" should go quiet rather than start doing something different. The chord it moved onto only became usable in the same change; see the entity-nav refresh row above for why.
- Last verified date: 2026-08-16 (static derivation + regression tests only)
- Remaining work: **live validation, which is the whole of it.** Nothing here has moved a character. Also unvalidated by measurement rather than reasoning: the approach taper constants (`APPROACH_DISTANCE`/`APPROACH_DEFLECTION`), the 2.5s blocked timeout, and whether the routing symptoms `NAVIGATION_AUDIT_2026-08-04.md` §7 still lists as unexplained (the west-east-west waypoints; unmeasured camera-yaw drift) are tolerable when a stick rather than a listener is acting on them — a guide's bad waypoint costs a correction, autowalk's costs a walk in the wrong direction.

### Trigger avoidance in routing
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Implementation status: **Implemented 2026-08-17.** Found by the first live autowalk run and diagnosed from the log plus the shipped collision data. Routing had no concept of warp triggers: a route could cross any number of them, and the audio guide has always had the same flaw -- a sighted-enough player just steers around the door, which is why it went unnoticed until a stick was following the route literally. The live route's second leg ran (92, 196) -> (89, 223) and warp region 7 (`common.rel` record 727, target room 0x97, the parts-shop door) is a trigger curtain 25 units wide at z=214.0; measured against the logged waypoint sequence, the leg passed **0.69 units** from its centre. Worse, the one place that knew these regions existed made it likelier: `region_geometry.interaction_volume_keys` deliberately REMOVES their triangles from the wall set so a doorway is never rebuilt as a barrier -- correct for Agate's Relic Stone cave (a trigger you must walk into, which does not change rooms), exactly wrong for a door you are only walking past. The distinction is not "is this an interaction region" but "does crossing it move me somewhere else", which only the warp records answer. `NavigationService` now takes `room_change_regions`, built in `phase1b_app.py` from the same authoritative `common.rel` warp/door/elevator records the "Exits" category is built from, and refuses any route leg that crosses one -- except the destination's own region, which routing to a door obviously has to reach.
- **Crossings, not tiles, and that distinction was measured.** The first implementation blocked every tile a trigger touched; on `M6_out` that cut the player's reachable component from **23,488 tiles to 1,961**, because Gateon Port's doors sit in narrow gaps between buildings and an 8-unit lattice swallows the gap along with the door. Refusing the crossing instead (`pathfinding._crosses_blocked_segment`, reusing the same `_segment_segment_distance` primitive the swept wall test already uses) leaves the gap walkable and costs **none of the room's ten exits their route** -- verified by routing to all ten from the logged player position with the guard on.
- Live-test status: **Not yet live-tested.** The exact live route cannot be replayed offline -- it was built against the engine's live collision-object enable state, and Gateon Port is precisely the room whose piers toggle, so the offline geometry differs. The defect reproduces on a different destination in the same room from the same data (region 11: 0.1 units from the parts-shop curtain unguarded, 74.2 guarded), which is what the regression tests pin.
- Regression-test status: Regression-tested -- `test_trigger_avoidance.py`, 12 tests: the crossing primitive (through / alongside / around the end / grazing), the curtain's real geometry pinned against the log's own numbers, the unguarded defect pinned so the fix cannot be mistaken for the room not having the problem, all ten exits still routing with the guard on, a destination still reachable through its own trigger, and `room_change_regions=None` remaining a faithful no-op for every offline tool and test that constructs the service without one.
- Last verified date: 2026-08-17
- Remaining work: live-confirm that autowalk now reaches the world-map exit from Gateon Port. Unknown by measurement rather than reasoning: whether `TRIGGER_CROSSING_MARGIN` (1.0) is the right grazing tolerance, and whether any room exists where a room-changing trigger genuinely spans the only passage -- there, refusing is correct but the player will meet an honest refusal where they previously got a route that worked by teleporting them.

### Collision feedback (blocked-movement cue)
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: **Investigating** — deliberately kept out of "Partially accessible"/"Implemented" per the project owner's explicit instruction, since the movement-input signal the cue depends on is not yet verified
- Current limitation: the first cut (stillness + facing a wall, no input check) was correctly rejected by the project owner as an unacceptable false positive for anything framed as collision feedback — it could not distinguish "actively pushing into a wall" from "standing still near a wall by choice." Redesigned (2026-07-29) into a fully separate `BlockedMovementReader`, requiring ALL of: (1) a movement direction actively held, (2) displacement below the stillness threshold, (3) forward collision geometry in the player's current facing direction, (4) sustained for a short debounce window, (5) not already fired this episode — resetting on movement, input release, a material facing change, or the obstacle clearing. This logic is implemented and unit-tested, but the "movement direction actively held" signal itself has **two unverified candidates**, neither live-confirmed yet:
  1. `movement_input.GSinputMovementSource` — reads the game's own cached Control Stick state (`GSinput`, not global keyboard state, so it works the same regardless of input device). Candidate address chain derived from static disassembly of `GSinputGetLeftStickXData`/`GSinputGetLeftStickYData` and their per-controller lookup — controller port 0 assumed to be the player's own controller (unconfirmed), deadzone threshold unconfirmed.
  2. **New lead (2026-07-29, from the project owner's own firsthand play observation that the walk animation continues even when blocked):** `tagPeopleWork+0x54`, a small enum byte confirmed via symbol names to hold locomotion-behavior state — `peopleStartWalkRandom` sets it to `4` ("walking"), `peopleStartRotRandom` sets it to `5` ("rotating"); it also gates whether `peopleUpdateAnimation` (the per-entity animation-update routine) runs at all, requiring it to be ≤6. These are confirmed AI-random-walk/rotate setters, not yet confirmed to be the same field the *player's own* held-input walking uses — `updateLeaderMovement`/`moveParty` (the hero's own per-frame movement functions) were disassembled directly and do not write this field themselves, so if the player's walking sets it too, it happens elsewhere not yet traced. The hero's own `tagPeopleWork` entry can be found live via the same pool already used elsewhere this session, filtered by `active != 0 and resID < 100` (per `isHero__13tagPeopleWorkCFv`'s own logic, statically confirmed).
- Severity: 1 (no collision/wall feedback at all)
- Story requirement: none
- Reproduction steps: not to be attempted yet — **explicitly not ready for live testing** per the project owner's instruction, pending verification of one of the two candidate signals above
- Relevant save/save-state: none captured
- Technical findings: `COLLISION_DETECTION_INVESTIGATION.md` (Codex, 2026-07-26) for the original collision-system research; this session's own disassembly of `GSinputGetLeftStickXData`/`GSinputGetLeftStickYData`/`peopleStartWalkRandom`/`peopleStartRotRandom`/`peopleUpdateAnimation`/`isHero` for the two candidate input/animation signals
- Implementation status: Implemented (gating logic and both module scaffolds), gated behind its own separate `--collision-feedback` flag, independent of `--terrain-footsteps`, both off by default
- Live-test status: Not live-tested — **do not enable for live testing** until a candidate signal is confirmed
- Regression-test status: Regression-tested (`test_terrain_footsteps.py`'s `BlockedMovementReaderTests`, `test_movement_input.py`)
- Last verified date: 2026-07-29 (implementation + tests only; no live verification of either candidate signal)
- Remaining work: verify one of the two candidate signals via read-only live polling (comparing idle vs. player-walking vs. player-holding-into-a-wall) — explicitly preferred over a GDB trace per the project owner's own priority order (existing structures → static cross-reference → read-only polling → GDB last); if verified, wire the confirmed source into `blocked_movement_factory` in place of the current placeholder; if animation-state proves reliable, also confirm it doesn't fire during scripted/NPC-controlled/cutscene movement before trusting it as a player-intent signal
- Notes: `ControlledRoomCollisionProbe` (the original single-room, hotkey-triggered diagnostic) is untouched and still exists separately for manual one-room checks

### Footstep sound / terrain feedback (redesigned 2026-07-29 to avoid GDB dependency)
- Primary workstream: Navigation and spatial awareness
- Discovery status: Currently reachable (works in any room, no story gate)
- Accessibility status: Implemented — **not yet live-tested**
- Current limitation: static/symbol search for the game's own native footstep-SFX trigger came up empty (history preserved below) and would have needed a live GDB trace to resolve, which the project owner judged too expensive relative to value given the earlier slowdown/boot-hang incident. **Redesigned per the project owner's explicit direction** to answer "am I moving, and what am I walking on?" using only data already safely available, without reproducing the game's native footstep audio: player-position deltas (already read for entity-nav/beacons) derive "is moving" and pace synthetic steps by real distance travelled, not the game's animation timing; the same locally-parsed room `.ccd` geometry already used for warps/doors/elevators/`collision_probe.py` supplies a "what's underfoot" terrain identifier via each environment triangle's `collision_type` field (semantic meaning still unclassified, but a distinguishable tone is guaranteed per distinct raw value); a "blocked" cue reuses `collision_probe.predict_forward_collision`'s existing geometric forward-ray prediction instead of the game's own ephemeral, unreadable collision result. No native sound, animation state, or velocity field was needed.
- Severity: was 1 (no footstep/terrain audio feedback existed at all); pending live confirmation of the new synthetic layer
- Story requirement: none
- Reproduction steps: walk on any surface (should hear a synthesized step cue every ~1.6 units travelled, pitch-varying by the raw local `collision_type` underfoot); stand still near a wall while facing it for a beat (should hear a distinct "blocked" cue once, not repeating until movement resumes)
- Relevant save/save-state: none needed — the feature works in any room with an already-extracted `.ccd` file (177 of 177 rooms with an interaction table already covered)
- Technical findings: new module `terrain_footsteps.py` — `find_ground_triangle()` (point-in-XZ-triangle + height-window ground lookup, mirroring `predict_forward_collision`'s existing wall-triangle filtering logic but inverted for horizontal surfaces), `TerrainFootstepReader` (distance-paced step cadence + stillness-duration-gated blocked-cue check), `TerrainTonePlayer` (synthesizes its own short click/buzz WAV tones via pure-stdlib `wave`/`struct`/`math` — no new binary asset files, no dependency on any existing beacon sound — and reuses `SpatialWavePlayer`'s existing pan/pitch/gain rendering, pitch keyed deterministically to the raw `collision_type` value without asserting semantic meaning for any value)
- Implementation status: Implemented, wired into `phase1b_lifecycle.py`/`phase1b_app.py`. **ON BY DEFAULT since 2026-08-10** at the project owner's request: the flag was opt-in only while the cadence/distance constants were being tuned live, and that tuning finished on 2026-07-29. `--terrain-footsteps` is still accepted (existing launchers pass it) but is now a no-op; `--no-terrain-footsteps` turns it off. The default is asserted in `tests/test_cli_defaults.py` rather than left to the desktop `.bat`, which lives outside this repository. Step gain also raised 50% the same day (`TerrainTonePlayer.STEP_GAIN` 0.6 → 0.9) — the blocked cue keeps its own separate level. **Split (2026-07-29) from collision/blocked-movement feedback**, which now has its own separate `--collision-feedback` flag and its own `BlockedMovementReader` class — footsteps no longer include any blocked-cue logic at all, neither flag auto-enables the other (per the project owner's explicit instruction), and `--collision-feedback` deliberately stayed off by default when footsteps flipped on, since it is still gated on an unverified movement-input read.
- Live-test status: **Live-tested (2026-07-29).** First attempt found total silence across 200+ real units walked; root-caused via the narrator's own log to `MAX_PLAUSIBLE_DELTA=8.0` discarding all real walking as false teleports (real deltas: 16-23/poll; real jumps: 143+/poll). Fixed with that data (`MAX_PLAUSIBLE_DELTA`→60.0, `STEP_DISTANCE`→12.0). After relaunch, the project owner confirmed it works. Dialogue-suppression and room-transition/no-burst handling were also independently confirmed via the same log evidence gathered during diagnosis. **Remaining checklist items (menu silence, turn-in-place silence, tone-changes-only-on-real-terrain-change, speech-clarity-over-sounds, input-lag) were explicitly skipped by the project owner's own choice**, not overlooked — noted here so this isn't mistaken for exhaustive confirmation later.
- Regression-test status: Regression-tested (`test_terrain_footsteps.py`, 18 new tests; 379 total passing)
- Last verified date: 2026-07-29 (implementation + tests only)
- Remaining work: live-test and tune the cadence/stillness/blocked-distance constants; confirm the synthesized tones are actually pleasant/distinguishable in practice (pure engineering judgment was used to pick waveform parameters, since audio can't be previewed without the player's ears); consider whether character facing (rather than camera-anchored yaw, which `player_pose()` currently supplies) would give a more accurate blocked-direction cue — not changed this pass since `player_pose()`'s existing yaw source is already what every other directional feature in this project uses
- Notes: original static-search history (symbol/disassembly dead ends: `floorSound_*` ruled out as background-music ducking, `procStep` ruled out as a graphics-timing false lead, `updateLeaderMovement` disassembled with no sound-engine calls found, `_sndPlaySE` confirmed used only internally within `GSsnd.s`) is preserved in [PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md) #7 for reference; a live GDB trace on the native sound engine remains a possible *future* enhancement (to eventually reproduce/complement the game's real terrain audio) but is no longer a dependency for this feature to exist and work

### NPC direct-interaction assistance (bypass distance/facing cone)
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: Blocked technically
- Current limitation: no safe invocation mechanism found for triggering the talk sequence from outside the game
- Severity: 1
- Story requirement: none
- Reproduction steps: N/A (investigation, not yet an implementation)
- Relevant save/save-state: none captured
- Technical findings: full call chain traced this session (`updateChat`→`peopleTalkCheck`→`peopleGetTalkSctID`→`floorExecScriptRes`/`floorExecScriptResThread`); confirmed the talk-triggering functions are pure `(groupID, resID)`-driven with no proximity dependency of their own; confirmed `(groupID, resID)` via the independently-discovered `peopleSearchID` function; no safe external "mailbox" hook found (the retail debug-menu system is a candidate but disproportionately risky/visual); execution breakpoints previously shown unreliable in this Dolphin/GDB-stub setup
- Implementation status: Not implemented (explicitly deferred pending a decision — see [PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md) #5)
- Live-test status: Not live-tested
- Regression-test status: N/A
- Last verified date: 2026-07-29 (static trace)
- Remaining work: decide between re-testing one-shot breakpoint reliability, a scoped/authorized code patch, or an approximate "impersonate a nearby real NPC" fallback
- Notes: this is the project's current active technical investigation

### Interaction-start announcements ("Talked to X.", "Opened X.")
- Primary workstream: Navigation and spatial awareness
- Discovery status: Currently reachable
- Accessibility status: Implemented, Regression-tested. Not yet live-tested.
- Current limitation: only covers NPC/door/warp/elevator/PC/sign categories (matching entity-nav's existing set minus item/healing, which don't have a clear "interaction begins" transition). The per-category verb phrasing ("Talked to"/"Opened"/"Entered"/"Used"/"Read") is a first-cut design choice, not confirmed against what the project owner actually wants to hear for each type. The default disambiguation radius used for door/warp/elevator/PC/sign (no per-entity `interaction_distance` exists for these categories, unlike NPCs) is an unverified placeholder.
- Severity: N/A (new capability, not a previously-tracked gap)
- Technical findings: reuses `entity_nav.py`'s own already-proven "free-roam control lost" detection (window opens or dialogue becomes active) for NPC/PC/sign-style interactions, and its "map changed" detection (`current_floor_id` changing) for door/warp/elevator-style room transitions -- both signals already existed and are independently re-implemented here (not read from `EntityNavigator`'s own state) to avoid coupling to or risking regressions in that already-working, tested reader. For room transitions specifically, the player's position at the moment the floor ID changes is already in the new room and useless for identifying the trigger, so the reader caches the player's pose every poll and uses the cached pre-transition position once a floor change is detected.
- Implementation status: Implemented as `battle_narrator/interaction_announcer.py`'s `InteractionAnnouncer`, using the exact same entity sources (name/position resolution) `entity_nav.py` already uses for NPC/door/warp/elevator/PC/sign categories -- no new name-resolution path.
- Live-test status: Not yet live-tested
- Regression-test status: Regression-tested (`test_interaction_announcer.py`, 14 tests)
- Last verified date: 2026-07-29 (implementation + tests only)
- Remaining work: live-test across all six categories; confirm or correct the per-category verb wording; tune (or find real per-entity data for) the disambiguation radius for door/warp/elevator/PC/sign categories, currently a flat, unverified default.
- Notes: deliberately does not touch `entity_nav.py` itself -- a fully independent reader watching the same two underlying signals, so a bug here cannot regress entity navigation and vice versa.

### Room or area summaries
- Primary workstream: Navigation and spatial awareness
- Discovery status: Unknown
- Accessibility status: Unknown
- Current limitation: not investigated
- Severity: unknown pending investigation
- Story requirement: none known
- Remaining work: not started
- Notes: named explicitly in the project owner's seed list; no research performed yet

### Accessible map information (in-game Map menu)
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: Investigating
- Current limitation: static research only (`MAP_ASSET_RESEARCH.md`); no live memory hook or production feature
- Severity: 1
- Story requirement: none (already reachable)
- Technical findings: `MAP_ASSET_RESEARCH.md`; an earlier ad hoc request to "locate PCs from extracted map data" was explored but not turned into a feature
- Implementation status: Not implemented
- Live-test status: Not live-tested
- Regression-test status: N/A
- Last verified date: not recently re-verified
- Remaining work: determine what the in-game Map menu actually shows and whether a live hook or purely static answer (room name + known landmarks) is sufficient
- Notes: distinct from entity-nav's warp/door data, which already gives authoritative positions without needing the in-game map screen itself

---

## General menus

### Title screen / main menu / options
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Current limitation: none known
- Severity: N/A (resolved)
- Technical findings: `TITLE_MAIN_OPTIONS_ACCESSIBILITY.md`
- Implementation status: Implemented
- Live-test status: Live-tested
- Regression-test status: Regression-tested (`test_phase1e_menus.py`)
- Last verified date: 2026-07-26 (approx, per doc)
- Remaining work: none currently open

### Yes/No confirmation dialogs
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Current limitation: parent-window detection is an explicit allowlist (`yes_no_confirmation_parent_ids`); a not-yet-seen parent context could still slip through silently
- Severity: 2 (would appear as "prompt goes silent," not a hard block, since the prompt itself still exists on screen)
- Technical findings: `menus.py`'s `yes_no_node`/`yes_no_focus`
- Implementation status: Implemented
- Live-test status: Live-tested (menu-triggered, dialogue-triggered, and Continue-screen parent 52 cases)
- Regression-test status: Regression-tested
- Last verified date: 2026-08-08
- Remaining work: watch for another confirmation-prompt parent context during future play; the Continue save-summary screen itself is tracked separately and is not covered by this row
- Notes: extensible by design (`yes_no_confirmation_parent_ids: tuple`) specifically for this reason

### Continue save-summary fields
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Implemented and Regression-tested; narrator restart/live confirmation pending
- Technical findings (2026-08-08/09): menu 219 is `menuSaveLoadCtrl`. Shipped DOL messages 231-238 are four label/value pairs: the labels and their player-name, play-time, snag-count, and purified-count templates. `_SaveParameterSet` writes play time to opcode `0x4C`, snag count to `0x34`, and purified count to `0x35` immediately before display. `msgctrlTime` was traced instruction-by-instruction: `_Time / 3600`, remainder `/ 60`, unpadded hours plus colon plus two minute digits. A read-only live render produced `27:10`, `22`, and `13` from the running game.
- Implementation status: Implemented by rendering messages 231-238 through `MessageRenderer` and prepending the resulting four fields to the first Continue confirmation focus. Production contains message routing IDs only, not retyped labels or values.
- Live-test status: Not yet live-tested after narrator restart. The 2026-08-08 23:35 log came from the older running process and spoke only `No`.
- Regression-test status: Regression-tested (`test_phase1e_menus.py`; full suite 1,111 passing at implementation time)
- Last verified date: 2026-08-09
- Remaining work: restart narrator and confirm the complete summary is heard on the real Continue screen

### Generic multiple-selection panels
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Live-tested historically; corrected implementation Regression-tested, new count rule pending live confirmation
- Technical findings (2026-08-09): menu 89 is `menuPanelCtrlSelect`. Its draw routine reads message IDs from the window allocation. Its controller obtains window parameter 2, allocates exactly `count * 4` bytes, and copies exactly that many IDs; `windowGetParam` proves parameter N is at `window + 0x68 + N*4`. The old resolve-until-failure heuristic over-counted at least one live list as eight rows, including duplicate message 128.
- Implementation status: `ChoiceMenuReader` now uses parameter 2 as the authoritative bound and requires every counted ID to resolve through the loaded game message tables.
- Live-test status: the older mechanism was live-tested across Mt. Battle, shops, and other menu-89 lists; the corrected authoritative-count version awaits the next narrator restart
- Regression-test status: Regression-tested (`test_choice_menu.py`)
- Last verified date: 2026-08-09
- Remaining work: live-confirm correct position totals on the next menu-89 screen

### Scripted move-teacher move lists
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Implemented and Regression-tested; not yet live-tested
- Technical findings (corrected 2026-08-10 from production evidence): menu IDs 228/229 both use `menuScriptWazaOshieCtrl`/`Cursor`. Cursor identity is the standard signed base at `+0x9C` plus position at `+0x9E`; `_WazaNum` (`0x804E7FA8`) is the row count; `_wazalist` (`0x804EA8D8`) points to 24-byte records. Real move rows are identified by the move ID at `+0`; resolve their game-owned name through `LocalMoveData`. The earlier claim that every row owned a message ID at `+4` was disproved by the 2026-08-10 live EXTREMESPEED row, whose `+4` word was poison value `0xB5353535`. The terminal non-move row still uses its `+4` message ID.
- Implementation status: `ProductionMenuReader` resolves the selected record's own message ID through `MessageRenderer`. No move or final-row label is embedded in production.
- Live-test status: Not yet live-tested
- Regression-test status: Regression-tested with move and final-row records, including move ID 245 resolving to the real `EXTREMESPEED` spelling while the captured `0xB5353535` word is deliberately rejected as text ownership
- Last verified date: 2026-08-09
- Remaining work: live-confirm at either move-teacher variant after narrator restart

### PDA / Trainer Card (mailbox)
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Current limitation: none known
- Severity: N/A (resolved)
- Technical findings: `PDA_ACCESSIBILITY.md`, `pda.py` (Codex, 2026-07-27)
- Implementation status: Implemented
- Live-test status: Live-tested (per attribution log)
- Regression-test status: Regression-tested (`test_pda.py`)
- Last verified date: 2026-07-27
- Remaining work: none currently open

### PDA Spot Monitor and Shadow Monitor
- Primary workstream: Speech and information coverage
- Discovery status: Discovered from native GXXE01 writers and data ownership
- Accessibility status: Implemented, Static-verified, Regression-tested
- Current limitation: not yet live-tested in Dolphin
- Severity: high
- Technical findings: `PDA_ACCESSIBILITY.md`, `pda.py` (Codex, 2026-08-10)
- Implementation status: Spot Monitor reads only unlocked spots from world-map flags, then game-owned location/species/food values; Shadow Monitor follows the native sorted records and cursorBios slot 12
- Live-test status: Not yet live-tested
- Regression-test status: 11 targeted PDA tests; full suite 1,352 passing
- Last verified date: 2026-08-10
- Remaining work: bounded live confirmation; Mailbox list and Strategy Memo

### Remaining general menus
- Primary workstream: Speech and information coverage
- Discovery status: Unknown
- Accessibility status: Unknown
- Current limitation: the pause menu's full structure beyond the submenus already covered (Bag, Party, PDA, PC) has not been systematically inventoried
- Severity: unknown pending discovery
- Remaining work: discover through play; no speculative inventory attempted here per the "no speculative overengineering" rule

---

## Pokémon and party menus

### Party list screen
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Current limitation: index-6 "Cancel" inferred, not independently OCR-confirmed like the other labels
- Severity: 3
- Technical findings: `party_list_screen.py`
- Implementation status: Implemented
- Live-test status: Live-tested
- Regression-test status: Regression-tested (`test_party_list_screen.py`)
- Last verified date: 2026-07-26
- Remaining work: none currently open

### Party action popup (Summary/Switch/Item/Cancel) and Give/Take popup
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Current limitation: none known
- Technical findings: `party_action_menu.py` (generalized to cover both popups)
- Implementation status: Implemented
- Live-test status: Live-tested
- Regression-test status: Regression-tested (`test_party_action_menu.py`)
- Last verified date: 2026-07-26
- Remaining work: none currently open

### Party summary screen (Info/Status/Moves pages)
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Partially accessible — the multi-Pokémon slot-selection fix is confirmed working live; the Moves page has a separate, pre-existing defect for Shadow Pokémon
- Current limitation: (1) the full 15-item live-test checklist from the validation task was not completed end-to-end before the investigation moved to a discovered defect — order/no-duplicate/no-skip/hotkey-stability/non-interference items were not explicitly re-confirmed one-by-one; (2) the Moves page shows a Shadow Pokémon's post-purification moveset instead of its actual current moves (see [PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md) #6) — this is independent of the slot-selection fix and was not introduced by it
- Severity: 2 (name/HP/level/order across party members confirmed correct by the project owner directly — "much better" — the remaining gap is the Moves-page/Shadow-move issue specifically)
- Story requirement: none
- Reproduction steps (slot fix): open the summary screen with 2+ party members, use L/R to switch, listen for the correct Pokémon each time — confirmed correct 2026-07-29. Reproduction steps (Moves bug): open the Moves page for a Shadow Pokémon that hasn't been purified yet.
- Relevant save/save-state: current live save (Eevee lv.11, Teddiursa lv.11 Shadow) — not yet captured as a named milestone
- Technical findings: `_menuStatus+0x0C` (`0x804297D4`) live `Pokemon*`, `party.py`'s `slot_for_pointer()`; Moves-page bug root-caused to Shadow Pokémon storing their post-purification move in the normal `move1-4` slot the whole time (see barrier log #6) — not an offset/resolution bug in `party.py`/`LocalMoveData`
- Implementation status: Implemented (slot-selection fix); Moves-page Shadow override not implemented
- Live-test status: **Live-tested for the slot-selection fix** (project owner confirmed live, 2026-07-29). Moves-page Shadow-move display remains an open, on-hold investigation.
- Regression-test status: Regression-tested (`test_party_summary_screen.py`, 361 total passing)
- Last verified date: 2026-07-29
- Remaining work: the Shadow-move-display investigation (on hold, see backlog); no further work needed on the slot-selection fix itself
- Notes: this is now confirmed as the project's first fully-closed live-test loop under the new discovery-driven process

### On-demand party slot readout (Ctrl+1 .. Ctrl+6)
- Primary workstream: Speech and information coverage
- Discovery status: n/a — a new feature request, not a discovered gap. Project owner, 2026-08-18: *"add hotkeys ctrl+1 through 6 to read out each pokemon's name, hp, status, level, shadow gauge, etc in the party."*
- Accessibility status: **Implemented 2026-08-18, NOT yet live-tested**
- Current limitation: none known beyond the pending live test
- Severity: n/a (new feature request)
- Story requirement: none
- Reproduction steps: press `ctrl+1` through `ctrl+6` with Dolphin focused, in the overworld or in a battle
- Technical findings: `hotkeys.PartySlotSummary`, reading `party.PartyMemorySource.slots()` — the overworld roster (`Hero.partyPokemon[6]`), NOT the battle field. That is the right source for both cases: the field only ever holds the one or two Pokémon currently out, whereas "what is in slot 4" is a question about the roster, and the roster struct is the same one the game writes HP and status back into during a battle. Speaks nickname, level, current/max HP with percentage, fainted, major status, Heart Gauge (Shadow only) and held item — reusing `health.STATUS_NAMES` (moved there from `hotkeys.py` this session so the ctrl+H summary, this readout and battle targeting cannot come to disagree about what a condition byte means) and `item_database.ItemNameResolver` for the held item, falling back to the raw item ID rather than guessing a name. An empty position says *"Slot 4 is empty."* and a read failure says *"Party is not available right now."* rather than going silent — the player pressed a key, and silence is indistinguishable from a dead hotkey.
- **Ability removed from this readout 2026-08-18**, same day it was added, at the project owner's report: *"you can remove the abilities in the ctrl+1-6, it's not accurate anyways."* Taken out rather than left in with a caveat — a stated fact a player cannot trust is worse than an absent one, because they either act on it and are misled or they learn to discount the whole utterance, which costs the fields that ARE correct. **This is a removal, not a fix:** `PartySlot.ability_name` still carries the same value, `resolver.LocalAbilityData` is untouched, and the party Summary screen's Status page still speaks it — so the underlying inaccuracy is unchanged and still reaches the player by that route. See the ability-resolution entry below.
- Implementation status: Implemented — `hotkeys.py`, `profile.default_party_slot_hotkeys`, `--party-slot-hotkeys` (one comma-separated argument, validated for length and duplicate chords), wired through `phase1b_app.py`/`phase1b_lifecycle.py` on the standard reader pattern, and listed individually in the settings menu's Hotkeys reference
- Live-test status: **Not yet live-tested**
- Regression-test status: Regression-tested (`tests/test_party_slot_summary.py`, 15 tests)
- Last verified date: 2026-08-18 (tests only)
- Remaining work: live-test through NVDA, including from inside a battle

### Ability name/description resolution (reported inaccurate)
- Primary workstream: Speech and information coverage
- Discovery status: **Defect reported 2026-08-18** by the project owner — *"it's not accurate anyways"* — while asking for the ability to be dropped from the new Ctrl+1..6 readout
- Accessibility status: **Regression** — the value is resolved and spoken, but is not trusted
- Current limitation: what the companion calls a Pokémon's ability does not match the game. **Root cause found statically, 2026-08-18** — see below. Not yet fixed.
- Severity: 2 — an ability decides whether a switch-in is safe (Levitate, Flash Fire, Volt Absorb), so a wrong one is actively misleading rather than merely missing; but nothing is gated behind it, and it is now absent from the readout most likely to be used mid-battle
- Story requirement: none
- Reproduction steps: open the party Summary screen's Status page for a Pokémon whose real ability is known and compare what is spoken
- **Root cause: `party_ability_index_offset` (+0x1D) is a SLOT FLAG, not an ability index, and is being used as one.** `party.PartyMemorySource._ability` reads that byte and, when it is nonzero, passes it straight to `LocalAbilityData.resolve` as an ability ID. The community tool's own struct settles what the byte is: `XDPartyPokemon.swift` declares `kPartyPokemonAbilityIndexOffset = 29` (0x1D) and both reads and writes it as a boolean — `usesSecondAbility = readByte(...) == 1`, `write8(usesSecondAbility ? 1 : 0, ...)`. So it holds 0 or 1, meaning "use ability slot 1 or slot 2", while `resolve` expects the ability-table index that `species_ability_index` returns (Eevee's Run Away is 50). The two failures that follow:
    - **byte == 1** → `resolve(1)` returns whatever ability #1 is in the table, unrelated to the species. Wrong for every Pokémon on its second ability.
    - **byte == 0** → falls back to `species_ability_index(species, personality)`, which re-derives the slot from personality parity (`ability2 if personality % 2 == 1`). That contradicts the flag the game just stated: the flag says slot 1, so it should be ability1 unconditionally. Wrong for every odd-personality Pokémon whose flag is 0.
  Between them that is most of the party, which matches the report. The field's own comment in `profile.py` shows the intent was right — prefer the stored per-Pokémon slot over personality parity, because a randomizer can diverge from vanilla slot rules — and only the interpretation is wrong.
- Technical findings: the rest of the chain is not implicated. `LocalAbilityData.species_ability_index` (species base stats, `common.rel` pointer 88, 0x124 stride, ability bytes at +0x32/+0x33) was checked against XG directly — Pikachu resolves to 9 and 31, Static and Lightningrod, matching XG's own documentation — and `LocalAbilityData.resolve`'s index→name half was live-verified against Eevee (index 50 → "RUN AWAY" / "Makes escaping easier.", matching the project owner's OCR). The fix is therefore local to `_ability`: treat +0x1D as the slot selector and let the species table supply the ID, rather than treating the slot as the ID.
- Implementation status: Implemented but not trusted; removed from the Ctrl+1..6 readout 2026-08-18, **still spoken by `party_summary_screen.py`'s Status page**
- Live-test status: **the diagnosis above is STATIC only** — read out of the community tool's struct definitions and this project's own source, with no live memory read and no in-game comparison. It has not been confirmed against a real Pokémon.
- Regression-test status: `test_ability_layout.py` pins the derived record layout against itself, which cannot catch this — the layout is fine; the caller's interpretation of a different field is not
- Last verified date: 2026-08-18 (static diagnosis)
- Remaining work: fix `_ability` to select ability1/ability2 by the +0x1D flag; confirm against one Pokémon whose real ability is known (a Pokémon on its second ability is the discriminating case, since slot-1 Pokémon are already right by accident whenever their personality is even). Until then the Summary screen keeps speaking the wrong value — decide whether to suppress it there too in the meantime.

### Ribbons page
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Deferred
- Current limitation: Ribbon bitfield's live value didn't plausibly decode as "no ribbons yet" for a freshly-caught Pokémon
- Severity: 3
- Technical findings: see `party_summary_screen.py`'s module docstring
- Implementation status: Not implemented (page name only, "Ribbons page.")
- Remaining work: needs its own bitfield-decoding investigation once a Pokémon with known ribbons is available to test against

### Held-item name resolution
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Unblocked, not yet implemented
- Current limitation: only the raw item ID and a "no item held" case are handled; no name lookup
- Severity: 2
- Remaining work: the name-lookup dependency this was waiting on is now built and live-confirmed -- `item_database.ItemDatabase`/`ItemNameResolver` (see the "Item name resolution infrastructure" entry above). Wiring this specific screen just needs its own held-item-ID read passed through the existing resolver; no new research required.
- Notes: directly connects to the Shops workstream's item-name research, and now to the completed Bag item-name work above

### Bag menu category tabs
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested (as of 2026-07-26); **superseded in production wiring 2026-07-29** by the new Bag item list's `BagMenuReader`, which reads this exact same window+cursor signal and already announces the category as part of its own richer utterance -- wiring both would double-announce the category on every tab change.
- Technical findings: reused `PartyActionMenuReader` with explicit `menu_id`/`labels`/`index_offset`
- Implementation status: Implemented (class and tests still present; `bag_category_factory` left defined but no longer passed to `LifecycleController` in `phase1b_app.py`)
- Live-test status: Live-tested (2026-07-26, before supersession)
- Regression-test status: Regression-tested (`BagCategoryReaderTests` in `test_party_action_menu.py`)
- Last verified date: 2026-07-26
- Remaining work: none currently open for the tab row itself; confirm during the Bag item list's live walkthrough that category-tab browsing still sounds correct through the new reader instead

### Item name resolution infrastructure (shared, reusable)
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Implemented, Regression-tested
- Current limitation: none for the resolver itself; individual screens still need their own live wiring (Bag done, see below; Shops/PC Storage/Evolution Stones not yet)
- Severity: N/A (infrastructure, not a single user-facing gap)
- Technical findings (2026-07-29, per the project's formal reverse-engineering philosophy -- static analysis first, one narrow live read to confirm, no blind memory diffing): the 2026-07-26 "recycled/virtualized row slots" conclusion below was a live-diffing artifact, not the real mechanism. Static disassembly of `menuPocket.cpp` (`_getItemIDFromMenuPos`, `_getItemNameMsg`) traced the full chain: item ID -> `itemDataBiosGetPtr` (bounds-checked lookup through `item_data_index`/`item_data_prime`, 0x28-byte-stride records) -> name message ID at record `+0x10` -> `GSmsgPrint2` (the same generic message-print pipeline already used for dialogue/moves/abilities). The runtime `.sbss` pointers for `item_data_index`/`item_data_prime` proved unreliable live (a live read returned implausible values for their bounds-check counts even though the pointers themselves happened to work for one sample) -- **do not use those four live globals**. Instead, the entire item database resolves the same way the Bag content itself does: **entirely statically**, from the already-extracted `common.fsys`, via `common.rel`'s own pointer table -- REL pointer 70 (`Items`, the 0x28-byte-stride record array), 71 (`NumberOfItems`, 444 -- the real bound), 68 (`ValidItems`, the item-ID-to-dense-index remap), 69 (`TotalNumberOfItems`, 594 -- the remap table's own bound), cross-referenced from the community `Pokemon-XD-Code` tool's `XDRelIndexes.swift`/`ItemsTable.swift`/`XGBagSlots.swift` (four independent sources agreeing: disassembly, that tool's documented struct layout, that tool's REL-pointer enum, and one live read the project owner directly confirmed -- item ID 13, message ID 5013, "yes its a potion").
- Implementation status: Implemented as `battle_narrator/item_database.py` (`ItemDatabase`: item ID -> kind/name-message-ID, entirely static; `ItemNameResolver`: pairs it with the existing `entity_names.ScriptedSpeakerNameTable` for the final localized string -- no new string-decoding logic, reused as-is)
- Regression-test status: Regression-tested (`test_item_database.py`, 8 tests)
- Last verified date: 2026-07-29
- Notes: designed to be shared, not Bag-specific -- the same `ItemDatabase`/`ItemNameResolver` pair is exactly what Shops (see below), PC Storage, and the Evolution Stone menu still need once each screen's own live row-to-item-ID mapping is found; solving item *identity* once here means those screens only need their own cursor/array wiring, not another name-resolution investigation.

### Bag item list (scrolling list within a category)
- Primary workstream: Speech and information coverage
- Discovery status: Currently reachable
- Accessibility status: Live-tested, Regression-tested
- Current limitation: none currently open. Descriptions are implemented (see "Item description text" below). The trailing "Close" row's exact on-screen wording is an unconfirmed placeholder (see Notes).
- Severity: was 1 (category tabs worked; individual item selection did not narrate); resolved.
- Technical findings: the 2026-07-26 "virtualized row slots" read was a live-diffing artifact of comparing the WRONG structures (the window's own bytes never change; the real state lives in a separate global `_cursor` array, see the `pocket_cursor_table_address` entry in `profile.py`). Static disassembly of `menuPocket2Cursor` found the row-selection mechanism directly: a small fixed global array `_cursor` (`0x80445BE0`, 16 slots x 4 bytes), indexed per-category by a "cursor ID" read from `menuPocket.cpp`'s own static `TabTbl` (cross-confirmed against the already-OCR-verified category order). Each cursor slot packs two halfwords (`cursorBiosGetPos`'s x/y) that the game itself ADDS together for the true row index -- confirmed by static tracing of `menuPocket2Cursor`'s own call into `_getItemIDFromMenuPos`, not assumed. The hero's own per-category item arrays were traced through `heroItemGetItemKindToItemAryPtr`'s kind dispatch into `heroGetStatus`'s statusCode dispatch and its semantically-named `heroBiosGetItem*Ptr` accessors (ItemNormal/ItemBall/ItemSkill/ItemSeed/ExtraItem for Items/Balls/TMs/Berries/Key Items) -- each returns `hero + fixed_offset + index*4`, where `hero` is the exact same base `PartyMemorySource._hero_base` already resolves (independently cross-confirmed: the party array's own 0x30 + 6*0xC4 lands exactly on 0x4C8, where the Items array begins). One narrow live read confirmed the whole chain end-to-end against a real item, directly confirmed by the project owner ("yes its a potion"). **2026-07-29, second live session:** the project owner asked what "the cancel button" they'd seen actually was; live investigation found it isn't a separate popup or window at all -- it's simply one more selectable row immediately after the last real item in the same scrollable list (confirmed live: cursor sum == valid item count exactly when the project owner reported standing on it, and "hit A on this and it will bring me out"). The item-selection action popup (Use/Give/Toss/Cancel, opened by pressing A on a real item) was investigated as the initial guess and ruled out by the project owner directly -- that popup's own labels remain unresolved in a separate, still-open thread (checked `pocket_menu.fsys` and `menu_common.fsys`, neither has them).
- Implementation status: Implemented as `battle_narrator/bag_menu.py` (`HeroItemArraySource`: raw item-record reads with empty-slot skipping; `BagMenuModel`: pure "what's selected" read, no speech, now including the trailing close row via `is_close`; `BagMenuReader`: the speech adapter -- item/quantity/category/description on open or category change, item/quantity/description only on plain cursor movement, "No items." for empty categories, "Close." for the trailing row (combined with "No items." when the category is empty, since row 0 is then both), clean close/reopen, dedup by (category, row)). Item identity deliberately leads after the 2026-08-11 live log showed rapid tab navigation interrupting `Key Items. Miror Radar...` after 0.465 seconds and likewise replacing the TM announcement; this is a generic ordering fix, not an item/TM special case. Top-of-list/bottom-of-list boundary cues were implemented, live-tested, then explicitly removed at the project owner's request (2026-07-29) as unwanted verbosity.
- Live-test status: Live-tested (2026-07-29 -- confirmed working after one bug fix, see below; close row identified live in the same session but not yet re-tested after this pass's changes)
- Regression-test status: Regression-tested (`test_bag_menu.py`, 28 tests)
- Last verified date: 2026-08-11
- Remaining work: live-confirm the close-row announcement and the removal of boundary cues on next relaunch; resolve the close row's exact wording via OCR if the project owner can check it (current placeholder: "Close").
- Notes: the old, narrower `bag_category_factory`/`PartyActionMenuReader`-based category-tab announcement is no longer wired into the lifecycle (superseded -- `BagMenuReader` already announces the category as part of its own richer utterance, and wiring both would double-announce on every tab change). The reusable name-resolution half of this work is now its own entry above, since Shops/PC Storage/Evolution Stones need it too. **First live-test pass found only "Top of list."/"Bottom of list." being heard, never the item name** -- root cause: `BagMenuReader` called the speech emitter up to three separate times per poll (item text, then each boundary cue), each with `interrupt=True`, so each call cut off the previous one before NVDA could finish speaking it; only the last call survived. Fixed by building one combined string per poll and emitting it once. Confirmed working by the project owner immediately after the fix ("ok it's working great now"). Boundary cues were subsequently removed entirely per explicit request, independent of that bug.

### Bag item-action and numeric-input popups
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Implemented and Regression-tested; not yet live-tested
- Technical findings (2026-08-09): menu 45 is `menuPocket2ActionCtrl`. Window parameter 0 (`window+0x68`) points to its work object; work `+0` points to 12-byte action records and work `+4` is the exact row count. The draw routine passes each selected record's message ID at `+0` directly to `GSmsgPrint2`. Menus 46-49 are the four `_openNumberInputMenu`/`menuPocket2NumCtrl` variants. Their `+0x9E` cursor is a digit-column selector, not the displayed quantity. All variants read, mutate, and redraw the actual value from `Data+0x34` (`0x80438318`); `menuPocket2PrintNumMenu` decomposes that value and prints its digits through message 17008.
- Implementation status: `ProductionMenuReader` resolves menu 45 from the selected record's game-owned message ID. For menus 46-49 it speaks the shared backing number itself whenever that value changes, without embedding an invented "Quantity" label or reacting to digit-column-only movement.
- Live-test status: Not yet live-tested after narrator restart
- Regression-test status: Regression-tested (`test_phase1e_menus.py`: record-backed action labels, value changes, and digit-column deduplication)
- Last verified date: 2026-08-09
- Remaining work: live-confirm an item action popup and each reachable numeric-input variant

### Bag item-use dialogue (Miror Radar, TMs, held-item results, memos)
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Implemented and Regression-tested; pending post-fix live confirmation
- Technical findings (2026-08-11): the production log proves this is not ordinary menu 82 dialogue. After selecting `USE` on Miror Radar, the shared GSmsg task at `0x80834BA0` opened packed ID `0x00003C1F` (message 15391) from 17:12:46.109 through 17:12:56.221. The battle reader observed it but suppressed it as `not fight_common`; the ordinary dialogue reader could not claim it because no menu-82 dialogue window existed. Message 15391 belongs to `pocket_menu.fsys`'s type-5 `pocket_menu` string table and contains the real nested-location template. The same table owns TM party prompts (`Teach which POKEMON?`, `ABLE`, `NOT ABLE`), held-item result dialogue, item targets, Miror Radar response levels, and Krane Memo pages. These are GSmsg tasks backed by pocket-menu text, not battle messages or map dialogue.
- Implementation status: `messages.py` now exposes reusable `FsysMessageCatalog` plus `PocketMenuCatalog`; `BattleNarrator` accepts a separately-owned supplemental catalog and renders its tasks with the canonical live-msgvar `MessageRenderer`. Pocket-menu ownership is activated from the real menu-44 window's presence, not from item IDs or message-ID ranges, so shops retain their dedicated reader and no Miror/TM strings are embedded in code. Pocket-menu task text uses the dialogue speech class and interrupt semantics.
- Live-test status: Pre-fix failure proven from the production log; post-fix audible confirmation pending narrator restart
- Regression-test status: Regression-tested (`test_battle_messages.py`: pocket-table ownership, active-Bag routing, message 15391)
- Last verified date: 2026-08-11
- Remaining work: live-confirm Miror Radar, one TM compatibility path, and one TM result path after restart

### Eevee evolution-stone selection menu
- Primary workstream: Speech and information coverage
- Discovery status: Currently reachable
- Accessibility status: Implemented, Regression-tested. Not yet live-tested with the narrator itself (labels confirmed via the project owner's own OCR, not yet heard spoken by the narrator on this exact screen).
- Current limitation: none functionally — see caveat under Remaining work about label generalization.
- Severity: 2 (was blocking for any user without OCR; the project owner was not personally blocked)
- Technical findings (2026-07-29): new window `menu_id=175`, alongside the ordinary dialogue window (`menu_id=82`). Selection cursor confirmed live and reliable at the window's `+0x9F` offset, cycling `0-4` across the 5 confirmed options (verified via before/after memory-snapshot diffing across a full cycle through all 5). Investigated and ruled out both of the window's direct child pointers as sources of real per-option identity: `+0x28`'s chain is a 2-node sliding highlight-frame graphic (only field that varies is a screen Y-coordinate, incrementing by a fixed 26px per selection, unrelated to content); `+0x24`'s chain is a flat, unbounded sequence incrementing by exactly 1 per node (checked 10+ nodes, no relationship to the 5-item list) — a small number in this chain coincidentally resolved through the species-name string table to real-looking but entirely unrelated Pokémon names ("Hitmontop," "Smoochum," etc.); this false lead was caught and corrected before being reported as fact. Also checked the small message-task-array system used for Yes/No confirmations (`manager_root`/task array, `task_capacity=2`) — too small to hold 5 persistent option identities.
- Resolution: the project owner then directly read the real on-screen order via their own OCR: Water Stone, Thunder Stone, Fire Stone, Moon Shard, Sun Shard (indices 0-4). Implemented by reusing `PartyActionMenuReader` unchanged (same class already used for the party action popup, bag category tabs, and pause menu) with `menu_id=175`, these 5 fixed labels, and the confirmed `+0x9F` index — no new reader class needed. See `profile.py`'s `stone_selection_menu_id`/`stone_selection_labels` and `StoneSelectionMenuReaderTests` in `test_party_action_menu.py` (2 tests).
- Implementation status: Implemented
- Live-test status: Not yet live-tested (needs a narrator relaunch and a return trip to this screen)
- Regression-test status: Regression-tested
- Last verified date: 2026-07-29 (implementation + tests only)
- Remaining work: confirm live that the narrator actually speaks these 5 labels correctly on relaunch. Also unconfirmed: whether this exact order is fixed regardless of inventory/save state, or specific to this one instance — if a future playthrough shows a different order, the labels will need re-deriving rather than assumed stale.
- Notes: this is a narrower fix than the general item-name-resolution work Held-item names and Shops are still waiting on (those need a real, general resolver, now built — see "Item name resolution infrastructure" above; this stone-menu fix just hardcodes one specific, directly-confirmed 5-option list) — do not treat this as having solved the general problem. **The 2026-07-29 values 1237/1238 found near this window remain classified as disproven, coincidental data, not real name IDs.** Now that the item database's real ownership chain is understood (item ID -> `item_data_index`/`item_data_prime` -> message ID), window 175 could in principle be revisited to check whether its options are backed by real item records at all -- explicitly not attempted yet, and must not be forced into the Bag structure without static evidence the two share the same underlying mechanism.

### Move PP/type/ability detail
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Technical findings: `resolver.py`'s `LocalMoveData`/`LocalAbilityData`
- Implementation status: Implemented
- Live-test status: Live-tested
- Regression-test status: Regression-tested
- Last verified date: 2026-07-26
- Remaining work: none currently open

---

## Shops

*Investigation started 2026-07-29; core flow implemented and live-verified 2026-07-30. See `Documentation/IMPLEMENTATION_ATTRIBUTION.md`'s many 2026-07-30 shop-related entries for the full derivation chain — this section summarizes current status only.*

### Shop entry / dialog type / buying / selling flow
- Primary workstream: Speech and information coverage (also Navigation, for the shop-goods list)
- Discovery status: Currently reachable (Agate Village Pokémart, `M3_shop_1F`, room 0x86)
- Accessibility status: **Implemented and live-verified** for the greeting, Buy/Sell/Quit menu, item-grid browsing, quantity selection, and the simple one-shot clerk lines (farewell, "anything else?", errors). **Not yet implemented**: the purchase/sell confirmation Yes/No's own window structure (text rendering is ready, the live window/cursor capture isn't done).
- Severity: was Level 1 (totally silent); now resolved for everything except the final confirmation step.
- Story requirement: shops are generally available early; confirmed reachable and tested live in the current save.
- Reproduction steps: walk up to and interact with the Agate Village shopkeeper; the whole Buy/Sell/Quit flow through item selection and quantity is narrated automatically.
- Technical findings — the full mechanism, static and live:
  - The shopkeeper is discovered NOT to be a distinct interaction-table entry (no `common.rel` interaction point, no `common.rel`-tracked warp/door/PC/sign record) and initially appeared absent from the live floor-character (People) table read — investigated by extracting `M3_shop_1F.fsys` directly off the game disc (`DolphinTool.exe extract -s "M3_shop_1F.fsys"`, single-file extraction, no full disc conversion needed) and disassembling its compiled room script with `Research/ThirdParty/XDscriptTools`'s existing `XDscriptLib.ScriptCtx` parser (already cloned, never previously used this project). Found a function literally named `talk_122_shop_m` (character "shop_m" — the room's own asset bundle also contains a `shop_m_0000` character model, confirming a real modeled shopkeeper). It's a genuinely ordinary `Character::talk` interaction (walk up, press A) — the live floor-character read earlier was picking up stale/cached data for this specific room, not evidence of a structurally different (counter/trigger-object) mechanism.
  - `talk_122_shop_m` checks story-progress flags, speaks one of two greeting variants via `Character::talk` (message 38206 or 38207, from this room's own local message table — decoded directly, "Welcome! We've just added POKé BALLS/SNACKS..."), then calls `Dialogs::openPokemartMenu(level, $dialogs)` (level 12 or 5 depending on story progress) — the actual shop-menu-opening script instruction.
  - The flavor greeting (38206/38207, and the room's other ambient NPC lines at 38052/38053) needs **no new code** — `Character::talk` is ordinary field dialogue (dialogue_type=3), already narrated by the existing `dialogue.py` unconditionally.
  - `Dialogs::openPokemartMenu` opens a genuinely different, standalone window (menu_id 60 for the item grid, 61 for quantity, none of the generic window-manager cursor/alloc machinery other menus use) — this is the part that needed real new work, all now built: `menus.py`'s `shop_menu_node`/`ProductionMenuReader` (Buy/Sell/Quit + greeting text), `shop_menu.py`'s `ShopBuyMenuModel`/`Reader`, `ShopBuyQuantityModel`/`Reader`, `ShopNotificationModel`/`Reader`, and `shop_messages.py`'s `ShopMessageTable` (a real derived reader of `pocket_menu.fsys`'s own local message table, reusing `dialogue.py`'s opcode constants for LETTER_FORMAT/SPEAKER decoding).
  - The greeting text itself (message 50601, "Hello! Welcome to our POKéMON MART. How may I serve you?") and the shop's own internal notification lines (50602 "May I help you with anything else?", 50603 "We look forward to your next visit.", 50605-50608 thank-you/error/bonus messages) were found by searching every already-extracted `.fsys` file for the exact text read off-screen live, landing in `pocket_menu.fsys`'s own local table — the same file already used for item descriptions.
  - The purchase/sell confirmation templates (50604, 50609) are real, decoded, and support live substitution (`shop_messages.py` already handles `0x2D`=item name, `0x2F`=quantity, `0x4B`=price placeholders) — reconstructed to "{item}, okay. And you wanted {quantity}. That will be ${price}. Is that okay?" and "We can pay you ${price} for your merchandise. Is that okay?" respectively. What's missing is only the live window/cursor structure for this specific screen (`menuSubOpenYesNo`, cursor menu_id 53 per disassembly, parent window not yet captured).
- Implementation status: Implemented (`shop_menu.py`, `shop_messages.py`, `menus.py`'s shop-related additions) for everything except the confirmation screen.
- Live-test status: Live-tested for the greeting, Buy/Sell/Quit, item browsing, quantity selection, and notifications (the project owner walked through the real screen while these were built, catching two real bugs along the way — a mis-assumed hardcoded label order, corrected via live behavioral testing, and a hardcoded-greeting-text mistake, corrected per the project owner's explicit no-hardcoding direction). Not yet live-tested: the confirmation screen (structure not found), the Sell flow's own steps past the already-working Bag Menu item selection.
- Regression-test status: Regression-tested (`test_shop_menu.py` + `test_shop_messages.py`: 37 tests; `ShopMenuTests` in `test_phase1e_menus.py`: 6 tests — 43 total as of 2026-07-30)
- Last verified date: 2026-07-30
- Remaining work: live-capture the purchase/sell confirmation Yes/No's window structure; live-verify the Sell flow past Bag Menu item selection; the alternate greeting variants (38206/38207) need no code but haven't been separately live-heard yet (only 50601 has)
- Notes: `XGPokemart`/`XGShopTypes`/`XGShopDialogTypes` in `Pokemon-XD-Code` document 4 shop dialog types and up to 7 shop subtypes — only the plain Agate Village Pokémart has been investigated; other shop subtypes (vending machine, battle CD shop — message 50672 "Welcome to the BATTLE CD SHOP" was found in the same table, suggesting a parallel flow) are not yet confirmed to work identically.

### Item browsing / list navigation (shop)
- Primary workstream: Speech and information coverage
- Discovery status: Currently reachable
- Accessibility status: Investigating
- Current limitation: same "virtualized row slots" concern flagged for the Bag item list above — untested for the shop's own list
- Severity: unknown
- Remaining work: shares an investigation path with the Bag item list problem above; solving one may substantially inform the other
- Notes: see Bag item list entry

### Item description text
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Implemented, Regression-tested. Not yet live-tested with the narrator itself.
- Current limitation: none functionally identified for the resolution chain itself; delivery UX (spoken on every cursor move) was an explicit, deliberate choice, not a default — see Notes.
- Severity: was 2; resolved pending live test.
- Technical findings: `ItemsTable.swift` documents the item struct (`Pocket`, `Is Locked`, `Battle Item ID`, `Price`, `Coupon Price`, `Hold Item ID`, `Name ID` → `common.rel` REL pointer 70/71, `Description ID` → `pocket_menu.fsys`'s own local message table). Computed the exact field layout by summing the struct's declared field sizes in order (5 bytes of leading `.byte` fields, 3 `.short` fields, 1 byte of implicit alignment padding before the first `.word`) — Description ID lands at offset **+0x14**, immediately after Name ID's already-confirmed +0x10, and the running total lands exactly on the independently-confirmed 0x28 record stride. `pocket_menu.fsys` extracted 2026-07-29 via a one-file targeted FST-parsing extraction (`Companion/_scratch_extract_specific_files.py`, avoids a full multi-thousand-file `wit.exe` extraction) directly from a plain ISO produced by converting the project's `.rvz` with `DolphinTool.exe`; the temp ISO was deleted immediately after, only `pocket_menu.fsys` itself was kept (now checked into `_dialogue_extraction/raw/files/`). Live-verified offline (zero game interaction) by decoding item #13's real description straight out of the extracted file: "Restores the HP of a POKéMON by 20 points." — the well-known, canonical real Potion description, and a match at the *exact* same +0x14 offset independently computed from the Swift tool's field list.
- Implementation status: Implemented as `battle_narrator/item_database.py`'s `ItemDescriptionTable` (loads `pocket_menu.fsys`'s local message table, same "standalone local table" shape as `messages.FightCommonCatalog` but a different file/message-ID range) and `ItemDescriptionResolver` (pairs it with `ItemDatabase` for item ID -> description text). Wired into `bag_menu.BagMenuReader` as an optional `description_resolver` argument.
- Regression-test status: Regression-tested (5 new tests in `test_item_database.py`, 4 new tests in `test_bag_menu.py`)
- Last verified date: 2026-07-29 (implementation + tests + one offline real-item verification; not yet heard through the narrator)
- Remaining work: guided live confirmation that descriptions are actually spoken correctly during Bag browsing.
- Notes: delivery UX was explicitly decided by the project owner, not assumed — offered three options (on-demand hotkey, spoken only on open/category-change, spoken on every cursor move) and the project owner chose the most verbose: descriptions are appended to *every* Bag announcement, including plain cursor movement between items in the same category, not just when opening or switching tabs.

### Quantity adjuster
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Investigating
- Current limitation: function family identified (`menuShopNumCtrl`, `menuShopNumCursor`, `menuShopNumDrawBuyNum`, `menuShopNumDrawPriceText`) but not disassembled or live-read
- Severity: unknown, provisionally 1 (a quantity stepper with no spoken feedback is exactly the kind of "silent numeric state" this project has repeatedly found to be a real blocker elsewhere, e.g. the EXP-quantity opcode problem in battle)
- Remaining work: disassemble `menuShopNumCtrl`/`menuShopNumCursor` to find the live quantity value and its min/max bounds; determine whether it recomputes total price live (likely, given `menuShopNumDrawPriceText`)
- Notes: not yet started beyond symbol identification

### Price / money / owned-quantity display
- Primary workstream: Speech and information coverage
- Discovery status: Discovered
- Accessibility status: Investigating
- Current limitation: `Items` table's `Price` field offset computed from the documented struct list but not live-verified; "owned quantity" and "can afford" logic not yet traced
- Technical findings: `menuShopDrawMoneyText`/`DrawMoneyWaku`/`DrawHaveWaku`/`DrawHaveText1`/`DrawHaveText2` identified by symbol; not disassembled
- Remaining work: same live-verification pass as the item-description work above

---

## Map and navigation screens

### In-game Map menu
- See "Accessible map information" under Field exploration above (same feature, cross-referenced here per the requested section list).

### Authoritative warp/door/elevator data
- Primary workstream: Navigation and spatial awareness
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Current limitation: Text/PC interaction-table types not wired
- Technical findings: `authoritative_warps.py`, full 177-room `.ccd` extraction
- Implementation status: Implemented
- Live-test status: Live-tested
- Regression-test status: Regression-tested
- Last verified date: 2026-07-27
- Remaining work: none currently open beyond the deferred Text/PC types
- Notes: same underlying feature as entity-nav's warp/door/elevator categories above; listed here too since it's also fairly described as a "map/navigation screen" data source

### Gateon Port changing bridge
- Primary workstream: Story mechanics, puzzles, and special systems
- Discovery status: **Discovered** (corrected 2026-08-09; the previous "reachability not established" text was stale). Gateon Port is reached and played — the production log shows repeated `M6_out` sessions through 2026-08-08 — and `GateonBridgeReader` shipped, has tests (`test_gateon_bridge.py`), and has fired live.
- Accessibility status: **Implemented, Regression-tested; polarity CORRECTED 2026-08-18 after the first live report, still not fully live-tested** — a `bridge` entity-navigation category publishes the connections the current alignment offers, updated live from flag 968, plus the pre-existing passive announcer
- Current limitation: **connection points only** — bridge *controls* are still not entities and `_RAW_PAD_TRANSITIONS`' 16 coordinate boxes remain in `gateon_bridge.py` (unused by the new category); the live `GScolsys2` enable state is still never read, so routing is not alignment-aware and the **plain beacon (ctrl+g) should be used for bridge connections rather than the routed guide**; no alignment transition has ever been observed live (all 17 `GATEON BRIDGE` log lines report alignment 0)
- Severity: 1
- Story requirement: reached
- **Defect found and fixed 2026-08-18 (shipped inverted for nine days).** The project owner reported the category listing places the bridge was not connected to. **`enable == 1` means that direction is BLOCKED**, so from 2026-08-09 the category published exactly the closed directions in every alignment; the production log shows autowalk aimed at one (`2026-08-16 21:29:12`, "Autowalk on, Southern bridge, south connection", while segment 30 was enabled). The original "settled 12/12 vs 0/12 against two independent sources" argument was **circular**: the `ALIGNMENTS` prose is a field-for-field restatement of the same enable bits, so it agrees with whichever reading produced it. What settles it is the collision data — entries 23-31 contribute **zero** triangles to the walk model, seven of the nine are collapsed planes with no footprint, `GScolsys2SetObjEnable(1, …)` switches a blocker **on**, and `pier_def` never toggles the decks (58/59). The first and last of those were already recorded in `ENTITY_NAVIGATION_ARCHITECTURE.md` §3.7 *when the wrong conclusion was drawn from them*. Corroborating: crossing between the piers passes three gates in a line (25, 26, 29), and under the old reading **no alignment ever opened all three**, making the piers permanently uncrossable — visible in the table the whole time. The lesson for this project's method: two descriptions of one source are one source, and a live check that was on the Remaining list ("walk to one announced connection") would have caught it on day one.
- **Also added 2026-08-18:** open is necessary but not sufficient. A pier's interior-facing gate (derived from the two decks' positions) opens onto the centre passage and nothing else, so it is published only when the passage is open too; the passage is published only when at least one interior gate is open. Without that, alignment 1 announced an unreachable passage and alignments 2 and 3 each announced one dead-end gate.
- Technical findings: general flag 968 drives `M6_out`'s `pier_def`, which toggles CCD entries 23-31 — the bridge's **blocking** geometry (no walk model of their own). The state table is parsed from the extracted room script and the decks (walk entries 58/59), their "northern"/"southern" naming, the compass direction of each segment and every position are derived from `M6_out.ccd` — no Gateon coordinate is written into the companion. `M6_out` also holds five room-script interaction records (`pier_trouble` ×2, `door_hoseb`, `ev_mechakyogre_check`, `crabcrab_in_col`); `pier_trouble` is the lead for the control pads. Full record: [GATEON_BRIDGE_ACCESSIBILITY.md](GATEON_BRIDGE_ACCESSIBILITY.md)
- Regression-test status: Regression-tested (`test_bridge_connections.py`, 41 tests). `PolarityTests` now pins the collision-data facts themselves rather than the document agreement; the 12/12 comparison is kept as `test_the_retired_prose_cannot_decide_the_polarity`, labelled as the trap it was, so it is not reinstated as evidence a third time. New `DeadEndTests` cover the interior-gate and passage rules.
- Remaining work: **live-validate**, and the discriminating check is one minute — in alignment 0 you should be able to walk straight through the middle between the piers (Centre passage is listed); in alignments 2 and 3 you should not, and no interior connection is offered. Then the `GScolsys2` live read, alignment-aware routing, and bridge controls. **Separately flagged 2026-08-18:** `pathfinding.build_room_geometry` gates WALL triangles by enable state, while the long comment above that filter says it deliberately does not and records a real live failure (routing over open water in `M6_out`, 2026-08-14) caused by exactly that. The fix described there was never applied — the shipped 0.1.0 release has the same gating — so that failure is likely still reproducible. Not changed as part of the polarity fix, because it is a routing change to a live-tuned system.

---

## Battle

### Command menu (Fight/Item/Pokémon/Call) and move menu
- Primary workstream: Battle accessibility
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Technical findings: production-integrated per `BATTLE_NARRATOR_PHASE_1B.md`
- Implementation status: Implemented
- Live-test status: Live-tested (including a corrected command order after a live report)
- Regression-test status: Regression-tested
- Last verified date: 2026-07-25 (per attribution log)
- Remaining work: none currently open

### HP/status settled narration, manual HP summary hotkey
- Primary workstream: Battle accessibility
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Technical findings: `health.py`, `PHASE_1F_HEALTH_NARRATION.md`
- Implementation status: Implemented
- Live-test status: Live-tested (Earthquake + indirect poison regression both confirmed)
- Regression-test status: Regression-tested
- Last verified date: 2026-07-25
- Remaining work: none currently open; this is the project's core regression-queue anchor (see [ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md))
- Notes: **2026-07-30 fix** — fainting previously spoke only "X fainted!" with no HP-loss percentage, because `FaintCoordinator` (which races ahead of the settled HP percentage specifically so fainting is announced promptly) discarded the percentage sentence in favor of a plain "fainted!" string. Now composes the same "X lost N percent. Zero percent remaining." sentence used for any other damage event, with "X fainted!" appended, across all three of its resolution paths (settled-event match, fast current-battler match using the tracker's own not-yet-advanced baseline, and the unmatched-after-grace-period fallback). See `IMPLEMENTATION_ATTRIBUTION.md`'s 2026-07-30 entry for the full trace.

### Stat-stage change narration (self and opponent-directed)
- Primary workstream: Battle accessibility
- Discovery status: Discovered
- Accessibility status: Live-tested for self-directed (attacker's own stat, e.g. Swords Dance); **opponent-directed was silently broken until 2026-07-30**
- Current limitation: none remaining for the 4 known message IDs (20243/20244/20246/20247); 20244 (target stat rise) has never been observed live yet, only inferred symmetric to 20247
- Severity: 2 (was silently dropping real battle information — a move lowering the opponent's stat gave no feedback at all)
- Story requirement: none
- Reproduction steps: use a stat-affecting move on the opponent (e.g. Growl, Leer) or on self (e.g. Swords Dance) in battle
- Technical findings: `narrator.py`'s `VERIFIED_OPCODES` had a single shared opcode-safety entry for all 4 `STAT_IDS`, `{0x00, 0x0D, 0x0E, 0x0F, 0x41}` — but opponent-directed messages (20244/20247) actually carry opcode `0x10` ("Pokemon 16"/tsuika target), not `0x0F` ("Pokemon 15"/attacker), confirmed via `_dialogue_extraction_tool.py`'s `OPCODE_NAMES` table and every real live occurrence of message 20247 in `logs/battle_narrator_phase1b.log` across 5 separate play sessions (2026-07-25 through 2026-07-29) — always suppressed as "unverified controls," 100% of the time, never once spoken. The resolution logic (`sample()`'s `tsuika_mons`/`attack_mons` split) was already correct; only the opcode gate was wrong.
- Implementation status: Implemented (`resolver.py`'s new `STAT_ACTOR_IDS`/`STAT_TARGET_IDS` split, `narrator.py`'s `VERIFIED_OPCODES` now has separate entries per direction)
- Live-test status: Not yet live-tested against the real game with the fix (the bug itself was diagnosed entirely from historical log evidence); regression-tested against a reconstruction of the exact real opcode sequence
- Regression-test status: Regression-tested (`test_battle_narrator.py`, including a regression test asserting `0x0F` is no longer accepted for 20247)
- Last verified date: 2026-07-30
- Remaining work: live-confirm an opponent-directed stat-lowering move is now spoken correctly

### Full-turn paralysis ("X is paralyzed! It can't move!") and Shadow Pokémon Reverse Mode trigger
- Primary workstream: Battle accessibility (Reverse Mode also touches Shadow Pokémon systems)
- Discovery status: Discovered (both confirmed live via `logs/battle_narrator_phase1b.log`, never spoken before this fix)
- Accessibility status: Implemented — not yet live-tested
- Technical findings: message IDs 20050 (full-turn paralysis) and 20450 (Reverse Mode) both use only already-proven-safe opcodes (`0x0F` attacker nickname, `0x00` New Line) but were never added to `VERIFIED_OPCODES`/the mode dispatch, so every real occurrence was silently suppressed as "unsupported template."
- Implementation status: Implemented (`resolver.py`'s `ACTOR_SENTENCE_TEMPLATES`, generalizing the existing poison/fainted "actor" mode into a lookup table)
- Live-test status: Not yet live-tested
- Regression-test status: Regression-tested (`test_battle_narrator.py`)
- Last verified date: 2026-07-30
- Remaining work: live-confirm at the next full-turn-paralysis or Reverse Mode trigger

### Remaining unsupported battle dialogue boxes (confirmed real, not yet implemented)
- Primary workstream: Battle accessibility
- Discovery status: Discovered — all confirmed as real, repeatedly-encountered, currently-silent messages via `logs/battle_narrator_phase1b.log` (not speculative)
- Accessibility status: Not implemented
- Current limitation: each needs at least one currently-unmapped opcode's live memory source resolved before it can be safely narrated (per the project's no-hardcoding/no-guessing standard) — none has been implemented, to avoid risking wrong narration from a guessed field
- Severity: 2 each (real, silently-dropped battle information)
- Technical findings (from live log evidence, template + raw opcode list):
  - **20070** — `"[opcode_0x20]'s\n[Move 40] raised DEFENSE a little!"`, opcodes `[0x20, 0x00, 0x28]`. A specific-move flavor line (a move whose effect is always "raise Defense a little," e.g. Harden-style). `Move 40` (`0x28`) is already proven (used by the move-used message); `0x20` is unmapped and does not fit the known "Pokemon 15-18" (`0x0F`-`0x12`) or "Ability 26-29" (`0x1A`-`0x1D`) opcode blocks, so its meaning needs independent disassembly work before use.
  - **20374** / **20377** — `"[opcode_0x1E]'s [Item 41]\nrestored health!"` / `"...restored its HP a little!"`, opcodes `[0x1E, 0x29, 0x00]`. In-battle item-heal messages (e.g. held Berries). `Item 41` (`0x29`) is a known opcode name but has never been resolved to an actual item ID by this project; `0x1E` (the item's holder) is unmapped.
  - **20484** — a multi-line Krane cutscene line ("The AURA READER is responding! That's a SHADOW POKéMON!") triggered on first encountering a Shadow Pokémon; opcodes include `0x2B` ("Player Field 43," a known name but unresolved live source) and one unmapped opcode `0x6E`. Lower priority — a rare, one-time story event rather than a recurring mechanic.
- Remaining work: resolve opcodes `0x20`, `0x1E`, `0x6E` (and `Player Field 43`'s live source) via disassembly of the message-substitution code before implementing any of these four
- Notes: this list is a byproduct of investigating the two bugs above by grepping the narrator's own historical log for every distinct `SUPPRESSED`/message-ID pattern rather than guessing at what might be missing — it is a lower bound on real gaps, not an exhaustive audit of every possible battle message

### Trainer challenge ("X would like to battle!")
- Primary workstream: Battle accessibility
- Discovery status: Discovered — confirmed real via `logs/battle_narrator_phase1b.log`: message 20301 has appeared in every trainer battle since 2026-07-25 (most recently the morning of 2026-07-30), always suppressed, never once spoken
- Accessibility status: Implemented (partial) — not yet live-tested
- Current limitation: the opposing trainer's class/name (opcodes `0x22`/`0x23`, "Foe Tr Class"/"Foe Tr Name") has no known live memory source — same unresolved gap already documented for the victory message's opponent name. Speaks a generic "A trainer wants to battle!" acknowledgment instead of either guessing at the name or staying silent, matching the precedent already set by the victory message's own partial fixed sentence.
- Severity: 2 (a battle-initiating event with zero narration until now)
- Technical findings: `resolver.py`'s new `PARTIAL_TRAINER_SENTENCES`/`PARTIAL_TRAINER_IDS`, `narrator.py`'s new `"partial_trainer"` mode (same shape as `"fixed"` — no live resolver call needed — but kept as a separate mode/dict since, unlike `FIXED_SENTENCES`, this message's opcodes do carry real data that's deliberately not being read, which would misrepresent `FIXED_SENTENCES`' own "no opcode carries data" invariant if merged in)
- Implementation status: Implemented
- Live-test status: Not yet live-tested
- Regression-test status: Regression-tested (`test_trainer_challenge_speaks_generic_partial_sentence`)
- Last verified date: 2026-07-30
- Remaining work: live-confirm at the next trainer battle; resolving the actual opponent trainer name (rather than the generic fallback) needs the same live GDB trace already documented as outstanding for the victory message

### Battle message narration, generally (2026-08-06, Phases 1-3)
- Primary workstream: Battle accessibility
- Discovery status: Discovered
- Accessibility status: **Implemented generically — awaiting live validation**
- Technical findings: battle messages no longer have per-ID English sentences
  or a per-ID opcode allow-list. `battle_narrator/battle_opcodes.py` holds the
  shipped `msgctrlcode` dispatch table (all 111 entries, dumped from the
  original `main.dol`), covering all 47 opcodes any of the 1,161 shipped
  `fight_common` messages uses; `message_render.py` renders each message the
  way the engine would, reading the same msgvar globals the same handlers
  read. ~51 retyped sentences and ~60 allow-list entries retired. Formerly
  "unresolvable" sources are all resolved: trainer class/name (0x22/0x23),
  the quantity opcode (`_Digit`), the speaker opcode (0x59 → `_Npc` → a name
  message ID), the send-out globals, the blocked-Pokémon global (0x11) and the
  appointed-Pokémon global (0x1E).
- Safety: a message speaks only if every opcode is registered, every argument
  resolves, the text is nonempty and it carries no double-encoding signature.
  Otherwise the **whole** message is silent and the exact opcode is logged
  once. No partial sentence is ever emitted.
- Live-test status: **Not live-tested.** Requires a narrator restart.
- Regression-test status: `tests/test_battle_messages.py` (90 tests) built on
  each message's own shipped GSchar bytes.
- Remaining work: smoke-test a short battle one event at a time.
- Notes: two user-visible faults were found in the production log rather than
  by inspection — a battle event self-interrupting the previous one (the
  reported "h! A Shadow Pokémon!", fixed in `SpeechCoordinator`) and stat
  changes being spoken twice by two independent readers (`narrate_stat_stages`
  now defaults off).

### Pokémon sent out ("Go!" / enemy send-out)
- Primary workstream: Battle accessibility
- Discovery status: Discovered
- Accessibility status: Player's own single send-out (20312) Implemented — **still reported not speaking as of 2026-07-30, cause not yet found**; opponent's single send-out (20304) newly Implemented 2026-07-30; both double-battle variants (20313/20305) Not implemented
- Current limitation: the project owner reported 2026-07-30 that send-outs still aren't being read after the 2026-07-28 implementation and a narrator restart. Re-checked `narrator.py`'s opcode gate, mode dispatch, and `sample()`/`compose()` for 20312 line by line and found no bug — the logic matches the already-passing unit test exactly (`test_send_out_speaks_go_with_actor_name`). No log evidence exists from after the 2026-07-28 implementation (the only 3 historical occurrences of message 20312 all predate it), so this could be a genuine live-only bug (e.g. `attack_mons` transiently invalid at the exact moment a fresh send-out message opens, unlike after a move has already been used) that static review can't surface — needs a live occurrence with fresh log output to diagnose, not a guess.
- Severity: 2
- Technical findings: `GO_SEND_OUT_ID` (20312, opcode `0x14`) covers only the player's own single-Pokemon send-out. Live log evidence found 3 more real, related messages, none previously handled: 20304 (opponent's single send-out, "sent out `<Pokemon>`!" — same `0x16`/`tsuika_mons` mechanism already proven for catch/appear messages, opponent trainer class/name left unresolved same as the victory-message gap; **fixed 2026-07-30**, added to `CATCH_TARGET_TEMPLATES`), 20313 (player double-battle send-out, "Go! X and Y!," needs a second live global for the partner Pokemon — not yet resolved) and 20305 (opponent double-battle send-out, needs opcode `0x17` — not yet resolved). 20305/20313's mere existence in the log is itself the first confirmed evidence this playthrough has had at least one double battle (2026-07-25) — relevant to the still-open "targeting" investigation.
- Implementation status: Implemented for 20312 (unconfirmed live) and 20304 (new); not implemented for 20313/20305
- Live-test status: Not yet live-tested for any of the four
- Regression-test status: Regression-tested (`test_send_out_speaks_go_with_actor_name`, new `test_foe_single_send_out_speaks_pokemon_name_only`)
- Last verified date: 2026-07-30
- Remaining work: live-confirm 20312 with fresh log output to find why it's reportedly still silent; live-confirm 20304's new fix; resolve the second-Pokemon opcodes (partner global, `0x17`) before attempting 20313/20305

- **2026-08-06 update — root-caused and rebuilt (Phase 2).** Everything above
  this line is superseded. All four send-out messages were reading the wrong
  source. The right one was never among the four globals investigated on
  2026-07-30: dumping the shipped `msgctrlcode` dispatch table
  (`.data:0x80404710`) out of the original `main.dol` shows opcodes
  0x14/0x15/0x16/0x17 dispatch to `msgctrlMyMons`/`msgctrlMyMons2`/
  `msgctrlEnemyMons`/`msgctrlEnemyMons2`, whose globals (`0x804EB210`–
  `0x804EB21C`) hold **GSchar text pointers**, not `FightOutPokemon*`. That is
  why reading them as pointers only ever found unaligned garbage. `20312`
  read `_ATTACK_MONS` (333 logged `invalid address 0x00000000` rejections)
  and `20304` read `_TSUIKA_MONS` (211 more); `20313`/`20305` fell back to
  `trainer_party_names()`, i.e. the trainer's first N **party slots**, which
  is party order and never send-out order — the direct cause of the
  "NPC sends out the wrong Pokémon" and Baton-Pass-ordering reports.
  All four now share one mode that reads the message's own opcode globals,
  **in the template's own opcode order** (20313 prints 0x15 then 0x14, 20305
  prints 0x16 then 0x17; the pair a name lands in is inverted between the
  player's side and the foe's, so position cannot be assumed). Trainer
  class/name now come from opcodes 0x22/0x23 (`_TRAINER_TYPE`/
  `_TRAINER_NAME`), closing the "opponent name needs a GDB trace" gap.
  Duplicate species are disambiguated by `battle_identity.IdentityLabeller`.
  Implementation status: Implemented for all four. Live-test status: **not
  yet live-tested** — needs a narrator restart. Regression-test status:
  `tests/test_battle_identity.py` (50 tests) plus rewritten send-out tests in
  `tests/test_battle_narrator.py`. See
  [BATTLE_IDENTITY_MODEL.md](BATTLE_IDENTITY_MODEL.md).

### Level up
- Primary workstream: Battle accessibility
- Discovery status: Discovered
- Accessibility status: Implemented and live-tested (2026-07-30, after a live-caught bug fix)
- Technical findings: `LevelSample`/`level_sample()`, reads level directly from the verified party struct rather than trusting the message's own ambiguous "Quantity" opcode. **Bug found and fixed 2026-07-30**: a real level-up spoke "Jolteon grew to level 0!" — `level_sample()` read the level at `fight_pokemon + pokemon_level_offset` directly, but `fight_pokemon` is the FightPokemon *wrapper*, not the Pokemon struct itself; the real data is embedded at `+fight_pokemon_embedded_offset` (0x04), the same indirection `health.py`'s `battlers()` already applies. Fixed to match. This method had zero direct unit test coverage before this fix (every existing narrator test used a `FakeResolver` stub bypassing the real offset math entirely) — added `tests/test_resolver.py` with real synthetic-memory coverage for `VerifiedResolver` to prevent this class of bug going undetected again.
- Implementation status: Implemented
- Live-test status: Live-tested — confirmed broken, then confirmed fixed via the same live event
- Regression-test status: Regression-tested (`test_resolver.py`, new file)
- Last verified date: 2026-07-30
- Remaining work: none currently open

- **2026-08-06 update — wrong recipient, root-caused (Phase 2).** The project
  owner reported the level-up announcement naming the wrong Pokémon, "as if
  switched". Confirmed by inspection: `level_sample()` read `_ATTACK_MONS`,
  the Pokémon that *attacked*. That is only the same Pokémon when exactly
  one party member is earning experience; in a double battle where both
  level, the two announcements name each other's Pokémon. The authoritative
  recipient is `get_exp_fight_pokemon_ptr` (`.sbss:0x804EB964`), which
  `WS_GET_EXP` (`fightSeqBasis.s`) sets immediately before applying the
  level-up and clears at the end of that recipient's loop iteration — so it
  is non-null for exactly the span in which 20003/20006 are displayed, per
  recipient. Switched to it; it now **raises** rather than falling back to
  `_ATTACK_MONS`, because a silent fallback to a known-wrong source would
  reintroduce the bug undetectably. `LevelSample.actor` became
  `.recipient` (a canonical `BattlerIdentity`), which also resolves for a
  recipient that is not on the field at all. Live-test status: **not yet
  live-tested**. Stat gains on level-up remain unimplemented — the
  authoritative old/new buffers are `old_menu_lvup_status` (`.bss:0x804B0A20`)
  and `fightPokemonToMenuLvupStatus`, scheduled for Phase 4.

### Experience (EXP) point count
- Primary workstream: Battle accessibility
- Discovery status: Discovered
- Accessibility status: Blocked technically
- Current limitation: the message's "Quantity" opcode's live source address is unresolved; a promising window-field write turned out to be a generic, non-EXP-specific engine utility
- Severity: 2 (level-up itself is covered; the exact point delta is not)
- Remaining work: needs a live GDB write-watchpoint trace to find the real source address
- Notes: money-earned (`20023`/`20119`) shares the identical blocker
- **2026-08-06 update — unblocked, no GDB needed.** The "Quantity" opcode is
  0x2F, and the `msgctrlcode` dispatch table shows it calls `msgctrlDigit`,
  which formats `_Digit` at `0x804EB27C`. That address is already in
  `profile.py` as `fight_message_digit_address` and is already read
  successfully for message 20026 ("Hit N times!") — so the source was
  never actually missing, only unconnected. Money uses opcode 0x4B →
  `msgctrlMoney` → `_Money` at `0x804EB2A8`, same mechanism with
  thousands-grouping. Both are wired up in Phase 3 with the rest of the
  generic message renderer.

### Money earned
- Primary workstream: Battle accessibility
- Discovery status: Discovered
- Accessibility status: Blocked technically
- Current limitation: same "Quantity" opcode blocker as EXP
- Severity: 2
- Remaining work: same as EXP above

### Victory / defeat
- Primary workstream: Battle accessibility
- Discovery status: Discovered
- Accessibility status: Partially accessible (defeat fully implemented and live-tested; victory implemented as a partial fixed sentence without the opponent's name)
- Current limitation: opponent trainer name/class substitution in the victory message has no known live memory source
- Severity: 2 (a partial, correct announcement exists either way)
- Implementation status: Implemented (partial for victory)
- Live-test status: Defeat is live-tested (pre-existing); victory's new fixed-sentence version is not yet live-tested
- Regression-test status: Regression-tested
- Last verified date: 2026-07-28
- Remaining work: opponent-name resolution needs a live GDB trace; live-confirm the victory fixed sentence in the meantime

### Shadow/catch flavor text and catch-target messages
- Primary workstream: Battle accessibility (also Shadow Pokémon systems)
- Discovery status: Discovered
- Accessibility status: Implemented — not yet live-tested
- Technical findings: 11 fixed flavor lines with only already-proven-safe structural opcodes; catch-target templates use the already-proven `tsuika_mons` target-name convention
- Implementation status: Implemented
- Live-test status: Not yet live-tested (needs an actual shadow-catch encounter)
- Regression-test status: Regression-tested
- Last verified date: 2026-07-28
- Remaining work: live-confirm at the next shadow-Pokémon catch attempt

### Double battles generally
- Primary workstream: Battle accessibility
- Discovery status: **Confirmed the project owner's main focus (2026-07-30, explicit statement)** — no longer an open discovery question. This game's battles are commonly two-Pokemon-per-side, not the single-battle default this project's battle narration was originally built and tested against.
- Accessibility status: Partially accessible — see the three sub-entries immediately below (send-out narration, target selection, remaining-opponent-count) for the specific gaps
- Severity: 1 (a structural gap affecting a large fraction of this game's actual battles, not an edge case)
- Remaining work: see sub-entries

### Double-battle send-out narration ("Go! X and Y!" / opponent sends out two)
- Primary workstream: Battle accessibility
- Discovery status: Discovered — confirmed real and recurring via `logs/battle_narrator_phase1b.log` (first seen 2026-07-25, recurred 2026-07-29 and 2026-07-30)
- Accessibility status: Not implemented
- Current limitation: message 20313 (player sends out two) and 20305 (opponent sends out two) each need a SECOND Pokemon identity resolved, beyond the single `attack_mons`/`tsuika_mons` globals already used for every single-battle message. Four "current battler" scratch globals exist (`_ATTACK_MONS`/`_DEFENCE_MONS`/`_CLIENT_MONS`/`_TSUIKA_MONS`, all four confirmed in xd-decomp's `config/GXXE01/symbols.txt`, 4 bytes apart at `0x804EB1FC`-`0x804EB208`) but only 2 have ever been used by this project; which of the other 2 (`_DEFENCE_MONS`/`_CLIENT_MONS`) holds which side's second Pokemon during these specific messages has not been confirmed live yet — all 4 read as null outside the brief window a relevant message is actually open, so a one-shot script can't reliably catch the moment.
- Severity: 2
- Technical findings: added temporary diagnostic logging (`narrator.py`'s `_debug_dump_battler_globals`) that fires whenever any send-out or faint message opens (20301/20304/20305/20312/20313/20021/20022, regardless of suppression) and logs all 4 globals' resolved nicknames to the narrator's own log — passively captures the data from the project owner's next double-battle send-out without needing a special request.
- Implementation status: Not implemented (diagnostic-only so far)
- Remaining work: restart the narrator, wait for the project owner's next double-battle send-out or faint, then read the log's `DOUBLE_BATTLE_DEBUG` lines to determine which global is which; implement and remove the temporary diagnostic once confirmed

### Pokémon targeting (double battles)
- Primary workstream: Battle accessibility
- Discovery status: Discovered and live-confirmed (2026-07-30) — real menu ID and cursor mechanism identified directly from a live target-selection screen, superseding this entry's earlier, partially-wrong hypothesis
- Accessibility status: Not implemented — mechanism confirmed, not yet wired into narration
- Current limitation: nothing spoken for this screen yet
- Severity: 1-2 (a battle-blocking decision point if it requires a manual cursor choice a blind player can't otherwise make — live-confirmed this session that it DOES block input, "controls froze," waiting for a choice)
- Technical findings: **Correction to the same day's earlier note below** — `menuFightOpenTarget`'s 4 menu IDs (`0x9F`/`0xA0`/`0xA2`/`0xA3`) belong to the separate "VS Quick Battle" C-stick control scheme (`profile.py`'s pre-existing `vs_button_parent_id`/`vs_target_menu_id` fields, whose own comment already says "VS Quick Battle uses direct C-stick move buttons and D-pad targets") — a different, less-common control scheme from the one the project owner actually uses. Widening those IDs (done this session, see below) was a real, disassembly-grounded fix for that scheme but did NOT explain what the project owner experienced. Root-caused the real case live instead: while the project owner was genuinely frozen on a target screen (confirmed by direct question, not assumed), read the live window list (`WindowListWalker`) and found no evidence of any VS-scheme window — instead found menu ID **92**, previously only ever logged as `UNSUPPORTED MENU id=92; silent` and never otherwise handled. Confirmed its cursor value (read via the exact same already-proven generic mechanism every other simple menu in this project already uses — `window+0x9C` base / `window+0x9E` offset, `profile.py`'s `window_cursor_base_offset`/`window_cursor_offset`, `menus.py`'s `_cursor()` helper) changes in direct response to the project owner moving the on-screen target cursor (captured live: value 2 → 0 after reversing direction once), while every other window's cursor field stayed fixed. One open question before implementation: the value changed by 2 (not 1) on a single reversed press, suggesting this may be a 4-position spatial grid (both allies' and both opponents' field positions, since some moves can legally target an ally) rather than a simple 2-way left/right choice between the two opponents — needs one more live sample moving the cursor by exactly one step in each of the 4 directions to confirm the full mapping before implementing.
- Implementation status: **Names Implemented (menu 92 via `StoryTargetFocus`, VS scheme via `VsTargetPanel`); HP/level/status added 2026-08-18, NOT yet live-tested.** A bare name is not enough to choose between two foes when you cannot see their HP bars, and the information otherwise arrives only after the attack has landed. Both target readers now append a clause from the new `battle_targets.py`: `Target: Opponent Wingull, level 14, 26 of 26 HP, 100 percent, paralyzed.`
- Technical findings (2026-08-18 addition): the clause is assembled from **two sources, each used only for what it can prove.** HP comes from the status panel the game is displaying — both readers already dereference that window's allocation to read the nickname, and max/current HP sit in the same 0x1C record at `+0x18`/`+0x1A`, the offsets `health.HealthMemorySource.windows()` already reads and treats as signed 16-bit. That needs no matching at all: it is by construction the HP of the panel the cursor is on. Level and major status are NOT in that allocation, so they are matched by nickname against the active battler array (`battle_targets.TargetFactsSource`) — the one place a wrong answer is possible, so a duplicated nickname yields nothing for either battler rather than a coin flip, matching `BattleIdentityResolver.send_out_event`'s existing policy. The HP half is unaffected by that, because it never depended on the name. `TargetFactsSource` is deliberately per-slot tolerant where `HealthMemorySource.battlers()` is all-or-nothing: a health *tracker* that silently skipped a battler would miss damage, but here the worst case is one target described a little less fully. Every part is independently optional — an unreadable or implausible field is left out of the sentence rather than defaulted, because "level 0" or "0 of 0 HP" spoken confidently is worse than a shorter sentence.
- Regression-test status: `tests/test_battle_targets.py` (new, 19 tests); `tests/test_phase1e_menus.py` extended — its story-target fixture now populates live battler level/status so the nickname-matched half is exercised, and a new VS test covers HP read from each target's own panel including a fainted target
- Remaining work: **live-test through NVDA.** Also still open: the full cursor-value-to-field-position mapping question below is now moot for narration (menu 92 is resolved through its own selected-target-item record, not the cursor), but a double battle where two foes share a nickname would silently lose level/status — correct by policy, unverified in practice.
- Notes: also confirms this game does allow a real double-battle target *choice* (not auto-resolved), directly answering the open question in this entry's own earlier revision

### Opponent's remaining Pokémon count (requested hotkey)
- Primary workstream: Battle accessibility
- Discovery status: Discovered — full struct chain traced via static disassembly and live-confirmed against two real trainers (2026-07-30)
- Accessibility status: Investigating — one open question before implementation
- Current limitation: the struct chain is confirmed exact (`FightFloor` → 2×`FightSide` → up to 2×`FightTrainer` per side → 6×`FightPokemon` per trainer), and live-reading it correctly reproduced the project owner's own two active Pokémon (side 0) and the opponent's three (side 1), cross-checked against `health.py`'s independently-proven battler list. What's still unconfirmed: whether a not-yet-sent-out Pokemon's HP field reads its real party HP (letting "still has HP" reliably mean "hasn't fainted yet, may or may not have been sent out") or whether it reads 0 by default until first use (which would make raw HP alone unable to distinguish "already fainted" from "not yet seen"). The one battle checked so far had every opposing Pokemon already sent out at least once (confirmed directly by the project owner), so it couldn't resolve this either way.
- Severity: n/a (new feature request, not a coverage gap)
- Story requirement: none
- Technical findings: `fightFloor_GetFightSidePtr(floor, side) = floor + side*0x6EF0 + 0x14` (`fightFloorDB.s`); `fightSide_GetFightTrainerPtr(side, trainer) = side + trainer*0x3744 + 0x64` (`fightSideDB.s`); `fightTrainer_GetFightPokemonPtr(trainer, i) = trainer + i*0x300 + 0x97C` (`fightTrainerDB.s`), each `FightPokemon` sharing the same embedded-Pokemon-struct layout already proven by `health.py` (nickname at `+0x52`, HP/max-HP/condition at the usual embedded offsets). `fight_floor_root` (already an existing, proven `profile.py` field) is the base address — no new global needed. Also found `fightTrainerGetHikaeFightPokemonNum` (`fightTrainer.s`), a real in-game function computing a "reserve Pokemon" count for AI switch-decision purposes, but its logic is entangled with switch-eligibility rules (not simply "how many are alive") and was not pursued further once the simpler raw-struct-read approach proved sufficient.
- Implementation status: **Implemented as a battle-START announcement 2026-08-18 (`battle_start.py`), NOT yet live-tested.** Scope change from this entry's earlier plan, at the project owner's 2026-08-18 request: *"when starting a battle, say how many pokemon the opponent has"* — a passive announcement once per battle, not the on-demand hotkey previously planned. The two are not in conflict; the hotkey remains available to add if wanted.
- Technical findings (2026-08-18 addition): **the HP ambiguity this entry raised is sidestepped rather than resolved.** A cell is counted on IDENTITY evidence only — species set, level 1-100, nickname not blank — and HP is deliberately not consulted. At battle start, which is exactly when this fires, most of the opponent's party has never been sent out, so if the unresolved "does an unsent Pokemon's HP read 0" question turns out to be yes, an HP-gated count would announce "1 Pokémon" for a full team of six. Species, level and nickname are copied from the persistent party at battle setup and do not depend on having been sent out. Battle start itself is detected from the field rather than from a message, because no single message opens every kind of battle: the announcement fires when a resolved battler is standing on the active array, requires the count to repeat across `identity_stable_samples` polls, and re-arms only after the field has been empty for 1.5s so a replacement gap is not mistaken for a new battle.
- **Open, and the one thing that still needs a live check:** nothing establishes what an UNUSED cell of a short party holds — whether slots 3-5 of a three-Pokémon trainer are zeroed at setup or retain a previous battle's data. Plausible stale data would be OVER-counted. `OpponentPartySource.counts` logs every accepted cell with its species, level and nickname (`OPPONENT PARTY side=1 trainer=0 count=3 cells=...`), so **one real battle against a trainer whose party size is known settles it from the log alone.**
- Regression-test status: `tests/test_battle_start.py` (new, 18 tests) covering side isolation, both foe trainers, implausible cells, unreadable cells, the no-HP-yet case, stability, the replacement-gap guard and re-arming
- Remaining work: run one battle and read the `OPPONENT PARTY` log line against a known opponent party size to confirm the count is exact; live-test the announcement through NVDA

---

## Shadow Pokémon systems

### Shadow status indicator, Shadow gauge ("Heart Gauge") reading, Hyper mode
- Primary workstream: Battle accessibility (also Shadow Pokémon systems as a cross-cutting concern)
- Discovery status: Reached; Heart Gauge's live data chain found and read 2026-07-30 at the project owner's explicit request, following directly from the same day's Shadow-move-display fix
- Accessibility status: **Heart Gauge sub-feature Implemented and live-verified (2026-07-30)** — Shadow status indicator and Hyper mode remain open (see Notes/Remaining work).
- Current limitation: Shadow status indicator (a general "is this individual currently Shadow" announcement outside the Status page) and Hyper mode are not yet implemented.
- Severity: provisionally 0-1, since shadow-move risk management and purification progress are core, frequent mechanics this game is built around
- Story requirement: none — already reachable, confirmed present in the current save
- Technical findings: `Pokemon::getDarkPointDirect() const` (`pokemonStatusPokemon.s`) → `Pokemon::getDarkPokemon() const` (resolves via the same `pokemon+0xBA` dark-pokemon-ID field the Shadow-move fix already uses) → `DarkPokemon::getDarkPointDirect() const`, a plain `s32` read at `+0x24` of a *third*, previously-untouched runtime array: `savedataBiosGetDarkpokemonPtr` (`savedataBios.s`) = `savedata_base + 0xE380` (`savedata_base` via the already-proven `savedata_pointer_address`), stride `0x48`, confirmed by reading `savedataGetStatus`'s actual jump table data directly (`.rodata "@2184"` in `savedata.s`) rather than inferring index-to-case mapping from code layout order, after an initial attempt at inferring it that way risked a real off-by-several-indices mistake — index `15` (`0xF`, the value `darkPokemonGetDarkPokemon` passes) landing exactly on `savedataBiosGetDarkpokemonPtr` in the raw table data is what confirmed it, not the earlier code-order guess. The `InitDarkPoint` denominator (`_deckDarkPokemon[dark_id]+0x8`) was already confirmed as part of the Shadow-move fix. Note: `darkPokemonBiosGetDarkPoint` (a similarly-named function on the *other*, `_deckDarkPokemon`-indexed struct) is a red herring for this purpose — it's a plain alias for `darkPokemonBiosGetInitDarkPoint`, i.e. the same static max value, not a live current reading; the real live value only exists on this third, save-relative structure. **Direction confirmed directly by the project owner**: Teddiursa's live reading of `0`/`3000` (fully drained) matches their own independent knowledge that, after extensive walking (steps are a known real accumulator toward purification — see `darkPokemonBiosGetSteps`/`SetSteps`, `darkPokemonBios.s`), it should currently be ready to have its heart purified — confirming `0` = fully open, not the reverse.
- Implementation status: **Heart Gauge Implemented (2026-07-30)**, per the project owner's explicit "both" answer to how it should be exposed: (1) `party.py`'s `_dark_status()` computes `heart_gauge_percent` (`round_percent(max_point - current, max_point)`) alongside the existing Shadow-move override, exposed on `PartySlot`; `party_summary_screen.py`'s Status page speaks "Heart Gauge: fully open, ready to purify." or "Heart Gauge: N percent open." whenever present. (2) A dedicated `HeartGaugeSummary` hotkey class (`hotkeys.py`, default `ctrl+s` since 2026-08-16, previously `ctrl+j`) speaks the same for every currently-Shadow owned Pokémon on demand. Wired through `profile.py`/`phase1b_app.py`/`phase1b_lifecycle.py` following the project's standard hotkey-reader pattern.
- Live-test status: Live-tested for the underlying value/direction (2026-07-30, Teddiursa). The Summary-screen and hotkey narration code paths themselves are regression-tested but not yet separately live-tested end-to-end through NVDA — pending the project owner's next play session.
- Regression-test status: Regression-tested — `test_heart_gauge_summary.py` (new, 8 tests), 3 new tests in `test_party_summary_screen.py`, `test_party.py` coverage for `heart_gauge_percent`. Full suite 495 passing.
- Last verified date: 2026-07-30
- Remaining work: live-verify the Summary-screen and hotkey narration through NVDA in an actual play session; Shadow status indicator and Hyper mode remain unimplemented — `darkPokemonBiosGetHokakuritu`/`pokemonGetDarkPokemonHyperJoutaiKakuritu` are the concrete leads for Hyper mode specifically.
- Notes: `darkPokemonBiosGetHokakuritu`/`pokemonGetDarkPokemonHyperJoutaiKakuritu` ("Hyper Joutai" = "Hyper state/mode") remain real, named, not-yet-read functions directly relevant to Hyper mode specifically — still open

### Shadow move display (summary/move-list shows post-purification moveset instead of current move)
- Primary workstream: Battle accessibility / Speech and information coverage
- Discovery status: Discovered — reopened 2026-07-30 at the project owner's prompt (a specific hypothesis about *why*: that Shadow Pokémon might carry an entirely separate species/Pokédex ID; tested and disproven, which productively redirected the investigation straight to the real mechanism rather than ending it)
- Accessibility status: **Implemented and live-verified (2026-07-30)**
- Current limitation: none for the Moves-page/party-read case. Not yet checked whether battle move-use narration (the in-battle "used X" message, resolved differently via `resolver.py`'s `move_sample()`/`current_move_id`, not `party.py`) is separately affected — plausible it already reads correctly, since that field likely reflects whichever move was actually selected/executed rather than a static slot list, but this hasn't been confirmed either way.
- Severity: 2 (now resolved for the confirmed case)
- Story requirement: none — reproduced and fixed against the current live save
- Reproduction steps (historical, now fixed): open the Moves page (or trigger battle move narration) for a Shadow Pokémon with an unpurified move slot
- Relevant save/save-state: current live save (Teddiursa)
- Technical findings: full trace in [PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md) #6, which now has the complete resolution. Summary: `pokemonBiosGetDarkpokemonDataId` (`pokemonBios.s`) reads a `u16` at `pokemon+0xBA` on the ordinary Pokemon struct; nonzero means this individual has an entry in a separate, persistent `_deckDarkPokemon` array (`deck.s`, pointer `0x804EBB60`, stride `0x18`, confirmed via `xd-decomp/config/GXXE01/symbols.txt`) holding 4 real "Dark Waza" (Shadow move) IDs at `+0x0C`, one per move slot. A slot's own waza entry reading `0` is the live-confirmed signal that slot isn't shadow-locked (no separate purification flag needed). Live-verified against the project owner's real Teddiursa via the actual production code path: normal `move1-4` read `{216, 287, 122, 232}` (122/232 = Lick/Metal Claw, the two genuinely-unlocked slots, matching what was already being narrated correctly); `_deckDarkPokemon[dark_id]`'s waza read `{356, 369, 0, 0}`, resolving to "Shadow Blitz" and "Shadow Mist" — the latter an exact match to this entry's own 2026-07-29 OCR finding.
- Implementation status: Implemented (`party.py`'s new `_dark_waza()`, wired into `_moves()`; new `profile.py` fields `dark_pokemon_data_id_offset`/`deck_dark_pokemon_*`)
- Live-test status: Live-tested — confirmed against the real, current save via the production `PartyMemorySource` code path
- Regression-test status: Regression-tested (`test_party.py`, 2 new tests: shadow-locked override applies correctly, non-Shadow Pokémon are unaffected)
- Last verified date: 2026-07-30
- Remaining work: confirm whether battle move-use narration needs the same override (separate code path, not yet checked)
- Notes: this also plausibly affects battle move narration (the move menu) — not yet checked, tracked as remaining work above rather than assumed fine

---

## Purification systems

### Purify Chamber and related screens
- Primary workstream: Story mechanics, puzzles, and special systems
- Discovery status: **Reachable — confirmed by the project owner 2026-08-05** ("Purify Chamber (HQ Lab)"). Supersedes the earlier "reachability not established" entry.
- Accessibility status: Implemented (model and reader), pending one live pass
- Severity: 0 — this is the one screen in the game whose entire point is a number that is never written down. TEMPO and FLOW are drawn only as bar widgets and coloured connecting lines, so without narration a blind player has no way at all to tell a good arrangement from a bad one; reading the occupants without them would be like reading a chessboard without saying who is winning.
- Story requirement: none — already reached
- Technical findings: full derivation in [PC_AND_PURIFY_CHAMBER_RESEARCH.md](PC_AND_PURIFY_CHAMBER_RESEARCH.md) §2. `CReliveHall` is savedata + `0x1D690`, nine 984-byte `CReliveStage` records (four 196-byte dancer slots, the visitor at `+0x310`, a signed facing byte at `+0x3D4`). Neither Tempo nor Flow is stored anywhere — `getTempo` (`0x8028DB78`) and `getPassionWoBonus` (`0x8028DDBC`) recompute on every redraw, confirmed by checking every caller of both — so `purify_chamber.py` ports them, reading every constant out of the game's own live tables rather than typing them in. The port's cross-check: maximum Tempo (96) times the largest Flow multiplier (2.0) is exactly 192, the literal `isBonusGet` (`0x8028E1E8`) compares against. Two independent paths, same number, neither value written into the model.
- Implementation status: **Implemented (2026-08-05)** — `purify_chamber.py` (`PurifyChamberModel` + `PurifyChamberReader`), wired through `phase1b_app.py`/`phase1b_lifecycle.py`. Announces the SET and its full state on L/R switch, the cursor position and its occupant on every move, pick-up/put-down, and resolves the action popup's labels (MOVE/PLACE/EXCHANGE/ROTATE/SUMMARY/CANCEL) from the game's own six `.data` option tables rather than a typed-in list. 54 unit tests in `tests/test_purify_chamber.py`.
- Remaining work: one live pass with the edit screen open to confirm the `CMenuReliveHall` cursor offsets (`+0x338` SET index, `+0x80F64` catch object, `+0x0C` cursor position, `+0x20` carried Pokémon) — read off real function bodies but not yet observed in a running screen. The ROTATE sub-dialogue (53528-53530) is not narrated as its own widget, though the facing it changes is reported in the SET summary.

---

## PC and storage

### PC main menu / storage-action submenu
- Primary workstream: Speech and information coverage
- Discovery status: Currently reachable (PCs are a durable, repeatable location, not a one-time story gate; already directly investigated live — see task #50 in session history)
- Accessibility status: Discovered
- Severity: 1
- Story requirement: none — already reached and investigated
- Technical findings: `IMPLEMENTATION_ATTRIBUTION.md`'s 2026-07-27 "live PC-menu window study" entry; `menu_id=122` main PC menu (3 options, wraps) and `menu_id=123` 4-option storage-action submenu
- Implementation status: **Implemented** — `pc_menu.py`'s `PCMenuReader`, wired via `pc_menu_factory`
- Remaining work: none

### Box grid navigation (Pokémon Storage)
- Primary workstream: Speech and information coverage
- Discovery status: Currently reachable (durable, repeatable location)
- Accessibility status: Implemented
- Severity: 0-1 (Pokémon Storage is a core, frequently-used system)
- Technical findings: the cursor blocker was solved live on 2026-08-02 — `pMenuPokemonLeave` (`0x804EA870`), cursor pointer at `+0x37F0`, selector at cursor `+0x0C`, current box at `+0x03E0`, indices 4-9 party and 10-39 the thirty box cells. Cell **contents** were then pinned statically from `PCBOX::getPokemon` (`0x80156AB0`): `savedata + 0xAD0 + box*0x170C + 0x14 + slot*0xC4`, where `0x170C == 0x14 + 30*0xC4` exactly. Cross-checked by the fact that the same `savedataGetStatus` jump table yields `savedata + 0x140` for section 2, which is already `profile.hero_offset`. Box names are the GSchar string in each box's `0x14` header.
- Implementation status: **Implemented**; a real addressing defect fixed 2026-08-05
- Notes: **the defect.** Box cells were read as `party_source._decode_slot(obj + 0x3718, slot)` — but that method's second argument is only an error label and does no addressing, so all thirty cells decoded the *same* address and the reader announced one Pokémon for every cell in the box. That is worse than silence: it is confidently wrong. It survived because `tests/test_pc_menu.py` held a single bare pytest function (no `unittest.TestCase`), which unittest discovery never collected, and because it asserted on menu labels rather than on which address a cell reads. Now fixed to read the save's own PC box, with `PCBoxAddressingTests` asserting the engine's formula, that all thirty cells resolve distinct consecutive addresses, and that boxes do not overlap.
- Remaining work: none for navigation. Announcement includes the box name where one is set; as of 2026-08-10 occupied cells speak the Pokemon name before box/grid coordinates. Regression-tested; full suite 1,353 passing.

### PC Summary screen, Item Storage
- Primary workstream: Speech and information coverage
- Discovery status: Currently reachable (durable, repeatable location)
- Accessibility status: Discovered
- Current limitation: PC box-Pokémon summaries are expected to reuse the already-implemented `party_summary_screen.py` mechanism (same `_menuStatus+0x0C` pointer, confirmed to work for non-party summaries too) once the box grid itself is navigable; PC Item Storage is confirmed to reuse the exact same bag-category-tabs window (`menu_id=44`) already fully mapped for the overworld Bag
- Severity: 1, contingent on the box-grid blocker above being resolved first for Pokémon Storage specifically; Item Storage could be wired sooner since its underlying window is already solved
- Implementation status: Not implemented
- Remaining work: wire Item Storage now (low additional cost, shares existing code); Pokémon Storage summary depends on the box-grid blocker

### PC exit flow
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: Unknown
- Accessibility status: Unknown
- Remaining work: not yet investigated

---

## Story interactions

### Krane's static per-room placement (name/position aid)
- Primary workstream: Story mechanics, puzzles, and special systems
- Discovery status: Discovered
- Accessibility status: Implemented (research artifact, not a standalone player-facing feature)
- Technical findings: parsed via `XGCharacter.swift`'s documented format for 3 M5 lab/apartment rooms
- Remaining work: none currently open; was a one-off lookup, not productized as its own hotkey/feature

### General scripted dialogue speaker names
- See "Overworld NPC dialogue" under Field exploration above (same feature).

### Gateon Port bridge
- See Map and navigation screens above (same item, cross-referenced here per the requested section list).

### Other one-off story interfaces
- Primary workstream: Story mechanics, puzzles, and special systems
- Discovery status: Unknown
- Accessibility status: Unknown
- Remaining work: discover through play; explicitly not pre-inventoried

---

## Puzzles and environmental mechanics

### Doors, elevators, warps
- See Field exploration / Map and navigation screens above — these are implemented as authoritative entity-nav categories.

### Switches, object-placement puzzles, pattern puzzles, timing mechanics ("later puzzles")
- Primary workstream: Story mechanics, puzzles, and special systems
- Discovery status: **Unknown — reachability not established from any available record.** No puzzle beyond ordinary doors/elevators/warps has been referenced anywhere in the repository or prior session history. Not asserted as "not yet reached" (a guess) — genuinely unresolved. Left unresolved per explicit instruction (2026-07-29 correction) until reported.
- Accessibility status: Unknown
- Current limitation: cannot be investigated until a specific puzzle is confirmed encountered
- Severity: provisionally 0 for any *mandatory* visual puzzle, per the master plan's blocker definition, until one is actually found and assessed
- Remaining work: discover through play; this is a category explicitly expected to grow, not to be pre-solved

### Future unknown puzzle types
- Deliberately not inventoried. This row exists as a placeholder acknowledging the coverage matrix will keep growing here, per [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md)'s explicit instruction not to predict every future feature.

---

## Special interfaces and minigames

Nothing has been discovered under this section yet. No minigame or special interface distinct from ordinary menus/battle/field has been reached or investigated in the current playthrough as far as verified this session. This section is intentionally empty pending discovery.

---

## Infrastructure and configuration

### Context detection / lifecycle gating (dialogue, battle, menu, loading suppression)
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Technical findings: `phase1b_lifecycle.py`
- Implementation status: Implemented
- Live-test status: Live-tested
- Regression-test status: Regression-tested (`test_phase1b_lifecycle.py`, `test_phase1b_shutdown_and_reset.py`)
- Last verified date: ongoing (foundation used by every other feature)
- Remaining work: none currently open

### Sound library (settings menu heading)
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: n/a — a new feature request. Project owner, 2026-08-18: *"add a sound library that plays each sound that the game makes for beacons and such that we added for each relevant part of the game."*
- Accessibility status: **Implemented 2026-08-18, NOT yet live-tested**
- Current limitation: none known beyond the pending live test
- Severity: n/a (new feature request) — though the underlying gap it closes is real: the companion makes eleven distinct non-speech sounds and, until this, the only way to learn any of them was to encounter it in play and infer what had happened. A cue you *misidentify* is worse than silence, because you act on it.
- Story requirement: none
- Reproduction steps: `F1`, then `H` to the "Sound library" heading; arrow through the entries and press `enter` on one
- Technical findings: `sound_library.py` (the catalogue and playback) plus a new `settings.Sound` item kind. Six ambient beacons, three navigation cues, a footstep and the blocked-movement cue. Every path is supplied by `phase1b_app.build_sound_library` from the same constant the feature itself uses (`PASSIVE_BEACON_SOUND_FILES`, `GUIDE_SOUND_FILES`, `terrain_footsteps.resolve_step_paths`/`resolve_blocked_path`), so the library cannot offer a sound nothing plays or miss one that something does — `GUIDE_SOUND_FILES` and the two terrain resolvers were extracted for exactly this, since those filenames were previously spelled inline in the guide factory and inside `TerrainTonePlayer.__init__`. `Sound` is the only item kind whose `description` is spoken: for every other setting the label already says what it does, but for a cue the explanation is the entire point, and the wording says what the sound *means*, never what it sounds like. `Enter` plays and says nothing — talking over the cue is what would stop the player recognising it later. A file that cannot be rendered drops its own entry and logs a warning; an entirely empty library contributes no heading rather than an empty one.
- Implementation status: Implemented — `sound_library.py` (new), `settings.Sound`/`VALUELESS_KINDS`/`_sound_library_categories`, `settings_menu.py` activation and entry text, `npc_beacons.GUIDE_SOUND_FILES`/`resolve_guide_sound_dir`, `terrain_footsteps.resolve_step_paths`/`resolve_blocked_path`, `phase1b_app.build_sound_library`
- Live-test status: **Not yet live-tested** — in particular, whether every entry is audible and distinguishable at the volume it is offered at (the warp entry deliberately plays at the same 0.2 trim the real warp beacon uses, so the example sounds like the thing it is teaching)
- Regression-test status: Regression-tested (`tests/test_sound_library.py`, 17 tests, plus a new category test in `tests/test_settings_menu.py`)
- Last verified date: 2026-08-18 (tests only; all 11 cues confirmed to resolve to real, playable files in this checkout)
- **Two corrections from the first live listen (2026-08-18):**
    - *"there is no blick [blocked] sound"* — the blocked-movement entry was inaudible on the project owner's hardware. Measured rather than guessed: the file peaks at full scale and measures −9 dBFS RMS, so it was never silent, but it is a square wave and **84% of a 90 Hz square's energy sits below 150 Hz**, which laptop speakers and most earbuds do not reproduce. What reached the ear was the 270 Hz third harmonic at a third of the amplitude. Raised to 200 Hz (`terrain_footsteps.BLOCKED_CUE_FREQUENCY`), which puts the fundamental in range on any speaker while keeping this the lowest, dullest cue in the set — a thud rather than a beep, so it stays distinguishable from the beacons, which is why a low tone was chosen originally. `BLOCKED_CUE_FILENAME` changed with it, deliberately: the file is generated only `if not path.exists()`, so under the old name every existing install would have kept its cached 90 Hz copy forever. Note the cue is off by default in play; this changes what the library demonstrates either way.
    - *"the door sound isn't for warps, it's for interior rooms"* — the door entry's description was wrong, and wrong in the one direction that matters. Building entrances are warp-attached and have never beaconed as doors (see the door/warp entry below); the door beacon only ever sounds for the 78 interior doors. The description said the opposite.
- Remaining work: live-test through NVDA; consider adding entries for any future cue, which is a one-line addition to `sound_library.CUE_TEXT` plus a path in `build_sound_library`

### Clerk and nurse titles (withdrawn until detection is settled)
- Primary workstream: Navigation and spatial awareness
- Discovery status: **Requested 2026-08-18** — *"make the clerks and nurses npc's and remove their titles as clerks and nurses until you are able to find out how to detect a clerk and a nurse"*
- Accessibility status: **Withdrawn 2026-08-18, NOT yet live-tested.** Not a fix — a deliberate retreat to saying less, which is correct while the detection cannot be trusted.
- Current limitation: no NPC is identified by role at all. Finding the Mart clerk or the Centre nurse is back to walking the NPC list.
- Severity: 2 — but the state it replaces was worse. A confident wrong title sends a player across a room to buy from a bystander, and unlike silence they have no way to tell.
- Story requirement: none
- Technical findings: **three** separate mechanisms were producing these titles, and two were the same mistake:
    1. `phase1b_app`'s `role_rooms = {0x85: "Pokemon Center nurse", 0x86: "Pokemon Mart clerk"}`, matched against `entity.identity[1]` — the **floor ID**. This is the exact guess `npc_roles.py`'s docstring was written to replace ("Every NPC standing in Agate's Mart was therefore announced as a clerk"), and which `npc_beacons.py` separately records as one that "both mislabels every other NPC in those two rooms and misses every other Pokemon Center". **It survived both of those write-ups and was still live.** Removed; those NPCs are now ordinary NPCs, named or lettered like any other.
    2. The Poké Mart **beacon**, gated on `npc.floor_id in XD_US_REV0.pokemart_room_ids` — the same guess in the sound layer, so every NPC standing in a Mart sounded like the clerk and a Mart in an unlisted room sounded like nobody. Disabled.
    3. `NPCRoleResolver`, the principled talk-script derivation (`Dialogs::openPokemartMenu` / `Character::101`). This is the one worth keeping and is the obvious starting point when this is picked back up, but it also puts a title in front of the player — `entity_sources` uses the resolved role as the entity's LABEL — so it is left unwired.
- **Nothing was deleted.** `npc_roles.py`, `assets/npc_roles.json` and their tests are untouched. The beacon wrapper is left in place as `lambda npc: False` with the one-line talk-script predicate written in the comment beside it, so the seam to plug back into is explicit rather than something to rediscover.
- Knock-on, recorded because it is easy to miss: `"pokemart"` was removed from `npc_beacons.PASSIVE_BEACON_SOUND_FILES`, because `phase1b_app.build_sound_library` builds the Sound library from that dict and the library's own rule is that it must never name a cue nothing plays. `sounds/pokemarts.wav` remains in the repo; restoring the category is one line.
- Implementation status: Withdrawn — `phase1b_app.py`, `npc_beacons.py`
- Live-test status: **Not yet live-tested**
- Regression-test status: `tests/test_npc_interactions.py` updated (the beacon-category set no longer contains "pokemart"); the rest of the suite passes unchanged, which is itself the useful signal — nothing depended on the room-id table
- Last verified date: 2026-08-18
- Remaining work: settle how a clerk and a nurse are actually detected. `NPCRoleResolver` is the candidate and is already derived from the game's own scripts; what is unproven is whether it identifies the right individual NPC in every room rather than the right room. `npc_beacons`'s `people_type_id` field (floor_character +0x06, the people-info table index) was exposed specifically to measure whether role NPCs share a type id across rooms — that measurement has still not been made, and it is the cheapest next step.

### Doors that are also warps (removed from entity navigation)
- Primary workstream: Navigation and spatial awareness
- Discovery status: **Requested 2026-08-18** — *"take doors that are also warps out of the item nav"*
- Accessibility status: **Implemented 2026-08-18, NOT yet live-tested**
- Current limitation: none known
- Severity: 2 — not a wrong answer, but a redundant one that made the Doors category longer and less useful than it looks
- Story requirement: none
- Technical findings: in this game's data a building entrance IS both things — the Door record animates the doorway, the Warp record moves you — and **72 of the 150 doors in the real table share a collision region with a warp**, so this is the common case, not an edge one. It has now been addressed twice, a week apart, on the same records: on 2026-08-10 such doors were made silent (`metadata["beacon"] = False`) because standing at an entrance played the door and warp beacons simultaneously from one point; on 2026-08-18 they were dropped from `AuthoritativeDoorEntitySource.entities()` outright. Silent-but-present still put them in the Doors cycle, duplicating spots the Exits category already lists **with their destination named** — strictly less informative than the entry they duplicated. What remains in the category is the 78 interior doors, which is exactly what the door beacon has always meant.
- Implementation status: Implemented — `authoritative_warps.AuthoritativeDoorEntitySource`. `metadata["warp_attached"]` is retained (now always False on a published door) so a caller that filtered on it does not silently start seeing a field that has vanished.
- Live-test status: **Not yet live-tested**
- Regression-test status: Regression-tested — `tests/test_authoritative_warps.py` updated; the former "published silent" test now asserts the door is not published at all, and the interior-door and cross-room cases are unchanged
- Last verified date: 2026-08-18
- Remaining work: live-test — walk a town and confirm the Doors category now holds only doors inside buildings, and that entrances are still reachable through Exits

### The same message spoken twice by two readers (fixed)
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: **Reported 2026-08-18** — *"texts repeat themselves"*
- Accessibility status: **Fixed 2026-08-18, NOT yet live-tested**
- Current limitation: scoped to the DIALOGUE/MENU_FOCUS pair; other repeat shapes are untouched, deliberately (see below)
- Severity: 2 — not wrong information, but every duplicated line is time the player spends listening to something they already heard
- Story requirement: none
- Technical findings: the production log names both culprits, **one millisecond apart**:

    ```
    17:19:47.634 SPEECH class=DIALOGUE   'LEON obtained the Cologne Case!'
    17:19:47.635 MENU FOCUS NotificationFocus(message_id=54005, ...)
    17:19:47.635 SPEECH class=MENU_FOCUS 'LEON obtained the Cologne Case!'
    ```

  The dialogue reader and the notification-window reader both render the same game message. **76 occurrences** across the logs — item pickups and Purify Chamber notices, mostly — and crucially in **both orders**, so neither reader could simply be muted: each is sometimes the only one that fires, and silencing either would lose the message outright.
- Fix: `SpeechCoordinator` drops an utterance whose exact text was just spoken **by the other reader** — same text, different speech class, within 1.0s. Nothing can be lost, because a message only one reader claims is still spoken; only an exact duplicate is dropped.
- **Why it is scoped rather than global**, which is the part that took the measuring: a log-wide scan of every same-text repeat found that legitimate ones (a player re-reading an NPC, cycling the move cursor back to a move, pressing the entity-nav repeat key) are always the **same** class twice, and the closest such legitimate repeat is **0.49s** — uncomfortably near the **0.38s** worst genuine duplicate. A global window would have been guessing in that 0.11s gap. Restricted to *different* classes there is no legitimate case at all, so 1.0s is safe with room to spare. The project owner chose this narrower option ("whatever safer") over muting a specific reader.
- Implementation status: Implemented — `speech.SpeechCoordinator.CROSS_READER_DEDUP_CLASSES` / `CROSS_READER_DEDUP_SECONDS`. Every suppression logs `SPEECH CROSS DEDUP` at INFO.
- Live-test status: **Not yet live-tested**
- Regression-test status: Regression-tested — `tests/test_speech_coordinator.py` (new, 10 tests). One of them caught a real over-reach in the first implementation, which suppressed same-reader repeats too.
- Last verified date: 2026-08-18
- Remaining work: live-test; watch for `SPEECH CROSS DEDUP` and confirm nothing suppressed was a line the player needed. Two other repeat shapes were found in the same scan and are NOT addressed: the teleport reader speaks twice (~0.18s apart) and says "Teleported **to to** world map" — a doubled word as well as a doubled utterance; and the name-entry keyboard repeats "Space".

### Mt. Battle room names
- Primary workstream: Navigation and spatial awareness
- Discovery status: **Named by the project owner 2026-08-18** — *"you can hardcode this map to Mt. Battle Enterance because i'm sure it shares certain elements to a pokemon center, but it's the enterance... also change mt. battle warp to mt. batlle outside"*
- Accessibility status: **Implemented 2026-08-18, NOT yet live-tested**
- Current limitation: none known
- Severity: 2 — the entrance announcing itself as a Pokémon Center is a wrong place name, which a player navigates by
- Story requirement: none
- Technical findings: two entries added to `player_facing_names.EXACT_ROOM_NAMES`, the project's existing curated label table. Neither was taken on trust — both were corroborated before being written:
    - **`D2_pc_1F` → "Mt. Battle entrance"** (was "Pokemon Center, 1st floor"). The room code says `pc` because the building reuses a Center's template, which is exactly what the owner described. Its own script settles what it is: it declares `mtbtl`, `mtbtl_chart` and `mtbtl_menu_1/2/3` — the Mt. Battle challenge chart and its menus. No other `_pc_` room in the game declares anything of the kind, and real Pokémon Centers (`M3_pc_1F`) are unaffected.
    - **`D2_out` → "Mt. Battle outside"** (was "Mt. Battle"). `LOCATION_NAMES["D2"]` is also "Mt. Battle", so a warp leading back outdoors announced the same words as the place the player was already standing in. The world-map destination entry is untouched, since that text comes from the game's own `worldmap.fsys` table (message 54508), not from here.
- Note on the standing no-hardcoding rule: that rule is about patching *derived* facts — positions, flags, offsets — with typed-in overrides instead of investigating. `EXACT_ROOM_NAMES` is a curated player-facing label table whose whole purpose is this, and whose existing entries were added the same way. The script evidence above is what keeps it on the right side of the line.
- Implementation status: Implemented — `player_facing_names.py`
- Live-test status: **Not yet live-tested**
- Regression-test status: Regression-tested — 4 new tests in `tests/test_player_facing_names.py`, including that ordinary Pokémon Centers and other D2 rooms are unaffected
- Last verified date: 2026-08-18
- Remaining work: live-test

### PC home menu announced "Save" for "Exit" (fixed)
- Primary workstream: Speech and information coverage
- Discovery status: **Reported 2026-08-18** — *"the pc says 'save' instead of 'exit'"*
- Accessibility status: **Fixed 2026-08-18, NOT yet live-tested**
- Current limitation: none known
- Severity: 1 — the player was told the wrong thing about the option they were about to confirm, on a menu that writes save data
- Story requirement: none
- Technical findings: `pc_menu.py` held **two disagreeing label tuples for the same menu**. The named constant `MAIN_LABELS` had the correct three entries (`Pokemon Storage`, `Item Storage`, `Exit`), but `_poll_fixed` carried its own inline four-entry tuple with a phantom `"Save"` in position 2 — so landing on Exit announced "Save", and index 3 was unreachable.
- **This is the second time this exact shape of bug hit this one menu.** The comment on `ACTION_LABELS` records the first: `_poll_fixed` was announcing the Item-PC's labels for the Pokemon-PC window. Both had the same cause — a second copy of the labels living at the call site, free to drift from the one that is named. `_poll_fixed` now reads the constants, so there is one copy left to be right or wrong.
- Implementation status: Implemented — `pc_menu.PCMenuReader`
- Live-test status: **Not yet live-tested**
- Regression-test status: Regression-tested — 3 new tests in `tests/test_pc_menu.py`, one of which asserts `_poll_fixed`'s source contains no literal label tuple, since re-introducing one is precisely how this broke twice
- Last verified date: 2026-08-18
- Remaining work: live-test — open the PC, arrow to the last entry, confirm it says "Exit"

### Invented battle lines from subject drift (fixed)
- Primary workstream: Battle accessibility
- Discovery status: **Reported 2026-08-18** by the project owner — *"it just said 'numel is in rage mode,' when numel is 1) not a shadow pokemon and b) not even my pokemon"*
- Accessibility status: **Fixed 2026-08-18, NOT yet live-tested**
- Current limitation: none known; see the deliberate trade-off below
- Severity: 1 — a fabricated battle fact is worse than a missing one. The player cannot tell it apart from a real line, and acts on it.
- Story requirement: none
- Technical findings: the production log shows one `OPEN`, one `CLOSE`, and **two** utterances between them:

    ```
    17:12:52.503 OPEN   message_id=20451 '[Pokemon 15] is in Rage Mode!'
    17:12:52.566 SPEECH 'Taillow is in Rage Mode!'   <- real
    17:12:53.756 SPEECH 'Numel is in Rage Mode!'     <- invented
    17:12:53.819 CLOSE  previous_packed=20451
    ```

  The game printed that box once, for Taillow. Over the 1.2s it stayed up, `_ATTACK_MONS` (opcode 0x0F) advanced to the next attacker in the turn; `narrator.process_allocated` deliberately stays ARMED after speaking, re-rendered the same template around the new pointer, and `StabilityGate` — which dedups on the RENDERED STRING — saw a new string and let it through. The re-arm's own comment stated the assumption that failed: *"a changed one is a genuinely new fact."*
- Fix: `MessageState` now carries `spoken_subjects` (the battlers the message was about when it last spoke), and a re-speak is suppressed when **every** battler has changed. Keyed on the canonical `BattlerIdentity.key` (party position + personality), **not** on the raw `FightOutPokemon*` — the pointer is the on-field wrapper, and `battle_identity`'s own docstring records that a Baton Pass keeps the wrapper while swapping the Pokemon behind it. An early version keyed on the pointer and silently swallowed the second line of a Dragon Dance.
- **Why the test is "every subject changed" and not "any subject changed":** a log-wide scan found 18 repeat utterances inside a single open cycle across the whole playthrough, in three distinct shapes, and only one is wrong:

  | Message | Shape | Verdict |
  |---|---|---|
  | 20243 / 20246 (15×) | Dragon Dance, Curse — actor unchanged, stat text changes | real |
  | 20215 (1×) | Intimidate in a double battle — actor unchanged, **target** changes, both foes cut from one box | real |
  | 20451 (1×) | Rage Mode — the sole battler changes outright | **invented** |

  The simpler "any subject changed" rule passes every other test in the suite and would still have swallowed the second half of every Intimidate. A real continuation of an event keeps an anchor — the actor is still the actor — while a pointer that drifted into an unrelated context shares nothing with what was spoken.
- Known trade-off, stated rather than hidden: a *single-subject* message that legitimately re-renders for a second Pokemon within one box would now be suppressed. No such message has been observed. Losing a line is the better error than inventing one — this project's standing rule for any cue the player would act on — and every suppression is logged at WARNING with both subject keys, so a live session can tell whether it ever costs a real line.
- Implementation status: Implemented — `narrator.py` (`MessageState.spoken_subjects`, `_subject_anchor_lost`, `_subjects_key`)
- Live-test status: **Not yet live-tested.** The diagnosis is from the production log, and the fix is covered by tests reproducing that exact sequence, but the fix itself has not run against a live battle.
- Regression-test status: Regression-tested — 4 new tests in `tests/test_battle_messages.py`. Each was confirmed to FAIL with its own fix disabled, not merely to pass with it: the Numel case fails without the guard, and the two-target case fails under the naive "any subject changed" rule.
- Last verified date: 2026-08-18
- Remaining work: live-test; watch the log for `SUBJECT DRIFT suppressed` and check whether any suppressed line was one the game really showed

### Speech priority/suppression, sound-beacon framework, hotkey registry
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: Discovered
- Accessibility status: Live-tested, Regression-tested
- Technical findings: `speech.py`, `hotkeys.py`. **2026-07-30, `npc_beacons.SpatialWavePlayer` (the shared rendering/playback engine behind terrain footsteps, NPC beacons, and the audio guide tone):** the project owner reported live that footsteps and the beacon were audibly silencing each other. Root cause: `winsound.PlaySound` is a single GLOBAL Windows audio channel — every `SpatialWavePlayer` instance in the project called the same one-sound-at-a-time OS API regardless of which feature owned it, so whichever call landed second cut off whatever was already playing, project-wide. Replaced with `pygame.mixer` (genuine concurrent channels; `pygame.mixer.set_num_channels(16)`), playing directly from the already-rendered in-memory PCM buffer instead of writing a temp WAV file and shelling out to play it by path — the old cache-directory/slot-alternation dance existed only to work around `PlaySound`'s file-based API. Each `SpatialWavePlayer` instance tracks only the channels it itself started, so one feature's `stop()` never cuts off a different feature's currently-playing sound. Source assets aren't all the same sample rate, and `pygame.mixer.Sound` built from a raw buffer does not resample it to the mixer's own configured rate — so every rendered buffer is now resampled (linear interpolation, reusing the WSOLA pitch-shift's own `_resample_linear`) to one fixed `MIXER_FREQUENCY = 44100` before playback. `simpleaudio` (a lighter, purpose-built alternative) was considered and rejected: it only ships a source tarball for this project's Python 3.12/Windows combination, requiring a C compiler to install, versus `pygame`'s prebuilt wheel (confirmed downloadable before committing to it). Live-verified directly (not just unit-tested) with two real `SpatialWavePlayer` instances and real `pygame.mixer`: both played fully concurrently (both channels simultaneously `get_busy() == True`), and calling `.stop()` on one left the other's sound playing.
- Implementation status: Implemented
- Live-test status: Live-tested (the concurrent-playback fix itself, via a real-`pygame.mixer` two-instance smoke test; the original speech/hotkey infrastructure this entry also covers was already live-tested earlier)
- Regression-test status: Regression-tested (`test_npc_beacons.py`: mixer init args, buffer resampling to `MIXER_FREQUENCY`, and per-instance `stop()` isolation against a `FakeMixer`)
- Remaining work: none currently open. `pygame` added to `requirements.txt`.

### Companion settings menu (`F1`)
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: Discovered
- Accessibility status: **Implemented 2026-08-16, Regression-tested, NOT yet live-tested.**
- Current limitation: see Live-test status — the central mechanism is argued, not measured.
- Severity: 3
- Story requirement: none
- Technical findings: `settings.py` (model, persistence, appliers), `settings_menu.py` (navigation and speech), `key_capture.py` (`WH_KEYBOARD_LL`). Full write-up in [SETTINGS_MENU.md](SETTINGS_MENU.md), including the vertical-slice record. Every value exposed already existed as a named constant, three of which carried comments saying they were named *for* this UI (`npc_beacons.PASSIVE_BEACON_GAIN_SCALE`, `PASSIVE_BEACON_CATEGORY_GAIN`, `TerrainTonePlayer.STEP_GAIN`); defaults are read from those constants rather than retyped. **This is the first feature in the project that takes keys away from Dolphin.** It has to: read from the owner's own configuration, `Hotkeys.ini` binds F1 to Load State Slot 1 and `GCPadNew.ini` binds the arrows to the main stick, H to D-pad right and Return to Start, so a polled menu on those keys would load a save state on open and walk the player around while they navigated. Polling (`GetAsyncKeyState`, what every other hotkey uses) observes but cannot consume; a low-level hook can. Scope is bounded four ways: only keys in `MenuKeyPolicy`, only while Dolphin has foreground focus, only F1 outside the menu, and `--no-settings-menu` disables the hook entirely.
- Implementation status: Implemented. Settings are applied to live readers and re-applied on every lifecycle rebuild (a reattach discards every reader); on/off toggles are instead gated at poll time in `LifecycleController._feature_enabled`, so switching one off does not destroy a reader that is expensive to rebuild. Stored in `companion_settings.json` under an `"accessibility"` key, merged with the paths `Setup.cmd` writes — which required `setup_companion.write_settings` to merge rather than overwrite, and `launch_accessible.py` to stop treating the file's existence as proof Setup had run.
- Live-test status: **Not started, and one claim depends on it.** Whether swallowing at the hook actually prevents Dolphin's DirectInput from seeing the key is a mechanism argument (non-exclusive DirectInput is built on the same input stream low-level hooks filter), not a measurement, and this project does not count those as verified. Procedure in [SETTINGS_MENU.md](SETTINGS_MENU.md) §7. Also unheard: whether the volume and distance values sound the way their numbers suggest.
- Regression-test status: Regression-tested — `test_settings_menu.py`, 80 tests: value formatting and stepping (including that six 0.05 steps land on exactly 0.3), store round-trip with Setup's keys preserved, unknown-key and corrupt-file handling, an unwritable path reported once, appliers against the real attributes they target (module-level beacon gains, the shared `TerrainTonePlayer`, both halves of `GuideModes`) plus no-readers/no-controller/raising-applier cases, heading and edge navigation, empty categories, the key policy (that `X`/`Z`/`T`/`G`/`F`/`F2` are never owned and that arrows reach the game while the menu is closed), poll-time gating including the once-only falling edge, and the lifecycle-reset path (`clear()` closes silently, releases the keys, and drops anything queued). A separate manual smoke run installed the real hook with foreground forced false, confirming it installs, pumps and uninstalls without consuming a key.
- Last verified date: 2026-08-16 (regression tests + hook install/uninstall smoke test only)
- Remaining work: the live run above. If a key does reach the game as well, the fallbacks are rebinding it in Dolphin or moving the menu onto keys Dolphin does not use; both live in `MenuKeyPolicy` alone.
- Notes: the menu is polled in every lifecycle state, before the state machine, including before Dolphin is attached — it reads no emulated memory, and a player who wants to turn the beacons down should not have to boot a game first. An open menu also raises the poll rate to the active interval, since the waiting states' half-second tick is far too slow for something a person is pressing keys at.

### Address and build validation (vanilla `GXXE01` rev 0 hash pin)
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: Discovered
- Accessibility status: Implemented, Regression-tested
- Current limitation: validates against vanilla XD only; XG-vs-vanilla divergence remains unverified (see [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md)'s risks)
- Remaining work: none currently open beyond the standing XG-verification caveat

### Automated test suite
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: Discovered
- Accessibility status: Regression-tested
- Current limitation: 361 tests passing as of 2026-07-29; live-memory-read implementation details are deliberately not unit-tested directly, per established project convention — only dispatch/orchestration logic is
- Implementation status: Implemented
- Regression-test status: Regression-tested (self-referential — this is the regression mechanism itself)
- Last verified date: 2026-07-29
- Remaining work: none currently open

### Live regression process
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: Discovered
- Accessibility status: Partially accessible
- Current limitation: live regression happens ad hoc after each change, not against a fixed, repeatable checklist
- Severity: 2 (process gap, not a player-facing gap)
- Remaining work: the project owner's seed list names this explicitly ("Existing battle HP narration," "Existing HP summary hotkey," "VS menu narration," "Entity navigation," "Existing menu narration," "Speech backend") as the current regression queue — see [ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md)

### Single-instance narrator guard
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: Discovered
- Accessibility status: Blocked technically / technical debt
- Current limitation: `run_accessible_pokemon_xd.py` has a `CreateMutexW` single-instance guard; `run_battle_narrator.py` (the one the project owner actually launches) does not — the two can run concurrently and double-narrate
- Severity: 1 (caused a real, reported "dialogue repeating more than ever" incident)
- Technical findings: see [PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md) #4
- Remaining work: add the same mutex guard (`Local\PokemonXGAccessibility.BattleNarrator`) to `run_battle_narrator.py`

### Installer and distribution
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: Discovered
- Accessibility status: **Implemented (2026-08-10/11), not yet live-tested end to end**
- What exists: an allowlist-built archive (`Tools/Build Accessibility Release.ps1`), a first-run flow (`Setup.cmd` → `setup_companion.py`), and `bootstrap_game_data.py`, which generates the runtime game-data subset from the recipient's own disc image in about five seconds. Plain `.iso`/`.gcm` are read directly; compressed formats convert through DolphinTool to a temporary ISO that is then deleted. The builder refuses to produce an archive unless three checks pass: no forbidden content; every beacon sound the *staged* code declares is staged (read back out of `PASSIVE_BEACON_SOUND_FILES`, so a newly added category cannot ship silent); and the staged tree compiles with its setup-path entry points importing.
- Verification: the bootstrap reproduced all 189 files of the existing local `_dialogue_extraction` tree **byte-for-byte** from the disc it was built from, and a freshly extracted archive constructed every loader the narrator requires (1,161 battle messages, 287 entity names, 280 warps / 150 doors / 46 elevators, 177 collision rooms, all six beacon sounds resolving inside the release).
- Current limitation: **no live run of a built release** — all of the above is static verification plus loader construction, with no Dolphin session. Gateon Port bridges disable themselves in a release because they need `rooms/M6_out.txt`, which comes from a third-party disassembler the bootstrap does not carry.
- Remaining work: an end-to-end live run from a clean extraction on a machine that is not the development one; an installer `.exe` with update checking (project owner's request, 2026-08-10 — the archive already carries a `VERSION` stamp for it to compare against).

### User-facing documentation
- Primary workstream: Infrastructure, safety, testing, and distribution
- Discovery status: Discovered
- Accessibility status: **Implemented (2026-08-10/16)**
- What exists: `README.md` (prerequisites, install, the full hotkey list, settings menu, autowalk behaviour, troubleshooting, known limitations), `THIRD-PARTY-NOTICES.md` (the Mossy4 CC-BY attribution is a licence obligation), `LICENSE` (MIT), and `MASTER.md` — the single map of every feature, which module owns it and how it is verified. The companion also carries its own in-app hotkey reference: the settings menu's Hotkeys heading is generated from the live arguments, so it cannot drift from the keys actually bound.
- Current limitation: none known; the README's hotkey table is maintained by hand and is the one place that *can* drift from `profile.py` (it was already wrong once, on 2026-08-16, when the `shift` modifiers were dropped).
- Remaining work: consider generating the README hotkey table from `hotkey_reference()` the way the in-app list already is.
- Forget-move correction (2026-08-10): window 98 overlays party-summary window 94 and the underlying Moves-page cursor owns selection. Its selected row now reuses the ordinary Moves-page presentation; no `Forget …?` or replacement-label wording is embedded. `LocalMoveData` now correctly parses move record `+0` as priority and `+1` as one-byte base PP, fixing EXTREMESPEED's live `01 05` record (priority +1, 5 PP), which previously failed as impossible 261 PP.
- PC/Day-Care correction (2026-08-10): live menu 123 action order is Deposit Pokémon, Withdraw Pokémon, Move Pokémon, Exit; default box names are deduplicated, and scalar `0x37F0` from reused Yes/No menu 89 is not treated as a storage cursor. Agate Day-Care map messages 50711/50713 are dynamic rendered choice prompts; 50710/50712/50714/50715/50716/50717 are dynamic rendered notifications. Ordinary 50709/50708 remain owned by DialogueReader. The Pokémon-view surface reuses the existing party list and summary readers.
- Summary/randomizer correction (2026-08-10): window 94 `+0x9F` is the page index, not the selected move row; window 98 owns the move cursor. Entry to page 2 announces every known move, then window-98 cursor changes announce focus. Ability assignment now comes from each live Pokémon record's resolved ability byte at `+0x1D`, so randomized abilities override vanilla species/personality slots; the runtime ability table still owns displayed name and description.
# 2026-08-10 — Mt. Battle Coupon Exchange and dual balance readout

- Coupon Exchange greeting/menu: message 50615; Exchange, Info, Quit.
- Coupon Exchange one-shot dialogue: 50616–50619 and 50622–50625, including
  the live-observed 50623 insufficient-coupons refusal.
- Coupon shop item and quantity screens: read the item's Coupon Price (+0x08)
  and announce Poké Coupons; ordinary Marts continue using Price (+0x06) and
  Pokédollars.
- `Ctrl+M`: always announces Pokédollars and Poké Coupons separately,
  including zero balances.
- Verification: 1,314 automated tests pass.

— Codex
# 2026-08-10 — Fully-open Shadow Pokémon move-source correction

- Live one-sample UI/database confirmation: FARQUAD's four battle-UI move IDs,
  names, PP, type, power, accuracy, and descriptions all agreed with the local
  move database (including ExtremeSpeed ID 245, 4/5 PP, Normal, 80 power,
  100 accuracy).
- Root cause: the party reader treated persistent nonzero `_deckDarkPokemon`
  move entries as live display flags. They remain nonzero at Dark Point 0.
- Implemented: at current Dark Point 0, summary/party narration uses the normal
  Pokémon move slots and does not substitute stale Shadow entries. Nonzero-Dark-
  Point behavior is unchanged pending proof of intermediate unlock thresholds.
- Verification: 1,315 automated tests pass.

— Codex

## Navigation: region-aware routing (2026-08-12)

Routed guidance now accepts a route only when an ordinary walkable path
reaches the destination's interaction region. Distance-based acceptance is
retired. See `NAVIGATION_AUDIT_2026-08-04.md` 6h and
`WORLD_NAVIGATION_ARCHITECTURE.md` 6k.

**Routed coverage is intentionally lower** -- roughly 43% of interaction
pairs, down from 69.3% -- because the removed 26 points were false routes:
measured, 1759 of 2024 previously-accepted reseeds put the player on the far
side of a wall from the destination. The invariant is zero known false
`VERIFIED` routes, not maximum coverage.

Remaining limitations, all measured and none fixed here:

- Cross-level destinations within one room are diagnosed (`height_layer` /
  `disconnected`), never routed.
- `M3_cave_1F_1`'s passage reads as disconnected pockets in the collision
  data even though the player can walk it; wall semantics are not yet
  investigated.
- Region target hysteresis and reachable-component selection are specified
  but not implemented.
- Worst-case route build in `M6_out` remains multi-second.
