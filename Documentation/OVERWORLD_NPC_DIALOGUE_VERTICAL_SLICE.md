# Overworld NPC Dialogue Vertical Slice

## Status

Implemented and live-validated on 2026-07-26. Production narrator intentionally stopped after validation.

## Test NPC and location

The repeatable white-coated NPC beside the Battle Sim console in the laboratory-like room at the current save position. The player was already standing beside and facing the NPC. A Dolphin window capture was used to provide accessible orientation; no sighted helper was required.

This NPC has two repeatable ordinary interaction pages:

1. "BATTLE SIMs are virtual battle simulations using machines. But they don't lose a thing when it comes to re-creating the excitement of a battle."
2. "I've tested it out before. The opposing POKéMON was incredibly lifelike. It made me shiver even though I knew it wasn't real."

The exact strings above come from the game's live encoded source, not OCR. OCR supplied by the player was useful only as an initial cross-check.

A separate three-page post-battle trainer conversation was captured during reverse engineering. It is not the chosen ordinary-NPC fixture. Its pages demonstrated field player-name insertion (`DAVID`) and helped prove the generic page mechanism.

## Authoritative architecture

No per-dialogue address or key hunt is required. All tested pages use the same live controller and task layout:

- message-manager root pointer: `0x804E8348`;
- live manager observed: `0x80444D08`;
- task-interior pointer: manager `+0x1C`;
- dialogue task base: interior pointer `-0x20`;
- whole-message start: task `+0x48`;
- current-page start: task `+0x4C`;
- current-page end/control pointer: task `+0x50`;
- substitution resume pointer: task `+0x54` (observed, not needed by production);
- field dialogue-controller type: byte `0x804E8380 == 3`;
- ordinary dialogue window: the sole active window has ID `82`;
- page printing/advancing bytes: window `+0xA4` and `+0xA5`;
- a complete wait-for-input page was consistently observed with both bytes zero;
- closure is authoritative when controller type changes away from `3` and window 82 disappears. Old task pointers remain allocated and must not be treated as visible.

The current page changes generically by moving task `+0x4C` and `+0x50`. Examples from one three-page stream:

- page 1 start `0x809A4EBD`, end `0x809A4F8C` (`0x03`);
- page 2 start `0x809A4F8F`, end `0x809A50A9` (`0x03`);
- page 3 start `0x809A50AC`, end `0x809A515E` (`0x02`).

## Context signature

Production requires all of the following:

- field controller type `3`;
- exactly one active window, ID `82`;
- coherent, bounded task and page pointers;
- page begins with verified field-speaker control `0x59`;
- page ends at verified `0x03` clear-window or `0x02` dialogue-end control;
- both completion bytes indicate wait-for-input.

Window ID 82 alone is explicitly rejected. It remains allocated in stale states and is reused. Battle-message IDs and the generic `_MsgID`/menu-ID globals were also observed stale or zero and are not used by this implementation.

## Verified control codes

- `0x00`: newline. Normalized to a natural speech space.
- `0x02`: dialogue end. Ends the final page.
- `0x03`: clear window. Ends a page and creates the next page boundary.
- `0x2B`: field player-name insertion. Resolved from the authoritative live player-name pointer; observed as `DAVID`.
- `0x59`: field speaker label/instruction. Verified visual metadata at page start; the associated leading colon/space is omitted from speech.
- `0x6D`: wait for input. Supported as nonverbal page-state metadata, though not encountered in the chosen NPC fixture.

All other controls remain unsupported. A page containing an unknown meaning-changing control is suppressed and logged rather than guessed.

## Speech and lifecycle behavior

- A page is spoken only when the authoritative completion bytes indicate it has finished printing.
- Multi-line source text is normalized into natural sentence spacing.
- A new page interrupts obsolete speech.
- The stable page key contains task identity, page bounds, and raw page bytes.
- Unchanged polling does not speak again.
- Transient invalid bounds or incomplete terminators are treated as in-progress samples and do not clear/re-arm the page.
- Only authoritative controller/window closure clears state.
- Reopening the identical conversation narrates page one again.
- `--dialogue-debug` logs meaningful opens/pages/closes, raw bytes, decoded text, and changed suppression reasons.

An early live build incorrectly cleared state on transient pointer updates and repeated page one. Production was stopped immediately. The fix retains the last page key through transient samples; an automated regression covers this exact failure. The subsequent repeat interaction spoke page one once, page two once, and closed normally.

## Live results

First ordinary interaction:

- page one decoded and spoke correctly;
- page two decoded and spoke correctly after manual advance;
- closure was detected without stale speech.

Repeat interaction:

- identical page one spoke again once;
- page two spoke once after advance;
- conversation closed;
- live log recorded exactly one `SPEECH class=DIALOGUE` event per page in the corrected run.

The user uses OCR, but production decoding does not depend on OCR or sighted transcription.

## Unsupported scope

Still silent unless separately verified: YES/NO choices, shops, naming screens, complex cutscenes, simultaneous speakers, signs, computers, bookshelves, item pickups, automatic map-entry dialogue, phone/PDA messages, and unverified controls.

## Files changed

- `Companion/battle_narrator/dialogue.py`
- `Companion/battle_narrator/profile.py`
- `Companion/battle_narrator/speech.py`
- `Companion/battle_narrator/phase1b_lifecycle.py`
- `Companion/battle_narrator/phase1b_app.py`
- `Companion/tests/test_dialogue.py`
- `Documentation/OVERWORLD_NPC_DIALOGUE_VERTICAL_SLICE.md`

## Verification

Baseline before this slice: 144 passing tests.

Final complete-suite result after documentation and lifecycle cleanup: **169 passing tests**.

## Signature

Prepared from live Dolphin memory, the game's encoded dialogue bytes, NVDA production logs, automated regression tests, and direct user confirmation.

**Signed: Codex (OpenAI)**  
**Date: 2026-07-26**
