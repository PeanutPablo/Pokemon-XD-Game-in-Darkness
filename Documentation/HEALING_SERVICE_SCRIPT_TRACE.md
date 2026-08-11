# HEALING_SERVICE_SCRIPT_TRACE.md

Engine- and script-side trace of the Pokémon Center healing service, and the
tooling inventory for the offline pipeline that will turn it into a
generated `Interactables`-tab entry ("Pokémon healing service").

**Status: investigation complete, pipeline NOT started.** No production
accessibility code was changed by this document's session. Everything below
is either confirmed from the decompilation / installed third-party tooling,
or explicitly marked as untested.

Date: 2026-08-04.
Target: vanilla US Pokémon XD, `GXXE01` revision 0. XG deltas UNVERIFIED —
see "XD / XG boundary".

---

## 1. THE METHOD NUMBER CORRECTION (read this first)

An earlier conclusion in this project's session history stated that the
healing method was **"People method 85"**. **That was wrong** and must not
be repeated.

| Fact | Value |
|---|---|
| Script class | **35** (`Character`) |
| **Actual script method** | **101** (`0x65`) |
| GoD Tool method name | **`Character.useHealingMachine`** |
| Internal `cmpPeople` jump-table index | **85** |
| Reason for the difference | the dispatch subtracts `0x10` before indexing |

The dispatch in `objPeople.s` is:

```
801C3F44   subi    r0, r27, 0x10      # r27 = incoming method id
801C3F48   cmplwi  r0, 0x62           # 99 entries (0..0x62)
801C3F4C   bgt     .L_801C5A0C        # out of range -> reject
801C3F54   slwi    r0, r0, 2
801C3F5C   lwzx    r0, r3, r0         # table "@2522"
801C3F64   bctr
```

So `table_index = method - 16`, and therefore:

```
method 101  -  16  =  table index 85
```

**"85" is ONLY ever the internal jump-table index.** It is not a script
method number, it must never appear in generated data as the method id, and
it must not be searched for in bytecode. Anywhere outside this section, the
healing method is **class 35, method 101 (`0x65`),
`Character.useHealingMachine`**.

### Independent corroboration

Two unrelated sources agree, which is why the corrected number is trusted:

1. **The decompilation.** `objPeople.s` dispatch index 85 (= method 101)
   contains `bl recoveryEventPC`.
2. **GoD Tool's own name table.** `XGScriptClassFunctionsData.swift`
   independently names class 35 method 101 `useHealingMachine`. It also
   names method 85 `getYRotationDegrees` — a rotation getter with no
   relationship to healing, which is exactly the false result the
   uncorrected number would have produced.

The class number is likewise confirmed from the binary rather than assumed:
`cmpPeople` checks the script variant's type with `cmpwi r0, 0x23` (35)
before dispatching, and GoD Tool names class 35 `Character`.

---

## 2. CONFIRMED CHAIN

```
live People actor
  → talk script ID                      (e.g. Agate nurse: 0x01000008)
  → room .fsys script resource          [NOT YET EXTRACTED]
  → Character class 35, method 101 `useHealingMachine`
  → cmpPeople dispatch index 85         (101 - 0x10)
  → recoveryEventPC   @ 0x801CF474
  → party healing
```

### Confirmed links

| Link | Evidence | Confidence |
|---|---|---|
| `recoveryEventPC` is the Pokémon Center healing event | `app/recovery/recoveryEvent.s`, sits with `recoveryEventCommon` / `recoveryPokemon` | High |
| It has exactly two callers | `objHero.s:962`, `objPeople.s:839` — both in the script-object layer | High |
| The People/Character caller is dispatch index 85 | jump table `@2522` resolved; nearest preceding case label `0x801C4A00`, call at `0x801C4A94` | High |
| Dispatch index 85 = script method 101 | `subi r0, r27, 0x10` | High |
| Class 35 = `Character` = `objPeople` | `cmpwi r0, 0x23` in `cmpPeople`; GoD Tool class-name table | High |
| Method 101 is named `useHealingMachine` | GoD Tool `XGScriptClassFunctionsData.swift` | High |

### NOT yet confirmed

- **Which talk script contains the call.** The Agate nurse's talk script ID
  is `0x01000008`, but its bytecode has not been read.
- **That the nurse's script actually calls method 101.** The semantic chain
  is proven to exist in the engine; it has *not* been proven that this
  specific actor's script reaches it.
- **Whether every Pokémon Center shares one implementation.**
- **Whether healing is conditional** (story flags, party state, refusal
  branches) — see "Availability semantics".
- **Any XG delta.**

---

## 3. TOOLING INVENTORY (Phase 1 — complete)

Everything needed already exists locally. **Adapt; do not rewrite.**

### 3.1 GoD Tool / `Pokemon-XD-Code` (Swift) — authoritative

Path: `PokemonXGAccessibility/Pokemon-XD-Code/Objects/scripts/XD/`

| File | Lines | Role |
|---|---|---|
| `XGScript.swift` | 2490 | script container / resource parsing |
| `XGScriptInstruction.swift` | 315 | instruction decode |
| `XGScriptOps.swift` | 91 | opcode table |
| `XGScriptClass.swift` | 380 | class + method dispatch model |
| `XGScriptClassFunctionsData.swift` | 841 | **class and method NAME tables** |
| `XDSScriptCompiler.swift` | 1063 | XDS compile / decompile |

`XGScriptClassFunctionsData.swift` holds `ScriptClassNames` and
`ScriptClassFunctions`. Entries are **positional tuples**, not labelled:

```swift
("useHealingMachine", 101, 0, nil, .null, "")
//  name              idx  paramCount  paramTypes  returnType  hint
```

A regex expecting `(name: "...", index: ...)` silently matches nothing —
this cost one wrong result during investigation. Parse positionally.

This table names **97** methods for class 35.

### 3.2 XDscriptTools (Python) — best decode adaptation target

Path: `PokemonXGAccessibility/Research/ThirdParty/XDscriptTools/`

```
XDscriptDisassembler.py
XDscriptLib/FunctionInfo.py     class/method metadata
XDscriptLib/_Instruction.py     instruction decoding
XDscriptLib/_ScriptCtx.py       script context / container
XDscriptLib/_ScriptVar.py       variant/value types
common_script.scd               sample .scd script resource
```

Python and already importable, so it avoids a Swift toolchain entirely.

**Caveat, measured:** its `FunctionInfo.py` names only **5** methods for
class 35 — it does *not* know `useHealingMachine`. Use XDscriptTools for
**instruction decoding** and GoD Tool's Swift table as the **name source**.
Do not rely on XDscriptTools alone to identify the method.

### 3.3 This project's own extraction

Path: `PokemonXGAccessibility/Companion/_dialogue_extraction_tool.py`

Already used in production by `authoritative_warps.py`, `messages.py`,
`shop_messages.py`, `entity_names.py`:

- `parse_fsys(bytes)` — FSYS archive entries (`{name, type, data}`)
- `RelFile(data)` / `.get_pointer(n)` — REL section pointers
- `decode_string_table(data)` — message tables

Extracted game data lives under the gitignored
`Companion/_dialogue_extraction/`. Currently only **five** archives are
extracted (`common`, `fight_common`, `pocket_menu`, `battle_disk`, plus the
full `collision/` `.ccd` set). **Room `.fsys` archives are NOT extracted** —
this is the immediate blocker.

### 3.4 Other local third-party

Path: `PokemonXGAccessibility/Research/ThirdParty/`

| Tool | Relevance |
|---|---|
| `pokemon_fsys_tool` (C++) | FSYS extraction; alternative to the Python tool |
| `PkmGCTools` / `LibPkmGC` | save/party structures; not needed here |
| `pokemon-ngc-rando` | randomiser; may contain room/script indices |
| `XDscriptTools` | see 3.2 |

`Research/disc_extract/` is currently **empty**.

Related existing docs: `XD_SCRIPTING_CODEMAP.md`,
`COMMUNITY_TOOLING_AUDIT.md`, `TEXT_AND_DIALOGUE_PIPELINE.md`,
`PC_AND_PURIFY_CHAMBER_RESEARCH.md`.

---

## 4. WHY A RAW BYTE SEARCH FOR `0x65` IS INVALID

Scanning script bytecode for the byte `0x65` (101) — or `0x55` (85) — would
produce false positives that cannot be distinguished from real call sites:

- **Operands.** Immediates, message IDs, flag numbers, actor indices and
  coordinates can all be 101.
- **Branch offsets.** Jump targets are ordinary integers.
- **String/text table data** interleaved in the same resource.
- **Other classes' method IDs.** Method 101 on `Camera`, `Menu`, `Pokemon`
  etc. is a completely different function; the class is what disambiguates.
- **Multi-byte encodings.** 101 may appear as a fragment of a larger
  operand, or be pushed as a value rather than used as a method id.

A call must be identified **structurally** — decode the instruction stream,
find the call opcode, and read its class **and** method operands together.
That is Phase 3 below, and it is why the decoder is adapted rather than
replaced with a scan.

---

## 5. WHY WIDENED TALK DISTANCE IS NOT A CLASSIFIER

During investigation it was observed live that the Agate nurse's runtime
talk distance is **6.00** while the static default is **3.00**:

- static default: `people_info + 0x24`
- **live per-actor value: `people_work + 0x178`**
  (`peopleGetTalkDistance` @ `0x802A2E90` reads `0x178(r3)`;
  `peopleSetTalkDistance` @ `0x802A2E58` writes it)

This is genuinely useful for **interaction geometry** — it explains talking
across a desk, and the companion currently reads the wrong (static) field.
But it is **not** a semantic signal:

- Mart clerks and Mt. Battle receptionists sit behind desks too and will
  very likely also have widened distance, while providing no healing.
- It is a *distance*, set for staging reasons, with no relationship to what
  the interaction does.
- Classifying on it would mislabel every desk NPC in the game as a healing
  service.

**Classification must come from what the script does** — a call to
`Character.useHealingMachine`. Widened distance is used only for
range/approach reporting.

---

## 6. AVAILABILITY SEMANTICS (to be determined)

A script *containing* method 101 proves the actor can heal somewhere in its
flow; it does not prove healing is available right now. Phase 7 must
classify each generated entry as one of:

- **Healing service actor** — method 101 reachable through normal
  interaction.
- **Conditional healing service** — reachable only past a script condition.
- **Shared or ambiguous script** — needs runtime evaluation.

Conditions to investigate: story flags, actor enabled/loaded state, room
state, dialogue branch selection, refusal branches, party state.

For the first implementation it is acceptable to label a conditional actor
as a healing service, **provided the menu does not claim healing is
guaranteed immediately**.

---

## 6a. VERTICAL SLICE — PROVEN END TO END (2026-08-04)

The single-room slice specified by the project owner is **complete and
verified against real game data**. Phases 2 and 3 are demonstrated for one
room; only batch scale-up and the later phases remain.

### Confirmed result

Disassembly of the real Agate Village Pokémon Center room script, line 368:

```
callstd       Character::101
```

A structural decode — the `callstd` opcode with class `Character` and method
`101` as decoded operands. **Not** a byte scan (see §4).

```
live People actor
  → talk script ID 0x01000008
  → M3_pc_1F.fsys                (718144 bytes, extracted from disc)
  → type-7 entry, magic "TCOD"   (the .scd script, 2240 bytes)
  → callstd Character::101       (line 368 of the disassembly)
  → cmpPeople dispatch index 85  (101 - 0x10)
  → recoveryEventPC @ 0x801CF474
  → party healing
```

### How to reproduce (four findings that were NOT obvious)

1. **The extractor already exists: `DolphinTool.exe`,** shipped with Dolphin
   at `OneDrive/Desktop/apps/Dolphin-x64/DolphinTool.exe`. It reads the
   **RVZ directly** — no ISO conversion, no new tooling, no `wit`/`nod`.
   ```
   DolphinTool.exe extract -i <rvz> -l                    # list disc files
   DolphinTool.exe extract -i <rvz> -s M3_pc_1F.fsys -o <dir>
   ```
   Both `M3_pc_1F.fsys` and `M6_pc_1F.fsys` are confirmed present on disc.
   Source RVZ: `xd-decomp/orig/GXXE01/Pokemon XD - Gale of Darkness (USA).rvz`.
   Output lands under `<dir>/files/`.

2. **The script resource is the type-7 entry, not type 14.** Room archive
   entry types for `M3_pc_1F`:
   | type | size | content |
   |---|---|---|
   | 14 | 1176 | not the script |
   | **7** | **2240** | **script, magic `54434f44` = `"TCOD"`** |
   | 5 | 3280 | string/message table |
   | 6 | 640 | — |
   | 1 | 903015 | models |
   | 2 | ×3 | models (`ojo_0000`, `ojisan2_0000`, `pc_f_0000`) |
   | 3 | 13320 | CCD (what `extract_warp_collision_data.py` already takes) |

   Identify the script by **magic `TCOD`**, matching
   `Research/ThirdParty/XDscriptTools/common_script.scd`. Do not identify it
   by entry size or index.

3. **`XDscriptDisassembler.py` writes a `.txt` beside its input** and prints
   nothing to stdout. Three invocations appeared to silently fail before
   this was noticed.
   ```
   python XDscriptDisassembler.py path/to/M3_pc_1F.scd   # -> M3_pc_1F.txt
   ```

4. **XDscriptTools decodes the call correctly as-is**, and prints
   `Character::101` *unnamed* — its `FunctionInfo.py` lacks the name, exactly
   as §3.2 predicted. This **confirms** the intended architecture: use
   XDscriptTools for decoding, GoD Tool's `XGScriptClassFunctionsData.swift`
   for naming.

### Artifacts produced (gitignored, user-owned game data)

```
Companion/_dialogue_extraction/rooms/files/M3_pc_1F.fsys
Companion/_dialogue_extraction/rooms/M3_pc_1F.scd
Companion/_dialogue_extraction/rooms/M3_pc_1F.txt
```

### Not yet done for this room

- The call site has **not** been attributed to a specific actor. `M3_pc_1F`
  has three actors (indices 0/1/2); which one's talk script reaches line 368
  is Phase 5.
- Reachability is unanalysed — direct vs conditional is Phase 4/7.

### The false-positive control is now an OFFLINE test

Because classification is script-based, the Poké Mart clerk and Mt. Battle
receptionist controls **no longer require the player to stand anywhere**.
Extract those rooms' `.fsys` the same way and assert their scripts contain
**no** `callstd Character::101`. Do this early — it is cheap and it is the
main guard against the mistake §5 warns about.

---

## 6b. PHASES 2, 3 AND 6 — DONE (2026-08-04)

The one-room slice is now a reproducible pipeline, and **the
false-positive control passes**.

Tool: `Companion/_healing_service_scan.py`. Per room it extracts
`<room>.fsys` from the RVZ with `DolphinTool`, takes the type-7 entry whose
magic is `TCOD`, disassembles it with XDscriptTools, and searches the
**decoded instruction stream** for a call whose class and method operands
are `Character` and `101` together. No byte scanning anywhere (§4).

### Validation-set result

| Room | Result | Evidence |
|---|---|---|
| `M3_pc_1F` Agate Village Centre | **HEALING** | line 368, `callstd Character::101` |
| `D2_pc_1F` Mt. Battle Centre | **HEALING** | line 1358, `callstd Character::101` |
| `M6_pc_1F` Gateon Port Centre | **HEALING** | line 175, `callstd Character::101` |
| `M1_shop_1F` Poké Mart | no healing call | **CONTROL — passed** |
| `S1_shop_1F` Outskirt Stand shop | no healing call | **CONTROL — passed** |

`M3_pc_1F` reproduces the hand-derived line 368 from §6a exactly, so the
generalised pipeline agrees with the manual result it replaces.

`D2_pc_1F` is the room the project owner healed in live on 2026-08-04
(narrated correctly end to end — greeting, the Yes/No at `menu_id=53`, and
the confirmation).

### Method naming now resolves

The scan reads GoD Tool's `XGScriptClassFunctionsData.swift` for names,
keyed on **class 35's own block** (`35 : [ ... ]`) — the class number being
confirmed from the binary's `cmpwi r0, 0x23`, not from a text search for
the word "Character", which also appears in every entry's parameter list. A
first attempt at scoping it that way silently returned another table's names
(`getvx`, `zerofloat`) — the same shape of error §3.1 warns about.

It reads **97** names for the class and reproduces all three of this
document's stated values: `101 → useHealingMachine`, `98 →
setTalkingDistance`, and `85 → getYRotationDegrees` — the last being exactly
the wrong answer the uncorrected method number would have selected.

Note also that the class-35 block begins at method **16**, which is the same
`0x10` the dispatch subtracts.

### §5 confirmed empirically

`setTalkingDistance` (method 98) is called by **every room scanned,
including both negative controls**. Widened talk distance is staging, set by
whichever script wants an actor reachable across a counter, with no relation
to what the interaction does. Classifying on it would have flagged both
Poké Marts as healing services.

### The finding that changes Phase 5's priority

`D2_pc_1F` is a single room containing **both** the healing nurse and the
Mt. Battle knockout-challenge receptionist — the project owner talked to
both, eleven seconds apart, in the live 2026-08-04 session
(`CHOICE MENU menu_id=174 ids=(31045, 31046, 31047)` for the receptionist,
then the healing dialogue). Its script is correspondingly large: 16944
bytes, 141 calls, 41 distinct methods, against 1392 bytes and 5 calls for
Gateon Port's.

So **room-level classification is not sufficient** and never will be. A room
answers "is there a healing service in here", which is genuinely useful for
a room-level announcement, but binding the service to the right *person*
requires per-actor attribution. Phase 5 is therefore a prerequisite for the
Interactables entry, not a later refinement — one room's `HEALING` verdict
would otherwise label the receptionist a nurse.

## 6c. FULL-GAME SWEEP (2026-08-04)

Ran across every room code in `assets/room_ids.json`: 276 attempted, 197
with a script and no healing call, 62 with no `TCOD` script entry at all, 2
not on the disc (`peopleViewer01`, `pokemon_menu` — catalogue entries that
are not rooms).

**15 rooms contain a `callstd Character::101`:**

| Room | Floor ID | Player-facing name |
|---|---|---|
| `M1_pc_1F` | 0x65, 0xB5 | Phenac City Pokémon Center |
| `M3_pc_1F` | 0x85 | Agate Village Pokémon Center |
| `M6_pc_1F` | 0x9A | Gateon Port Pokémon Center |
| `D2_pc_1F` | 0x15 | Mt. Battle Pokémon Center |
| `M5_labo_1F` | 0x8C | Pokémon HQ Lab, 1st floor |
| `M2_enter_1F` | 0x71 | Pyrite Town entrance |
| `M2_building_3F` | 0x6E | Pyrite Town building, 3rd floor |
| `S2_building_1F_2` | 0xA5 | ONBS, 1st floor |
| `D1_labo_1F` | 0x7 | Cipher Lab, 1st floor |
| `D1_labo_B1` | 0x8 | Cipher Lab, basement |
| `D5_factory_2F` | 0x41 | Shadow Pokémon Lab, 2nd floor |
| `D4_dome_4` | 0x33 | Realgam Tower dome |
| `D6_dome_1F` | 0x49 | Citadark Isle dome, 1st floor |
| `D6_fort_1F` | 0x4C | Citadark Isle fortress, 1st floor |
| `D6_fort_2F_2` | 0x4E | Citadark Isle fortress, 2nd floor |

All four Pokémon Centers are present and no other `_pc_` room is (upper
floors and basements correctly do not carry the call). The remaining eleven
are consistent with XD's habit of placing healing machines inside dungeons
and story locations, but **none of them has been verified in play** — they
are exactly the kind of claim this project does not ship on static evidence
alone.

### What this list is, and what it is NOT

It is: "this room's script contains a call to `useHealingMachine`
somewhere."

It is **not** a list of places the player can heal right now. Still
outstanding, and all of it matters before any of this reaches the player:

- **Phase 4 (reachability).** A call may sit behind a story condition, in a
  branch that is never taken, or in dead code. Nothing here distinguishes
  those from an unconditional service.
- **Phase 5 (per-actor attribution).** Unstarted, and now known to be a
  prerequisite rather than a refinement — see §6b.
- **Phase 7 (availability semantics).** A dungeon healing machine is very
  likely gated on story progress; several of the eleven are in locations
  reached once, late.
- **Indirect reach.** The scan finds direct `callstd` sites only. Whether
  method 101 can be reached through a computed dispatch or a shared
  subroutine is explicitly unresolved (Phase 3's remaining half), so this
  list is a lower bound, not a complete one.

## 6d. PHASE 5 — ATTRIBUTION, AND A CORRECTION TO PHASE 9 (2026-08-04)

Each healing call was attributed to the **FTBL function** containing it and
to the **receiver operand** the call is made on. FTBL names are the
developer's own, shipped in the game data.

Only FTBL entries count as function boundaries — `loc_NN:` labels are branch
targets *inside* a function. Gateon's call sits under `loc_61:`, a jump
target within `talk_124_pc_f`, so treating every label as a function
attributes the call to a branch instead of the actor's talk handler.

The receiver is the load instruction immediately before `callstd`, since
arguments are pushed first and the receiver last.

### Healing comes in TWO mechanisms, not one

| Room | Function | Receiver |
|---|---|---|
| `M1_pc_1F` Phenac | `talk_121_pc_f` | `$stack[1]` |
| `M3_pc_1F` Agate | `talk_124_pc_f` | `$stack[1]` |
| `M6_pc_1F` Gateon | `talk_124_pc_f` | `$stack[1]` |
| `D2_pc_1F` Mt. Battle | `talk_104_pc_f` | `$stack[1]` |
| `D4_dome_4` Realgam dome | `talk_105_pc_f` | `$stack[1]` |
| `D1_labo_1F` Cipher Lab | `tako_machine` | `$characters[0]` |
| `D1_labo_B1` Cipher Lab B1 | `tako_machine` | `$characters[0]` |
| `D6_dome_1F` Citadark dome | `tako_machine` | `$characters[0]` |
| `D6_fort_1F` Citadark fort | `tako_machine` | `$characters[0]` |
| `D6_fort_2F_2` Citadark fort 2F | `tako_machine` | `$characters[0]` |
| `M5_labo_1F` HQ Lab | `tako_machine` | `$characters[0]` |
| `D5_factory_2F` Shadow Lab | `recovery_d5_factory_2f` | `$characters[0]` |
| `M2_enter_1F` Pyrite entrance | `recovery_m2_enter_1f` | `$characters[0]` |
| `M2_building_3F` Pyrite | `recover` | `$characters[0]` |
| `S2_building_1F_2` ONBS | `recovery_s2_building_1f_2` | `$characters[0]` |

**The split is exact, with no exceptions, and two independent signals agree
on it:** every `talk_*_pc_f` site takes `$stack[1]`, every machine-style
site takes `$characters[0]`. Function naming and receiver form were derived
separately, so their agreement is evidence the categories are real rather
than an artifact of either rule.

- **Nurse (5 rooms).** A person, model `pc_f`, spoken to. The receiver is
  whichever actor was passed into the talk handler, so attribution runs
  through the actor's talk script ID, not through a literal index.
- **Healing machine (10 rooms).** Modelled as a room character but operated
  directly — `tako_machine` shows a message box, asks
  `Dialogs::displayYesNoQuestion`, and heals on yes. The receiver is the
  literal `$characters[0]`.

### This corrects Phase 9

Phase 9 as written says the Interactables entry should "point at the same
**live** People actor". That holds for the five nurse rooms and **not** for
the other ten, which are machines. Two thirds of the game's healing points
are not people at all.

Practically this is good news: `$characters[0]` is an explicit
room-relative character index, which is *easier* to bind than the nurse
case, and it is the same identity `npc_beacons.py` already resolves
(`floor_character` record index against the live people-work actor's
`+0x18`). But it means the player-facing category cannot be "nurse", and a
beacon/announcement that says "talk to" would be wrong in ten of fifteen
places.

### Still unresolved — do not build on these

- **The number in `talk_<N>_pc_f` is not identified.** It varies by room
  (104, 105, 121, 124, 124) so it is *not* a global model ID, which was the
  first hypothesis and is now dead. It is plausibly a room-relative
  character or people ID; that has not been verified against live memory.
- ~~**Whether the script's `$characters[]` array is ordered identically to
  `floor_character`**~~ — **RESOLVED, and the answer is NO.** See §6e.
- **Reachability and gating (Phases 4 and 7) remain untouched.** The
  machines sit in dungeons reached once and late; several are very likely
  story-gated.
- **§9's live sample assumed the widened-talk-distance actor in
  `M3_pc_1F` (people_info type 123) was the nurse.** The script names that
  room's non-nurse handler `talk_123_ojisan2` — an older *male* model — so
  either the number is not a people_info type or that identification was
  wrong. Recorded as a discrepancy to resolve live, not silently corrected
  in either direction.

## 6e. `$characters[]` IS NOT THE LIVE ACTOR INDEX (2026-08-04)

The naive binding — script `$characters[N]` = live room actor index `N` —
is **wrong**, and it was disproved without needing a new live session, by
checking the script against live data §9 had already recorded.

### The disproof

`M3_pc_1F`'s `preprocess` opens with:

```
	ldimm         int, =6
	ldvar         $characters[6]
	callstd       Character::98        ; setTalkingDistance
```

So the script widens exactly one actor's talk distance to **6**, and it does
it to `$characters[6]`.

§9's live sample of that same room recorded exactly one actor with a widened
distance: **index 2**, at `6.00` against a static default of `3.00`.

One widened value in the script, one widened value live, and they agree on
the number but not the index. Therefore `$characters[6]` is live actor
index 2, and the arrays are offset — not identical.

### The model this supports

`$characters[]` appears to have a reserved low range, with room-local actors
starting at 4:

- Across all 146 scripts that use the array, the lowest index is **0** in
  132 rooms, and real actor references then resume at **3 or 4** — a
  consistent *gap*, not a continuous range. The commonest shape is literally
  `[0, 4, 5, 6, …]`.
- `M3_pc_1F` has 3 live actors and the script uses exactly `[4]`, `[5]`,
  `[6]` — three references, contiguous, with `[6]` confirmed above as live
  index 2. That is `live = N − 4` for all three.
- This is consistent with the global-character slots already documented
  elsewhere in this project: `floorCharacterBiosFindByResID` branches to
  `_globalCharacter` when `groupID == 0`, and barrier-log #9 records
  `identity_a == 0` as the game's own sentinel for special/global
  partner-follower slots.

So: **`$characters[N≥4]` → room-local actor `N−4`; `$characters[0..3]` →
global slots, not room placements.** One confirmed data point, one
consistent count, and a plausible mechanism — good enough to design
against, not good enough to ship unverified.

`M6_pc_1F` neither confirms nor contradicts it: the script references only
`[4]` and `[7]` despite the room having 4 live actors, because a script only
touches actors it needs to manipulate. Its nurse is reached through
`$stack[1]`, so it is never named by literal index at all.

### The two-engine-callers convergence — TESTED AND FALSE

It was tempting to read the two script mechanisms as matching the two engine
callers §2 records for `recoveryEventPC` (`objHero.s:962` and
`objPeople.s:839`), with the machine case being "the hero uses the machine"
because its receiver is a global rather than room-local character.

**That hypothesis is wrong.** `objHero.s`'s caller was resolved the same way
§1 resolved the People one, by reading the jump table's own data rather than
inferring from code layout:

- `cmpHero` uses the identical dispatch shape — `subi r0, r27, 0x10`,
  `cmplwi r0, 0x35` (54 entries), table `@2588`.
- The table has exactly 54 entries. `bl recoveryEventPC` at `0x801C2598`
  falls inside the case beginning `0x801C243C`, which is **table index 42**
  (the next case starts `0x801C25A0`).
- `42 + 0x10` = **method 58**.
- GoD Tool names class **43** (`Player`) method 58
  **`healPartyAtPokeCenter`**.

So the second engine caller is not a hero-flavoured variant of the same
script call at all — it is a **different script method on a different
class**: `Player::healPartyAtPokeCenter`, alongside
`Character::useHealingMachine`.

Both script mechanisms found in §6d therefore funnel through the *same*
engine path: class 35 method 101 → `cmpPeople` index 85 → `objPeople.s:839`.
The nurse/machine distinction is real at the script level and invisible at
the engine level.

### Which exposed a gap in the sweep — now closed

§6b/§6c searched for `Character::101` only, so it could not have found a room
that heals via `Player::58`. Re-scanning all 276 extracted scripts for
**both** signatures:

- **15 rooms** — exactly the same set as §6c.
- **0 rooms** call `Player::healPartyAtPokeCenter`.

So the method exists in the script language and is wired up in the engine,
but **no room script in the game uses it**. The §6c inventory is now
verified complete against both known healing signatures rather than merely
against the one that was looked for, which is a stronger claim than it could
previously make.

Two caveats survive unchanged: this still only finds *direct* `callstd`
sites, and a third healing route on some other class would still be invisible
to a search that does not know to look for it — which is exactly the mistake
this section corrects.

## 7. REMAINING PHASES (for a fresh session)

Phase 1 (inventory) is **complete** — section 3. Do not redo it.
Phases 2 and 3 are **demonstrated for one room** — section 6a. Generalise
them; do not re-derive them.

**Phase 2 (scale up) — extract all room scripts.** Batch the DolphinTool
extraction across every room `.fsys`, pull the type-7/`TCOD` entry from
each, and disassemble. Record provenance. Reproducible script, not manual
per-room work.

**Phase 3 (generalise) — resolve the call encoding properly.** The `callstd`
form is confirmed for the direct case. Still to determine: operand layout
and method-index width, receiver/object encoding, argument count/stack
behaviour, endianness, control flow, and **whether method 101 can be reached
indirectly** (function pointer, computed dispatch, shared subroutine).
Reading `XDscriptLib/_Instruction.py` gives the authoritative encoding
without guesswork.

**Phase 4 — control-flow analysis.** Find scripts that can reach a method
101 call. Distinguish direct unconditional, direct conditional, via shared
subroutine, unreachable/dead, and helper-invoked. A shallow direct-call
scan is acceptable first, but must state what indirection it misses.

**Phase 5 — map scripts to actors.** Per healing script record: room id,
room name, actor index, actor type/model, talk script ID, call location,
conditional flag, confidence. **Actor index alone is not a runtime
identity** — document which room-loaded structures let the companion bind a
generated entry to the live actor (`floor_character` record + the
people-work actor, as used by `npc_beacons.py`).

**Phase 6 — validate generality.** Required set:

- the Agate nurse in `M3_pc_1F` (known case)
- a nurse in a **second** Pokémon Center (`M6_pc_1F` sampled already)
- a third healing location with different layout/scripting if one exists
- a **Poké Mart clerk** with widened talk distance
- **another receptionist / desk NPC** (e.g. Mt. Battle)

The clerk and receptionist **must not** classify as healing services unless
their scripts genuinely reach method 101. This is the false-positive
control for section 5.

**Phase 7 — availability semantics.** Section 6.

**Phase 8 — generate data, do not hand-author.** Produce
`data/generated_healing_services.json` (or the project's generated-data
convention) with a header recording how and when it was generated. Per
entry: game/version identity, room ID, talk script ID, actor identity
fields, method-call evidence (source archive + offset), direct/conditional
classification, confidence. A hand-written list of Centers may be used
**only** as a temporary test oracle.

**Phase 9 — Interactables integration.** Add the semantic entry
"Pokémon healing service". The People/NPC tab may still list the nurse as a
person. The Interactables entry must:

- point at the same **live** People actor
- use the actor's **live** position (`people_work + 0x08` → model `+0x18`)
- use the **live** talk distance (`people_work + 0x178`)
- respect actor enabled/loaded state
- navigate to a valid approach position where possible
- report real interaction state: out of range / in range but facing away /
  interaction available (subject to line of sight)

**Phase 10 — XD/XG boundary.** Determine whether XG alters these room
scripts or healing actors. Generate from the actual targeted resources. If
XG does not alter them, document the evidence. Do not assume a
retail-XD-generated table covers XG.

### Deliverables still owed

- `Documentation/XD_SCRIPT_METHOD_CALL_PARSING.md`
- `Documentation/HEALING_SERVICE_LIVE_VALIDATION.md`
- the generated healing-service data file
- focused parser/extractor tests
- focused runtime classification tests
- index + handoff updates as each lands

---

## 8. BOUNDARIES (carried forward)

- Do **not** use widened talk distance as the semantic classifier.
- Do **not** identify nurses by actor index, coordinates, model/clothing, or
  guessed role.
- Do **not** hand-hardcode one entry per Pokémon Center as the final answer.
- Do **not** attempt a full XD scripting-language implementation unless
  accurate method-call tracing genuinely requires it.
- Do **not** change unrelated navigation behaviour.
- Keep parser and generated-data pipeline independently testable.
- If extraction or parsing blocks, **document the exact missing format or
  opcode** rather than substituting a heuristic.

---

## 9. LIVE OBSERVATIONS RECORDED DURING THE TRACE

Read-only, from the running game; useful as fixtures for later phases.

**`M3_pc_1F` (Agate Village Pokémon Center, floor `0x85`)** — 3 actors:

| idx | people_info type | live talk dist | static | position |
|---|---|---|---|---|
| 0 | 119 | 3.00 | 3.00 | (24.9, 5.3) |
| 1 | 87 | 3.00 | 3.00 | wanders: (−5.3, 1.0) → (−8.0, −1.3) → (−20.8, …) |
| 2 | **123** | **6.00** | 3.00 | (−0.9, −21.9), stationary |

Agate nurse talk script ID: **`0x01000008`**.

**`M6_pc_1F` (floor `0x9A`)** — 4 actors, types 87, 114, 118, 123.

Types **87** and **123** appear in both Centers; type 87 was observed
wandering, type 123 stationary. **This is circumstantial only** and is
explicitly *not* the basis for classification — it is recorded so a later
phase can check its script-derived answer against it.

**Shop greeting, live 2026-08-04 (Poké Mart).** The `ChoiceMenuReader` +
`RuntimeMessageCatalog` added earlier in the same session fired correctly on
the shop's generic choice widget:

```
CHOICE MENU menu_id=89 index=0 of 3 label='BUY' ids=(15027, 15028, 15029)
SPEECH  'BUY. 1 of 3.'
```

This is the runtime message resolver validated on a second independent
screen (the first was Mt. Battle, ids 31045-31047 → YES/INFO/EXIT).

⚠ **Open risk:** menu 89 is the shop greeting, which `menus.py` *also*
narrates from the hardcoded `shop_menu_labels` tuple `("Buy","Sell","Quit")`.
No duplicate line appeared in the sampled log, but the two readers are not
mutually exclusive by construction — `choice_menu.py` only excludes
`new_game_confirmation_menu_id` (53), and the shop cursor's id is
engine-allocated. **Listen for "Buy" being spoken twice at a shop.** If it
is, add the shop case to `ChoiceMenuReader.ignored_menu_ids`, or better,
retire the hardcoded labels in favour of the resolved ones.

`colBallSize` (`people_info + 0x10`) = 4.00 for all three Agate actors.
Applying the engine's own gate `0.3 + talkDistance + colBallSize` gives
10.30, while the player interacted from 12.28 — so **one term of the
distance model is still unaccounted for**. `peopleTalkCheck` measures a 3-D
distance to `peopleGetNeckPos`, and its `colBallSize` may be taken from a
different entity than the target NPC. Unresolved; relevant to Phase 9's
range reporting, not to classification.

---

## 10. KEY ADDRESSES

| Symbol | Address | Note |
|---|---|---|
| `recoveryEventPC` | `0x801CF474` | Pokémon Center healing event |
| `recoveryEventCommon` | `0x801CF404` | |
| `recoveryPokemon` | `0x801CF3A4` | |
| `cmpPeople` | `0x801C3EA8` | `AppScript::cmpPeople(int, tigaVariant*, tigaVariant*)` |
| dispatch table `@2522` | — | 99 entries, index = method − `0x10` |
| healing call site | `0x801C4A94` | `bl recoveryEventPC` |
| `peopleTalkCheck` | `0x802A3444` | distance + 40° cone + line of sight |
| `peopleGetTalkDistance` | `0x802A2E90` | reads `people_work + 0x178` |
| `peopleSetTalkDistance` | `0x802A2E58` | writes `people_work + 0x178` |
| `peopleBiosGetPosPtr` | `0x80297724` | `people_work + 0x08` → model |
| `GSmodelGetPositionPtr` | `0x800F7B30` | model `+ 0x18` |
| `floorCharacterBiosGetTalkSctID` | `0x80122528` | talk script ID |

Source files in `xd-decomp/build/GXXE01/asm/`:
`game/pxdvs/app/recovery/recoveryEvent.s`,
`game/pxdvs/app/script/objPeople.s`,
`game/pxdvs/app/script/objHero.s`,
`game/pxdvs/app/people/peopleTalk.s`.
