# COMMUNITY_TOOLING_AUDIT.md

Synthesis of the 2026-07-24 community-tooling research pass. This document does not repeat the detailed findings already written up elsewhere — it ties them together, surfaces cross-cutting discoveries that only became visible by reading multiple repos side by side, and gives a map of which document to read for what. Read the linked documents for citations; this one is the index and the "so what."

## Scope of this pass

Six additional community repositories were cloned into `Research/ThirdParty/` and audited alongside the two repositories already in this project (`xd-decomp`, `Pokemon-XD-Code`). Clone provenance (URLs, commit hashes, licenses) is in [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md)'s "Community tooling clone record" section — not repeated here.

| Deliverable | Covers |
|---|---|
| [XD_SCRIPTING_CODEMAP.md](XD_SCRIPTING_CODEMAP.md) | Script container format, opcodes, native engine identity, common/map script loading, NPC/warp/dialogue/party/battle script operations |
| [TEXT_AND_DIALOGUE_PIPELINE.md](TEXT_AND_DIALOGUE_PIPELINE.md) | String-table format, the encoding question (resolved), control codes, substitutions, message-ID leads, extraction-tool design, vertical-slice design |
| [MAP_ASSET_RESEARCH.md](MAP_ASSET_RESEARCH.md) | Map/room identification, transforms, warps, doors, NPC placement, render-vs-collision geometry, Blender-addon CLI headlessness |
| [NAVIGATION_VERTICAL_SLICE.md](NAVIGATION_VERTICAL_SLICE.md) | One-room navigation experiment design |
| [BATTLE_MENU_RESEARCH.md](BATTLE_MENU_RESEARCH.md) | Battle command/party/move/target/shadow-status structures, battle-engine root-pointer lead |
| [ACCESSIBILITY_HOOKS.md](ACCESSIBILITY_HOOKS.md) (addendum) | New battle/menu hook candidates folded into the existing tiered list |
| [DISTRIBUTION_PIPELINE.md](DISTRIBUTION_PIPELINE.md) | Disc/FSYS tooling capability, installer design, GPLv2 reuse consequences |
| [COMMUNITY_QUESTION_DRAFT.md](COMMUNITY_QUESTION_DRAFT.md) | Drafted (unsent) question for the Orre modding Discord |

## Cross-cutting discoveries — things that only surfaced by reading multiple repos together

None of these appear in any single one of the documents above; they emerged from comparing repos against each other and against this project's existing findings.

1. **"GoD Tool" is `Pokemon-XD-Code`, not a separate unaudited tool.** `pokemon-ngc-rando`'s README states it is "Based off of the GoD Tool written by Stars," linking directly to `PekanMmd/Pokemon-XD-Code`. The user's own community-question draft asked about "Windows GoD Tool builds" as if it might be something new — it isn't; it's the repo already in this project's "secondary" slot.

2. **`Pokemon-XD-Code` supersedes `XDscriptTools` outright**, not just partially. `XDscriptTools` (2015, 5 commits) is a disassembler only, by its own README's admission. `Pokemon-XD-Code` has a full script compiler/reassembler, a decompiler to editable pseudo-code, and — notably — a demonstrated mechanism for injecting **new** native script functions via hand-written PowerPC ASM (`Code snippets.swift:7655-7689`), not just modifying existing ones. Any future scripting work in this project should build on `Pokemon-XD-Code`, treating `XDscriptTools` as historical reference only (its section-format documentation remains independently useful and was cross-checked as correct against a real `.scd` sample, with one flagged discrepancy: it assumes `STRG` holds dialogue text in SJIS, but actual dialogue lives elsewhere in 2-byte Unicode — see the scripting codemap §11 summary table).

3. **The native scripting engine's actual identity was recovered by cross-correlation, not by either project alone.** `xd-decomp`'s symbol table has mangled C++ names with no source (`GSscript::Tiga`, `GSscript::tigaVariant`, `GSscript::TigaThread`, and ~20 `AppScript::cmpXXX` handlers like `cmpFight`, `cmpPokemon`, `cmpWaza`, `cmpDarkPokemon`). `Pokemon-XD-Code`'s independently-reverse-engineered `ScriptClassNames` table (Battle/Pokemon/Move/ShadowPokemon/Daycare/...) maps almost 1:1 onto these handlers — despite neither project citing the other. This convergence is strong corroborating evidence for both projects' correctness, and it is new information this project didn't have before this pass.

4. **The text-encoding "disagreement" was never a real contradiction.** It was three true, non-conflicting facts about three different pipeline stages: SJIS is the build-time authoring encoding, "GSchar" is a 16-bit intermediate `xd-decomp` builds from SJIS, and the shipped/runtime string-table format `Pokemon-XD-Code` reads directly off disc is 2 bytes per character. Full trace in `TEXT_AND_DIALOGUE_PIPELINE.md` §1.

5. **Collision geometry and script-triggered interaction volumes are the same mesh, not separate systems** — `Pokemon-XD-Code`'s `XGCollisionData.swift` flags specific collision triangles `isInteractable` with an `interactionIndex` that cross-references directly into the door/warp/PC interaction-point table. Render geometry's relationship to collision geometry remains genuinely **Unknown** (not Inferred) — kept that way deliberately per this project's evidentiary standard, since nothing found proves or disproves whether collision meshes are simplified relative to visual meshes here.

6. **A new, previously-undocumented live-position lead:** `heroMoveGetHeroPos`/`heroMoveGetHeroRot`, operating on a fixed-address `HeroMove` struct (`xd-decomp` `.bss:0x804479F0`). Symbol/address only, no decompiled body, unverified against XG — but a materially better starting point for a future player-position discovery experiment than a blind scan would be.

7. **A new battle-engine root-pointer lead:** `fightFloorBiosGetFightFloorPtr` (`.text:0x801F6274`, 3 instructions), sitting atop a large, systematically-named `fightFloor*`/`fightSide*` Bios-style accessor API. If this resolves to one root pointer, most other battle-state fields become offset-reachable instead of requiring separate blind scans each.

8. **A caveat that tempers the paused live investigation:** `gLastSelectedIndex`'s symbol-table neighbors are all camera-system globals (`pCamWork`, `gCurrentFOV`, `gLastMotionType`), not menu-system ones. When that investigation resumes, the writer instruction at `PC=0x800B35E4` needs checking against whether it's inside a camera-prefixed function before treating the earlier live hit as confirmation of menu-selection tracking.

9. **A new alternative to the refuted Phase 0B `g_pHero`/`_orreHero` hypothesis:** `Hero::getHeroPtr()` (from `Pokemon-XD-Code`) resolves through `savedataGetStatus(0, 2)`, not a direct static pointer — a different, more indirect access pattern worth trying if/when Phase 0B's HP-structure work resumes.

10. **The distribution-pipeline installer's hardest problem has zero precedent in either candidate tool.** Neither `pokemon-ngc-rando` nor `pokemon_fsys_tool` implements any hash verification anywhere (confirmed by exhaustive grep, zero hits in both). The installer design's hash-checking steps (input verification, output verification, XG-revision verification) must be written from scratch.

## Licensing summary (all repos touched by this pass)

| Repo | License | Reuse implication |
|---|---|---|
| `xd-decomp` | (existing repo — see REPOSITORY_AUDIT.md) | Already governs this project's primary codebase |
| `Pokemon-XD-Code` | (existing repo — see REPOSITORY_AUDIT.md) | Reference only per existing project convention |
| `XDscriptTools` | 3-clause BSD | Permissive — attribution required, otherwise low-friction to reuse/adapt |
| `Blender-Addon-Gamecube-Models` | GPLv3 | Copying code in requires this project's own code (at minimum, the combined addon-adjacent portion) to be GPL-compatible; **calling** the addon as an external tool/CLI process is not the same as incorporating its code and does not carry the same obligation |
| `pokemon-ngc-rando` | GPLv2 | Same caveat as above — copying its source into this project would make the combined program a GPLv2 derivative, requiring full source availability under GPLv2 for the whole program, not just the borrowed part. **Calling it as an external process is the safe reuse path**, per `DISTRIBUTION_PIPELINE.md`'s license section. |
| `pokemon_fsys_tool` | MIT | Permissive, no meaningful reuse friction |
| `PkmGCTools` | Split: `LibPkmGC`=LGPLv3, `PkmGCSaveEditor`=GPLv3 | Track sub-license per component if ever reused; LGPLv3 is more permissive (dynamic linking generally doesn't trigger copyleft) than the GPLv3 save editor |
| `GC-pokemon-RNG-manipulation-assistant` | MIT | Permissive; but this pass found it has no memory-address or Dolphin-integration content relevant to this project's needs — audited and found to be out of scope, not a reuse candidate |

**Standing rule, unchanged from the user's instructions:** none of the above license permissiveness changes the separate, absolute rule that no Nintendo game data (dialogue, models, maps, scripts, textures, or other extracted assets) is ever committed or distributed by this project, regardless of what license governs the *tooling* that could extract it.

## What this pass did NOT do

- No implementation. Every "design" section in the six deliverable documents is exactly that — a design, not code that runs.
- No live Dolphin testing. The paused Phase 0C investigation was left untouched, as instructed; the battle/menu audit was explicitly static/offline-only.
- No sending of the drafted community question.
- No attempt to build/run any of the six newly-cloned repos (per the user's Part 1 instruction: "Do not build every project merely because it was cloned").

See [ACCESSIBILITY_ARCHITECTURE_V2.md](ACCESSIBILITY_ARCHITECTURE_V2.md) for the resulting architecture recommendation, and the end-of-pass chat report for the three ranked next-step proposals awaiting approval.
