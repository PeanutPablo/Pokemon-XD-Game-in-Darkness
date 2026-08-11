# ACCESSIBILITY_MASTER_PLAN.md

**Status:** Living document. Created 2026-07-29. This is the top-level control document for the Pokémon XD/XG blind-accessibility project. It supersedes the "linear feature list" framing implicit in earlier phase-numbered documents (`PHASE_0_RESULTS.md`, `BATTLE_NARRATOR_PHASE_1B.md`, etc.) without deleting them — those remain as historical/technical records, cited from here and from [ACCESSIBILITY_COVERAGE_MATRIX.md](ACCESSIBILITY_COVERAGE_MATRIX.md) where relevant.

## Project goal

Let a blind player play Pokémon XD (and eventually XG) through natural, ordinary controller play, with a companion NVDA narrator supplying everything that would otherwise require sight — without giving the player information or capability a sighted player wouldn't have, and without taking control away from the player.

The player (the project owner) is actively playing through the game while this project is developed. Discovery of what needs accessibility support happens **through play**, not through advance inventory. New menus, battle states, puzzles, and mechanics appear as the story progresses, and each one is a legitimate, expected source of new work — not a sign the project's scope was mis-estimated.

## Accessibility philosophy

- **Narrate, don't play.** The companion reads memory and speaks; it does not send input to the game, with exactly one narrow, explicitly authorized exception (the entity-nav-restricted teleport feature, a position-only write — see [`teleport.py`](../Companion/battle_narrator/teleport.py)). Any future input-sending feature requires the same explicit, risk-acknowledged authorization process that feature went through.
- **Parity, not advantage.** Features expose information a sighted player already has (item names, HP, menu focus, NPC identity) — not hidden game state, not perfect play assistance.
- **Read-only until proven necessary.** Every reader is passive by default. Writes are the rare, deliberate exception, never the default tool reached for.
- **Verify against the running game, not assumption.** Community reverse-engineering repositories (`xd-decomp`, `Pokemon-XD-Code`) are a strong starting hypothesis, not proof. Every address/offset used in production has been live-verified against the actual running game at least once; static-only findings are marked as such and are not shipped as production behavior.
- **Honesty over the appearance of completeness.** A feature that passes automated tests but hasn't been seen working live is not "done." A discovered barrier that hasn't been fixed is not silently dropped from tracking.

## The five workstreams

Every feature has exactly one **primary** workstream (it may also be relevant to others):

1. **Speech and information coverage** — narrating game state that's inherently informational: dialogue, menu contents, item/move/ability text, battle events, status.
2. **Navigation and spatial awareness** — knowing where you are, what's around you, and how to move deliberately: entity navigation, beacons, collision/footstep feedback, guided movement, map information.
3. **Battle accessibility** — everything specific to the battle state machine: command/move menus, HP/status, sent-out Pokémon, rewards, targeting, shadow-Pokémon battle mechanics.
4. **Story mechanics, puzzles, and special systems** — one-off or story-gated systems that don't fit the general menu/battle model: the Gateon bridge, Purify Chamber, environmental puzzles, minigames.
5. **Infrastructure, safety, testing, and distribution** — the plumbing everything else depends on: lifecycle/context detection, speech priority, hotkeys, address validation, the test suite, and eventually packaging this for the player to run independently of active development.

## Development priorities

When choosing what to work on next, in order (a newly discovered Level 0 blocker can override this order — see [ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md)):

1. Hard story or gameplay blockers (Level 0 — see severity model below).
2. Foundational systems reused throughout the game (lifecycle/context detection, entity nav, speech priority — the things every later feature depends on).
3. Frequently encountered battle information.
4. Frequently used menus.
5. Guided navigation.
6. Story-specific mechanics and puzzles.
7. Polish, configuration, and distribution.

This is a priority order, not a chronological roadmap — it does not mean these happen strictly in sequence, and it is explicitly not exhaustive of every feature that will ever be needed.

## Definition of a blocker

A **blocker** (Level 0, see severity model) is a barrier where the blind player cannot continue the game, or cannot make a required decision with the same information a sighted player has, without either (a) outside sighted help, (b) memorization from a previous sighted playthrough or written guide, or (c) blind trial-and-error that a sighted player would never need to do. "Technically possible with enough retries" does not disqualify something from being a blocker if the retry cost is unreasonable — that distinction is what separates Level 0 from Level 1 (see severity model).

## Definition of a complete vertical slice

A feature is not "done" the moment code exists. It passes through distinct states, tracked separately (see [ACCESSIBILITY_COVERAGE_MATRIX.md](ACCESSIBILITY_COVERAGE_MATRIX.md)'s accessibility-status list):

**Implemented** → the code exists, follows [VERTICAL_SLICE_TEMPLATE.md](VERTICAL_SLICE_TEMPLATE.md), and automated tests pass.
**Live-tested** → the project owner has actually experienced the feature working correctly in the real, running game, in the real context it's meant for.
**Regression-tested** → the feature has an automated regression test that will catch it silently breaking again, and it's been added to the regression queue in [ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md).

A slice is only "complete" once all three are true. Passing an automated test suite alone is never sufficient to close an item.

## Discovery-driven development cycle

This project follows one repeating cycle, documented here so every session can resume it without re-deriving it:

1. Play until a real accessibility barrier appears.
2. Record the barrier immediately in [PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md).
3. Classify its severity and workstream.
4. Preserve a save or save state near the barrier (see [MILESTONE_SAVE_INDEX.md](MILESTONE_SAVE_INDEX.md)) if one doesn't already cover it.
5. Define the smallest complete vertical slice that resolves it (see [VERTICAL_SLICE_TEMPLATE.md](VERTICAL_SLICE_TEMPLATE.md)).
6. Research only what that slice requires — no speculative research for hypothetical future features.
7. Implement behind appropriate safety checks (context gating, range/category restriction, read-only by default).
8. Run the automated test suite.
9. Guide the project owner through live validation, one action at a time — never a blind multi-step "please do these 10 things and report back."
10. Add regression coverage.
11. Update [ACCESSIBILITY_COVERAGE_MATRIX.md](ACCESSIBILITY_COVERAGE_MATRIX.md) and [ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md).
12. Resume the playthrough.

**The playthrough is the accessibility audit.** Playing and developing are not separate activities to be scheduled independently — the project owner encountering a barrier while playing normally *is* the discovery mechanism this whole project runs on.

## Rules for live validation

- Live validation is performed by the project owner, one concrete action at a time, since they cannot see the screen and I cannot ask them to look at or describe it (their own OCR of their own screen is the one acceptable exception, already used successfully for e.g. the party-summary-screen OCR work).
- Never present a multi-step live-test protocol and wait for a single combined report — confirm each step before moving to the next, unless the project owner has explicitly asked for a different cadence for a specific investigation.
- A feature is not marked live-tested from a static/automated result alone, no matter how strong the static evidence is.
- When a live test reveals a bug, fix and re-verify before moving on — don't accumulate a backlog of "probably fine" unverified fixes.

## Rules for preserving ordinary controller behavior

- The companion must never consume, remap, or intercept a real controller input meant for the game itself. Hotkeys use Windows-level key combinations (`ctrl+shift+...`) distinct from anything Dolphin forwards to the game.
- The one existing write path (teleport) only ever writes position data for an entity-nav-selected, category-restricted target — never arbitrary coordinates, never simulated button presses.
- Any future feature that would need to simulate input requires the same explicit stop-and-ask process the teleport feature went through before being authorized, every time — prior authorization for one feature does not extend to another.

## Rules for avoiding speculative overengineering

- Do not build generalized abstractions (a "universal grid navigator," a "universal menu framework") ahead of a second concrete need for them. [VERTICAL_SLICE_TEMPLATE.md](VERTICAL_SLICE_TEMPLATE.md) explicitly scopes each slice to in-scope/out-of-scope behavior for exactly the case at hand.
- Do not pre-build support for game states that haven't been reached yet (e.g., don't implement Purify Chamber accessibility before the Purify Chamber has actually been discovered in play).
- Do not run broad, unscoped memory-hunting passes "just in case" — every research task should have a specific decision it's meant to support (per the work-in-progress limits below).
- It is acceptable, and expected, for [ACCESSIBILITY_COVERAGE_MATRIX.md](ACCESSIBILITY_COVERAGE_MATRIX.md) to contain many "Unknown" and "Blocked by story progression" rows indefinitely. That is the system working as intended, not a gap to rush to fill.

## Work-in-progress limits

At any given time:

- One active blocker.
- One active foundational implementation.
- One active technical investigation.
- One regression queue.
- One story-locked queue.

Research tasks may be broader in scope when genuinely necessary (e.g. a full static trace of a call chain), but each one must still exist to support a specific, stated decision — not open-ended exploration for its own sake.

## Current major risks and technical constraints

- **XG vs. vanilla XD divergence is still unverified.** Every address in production use has been live-verified against the actual game running under Dolphin, but the project has not independently confirmed whether the game being played is exactly vanilla `GXXE01` rev 0 end-to-end (the working assumption throughout this session's live work) or a modified ROM (XG) with local edits. `xd-decomp`'s own build-hash check only validates a from-scratch vanilla build, not the live game. Treat this as a standing caveat on every "vanilla-derived" static finding, even though live verification has succeeded repeatedly this session.
- **Execution breakpoints are unreliable in the current Dolphin/GDB-stub configuration.** Established early and re-confirmed during the NPC-interaction investigation. This blocks any approach that needs precise mid-frame intervention (e.g., substituting a value between two specific instructions) and previously caused a real slowdown/boot-hang incident when a watchpoint was left armed and the stub force-killed. Do not re-enable the GDB stub casually.
- **Executable code modification is off the table** unless explicitly, separately authorized — every accepted approach so far works by reading/writing data, not patching instructions.
- **No safe "mailbox" invocation point has been found yet for triggering arbitrary game-side script execution from outside the game** (see the NPC direct-interaction investigation). This blocks the "bypass distance/facing cone" interaction feature until either a new hook is found, or the project owner decides to accept a narrower/riskier approach.
- **Two known duplicate-narration hazards exist:** (1) the venv-launcher stub + real-interpreter process pair is confirmed harmless (one logical narrator instance, not two); (2) `run_accessible_pokemon_xd.py` has a single-instance mutex guard that `run_battle_narrator.py` (the one the project owner launches via their desktop batch file) does not share — meaning both can run simultaneously and double-narrate. Adding the same mutex guard to `run_battle_narrator.py` is flagged as unresolved technical debt (see [ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md)).
- **Several core documentation files are stale** (`INDEX.md`, `UNKNOWNS_AND_BLOCKERS.md` — both dated 2026-07-25, describing a pre-Dolphin-attachment, pre-production research state that has been superseded by extensive verified work since). Code and the dated entries in `IMPLEMENTATION_ATTRIBUTION.md` are more current sources of truth than these two files until they're refreshed. This master plan and the coverage matrix now serve as the authoritative current-state documents; `INDEX.md`/`UNKNOWNS_AND_BLOCKERS.md` should eventually be refreshed or explicitly marked historical.
- **Live progress state is not currently checkpointed under a named-milestone system.** See [MILESTONE_SAVE_INDEX.md](MILESTONE_SAVE_INDEX.md) — only one anonymous Dolphin save-state slot exists today; the stable-name system this plan calls for is not yet populated.
