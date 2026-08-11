# BATTLE_MENU_RESEARCH.md

Static-analysis codemap of battle-menu structures: battle command definitions, `menuFight*` functions, move/target selection, active battlers, party slots, move IDs/PP, HP/max HP, status, shadow status, turn state, battle-message IDs, and controller/input functions.

**Scope and method, stated up front:** this document is pure static analysis — reading `xd-decomp`'s decompiled source and symbol table (`xd-decomp/config/GXXE01/symbols.txt`), and `Pokemon-XD-Code`'s Swift source (a separate, independent reverse-engineering project, aka "GoD Tool") — against the same vanilla US GXXE01 build referenced throughout this project's documentation. No live emulator connection, no memory reads, no re-testing of the paused live investigation was performed to produce this document. Everything here is offline/source-level Confirmed or Inferred, never live-Confirmed unless explicitly cross-referencing a result already recorded in `PHASE_0_RESULTS.md`.

**Relationship to `PHASE_0_RESULTS.md`:** that document is authoritative for everything live-tested so far and is not edited here. Anything below that looks like a good next live-test candidate is flagged explicitly as **candidate for future PHASE_0_RESULTS.md integration** — none of it is asserted as confirmed live behavior.

---

## 1. Two independent static sources, and how they relate

- **`xd-decomp`** — C++ decompilation project. Gives named, addressed `.text` functions and `.data`/`.sdata`/`.sbss`/`.bss` globals for the retail US GXXE01 binary, plus a handful of fully decompiled source files (including the `Pokemon`/`Hero` classes used below). Citations below are `symbol = section:0xADDRESS` (from `symbols.txt`, line numbers given) or `file:line` for real source.
- **`Pokemon-XD-Code`** ("GoD Tool") — Swift project for offline .dol/.iso editing *and* a separate live Dolphin-breakpoint-injection debugger (`ColoXDProcess.swift` / `XDBreakPoints.swift`). Its **breakpoint addresses are `.text` addresses in the same US GXXE01 binary**, so they are directly cross-referenceable against `xd-decomp` symbols by address, even though the two projects don't reference each other. Its **struct-offset constants** (`kPartyPokemon*Offset`, `kBattlePokemon*Offset`) describe an **in-memory struct layout**, not a disc-file layout — confirmed by the fact that `kPartyPokemonSpeciesOffset=0`, `=2`, `=4`, `=22`(0x16), `=128`(0x80), `=144`(0x90) match `xd-decomp`'s `Pokemon` struct field offsets (`dataID@0`, `itemDataID@2`, `hp@4`, `condition@0x16`, `wazas@0x80`, `maxHp@0x90`) exactly — this is the same cross-project agreement already noted in `ACCESSIBILITY_HOOKS.md` Tier 1 §3/§4, extended here with the fields `ACCESSIBILITY_HOOKS.md` didn't cover (PP, moves, stat stages, ability, type, shadow ID).

---

## 2. The `Pokemon` struct (party storage) — full field map

Source: `xd-decomp/include/game/pxdvs/app/pokemon/pokemon.hpp` (Confirmed, real decompiled header, not symbol-only), cross-checked field-for-field against `Pokemon-XD-Code/Objects/data types/XDPartyPokemon.swift:10-63` (`kPartyPokemon*Offset` constants). Struct size implied by both: `0xc4` bytes per Pokémon (`Pokemon-XD-Code`'s `kSizeOfPartyPokemonData = 0xc4`, `XDPartyPokemon.swift:81`).

| Offset | Field (`xd-decomp` name) | Field (`Pokemon-XD-Code` name) | Notes |
|---|---|---|---|
| `0x0` | `dataID` (u16) | `species` | Pokédex/species ID |
| `0x2` | `itemDataID` (u16) | `item` | Held item |
| `0x4` | `hp` (u16) | `currentHP` | **Current HP** — see §5 for the live-observed candidate this offset would predict, cross-referenced |
| `0x6` | `friendLevel` (u16) | `happiness` | |
| `0x8` | `catchFloorId` (u16) | — | |
| `0xa` | `amari` (u16) | — | |
| `0xc` | `para1Amari` (u16) | — | |
| `0xe` | `catchLevel` (u8) | `levelCaughtAt` | |
| `0xf` | `catchBallId` (u8) | `pokeballCaughtIn` | |
| `0x10` | `catchTrainerSex` (u8) | — | |
| `0x11` | `level` (u8) | `level` | |
| `0x12` | `fur` (u8) | — | |
| `0x13` | `pokerus` (u8) | — | |
| `0x14` | `pcboxMark` (u8) | — | |
| `0x15` | `mailId` (u8) | — | |
| `0x16` | **`condition`** (u8) | **`status`** | **Non-volatile status condition** (poison/paralysis/etc — see §7 for the ID table) |
| `0x17` | `conditionCount` (u8) | — | |
| `0x18` | `conditionTurn` (u8) | — | |
| `0x19` | `conditionTurnNow` (u8) | — | |
| `0x1d` | `flags` (bitfield: `tamago`/`tokusei`/`fusei`) | — | |
| `0x20` | `exp` (u32) | `expTotal` | |
| `0x24` | `catchTrainerRnd` (u32) | — | |
| `0x28` | `rnd` (u32) | `PID` (Personality ID) | |
| `0x2c` | `conditionAmari` (u32) | — | |
| `0x30` | `eventGetFlag` (u32) | — | |
| `0x34` | `attest` (4 bytes) | — | Validity-check struct, see `Hero::getPokemon` below |
| `0x38` | `catchTrainerName[11]` | `OTName` (offset `0x38`/56 decimal, matches) | |
| `0x4e` | `nickname[11]` | `nickname` (offset `0x4e`/78 decimal, matches) | |
| `0x64` | `nicknameOrg[11]` | `speciesName` (offset `0x64`/100 decimal, matches) | |
| `0x7c` | `ribbon` (union, 4 bytes) | `ribbons` (offset `0x7c`/124, matches) | |
| **`0x80`** | **`wazas[4]`** (`PokemonWaza{u16 dataId; u8 pp; u8 ppCount;}`, 4 bytes each) | **`move1`/`move1PP`/…/`move4`/`move4PP`** (offsets 128–142) | **Move IDs and PP** — see §6 |
| `0x90` | `maxHp` (u16) | `maxHP` (offset `0x90`/144, matches) | **Max HP** |
| `0x92`–`0x9a` | `phyAtk`/`phyDef`/`speAtk`/`speDef`/`nimbleness` (u16 each) | `attack`/`defense`/`specialAttack`/`specialDefense`/`speed` | Base stats (post-calculation) |
| `0x9c`–`0xa6` | `*Effort` fields (EVs, u16 each) | `EV*` fields (offsets 156–166) | |
| `0xa8` | `statusRnd` (`PokemonStatusRnd`, packed IVs) | `IV*` fields (offsets 168–173, 1 byte each) | |
| `0xae` | `expandStatus[2]` (contest stats) | — | |
| `0xb8` | `fightTrainerPokemonDataId` (u16) | — | |
| `0xba` | **`darkPokemonDataID`** (u16) | **`shadowID`** (offset `0xba`/186, matches) | **Shadow-Pokémon status/ID** — see §8 |
| `0xbc` | `comboPartnerAll` (u8) | — | |

**Accessors** (all `.text`, real getters/setters with disassembled-equivalent C++ bodies in `xd-decomp/src/game/pxdvs/app/pokemon/pokemonStatusPokemon.cpp:1-350`): `Pokemon::getHp()/setHp()`, `getCondition()/setCondition()`, `getMaxHp()/setMaxHp()`, `getDarkPokemonDataId()`, `isDarkPokemon()` (declared `pokemon.hpp:233`, body not in the decompiled excerpt), `initCondition()` (`pokemonStatusPokemon.cpp:248-253`, zeroes all 4 condition fields at once — useful if you ever need to recognize "status just cleared" as a single write instead of chasing 4 separate byte writes), `getPokemonWaza(u16 wazaNum)` (`pokemonStatusPokemon.cpp:264-270`, returns `&wazas[wazaNum]`, bounds-checked against `MAX_WAZA=4`).

**Note on `hp @ +0x4`:** this is the field `PHASE_0_RESULTS.md` Phase 0B was testing for when it tried `_orreHero`/`_menuCtrlHero` + `partyPokemon[6]` (`+0x30`) + `Pokemon.hp` (`+0x4`) and got refuted (`g_pHero`'s target didn't match either static struct). **This document does not re-open that refutation** — the struct layout itself (`+0x4` for HP) is corroborated further here by GoD Tool's independent offset table, but *which pointer leads to a live instance of this struct* remains the open question. §4 below has a new lead on that specific point.

---

## 3. `Hero` class — party container and the pointer-chain problem

Source: `xd-decomp/include/game/pxdvs/app/hero/hero.hpp` (Confirmed real header) + `xd-decomp/src/game/pxdvs/app/hero/heroMemberFunctions.cpp` (Confirmed real source, with `/* --INFO-- Address: ... */` comments giving the exact `.text` address of each compiled method).

- `Pokemon partyPokemon[6]` at **`Hero + 0x30`** (`hero.hpp:15`) — matches the struct `PHASE_0_RESULTS.md` Phase 0B tested.
- `Pokemon *Hero::getPokemon(s32 partySlot)` — `.text:0x801508F8`, body: `return &partyPokemon[partySlot]` after a `0 <= partySlot < 6` bounds check (`heroMemberFunctions.cpp:330-336`). This is the canonical, bounds-checked party-slot accessor — **party slot indexing is trivially `partySlot`, 0–5, no separate lookup table.**
- `Pokemon *Hero::getPokemon(s32 partySlot, bool &isHatena)` — `.text:0x80150828` (`heroMemberFunctions.cpp:282-310`) — the "full" accessor used by menus: additionally validates `pokemonDataID != 0`, `gamedataAttestCheckValid(pokemon->getAttest())`, and `!pokemon->isFuseiFlag()` before returning non-null. This is likely the real gate a menu system calls before showing a party slot as populated — a slot can have nonzero bytes and still be treated as empty if any of these three checks fail.
- **`Hero::getHeroPtr()`** — `.text:0x8015060C` (`heroMemberFunctions.cpp:174-179`):
  ```cpp
  Hero *Hero::getHeroPtr() {
    Hero *heroPtr;
    heroPtr = (Hero *)savedataGetStatus(0, 2);
    return heroPtr;
  }
  ```
  **This is a genuinely new static finding relative to `PHASE_0_RESULTS.md`.** The live investigation's Phase 0B hypothesis path was `g_pHero` (`.sbss:0x804EBBE0`) → refuted. **This static source shows the game's own code does not use `g_pHero` to get the live `Hero*` at all** — it calls `savedataGetStatus(0, 2)` (`.text:0x801CEFB4`, size `0x168`, `xd-decomp/config/GXXE01/symbols.txt:8282`). `g_pHero` may still be a real, separately-maintained cache/copy of this pointer (it *was* observed live as a real non-null pointer during battle), but `Hero::getHeroPtr()` is the actual accessor the retail code defines, and it goes through the save-data subsystem, not a bare global.

  **Candidate for future PHASE_0_RESULTS.md integration:** when the live investigation resumes, calling/emulating `savedataGetStatus(0, 2)` (or setting a read/execution breakpoint on `0x801CEFB4` and inspecting `r3`/return value during battle) is a more source-grounded way to find the live `Hero*` than continuing to distrust `g_pHero`'s target. If `savedataGetStatus(0,2)`'s returned pointer, plus `0x30`, plus `partySlot*0xc4`, plus `0x4`, lands on a value matching the already-known-good HP candidate `0x804454B4`/`0x804454BC` from Phase 0C, that would be strong triangulating evidence tying the brute-force-found HP address back to the named struct for the first time. **Do not test this now — this is a note for the paused live investigation, not an action taken here.**

- Other `Hero` fields relevant to battle bookkeeping (`hero.hpp:37-54`): `battleResumeFloorID`/`battleResumeFloorIndex` (`+0x95a`/`+0x95c`), `meetShadowPokemonCount` (`+0x938`, note: `xd-decomp`'s own method comment calls the same field `getMeetDarkPokemonCount`/`setMeetDarkPokemonCount` — "dark" and "shadow" are used interchangeably for the same concept throughout this codebase, consistent with the Japanese-origin "shadow Pokémon" naming), `battleCDItems[60]` (`+0x7f0`, "Battle CDs" — an XD-specific item category used in-battle).

---

## 4. The `fightFloor*`/`fightSide*`/`fightTrainer*` battle-engine namespace (new — not covered in `ACCESSIBILITY_HOOKS.md` Tier 2 §5)

This is by far the largest coherent finding of this audit: `xd-decomp`'s symbol table contains a **large, systematic Bios-style accessor API** for live battle state, under the `fightFloor*` prefix (all `.text`, all real named+addressed retail functions, none decompiled to C++ source — symbol-only, but the naming is exhaustive and consistent enough to read as documentation in itself). Representative entries (`xd-decomp/config/GXXE01/symbols.txt:8824-8996`, `dbgMenuFight*` debug-menu wrappers excluded from this table since those are developer-tool-only, not retail hooks):

| Symbol | Address | What it implies exists |
|---|---|---|
| `fightFloorBiosGetFightFloorPtr` | `0x801F6274` | **A singleton "current fight floor" object accessor** — the natural root of the whole live battle-state tree. Size `0xC` (trivial getter of a stored pointer/field) |
| `fightFloorBiosGetTurnCount` / `...SetTurnCount` | `0x801F622C` / `0x801F5FF4` | **Turn counter**, get+set pair both exist |
| `fightFloorBiosGetAttackPokemonPtr` / `...GetDefensePokemonPtr` | `0x801F61C4` / `0x801F61A8` | **Active attacker/defender Pokémon pointers** — the direct "who's acting right now" accessor, get+set pairs exist (`...SetAttackPokemonPtr` `0x801F5FD0`, `...SetDefensePokemonPtr` `0x801F5FBC`) |
| `fightFloorBiosGetFightSidePtr` | `0x801F61E0` | Per-side (player side / enemy side) state pointer |
| `fightFloorBiosGetAppointPokemonPtr` / `...Ptr` variants for `Item`/`Trainer`/`Waza`/`Tokusei`(ability)/`Side` | `0x801F6154` and neighbors | **"Appoint" = the currently-selected/pending choice** — `AppointWazaPtr`/`AppointWazaDataId` (`0x801F611C`/`0x801F603C`) is a strong candidate name for "the move the player just selected", `AppointPokemonPtr`/`...DataId` similarly for a selected party-switch target |
| `fightFloorBiosGetIrekaePokemonPtr` | `0x801F6170` | "Irekae" = swap/switch-in — the Pokémon being switched in, get+set pair exists (`...Set...` `0x801F5F94`) |
| `fightFloorBiosGetEscapePokemonPtr` | `0x801F618C` | Run/flee target |
| `fightFloorBiosGetKizetuPokemonPtr` | `0x801F5BEC` | "Kizetu" = faint/knockout — likely tracks the currently-fainted Pokémon during a KO sequence |
| `fightFloorBiosGetWazakoukaMsgId` / `...GetCriticalMsgId` / `...GetAttackMsgId` / `...GetAppointMsgId` | `0x801F6074`/`0x801F6090`/`0x801F60AC`/`0x801F60C8` | **Battle message IDs** — see §9 |
| `fightFloorGetFightOutPokemonPtrAry` | `0x801F23DC` | Array of pointers to the Pokémon currently "out" (active) on the field — this is the closest named candidate for **"active battler(s)"** as a small array rather than a single pointer (relevant for double battles) |
| `fightFloorGetValidFightOutPokemonCount` | `0x801F2C4C` | Count of currently-valid active battlers |
| `fightFloorGetGcHeroFightTrainerPtr` | `0x801F3070` | The player's own `FightTrainer` struct pointer, specifically |
| `fightFloorGetFightPokemonPtrToFightTrainerPtr` | `0x801F450C` | Pokémon pointer → owning trainer pointer (reverse lookup) |

**Why this matters more than any single address:** none of these are decompiled to C++ (no `.cpp` source exists for this subsystem in `xd-decomp` today, only symbol names+addresses), so **this is Confirmed-symbol-exists / Unknown-implementation-detail**, per the citation convention. But the naming is systematic enough (Get/Set pairs, consistent `fightFloorBios*` prefix, English glosses of the Japanese internal terms like "Irekae"/"Kizetu"/"Kaisuu"/"Tenkou" that also appear in `xd-decomp`'s other battle-adjacent symbols) that this reads as a real, disciplined internal Bios-style API layer, not incidental naming.

**Candidate for future PHASE_0_RESULTS.md integration — the strongest one in this document:** `fightFloorBiosGetFightFloorPtr` (`0x801F6274`) is a trivial (`0xC`-byte) function, meaning it almost certainly just returns a cached pointer from a static global rather than computing anything. **Setting an execution breakpoint on it (once `Z0` reliability is fixed — see the open methodology problem in `PHASE_0_RESULTS.md`) or, more promisingly given `Z0`'s current unreliability, finding what static global it reads from via disassembly of its 3 instructions, would give a root pointer for the entire live battle state tree** — turn count, active Pokémon, appointed move/target, message IDs, all reachable by chasing further Bios getters from that one root. This is a fundamentally different, more promising strategy than blind-scanning for individual fields one at a time (which is what Phase 0C's `gLastSelectedIndex` work had to resort to) — if the root pointer is found, every field in this table becomes reachable by offset instead of by further scanning.

---

## 5. Cross-referencing the Phase 0C `gLastSelectedIndex` lead against its symbol neighborhood — an important caveat

`PHASE_0_RESULTS.md` records `gLastSelectedIndex` (`.sdata:0x804E84CC`) as "the strongest lead" for the battle-menu selection index, with real live confirmation (write-on-Right-press, no-write-on-Down/Up, matching the offline save-state diff exactly). This document does not contradict that live evidence. However, static analysis of `gLastSelectedIndex`'s **immediate symbol neighborhood** (`xd-decomp/config/GXXE01/symbols.txt:17009-17020`) surfaces a pattern worth flagging before more time is invested in it:

```
pCamWork              = .sdata:0x804E84B0  // camera work pointer
gCurrentFOV           = .sdata:0x804E84C0  // camera field-of-view (float)
gLastMotionType       = .sdata:0x804E84C4  // "motion type" — animation/camera?
gLoopCameraWaitTime   = .sdata:0x804E84C8  // explicitly camera-named, float
gLastSelectedIndex    = .sdata:0x804E84CC  // <- the live-tested lead
old_pos_pattern$2118  = .sdata:0x804E84D0  // compiler-generated name, "old position pattern"
```

**Every other named symbol immediately adjacent to `gLastSelectedIndex` in linker layout order is camera-system-related** (`pCamWork`, `gCurrentFOV`, `gLastMotionType`, `gLoopCameraWaitTime`), and the symbol immediately after it (`old_pos_pattern$2118`) is also position/motion-flavored, not menu-flavored. This is **circumstantial, not conclusive** — linker-adjacency reflects compilation-unit/translation-order, not necessarily semantic relatedness, and a genuinely global "last selected index" utility (e.g., a general-purpose cursor-memory helper reused by *both* camera-target-selection UI and the battle move-selection UI) is a plausible explanation that would make both the camera-neighborhood pattern *and* the live battle-menu behavior true simultaneously. But it is also consistent with a less convenient explanation: that this address is actually a **camera-target or camera-shot-selection index** (e.g., "last selected camera angle/subject") that happens to also get written during the battle menu's Right-press because that press triggers a camera pan/refocus onto the newly-highlighted target Pokémon — i.e., the write could be a *side effect* of a camera-follow update triggered by the UI action, not the UI selection state itself.

**This does not overrule the live result recorded in `PHASE_0_RESULTS.md`** (per this task's instructions, that stays as the authoritative, not-yet-fully-verified "promising" status). It is flagged here as **new static context that should inform, not block, the next live step**: when the paused investigation resumes and gets to disassemble the writer instruction at `PC=0x800B35E4` (per `PHASE_0_RESULTS.md`'s own stated next step), specifically check whether that PC falls inside a function with a camera-related name/prefix in `symbols.txt`, versus a `menuFight*`-prefixed one. That single check would resolve this ambiguity cheaply, using data already planned to be collected anyway.

---

## 6. Move IDs, PP, and the `waza` ("technique"/move) data-definition subsystem

- **In-struct move storage** (per-Pokémon, live/mutable): `Pokemon::wazas[4]` at `+0x80` (§2 above), each a `PokemonWaza{u16 dataId; u8 pp; u8 ppCount;}` (`pokemon.hpp:75-79`). `dataId` is the move's ID into the static move-definition table (§below); `pp` and `ppCount` are two separate fields — `pp` reads as "current remaining PP", `ppCount` as "max PP for this move as learned" (a Pokémon can learn a move at a boosted max-PP via PP Ups, so this being per-instance rather than looked up fresh from the static table each time makes sense). Getter: `Pokemon::getPokemonWaza(u16 wazaNum)` (`pokemonStatusPokemon.cpp:264-270`).
- **`Pokemon-XD-Code` cross-reference:** `move1`/`move1PP`…`move4`/`move4PP` at offsets `128,130,132,134,136,138,140,142` (`XDPartyPokemon.swift:27-34`) — `128=0x80` matches `wazas[0]` exactly, and the 2-byte move-ID + 1-byte PP pattern repeating every 4 bytes matches `PokemonWaza`'s `{u16,u8,u8}` layout exactly (GoD Tool's `moveNPP` field corresponds to `wazas[n].pp`; it does not expose `ppCount` separately, suggesting either it wasn't needed for their editor use case or it's folded into a different offset not itemized here).
- **Static move-definition table (per-move constant data, not per-Pokémon)** — the `wazaDataBios*` accessor family (`xd-decomp/config/GXXE01/symbols.txt:5463-5539`, `.text:0x8013D03C`–`0x8013E018`), one Get/Set pair per field: `wazaDataBiosGetName`/`SetName`, `GetPp`/`SetPp` (**base max PP for the move, before any per-Pokémon PP Ups**), `GetIryoku` ("iryoku" = power), `GetAvg` ("avg" — likely accuracy, Japanese "meichuu" abbreviated, or possibly a mistranslation artifact; unconfirmed which), `GetRangeId` (**target range** — the move's intrinsic target type, e.g. single-target/all-foes/self, distinct from the *player's chosen* target discussed in §7), `GetPri` (priority), `GetZokuseiDataId` (elemental type), `GetFightAttackMsgId`/`GetFightAttackTunagiMsgId` (battle message IDs specific to this move, "Tunagi" = connecting/chain message, possibly the multi-part "It's super effective!" follow-up line), `GetSeqId` (animation sequence ID), plus move-flag getters for `Dageki`(contact), `Mamoru`(protectable), `Majikku`(magic-coat-able), `Yokodori`(snatchable), `Oumugaesi`(mirror-move-able), `Oujanosirusi`(mean-look/block-escape-like), `Monomane`(mimic-able), `Nekonote`(sound-based or similar), `Negoto`(usable while asleep, "sleep talk"-compatible), `Bouon`(sound-blockable), `Pressure`(affected by the Pressure ability), `HidenFlag`(HM flag), `RiskFlag`. This is a rich, fully-enumerated move-property table — **everything needed to narrate a move's name, power, type, PP, and target range exists as a named accessor**, even though none of it is decompiled to C++ source (symbol-only, Confirmed-exists / Unknown-body).
- **`wazaGetMaxPP`** (`.text:0x8013D1BC`, `symbols.txt:5466`) — separate top-level function (not under the `wazaDataBios*` prefix), likely the actual runtime "what's this move's max PP including boosts" query used by menus, as opposed to the raw base-PP-only Bios getter.
- **Move-selection menu functions** (`menuFight*`, all `.text`, symbol-only): `menuFightDrawWaza` (`0x8001C868`), `menuFightDrawPP` (`0x8001C530`), `menuFightDrawType` (`0x8001C758`), `menuFightWazaButton` (`0x8001CC90`, likely the input-handling function for the move-list submenu — a promising execution-breakpoint target once `Z0` reliability is fixed), `menuFightWazaCtrl` (`0x8001CEBC`), `menuFightOpenWaza`/`menuFightCloseWaza` (`0x8001E014`/`0x8001DF58`).

---

## 7. Target selection

- **Live selected-target enum**, from `Pokemon-XD-Code`'s battle-context breakpoint decoder (`Objects/processes/Dolphin/ColoXD/ColoXDBreakPoints.swift:474-511`, `BattleMoveSelectionContext`, register `r9` at the `onDidConfirmMoveSelection` breakpoint, `.text:0x802043d0`):
  ```swift
  enum Targets: Int {
    case none       = 0x0
    case topFoe     = 0x1
    case topAlly    = 0xC
    case bottomAlly = 0xD
    case bottomFoe  = 0x10
  }
  ```
  This is a **double-battle-shaped** enum (top/bottom rows per side) even though XD is primarily single-battles with occasional double battles (Miror B. fights, etc.) — worth remembering that single-battle target selection likely only ever produces `topFoe` in practice, with the others reachable only in double-battle-capable fights. This value is read from a **CPU register at a breakpoint**, not a persistent memory address — confirming `ACCESSIBILITY_HOOKS.md` Tier 2 §5's assessment that target selection is event-driven, not (yet) known to be pollable.
- **Static per-target-slot pointers** — three real `.sbss` globals found in `xd-decomp`'s symbol table that were not in `ACCESSIBILITY_HOOKS.md` or `PHASE_0_RESULTS.md`: `_target_fight_side_ptr` (`.sbss:0x804EA648`), `_target_fight_trainer_ptr` (`.sbss:0x804EA64C`), `_target_fight_pokemon_ptr` (`.sbss:0x804EA650`) — three consecutive 4-byte pointer slots (`symbols.txt:17287-17289`). Also `fight_target_data` (`.data:0x804139B8`, size `0xF0` — a real static array/struct, not a pointer) and `fight_target_data_number` (`.sdata:0x804E8588`, likely a count of entries in the former). And a rendering-side helper: `menuFightDrawTargetCursor` (`.text:0x80018588`), `menuFightCtrlTarget` (`.text:0x80018614`, only `0x4` bytes — suspiciously trivial, possibly a stub/thunk), `menuFightOpenTarget`/`menuFightCloseTarget` (`0x8001D9A8`/`0x8001D934`).

  **Candidate for future PHASE_0_RESULTS.md integration:** `_target_fight_pokemon_ptr` (`.sbss:0x804EA650`) is a directly promising live-test target for "which Pokémon is currently highlighted as the move's target" — it's a real static pointer (not stack-relative, not a register), sits right next to two other target-scoped pointers (side/trainer) suggesting a coherent "currently targeted X" trio, and if it does point at a live Pokémon struct, the offsets from §2 (hp `+0x4`, condition `+0x16`, etc.) would immediately apply. Should be tested with a `Z2` write watchpoint (the only proven-reliable mechanism per `PHASE_0_RESULTS.md`'s methodology finding) while moving the target cursor left/right during a double battle or the target-select substep of a normal battle.
- **`Pokemon-XD-Code`'s battle-context struct** (`XDBattlePokemon`, `Objects/data types/XDPartyPokemon.swift:121-182`) documents fields that only make sense for a Pokémon *currently in battle*, at fixed offsets from a `battleDataOffset` that in their tool comes from a breakpoint register, not a known static address: `currentType1`/`currentType2` (`+0x808`/`+0x80a`), `currentAbility` (`+0x80c`), and stat stages `attackModifer`…`evasionModifer` (`+0x7b0`…`+0x7b6`, one signed byte each, `XGStatStages` enum centered on `.neutral`). There's also `battleStateOffset = battleDataOffset + 1608` (`+0x648`), an offset that's referenced but not decoded into named fields in the excerpt found — worth deeper investigation if the live investigation ever gets a pointer into this struct family (e.g., via `_target_fight_pokemon_ptr` above, or via the `fightFloorBiosGetAttackPokemonPtr`/`GetDefensePokemonPtr` family in §4). **This is the concrete shape of the "active battler" structure the task asked about** — a battle-only superset of the party `Pokemon` struct, reached via a pointer field rather than being the party struct itself (note `XDBattlePokemon.init` reads a pointer stored at `battleDataOffset+0x0` to find the underlying party data, meaning the battle-context struct and the party struct are two separate allocations linked by a pointer, not one merged struct).

---

## 8. Shadow-Pokémon status

- `Pokemon::darkPokemonDataID` at `+0xba` (§2), getter `getDarkPokemonDataId()` (`pokemonStatusPokemon.cpp:30-32`), and `isDarkPokemon()`/`getDarkPokemon()` (declared `pokemon.hpp:229,233`, not in the decompiled excerpt available). **"Dark Pokémon" is this codebase's internal name for "Shadow Pokémon"** — confirmed by `Hero::setMeetDarkPokemonCount(u8 shadowPokemonCount)` (`heroMemberFunctions.cpp:343-345`) using both names for the same parameter in the same function, and by `Pokemon-XD-Code` naming the equivalent field `shadowID` (offset `186`/`0xba`, matching exactly).
- `DarkPokemon` is a **separate class/struct** (`darkPokemon.hpp`, included by `pokemon.hpp:5`, not read in full for this audit — flagged as a good next static-analysis target if shadow-Pokémon-specific state like Heart Gauge/purification progress is needed later) reached via `Pokemon::getDarkPokemon()`. `heroMemberFunctions.cpp:247-250` shows it being fetched and having `setPlace()` called on it during `Hero::setPokemon`, confirming it's a real, actively-used side-structure, not vestigial.
- `Pokemon-XD-Code`'s breakpoint set (§ list in the file read for this audit) includes three shadow-specific live hooks with real `.text` addresses in `XDBreakPoints.swift:99-113`: `onShadowPokemonEncountered` (`0x802263cc`, `0x802263dc`, `0x802263e4` — three addresses for one event, likely three different encounter code paths), `onShadowPokemonFled` (`0x80209a58`), `onShadowPokemonDidEnterReverseMode` (`0x802269a4` — "reverse mode" is the enraged/hyper-mode shadow state). `onDidPurification` also exists (`0x8023370c`). These are register-read breakpoints (event-driven), not static addresses, consistent with the rest of the battle-event system.
- **Not found in this pass:** a persistent "Heart Gauge" (purification-progress meter) memory address or offset. `XGStatusEffects.swift` (§9) and `XDPartyPokemon`'s field list do not include one. This would need its own targeted search — flagged as a gap, not resolved here.

---

## 9. Battle-message IDs and status-effect name table

- **`xd-decomp` message-ID accessors** (all symbol-only, `.text`): `getLogMsgBattle` (`0x800A4428`, local/static-linkage — takes an `ITEMUSE2POKEMON_LOG` struct and a `Pokemon*`, suggesting battle log lines are template-composed from an item-use/battle-event log record plus the acting Pokémon, not looked up as flat strings), `fightFloorBiosSetWazakoukaMsgId`/`GetWazakoukaMsgId` (`0x801F5EE0`/`0x801F6074`, "kouka" = effect — the "It's super effective!"-class message), `fightFloorBiosGetCriticalMsgId` (`0x801F6090`), `fightFloorBiosGetAttackMsgId` (`0x801F60AC`), `fightFloorBiosGetAppointMsgId` (`0x801F60C8`), `wazaDataBiosGetFightAttackMsgId`/`GetFightAttackTunagiMsgId` (§6, per-move message IDs), `fightMsgctrlSetValue` (`0x802370EC`, likely the low-level "insert this numeric value into the message template" function — battle messages commonly need to interpolate damage numbers, Pokémon names, etc. into a template string).
- **Status-effect name/ID table**, from `Pokemon-XD-Code` (`enums/XGStatusEffects.swift:11-30`): a **disc-file offset** (not a RAM address — explicitly commented `// in Start.dol` in the source, `kFirstStatusEffectOffset = 0x3f93e0` for XD US), `kSizeOfStatusEffect = 0x14` (20 bytes per entry), `kNumberOfStatusEffects = 87`, with per-entry `kStatusEffectDurationOffset = 0x4` and `kStatusEffectNameIDOffset = 0x10`. This is a **static per-status-ID metadata table** covering the full 87-entry status space (non-volatile conditions 0-8, volatile statuses like confusion/attract/flinch, field effects like reflect/spikes, weather, and move-outcome flags like "super effective"/"missed"/"OHKO" — all sharing one ID space per this enum). **`XGNonVolatileStatusEffects`** (`XGStatusEffects.swift:35-56`) is the narrower subset that maps directly onto `Pokemon.condition`/`+0x16`: `none=0, poison=3, badPoison=4, paralysis=5, burn=6, freeze=7, sleep=8` (note: values 1-2 are skipped in the non-volatile-only enum — `XGStatusEffects.no_status=1` and `.brn_psn_or_par=2` in the full enum are likely aggregate/query values, not condition states a Pokémon actually holds).
  - **Caveat:** this table's offset (`0x3f93e0`) is a **disc/DOL file offset**, per the source comment — turning it into a live RAM address requires knowing how `main.dol` gets mapped into the `0x80000000`+ address space at load (typically a fixed offset added to the file offset for a given segment, but this needs confirming against `xd-decomp`'s own linker map/`.map` output rather than assumed). Not resolved in this pass — flagged as a concrete next step if narrating status-effect *names* (not just raw condition IDs) becomes a priority.

---

## 10. Controller/input functions

- **`PADRead`** (`.text:0x800BB348`, size `0x300`) — real decompiled SDK source exists: `xd-decomp/src/dolphin/pad/Pad.c`. This is the same function `PHASE_0_RESULTS.md`'s "Execution breakpoints are unreliable" sanity check used (confirmed must-execute-every-frame, and confirmed `Z0` still didn't fire on it — the strongest evidence in that document that `Z0` is broken in this Dolphin/GDBStub configuration, not that `PADRead` itself is unreachable).
- **`GSinput*` family** (`.text:0x80103F70`–`0x8010475C`, `symbols.txt:4405-4426`) — a higher-level input wrapper over raw `PADRead`, symbol-only (no decompiled source located in this pass): `GSinputRead`/`GSinputReadStart`/`GSinputReadEnd` (the actual per-frame read cycle), `GSinputButtonsPressed`/`GSinputButtonsChanged`/`GSinputButtonsRepeat` (three different edge-detection semantics — "repeat" suggests menu cursor auto-repeat-on-hold is handled at this layer, relevant if a future accessibility hook wants to distinguish a deliberate press from an auto-repeat tick), `GSinputGetLeftStickXData`/`...YData`/`GetRightStickXData`/`...YData`, `GSinputIsConnected`, `GSinputGetSubType` (controller type detection — GameCube controller vs. other peripherals), `GSinputMotorStart` (rumble). This is almost certainly the layer `menuFightWazaButton`/`menuFightMainCtrl` and other `menuFight*` input-handling functions call into, though that call relationship wasn't traced (no decompiled source for the `menuFight*` functions exists in `xd-decomp` today — symbol-only, per §11 below).

---

## 11. What's still symbol-only (no decompiled C++ body) — explicit gap list

Per this project's citation discipline, everything below is **Confirmed** to exist (real symbol, real address, in the retail binary) but **Unknown** in implementation detail (no source body in `xd-decomp` as of this audit):

- The entire `menuFight*` menu-controller family (`menuFightMainCtrl`, `menuFightOpenTop`, `menuFightWazaButton`, `menuFightOpenTarget`, `menuFightOpenPokemon`, and ~60 more under this prefix, `symbols.txt` lines 367-448) — this is the actual UI/input-handling code for the battle menu, and it is entirely un-decompiled. This is *the* highest-value decompilation target if this project ever moves from "find addresses by scanning" to "understand the code that writes them" for the battle menu specifically, matching the "Needs decompilation" framing `ACCESSIBILITY_HOOKS.md` already uses for other subsystems.
- The entire `fightFloor*`/`fightSide*`/`fightTrainer*`/`fightType*` battle-engine namespace (§4) — likely several thousand lines of real battle logic (turn order, damage calculation, AI), all symbol-only.
- The entire `wazaDataBios*` move-property table backend (§6) and the `wazaCheckDarkWaza`/`wazaGetWazaTypeIdName`/`wazaIsWazaTypeId`/`wazaGetMaxPP` helpers around it.
- `DarkPokemon` class internals (§8) beyond the two call-sites observed in `heroMemberFunctions.cpp`.
- `savedataGetStatus` (§3) itself — its `(0, 2)` argument pair is unexplained; `savedata.hpp` exists but wasn't read in full for this pass (flagged, not resolved).

---

## 12. Summary: single most promising new static lead for the live selection field

Two candidates emerged, at different levels of the stack:

1. **Low-level, incremental:** `_target_fight_pokemon_ptr` (`.sbss:0x804EA650`, §7) — a real static pointer slot, directly testable with the same `Z2`-watchpoint methodology already proven reliable in `PHASE_0_RESULTS.md`, that could confirm or refute whether target-selection has a persistent-memory representation at all (the open question `ACCESSIBILITY_HOOKS.md` Tier 2 §5 flags as blocking pollable target-selection support).
2. **High-level, structural:** `fightFloorBiosGetFightFloorPtr` (`.text:0x801F6274`, §4) — disassembling this trivial 3-instruction function would very likely yield a single root static pointer for the *entire* live battle-state tree (turn count, active Pokémon, appointed move, message IDs), which would let every other value in this document be found by fixed offset from one confirmed root, instead of one more blind scan per field.

Neither was live-tested in this pass, per the read-only/static-only scope of this task.
