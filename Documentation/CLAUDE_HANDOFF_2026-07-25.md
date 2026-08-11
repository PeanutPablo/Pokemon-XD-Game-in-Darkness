# PokÃ©mon XD Accessibility â€” Claude Handoff

> **Current addendum (2026-08-03):** The Shadow Pokémon research pass is documented in [SHADOW_POKEMON_SYSTEM_INVESTIGATION.md](SHADOW_POKEMON_SYSTEM_INVESTIGATION.md), with its [memory map](SHADOW_POKEMON_MEMORY_MAP.md), [move table](SHADOW_MOVE_TABLE.md), [prior-notes audit](SHADOW_POKEMON_CLAUDE_NOTES_AUDIT.md), and [live-test plan](SHADOW_POKEMON_LIVE_TEST_PLAN.md). Documentation only; production accessibility code was deliberately unchanged. The checkpoint below remains historical.

**Checkpoint:** 2026-07-25, America/New_York  
**Prepared for:** Claude, for continuation on 2026-07-26  
**Prepared and signed by:** Codex (OpenAI)

## 1. Paths and launch state

- Project: `C:\Users\psych\Documents\My Games\pokemon xg accessibility\PokemonXGAccessibility`
- Dolphin and game image:
  `C:\Users\psych\OneDrive\Desktop\apps\Dolphin-x64`
- Dolphin executable:
  `C:\Users\psych\OneDrive\Desktop\apps\Dolphin-x64\Dolphin.exe`
- Game image:
  `C:\Users\psych\OneDrive\Desktop\apps\Dolphin-x64\Pokemon XD - Gale of Darkness (USA).rvz`
- Canonical production entry point:
  `Companion\run_battle_narrator.py`
- Single-instance accessible entry point:
  `Companion\run_accessible_pokemon_xd.py`
- Combined launcher:
  `Launch Pokemon XD Accessible.cmd`
- Desktop shortcut:
  `C:\Users\psych\OneDrive\Desktop\PokÃ©mon XD Accessible.lnk`
- Production log:
  `Companion\logs\battle_narrator_phase1b.log`

The Desktop shortcut starts the production companion silently and then boots
the exact RVZ in Dolphin. The accessible entry point uses the named mutex
`Local\PokemonXGAccessibility.BattleNarrator`, so repeated launches do not
create duplicate narrators.

At this checkpoint Dolphin is running as PID 13348 and the production narrator
is running as PID 28988. The game has just finished a Quick Battle victory.
The latest downstream messages are unsupported victory/result messages:

- message 20300: `Player defeated [Foe Tr Class 34] [Foe Tr Name 35]!`
- message 40001 from a non-`fight_common` table

These are intentionally silent. Do not invent their substitutions.

## 2. Test baseline

Run the complete suite from the project root with the bundled Python:

```powershell
$env:PYTHONPATH='Companion'
& 'C:\Users\psych\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  -m unittest discover -s Companion/tests -p 'test_*.py' -q
```

**Current result: 138 tests passing.**

The checked-in `Companion\.venv` contains the required native packages but its
original Python executable path is stale. The working runtime is the bundled
Python 3.12 executable above, with these paths when launching production:

```text
PYTHONPATH=<project>\Companion;<project>\Companion\.venv\Lib\site-packages
```

Preserve unrelated existing changes. This worktree contains extensive earlier
research and untracked production files; do not use destructive Git cleanup.

## 3. Production architecture and safety

The production companion remains external and read-only:

- Reads Dolphin emulated memory through `dolphin_memory_engine`.
- Never writes game memory.
- Uses bounded pointer/range validation.
- Resolves live strings against locally extracted game data where applicable.
- Uses stable double-sampling for battle messages and settled HP/status events.
- Deduplicates unchanged menu identities.
- Menu focus and battle events interrupt obsolete menu speech.
- Unsupported, ambiguous, invalid, or out-of-range data remains silent.
- Lifecycle reset clears reader state and re-arms narration.

Key files:

- `Companion\battle_narrator\phase1b_app.py`
- `Companion\battle_narrator\phase1b_lifecycle.py`
- `Companion\battle_narrator\menus.py`
- `Companion\battle_narrator\narrator.py`
- `Companion\battle_narrator\resolver.py`
- `Companion\battle_narrator\health.py`
- `Companion\battle_narrator\hotkeys.py`
- `Companion\battle_narrator\profile.py`
- `Companion\battle_narrator\speech.py`

## 4. Ordinary battle narration

Implemented production behavior includes:

- Battle command menu narration.
- Ordinary four-slot move-menu narration with current/max PP.
- Verified live move-use messages.
- Poison application and poison damage.
- Fainting message 20021 (`Pokemon 15`) through `attack_mons`.
- Stat changes using messages 20243, 20244, 20246, and 20247.
  Target-side messages 20244/20247 use `tsuika_mons`; attacker-side
  messages 20243/20246 use `attack_mons`.
- Rock Tomb's target-side Speed drop is therefore supported.
- Loss message 20024: `[player] is out of usable PokÃ©mon!`
- Battle HP loss and recovery narration.
- Control+Shift+H active-battler summary.

Rock Tomb was correlated live with message 20247 and the target actor source.

Tri Attack status changes are tracked from the stable embedded PokÃ©mon
condition field rather than an unresolved transient message:

- 5: paralyzed
- 6: burned
- 7: frozen

The condition must appear in two identical samples. Initial conditions and a
condition already present on a replacement PokÃ©mon are baseline-only, avoiding
false status announcements. Poison is not duplicated by this tracker because
poison already has an authoritative battle-message path.

## 5. HP, healing, faint/empty slots, and summaries

`BattlerSample` now includes:

- identity
- nickname
- current HP
- maximum HP
- major condition
- level

Verified embedded PokÃ©mon offsets:

- level: `+0x11`
- condition: `+0x16`
- current HP: `+0x04`
- maximum HP: `+0x90`

Settled healing includes absolute and percentage values. Example:

```text
Player Kingdra recovered 30 HP, 19 percent, now 79 of 155, 51 percent.
```

Damage retains the percentage-first format:

```text
Mew lost 22 percent. 78 percent remaining.
```

Control+Shift+H now includes level, HP, percentage, fainted state, and major
status. It double-samples the entire signature, including level, and suppresses
the summary if battlers change between samples.

Replacement safety is covered:

- fainted battler followed by an empty slot clears state;
- a healthier replacement entering the same logical slot is baseline-only and
  is never announced as healing;
- a replacement carrying an existing major condition is baseline-only;
- simultaneous battlers and drain damage/healing remain independent.

## 6. VS Mode menu path

Window IDs are reused elsewhere, so no supported VS menu uses a single ID as
its identity.

Verified path:

1. `281 -> 280`: VS Mode
   - Quick Battle
   - Group Battle
   - Cancel
2. `281 -> 164`: Quick Battle
   - Battle VS CPU
   - 2-Player Battle
   - Cancel
3. `281 -> 164 -> 262`: challenge level
   - Ultimate
   - Hard
   - Normal
   - Easy
   - Cancel
4. `281 -> 165`: confirmation
   - YES
   - NO
   - visible prompt: `Start battle with the selected PokÃ©mon?`

Quick Battle's authoritative cursor is the byte at `0x804349CF`:

- 0: Battle VS CPU
- 1: 2-Player Battle
- 2: Cancel

The challenge and confirmation menus use the signed sum of standard cursor
base at window `+0x9C` and cursor offset at `+0x9E`.

Earlier mappings for IDs 278 and 279 were removed/suppressed because those IDs
are reused by the title and Options menus. Title/Options contexts must remain
silent until independently mapped.

## 7. VS direct-button battle UI

VS Quick Battle does not use the ordinary move-selection window.

Verified contexts:

- Parent/window pair: `162 -> 158` for the direct move-button panel.
- Parent/window pair: `162 -> 160` for `Which PokÃ©mon?` target selection.
- Decorative windows 66 and 68 may appear before the pair or after it.
  The production signature accepts only the two live-verified arrangements
  and suppresses an unknown deeper child.

### Move structure

Window 158's allocation stores:

- one initial actor-name pointer;
- four move records beginning at allocation `+0x04`;
- record stride `0x0C`;
- live move-name pointer at record `+0x00`;
- type-name pointer at record `+0x04`;
- type ID at record `+0x08`;
- maximum PP at record `+0x0A`;
- current PP at record `+0x0B`.

The acting `FightOutPokemon` pointer appears in one of a small set of
allocation fields because two live allocation layouts alternate. Production
searches only offsets:

```text
0x40, 0x44, 0x48, 0x4C, 0x50, 0x54, 0x58, 0x5C
```

Exactly one candidate must match the current active-battler pointers.
Zero or multiple matches are silent. The VS `FightPokemon` data is embedded at
actor `+0x08`.

Each live move name is checked against the local move ID/name, and menu PP is
checked against PokÃ©monWaza current PP.

Controller-neutral move mapping:

- C-stick up: first displayed move
- C-stick right: second displayed move
- C-stick down: third displayed move
- C-stick left: fourth displayed move

Live-validated underlying output before controller-neutral wording:

```text
Mew moves. I, Dizzy Punch, 3 of 10 PP. L, Aerial Ace, 5 of 20 PP.
K, Reversal, 5 of 15 PP. J, Endure, 5 of 10 PP.
```

Production now speaks the equivalent GameCube form:

```text
Mew moves. C-stick up, Dizzy Punch, 3 of 10 PP.
C-stick right, Aerial Ace, 5 of 20 PP.
C-stick down, Reversal, 5 of 15 PP.
C-stick left, Endure, 5 of 10 PP.
```

The user's keyboard profile maps I/K/J/L to C-stick up/down/left/right, but
production intentionally speaks GameCube controls for portability.

### Target structure

Target identities come from stable battle-status windows, not from the
active-battler array, because that array was observed compacting after a faint:

- player status windows: 55 and 64;
- upper opponent status window: 56;
- lower opponent status window: 65.

Controller-neutral target mapping:

- D-pad up: upper opponent;
- D-pad down: the other player PokÃ©mon;
- D-pad right: lower opponent.

Missing/fainted status windows are omitted. Live example after Raikou fainted:

```text
Targets. D-pad up, Latios. D-pad right, Kangaskhan.
```

The teammate/D-pad-down entry was correctly omitted; no stale Raikou target
was spoken. Actor identity is retained through the short transition between
windows 158 and 160, then replaced by the next verified move panel or cleared
by lifecycle reset.

## 8. Fainting and whiteout â€” important current caveat

Newly implemented and automated:

- message 20022: `[Pokemon 16] fainted!`
- message 20025: `[Player Battle 19] whited out!`
- message 20021 remains the attacker-side faint variant.
- message 20024 remains `[player] is out of usable PokÃ©mon!`

Automated expected outputs:

```text
Salamence fainted!
David whited out!
```

**Do not consider target-side fainting fully live-validated yet.**

After implementation, a live message 20022 occurred at approximately
22:47:15. Its transient `tsuika_mons` pointer was already zero during every
stable sample, so production safely rejected it:

```text
SAMPLE_REJECTED ... message_id=20022 reason=FightOutPokemon:
invalid address 0x00000000
```

This means the ID/opcode/template are authoritative and automated coverage
passes, but the chosen live actor source does not survive long enough in this
case. The next task should resolve 20022's actor without guessing. Safest
candidate approach:

1. correlate the faint message with the settled HP transition to zero;
2. retain the exact `BattlerIdentity`/nickname from the HP tracker long enough
   for message 20022;
3. have one shared deduplication path so HP and message narration cannot both
   say `fainted`;
4. verify simultaneous faints and replacements before production speech.

Whiteout message 20025 was previously observed live and was formerly
suppressed. Its new player-name composition is automated but has not yet been
re-triggered live after implementation.

## 9. Known unsupported or follow-up work

- Fix the live actor source for message 20022 as described above.
- Re-trigger and live-validate message 20025.
- Victory message 20300 is unsupported; trainer-class/name opcodes 34/35 and
  controls 93/94 are not verified.
- Result message 40001 is outside the `fight_common` table and unsupported.
- Title menu and Options menu remain intentionally silent because IDs 278/279
  are reused and no stable context signature has been completed.
- Group Battle and later VS paths should not be mapped without independent
  live verification.
- The active-battler array was seen compacting after a faint. Do not assume its
  indices always correspond to fixed visual/team positions. VS targeting
  already avoids that assumption through status-window identities.
- Do not clean older research artifacts or unrelated changes as part of a
  feature slice.

## 10. Tests added or expanded

Coverage now includes:

- VS context signatures and reused-ID suppression;
- every VS/Quick Battle/challenge/confirmation option;
- initial focus, movement, deduplication, invalid cursors, nesting priority,
  deeper-child suppression, close/reopen re-arming;
- all four VS direct move buttons, current/max PP, local/live name agreement,
  both live allocation arrangements, actor unique matching;
- target names, missing teammate omission, target screen without prior actor;
- ordinary and target-side stat messages, including Rock Tomb;
- stable paralysis/burn/freeze changes and replacement suppression;
- HP loss, healing percentages, simultaneous battlers, drain effects,
  faint-to-empty, healthier replacement, and invalid data;
- Control+Shift+H level/status/HP summary and between-sample suppression;
- message 20021 attacker faint, 20022 target faint, 20024 loss, and 20025
  whiteout.

Current files modified for the latest production work:

- `Companion\battle_narrator\health.py`
- `Companion\battle_narrator\hotkeys.py`
- `Companion\battle_narrator\menus.py`
- `Companion\battle_narrator\narrator.py`
- `Companion\battle_narrator\profile.py`
- `Companion\battle_narrator\resolver.py`
- `Companion\run_accessible_pokemon_xd.py`
- `Companion\tests\test_battle_hp_summary.py`
- `Companion\tests\test_battle_narrator.py`
- `Companion\tests\test_phase1e_menus.py`
- `Companion\tests\test_phase1f_health.py`
- `Launch Pokemon XD Accessible.cmd`

## Signature

Prepared from production code, automated tests, live Dolphin inspection, and
the production narrator log.

**Signed: Codex (OpenAI)**  
**Date: 2026-07-25**

# Addendum â€” Overworld NPC Dialogue Vertical Slice (2026-07-26)

General ordinary NPC dialogue is now production-integrated. Do not restart discovery from `_MsgID` or window ID 82 alone; both were disproven as authoritative visibility markers. Read `Documentation/OVERWORLD_NPC_DIALOGUE_VERTICAL_SLICE.md` first. It contains the verified generic manager/task offsets, current-page pointers, completion and closure signatures, control-code policy, exact two-page live NPC fixture, transient-pointer race and fix, 169-test result, and remaining unsupported dialogue subtypes.

Key production files: `Companion/battle_narrator/dialogue.py`, `profile.py`, `speech.py`, `phase1b_lifecycle.py`, and `phase1b_app.py`. Focused tests are in `Companion/tests/test_dialogue.py`.

Production narrator was stopped after live validation, per the slice instructions. Dolphin remained running.

## Addendum signature

Prepared from production code, live Dolphin memory, NVDA logs, captured encoded pages, automated tests, and direct blind-user confirmation.

**Signed: Codex (OpenAI)**  
**Date: 2026-07-26**
# Addendum — NPC Proximity Sounds (2026-07-26)

Generic NPC discovery and proximity sounds are production-integrated. Read `Documentation/NPC_PROXIMITY_SOUNDS.md` before changing this feature. It records the verified leader-model position chain, generic floor-character table, visibility/talk filtering, stable sound assignment, queue/rearm rules, CC BY 4.0 attribution, and the 172-test regression result.

Key production file: `Companion/battle_narrator/npc_sounds.py`.

## Addendum signature

Prepared from static disassembly, live read-only Dolphin memory, production code, and automated tests.

**Signed: Codex (OpenAI)**  
**Date: 2026-07-26**

# Addendum — Stereo and Vertical NPC Beacons (2026-07-26)

NPC sounds were upgraded after blind-user validation showed the original 24-bit, one-shot cues were inaudible and too easy to miss. Production now uses amplified 16-bit sources and repeating spatial beacons for every visible, talkable NPC within 120 units. Pan follows the player model's live Y rotation (confirmed radians); distance controls gain; positive NPC/player Y difference raises pitch and negative difference lowers it. Live floor 141 validation logged all six visible NPCs with distinct pans. Full suite: 175 passing.

Key implementation: `Companion/battle_narrator/npc_beacons.py`. Read `Documentation/NPC_PROXIMITY_SOUNDS.md` before modifying it.

## Addendum signature

Prepared from blind-user audio confirmation, live read-only Dolphin pose/NPC data, stereo render inspection, live production logs, and automated tests.

**Signed: Codex (OpenAI)**  
**Date: 2026-07-26**

# Addendum — Camera-Fixed Joystick Mapping (2026-07-26)

Per blind-user correction, NPC stereo and pitch are camera-relative, not character-facing or world-height-relative. The active camera pointer is `0x804EAEE0`; its Euler rotation begins at `+0x84` and Y yaw at `+0x88` is radians. Screen-left/right drives stereo pan. Projected camera-forward distance (the direction reached by holding joystick-up) raises pitch; camera-backward distance lowers it. World Y is deliberately ignored. Live production logs confirmed dynamic pan and pitch values. Full suite remains 175 passing.

## Addendum signature

Prepared from static disassembly, live active-camera memory, production logs, automated tests, and direct blind-user requirements.

**Signed: Codex (OpenAI)**  
**Date: 2026-07-26**

# Addendum — Half Volume and Named Interaction Zone (2026-07-26)

Beacon gain is now multiplied by 0.5. The generic floor-character record's people-info ID (`+0x06`) resolves through `peopleInfoData`; its `+0x24` float is the game's per-entity talk distance. Entering that radius emits one NVDA message, “Name, interaction available,” and leaving rearms it. Character name index `+0x08` resolves through common.rel PeopleIDs index 2 and string table index 136; unnamed entries fall back to “NPC.” Full suite: 177 passing. Live logs confirm beacon gains are exactly halved.

Key name loader: `Companion/battle_narrator/entity_names.py`.

## Addendum signature

Prepared from static disassembly, game-owned common.rel tables, live production logs, and automated tests.

**Signed: Codex (OpenAI)**  
**Date: 2026-07-26**

# Addendum — Interaction Collision Fix and Distance Cadence (2026-07-26)

The initial interaction trigger failed because every tested NPC's raw talk distance was 3.0 while collision held the adjacent player center at 3.05. Production now adds a verified 1.5-unit collision allowance. Live validation immediately produced NVDA: “Lily, interaction available.” Each NPC now has an independent distance-based deadline: about 0.55 seconds at zero distance to about 4 seconds at 120 units, subject to non-overlapping playback. Camera-forward/back pitch is capped at ±6 semitones instead of ±12. Full suite remains 177 passing.

## Addendum signature

Prepared from live player/NPC/talk-distance memory, NVDA production logs, cadence logs, and automated tests.

**Signed: Codex (OpenAI)**  
**Date: 2026-07-26**

# Addendum — Wider Beacon Frequency Range (2026-07-26)

Per user tuning, the independent per-NPC repeat interval now scales from approximately 0.30 seconds at zero distance to 6.0 seconds at 120 units, using the existing nonlinear distance curve. The ±6-semitone pitch cap is unchanged. Full suite remains 177 passing.

**Signed: Codex (OpenAI)**  
**Date: 2026-07-26**

# Addendum — Rapid Interaction Pulse and Named Immediate Dialogue (2026-07-26)

Inside the effective interaction radius, that NPC receives scheduler priority, a 0.18-second deadline, and a 0.12-second playback window to create a rapid pulse. When `DialogueReader.active` is true, lifecycle polling calls `SpatialWavePlayer.stop()` and suspends every beacon. Dialogue no longer waits for printing/advancing flags to settle: the already-prepared full page buffer is decoded on first appearance, while the verified page key still deduplicates it. Spoken pages are prefixed from the shared current `NPCInteractionContext` (for example, “Lily: ...”). Full suite: 178 passing.

## Addendum signature

Prepared from verified dialogue buffers, live interaction context, production implementation, and automated tests.

**Signed: Codex (OpenAI)**  
**Date: 2026-07-26**

## Reserved Distinct Sounds for Overworld Entity Categories

At the user's direction, additional overworld categories must be aurally distinct. `battle_narrator/npc_beacons.py` now owns `ENTITY_SOUND_FILES`, with unique files for ordinary NPCs, items, doors, warps, nurses/healing stations, store clerks, and Poké Boxes. Nurses and clerks override the ordinary-NPC sound. The same spatial/cadence/dialogue-suppression rules apply to every category. Live coordinate discovery for non-character interaction regions is still pending a readable running game.

Documented by **Codex (OpenAI)** on **2026-07-26**.
## Title, Main Menu, and Options Accessibility

Production `ProductionMenuReader` now supports the pre-game title flow. Static disassembly confirmed title window ID 17, options window ID 279, standard `tagWINDOW_WORK +0x9C/+0x9E` cursor fields, title states 41 (Press Start) and 42 (selection context), audio mode at `0x8044DA73 & 0x04`, and vibration through game-data root `0x804E88D8`, save `+0xA8`, no-vibration byte `+0x21`. It speaks the title prompt, main-menu focus, and options focus plus live values. Context gating prevents IDs 17/279 from colliding with VS menus. The rejected historical stack byte `0x804FFCEF` is not used. Full suite: 182 passing. Live title validation confirmed state 41 while unrelated window ID 51 was present; production then logged and spoke the Press Start prompt immediately. Main/options traversal still needs user exercise. See `TITLE_MAIN_OPTIONS_ACCESSIBILITY.md`.

Implemented and documented by **Codex (OpenAI)** on **2026-07-26**.
## Correction to Title/Menu Accessibility

Blind live testing disproved the first title interpretation. State 41 is post-Start and no longer speaks “Press Start.” Live capture proved window 17 is the parent and window 278 is the focused title child; main focus now requires state 42 and direct signature `(17, 278)`. Title Memory Card notices are active GSmsg tasks during states 32/200. Production resolves them through local `dol_strings.json`, strips control tags, and deduplicates by message ID. Live message 129 is “The Memory Card in Slot A has been read!” ID 152 has a clearly marked provisional fallback, “Checking the Memory Card in Slot A,” because it is absent from the extracted table. Full suite: 183 passing.

Corrected and documented by **Codex (OpenAI)** on **2026-07-26**.
## Live manual correction - actual main menu and Options (2026-07-26)

A Codex-driven Dolphin pass disproved the remaining state/label assumptions. The actual main menu is `_menuTitleStatus == 41`, with direct window signature `(17, 278)` and the cursor on child 278. State 42 is not the live selection state in this build. The visible menu has five entries in cursor order: New Game, Continue, VS Mode, Options, Exit. Production and tests now use those exact facts.

The corrected production companion spoke `Continue`, `Options`, and `Exit` from live cursor movement. Opening Options produced window 279 and immediate `Sound` focus speech. During the same pass, active title GSmsg 129 spoke `The Memory Card in Slot A has been read!` before the main-menu focus returned. The diagnostic keyboard driver was also corrected to provide Windows extended-key scan codes for arrow inputs; without those flags, short Dolphin navigation presses were unreliable.

Visible inspection established that a clear `0x04` audio-mode bit corresponds to Stereo and a set bit corresponds to Mono; the previous polarity was reversed. Production now uses the corrected polarity. One remaining reverse-engineering item is the Options screen's unsaved/staged left-right value: the global audio byte represents the committed setting, so Claude should locate the staged option-work field before claiming that every unsaved Sound toggle is announced immediately.

Automated validation after these corrections: 212 tests passing. The title/menu-focused module contains 73 passing tests, including the fifth Exit entry.

Investigated, implemented, live-tested in Dolphin, and documented by **Codex (OpenAI)** on **2026-07-26**.

## Re-entrant title-screen announcement (2026-07-26)

The Press Start announcement is now tied to the live title-screen transition rather than to process startup. Production requires `_menuTitleStatus == 32` and `_menuTitleStartStatus == 1` at `0x804EAA30`. It announces `Pokemon XD: Gale of Darkness. Press Start.` once per continuous appearance, clears its identity when that screen disappears, and announces again when the player backs out to it or returns to it after skipping the intro.

Known and unknown active GSmsg title tasks suppress the Press Start prompt. This preserves Memory Card notice priority and prevents overlapping or misleading title speech. Automated coverage verifies initial speech, unchanged-state deduplication, re-announcement after a screen transition, and suppression during an unknown active title message. Full suite: 214 passing.

Implemented and documented by **Codex (OpenAI)** on **2026-07-26**.

## New Game confirmation accessibility (2026-07-26)

Live Dolphin mapping established the New Game confirmation signature: direct windows `(17, 51, 53)` while title state is 41. Window 51 owns the visible prompt and window 53 owns the signed standard cursor; cursor 0 is Yes and cursor 1 is No. Active GSmsg task 17113 is the prompt `Is it okay to start a new Story?`

Production now requires the full direct signature before interpreting window 53, preventing reused IDs elsewhere from being mislabeled. Initial focus and every Yes/No cursor change speak the prompt together with the current choice. Live production verification announced `Is it okay to start a new Story? No` on the actual screen. The full suite has 216 passing tests.

The preset character-name list and general naming keyboard remain pending live mapping. Selecting Yes was intentionally not automated without explicit user approval because beginning a new story could affect existing progress.

Investigated, implemented, live-tested, and documented by **Codex (OpenAI)** on **2026-07-26**.

## Character name list and naming keyboard accessibility (2026-07-26)

With explicit user authorization, Codex entered the New Game flow and mapped both naming screens live. The preset-name screen is the direct window pair `(104, 101)`. Its signed standard cursor entries are New Name, Michael, David, Adam, and Exit. The general keyboard is the direct pair `(104, 102)` and uses the same `+0x9C/+0x9E` signed cursor sum.

The keyboard cursor table contains A-Z; digits 1-9 and 0; exclamation mark, question mark, male symbol, female symbol; left/right double quotes; left/right single quotes; slash, hyphen, ellipsis, period, comma; Back; and Done. Production requires the verified parent/child pair before assigning these labels.

The live composed player name is a seven-character UTF-16BE/GSchar buffer at `0x80429794`. Keyboard focus identity includes the composed name, so selecting a character or deleting one announces the updated text even when the cursor remains on the same key. Speech format is `<focused key>. Name: <current text>`, using `blank` when empty. Live production verification announced `A. Name: AB`, `A. Name: A`, and `A. Name: blank` while temporary test characters were entered and erased. No temporary name was confirmed.

The full automated suite now has 220 passing tests. Coverage includes the verified preset-name pair, keyboard letters/symbols/actions, rejection outside the verified parent context, and re-announcement when entered text changes without cursor movement.

Investigated, implemented, live-tested in Dolphin, and documented by **Codex (OpenAI)** on **2026-07-26**.

## Correction - naming keyboard hover cursor (2026-07-26)

Blind live testing showed that window 102's ordinary `+0x9C/+0x9E` cursor remains zero while the keyboard highlight moves, causing the first implementation to announce A regardless of the hovered key. Controlled scan-code movement and bounded memory comparison identified the actual one-based hover column at `0x804EA7A4` and zero-based hover row at `0x804EA7A8`.

Production now maps this live row/column pair directly across all alphabet, number, symbol, blank, Back, and Done positions. Hover identity changes immediately with either coordinate; selection is not required. Live verification spoke `Q. Name: blank` and `G. Name: blank` as the cursor moved over those letters. It also correctly followed Back, Ellipsis, Hyphen, right double quote, question mark, and blank positions. The composed-name buffer remains part of identity, so edits without cursor movement are still announced.

The full suite remains 220 passing, with the keyboard test changed from the invalid standard-cursor assumption to verified live-coordinate coverage.

Corrected, live-tested, and documented by **Codex (OpenAI)** on **2026-07-26**.

## Keyboard hover speech simplification (2026-07-26)

Per blind-player feedback, naming-keyboard hover speech now contains only the highlighted key label. It says `A`, `B`, `Q`, and so on rather than appending the composed-name value on every movement. Coordinate tracking and entered-buffer identity remain intact, but the emitted hover text is deliberately concise. Live logs confirmed rapid G, H, I, and S hover transitions after restart. Full suite: 220 passing.

Adjusted and documented by **Codex (OpenAI)** on **2026-07-26**.

## General Yes/No prompt accessibility (2026-07-26)

Live name confirmation established that Yes/No prompts are reusable direct windows: text window 51 immediately followed by choice window 53. On the naming screen this pair is layered after `(104, 102)`, and active GSmsg task 15130 displays `Is <entered name> OK?`.

Production now recognizes any direct `(51, 53)` pair, regardless of the surrounding screen. It reads the active GSmsg task, resolves locally extracted prompt text when available, strips display tags, and appends the live highlighted choice from window 53 (`0 = Yes`, `1 = No`). Dynamic task 15130 substitutes the live UTF-16BE name buffer; task 17113 retains the verified New Story wording. The narrower `(17, 51, 53)` New Game rule remains higher priority for its already-verified behavior.

Live production verification announced `Is MC O OK? Yes` on the actual naming confirmation. Automated coverage also verifies a different local prompt (`Your progress will be saved. Is that okay? No`). Full suite: 222 passing.

This generalizes every prompt that uses the verified 51/53 pair and an active resolvable GSmsg. Any future prompt using a different choice window must be mapped separately rather than guessed.

Implemented, live-tested, and documented by **Codex (OpenAI)** on **2026-07-26**.

## Separate hover and typed-name feedback (2026-07-26)

Keyboard navigation remains concise: moving the highlight speaks only the key label. A change to the live composed-name buffer now produces a separate `Name: <text>` announcement, or `Name: blank` after deleting the final character. This restores essential typing confirmation without making every hover verbose. If cursor and text change within one poll, the entered-name change takes priority; the next hover transition speaks its key normally. Yes/No name confirmation continues to speak `Is <name> OK?`.

Focused and full automated suites pass: 222 tests.

Adjusted and documented by **Codex (OpenAI)** on **2026-07-26**.

## Correction - zero-based keyboard columns and Space keys (2026-07-26)

Live visual comparison disproved the first column interpretation: `0x804EA7A4` is zero-based (`0..9`), not one-based. At row 1, column 2 visibly highlights M; the old mapping incorrectly announced L. Production now indexes every row directly by the zero-based column. Live verification matched visible M, then L after one left movement, then B after moving up.

The empty-looking selectable cells are Space keys, not inert blanks. They enter a space into the composed-name buffer and now announce `Space`. Alphabet, digit, punctuation, gender-symbol, Back, and Done coordinates were shifted/corrected consistently. Full suite remains 222 passing, including explicit Space coverage.

Corrected, visually verified in Dolphin, and documented by **Codex (OpenAI)** on **2026-07-26**.

## Exact LEON keyboard validation (2026-07-26)

After correcting the zero-based columns, Codex manually typed LEON through Dolphin without confirming the final name. Live production speech and buffer transitions were: `L` then `Name: L`; `E` then `Name: LE`; `O` then `Name: LEO`; `N` then `Name: LEON`. This validates both the corrected alphabet coordinates and the separate hover-versus-entry feedback on a complete requested name.

Validated and documented by **Codex (OpenAI)** on **2026-07-26**.

## Beacon volume quarter-scale and reliable nearest interaction name (2026-07-26)

Per user feedback, beacon gain was halved again: the distance curve now uses a 0.25 maximum multiplier instead of 0.50. Live restart verification showed the same nearby beacon fall from gain 0.38 to 0.19, exactly half its prior playback gain.

The interaction announcement previously depended only on set entry. That could miss a newly relevant entity when the player remained inside overlapping interaction zones and the nearest target changed. Production now tracks the nearest in-range interaction identity and announces whenever that nearest identity changes. `NPCInteractionContext.name` follows the same nearest entity for dialogue prefixes. New diagnostics record floor, NPC index, name ID, resolved name, and distance for every interaction announcement.

Tests verify exact-radius single announcement, nearest-target changes from Krane to Lily while both remain in range, and the new 0.25 maximum gain. Full suite: 223 passing. At live restart the nearest current NPC was 28.80 units away, outside the interaction radius, so no false name announcement was emitted.

Implemented, tested, live-verified, and documented by **Codex (OpenAI)** on **2026-07-26**.

## Constant-duration pitch shifting (2026-07-26)

Beacon pitch no longer changes playback speed. The old renderer changed the WAV sample rate to `rate * pitch`, which necessarily shortened high-pitched cues and lengthened low-pitched cues. Production now shifts the waveform spectrum at the original sample count and writes the original sample rate. Stereo pan and gain are applied afterward. Scheduler busy duration also uses the source duration directly rather than dividing by pitch.

Live output verification: source and pitched render were both 44,100 Hz, 16,365 frames, and 0.3711 seconds. Automated rendering verifies preserved rate, frame count, 16-bit samples, and stereo output. Full suite remains 223 passing.

Implemented, live-verified, and documented by **Codex (OpenAI)** on **2026-07-26**.

## Foreground-only beacon playback (2026-07-26)

Positional entity beacons now play only while Dolphin.exe owns the foreground window. Losing focus immediately stops the current beacon and clears its timing and interaction state. Returning focus resumes from a clean schedule, avoiding queued or rapid catch-up sounds. This gate applies to beacon audio; it does not disable the companion's other accessibility readers.

Implementation: NPCSoundReader accepts an injectable foreground predicate, while production uses WindowsForegroundProcess to identify the foreground executable. Automated coverage verifies immediate one-time stopping while unfocused and clean playback after focus returns.

Signed: **Codex (OpenAI)** — 2026-07-26

## Elevator beacon and map announcements (2026-07-26)

Implemented a distinct elevator beacon and automatic room announcements. Static analysis of the user's extracted Pokémon XD/XG assets identified the Pokémon HQ Lab 1F elevator as common interaction point 687 (room 0x8C, collision region 10) with collision-center coordinates x=0.0, y=15.0, z=-140.00003. Lab 2F uses interaction region 10 at x=0.0, y=15.0, z=16.1. These are injected as named Elevator entities and use 263131__mossy4__tone-beep-slower-lower-amb-verb.wav, distinct from the NPC sound. They retain stereo, pitch, distance cadence, dialogue suppression, and foreground-only gating.

NPCSoundReader now reads the current floor independently of NPC availability and announces a map only when its floor ID changes. The full 285-entry XD room-ID catalog is stored at Companion/assets/room_ids.json; broad area codes are expanded to names such as Pokémon HQ Lab, and room components are spoken in readable form. Unknown XG-added IDs safely fall back to Map plus the numeric ID.

Validation: automated tests cover one-time map-change announcements and elevator category-sound routing; full suite passes 226 tests.

Signed: **Codex (OpenAI)** — 2026-07-26

## P★DA item beacon (2026-07-26)

Implemented a named item beacon for the opening P★DA pickup in the player's bedroom. The authoritative room catalog places the bedroom in Pokémon HQ Lab Residential Wing 1F, floor ID 0x8A (M5_apart_1F). Static analysis of that room's script identified functions look_pda, in_heroroom, se_get_pda, and get_pda. The in_heroroom function tests the hero against x=-35..-25 and z=-114..-94 before invoking look_pda; the implemented beacon uses the exact zone center x=-30, y=15, z=-104 with interaction radius 10.

The virtual entity is labeled 'P star D A' for clear NVDA pronunciation and uses the dedicated item sound 263129__mossy4__sine-up-flutter-beep.wav. It inherits foreground-only playback, dialogue suppression, camera-relative stereo, direction pitch, distance gain, and proximity cadence. Automated coverage locks the room ID, center, and label; full suite passes 227 tests.

Signed: **Codex (OpenAI)** — 2026-07-26

## Collision detection investigation (2026-07-26)

Codex traced the room `.ccd` triangle format and the verified vanilla-US-XD environment and human collision routines. Environment movement uses `GScolsys2HitCollision`, which returns a direct hit boolean and a corrected position. People use a separate 48-slot per-floor human table and `GScolsys2HumanCollision`, whose meaningful results are `6` for collision and `7` for clear.

The exact per-frame result is ephemeral at the engine call boundary, not a confirmed stable memory flag readable by the current external companion. The recommended read-only route is a locally parsed `.ccd` capsule sweep, followed by mapping-independent directional-input discovery and separate dynamic human/object handling. It must not be described as safe pathfinding until collision types, slopes, doors, dynamic transforms, and XG-specific behavior have been validated.

Full structure tables, vanilla addresses, constraints, validation steps, and unresolved questions are in `COLLISION_DETECTION_INVESTIGATION.md`. This was research and documentation only; no collision feature was enabled.

Investigated and documented by **Codex (OpenAI)** on **2026-07-26**.