# IMPLEMENTATION_ROUTE_COMPARISON.md

Evaluation of four candidate approaches for getting live game state (menu selection, battle state, dialogue text, etc.) out of Pokémon XG and into an NVDA-facing companion. Written from repository evidence (see [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md), [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md)) and current Dolphin/tooling capabilities researched 2026-07-23. No Dolphin build was cloned, downloaded, or modified to produce this comparison.

## Route A — Modify/patch the game's `main.dol`

**What this would mean:** decompile the specific functions that own menu-selection state, battle state, and dialogue text (per [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md)) into matching C/C++ in `xd-decomp`, then inject a small export routine (e.g., write selection index + string pointer to a fixed unused memory address, or over EXI/serial) at the point those values change, and rebuild `main.dol`.

- **Access to live menu/battle state:** Best possible, in principle — direct access at the source level, no guessing at memory layout, can be triggered exactly on state transitions rather than polled.
- **Detect selection changes:** Trivial — insert the hook exactly where the game already writes the new selection value (e.g., `menuTitleSetSelect`, `_menuTopSelectCursor` writes — both are Confirmed-symbol-only addresses today, not yet decompiled to source).
- **Send text to NVDA/Tolk:** Cannot be done directly from GameCube-native code — a GameCube binary cannot call a Windows DLL. Requires a second, external process (companion) that receives an exported signal (e.g., via a Dolphin-visible memory buffer that an external reader polls, or literally the same mechanism as Route B/C) and Tolk lives on the Windows side regardless. Route A doesn't eliminate the need for a companion — it only changes how the companion learns about state changes (from a game-authored export rather than a guessed memory address).
- **Stability across XG revisions:** **Weakest of the four.** This route requires the deepest reverse-engineering (real decompilation, not just a memory-address peek) and it requires that XG's own binary be rebuildable or at least byte-patchable at the exact same addresses `xd-decomp` uses — which is unconfirmed and, per [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md), likely to only partially hold, if at all. Since `xd-decomp`'s build hash check (`ff9e752ead9914af0b363ae6c831a34ccce189d2`) is pinned to unmodified retail GXXE01, this route cannot currently target XG's binary at all without first establishing (a) what XG's revision/base actually is and (b) whether XG's own code layout matches closely enough to patch using xd-decomp's map.
- **Amount of reverse engineering required:** **Highest.** Real decompilation (not just address discovery) of menu/battle/text systems, none of which currently have real source in `xd-decomp` (Confirmed: 8 of 522+ referenced game files exist).
- **Testing speed:** **Slowest.** Every iteration requires a full rebuild (`ninja`) and a fresh boot/reload in Dolphin to test a change.
- **Maintenance burden:** High — a binary patch tied to specific addresses breaks silently if XG is ever updated/re-patched, and every new accessibility feature requires new decompilation work before it can be hooked.
- **Interference with normal gameplay:** Potentially none if the patch only adds a passive export (doesn't alter existing logic) — but any mistake in a hand-patched binary risks crashes, unlike an external, out-of-process reader which can never crash the game itself.

## Route B — Read Dolphin's emulated memory from an external Windows companion

**What this would mean:** a Windows-side process (no Dolphin modification, no game patch) attaches to a running, unmodified Dolphin process and reads/polls specific RAM addresses, the same way tools like Cheat Engine or the community's `dolphin-memory-engine` do.

- **Access to live menu/battle state:** Good, once addresses are known for XG specifically — reads the same live values the game itself uses, with no need to alter the game at all.
- **Detect selection changes:** Straightforward via polling: read the known cursor-index address on a timer/frame-tick and speak only on change (debounce). Slightly less "event-driven" than Route A/C (it's poll-based, not push-based), but at the poll rates relevant to human menu navigation (tens of Hz) this is not a practical limitation.
- **Send text to NVDA/Tolk:** Best fit of all four routes — the companion is *already* a normal Windows process, so it can call Tolk (via the `cytolk` Python wrapper, confirmed pip-installable, auto-detects NVDA) with zero additional plumbing.
- **Stability across XG revisions:** Depends entirely on knowing XG's actual addresses — **but this is discoverable without any reverse engineering of Dolphin or the game's code,** purely by memory-scanning technique (e.g. searching MEM1 for a byte that changes exactly when you move the cursor, the classic "unknown initial value → known new value" scan workflow). This makes Route B the **most revision-resilient in practice**, because rediscovering an address after an XG update is a live, empirical, moderate-effort task (minutes to an hour with the right scanning tool) — it does not require rebuilding anything or new decompilation.
- **Amount of reverse engineering required:** Low-to-moderate, and importantly, it's a *kind* of reverse engineering (memory scanning) that doesn't require toolchain setup, a successful build, or C/C++ decompilation skill — only a running, unmodified copy of XG in Dolphin and a scanner tool.
- **Testing speed:** **Fastest.** No rebuild, no game patch — restart the companion script and test immediately. This is the standard workflow for the *entire* existing GameCube-accessibility/speedrunning/randomizer tool community (this exact approach is what `randovania`'s `py-dolphin-memory-engine` and the "TwitchPlaysPokemon" `dolphinWatch` fork exist to support).
- **Maintenance burden:** Low for a given revision (a stable address list + a small Python script); moderate if XG updates and shifts addresses, but re-scanning is cheap (see above).
- **Interference with normal gameplay:** **None.** Purely read-only, out-of-process. Cannot crash or alter the game; worst case is a stale/incorrect read, not a corrupted game state. This is a meaningful safety property for a screen-reader companion meant to run every session.

**Confirmed tooling for this route (researched, not yet installed/used):**
- `dolphin-memory-engine` (C++, aldelaro5) — the reference RAM-search tool; confirmed via its own README: **"No modified Dolphin build is required."** Attaches to the Dolphin process by name on Windows.
- `dolphin-memory-engine` (same name, separate **Python package** on PyPI, maintained by the `randovania` project under `randovania/py-dolphin-memory-engine`) — a `pip install`-able library exposing `hook()`/`read_*`/`write_*` calls, i.e. exactly the primitive a Python companion script would use. This is actively used in production by an established multi-game modding/rando community, not a one-off hobby script.
- `cytolk` — a Cython wrapper for the Tolk screen-reader abstraction library, pip-installable, auto-detects NVDA and exposes `tolk.speak(text)`.

## Route C — Add a small export bridge to a custom Dolphin build

**What this would mean:** build Dolphin from source with a small patch that exports specific game-memory values (or hooks specific PC addresses) directly, e.g. over a named pipe/socket, rather than relying on an external process to poll raw memory.

- **Access to live menu/battle state:** Equivalent to Route B in terms of *what* it can see (same emulated RAM), but can additionally hook at the **CPU/JIT level** (e.g., breakpoint-triggered export exactly when a specific instruction executes) rather than only polling memory — closer to event-driven than Route B.
- **Detect selection changes:** Can be made push-based/event-driven (export fires exactly on the write, not on a poll interval) — a real advantage over Route B for zero-latency, zero-missed-transition detection.
- **Send text to NVDA/Tolk:** Same as Route B — still needs a separate Windows-side receiver process to actually call Tolk (Dolphin itself would only be the exporter, not the speaker).
- **Stability across XG revisions:** Same address-discovery problem as Route B (still needs to find XG's actual addresses), **plus** an additional maintenance axis Route B doesn't have: the custom Dolphin build itself must be kept in sync with upstream Dolphin (rebasing a patch against a fast-moving emulator codebase — note the WebSearch results above show Dolphin has weekly-ish "progress report" releases and hundreds of PRs). This is extra ongoing engineering cost with no corresponding accuracy benefit, since Route B can already read anything Route C could export.
- **Amount of reverse engineering required:** Same game-side effort as Route B, **plus** Dolphin/C++/emulator-internals engineering effort. Strictly a superset of Route B's requirements.
- **Testing speed:** Slower than Route B — any change to *what* is exported requires a Dolphin rebuild (C++, full emulator codebase), not just editing a Python script.
- **Maintenance burden:** **Highest ongoing burden of the memory-reading routes** — you would be maintaining a Dolphin fork indefinitely. Existing prior art here (`Dolphin-Lua-Core`, `TASLabz/dolphin-lua-core` — explicitly marked "do not use — obsolete" in its own repo name, `TwitchPlaysPokemon/dolphinWatch`) shows this pattern has a track record of bitrotting once maintainers move on, precisely because it requires continuously tracking upstream Dolphin.
- **Interference with normal gameplay:** None to the game itself; but running a non-mainline Dolphin build carries its own risk surface (missing upstream fixes/perf/compatibility work, needing to rebuild for Dolphin updates).

**Confirmed prior art (researched, not adopted here):** `Dolphin-Lua-Core` (SwareJonge, based on dragonbane0's Zelda-edition fork) adds Lua scripting with `ReadValue8/16/32` memory functions to a Dolphin 5.0-era fork — direct evidence this pattern is technically viable, and also that it isn't part of mainline Dolphin (confirmed: no merged official Python/Lua scripting API was found in current mainline Dolphin as of this research).

## Route D — Use Dolphin's own debugging/memory-watch/Gecko-code facilities for an initial prototype

**What this would mean:** use stock, unmodified Dolphin's **built-in** debugger (memory watches, breakpoints, memory-check breakpoints with logging) and/or Gecko codes to observe or lightly patch game state, without writing any external tool yet.

- **Access to live menu/battle state:** Good for **manual, interactive investigation** — Dolphin's debugger lets you set a watch on an address and see it update live, and set a read/write breakpoint that fires (optionally just logging, not halting) when a specific memory location is touched. This is exactly the tool needed to *discover* the cursor/selection address for XG in the first place — it is the natural first step of Route B, not a competing route to it.
- **Detect selection changes:** Excellent for discovery (breakpoint-on-write immediately shows you which instruction/address changes when you move a cursor) but not something you'd leave running as the "production" mechanism — it's an interactive debugging workflow, not an automated pipeline.
- **Send text to NVDA/Tolk:** Not applicable — Dolphin's debugger has no path to an external screen reader by itself. Gecko codes can only patch/poke memory in simple ways; they cannot call Windows APIs.
- **Stability across XG revisions:** N/A as a shipping mechanism — this route only matters as a *discovery* tool, used once (or once per XG revision) to find addresses that Route B's script then encodes.
- **Amount of reverse engineering required:** This *is* the reverse-engineering step — using it well is how you'd populate Route B's address list.
- **Testing speed:** Immediate, interactive — no code to write at all for basic exploration.
- **Maintenance burden:** None — it's a one-time or per-revision discovery activity, not an ongoing system.
- **Interference with normal gameplay:** A watch/logging breakpoint has no effect on the game; Gecko codes, if used to poke values (e.g. force-set a value to test a hypothesis) can obviously alter gameplay, but that's opt-in and reversible (uncheck the code).

## Recommendation

**Route B (external Windows companion reading unmodified Dolphin's memory), bootstrapped using Route D's built-in debugger for address discovery.**

Reasoning, tied directly to evidence above:
1. It requires no Dolphin modification (your explicit constraint) and no successful `xd-decomp` build (which is currently blocked on the disc image anyway, per [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md)).
2. It has an established, actively-maintained tooling path (`py-dolphin-memory-engine` + `cytolk`) used in production by an existing modding community — not something to build from scratch.
3. It is the only route that is genuinely safe to iterate on: wrong reads produce wrong speech, never a corrupted save or a crashed game.
4. It cleanly separates the two genuinely hard problems — "where is the data" (an empirical memory-scanning question, answerable once you have XG running) from "how do we speak it" (already solved by Tolk/NVDA) — without also taking on "how do we maintain a fork of an actively-developed emulator" (Route C) or "how do we decompile a menu system that's 0% done" (Route A) as prerequisites.
5. Route A's and C's advantages (push-based exactness, no polling) are real but not currently worth their much higher up-front cost, especially since **the addresses needed for either route are still unknown for XG** — meaning Route D/B's discovery work has to happen first regardless of which route you ultimately want long-term.

This does not foreclose Route A later. Once Route B proves out a specific interaction (e.g., title-menu narration) and the project has working addresses plus a rebuildable `xd-decomp` baseline, revisiting specific hot paths as in-game exports (Route A/C) becomes a reasonable "harden it" step — but only after Route B has established that the addresses are stable and the concept works end-to-end.
