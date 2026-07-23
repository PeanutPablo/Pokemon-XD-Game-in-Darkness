# FIRST_VERTICAL_SLICE.md

Design and current verification protocol for the smallest possible prototype:

> "When the player changes the selected option on a verified vanilla-XD battle command menu, speak the selected option through NVDA."

The current pass deliberately validates the route against vanilla US XD (`GXXE01`, disc 0, revision 0). XG remains a later, separately fingerprinted target; no vanilla address may be carried over by assumption.

## Phase 0C controlled scan definition

- **Preferred active menu:** opening battle command menu, if it can be reached repeatably. Exact labels and count must be established from a self-captured Dolphin screenshot before assigning meanings. Expected labels must not be guessed.
- **Fallback order:** move-selection menu, pause/start menu, then title-screen menu.
- **User action:** one exact direction press per requested transition, acknowledged before the next snapshot. No batch of timing-sensitive inputs.
- **Snapshot boundaries:** pause on a stable selection; capture baseline; resume; move once; pause immediately; capture changed sample; capture a second no-movement sample.
- **Widths:** evaluate unsigned 8-bit, 16-bit big-endian, and 32-bit big-endian interpretations independently.
- **Success:** a candidate maps consistently across every menu position, remains unchanged without movement, reverses predictably, rejects unrelated input/animation, and can be derived again after fully closing and restarting Dolphin.
- **Failure:** a one-transition match, frame-varying value, raw input state, animation counter, rendering coordinate, or candidate that cannot cover every selection.
- **Address notation:** record GameCube virtual address separately from DOL file offset, structure-relative offset, and Dolphin host-process address.
- **Log location:** `Companion/logs/phase0c_menu_scan.log`; do not commit raw memory snapshots or logs containing substantial game data.
- **Rollback:** stop the reader and close Dolphin. The scanner performs no emulated-memory writes and makes no game-image changes.
- **Source follow-up:** search `xd-decomp` symbols/maps/assembly and `Pokemon-XD-Code` for every surviving candidate's readers/writers; determine whether it is static, module-relative, pointer-derived, or dynamically allocated.

Phase 0D must not begin until this protocol produces a sufficiently verified state. Its proof must poll conservatively, deduplicate unchanged values, speak only verified labels, log raw and normalized transitions plus reconnection events, provide a non-conflicting repeat-current-selection key, survive Dolphin loss/restart, and never call a memory-write API.

This follows Route B from [IMPLEMENTATION_ROUTE_COMPARISON.md](IMPLEMENTATION_ROUTE_COMPARISON.md): an external Windows companion reading unmodified Dolphin's memory, bootstrapped by Dolphin's own built-in debugger for address discovery. No code from this design has been implemented yet, beyond the two connectivity diagnostics described in "Current implementation status" below.

## Terminology: three distinct tools, easy to conflate

This design touches three separate things that all revolve around "Dolphin memory" and are easy to mix up because two of them share almost the same name. Keep them distinct:

1. **Dolphin Memory Engine (the graphical application)** — a standalone C++ program by aldelaro5 (`github.com/aldelaro5/Dolphin-memory-engine`), downloaded and run **by you**, separately from anything in this repo. It has a GUI: a RAM search window, a watch list, a hex memory viewer. **This is the tool used for Phase 0 address discovery** — you use it interactively to scan for the byte that changes when you move the title-screen cursor. It is not a Python package and is not installed into `Companion/.venv`. Confirmed via its own README: "No modified Dolphin build is required" — it attaches to a stock Dolphin process.
2. **`dolphin-memory-engine` (the Python library our companion code imports)** — a separate project by Henrique Gemignani (`github.com/henriquegemignani/py-dolphin-memory-engine`), installed via `pip install dolphin-memory-engine` into `Companion/.venv` (confirmed installed at version **1.3.1** — see [ENVIRONMENT.md](ENVIRONMENT.md)). It shares the "dolphin-memory-engine" name and the same underlying idea (attach to a running, unmodified Dolphin process and read/write its emulated RAM) but is a different codebase, imported in Python as `import dolphin_memory_engine`. **This is what `Companion/test_dolphin_connection.py` uses today**, and what any future polling script will use — it has no GUI; it's a library your code calls (`hook()`, `read_word()`, etc.).
3. **Dolphin's own built-in debugger** — a feature of Dolphin itself (Tools → memory view, breakpoints, memory-check breakpoints with logging), no separate download at all. Useful as a *first, even lower-friction* pass for Phase 0 before reaching for tool #1, and useful later for setting a write-breakpoint to pin down exactly which instruction touches a candidate address.

**How they relate in this project's workflow:** you will use tool #3 (and/or tool #1) interactively, by hand, to discover an address in Phase 0 below. Once an address is known, that address becomes a constant in a small Python script that uses tool #2 (the library) to read it automatically and repeatedly, feeding the speech companion. Tool #1 and #2 do the same *kind* of thing (attach + read Dolphin's RAM) but are not interchangeable in code — #1 is a GUI you operate by hand, #2 is a library your script imports. Nothing under `Companion/` invokes or depends on tool #1; it never needs to be installed into the venv.

## Current implementation status (as of this update — read before assuming any of this is still just a design)

Two small, connectivity-only diagnostics now exist under `Companion/`, run inside the project's Python 3.12 virtual environment (`Companion/.venv`, kept separate from the system's Python 3.14 — see [ENVIRONMENT.md](ENVIRONMENT.md)):

- **`Companion/test_speech.py`** — loads Tolk (via `cytolk` 0.1.13), detects the active screen reader, and speaks/brailles a fixed test sentence. **Tested and confirmed working: NVDA was detected and audibly spoke the message.**
- **`Companion/test_dolphin_connection.py`** — calls `hook()` from the `dolphin_memory_engine` Python library (tool #2 above) and reports `get_status()`/`is_hooked()`. **Tested with Dolphin not installed: correctly reported `DolphinStatus.notRunning` and exited cleanly**, exactly the expected result at this stage.

Neither script reads or writes any game memory address, polls anything in a loop, or hard-codes a memory address. They only prove the two connection primitives (screen-reader output, Dolphin-process attachment) work independently, before Phase 0/Phase 1 below are attempted. Everything from "Phase 0" onward in this document is still design, not yet implemented.

## Plain statement up front

**The currently decompiled code in `xd-decomp` is insufficient to identify the menu selection state for XG.** Here's exactly why, and exactly what to do about it — this is the load-bearing fact for this whole document.

- `xd-decomp` has only resolved **symbol names + addresses** for the title-menu system (`menuTitle`, `menuTitleGetSelect`/`SetSelect` at `.text:0x800A3194`/`0x800A31AC`, cursor state `_menuTopSelectCursor` at `.sbss:0x804EA798`), not decompiled source — see [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md). Confirmed by the code-mapping research: zero `.cpp` files exist for any menu system in this repo today.
- Those addresses are for **unmodified retail US Pokémon XD (GXXE01 Rev 0)**, not for Pokémon XG. Whether XG's title/menu code sits at the same addresses is **Unknown** and cannot be assumed (see [UNKNOWNS_AND_BLOCKERS.md](UNKNOWNS_AND_BLOCKERS.md)).
- Therefore: **the actual next controlled action, once you have your legally-obtained XG image, is a memory-search experiment to (re)discover these addresses empirically in XG itself** — not to trust the xd-decomp addresses as given. The design below assumes that experiment happens first (Phase 0) and the "speak on selection change" prototype (Phase 1) is the phase after it.

## Phase 0 — Address discovery experiment (must happen before Phase 1; requires your XG image)

**Goal:** find the live memory address (or addresses) in XG whose value changes exactly when, and only when, the player moves the cursor on the title screen / first menu.

**Tooling:** stock, unmodified Dolphin (any recent stable build) + its built-in debugger (tool #3 in the terminology section above — Route D from the comparison doc) as the first pass; the standalone **Dolphin Memory Engine graphical application** (tool #1 — aldelaro5's program, downloaded and run by you, *not* the Python library) as a second pass if the built-in debugger isn't precise enough for a full scan-based search. Neither of these is the `dolphin_memory_engine` Python library (tool #2) that `Companion/test_dolphin_connection.py` already uses — that library is for the automated *polling* step in Phase 1, after an address is known, not for the interactive *discovery* step here.

**Procedure (you drive this, since it requires your own Dolphin + XG):**
1. Boot XG in Dolphin, get to the title screen or first accessible menu, but don't move the cursor yet.
2. Open Dolphin's built-in Memory view / Cheats Manager (tool #3) and either:
   - Set a **write breakpoint region** across a plausible RAM window and watch for hits when you press a direction key, or
   - Switch to the Dolphin Memory Engine application (tool #1) for a proper scan-based search: scan for "unknown initial value," press down once to move the cursor, then scan for "changed value," repeat with up/down presses to narrow to one or a few candidate addresses.
3. For each candidate address, verify: does it change **only** on an actual selection change (not every frame, not on unrelated input)? Does its value correspond in an obvious way to the option index (e.g. 0, 1, 2 for three menu options)?
4. Record: the address, its size (1/2/4 bytes), whether it's in MEM1 (main GameCube RAM) — expect an address in the `0x8000_0000`–`0x817F_FFFF` range for MEM1 — and the exact XG build/revision you tested against (see identity fields in [ENVIRONMENT.md](ENVIRONMENT.md)).
5. Separately, identify **where the displayed text comes from** for each option: this game's dialogue/menu text is not plain ASCII but an in-house "GSchar" format built from Shift-JIS source data (Confirmed in `xd-decomp`: `GScharMakeFromSJIS`, `SJIStoGSchar`, `sjis_81xx`/`sjis_e0xx` raw charset tables — see [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md)). Two sub-options to investigate once you have the game running:
   - Find the **already-decoded, display-ready text buffer** in RAM (likely simplest: search for the literal displayed English text, e.g. search Dolphin's memory for the ASCII/UTF bytes of "NEW GAME" if that's a menu option's visible label — many localizations store the final display string in a more directly readable form even if the source pipeline is SJIS-based). This avoids needing to implement or reuse the GSchar decoder at all.
   - If no plain-readable buffer exists (e.g. text is only ever composed as glyph-texture draw calls, never as a flat string in RAM), the fallback is a **static, hand-built table**: menu-index → English label, populated once by you (since there are only a handful of title/first-menu options) rather than reading text out of memory at all. This sidesteps the encoding problem entirely for a first prototype and is the recommended starting point — simplicity over generality for the vertical slice.

**This phase's output is data (addresses + a small lookup table), not code.** It's a prerequisite for everything below.

## Phase 1 — The prototype itself

### Exact selection state we expect to observe

A single integer (1–2 bytes, exact size TBD by Phase 0) representing the currently highlighted option index on the title/first menu, at a specific RAM address discovered in Phase 0. Expected small range (e.g. 0–2 or 0–3 depending on how many options XG's title screen has — unconfirmed count, since this is XG-specific and not yet observed).

### Where the displayed text comes from

Per Phase 0 above: either (a) a live, human-readable text buffer at a nearby/related address, or (b) a static index→label table maintained in the companion app itself. **Recommendation: start with (b).** It requires zero text-decoding work and is trivially correct once the option order is confirmed by eye against Dolphin's video output.

### Proposed hook / memory-reading point

External, out-of-process polling of the single selection-index address from Phase 0, via the `dolphin_memory_engine` Python library — tool #2 in the terminology section above, `pip install dolphin-memory-engine`, confirmed installed at version 1.3.1 in `Companion/.venv`, exposing `hook()`/`is_hooked()`/`get_status()`/`read_word()`-style calls against an unmodified, already-running Dolphin process (confirmed by direct introspection — see [ENVIRONMENT.md](ENVIRONMENT.md)). `Companion/test_dolphin_connection.py` already exercises `hook()`/`get_status()`/`un_hook()` today; Phase 1 would add a `read_word()` (or similar) call at the Phase-0-discovered address inside a poll loop, and nothing else. No Dolphin modification, no game patch — consistent with your instruction not to touch Dolphin or the ISO yet.

### How changes are detected without repeatedly speaking unchanged text

Simple debounce in the companion's poll loop:
```
last_value = None
loop (e.g. every 50-100ms):
    current_value = read selection-index address
    if current_value != last_value and current_value is a known valid index:
        speak(label_table[current_value])
        last_value = current_value
```
This is the entire "detect a change" logic for the prototype — no smoothing, no debounce timers beyond the equality check, since a menu cursor index is a discrete, non-jittery value (not an analog stick reading).

### How the information reaches a Windows companion

There is no separate "information transport" step in this design — the companion **is** the reader. It polls Dolphin's memory directly in its own loop (no IPC, no sockets, no exported bridge). This is the simplicity benefit of Route B: reader and speaker are the same process.

### How the companion will speak through Tolk/NVDA

`cytolk` (pip-installable Cython wrapper around the Tolk screen-reader abstraction library, confirmed installed at version 0.1.13). On detecting a change: `tolk.load()`, then `tolk.speak(label, interrupt=True)` (this exact sequence is already proven working in `Companion/test_speech.py`, confirmed by an actual NVDA speech test — see [ENVIRONMENT.md](ENVIRONMENT.md)). Tolk speaks through whatever screen reader is active, so this also naturally supports other NVDA-compatible workflows without extra code.

### Required files and dependencies

- Python 3.12.10, isolated in a project-local virtual environment at `Companion/.venv` (not the system's Python 3.14.6, which remains untouched — see [ENVIRONMENT.md](ENVIRONMENT.md) for why a second Python version was needed: `dolphin-memory-engine` only ships prebuilt wheels for Python ≤3.12).
- `dolphin-memory-engine` 1.3.1 — **installed** in `Companion/.venv`.
- `cytolk` 0.1.13 — **installed** in `Companion/.venv`.
- A stock, unmodified Dolphin build (not yet installed, per your instruction — you'll supply this alongside your game image), plus, for Phase 0 specifically, the separate Dolphin Memory Engine graphical application (tool #1 in the terminology section) if the built-in debugger alone isn't enough — also not yet installed.
- Your own legally-obtained Pokémon XG image, running in that Dolphin.
- NVDA running on Windows (already confirmed working with this setup).
- Two small diagnostic scripts already exist under `Companion/`: `test_speech.py` and `test_dolphin_connection.py` (see "Current implementation status" above). The actual polling prototype (e.g. `title_menu_prototype.py`) is **not yet written** — this document remains the design for it, not the script itself, and it depends on Phase 0's address discovery happening first.
- A small hand-authored `label_table` (Python dict/list) mapping observed indices to menu option text, populated by you during Phase 0 by eye.

### Logging and diagnostics

For a prototype this small, recommend:
- Print (to console, not spoken) every raw poll result at first, so you can visually confirm the address is behaving as expected before trusting the speech path.
- Log each spoken event with a timestamp to a plain text file in `Companion/logs/` (e.g. `[12:03:41] spoke: "NEW GAME" (index 1)`), so a session can be reviewed after the fact without needing to have been listening live.
- No telemetry, no network calls — this is a local diagnostic log only.

### Success and failure criteria

**Success:** moving the cursor with keyboard-mapped controller input (see testing procedure below) through every option on the title/first menu causes NVDA to speak the correct, corresponding label exactly once per change, with no repeats while holding a direction, and no missed transitions when moving quickly.

**Failure modes to watch for, and what they'd indicate:**
- Nothing is ever spoken → either the address is wrong (Phase 0 needs redoing) or the poll loop isn't running/isn't attached (check `dolphin-memory-engine`'s `hook()` succeeded).
- Speech repeats every poll tick even without moving → the debounce equality check is broken, or the address is noisy (wrong address, possibly something that changes every frame — back to Phase 0).
- Speech is delayed noticeably behind the actual cursor movement → poll interval is too slow; reduce it (still no Dolphin/game modification needed, just a smaller sleep value).
- Wrong label spoken for a given index → the hand-built `label_table` has an off-by-one or the option order was misread during Phase 0.

### A keyboard-only blind testing procedure

1. Confirm your controller-to-keyboard mapping in Dolphin's controller settings before starting (standard Dolphin GameCube-pad-to-keyboard config; this is Dolphin setup, not part of this design, and something you'd do once regardless of this project).
2. With NVDA running and the companion script started (confirm via a spoken or logged "ready" message — recommend the script itself speaks or logs one line like "companion ready" on successful `hook()`, so a blind tester has positive confirmation the tool is attached before relying on it).
3. Boot XG to the title/first menu.
4. Press the mapped "down" key once. Expect: NVDA speaks the next option's label. Confirm against the log file afterward if any doubt.
5. Press "down" repeatedly to cycle through all options, including wrapping past the last option back to the first (if the menu wraps) — confirm every option is reachable and correctly spoken, including the wrap transition.
6. Press "up" to reverse — confirm correct labels in reverse too.
7. Hold a direction key down (auto-repeat, if the game has key-repeat on menus) — confirm no rapid-fire duplicate speech beyond one utterance per actual index change.
8. Do nothing for several seconds — confirm silence (no phantom repeats of the last-spoken label).

This procedure requires no sighted assistance to execute once step 1 (controller mapping) is done, since every check point is either a spoken confirmation or reviewable from the log file.

### How the experiment will be rolled back

Trivial by design: close the companion script (or `Ctrl+C` it). It never modified Dolphin, never modified the game, never wrote to the emulated RAM (read-only polling only), and never touched `orig/GXXE01` or any XG image file. There is nothing to undo in Dolphin or the game itself. The only artifacts are the Python script and its log files under `Companion/`, both of which can be deleted freely.

## What this slice deliberately does not do

- No overworld/movement narration (explicitly out of scope per your instructions).
- No battle-state narration (a much larger follow-on effort — see [ACCESSIBILITY_HOOKS.md](ACCESSIBILITY_HOOKS.md) for what's known/unknown there).
- No write access to game memory (pure observation).
- No assumption that the discovered address(es) will hold across XG revisions/updates without re-verification — a version/revision check (Phase 0's recorded revision fingerprint) should gate the companion from running silently against a build it hasn't been verified on, once this grows past a single-session prototype.
