# ACCESSIBILITY_HOOKS.md

This document reframes [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md)'s findings around one question: **which hook points are actually good candidates for a screen-reader companion, ranked by how ready they are, and what's missing before each could be used?** Nothing here is a decision to implement — it's a prioritized readiness assessment.

## How to read the ranking

Each candidate gets:
- **Readiness** — Ready-to-probe (a specific address/symbol exists to test against XG once you have it), Needs discovery (concept confirmed to exist, no address — needs a memory-search experiment like Phase 0 in [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md)), or Needs decompilation (no shortcut exists — the logic itself isn't reverse-engineered enough to know what to look for).
- **Confidence** — Confirmed / Inferred / Unknown, per the same standard used throughout this audit.
- **XG risk** — how likely the vanilla-XD evidence is to transfer, given XG is an unknown-revision ROM hack.

## Live-evidence checkpoint

- **Inferred, not Confirmed:** `0x804454B4` and `0x804454BC` behaved like mirrored active-battler HP fields in one vanilla-XD opening-battle session (590 → 170 → 125 → 53). They are investigation leads only.
- **Unknown:** the owning structure/pointer chain, stable maximum HP, opponent Metagross HP, survival across a complete Dolphin restart, and every aspect of XG applicability.
- **Refuted:** treating `_orreHero`, `_menuCtrlHero`, or the observed `g_pHero` target as a proven direct route to the active battle Pokémon.
- **Next target:** the battle command menu is preferred over the older title-menu proposal because it proves a directly useful part of the blind battle loop. No menu-selection address is yet verified.

## Tier 1 — Ready to probe once you have XG running (best first targets)

### 1. Title screen / first-menu cursor selection
- **Readiness:** Ready-to-probe. `xd-decomp` gives named, addressed accessor functions: `menuTitleGetSelect = 0x800A3194`, `menuTitleSetSelect = 0x800A31AC` (Confirmed symbol+address, vanilla XD US, no source body).
- **Why it's first:** This is exactly the target of the vertical slice in [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md). It's a single small integer, changes only on deliberate player action, and has no dependency on text-encoding work if you use a hand-built label table.
- **XG risk:** Unknown until tested. Title-screen code is often among the *least* likely to be touched by a ROM hack (hacks usually focus on battle mechanics, Pokémon data, or maps) — a reasonable, but unverified, first guess.

### 2. Overworld system-menu cursor (`_menuTopSelectCursor`)
- **Readiness:** Ready-to-probe. `_menuTopSelectCursor = .sbss:0x804EA798` (Confirmed symbol+address).
- **XG risk:** Same caveat as above — a generic menu-cursor variable is a moderate-likelihood-of-surviving target, but unverified.

### 3. Party Pokémon HP (current + max)
- **Readiness:** Ready-to-probe, and unusually well-supported: **two independent projects agree** that current HP sits at offset `0x4` within the per-Pokémon struct (`xd-decomp`'s `Pokemon.hp` at `pokemon.hpp:81-139`, and `Pokemon-XD-Code`'s `currentHP@4`). `maxHp` is at `0x90` per `xd-decomp`, `144(=0x90)` per `Pokemon-XD-Code` — **these also agree** (0x90 = 144 decimal). This cross-project agreement is the strongest corroboration found anywhere in this audit.
- **Why it matters for accessibility:** HP is probably the single most valuable piece of battle information to narrate continuously (health bars are a classic sighted-only UI element).
- **XG risk:** Higher than the menu items above — battle/Pokémon data structures are exactly what a "NeXt Gen"-style ROM hack is likely to modify (e.g. adding new stats, fields, or Pokémon slots could shift this offset). Treat as a good first hypothesis to test, not an assumption.

### 4. Status condition (poison/paralysis/etc.)
- **Readiness:** Ready-to-probe. `xd-decomp`: `Pokemon.condition` at offset `0x16`, real getter/setter bodies exist (`pokemonBios.cpp:24-29`). Bonus: `joutaiDataBiosGetStatus/StatusKind/GetName` (symbol-only) suggests a name-lookup path exists in the retail binary for narrating the status by name, not just by numeric ID. `Pokemon-XD-Code` has `status@22(=0x16)` — **agrees exactly with `xd-decomp`.**
- **XG risk:** Same caveat as HP — a plausible ROM-hack modification target.

## Tier 2 — Concept confirmed, but needs its own discovery pass or is event-driven rather than pollable

### 5. Battle move/target selection
- **Readiness:** Needs discovery for a *pollable* address — what exists today (`Pokemon-XD-Code`'s `onDidConfirmMoveSelection`/`onDidConfirmTurnSelection` breakpoints reading CPU registers) is **event-driven via code injection**, which Route B (pure memory polling) cannot use as-is. A polling-only companion would need to find a *persistent* memory value that reflects "currently highlighted move/target" (if one exists at all — some UIs only ever compute the choice transiently in registers, never storing intermediate highlight state in RAM in an easily-findable way). This needs its own targeted memory-search/debugger session against XG, informed by (but not assumed equal to) the vanilla addresses in [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md) categories 4-6.
- **Why it matters:** This is the natural "next slice" after the title-menu prototype — narrating "Fight / Bag / Pokémon / Run," then move names, then targets.
- **XG risk:** High — battle command flow is core gameplay logic, a likely area for a gameplay-focused ROM hack to touch.

### 6. Dialogue/message-box text
- **Readiness:** Needs discovery. Both repos confirm the *concept* (message-box classes/functions exist) but neither has a live "currently displayed text" RAM address. Compounded by the encoding question: `xd-decomp` points to an SJIS-sourced "GSchar" internal format; `Pokemon-XD-Code` documents the stored/on-disk format as 2-byte big-endian Unicode codepoints with an extensive control-code scheme. These two claims are not yet reconciled (see [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md) category 13) — meaning even after finding the right address, correctly decoding what's there is a second, separate task.
- **XG risk:** Uncertain — depends heavily on whether XG changes any dialogue/script content (very likely, since new text/story content is a defining feature of most "ROM hack" style projects) versus whether it changes the *engine* that displays that text (less certain, but plausible if new UI/text features were added).

### 7. Battle turn messages / results (damage dealt, "it's super effective," etc.)
- **Readiness:** Needs discovery — same open question as dialogue text (category 6), plus a deep, currently-symbol-only battle-message-ID system (`getLogMsgBattle`, `fightFloorBiosSetWazakoukaMsgId`, etc.) that would need real decompilation to fully understand rather than just poll, since these appear to be message *IDs* looked up into a string table, not raw text.
- **XG risk:** High — battle-result text is exactly what a "NeXt Gen"-style hack is likely to expand (new move effects, new message variety).

## Tier 3 — Needs real decompilation, not just discovery (no practical memory-polling shortcut)

### 8. Maps, rooms, doors, warps, collision, NPC interaction
- **Readiness:** Needs decompilation for anything beyond "what room am I in" (which has a Ready-to-probe candidate: `Pokemon-XD-Code`'s `0x80814ab6`, XD US). Collision and warp/door logic are file-format-level constructs (loaded per-room from disc), not simple live flags — narrating "there's a door to your north" isn't a single memory read, it requires understanding the room's loaded collision/interaction data structurally.
- **Explicitly out of scope right now** per your instructions ("do not attempt overworld navigation yet") — included here only so the audit is complete, not as a next step.

### 9. Player position/facing
- **Readiness:** Needs discovery at minimum (no live player-position address found in either repo — only NPC placement data, which is a different thing). Even once found, turning raw X/Y/Z/facing into something narratable (e.g., relative directions, "wall to your left") is a design problem on top of the data problem.
- **Explicitly out of scope right now** per your instructions.

### 10. The in-game debug menu system (`dbgMenu*`)
- **Readiness:** Intriguing but needs decompilation. 278 resolved `dbgMenu*` symbols exist in the shipped retail binary (Confirmed via symbol count), suggesting a substantial built-in developer tool (camera, floor/map, Pokémon editor, fight/battle tools, sound test, memory-card tools, move viewer, log viewer — `dbgMenuLog.cpp` is literally in the placeholder list) is present but completely undocumented at the source level in `xd-decomp` today.
- **Why it's interesting, not why it's a shortcut:** If this debug menu is reachable in-game (varies by title — some GC games gate debug menus behind a specific save flag, memory-card file, or button combo) it could in principle expose diagnostic text dumps useful for reverse engineering. But this is speculative — neither repo documents how to reach it, whether XG retains it, or what it actually outputs. Treat as a research lead, not a plan.

## What this means for prioritizing follow-on work (after the title-menu vertical slice)

Recommended order, purely by readiness-and-corroboration-strength, not by narrative importance:
1. Title-menu selection (already the vertical slice target).
2. HP + status condition (Tier 1, cross-project corroborated, high accessibility value, moderate XG risk).
3. Overworld system-menu cursor (Tier 1, same pattern as #1).
4. Battle command/move/target selection (Tier 2, higher effort, very high accessibility value — this is the core "can a blind player actually play battles" question).
5. Dialogue and battle-message text (Tier 2, hardest of the near-term items due to the unresolved encoding question).

Everything in Tier 3 is explicitly deferred per your current instructions and shouldn't be started until the above prove the approach works and you decide to expand scope.
