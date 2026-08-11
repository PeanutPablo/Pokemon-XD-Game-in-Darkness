# PLAYTHROUGH_BARRIER_LOG.md

**Status:** Living document. Created 2026-07-29. Reusable incident log for accessibility barriers discovered while the project owner plays. This is the primary intake mechanism for the discovery-driven development cycle in [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md) — every entry here should eventually be reflected as a row in [ACCESSIBILITY_COVERAGE_MATRIX.md](ACCESSIBILITY_COVERAGE_MATRIX.md) and, if not immediately actionable, as an item in [ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md).

Record a barrier the moment it's found — during the session it happened in, not retroactively from memory.

## Entry format

```
## <sequence number>. <short title>

- Date:
- Location:
- Story point:
- Game context: (field / battle / which menu / dialogue / loading / cutscene)
- What I attempted:
- What was spoken:
- What appeared visually, if known: (only from the project owner's own OCR or explicit report — never from asking them to describe the screen for me)
- Information I needed:
- What prevented or complicated progress:
- Completely blocked: (yes/no)
- Reproduction steps:
- Relevant save file or save state: (cross-reference [MILESTONE_SAVE_INDEX.md](MILESTONE_SAVE_INDEX.md); capture a new one if none exists)
- Suggested workstream:
- Severity: (Level 0 / 1 / 2 / 3 — see [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md)'s severity model)
- Temporary workaround: (if any exists right now)
- Permanent accessibility requirement:
- Technical notes: (addresses, structures, or leads found while investigating — keep this updated as investigation proceeds)
- Resolution status: (Open / Investigating / Implemented / Live-tested / Regression-tested / Deferred / Won't-fix, with reasoning)
```

## Log

No barriers have been formally logged under this system yet as of 2026-07-29. The entries below are retroactively reconstructed, at reduced detail, from barriers already found and substantially addressed during earlier sessions this project — recorded here so this log doesn't start artificially empty of the project's real history. Going forward, new barriers should be logged in full at the time they're found, ideally before investigation begins.

### 1. Dialogue boxes not speaking

- Date: 2026-07-28 (approximate, prior to this log's creation)
- Location: various, first noticed generally
- Story point: mid-playthrough, M5 lab/apartment area
- Game context: field dialogue
- What I attempted: talking to an NPC and progressing through a conversation
- What was spoken: nothing
- Information I needed: the dialogue text itself
- What prevented or complicated progress: no narration at all during conversations
- Completely blocked: effectively yes, for any conversation-gated content
- Reproduction steps: talk to any NPC while `profile.my_name`'s pointer is unreadable/persistently null in the current context
- Relevant save file or save state: none captured
- Suggested workstream: Speech and information coverage
- Severity: Level 0 while unresolved
- Temporary workaround: none
- Permanent accessibility requirement: dialogue must speak regardless of whether the player-name substitution opcode's source is currently readable
- Technical notes: two distinct root causes found and fixed — (1) an uncaught `MemoryError` from a stale player-name address crashed the whole poll loop; (2) `player_name()` was called eagerly for every page even when the page's opcodes never used it. See `IMPLEMENTATION_ATTRIBUTION.md`'s 2026-07-28 entries for the full fix history.
- Resolution status: Implemented, live-tested (confirmed working immediately after the fix). Regression-tested (`test_dialogue.py`).

### 2. NPC speaker names missing/inconsistent

- Date: 2026-07-28 (approximate)
- Story point: mid-playthrough
- Game context: field dialogue, both scripted/cutscene and free-roam
- What I attempted: identifying who was speaking in a conversation
- Information I needed: the speaking NPC's name
- What prevented or complicated progress: names were silent for scripted conversations, and inconsistent ("only works for Jovi") for others
- Completely blocked: no — Level 1, since the conversation itself could still be heard
- Suggested workstream: Speech and information coverage
- Severity: Level 1
- Permanent accessibility requirement: speaker name must resolve for both scripted and free-roam dialogue
- Technical notes: resolved via `msgctrlSetValue(89, ...)`'s `_Npc` global, discovered as a side effect of the `floorExecScriptRes` interaction-boundary trace; the "only Jovi" symptom traced to the proximity-based fallback beacon system being muted from an earlier, unrelated request.
- Resolution status: Implemented, live-tested, regression-tested (`test_entity_names.py`).

### 3. Party/summary screens showing "Empty slot" / always Eevee

- Date: 2026-07-28
- Story point: mid-playthrough, after gaining a second party member (Teddiursa)
- Game context: party list and summary screens
- What I attempted: checking party status after the roster grew past one Pokémon
- Information I needed: correct per-slot party data, and the actually-selected Pokémon's summary
- What prevented or complicated progress: stale heuristic-scanned address broke once save-data's randomized base address shifted across a boot; summary screen always showed slot 0 regardless of L/R navigation
- Completely blocked: no — Level 1/2 (state was readable, just wrong)
- Suggested workstream: Speech and information coverage
- Severity: Level 1 while broken (wrong information is worse than no information)
- Permanent accessibility requirement: party data must resolve dynamically every boot; summary screen must track the actually-displayed Pokémon
- Technical notes: root cause was `savedataBiosSetNowSavedataPtr` randomizing the save-data base address every boot; fixed with a dynamic pointer chain. Summary-screen fix uses `_menuStatus+0x0C`'s live `Pokemon*`.
- Resolution status: Implemented, regression-tested (361 passing). Live-test of the summary-screen multi-Pokémon fix specifically is **still outstanding** — the project owner had not yet restarted their narrator to pick up that fix as of this document's creation.

### 4. Duplicate dialogue narration

- Date: 2026-07-28/29
- Game context: any narrated event
- What I attempted: normal play
- What prevented or complicated progress: every line spoken twice (or more)
- Completely blocked: no, but Level 1 (constant, disorienting double-speech)
- Suggested workstream: Infrastructure, safety, testing, and distribution
- Severity: Level 1
- Permanent accessibility requirement: exactly one narrator instance should ever run
- Technical notes: two distinct causes found across two occurrences — first, a genuine second `run_battle_narrator.py` process (resolved by the project owner taking over exclusive manual launching via their desktop batch file); second, a completely separate script, `run_accessible_pokemon_xd.py`, running invisibly in the background without the same single-instance mutex guard `run_battle_narrator.py` lacks.
- Resolution status: Investigating / partially resolved. The immediate stray process was killed both times. The underlying gap — `run_battle_narrator.py` has no single-instance guard — remains open technical debt (see [ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md)).

### 5. NPC interaction requires standing inside a tiny distance/facing cone

- Date: 2026-07-29
- Game context: field, any NPC conversation
- What I attempted: exploring whether an NPC could be talked to via entity-nav selection without physically walking into the game's exact interaction range and facing cone
- Information I needed: N/A (this is a convenience/independence barrier, not an information barrier)
- What prevented or complicated progress: the tiny interaction radius and ±40° facing requirement make locating and correctly approaching an NPC without sight much harder than it needs to be
- Completely blocked: no — Level 1 (possible via careful audio-guided approach, but effortful and error-prone)
- Suggested workstream: Navigation and spatial awareness (also touches Speech and information coverage)
- Severity: Level 1
- Permanent accessibility requirement: a way to initiate a conversation with an entity-nav-selected NPC without needing to satisfy the game's own proximity/facing check
- Technical notes: full call-chain traced (`updateChat` → `peopleTalkCheck` → `peopleGetTalkSctID` → `floorExecScriptRes`/`floorExecScriptResThread`). The talk-triggering functions are pure and argument-driven `(groupID, resID)`, but no safe way to invoke them from outside the game without either an unreliable execution breakpoint or executable-code modification has been found yet. See the coverage matrix's "NPC direct-interaction assistance" entry.
- Resolution status: Investigating, blocked technically. Not implemented. Awaiting a decision on how to proceed (re-test breakpoint reliability for a narrow one-shot case, accept a scoped code patch with explicit authorization, or an approximate fallback).

### 6. Party summary screen's Moves page shows a Shadow Pokémon's post-purification moveset, not its current moves

**2026-08-10 correction:** the earlier claim that a nonzero deck Shadow-move
entry is sufficient to identify the currently displayed move was disproven by
a direct UI/runtime/database comparison. FARQUAD's UI showed ordinary move IDs
263/328/84/245 with fully matching properties while its persistent deck still
held Shadow IDs 356/368; current Dark Point was 0/2500. The reader now ignores
deck overrides when Dark Point is zero. See the signed 2026-08-10 attribution
entry for the exact sample and deliberately limited scope.

- Date: 2026-07-29
- Location: mid-playthrough live save (Eevee lv.11, Teddiursa lv.11)
- Story point: Teddiursa currently a Shadow Pokémon, not yet purified
- Game context: party summary screen, Moves page
- What I attempted: live-validating the just-fixed multi-Pokémon summary-screen bug (previously always showed slot 0/Eevee regardless of L/R switch)
- What was spoken: "Return, Lick, Refresh, ..." for Teddiursa's moves
- What appeared visually, per the project owner's own OCR: "Shadow Mist" (Teddiursa's actual current Shadow move)
- Information I needed: N/A — this surfaced as a side effect of validating a different fix
- What prevented or complicated progress: the spoken moveset does not match what's actually usable in battle right now
- Completely blocked: no — Level 2 (misleading information, not an inability to act)
- Reproduction steps: open the summary screen's Moves page for a Shadow Pokémon that has not yet had its shadow move purified
- Relevant save/save-state: current live save (Teddiursa, lv. 11, Shadow, not yet captured as a named milestone — see [MILESTONE_SAVE_INDEX.md](MILESTONE_SAVE_INDEX.md))
- Suggested workstream: Speech and information coverage (cross-cutting with Shadow Pokémon systems)
- Severity: 2
- Temporary workaround: none
- Permanent accessibility requirement: the Moves page must announce the Pokémon's actual current, usable moves — substituting the live Shadow move's name for whichever slot is currently shadow-locked, not the underlying "future" move stored in that slot
- Technical notes: live-dumped Teddiursa's raw party struct and confirmed the bug is not in `party.py`'s offsets or `LocalMoveData`'s resolution — move slot 0 genuinely contains move ID 216 ("Return") in the struct's normal `move1-4` fields (offset `0x80`, matching `Pokemon-XD-Code`'s `kPartyPokemonMove1Offset`), which resolves correctly to "Return." This is architecturally consistent with Colosseum/XD's known Shadow Pokémon mechanic: the eventual post-purification move is stored in the normal slot the whole time, and the game substitutes a Shadow-move display/behavior over it until that slot is purified. The field marking "this slot is currently shadow-locked" plus the active Shadow move's own identity has **not** been found yet — a two-Pokémon raw-byte diff wasn't sufficient evidence to point at a specific field (too many confounding per-Pokémon differences). Per the project owner's explicit "no hardcoding" instruction (see the `feedback_no_hardcoding` memory entry), the correct fix requires disassembling the game's own move-list draw/resolution code to find what it actually checks — not a guessed offset or a per-species override table.
- **2026-07-30 update — root cause found and fixed.** The project owner independently raised a specific, falsifiable hypothesis (that Shadow Pokémon might carry an entirely separate species ID) prompting a fresh investigation. That specific hypothesis was tested live and disproven — Teddiursa's species ID reads exactly `216`, the ordinary Pokédex number — but pursuing it led directly to the real answer: `pxdvs/app/pokemon/pokemonBios.s`'s `pokemonBiosGetDarkpokemonDataId` reads a `u16` at `+0xBA` on the normal Pokemon struct; if nonzero, that's an index into a completely separate, persistent array (`_deckDarkPokemon`, `pxdvs/app/deck/deck.s`/`darkPokemonBios.s`, pointer at `0x804EBB60`, stride `0x18`, live-verified against `xd-decomp/config/GXXE01/symbols.txt`) holding up to 4 real "Dark Waza" (Shadow move) IDs, one per move slot, at `+0x0C`. Live-read Teddiursa's actual data: normal `move1-4` = `{216, 287, 122, 232}` (122/287 already correctly narrate as Lick/Metal Claw — the two NOT shadow-locked), while `_deckDarkPokemon[dark_id]`'s waza array read `{356, 369, 0, 0}` — resolving to **"Shadow Blitz"** and **"Shadow Mist"** for the two shadow-locked slots. "Shadow Mist" is an exact match to this very entry's own 2026-07-29 OCR finding, confirming the fix precisely. A slot's own waza entry being `0` is itself the correct, live-confirmed signal for "not currently shadow-locked" (no separate purification-flag lookup needed — a purified slot's entry going to `0` is the same signal, self-updating). Implemented in `party.py`'s `_moves()`/new `_dark_waza()`; new `profile.py` fields (`dark_pokemon_data_id_offset`, `deck_dark_pokemon_*`); 2 new tests in `test_party.py`. Full suite: 482 passing.
- Resolution status: **Implemented and live-verified.** Live-confirmed against the project owner's real, current Teddiursa via the actual production `PartyMemorySource` code path (not a raw scratch read) — see the 2026-07-30 update above for the full trace. The multi-Pokémon summary-screen pointer fix from 2026-07-29 remains unaffected and correct.

### 7. No footstep, terrain, or collision feedback exists at all

- Date: 2026-07-29
- Location: anywhere in the field
- Story point: any
- Game context: ordinary overworld movement
- What I attempted: N/A — this is a standing, always-present gap named directly by the project owner as "a crucial primary issue," not a single reproducible incident
- What was spoken: nothing — no audio marks a footstep, terrain type, or blocked movement
- Information I needed: whether I'm actually moving, what surface I'm on, and whether I've walked into something
- What prevented or complicated progress: no passive sense of movement rhythm or terrain the way ambient game sound gives a sighted player; no wall/obstacle feedback beyond noticing position hasn't changed
- Completely blocked: no — Level 1 (beacons/entity-nav provide some spatial awareness, but nothing for the moment-to-moment "am I moving, what's underfoot" question)
- Reproduction steps: walk anywhere; walk into any wall
- Relevant save/save-state: none needed — applies everywhere
- Suggested workstream: Navigation and spatial awareness
- Severity: 1
- Temporary workaround: none
- Permanent accessibility requirement: audio feedback for movement/terrain/collision
- Technical notes: static investigation for the game's own native footstep-SFX trigger found no dedicated function anywhere in vanilla XD's decompiled symbol table (`floorSound_*` ruled out as a background-music-ducking subsystem unrelated to footsteps; `procStep__F15HEROMOVE_MEMBER` ruled out as a graphics-timing false lead calling only `GSgfxVideoGetLastRenderTime`; `updateLeaderMovement__F15HEROMOVE_MEMBERPf` disassembled directly with no sound-engine calls found; `_sndPlaySE` confirmed used only internally within `GSsnd.s`, meaning every real sound trigger goes through a wrapper not visible from movement code). Closing this gap fully would need a live GDB trace, which the project owner judged too expensive relative to value given the earlier slowdown/boot-hang incident. Redesigned instead as a fully synthetic, accessibility-only layer built from data already available: position deltas for movement/pacing, local `.ccd` `collision_type` for terrain identity, and `collision_probe.predict_forward_collision`'s existing geometric prediction for a blocked cue — see the coverage matrix's "Footstep sound / terrain feedback" and "Collision feedback" entries and `Companion/battle_narrator/terrain_footsteps.py`.
- Resolution status: Footsteps — Implemented, Regression-tested. **First live-test session (2026-07-29) found footsteps completely silent despite 200+ units of confirmed real walking.** Diagnosed via the narrator's own log, not guesswork: `MAX_PLAUSIBLE_DELTA` (the safety threshold meant to reject teleport/room-transition-scale jumps) was set to 8.0, but real per-poll walking deltas in the field log clustered around 16-23 units — meaning literally every bit of real walking was being misclassified as a "jump" and discarded before it could ever accumulate toward a step. Fixed using the real observed data (genuine teleport-scale jumps started at 143+, giving a clean gap to set the new threshold in): `MAX_PLAUSIBLE_DELTA` raised to 60.0, and `STEP_DISTANCE` raised from 1.6 to 12.0 to match the same observed walking scale (the old value would have fired many steps per single poll tick once the jump-threshold bug was fixed). Not yet re-confirmed live — the narrator needs a relaunch to pick up the fix, then the live-test sequence resumes. Also confirmed during this session: the room-transition/large-jump handling itself worked correctly throughout (transitions were seen and correctly logged as "large jump ignored" rather than producing bursts), and dialogue-suppression fired correctly multiple times.
- Collision/blocked-movement — **redesigned again 2026-07-29** after the project owner correctly rejected the first cut's stillness-only gating as an unacceptable false positive (couldn't distinguish "pushing into a wall" from "standing still near one"). Now split into its own `BlockedMovementReader`/`--collision-feedback` flag requiring verified active movement input as one of five conditions; two candidate input signals identified (`GSinput` Control Stick state, and a `tagPeopleWork+0x54` animation-state enum prompted by the project owner's own firsthand observation that the walk animation continues while blocked) but **neither is live-verified yet** — collision feedback must not be live-tested until one is confirmed. See the coverage matrix's "Collision feedback" entry for full technical detail.

### 8. Recurring "The controls are unresponsive..." message, cause not fully confirmed

- Date: 2026-07-29
- Location: an outdoor hub room with door/warp targets named `M6_junk_1F`, `M6_houseA-D`, `M6_tower_1F`, `M6_crab_1F`, `M6_shop_1F`, `M6_pc_1F`, and `worldmap` — consistent with the Gateon Port hub, not yet confirmed by room-name lookup
- Story point: not confirmed
- Game context: overworld free-roam, immediately after browsing warp entities via entity-nav (not confirmed to be the trigger)
- What I attempted: N/A — the project owner reported experiencing this "sometimes" and asked me to check the log
- What was spoken: `"The controls are unresponsive..."`, one to several times per episode, always tied to the same game message ID (41182)
- Information I needed: whether this is legitimate game text (e.g. a story-progression gate worded as a control glitch, matching the tone of this game's tech/hacking themes) or a side effect of a bug in this project's own code
- What prevented or complicated progress: the project owner directly experiences unresponsive controls when this plays — whether that's the real game correctly blocking an action, or an artifact of something in this project interfering with game state, is not yet established
- Completely blocked: not confirmed — appears to self-resolve (each episode ends with a `CLOSE` log line) rather than persisting indefinitely
- Reproduction steps: not yet isolated to a specific player action
- Relevant save/save-state: current live save
- Suggested workstream: Navigation and spatial awareness (cross-cutting with the teleport feature's risk profile)
- Severity: 2 (pending confirmation — could be 0/non-issue if it's legitimate game text, or higher if this project's own teleport feature is inducing it)
- Temporary workaround: none identified yet
- Permanent accessibility requirement: TBD pending root cause
- Technical notes: every occurrence follows an identical sequence in the log: `UNSUPPORTED MENU id=82; silent` → `ENTITY NAV cleared: left free-roaming overworld control` → a battle-message-table `OPEN` for message_id 41182 that is correctly `SUPPRESSED` (`reason=not fight_common` — this is a benign, self-correcting code path: a battle-message poller sees the same message ID and correctly declines to interpret it as a battle message; not itself a bug) → ~0.4s later the narrator's existing `DIALOGUE` speech class (`dialogue.py`, already unconditionally wired into the lifecycle poll loop — the same reader used for ordinary NPC conversation) correctly speaks the literal on-screen text → a `CLOSE` line ends the episode, sometimes after the text repeats 2-4 times a few seconds apart. Found two occurrences in the log: one cluster at 18:35:48-18:36:26 and a second, independent cluster at 20:02:37-20:02:57 (today). Checked for a correlation with this project's own teleport feature (`teleport.py` — a deliberate, explicitly-accepted-risk exception to the project's read-only design, see that file's docstring): the **first** cluster was preceded, 36 seconds earlier, by two uses of the teleport hotkey landing on the `M6_pc_1F` warp record, and the project owner's very next action after the last "unresponsive" line was to teleport to `worldmap` — consistent with (but not proof of) using teleport to escape a stuck state. The **second, most recent** cluster has **no teleport use anywhere nearby** — only read-only entity-nav warp browsing beforehand — which argues against teleport being the sole cause, since it reproduced without it.
- Resolution status: **Investigating, not resolved.** Two competing explanations remain open and neither is being guessed at: (1) this is genuine, intentional game text — a Gateon-Port-style story/area gate worded as a "controls glitch" for thematic reasons (the project's own backlog already tracks a "Gateon Port bridge" as blocked-by-story-progression, and this hub's warp targets are consistent with that location) and the narrator is correctly relaying a real, working-as-intended block; or (2) this project's own teleport feature is occasionally leaving the game in a state it doesn't fully recover from on its own, which the first cluster's timing is at least suggestive of. Needs the project owner to report, at the next occurrence, exactly what they were doing right before it played (walking toward a specific boundary/bridge vs. having just used teleport) to distinguish the two.

### 9. Entity-nav reported a kidnapped, story-absent NPC (Krane) as present and "in interaction range"

- Date: 2026-07-29
- Location: Pokémon HQ Lab, 2nd floor (`floor_id` 0x8D)
- Story point: after Krane has been kidnapped (Krane is canonically absent from every map at this point in the story)
- Game context: field, entity-nav NPC category
- What I attempted: locating and approaching NPCs via entity-nav, per the project owner's report that something was wrong with the NPC locator
- What was spoken: Krane described as a nearby NPC, including "in interaction range" at close distance
- Information I needed: whether floor_character's own "visible" bit (the only signal `NPCMemorySource.npcs()` read at the time) reliably reflects whether a named character is truly present right now
- What prevented or complicated progress: the project owner reported this directly and firmly disputed my initial (wrong) conclusion that the visible-bit toggling was "correct dynamic behavior" — their report was the only reason this was caught, since the static bit alone gave no indication anything was wrong
- Completely blocked: no — Level 2 (actively misleading information: a blind player has no other way to know an NPC isn't really there, unlike a sighted player who'd simply see an empty room)
- Reproduction steps (historical, now fixed): stand in a room containing a story-hidden named character's `floor_character` placement record; entity-nav would report them as present
- Relevant save/save-state: current live save (post-Krane-kidnapping story point)
- Suggested workstream: Navigation and spatial awareness
- Severity: 2
- Temporary workaround: none needed — fixed
- Permanent accessibility requirement: entity-nav must never report a story-inactive character as a present, locatable, interactable NPC
- Technical notes: root-caused via static disassembly, then confirmed live twice (two independent rooms, two independent story-hidden characters, zero false positives/negatives across 18 live-read NPC records). `floor_character`'s own visible bit (`floorCharacterBiosGetVisibility`, byte 0 bit 0x80) is static per-room placement data and does not track story state — the game's actual live-presence signal lives in a completely separate runtime table: the `people` actor array (`_pPeopleWorkTop` / `_people_num`, addresses confirmed against xd-decomp's own `config/GXXE01/symbols.txt`: `.sbss:0x804EBBBC` / `.sbss:0x804EBBB8`), stride `0x1B0`, with an "occupied" byte at `+0x00` and the real model-visibility ("disp") byte at `+0x0D` (confirmed via `peopleBiosSetDispFlag`, which calls `GSmodelSetVisibility` directly — [peopleBios.s:413](../xd-decomp/build/GXXE01/asm/game/pxdvs/app/people/peopleBios.s:413)). Each live actor carries an identity pair at `+0x14`/`+0x18` that matches back to a `floor_character` record's room-relative index (`+0x18` == index; `+0x14` == a per-room group ID, confirmed non-zero for every real room sampled — `identity_a == 0` is the game's own disassembly-confirmed sentinel for the special/global partner-follower slots, per `floorCharacterBiosFindByResID`'s explicit `groupID == 0` branch to `_globalCharacter`, so those are excluded rather than mistaken for room NPCs). `NPCMemorySource._live_visibility_by_index()` now reads this table and its `disp` bit overrides the stale static bit whenever a live record exists for that index, falling back to the static bit only if no live actor is found. Live-confirmed on Lab 2F: index 2 and index 3 (Krane) both flipped from static `visible=True` to the correct `visible=False` once cross-referenced against the live `disp` bit.
- Resolution status: **Implemented, live-tested, regression-tested.** New profile fields (`people_work_*`) in `profile.py`; new `NPCMemorySource._live_visibility_by_index()` in `npc_beacons.py`; 4 new tests in `test_npc_beacons.py::NPCMemorySourceTests` (472 total passing). Live-reverified against the running game with the actual production code path (not a raw dump) immediately after the fix. Requires a narrator restart to take effect in the live session.

### 10. Narrator crashed outright on a "ready to purify" notification

- Date: 2026-08-04
- Location: Mt. Battle (trainer battles against Hardig and Goling logged immediately before)
- Story point: a Shadow Pokémon's Heart Gauge had reached fully open
- Game context: overworld/battle, a progress notification appearing on screen
- What was spoken: nothing — the companion process died
- Completely blocked: **yes, totally.** Every accessibility feature stopped at once, and relaunching walked straight back into the same still-displayed notification and died again. Three crash-relaunch cycles at 01:09:50, 01:10:03 and 01:10:56.
- Reproduction steps: have a party Pokémon whose Heart Gauge is ready, and let the "can now be purified" notification appear.
- Suggested workstream: Infrastructure, safety, testing, and distribution
- Severity: **0** — this is the most severe failure mode the project has: not a missing announcement, but the loss of every announcement.
- Permanent accessibility requirement: a single reader raising an unexpected exception must not take the whole narrator down with it.
- Technical notes: `AttributeError: 'PartySlot' object has no attribute 'nickname'` in `menus.progress_notification_focus`. Two bugs in one expression: `PartySlot` exposes `raw_nickname`, never `nickname`, and had no `species` field at all. The `slot.species` comparison would have raised too had the `slot.nickname` default argument not raised first.
- **Why the tests did not catch it:** `ProgressNotificationTests`' party double was `SimpleNamespace(species=25, nickname="SPARKY")` — a shape the real class has never had. The feature was written against an interface that existed only in the test file, so the tests passed for the entire life of the feature while the code could never once have run. The fixture now builds a real `PartySlot`.
- Resolution status: **Fixed 2026-08-04, not yet live-tested.** `species` added to `PartySlot` as a defaulted trailing field (inserting it in its natural position renamed every positional argument after it and broke 34 construction sites); `progress_notification_focus` corrected and now speaks the name through `health.speech_name` like every other party name. 743 tests pass. Needs confirming live the next time a purification/evolution/item notice appears.
- Follow-up worth considering separately: the whole-narrator-dies-on-one-reader-exception behaviour is the real severity here. The `AttributeError` was the trigger, not the reason a single bad reader silenced everything.
