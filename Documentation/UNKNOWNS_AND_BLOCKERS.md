# UNKNOWNS_AND_BLOCKERS.md

## Current bounded blockers and unknowns — 2026-07-25

- **Completed:** Phase 1F production regression confirmed ordinary Earthquake damage and indirect poison damage through the same settled HP-loss pipeline.
- **Unknown:** every Pokémon XG address, structure layout, and compatibility claim. XG has not been validated, and the working production profile deliberately accepts only vanilla `GXXE01` revision 0.
- **Out of current scope:** target-selection narration, healing speech, additional event-specific health fields, forced poison/critical-hit testing, and generalized message-opcode interpretation.
- **Rejected:** `0x804454B4` and `0x804454BC` are not production HP hooks. Stable health narration now uses the verified FightFloor battler chain plus dynamically reconstructed status windows documented in [PHASE_1F_HEALTH_NARRATION.md](PHASE_1F_HEALTH_NARRATION.md).
- **Resolved since the original audit:** read-only Dolphin attachment, NVDA/Tolk output, persistent lifecycle handling, GSmsg battle narration, command-menu focus, move-menu focus, move/type/PP resolution, and generic production health integration.

The older sections below are retained as a historical audit. Statements that the companion, dependencies, Dolphin, menu hooks, GSmsg source, or vanilla HP chain do not exist are superseded by this checkpoint and the current [INDEX.md](INDEX.md).

Everything this investigation could not resolve, organized by what would resolve it. If you only read one section before deciding what to do next, read "Blockers that require your XG game files" — that's the actual critical path.

## Blockers that require your legally-obtained XG game files (nothing else resolves these)

1. **XG's exact base revision is unknown.** `xd-decomp` supports GXXE01 Rev 0 (US retail) and NXXJ01 (JP demo) only. Which revision XG was built from — and whether it was built from Rev 0 at all — is not knowable from either repository. **Resolution:** inspect your XG image's header/banner once you have it (does not require running it — a disc-image header read is enough for a first pass).
2. **Whether XG's code is address-shifted relative to vanilla XD is unknown.** Traced in [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md): if XG only edits data tables/text in place, addresses may substantially survive; if it adds/relocates code, they likely won't, and the degree could vary function-by-function. **Resolution:** the Phase 0 memory-search experiment in [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md), run against your actual XG image in Dolphin.
3. **Every specific RAM address cited from `Pokemon-XD-Code` in [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md) is unverified against XG.** They're vanilla-XD-US findings from a different project, gated in that project's own code to region `.US` with only a 4-character game-ID check (not a full version/hash check) — meaning even that project would apply them to XG blindly if asked to. **Resolution:** same Phase 0 experiment, using these addresses as a prioritized shortlist to check first rather than a blind full-memory scan.
4. **No live RAM address for dialogue text, battle messages, move/target selection state (as a pollable, not just event-driven, value), or player position exists in either repo.** These are all "Needs discovery" per [ACCESSIBILITY_HOOKS.md](ACCESSIBILITY_HOOKS.md) — genuinely unknown, not just XG-unverified. **Resolution:** memory-search experiments per target, same methodology as Phase 0, extended after the title-menu slice succeeds.
5. **Whether XG can even be built/run/verified against `xd-decomp`'s tooling at all is unknown** — `xd-decomp`'s hash check (`build.sha1` = `ff9e752ead9914af0b363ae6c831a34ccce189d2`) is pinned to unmodified retail GXXE01; it will not "match" XG and isn't intended to. This is not really a blocker so much as a scope clarification: **`xd-decomp` is not a tool for building or verifying XG itself** — it's a reference for what vanilla addresses/symbols *might* still apply, nothing more, until proven otherwise.

## Blockers that require your decision (not technical, just need a yes/no from you)

1. **Whether to `pip install ninja`.** Small, low-risk, but not done without asking per your instructions. See [ENVIRONMENT.md](ENVIRONMENT.md).
2. **Whether to run `python configure.py`**, which triggers downloading the pinned binutils/compiler/dtk/objdiff/sjiswrap bundle from the internet (the Metrowerks compiler package is the notable size). This does not require a disc image and doesn't touch XG at all — it only sets up the ability to attempt a *vanilla XD* build later, which itself requires a vanilla XD (or eventually XG) disc image you'd supply. Not done without asking. See [ENVIRONMENT.md](ENVIRONMENT.md).
3. **Whether to `git submodule update --init`** for `extern/musyx` (small, MIT-licensed sound engine submodule, required for a complete build). Not done without asking, flagged in [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md).
4. **Whether to install `dolphin-memory-engine` (Python) and `cytolk`** (both small, pip-installable) once you're ready to actually start the Phase 0 discovery experiment in [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md). Not done — this entire investigation stayed in research/setup mode as instructed.
5. **Whether to install Dolphin itself.** Explicitly deferred per your instructions — not installed, not downloaded, not cloned.

## Genuine open technical questions (not blocked on your game files specifically, but unresolved by this audit)

1. **The dialogue-text-encoding reconciliation question:** does `xd-decomp`'s "GSchar"/SJIS-table pipeline describe an intermediate build-time representation that gets converted into the 2-byte-big-endian-Unicode format `Pokemon-XD-Code` documents as the actual stored/runtime format, or are these two different things entirely (e.g. different games/subsystems, or one describing font rendering and the other describing string storage)? Neither project states this explicitly; I did not find a citation connecting them. See [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md) category 13.
2. **Whether `xd-decomp`'s and `Pokemon-XD-Code`'s per-Pokémon struct offsets describe the same struct.** Several fields agree exactly (`hp`@0x4, `status`/`condition`@0x16, `maxHp`@0x90=144) which is reassuring, but the two documents weren't cross-checked field-by-field in this audit beyond the categories requested. A full side-by-side diff of `xd-decomp`'s `pokemon.hpp` against `Pokemon-XD-Code`'s `XDPartyPokemon.swift` would be worthwhile before writing any code that reads Pokémon data, to catch a subtle mismatch (e.g. save-file layout vs. live-battle-array layout, which can legitimately differ even within one game).
3. **Whether XG retains, modifies, or strips the game's built-in `dbgMenu*` debug-menu system** (278 resolved symbols exist in vanilla retail, zero decompiled source anywhere) — noted as a research lead in [ACCESSIBILITY_HOOKS.md](ACCESSIBILITY_HOOKS.md), not investigated further since reaching it requires a running XG image.
4. **Whether mainline mainline (non-forked) Dolphin has gained any first-party scripting API since this research was performed** — as of 2026-07-23, WebSearch found only fork-based Lua/Python scripting projects (several explicitly marked obsolete/unmaintained), no merged mainline feature. This is a fast-moving open-source project; worth a quick re-check if this project resumes after any significant time gap, since a first-party scripting API would strengthen Route C's case in [IMPLEMENTATION_ROUTE_COMPARISON.md](IMPLEMENTATION_ROUTE_COMPARISON.md) considerably.
5. **Exact size of the Metrowerks compiler download** (`compilers_20250812.zip` from `files.decomp.dev`) was not measured, since it was never downloaded. Worth checking (e.g. a `curl -I` HEAD request for `Content-Length`, which doesn't download the file) before committing to the download if bandwidth/disk space is a concern.

## What was explicitly not investigated (per your scope limits, not because it's blocked)

- Overworld navigation / player movement narration.
- Production accessibility code was outside the original audit scope; it now exists and is documented in the current index and phase records.
- Any ISO modification, ISO download, or use of a prepatched game.
- Dolphin cloning, building, or patching.
- Full-game implementation of any kind.

These aren't gaps in the research — they're the boundaries you set, restated here so future sessions don't accidentally treat their absence as an oversight.
