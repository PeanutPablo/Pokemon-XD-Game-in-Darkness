# INDEX.md

## Living project control documents (start here, 2026-07-29)

Everything below this section predates most of the project's actual current state and is retained for historical provenance only — see [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md)'s "Current major risks" section for why. The project's current, actively-maintained source of truth is:

- **[ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md)** — project goals, philosophy, the five workstreams, and the discovery-driven development cycle this project now follows.
- **[ACCESSIBILITY_COVERAGE_MATRIX.md](ACCESSIBILITY_COVERAGE_MATRIX.md)** — the authoritative, continuously-updated inventory of every known game state/screen/mechanic and its accessibility status.
- **[ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md)** — active blocker/foundational-feature/investigation, next reachable work, and the regression queue.
- **[PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md)** — incident log of accessibility barriers found during play.
- **[MILESTONE_SAVE_INDEX.md](MILESTONE_SAVE_INDEX.md)** — named save/save-state checkpoints for re-testing.
- **[VERTICAL_SLICE_TEMPLATE.md](VERTICAL_SLICE_TEMPLATE.md)** — required structure for every new implementation.
- **[ENTITY_NAVIGATION_ARCHITECTURE.md](ENTITY_NAVIGATION_ARCHITECTURE.md)** — authoritative per-source ownership map for every navigable overworld entity (NPCs, pickups, warps/doors/elevators/PCs/signs, healing, bridges): engine owner, identity key, position and interaction-position source, state flags, cache lifetime, known defects, confidence. **Supersedes `ENTITY_NAVIGATION.md` as the architecture record** (2026-08-06); that document is retained as build history only.
- **[ENTITY_NAVIGATION_AUDIT.md](ENTITY_NAVIGATION_AUDIT.md)** — Phase 1 audit: baseline, source authority ratings, hardcoding/heuristic inventory, log review, root-cause grouping, and the sequenced Phase 2–7 plan. Read this before changing anything in `entities.py` / `entity_sources.py` / `entity_nav.py` / `treasure_entities.py` / `authoritative_warps.py` / `gateon_bridge.py`. **Start at §0 (Pass 2 re-audit, 2026-08-09)** — it records that the Phase 2 NPC source was reverted out of production on 2026-08-06 and never restored, which is the cause of every currently-reported entity-navigation symptom.
- **[INTERACTABLE_OBJECTS.md](INTERACTABLE_OBJECTS.md)** — the room-script interaction system (2026-08-09): televisions, beds, PokéSpot plates, the Snag Machine, machines, consoles, the Relic Stone and floor hazards, all owned by the 241 marker-`0x0100` `common.rel` records whose handler index resolves into the owning room script's own function table (241/241 verified). Includes the method-byte press-A discriminator and a proposed six-category design.
- **[ENTITY_STATE_AND_BEACON_POLICY.md](ENTITY_STATE_AND_BEACON_POLICY.md)** — the six independent entity conditions (exists / spawned / visible / interactable / landmark / beaconing), the per-state beacon table, exact cache lifetimes and invalidation triggers, and how far the current code is from all of it.
- **[GATEON_BRIDGE_ACCESSIBILITY.md](GATEON_BRIDGE_ACCESSIBILITY.md)** — Gateon Port's moving bridges: flag 968, the re-verified per-state `GScolsys2` enable table, what is hardcoded and must go, the one live measurement that gates Phase 5, and why routing is currently wrong in every alignment.
- **[ENTITY_IDENTITY_MODEL.md](ENTITY_IDENTITY_MODEL.md)** — how each entity is keyed, the eight ordered NPC validity rules, the generation/epoch rule, and why roles and letters are attributes rather than identities.
- **[ENTITY_POSITION_AND_INTERACTION_POINTS.md](ENTITY_POSITION_AND_INTERACTION_POINTS.md)** — world position versus interaction point per category, the neck-reference derivation, the engine's real three-term talk threshold, and which position drives direction/distance/range/beacon.
- **[INTERACTION_DIAGNOSTIC.md](INTERACTION_DIAGNOSTIC.md)** — the development-only `--interaction-diagnostics` tool: what each logged field means, how the manual A-press marker scores predictions, and the three open questions it exists to settle.
- **[SHADOW_POKEMON_SYSTEM_INVESTIGATION.md](SHADOW_POKEMON_SYSTEM_INVESTIGATION.md)** — current Shadow Pokémon architecture and XD/XG boundary.
- **[SHADOW_POKEMON_MEMORY_MAP.md](SHADOW_POKEMON_MEMORY_MAP.md)** — pointer chains, layouts, offsets, and confidence.
- **[SHADOW_MOVE_TABLE.md](SHADOW_MOVE_TABLE.md)** — locally extracted Shadow move records and descriptions.
- **[SHADOW_POKEMON_CLAUDE_NOTES_AUDIT.md](SHADOW_POKEMON_CLAUDE_NOTES_AUDIT.md)** — claim-by-claim audit of earlier notes.
- **[SHADOW_POKEMON_LIVE_TEST_PLAN.md](SHADOW_POKEMON_LIVE_TEST_PLAN.md)** — controlled validation plan for unresolved mechanics and XG deltas.
- **[HEALING_SERVICE_SCRIPT_TRACE.md](HEALING_SERVICE_SCRIPT_TRACE.md)** — engine/script trace of the Pokémon Center healing service, the tooling inventory for the offline classification pipeline, and the remaining phases. **⚠ Contains a correction: an earlier session concluded the healing method was "People method 85". That was WRONG.** The healing method is **class 35 `Character`, method 101 (`0x65`), `useHealingMachine`**; 85 is only the internal `cmpPeople` jump-table index, because the dispatch subtracts `0x10` (`101 − 16 = 85`). Read §1 of that document before touching anything script-related.

`IMPLEMENTATION_ATTRIBUTION.md` remains the authoritative, dated, chronological record of who implemented what — read it for detailed history; read the five documents above for current state and what's next.

## Current checkpoint â€” 2026-07-25 (historical, superseded above)

The verified vanilla US XD (`GXXE01`, revision 0) read-only companion now provides persistent lifecycle handling, shared GSmsg battle narration, dynamically resolved move announcements, stat changes, poison/faint/loss messages, primary command-menu focus, move-menu focus with type and PP, a production-integrated generic settled HP-loss module, and a foreground-scoped manual live battle HP-summary hotkey.

Phase 1F direct-damage behavior is live-confirmed in its preserved diagnostics. The production health and manual-summary integration passes all 67 automated tests. Its bounded production regression is complete: ordinary Earthquake damage and an indirect poison tick both produced correct, uniquely settled percentage-based HP-loss announcements through the same reconstruction pipeline. PokÃ©mon XG remains untested, and no vanilla address is considered XG-compatible without separate validation.

All runtime memory access remains read-only. Extracted copyrighted data remains local under the gitignored `Companion/_dialogue_extraction` path and is not packaged.

Documentation index for the PokÃ©mon XD/XG blind-accessibility research project. Earlier Phase 0 material is retained for provenance but may be superseded by the current checkpoint and dedicated phase records.

## Overworld dialogue vertical slice

Ordinary repeatable NPC dialogue is now production-integrated and live-validated. The companion follows the generic field message task's moving page pointers, waits for the authoritative completed/waiting state, safely decodes verified controls, resolves the live player name, speaks each page once, interrupts obsolete pages, and re-arms on authoritative closure. See [OVERWORLD_NPC_DIALOGUE_VERTICAL_SLICE.md](OVERWORLD_NPC_DIALOGUE_VERTICAL_SLICE.md) for addresses, captured pages, controls, safety signature, tests, live results, and the signed Codex handoff.
## Collaboration attribution

Implementation ownership is tracked in [IMPLEMENTATION_ATTRIBUTION.md](IMPLEMENTATION_ATTRIBUTION.md). Codex has signed only the Phase 1F production integration and documentation it completed; Claudeâ€™s section is intentionally reserved for Claude to complete.

The rule for promoting every verified update into the default narrator is recorded in [PRODUCTION_INTEGRATION_POLICY.md](PRODUCTION_INTEGRATION_POLICY.md).
## Read in this order
1. **[ENVIRONMENT.md](ENVIRONMENT.md)** â€” What's installed on this machine vs. what `xd-decomp` requires (Python, Ninja, compilers, platform deps), and exactly what would be downloaded if you green-light the next setup step. Nothing has been installed beyond Git/Python, which were already present.
2. **[REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md)** â€” Clone record (commit hashes), how the `xd-decomp` build system actually works (traced in code, not assumed), current decompilation completion status, and why no build was attempted.
3. **[ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md)** â€” The full code/symbol/data-structure map across both repos, organized by the 14 requested categories, every entry labeled Confirmed/Inferred/Unknown with exact file:line or address citations.
4. **[ACCESSIBILITY_HOOKS.md](ACCESSIBILITY_HOOKS.md)** â€” The same findings reframed as a prioritized, tiered list of accessibility-hook candidates: what's ready to probe first, what needs its own discovery pass, and what needs real decompilation.
5. **[IMPLEMENTATION_ROUTE_COMPARISON.md](IMPLEMENTATION_ROUTE_COMPARISON.md)** â€” The four candidate routes (patch `main.dol`, external memory read, custom Dolphin build, Dolphin's built-in debugger), compared on the criteria you specified, with a recommendation and reasoning.
6. **[FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md)** â€” Full design (not implementation) for "speak the selected title-menu option through NVDA," including the Phase 0 memory-discovery experiment that has to happen first, since the currently decompiled code cannot identify XG's actual menu-selection address on its own.
7. **[BATTLE_HP_SUMMARY.md](BATTLE_HP_SUMMARY.md)** â€” Manual foreground-only live HP/status summary, ordering, stability, configuration, and regression evidence.
8. **[PHASE_1F_HEALTH_NARRATION.md](PHASE_1F_HEALTH_NARRATION.md)** â€” Verified health structure chain, production settling rules, tests, and the completed direct/indirect live regression.
9. **[OVERWORLD_NPC_DIALOGUE_VERTICAL_SLICE.md](OVERWORLD_NPC_DIALOGUE_VERTICAL_SLICE.md)** â€” Production overworld NPC dialogue architecture, controls, fixtures, and live validation.
10. **[TITLE_MAIN_OPTIONS_ACCESSIBILITY.md](TITLE_MAIN_OPTIONS_ACCESSIBILITY.md)** — Production NVDA speech for Press Start, main-menu focus, and options values.
11. **[NPC_PROXIMITY_SOUNDS.md](NPC_PROXIMITY_SOUNDS.md)** — Generic per-NPC sound assignment, proximity behavior, verified live structures, attribution, and tests.
12. **[COLLISION_DETECTION_INVESTIGATION.md](COLLISION_DETECTION_INVESTIGATION.md)** — Static `.ccd` geometry, live environment and human collision routines, read-only limitations, and the recommended validation-first implementation route.
13. **[NAVIGATION_AUDIT_2026-08-04.md](NAVIGATION_AUDIT_2026-08-04.md)** — Independent audit of the routed guide: collision radius corroborated at 3.50 across four rooms, the passability-authority classifier indicted, the waypoint cursor's missing look-ahead identified as the back-and-forth cause, and a verifiable order of work. Supersedes `WORLD_NAVIGATION_ARCHITECTURE.md` §6g's conclusion.
14. **[UNKNOWNS_AND_BLOCKERS.md](UNKNOWNS_AND_BLOCKERS.md)** â€” Everything unresolved, split into: blocked on your XG game files, blocked on a decision only you can make, genuinely open technical questions, and what was deliberately left out of scope.

## Project layout

```
PokemonXGAccessibility/
    Companion/             Read-only NVDA companion, diagnostics, tests, local extracted-data workspace, and logs
    Documentation/         Research records, architecture, implementation status, and validation procedures
    Pokemon-XD-Code/       Secondary reverse-engineering reference
    xd-decomp/             Primary vanilla-XD decompilation reference
    Research/              Supporting research artifacts
    Tools/                 Project tooling
```

## Historical status summary (superseded by the current checkpoint above)

Both repositories are cloned and pinned to specific commits (see [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md)). No build has been attempted (no disc image, 
inja` not installed, nothing downloaded without asking first). The code map shows `xd-decomp`'s game-logic layer is very early-stage (8 of 522+ referenced files have real source), concentrated on PokÃ©mon/move/party data rather than menus or battle UI â€” but that data-model code (HP, status, move slots) happens to be exactly what's most valuable for narration, and is independently corroborated by `Pokemon-XD-Code`'s separate reverse-engineering effort. The recommended path forward is an external, read-only Windows companion reading unmodified Dolphin's memory (Route B), bootstrapped by Dolphin's own built-in debugger to discover XG-specific addresses empirically â€” because none of the addresses found in either repository can be assumed to apply to XG's unknown revision without direct verification.

## Historical next steps (superseded; retained for provenance)

1. You decide on the small installs flagged in [UNKNOWNS_AND_BLOCKERS.md](UNKNOWNS_AND_BLOCKERS.md) (ninja, submodule init, configure.py's tool downloads) â€” only relevant once you're ready to attempt a *vanilla XD* build for reference/cross-checking purposes.
2. You supply your legally-obtained XG image and install Dolphin yourself.
3. Run the Phase 0 memory-search experiment from [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md) to find XG's actual title-menu-selection address.
4. Build and test the title-menu narration prototype per the rest of that document.
5. Only after that works end-to-end, revisit [ACCESSIBILITY_HOOKS.md](ACCESSIBILITY_HOOKS.md)'s Tier 2/3 candidates for what to tackle next.

