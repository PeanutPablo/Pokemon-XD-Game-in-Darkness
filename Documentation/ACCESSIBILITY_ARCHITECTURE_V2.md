# ACCESSIBILITY_ARCHITECTURE_V2.md

Architecture recommendation, revised in light of the 2026-07-24 community-tooling audit ([COMMUNITY_TOOLING_AUDIT.md](COMMUNITY_TOOLING_AUDIT.md)). Supersedes the recommendation in [IMPLEMENTATION_ROUTE_COMPARISON.md](IMPLEMENTATION_ROUTE_COMPARISON.md) only insofar as new evidence refines it — that document's original reasoning (why Route B / read-only external memory access was preferred over code injection or a custom Dolphin build) still holds and isn't re-litigated here.

## The four options, revisited

- **A. Runtime memory reading plus static local indexes** — what this project has been doing since Phase 0. Read-only, reversible, no game-binary modification, works against an unmodified XG install.
- **B. Game-side code injection** — modifying `main.dol`/REL files to add new logic (e.g. hooking dialogue-display to emit an accessible event). `xd-decomp`'s `--non-matching` build mode supports *modifying* already-decompiled functions; `Pokemon-XD-Code`'s `addASMFunctionToCustomClass` mechanism (newly discovered this pass, see `XD_SCRIPTING_CODEMAP.md` §3) supports adding **new** script-level functions without needing the target function decompiled first. Both are real, working mechanisms now, not hypothetical.
- **C. A custom Dolphin build** — patching Dolphin itself (e.g. exposing better hooks than the GDB stub). Nothing in this pass changed the earlier reasoning against this: high maintenance burden, and the GDB-stub route has proven workable (with the caveat that `Z0` execution breakpoints are unreliable — see PHASE_0_RESULTS.md — but `Z2` write watchpoints are fully reliable).
- **D. Hybrid** — the user's stated preference, combining A with narrow, deliberate use of B only where A cannot reliably observe something.

## Recommendation: D (hybrid), confirmed and refined

The user's stated architecture is confirmed as the right target, and this pass gives it sharper edges than before:

- **External companion (NVDA/Tolk, configuration, speech priorities, user commands)** — unchanged, already working (Phase 0A confirmed NVDA speech via Tolk).
- **Locally generated static database (text, maps, metadata)** — now has a concrete generation path: `Pokemon-XD-Code`'s FSYS/string-table/script parsers (Swift) or `pokemon-ngc-rando`'s independently-reimplemented equivalents (C#) can both walk a user's own XG disc image and extract the needed tables offline. Per the legal boundary already in force, this generated database stays local and gitignored — never committed, never distributed. Calling either tool as an **external process** (not copying its code) sidesteps the GPLv2 licensing consequence documented in `DISTRIBUTION_PIPELINE.md`.
- **Read-only Dolphin memory (live state)** — unchanged mechanism (GDB stub `Z2` watchpoints, or `dolphin_memory_engine` for simple polling reads), now with several new concrete candidate addresses/symbols from this pass to test once XG is available (battle-engine root pointer, hero-position struct, message-ID field).
- **Minimal game-side instrumentation, only where read-only observation genuinely cannot reach** — this tier remains real but should stay the last resort per the user's own framing ("do not recommend injection merely because one RAM scan failed... also do not reject injection categorically"). The newly-discovered `Pokemon-XD-Code` script-injection mechanism (item 2 above) is the concrete tool to reach for *if* a specific subsystem turns out to need it — e.g., if message-display is event-driven with no reliable pollable "currently active" flag, a one-instruction script hook that writes a value to an otherwise-unused global the companion can poll would be a narrowly-scoped, reversible use of Route B, not a wholesale binary patch.

## Per-subsystem recommendation

| Subsystem | Preferred source | Why (this pass's evidence) |
|---|---|---|
| Pokémon/move/item names | Static extracted tables | `Pokemon-XD-Code`'s `XGStringTable.swift` and data-definition parsers already do this; no live state needed for names that don't change at runtime |
| Dialogue text | Static strings + live message ID | String format and control codes fully mapped (`TEXT_AND_DIALOGUE_PIPELINE.md`); best live-ID lead is `_MsgID`/`msgctrlMsgID` (`.sbss:0x804EB284`) plus `dispMsgYesNo__FUl`/`dispMsg__FUl`, both taking a message ID as their primary argument — needs live verification, not yet tested |
| Battle state (HP, status, party) | Live runtime structures | Phase 0B already validated an HP-candidate structure (Inferred); this pass adds the `Pokemon` struct full field map and the `fightFloor*` battle-engine namespace as next live-test targets |
| Menu focus / selection | Live menu object or controlled hook | Symbol-first tracing is the proven method (`Z2` watchpoints); `gLastSelectedIndex` is a real but camera-neighbor-caveated lead, `fightFloorBiosGetFightFloorPtr` is a promising root-pointer candidate — both need live re-testing before either is trusted |
| Move/target selection | Live runtime structures | `BATTLE_MENU_RESEARCH.md` §7 documents symbol-only target-selection candidates; needs the same live-watchpoint verification as menu focus |
| Map names and connections | Static scripts/assets | `MAP_ASSET_RESEARCH.md` documents room-ID and connection data as static/on-disk |
| Player position/facing | Live runtime state | New lead this pass: `heroMoveGetHeroPos`/`heroMoveGetHeroRot` on a fixed-address `HeroMove` struct (`.bss:0x804479F0`) — symbol-only, unverified, but a real starting point instead of a blind scan |
| Doors/NPCs/interactables | Static scripts/assets + live state | Static placement data confirmed in `Pokemon-XD-Code`'s room-file parsers; live state needed only to know which are currently relevant (e.g. which NPCs are in the loaded room) |
| Collision/walkable geometry | Static assets, confidence level Unknown | Real collision-format code exists (`XGCollisionData.swift`), and interaction triggers are confirmed to share the collision mesh — but the relationship between collision and *visual* geometry is explicitly Unknown; do not present navigation guidance as validated-safe until this is resolved with a real room-by-room check |
| Script/event state | Static script disassembly + live thread/variable state | `GSscript::TigaThread` (per-task script thread) and `GSscript::tigaVariant` (tagged value) are the real native types per the scripting codemap; live state here is genuinely new discovery territory, not yet attempted |
| Speech | External Tolk/NVDA companion | Unchanged, already working |

## What changed from the user's original table vs. this one

The user's proposed table in their request was already directionally correct; this pass's contribution is turning "live runtime structures/events" and "live menu object or controlled hook" from abstract categories into specific, named, address-cited candidates ready for the next live-testing session — and flagging exactly one place (collision-vs-visual geometry) where the honest answer is still "we don't know," rather than letting optimism about the Blender addon's format support imply more certainty than the evidence supports.

## Immediate implication for sequencing

Because Route B (script injection) now has a *demonstrated*, low-risk mechanism (`Pokemon-XD-Code`'s custom-class ASM injection) rather than being purely theoretical, it's reasonable to keep it in the toolkit for one specific, narrow future case — a subsystem where Phase 0-style read-only discovery genuinely stalls (e.g., an event-driven flag with no pollable live state at all) — without that changing the overall preference for Route A everywhere it works. This is a refinement, not a reversal, of the existing recommendation.
