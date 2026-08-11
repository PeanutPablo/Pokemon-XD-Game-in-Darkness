# XD_SCRIPTING_CODEMAP.md

Audit of the XD scripting system ("TCOD"/XDS script format, the "Tiga" VM, and the `AppScript` game-command dispatch layer), across three repositories:

- `Research/ThirdParty/XDscriptTools/` (TuxSH, 2015, 3-clause BSD, HEAD `ca8140a`) — small standalone Python **disassembler**.
- `Pokemon-XD-Code/` (PekanMmd/StarsMmd "GoD Tool", HEAD `f2d6c4a`, 2024-09) — large Swift toolkit; contains a full **disassembler + assembler/compiler + runtime patcher** for the same format.
- `xd-decomp/` (TeamOrre, primary decomp, HEAD `0173512`) — ground-truth symbol map (`config/GXXE01/symbols.txt`) and, for this subsystem, **zero real decompiled C++ source** (all `NonMatching` placeholders); still valuable for confirming real addresses/sizes/mangled signatures of the engine described by the other two.

Investigation date: 2026-07-24. Labels: **Confirmed** (verified by direct file/code read), **Inferred** (reasonable, not directly proven), **Unknown**. Every `Pokemon-XD-Code` address is scoped to retail XD **US (GXXE01)** only — see the version-scope warning in `ARCHITECTURE_CODEMAP.md`; nothing here is verified against XG.

---

## 0. Top-line answer to the core question this audit was commissioned to answer

**`Pokemon-XD-Code` contains a substantially richer script system than `XDscriptTools`, in every dimension: it disassembles, it *compiles/reassembles* (which `XDscriptTools`'s own README explicitly says it cannot do), it can decompile to a human-editable text macro language, and it includes a live-patching mechanism for injecting brand-new native script classes/functions into the running game via hand-written PowerPC ASM.** Where `XDscriptTools` documents ~10 of the engine's ~28 script classes with partial function tables (many entries literally named `unknownFunctionNNN`), `Pokemon-XD-Code`'s `XGScriptClassFunctionsData.swift` documents all ~28 classes with named, typed, macro-annotated functions — e.g. the `Character` class alone has ~100 fully-named, fully-parameter-typed functions in `Pokemon-XD-Code` versus ~5 named methods in `XDscriptTools`.

**Recommendation: do not maintain a duplicate/independent XD-script implementation in this project.** If/when this project needs to parse, generate, or inject XD/XG scripts, `Pokemon-XD-Code`'s `XDSScriptCompiler`/`XGScript`/`XGScriptClass` machinery (Swift, macOS-oriented but the format logic itself is platform-independent) is the more complete reference to port logic from or wrap, not `XDscriptTools`. **Licensing caveat, per your instructions: `Pokemon-XD-Code`'s license was not independently re-verified in this pass — treat any reuse as requiring its own license check before copying code; this document is audit-only, no code was copied.** `XDscriptTools` remains useful as a second, independent, much smaller cross-check of the low-level instruction/section format (and is unambiguously 3-clause BSD, confirmed), but it is not the disassembler/compiler of record for this project going forward.

---

## 1. Script container/file format — sections

**Confirmed (direct binary read of the bundled sample, cross-checked against both parsers' code):**

`Research/ThirdParty/XDscriptTools/common_script.scd` begins with the 4-byte ASCII magic `TCOD` (Confirmed by direct read of the file's first bytes) followed immediately by section magics `FTBL`, `HEAD`, `CODE`, and (later in the same file) `STRG`/`VECT`/`GVAR`/`GIRI`/`ARRY` markers, matching both parsers' section-name lists exactly.

| Section | Purpose | Confirmed in | Notes |
|---|---|---|---|
| `TCOD` | Outer container magic, not a "section" per se | Both | `Research/ThirdParty/XDscriptTools/XDscriptLib/_ScriptCtx.py:116` (`if src[:4] != b'TCOD'`); `Pokemon-XD-Code/Objects/scripts/XD/XDSScriptCompiler.swift:709` writes `0x54434F44` = ASCII `"TCOD"` |
| `FTBL` | Function table: exported function names → code offsets | Both | `_ScriptCtx.py:51-61` (`parseFTBLSection`); `XDSScriptCompiler.swift:712-792` (`compileFTBL`) |
| `HEAD` | List of function entry-point offsets + overall script entry point (`valueOffset`) | Both | `_ScriptCtx.py:63-65`; `XDSScriptCompiler.swift:794+` (`compileHEAD`) |
| `CODE` | The actual bytecode instruction stream (4-byte words) | Both | `_ScriptCtx.py:67-76`; `XDSScriptCompiler.swift:822` (`compileCODE`) |
| `STRG` | String constants (SJIS-decoded by `XDscriptTools`; see note in section 7 below re: real in-game encoding) | Both | `_ScriptCtx.py:79-84`; `XDSScriptCompiler.swift:942` (`compileSTRG`) |
| `VECT` | Vector (3-float) constants | Both | `_ScriptCtx.py:86-90`; `XDSScriptCompiler.swift:994` (`compileVECT`) |
| `GIRI` | Character/NPC references: pairs of `(grpID, resID)` u32s; `(grpID=0, resID=100)` is the player | Both | `_ScriptCtx.py:92-96` (docstring states the player convention directly); `XDSScriptCompiler.swift:1022` (`compileGIRI`) |
| `GVAR` | Global variables for this script, as 8-byte `XDscriptVar` (type + value) records | Both | `_ScriptCtx.py:98-102`; `XDSScriptCompiler.swift:859` (`compileGVAR`) |
| `ARRY` | Array constants | Both | `_ScriptCtx.py:104-112`; `XDSScriptCompiler.swift:887` (`compileARRY`) |

**Your secondhand list (CODE, FTBL, HEAD, GVAR, STRG, VECT, GIRI, ARRY) is Confirmed correct and complete** — both independent implementations (one BSD Python from 2015, one Swift from a separately-authored, actively-maintained project) agree on exactly these 8 section names, with the same field-level layout (both parsers read the same generic 0x20-byte section header: magic[4], totalSize[4], padding[8], nbElems[4], valueOffset[4], unknown[4], then data — `_ScriptCtx.py:9-30` docstring vs. `XDSScriptCompiler.swift`'s per-section `compileXXXX` functions, which write that same header shape). No additional section type was found in either repo beyond these 8 plus the outer `TCOD` container magic. **Confirmed, not just Inferred:** direct hex inspection of `common_script.scd` shows real `FTBL`-section function names — `modify_floor`, `preprocess`, `postprocess`, `hero_main`, `floor_link`, `door_open`, `elevator`, `elevator_out`, `fade_in`, `fade_out`, `fade_zero`, `tresure_move`, `check`, `carpet_move`, `use_pcbox`, `mark_move`, `talk_wait`, `cologn_use`, `evolution`, `watch_common_tv`, `watch_common_news`, `white_in`, `white_out`, `flagshop`, `tv_flag_check`, `restart_fade_in` — which is itself strong direct evidence for door/elevator/fade/save ("anywaysave") map-transition-style logic living in the common script's callback set, consistent with the `FunctionInfo.py` docstring's "Special callbacks" list (`XDscriptLib/FunctionInfo.py:49-63`, listing `pushpop_postprocess, modify_floor, preprocess, hero_main, postprocess, pushpop_preprocess, talk_follower, sound, anywaysave_callback, anywaysave_restart` as map-script callback names — **Confirmed** for the doc comment, cross-verified for the subset that literally appears in the sample file).

## 2. Opcode definitions / instruction set

**Confirmed, and the two repos' opcode tables are byte-identical for XD (18 opcodes, 0–17):**

| # | Name (`XDscriptTools`) | Name (`Pokemon-XD-Code`) |
|---|---|---|
| 0 | nop | nop |
| 1 | operator | operator |
| 2 | ldimm | ldimm |
| 3 | ldvar | ldvar |
| 4 | setvar | setvar |
| 5 | setvector | setvector |
| 6 | pop | pop |
| 7 | call | call |
| 8 | return | return |
| 9 | callstd | callstd |
| 10 | jmptrue | jmptrue |
| 11 | jmpfalse | jmpfalse |
| 12 | jmp | jmp |
| 13 | reserve | reserve |
| 14 | release | release |
| 15 | exit | exit |
| 16 | setline | setline |
| 17 | ldncpvar | ldncpvar |

Citations: `Research/ThirdParty/XDscriptTools/XDscriptLib/_Instruction.py:68-73` (`instructionNames` tuple); `Pokemon-XD-Code/Objects/scripts/XD/XGScriptOps.swift:35-91` (`XGScriptOps` enum + `instructionNames` array).

Each instruction word is `OOSSPPPP`: 8-bit opcode, 8-bit sub-opcode, 16-bit signed parameter — **Confirmed**, `_Instruction.py:17-20` docstring, matched by `XGScriptOps.swift`'s identical enum layout and `XGScriptInstruction.swift`'s field parsing.

**New finding not in `XDscriptTools`: `Pokemon-XD-Code` also documents a variant instruction set for Pokémon Battle Revolution (`#if GAME_PBR`) with 2 additional opcodes** — `unknown18` (18) and `loadShortImmediate` (19) — `Pokemon-XD-Code/Objects/scripts/XD/XGScriptOps.swift:11-33`. This is **Confirmed present in the source as a compile-time variant**, but **Unknown/not applicable to XD or XG** (PBR is a different game on different hardware); flagged only because it shows the same VM lineage extends to at least one other Genius Sonority title, corroborating the `GSscript`/`Tiga` naming found in `xd-decomp` (section 3 below) as a shared internal engine, not an XD-specific one-off.

Operators (16 total, indices 16–53, unary/binary/comparison) are also **Confirmed identical** between `FunctionInfo.py:80-115` and `XGScriptClassFunctionsData.swift:46-85` (e.g. `not=16`, `neg=17`, `add=35`, `equ=48`, `neq=53`).

## 3. Opcode/function metadata — the native engine identity (strongest finding of this audit)

**Confirmed, `xd-decomp`, symbol-only (no decompiled source, but real mangled C++ signatures resolved against the retail binary) — this is the single most valuable discovery of this pass:** the native script VM is a real C++ class named `GSscript::Tiga`, with companion classes `GSscript::tigaVariant` (the tagged-value type — this is almost certainly the native counterpart of `XDscriptVar`/`ScriptVar`) and `GSscript::TigaThread` (one thread per running script "task" — matches both repos' documented 8-task, sync/async multitasking model, `_Instruction.py:36-42`). Representative resolved symbols, `xd-decomp/config/GXXE01/symbols.txt`:

- `execute__Q28GSscript4TigaFPQ28GSscript10TigaThread = .text:0x8023B900` — the VM's main instruction-dispatch loop.
- `calcExpr1__Q28GSscript4TigaFiPQ28GSscript11tigaVariantPQ28GSscript11tigaVariant = .text:0x8023C898` / `calcExpr2` — operator evaluation (opcode 1).
- `execMethod__Q28GSscript4TigaFiiPQ28GSscript11tigaVariantPQ28GSscript11tigaVariant = .text:0x8023ACDC` — `callstd` dispatch (opcode 9), i.e. exactly the `classID.functionID` call convention both Python/Swift tools document.
- `makeThread`, `runParams`, `runParamsPC`, `runParamsWait`, `blockThread`, `unblockThread`, `deleteThread`, `stop`, `setSaveFlag` (all `Q28GSscript10TigaThreadF...` or `Q28GSscript4TigaF...`) — the task/thread lifecycle API.
- `mappingScript__Q28GSscript4TigaFPc = .text:0x8023D958` / `unmappingScript__Q28GSscript4TigaFv = .text:0x8023D8C8` — loads/unloads a raw script blob (a `char*`) into the VM; `setTpcChank__Q28GSscript4TigaFP6CChank = .text:0x8023D640` feeds it via a `CChank`/`CChankBlock` generic chunked-file reader (`searchChankID__6CChankFPCcl`, `loadFromMemory__11CChankBlockFPcPc` — `symbols.txt:10820-10857`), i.e. the retail engine's own low-level TCOD-section reader, independently corroborating the section-chunk format in section 1 above from the native-code side, not just the two RE tools' agreement with each other.
- `debugDump`, `getStateSize`, `restoreStateData`, `makeStateData` (save-state serialization of a `Tiga` instance) — relevant to "story flags / global variables / script execution state": **Confirmed** that script/thread state is explicitly save-file-serializable at the engine level, though the exact byte layout is not decompiled.

**Confirmed, `xd-decomp`, symbol-only — the game-specific command dispatch layer sits in a separate C++ class, `AppScript`,** whose ~20 `cmpXXX(int, tigaVariant*, tigaVariant*)` methods are the native implementations that `callstd` (opcode 9) ultimately reaches per script "class ID." These map almost exactly onto `Pokemon-XD-Code`'s documented `ScriptClassNames` table (`XGScriptClassFunctionsData.swift:12-43`):

| `AppScript::cmpXXX` (xd-decomp symbol, no source) | Size | Corresponding `Pokemon-XD-Code` script class |
|---|---|---|
| `cmpCamera` `.text:0x801BE3CC` | 0x21B0 | `Camera` (33) |
| `cmpFloor` `.text:0x801C057C` | 0x13B4 | `Map` (38) |
| `cmpHero` `.text:0x801C1930` | 0xFF8 | `Player` (43) |
| `cmpMenu` `.text:0x801C2928` | 0x1580 | `Menu` (40) |
| `cmpPeople` `.text:0x801C3EA8` | 0x1B9C | `Character` (35) — **the largest handler of the whole set, consistent with `Character` being documented as "the biggest class... 99 functions" in `XDscriptTools`'s own comment (`FunctionInfo.py:253`) and ~100 functions in `Pokemon-XD-Code`** |
| `cmpFight` `.text:0x801BB520` | 0x8F0 | `Battle` (42) |
| `cmpPokemon` `.text:0x801BC4E4` | 0x56C | `Pokemon` (37) |
| `cmpWaza` `.text:0x801B89E4` | 0x3DC | `Move` (58) — "waza" = move, consistent with the decompiled `PokemonWaza` struct in `pokemon.hpp` (see `ARCHITECTURE_CODEMAP.md` §5) |
| `cmpDarkPokemon` `.text:0x801B8768` | 0x27C | `ShadowPokemon` (59) |
| `cmpSodateya` `.text:0x801B8DC0` | 0x16C | `Daycare` (52) — "sodateya" = day-care (breeder) |
| `cmpTask` `.text:0x801BBF40` | 0x5A4 | `Tasks`/`Thread` (39/54) |
| `cmpFade` `.text:0x801BBE10` | 0x130 | `Transition` (41) |
| `cmpModel` `.text:0x801BA334` | 0xC4C | `Model` (45) |
| `cmpLight` `.text:0x801BAFAC` | 0x574 | `Light` (44) |
| `cmpCol` `.text:0x801BA204` | 0x130 | `Collision` (46) |
| `cmpSound` `.text:0x801B959C` | 0xC68 | `Sound` (47) |
| `cmpPad` `.text:0x801B9330` | 0x1F0 | `Controller` (48) |
| `cmpMail` `.text:0x801B91B0` | 0x180 | `PDA` (49) |
| `cmpTv` `.text:0x801B8F2C` | 0xA0 | `TV` (51) |
| `cmpDirection` `.text:0x801B8FCC` | 0x1E4 | `Direction` (50) |
| `cmpEsaba` `.text:0x801B8500` | 0x268 | no obvious `Pokemon-XD-Code` class-name match — **Unknown** ("esaba" untranslated; possibly a leftover/internal name not surfaced as a user-facing script class, or folded into another class in the Swift tool's naming) |

**This cross-repo correlation (independent naming — Japanese-derived internal symbol names in `xd-decomp` vs. English descriptive names reverse-engineered by `Pokemon-XD-Code`'s author from script disassembly — landing on the same ~20-way category split) is strong corroborating evidence that both projects are describing the same real subsystem correctly, from two independent angles (static symbol names vs. behavioral RE).** Neither project cites the other for this, so this convergence was not previously documented anywhere in this project's existing docs. `configure.py:1164-1173` confirms these all live in one still-unsourced object, `game/pxdvs/app/script/appScript.cpp` (`NonMatching`).

**Function-ID catalog — Confirmed comparison, `Pokemon-XD-Code` is markedly more complete:**

- `XDscriptTools/XDscriptLib/FunctionInfo.py` documents 12 of the ~28 class IDs with any function data (`""`(0), `Vector`(4), `Array`(7), `Character`(35, partial — 6 of 99 functions named), `Pokemon`(37, partial — ~13 functions), `Tasks`(39), `Dialogs`(40), `Transition`(41), `Player`(43, ~25 functions), `Daycare`(52), `TaskManager`(54), `ShadowPokemons`(59)); everything else is `UnknownClassNN`.
- `Pokemon-XD-Code/Objects/scripts/XD/XGScriptClassFunctionsData.swift` (841 lines) documents all classes 0–60 by name (`ScriptClassNames`, lines 12-43) and, for the ones with real script usage, full per-function tables including **typed parameter lists** (`XDSMacroTypes` — e.g. `.vector`, `.msg`, `.battleID`, `.partyMember`, `.floatAngleDegrees`) and **return-type annotations**, which neither `xd-decomp` nor `XDscriptTools` has at all. Example breadth: `Character` (35) has ~100 named functions (`XGScriptClassFunctionsData.swift:204-364` and others), `Player` (43) has ~40, `Battle` (42) has ~30, `Map`/floor-equivalent (38) has door/warp functions (section 6 below).

## 4. Function metadata catalog — character, party, gift/event Pokémon, other map/game ops

All entries below are **Confirmed** from `Pokemon-XD-Code/Objects/scripts/XD/XGScriptClassFunctionsData.swift` (the tuple format is `(name, functionIndex, paramCount, [paramTypes], returnType, hint)`), cross-referenced where possible against `XDscriptTools`'s smaller, independently-authored subset in the same file location (`FunctionInfo.py`).

**Character visibility / position / rotation / vectors** (class `Character`=35):
- `setVisibility(Character, bool)` — index 16, both repos agree (`FunctionInfo.py:258`, `XGScriptClassFunctionsData.swift:256`).
- `setPosition(Character, float x, float y, float z)` — index 29; `setPositionVector(Character, vector)` — index 30; `getPositionIntoVector` — 34; `getPosition() -> vector` — 75 (`XGScriptClassFunctionsData.swift:269-274,323`). **Not present at all in `XDscriptTools`.**
- `setRotation(Character, angleX, angleY, angleZ degrees)` — index 31; `setRotationVector` — 32; `getRotation() -> float` — 76 (`XGScriptClassFunctionsData.swift:271-272,324`). **Not present in `XDscriptTools`.**
- `walkToPosition`/`walkToPositionVector`/`walkToCharacter` (36-38), `turnToAngleRadians`/`turnToRotation`/`turnToCharacter` (47-49), `initializeNewWalkingRoute`/`addToWalkingRoute`/`beginWalkingRoute` (54-56) — full NPC movement scripting API, entirely undocumented in `XDscriptTools`.
- `attachToCharacter`/`detachFromCharacter` (51-52), `setModel` (70), `setScale` (108) — object/appearance ops.

**Dialogue / message display / yes-no choices** (class `Dialogs`=40 in `XDscriptTools`'s naming; `Character.talk` method 73 is the more commonly used path per `Pokemon-XD-Code`):
- `Character.talk(Character, type:int, msgID, ...)` — index 73, variadic; both repos document type codes: **Confirmed, `XDscriptTools`**, `FunctionInfo.py:265-272`: `1`=normal msg, `2`=character approaches-then-talks-then-leaves, `8`=**yes/no question**, `15`=play species cry, `16`=informative dialog with no sound (22 total type values, 1-3 and 6-21).
- `Dialogs.displayYesNoQuestion(msgID)` — index 21 (`FunctionInfo.py:327`) — a second, class-level yes/no path distinct from `Character.talk` type 8.
- `Dialogs.displaySilentMsgBox`/`displayMsgBox` (16-17, with "display char-by-char" and "text sound pitch" flags), `setMsgVar` (28, substitutes a variable into a message template — ties to the "variable-substitution codes for names" text-control-code system noted in `ARCHITECTURE_CODEMAP.md` §13), `promptPartyPokemon`/`openPokemonSummary` (32-34), `promptName` (36), `openPokemartMenu`/`openItemMenu` (39, 50), `openMoneyWindow`/`openPkCouponsWindow` (67, 70) — `FunctionInfo.py:320-354`.

**Party operations & gift/event Pokémon** (class `Player`=43):
- `receiveGiftOrEventPkm(int ID)` — index 37; `FunctionInfo.py:379-386` documents the actual ID→species mapping observed from real scripts (IDs 1–14: e.g. male Jolteon, male Vaporeon, Duking's Plusle, Mt. Battle Ho-Oh, Bonus Disc Pikachu, AGETO Celebi, shadow Togepi/Elekid/Meditite/Shuckle/Larvitar/Chikorita/Cyndaquil/Totodile) — this is a directly reusable ID table for narrating gift-Pokémon script events.
- `countPartyPkm`/`countShadowPartyPkm`/`countNotFaintedPartyPkm`/`countValidPartyPkm`/`countLegendaryPartyPkm` (34-35,41,43,53), `getPartyPkm(index)` (44), `getPartyPkmNameAsStr(index)` (36), `checkPkmOwnership(index)` (45), `releasePartyPkm(index)` (69), `healParty()` (39), `getFirstInvalidPartyPkmIndex()` (42) — `FunctionInfo.py:374-407`.
- Money/currency: `receiveMoney`/`getMoney` (29-30), `getPkCoupons`/`setPkCoupons`/`receivePkCoupons` (61-63).
- `startGroupBattle(int)` — index 40 — battle-trigger entry point at the `Player` level, distinct from the dedicated `Battle` class (below).

**Battle starts** (class `Battle`=42, `Pokemon-XD-Code` only — `XDscriptTools` does not document this class at all, listing class 42 only as `UnknownClass42`):
- `startScriptedBattle(battleID, isTrainer:bool, dontBlackOut:bool)` — index 16; `startOpenBattle(battleID)` — 17 (returns result instead of auto-handling the loss/blackout flow); `getBattleResult() -> {1=lose,2=win,3=tie}` — 18; plus ~20 more functions controlling next-battle overrides (battlefield, post-battle text, trainer type, Colosseum round, switch/erase-flag settings) — `Pokemon-XD-Code/Objects/scripts/XD/XGScriptClassFunctionsData.swift:530-556`. This entire class is a **new-to-this-project finding** not present in either prior audit doc or in `XDscriptTools`.

**Story flags / global variables / script execution state:**
- Single-flag ops (class 0, the "no class" pseudo-namespace): `setFlagToTrue`/`setFlagToFalse`/`setFlag`/`checkFlag`/`getFlag` — indices 129-133 (`FunctionInfo.py:154-160`, matched in `XGScriptClassFunctionsData.swift`'s class-0 table).
- Multi-flag ops: `checkMultiFlagsInv`/`checkMultiFlags` (139-140, variadic).
- Global variables persist via the `GVAR` section (per-script) — section 1 above; **Confirmed, `Pokemon-XD-Code`, live memory location, XD US only:** `XDProcess.swift:81-90` (`getFlag`) reads flags from `CommonIndexes.GeneralFlags.startOffset` inside `common.rel`'s own indexed-pointer table, at `flagOffset = flagsStart + (id * 6)` — **6 bytes per flag**, with an "unknown1"/metadata word read from a separate `FlagsMetaData` table region — this is a real, live, RAM-verified flag storage layout (comment: "Based on Ghidra decomp"), not just a script-side abstraction. **This is a genuinely new, concrete, byte-level fact this audit surfaced** that neither prior doc (`ARCHITECTURE_CODEMAP.md`) nor `XDscriptTools` records.
- Task/thread state: `Tasks.getLastReturnedInt`/`sleep` (20-21), `TaskManager.getTaskCounter`/`stopTask` (18-19) — script-visible thread bookkeeping, on top of the native `GSscript::TigaThread` save-state API in section 3.
- Variable storage levels (Confirmed, `XDscriptTools`, `_Instruction.py:135-153`, `variableName` property): level 0 = `$globals[n]` (per-script `GVAR` slot), level 1 = `$stack[n]` (local/stack variable), level 2 = `$lastResult` (single implicit return-value register), level 3 = "special" variables further split into singleton pseudo-objects (0–0x7F, resolved via the class-0 function-name table), characters (0x80–0x120, offset into the `GIRI` table), and arrays (≥0x200, offset into `ARRY`). **This 4-tier addressing scheme is Confirmed identical in both `XDscriptTools` and implied by `Pokemon-XD-Code`'s `XDSVariable`/compiler code**, though `Pokemon-XD-Code`'s own explicit prose description of the 4 tiers was not separately located — cite `XDscriptTools` as the primary source for this specific claim, **Inferred** (not separately re-derived) that `Pokemon-XD-Code`'s compiler necessarily implements the identical scheme since it must produce byte-compatible `CODE` sections.

## 5. How the common script is loaded

- **Confirmed, symbol-only, `xd-decomp`, no source:** `game/pxdvs/app/floor/floorScript.cpp` (`configure.py:1079`, `NonMatching`) contains `floorMappingCommonScript = .text:0x8012606C`, `floorGetCommonScript__Fv = .text:0x801261F8`, and class `FloorManager`'s `mappingCommonScript__12FloorManagerFPc = .text:0x801271DC` / `getCommonScript__12FloorManagerFv = .text:0x8012621C` / `setCommonScriptType__12FloorManagerF15FloorModuleType = .text:0x80127264`. This confirms a real, dedicated "common script" concept exists as first-class engine functionality (a `FloorManager`-owned pointer, distinct from each map's own script), and that its mapping/unmapping goes through the same generic `Tiga::mappingScript(char*)`/`unmappingScript()` API documented in section 3 — **Confirmed** the mechanism, **Unknown** the exact call site / trigger condition (no source; not traced to a specific boot-sequence instruction).
- **Confirmed, `Pokemon-XD-Code`, file-location level (static, not a runtime trace):** the common script is compiled into `common.rel` (aliased directly in the compiler: `Objects/scripts/XD/XDSScriptCompiler.swift:79-83`, `if file.fileName == XGFiles.common_rel.fileName.removeFileExtensions() { scdFile = XGFiles.common_rel }`), and `common.rel` itself is one of the files packed inside `common.fsys` per your brief — **this specific `common.rel`-inside-`common.fsys` packaging claim was not independently re-verified in this pass** (not directly located in the files read); treat as carried over from your brief, **Unknown** (not re-confirmed) rather than newly Confirmed here. The REL-loading mechanism itself (once the byte blob is in memory) **is** Confirmed generically: `xd-decomp`'s fully-decompiled `src/dolphin/os/OSLink.c` (528 lines, real source) implements the standard Nintendo `OSLink`/`OSLinkFixed` REL relocator (`symbols.txt:2957-2958`), and `GSfsysOSLinkPreFunc`/`GSfsysOSLinkPostFunc` (`symbols.txt:7869-7870`, no source) are the game-specific hooks that call it for FSYS-packaged REL files — i.e. common.rel (and every map .rel) most plausibly loads via this same generic FSYS→OSLink pipeline, though the specific call graph tying "common script" to this pipeline was not traced end-to-end (**Inferred**, not walked instruction-by-instruction).
- **On the "loaded after the health-and-safety screen" claim specifically: this was NOT found stated anywhere in either repo as a fact about common-script loading.** The phrase "health and safety screen" appears exactly once in `Pokemon-XD-Code`, in `Objects/processes/Dolphin/ColoXD/XD/XDProcess.swift:12-21`, as a comment describing an **unrelated, currently-unpopulated (`nil` for all regions) hook point** (`cacheClearInitialInjectionPoint`) intended for early instruction-cache invalidation after that screen — it is not evidence about when the common script loads. **Recommendation: treat "common script loads after the health-and-safety screen" as Unknown / unverified community folklore, not Confirmed, until traced directly (e.g. via a Dolphin breakpoint on `floorMappingCommonScript = 0x8012606C`).**
- Confirmed for the *common script's own content*: the `FTBL` function-name table extracted directly from `common_script.scd` (section 1 above) lists exactly the kind of cross-cutting, always-resident callback names (`hero_main`, `door_open`, `elevator`, `fade_in`/`fade_out`, `evolution`, `watch_common_tv`, `flagshop`, `restart_fade_in`) you'd expect from a script that's mapped once, globally, rather than per-map — consistent with (but not proof of) the "loaded once, early" framing.

## 6. How each map's own script is loaded

- **Confirmed, `Pokemon-XD-Code`, static structure:** each room has a runtime-filled `Map File ID` and a separate REL pointer in the static room table (`Objects/struct tables/RoomsTable.swift`, already documented in `ARCHITECTURE_CODEMAP.md` §11) — map scripts are packaged as the map's own `.rel` file (mirrored 1:1 by the `XDSScriptCompiler`'s own file-pairing logic: `Objects/scripts/XD/XDSScriptCompiler.swift:105-108`, which locates a sibling `.rel` with the same base filename as the `.xds`/`.scd` script text file being compiled, and a sibling `.msg` string table the same way, lines 111-115).
- **Confirmed, `xd-decomp`, symbol-only:** the `FloorManager`/`floorRead*` family (`floorReadResourceID`, `floorReadMapPre/PostFunc`, `floorReadObjPre/PostFunc`, `floorReadColPre/PostFunc` — already catalogued in `ARCHITECTURE_CODEMAP.md` §11) is the generic per-floor/per-room resource loader; nothing in the resolved symbol names specifically isolates a "read this floor's script" step distinctly from the common script's `floorMappingCommonScript`/`FloorManager::mappingCommonScript` pair above — **Unknown** whether per-map scripts go through a differently-named but parallel `FloorManager` method (no `floorMappingScript`-style symbol without "Common" in it was found) or reuse the same `mappingScript(char*)` call with a different source pointer (**Inferred** as the more likely design, since `Tiga::mappingScript` takes a raw buffer pointer with no "which script" semantics baked into the name — i.e. one generic VM-load function, invoked twice with two different source buffers, is architecturally simpler and matches the "only 8 tasks max, common script's tasks and map script's tasks coexist" model in `_Instruction.py:37-38`).
- **Confirmed, `Pokemon-XD-Code`, from the class-0 comment block:** `Tasks` function-ID convention — `"if (id & 0x59600000) != 0: current script, otherwise common script"` (`XDscriptTools/XDscriptLib/FunctionInfo.py:307`, matched conceptually by `Pokemon-XD-Code`'s `Tasks` class functions `createSyncTaskByID`/`createAsyncTaskByID`/`createSyncTaskByName`/`createAsyncTaskByName`, `XGScriptClassFunctionsData.swift` — both repos document this class) — this is the clearest **Confirmed** mechanism for how a map script and the common script coexist and call into each other: task/function IDs are namespaced by a bit flag, not by separate address spaces, meaning the common script's functions are directly callable by ID from a map script's task-creation calls (and vice versa), which is consistent with both being mapped into the same `Tiga` VM instance simultaneously rather than one replacing the other.

## 7. String/message references from scripts

- **Confirmed, both repos, section-level:** `STRG` section holds this *script's own* local constant strings (`ldimm` subOpcode 3, `str, ="..."` — `_Instruction.py:366-368`); this is separate from the much larger shared dialogue string table.
- **Confirmed, `Pokemon-XD-Code`, cross-referencing `ARCHITECTURE_CODEMAP.md` §3/§13 (not re-derived, carried forward as already-Confirmed):** the actual in-game dialogue message table is located via `common.rel`'s self-describing internal pointer table at index 136 (`CommonIndexes.StringTable1`), and the real per-character encoding is 2-byte big-endian Unicode code points with an extensive control-code scheme, **not** the `STRG` section's plain SJIS-decoded bytes that `XDscriptTools` assumes (`_ScriptCtx.py:83`, `sec.stringContents = sec.data.decode('sjis')`). **This is a real, Confirmed discrepancy between the two repos worth flagging explicitly for any future implementation: `XDscriptTools`'s SJIS decode of the `STRG` section is only correct for whatever `STRG` actually stores (likely short internal/debug strings, not player-facing dialogue) — do not assume it decodes the dialogue message table, which lives in a completely different location/encoding per `Pokemon-XD-Code`.**
- **Confirmed, `Pokemon-XD-Code`, `msg`-typed script parameters:** many function signatures take a `.msg` macro-typed parameter (e.g. `Character.talk(..., msg, ...)` — index 73; `Dialogs.displayMsgBox(msgID, ...)` — index 17) which the compiler/disassembler resolves against the paired `.msg` string-table file for that script (`XDSScriptCompiler.swift:111-115`) — i.e. **message IDs in `CODE` are indices into an external string table file, not into the script's own local `STRG` section**, for player-facing text. This directly resolves what would otherwise look like a contradiction between sections 1 and this section.

## 8. Character/NPC operations, object IDs, visibility, position/rotation, vectors

Covered exhaustively in section 4 above (Character class, ~100 functions). Object identity: **Confirmed, both repos** — a character/object reference in script-land is a `(grpID, resID)` pair stored in the `GIRI` section (`_ScriptCtx.py:92-96`; `XDSScriptCompiler.swift:1022`), where `(0, 100)` is reserved for the player character (`_ScriptCtx.py:93` docstring, **Confirmed** stated directly, not inferred). `Pokemon-XD-Code`'s `Character.attachToCharacterGIRI(gid, rid, mode)` (index 74) confirms `grpID`/`resID` are exposed directly as script-callable parameters, not just an internal compiler bookkeeping detail.

## 9. Warps, doors, map transitions

- **Confirmed, `Pokemon-XD-Code`, class `Map` (=38, `XDscriptTools` does not document this class at all — listed only as `UnknownClass38`):** `getNextWarpPointIndex(Map)` — index 20; `warpToMap(Map, room, entryPointIndex)` — 22; `warpToMapWithSoundEffect` — 23; `controlDoor(Map, ...)` — 24; `getWarpPointsListVector`/`getWarpPointsListFloat` — 47-48; `warpToMapWithTransitions(Map, room, unknown:bool, beforeWarpFn, afterWarpFn)` — 49 (`XGScriptClassFunctionsData.swift:397-426`). `Player.setSmoothWarp(bool)` — index 66 (`XGScriptClassFunctionsData.swift:611`). This is an **entirely new finding for this project** — no warp/door script-function catalog existed in `ARCHITECTURE_CODEMAP.md` before this pass (that document explicitly logged "no 'warp' symbols were found by name in `xd-decomp`'s `symbols.txt`" as Unknown, §11 — **still true and Confirmed again in this pass**, since `xd-decomp` has no source for `appScript.cpp`/`objFloor.cpp`; the warp API only exists, currently, as script-level metadata in `Pokemon-XD-Code`, not as native-code symbols).
- **Confirmed, `xd-decomp`, indirect corroboration:** the common script's own `FTBL` names (section 1) include `door_open`, `elevator`, `elevator_out` — real evidence that door/elevator handling is at least partly common-script-driven (callback-based), not purely a native `AppScript::cmpFloor` routine, though both likely cooperate (native `cmpFloor` = 0x13B4 bytes almost certainly implements `Map`'s `warpToMap`/`controlDoor` `callstd` targets, while the common script's `door_open`/`elevator` functions are the higher-level scripted behavior triggered by them).
- **Unknown:** exact `controlDoor` semantics beyond its signature (`Map, number, number, number -> integer`, `XGScriptClassFunctionsData.swift:401`) — parameter meanings not documented in either repo.

## 10. Dialogue display, yes/no choices, items, party operations, battle starts

All Confirmed and cited in sections 4 (party/gift-Pokémon/battle) and 7 (dialogue/messages) above. Items specifically: **Confirmed, `Pokemon-XD-Code`:** `Dialogs.openItemMenu(int)` — index 50 (`FunctionInfo.py:344`); `Player.receiveGiftOrEventPkm` is Pokémon-specific, not items — a generic "give item" script function was **not found by name** in either repo's documented function tables (**Unknown** — may exist under an undocumented index, or item-granting may be a data-table effect rather than a script call; not resolved in this pass).

## 11. Story flags, global variables, script execution state

Covered in section 4 above (flag functions, `GVAR` section, live RAM flag layout from `XDProcess.swift`, `TigaThread` save-state API). Repeating the single most actionable fact here for visibility: **Confirmed, `Pokemon-XD-Code`, XD US only, live memory:** flags are stored at `CommonIndexes.GeneralFlags.startOffset + kRELtoRAMOffsetDifference`, 6 bytes per flag, indexed by `id * 6`, bounded by `CommonIndexes.NumberOfGeneralFlags.value`, with a parallel `FlagsMetaData` table (`Objects/processes/Dolphin/ColoXD/XD/XDProcess.swift:81-90`). Comment explicitly says "Based on Ghidra decomp," meaning this specific fact traces back to a third-party disassembly effort outside either cloned repo's own original research — flagged for completeness, not as a weakness (Confirmed still applies to what's actually in the file you have).

---

## Summary table: `XDscriptTools` vs. `Pokemon-XD-Code` capability comparison

| Capability | `XDscriptTools` | `Pokemon-XD-Code` |
|---|---|---|
| Disassemble `.scd`/TCOD binary → text | Yes (its sole purpose) | Yes |
| Compile/reassemble text → `.scd`/TCOD binary | **No** (README: "disassembler, etc..."; no compiler code exists in the repo — **Confirmed absence**, `Research/ThirdParty/XDscriptTools/` contains no file with "compil" in its name or content) | **Yes** — `XDSScriptCompiler.swift`, full round-trip, writes real `TCOD`/`FTBL`/`HEAD`/`CODE`/`GVAR`/`ARRY`/`STRG`/`VECT`/`GIRI` sections |
| Decompile to a friendlier macro/text language | No (raw opcode mnemonics only) | Yes — typed, macro-annotated pseudo-code via `XDSMacroTypes` |
| Opcode table | 18 opcodes (XD only) | 18 opcodes + documented PBR variant (20) |
| Script-class function catalog | ~12 of ~28 classes, many functions unnamed (`unknownFunctionNNN`) | All ~28 classes named; hundreds of functions individually named, typed, and parameter-annotated |
| Live game-memory patching / new native function injection | No (static file tool only) | Yes — `XGScriptClass.repointToRAMOffset`/`createCustomClass`/`addASMFunctionToCustomClass` (`Objects/scripts/XD/XGScriptClass.swift:177-354`), with a real worked example injecting 3 new controller-trigger-reading script functions in `Code snippets.swift:7655-7689` |
| User-extensible custom script classes for compiling new scripts | No | Yes — `XGScript.loadCustomClasses()` reads a `"Custom Script Classes"` JSON file at compile/disassemble time (`Objects/scripts/XD/XGScript.swift:2450-2461`) |
| Last updated | 2015 (5 commits) | 2024-09 (part of an actively-larger, ~2-year-old-at-audit-time project) |
| License | 3-clause BSD (Confirmed) | Not re-verified in this pass — check before any code reuse |

**Bottom line for future implementation work in this project: `Pokemon-XD-Code` supersedes `XDscriptTools` for essentially every capability relevant to reading, generating, or modifying XD/XG scripts. The one thing `XDscriptTools` offers that's worth keeping in mind is its small size and simplicity as an independent cross-check of the low-level binary format — useful for validating that a from-scratch reimplementation's raw section/opcode parsing is correct, without needing to stand up any of `Pokemon-XD-Code`'s much larger Swift/macOS-oriented toolchain.** Neither repo's script-injection or script-authoring code should be copied into this project without a license check first, per your standing instruction — this document only records what exists and where, it recommends no code reuse action.
