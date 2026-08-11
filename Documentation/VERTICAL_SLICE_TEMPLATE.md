# VERTICAL_SLICE_TEMPLATE.md

**Status:** Living document. Created 2026-07-29. Required structure for every accessibility implementation in this project. Copy this template into the relevant section of a design note, a PR description, or directly into [ACCESSIBILITY_COVERAGE_MATRIX.md](ACCESSIBILITY_COVERAGE_MATRIX.md)'s "Technical findings"/"Notes" fields when scoping new work.

Fill in every section. "Not applicable" is an acceptable answer where genuinely true (e.g. a passive reader has no cancellation behavior) — leaving it blank is not.

---

## Blind-player failure

One or two sentences. The exact thing a blind player cannot do, or cannot do without unreasonable cost, right now. Not "improve X" — the concrete failure. Example: *"When the shop's item cursor moves, nothing is spoken, so the player cannot know which item is selected, its price, or whether they can afford it without sighted help."*

## Intended behavior

What the player experiences once this slice ships, in plain terms — what gets spoken/played and when.

## In-scope behavior

The exact, bounded set of cases this slice handles. Be specific about game states, screens, and categories covered.

## Out-of-scope behavior

Explicitly excluded cases — especially ones that look similar but aren't handled yet (e.g. "the item list itself is out of scope; only the category-tab row is covered by this slice"). This section exists to prevent silent scope creep and to make partial coverage honest and visible.

## Game contexts

Which game states this applies in (field / battle / specific menu IDs / dialogue / loading), and which contexts must suppress it. Reference the existing lifecycle/context-gating mechanism (`phase1b_lifecycle.py`) rather than inventing a new gating mechanism per feature.

## Data sources

Exact memory addresses/offsets, structures, or files this reads (or, for planning-stage entries, what's still unknown and needs discovery). Cite the static source (symbol name + address, or community-repo file) and whether it's been live-verified, statically-inferred-only, or unverified.

## Address validation

How this slice protects against reading garbage: range checks, plausibility checks, the vanilla `GXXE01` rev-0 hash pin, or an explicit statement that a check is missing and why that's currently acceptable.

## Speech or sound behavior

Exact wording/sound cue, which `SpeechEventClass` it uses, interruption/priority behavior relative to other speech.

## Input behavior

Any hotkey involved (exact key combination), and explicit confirmation that no game-facing input is sent unless this is the teleport feature or another feature that has gone through the same explicit authorization process.

## Safety conditions

What has to be true before this fires: entity-nav selection validity, category restriction, floor/room matching, staleness checks, or any other guard specific to this slice.

## Cancellation behavior

What stops this mid-flight: selection changing, leaving the context, the player closing the screen, an error. "Not applicable" is fine for a one-shot announcement with no ongoing state.

## Automated tests

What's covered by fakes/synthetic data in `Companion/tests/`, and — per this project's established convention — what's *not* unit-tested directly because it's a live-memory-read implementation detail better verified live (see existing examples: `player_name()`, `slot_for_pointer()`'s pointer resolution).

## Live-test procedure

The smallest possible set of concrete, one-at-a-time actions for the project owner to perform to confirm this works, matching the "one action at a time" rule in [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md). Reference a save/save-state from [MILESTONE_SAVE_INDEX.md](MILESTONE_SAVE_INDEX.md) if one exists for this context.

## Regression targets

What existing behavior must NOT change as a result of this slice, and which existing regression tests cover that (or which new ones need adding to [ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md)'s regression queue).

## Known limitations

Honest, explicit list of what this slice does not solve, mirroring the project's established practice of stating gaps plainly (e.g. the summary screen's Ribbons page, held-item name resolution, EXP point-count value).

## Completion decision

Explicit statement of current status against the three-part definition in [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md): Implemented / Live-tested / Regression-tested, each called out separately. Do not mark this slice "complete" until all three are true.
