# ACCESSIBILITY_HOOKS.md

This document reframes [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md)'s findings around one question: **which hook points are actually good candidates for a screen-reader companion, ranked by how ready they are, and what's missing before each could be used?** Nothing here is a decision to implement — it's a prioritized readiness assessment.

## How to read the ranking

Each candidate gets:
- **Readiness** — Ready-to-probe (a specific address/symbol exists to test against XG once you have it), Needs discovery (concept confirmed to exist, no address — needs a memory-search experiment like Phase 0 in [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md)), or Needs decompilation (no shortcut exists — the logic itself isn't reverse-engineered enough to know what to look for).
- **Confidence** — Confirmed / Inferred / Unknown, per the same standard used throughout this audit.
- **XG risk** — how likely the vanilla-XD evidence is to transfer, given XG is an unknown-revision ROM hack.

## Live-evidence checkpoint — superseding the original Phase 0 ranking

- **Confirmed for vanilla GXXE01 revision 0:** the production companion resolves battle command focus, move focus, shared GSmsg battle sentences, dynamic move substitutions, stat changes, poison/faint/loss text, and stable active-battler HP through named structures.
- **Confirmed HP chain:** eight slots at `0x804A1730 + 0xDE44`; each slot provides `FightOutPokemon*`, then `FightPokemon*` at `+0x04`, embedded `Pokemon` at another `+0x04`, current HP at embedded `+0x04`, maximum HP at embedded `+0x90`, and nickname at `FightPokemon + 0x52`.
- **Confirmed display correlation:** status windows are dynamically reconstructed from manager `0x80445A68`; copied nickname, maximum HP, target HP, animation old HP, and duration permit a unique settled-event match. See [PHASE_1F_HEALTH_NARRATION.md](PHASE_1F_HEALTH_NARRATION.md).
- **Rejected as production hooks:** historical candidates `0x804454B4` and `0x804454BC`. They do not provide stable ownership or battler identity.
- **Production integration:** generic settled percentage-loss narration is implemented and passes 59 automated tests. Its one bounded Earthquake regression remains pending.
- **Still unknown:** every aspect of Pokémon XG compatibility. No vanilla address transfers to XG without a separate controlled validation.

The tier list below is retained as the original research prioritization. Entries describing menu or vanilla-XD HP discovery as future work are historical and are superseded by this checkpoint.

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

## Addendum — battle-menu static codemap audit (new candidates)

This section adds candidates surfaced by a static-only codemap pass (`xd-decomp` source/symbols + `Pokemon-XD-Code` cross-reference, no live testing) recorded in full in [BATTLE_MENU_RESEARCH.md](BATTLE_MENU_RESEARCH.md). It does not revise any ranking above; it slots new items into the same tiering.

### Tier 1 addition — Move IDs, PP, and move-property lookup
- **Readiness:** Ready-to-probe for the per-Pokémon side (struct offsets known and cross-project-corroborated), Needs decompilation for the move-property table backend.
- `Pokemon::wazas[4]` at struct offset `+0x80` (`xd-decomp/include/game/pxdvs/app/pokemon/pokemon.hpp:75-79,121`), each entry `{u16 dataId; u8 pp; u8 ppCount;}` — Confirmed real header, and independently corroborated by `Pokemon-XD-Code`'s `move1`/`move1PP`…`move4`/`move4PP` offsets `128-142` (`Objects/data types/XDPartyPokemon.swift:27-34`), which land on the exact same byte pattern. Same cross-project-agreement strength as the existing HP/status entries above.
- Static move-property table (name/power/type/PP/target-range/priority/message-IDs) exists as a full symbol-only `wazaDataBios*` Get/Set family (`xd-decomp/config/GXXE01/symbols.txt:5463-5539`) — Confirmed-exists, Unknown-body (no decompiled source).
- **XG risk:** Same caveat as HP/status — move/PP data is a plausible ROM-hack modification target.

### Tier 2 additions — battle-engine root pointer and target-selection static candidate
- **`fightFloorBiosGetFightFloorPtr`** (`.text:0x801F6274`, size `0xC` — trivial, almost certainly a bare pointer return): a large, systematic `fightFloor*`/`fightSide*` Bios-style accessor API exists in the retail binary (turn count, attack/defense Pokémon pointers, appointed move/target/item, per-side state, message IDs — full list in `BATTLE_MENU_RESEARCH.md` §4), all reachable in principle from this one root. **Readiness:** Needs discovery (disassembling this one short function to find its backing static global is the concrete next step) but structurally the most promising lead in the whole audit — one confirmed root would make most other battle-state fields offset-reachable instead of requiring individual blind scans.
- **`_target_fight_pokemon_ptr`** (`.sbss:0x804EA650`, real static global, not stack-relative) plus two neighbor pointers `_target_fight_side_ptr`/`_target_fight_trainer_ptr` (`.sbss:0x804EA648`/`0x804EA64C`) — a directly testable candidate for "which Pokémon is currently the move's target," using the same `Z2` write-watchpoint methodology `PHASE_0_RESULTS.md` already proved reliable. **Readiness:** Ready-to-probe. **Not yet live-tested.**
- **XG risk:** High for both, same reasoning as the existing "battle move/target selection" entry above (Tier 2 §5) — this addendum gives that entry concrete new addresses to try, it does not lower its risk rating.

### Caveat on the existing `gLastSelectedIndex` lead (Tier "next target" in the live-evidence checkpoint above)
Static analysis of `gLastSelectedIndex`'s (`.sdata:0x804E84CC`) immediate symbol-table neighborhood shows every adjacent named symbol is camera-system-related (`pCamWork`, `gCurrentFOV`, `gLastMotionType`, `gLoopCameraWaitTime` — `xd-decomp/config/GXXE01/symbols.txt:17009-17015`). This does not overrule the live result already recorded in `PHASE_0_RESULTS.md` (real watchpoint hit, right direction/magnitude, on a real Right press) — it's flagged as context for the next live step: when the paused investigation resumes and disassembles the writer at `PC=0x800B35E4`, check whether that PC falls inside a camera-prefixed function versus a `menuFight*`-prefixed one, since the write could plausibly be a camera-follow side effect of the UI action rather than the UI selection state itself. Full reasoning in `BATTLE_MENU_RESEARCH.md` §5.

### Note on `Hero::getHeroPtr()` (relevant to the refuted Phase 0B `g_pHero` hypothesis)
`xd-decomp`'s real decompiled source shows the retail code's actual live-`Hero*` accessor is `Hero::getHeroPtr()` (`.text:0x8015060C`), which calls `savedataGetStatus(0, 2)` (`.text:0x801CEFB4`) — not `g_pHero`. This doesn't reopen the Phase 0B refutation (`g_pHero`'s target still didn't match the expected struct), but it gives a source-grounded alternative accessor to try when that line of investigation resumes, instead of continuing to distrust `g_pHero` in isolation. Full reasoning in `BATTLE_MENU_RESEARCH.md` §3.

### RNG-manipulation-assistant repo (`Research/ThirdParty/GC-pokemon-RNG-manipulation-assistant`) — checked, no new addresses
This repo (starter-RNG manipulation via random-battle-team prediction, for both Pokémon Colosseum and XD) was checked as instructed for hardcoded battle/RNG memory addresses. **It has none.** It is a pure offline LCG-algorithm implementation (`Source/PokemonRNGSystem/BaseRNGSystem.h`/`.cpp` plus per-game subclasses `Colosseum/ColosseumRNGSystem`/`XD/GaleDarknessRNGSystem`) that predicts starter stats from a seed and frame-timing input alone — it has no Dolphin memory-engine integration and reads no live RAM at all, so it contributes no cross-reference data to this audit despite being an independent, already-working tool for this exact game family.
