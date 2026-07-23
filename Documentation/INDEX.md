# INDEX.md

## Current checkpoint — 2026-07-23

The vanilla US XD baseline is built and verified, the replacement RVZ is Redump-verified, read-only Dolphin attachment and NVDA speech have both succeeded, and Phase 0B produced two **Inferred** active-battler HP candidates (`0x804454B4`, `0x804454BC`) while refuting the `_orreHero`/`g_pHero` direct-layout hypothesis. Phase 0C is next: identify and verify a battle-command-menu selection using the controlled protocol in [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md). Dolphin is currently closed, so no live Phase 0C scan or Phase 0D speech proof has yet been performed. Pokémon XG remains untested and no vanilla address is considered XG-compatible.

Documentation index for the Pokémon XG: NeXt Gen blind-accessibility research project. Investigation date: 2026-07-23. This is research/setup-mode output only — no production accessibility code, no ISO, no Dolphin build, no game files exist anywhere in this project yet.

## Read in this order

1. **[ENVIRONMENT.md](ENVIRONMENT.md)** — What's installed on this machine vs. what `xd-decomp` requires (Python, Ninja, compilers, platform deps), and exactly what would be downloaded if you green-light the next setup step. Nothing has been installed beyond Git/Python, which were already present.
2. **[REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md)** — Clone record (commit hashes), how the `xd-decomp` build system actually works (traced in code, not assumed), current decompilation completion status, and why no build was attempted.
3. **[ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md)** — The full code/symbol/data-structure map across both repos, organized by the 14 requested categories, every entry labeled Confirmed/Inferred/Unknown with exact file:line or address citations.
4. **[ACCESSIBILITY_HOOKS.md](ACCESSIBILITY_HOOKS.md)** — The same findings reframed as a prioritized, tiered list of accessibility-hook candidates: what's ready to probe first, what needs its own discovery pass, and what needs real decompilation.
5. **[IMPLEMENTATION_ROUTE_COMPARISON.md](IMPLEMENTATION_ROUTE_COMPARISON.md)** — The four candidate routes (patch `main.dol`, external memory read, custom Dolphin build, Dolphin's built-in debugger), compared on the criteria you specified, with a recommendation and reasoning.
6. **[FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md)** — Full design (not implementation) for "speak the selected title-menu option through NVDA," including the Phase 0 memory-discovery experiment that has to happen first, since the currently decompiled code cannot identify XG's actual menu-selection address on its own.
7. **[UNKNOWNS_AND_BLOCKERS.md](UNKNOWNS_AND_BLOCKERS.md)** — Everything unresolved, split into: blocked on your XG game files, blocked on a decision only you can make, genuinely open technical questions, and what was deliberately left out of scope.

## Project layout

```
PokemonXGAccessibility/
    xd-decomp/            Primary codebase — TeamOrre's Pokémon XD decompilation (C/C++, matching-build toolchain)
    Pokemon-XD-Code/       Secondary reference — PekanMmd's Colosseum/XD/PBR modding-tool codebase (Swift)
    Documentation/         This folder
    Tools/                 Empty — reserved for future companion/discovery scripts, none written yet
    Companion/             Empty — reserved for the future NVDA-facing companion app, none written yet
```

## Historical status summary (superseded by the current checkpoint above)

Both repositories are cloned and pinned to specific commits (see [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md)). No build has been attempted (no disc image, `ninja` not installed, nothing downloaded without asking first). The code map shows `xd-decomp`'s game-logic layer is very early-stage (8 of 522+ referenced files have real source), concentrated on Pokémon/move/party data rather than menus or battle UI — but that data-model code (HP, status, move slots) happens to be exactly what's most valuable for narration, and is independently corroborated by `Pokemon-XD-Code`'s separate reverse-engineering effort. The recommended path forward is an external, read-only Windows companion reading unmodified Dolphin's memory (Route B), bootstrapped by Dolphin's own built-in debugger to discover XG-specific addresses empirically — because none of the addresses found in either repository can be assumed to apply to XG's unknown revision without direct verification.

## Historical next steps (superseded; retained for provenance)

1. You decide on the small installs flagged in [UNKNOWNS_AND_BLOCKERS.md](UNKNOWNS_AND_BLOCKERS.md) (ninja, submodule init, configure.py's tool downloads) — only relevant once you're ready to attempt a *vanilla XD* build for reference/cross-checking purposes.
2. You supply your legally-obtained XG image and install Dolphin yourself.
3. Run the Phase 0 memory-search experiment from [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md) to find XG's actual title-menu-selection address.
4. Build and test the title-menu narration prototype per the rest of that document.
5. Only after that works end-to-end, revisit [ACCESSIBILITY_HOOKS.md](ACCESSIBILITY_HOOKS.md)'s Tier 2/3 candidates for what to tackle next.
