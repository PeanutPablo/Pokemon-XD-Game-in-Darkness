# Title Screen, Main Menu, and Options Accessibility

## Implemented behavior

The production companion now speaks through NVDA on all three pre-game screens:

- Title screen: “Pokémon XD: Gale of Darkness. Press Start.” once when the stable press-start state appears.
- Main menu: speaks the focused entry immediately and once per cursor change: New Game, Continue, VS Battle Mode, or Options.
- Options: speaks both the focused row and its current value. Examples: “Sound, Stereo,” “Sound, Mono,” “Rumble, On,” “Rumble, Off,” and “Exit.” A left/right value change is announced even when focus remains on the same row.

Speech uses the existing `MENU_FOCUS` priority, so new focus interrupts obsolete focus speech. Closing and reopening a menu re-arms its initial announcement.

## Verified implementation points

Static disassembly of the byte-identical GXXE01 `main.elf` established:

- Main title selection window ID: 17 (`menuTitleOpenMenu` passes 17 to the window allocator).
- Options selection window ID: 279 (`menuTitleOption` passes 279).
- Both use the already-verified `tagWINDOW_WORK` signed cursor sum at offsets `+0x9C` and `+0x9E`.
- `_menuTitleStatus` is `0x804EAA38`; state 41 is the press-start wait and state 42 owns the title selection flow.
- Options has exactly three rows; `_menuOptionMsgTable` at `0x803D07C0` contains three message IDs.
- Stereo/mono is read from the real audio state byte at `0x8044DA73`, mask `0x04`, following `soundGetOutputMode`.
- Vibration is read from the game-data manager root at `0x804E88D8`, through the save structure at `+0xA8`, with the `no vibration` byte at `+0x21`. The displayed value is inverted correctly: zero means Rumble On, one means Rumble Off.

Window IDs 17 and 279 are reused in VS/menu contexts. The reader therefore requires `_menuTitleStatus == 42` before treating either as a title screen window. Existing nesting rules retain priority for verified battle/VS contexts.

## Corrected historical finding

The old `phase0d_menu_speech_proof.py` address `0x804FFCEF` must not be used. Later write-watchpoint work proved it was stack scratch. The production implementation uses the window manager, window IDs, cursor fields, title state, and actual option stores described above.

The old fourth-label guess “Exit Game” was also not grounded in decoded text and conflicts with the verified `menuTitleOption` route. Production uses “Options.”

## Tests and validation

Four new tests cover press-start deduplication, main-menu cursor speech, live stereo/mono changes, and live rumble on/off changes. Existing tests ensure reused IDs outside the title context remain silent and VS nesting retains priority. Full suite: 182 tests passing.

Live validation confirmed `_menuTitleStatus == 41` on the running title screen. The title screen also had an unrelated window ID 51, proving that detection must use the title state rather than require an empty window list. After that correction, the production log confirmed immediate `MENU_FOCUS` speech: “Pokémon XD: Gale of Darkness. Press Start.” Main-menu and options cursor/value traversal remain to be exercised by the user.

Implemented, investigated, and documented by **Codex (OpenAI)** on **2026-07-26**.
## Live correction: parent/child title windows and Memory Card notifications

The first production pass was corrected after the blind player's live test. `_menuTitleStatus == 41` occurs after Start in this flow, so it must not trigger a late “Press Start” announcement. The late announcement was removed.

Live bounded window capture established that window 17 is a parent, not the focused main-menu window. The active title selection child is window 278, producing the signature `(17, 278)`. Production now requires title state 42 plus this direct parent/child relationship before reading the child’s verified `+0x9C/+0x9E` cursor. This also preserves the existing protection against IDs 17, 278, and 279 being reused by VS menus.

Memory Card notices are GSmsg tasks, not ordinary NPC dialogue and not battle messages. Live logs captured title messages 129 and 152. Message 129 resolves from the locally extracted DOL table to “The Memory Card in Slot A has been read!” The menu reader now reads active GSmsg task IDs only during title notification states 32 and 200, resolves local DOL strings, strips display/control tags, speaks once immediately, and deduplicates unchanged tasks. ID 152 is absent from the extracted table; it currently has the conservative fallback “Checking the Memory Card in Slot A.” This fallback is explicitly provisional until its exact displayed wording is captured.

The corrected suite contains 183 passing tests, including notification decoding/deduplication, no late post-Start title announcement, and the verified `(17, 278)` main-menu signature.

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

## Continue confirmation parent-window correction (2026-08-08)

A read-only live probe on the Continue confirmation established the direct
window chain `219 -> 52 -> 53`. Window 52 is the prompt parent and window 53
is the standard signed choice cursor; all three windows had null allocation
pointers. At the same time, the active GSmsg task was message 17134, resolved
from the game's own message catalog as the Continue confirmation question.
This proves that the visible prompt and the choice graphics are separate
sources and that the existing `(51, 53)` rule could not cover Continue.

Production now permits parent 52 through the existing structural Yes/No
reader. It still obtains the prompt from the active game message and the
selection from window 53; no Continue wording or menu label was added to the
implementation. A regression fixture pins message 17134 and the `52 -> 53`
shape. The focused menu/dialogue suites pass all 152 tests, and the project
owner confirmed after restarting the narrator that the real Continue
confirmation now reads correctly.

The preceding Continue save-summary screen (name, play time, snagged count,
and purified count) is a different surface and remains open work.

Investigated, implemented, regression-tested, live-tested, and documented by
**Codex (OpenAI)** on **2026-08-08**.
### Naming-keyboard sparse-row correction (2026-08-10)

The second alphabet row is not a contiguous ten-column table. Live entered
text proves its raw coordinates are K–P at 0–5, Q at 7, R at 8, S at 10,
and T at 11; columns 6 and 9 are gaps. Production follows that sparse map and
does not announce a fabricated key while the cursor coordinate crosses a gap.

### Sparse-row identity collision correction (2026-08-11)

The Name Rater log confirmed the sparse coordinates but exposed a second
defect: deduplication used `row * 10 + column`. Because row 1 has valid
columns 10 and 11, S collided with U and T collided with V. Production now
encodes the complete `(row, column)` pair without assuming a ten-column
stride. A regression walks S, U, T, V and requires all four announcements.
