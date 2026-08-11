# BATTLE_SYSTEM_ARCHITECTURE.md

**Status:** Phase 1 deliverable, created 2026-08-06. Ownership map for the
battle subsystem, derived static-first from `xd-decomp`'s own symbol table,
the shipped `main.dol`'s data sections, and disassembly — then cross-checked
against 3,673,576 lines of the production narrator log
(`Companion/logs/battle_narrator_phase1b.log`).

Nothing in this document was derived from the project owner's description of
on-screen text. Every address carries the symbol name it came from, so each
claim is re-checkable against `xd-decomp/config/GXXE01/symbols.txt`.

---

## 0. The single most important finding

The battle narrator has **two message pipelines that never met**:

| Pipeline | Where | What it does | Battle coverage |
|---|---|---|---|
| Generic runtime renderer | `runtime_messages.py` + `message_render.py` | Resolves any message ID out of the game's own loaded string tables and performs the engine's own control-code substitutions | **Deliberately excluded battle opcodes 0x0D–0x2A** (`message_render.py` docstring: "Deliberately NOT implemented") |
| Battle narrator | `messages.py` (offline `fight_common.fsys`) + `narrator.py` + `resolver.py` | Matches a message ID to a per-ID `state.mode`, samples one or two globals, and formats a **hand-written English sentence** | ~45 message IDs out of 300+ seen live |

The generic renderer skipped the battle opcodes because the `msgctrlcode`
dispatch table was only transcribed for the non-battle half. `narrator.py`
then filled the gap with per-ID English literals and per-ID
`VERIFIED_OPCODES` allow-lists — which is why every message ID nobody
enumerated is silent, and why the ones that do speak carry copied game text.

**The whole battle-opcode half of that table is recoverable, and is
transcribed in §2 below.** Implementing it collapses most of the reported
symptoms into one repair.

---

## 1. Battle lifecycle and top-level structures

| Subsystem | Owner (symbol) | Runtime address | Notes |
|---|---|---|---|
| Fight floor root | `FightFloor` | `0x804A1730` (`profile.fight_floor_root`) | Embeds 2 `FightSide` at `+0x14`, stride `0x6EF0` |
| Fight side | `fightSideGetValidFightTrainerPtr` | side base `+0x64`, stride `0x3744` | Up to 2 `FightTrainer` per side |
| Fight trainer | `fightTrainerGetNamePtr` | trainer `+0x04` = embedded Hero (name) | `+0x00` u16 = deck trainer data ID |
| Trainer party | `fightTrainer_GetFightPokemonPtr` | trainer `+0x97C`, stride `0x300`, 6 slots | Persistent per-trainer roster. Absolute base for side 0 / trainer 0 / slot 0 is `floor + 0x9F4` (`0x14 + 0x64 + 0x97C`); `profile.fight_trainer_first_pokemon_offset` held `0xA04` and was **corrected in Phase 2** |
| Active battler array | — | `fight_floor_root + 0xDE44`, 8 × u32 `FightOutPokemon*` | **Compacts after a faint** (see §4) |
| `FightOutPokemon` | `fightOutPokemonGetNicknamePtr` (`0x80203548`) | `+0x04` → `FightPokemon*`; `+0x7B0..0x7B6` stat stages | Live battle actor wrapper |
| `FightPokemon` | `fightPokemonGetPokemonPtr` | `+0x04` → embedded `Pokemon`; `+0x52` nickname | |
| Embedded `Pokemon` | — | `+0x04` HP, `+0x11` level, `+0x16` condition, `+0x90` max HP, `+0xBA` u16 dark-Pokémon data ID | Already verified by `health.py`/`party.py` |
| Battle sequence engine | `fightSeq_GetWazaSeq` / `fightSeq_NextWazaSeq` | `_wazaSeqAdrs` `0x804EB930`, `ActionSeqNo` `0x804EB934` | Drives every `WS_*` step |
| Battle message window | `fightMenuOpenMsg` / `fightMenuCloseMsg` | GSmsg task array, `manager_root 0x804E8348 +0x1C` | Already read by `tasks.GSmsgTaskArray` |

---

## 2. The message-control dispatch table (`msgctrlcode`)

`msgctrlcode = .data:0x80404710`, size `0x378` = **111 entries × 8 bytes**.
Entry layout: `+0x00 u8 flags` (bits 6–7 = return mode), `+0x04 u32 handler`.
Modes: `0` = formatting only, `1` = handler returns a GSchar text pointer,
`2` = handler returns another message ID to splice in.

Dumped directly from `xd-decomp/orig/GXXE01/sys/main.dol` and named against
`symbols.txt`. **This is the authoritative opcode → data-source map.** The
`Source` column is the global each handler actually reads.

### 2a. Battle opcodes — the ones currently unimplemented

| Op | Mode | Handler | Source global | Address | Kind |
|---|---|---|---|---|---|
| 0x0D | 1 | `msgctrlEvStrBuf0` | `_EV_STR_BUF0` | `0x804EB1F0` | text pointer |
| 0x0E | 1 | `msgctrlEvStrBuf1` | `_EV_STR_BUF1` | `0x804EB1F4` | text pointer |
| 0x0F | 1 | `msgctrlAttackMons` | `_ATTACK_MONS` | `0x804EB1FC` | `FightOutPokemon*` → nickname |
| 0x10 | 1 | `msgctrlDeffenceMons` | `_DEFENCE_MONS` | `0x804EB200` | `FightOutPokemon*` → nickname |
| 0x11 | 1 | `msgctrlClientMos` | `_CLIENT_MONS` | `0x804EB204` | `FightOutPokemon*` → nickname |
| 0x12 | 1 | `msgctrlTsuikaMons` | `_TSUIKA_MONS` | `0x804EB208` | `FightOutPokemon*` → nickname |
| 0x13 | 1 | `msgctrlMyName` | `_MY_NAME` | `0x804EB20C` | text pointer |
| **0x14** | 1 | `msgctrlMyMons` | `_MY_MONS` | **`0x804EB210`** | **text pointer** |
| **0x15** | 1 | `msgctrlMyMons2` | `_MY_MONS2` | **`0x804EB214`** | **text pointer** |
| **0x16** | 1 | `msgctrlEnemyMons` | `_ENEMY_MONS` | **`0x804EB218`** | **text pointer** |
| **0x17** | 1 | `msgctrlEnemyMons2` | `_ENEMY_MONS2` | **`0x804EB21C`** | **text pointer** |
| 0x18 | 1 | `msgctrlEnemyTmons` | `_ENEMY_TMONS` | `0x804EB220` | text pointer |
| 0x19 | 1 | `msgctrlEnemyTmons2` | `_ENEMY_TMONS2` | `0x804EB224` | text pointer |
| 0x1A | 1 | `msgctrlSpeabiNamea` | `_SPEABI_NAMEA` | `0x804EB228` | ability text pointer |
| 0x1B | 1 | `msgctrlSpeabiNamed` | `_SPEABI_NAMED` | `0x804EB22C` | ability text pointer |
| 0x1C | 1 | `msgctrlSpeabiNamec` | `_SPEABI_NAMEC` | `0x804EB230` | ability text pointer |
| 0x1D | 1 | `msgctrlSpeabiNamet` | `_SPEABI_NAMET` | `0x804EB234` | ability text pointer |
| 0x1E | 1 | `msgctrlClientnowork` | `_CLIENTNOWORK` | `0x804EB238` | `FightOutPokemon*` → nickname |
| 0x1F | 1 | `msgctrlSideAttackNameha` | `_SIDE_ATTACK_NAMEHA` | `0x804EB23C` | side-qualified name (§2c) |
| 0x20 | 1 | `msgctrlSideAttackNamewo` | `_SIDE_ATTACK_NAMEWO` | `0x804EB240` | side-qualified name |
| 0x21 | 1 | `msgctrlSideAttackNameno` | `_SIDE_ATTACK_NAMENO` | `0x804EB244` | side-qualified name |
| **0x22** | 1 | `msgctrlTrainerType` | `_TRAINER_TYPE` | **`0x804EB248`** | **trainer class text pointer** |
| **0x23** | 1 | `msgctrlTrainerName` | `_TRAINER_NAME` | **`0x804EB24C`** | **trainer name text pointer** |
| 0x24 | 1 | `msgctrlTrainerLose` | `_TRAINER_LOSE` | `0x804EB250` | text pointer |
| 0x25 | 1 | `msgctrlTrainerEnename` | `_TRAINER_ENENAME` | `0x804EB254` | text pointer |
| 0x26 | 1 | `msgctrlTrainerEnename2` | `_TRAINER_ENENAME2` | `0x804EB258` | text pointer |
| 0x27 | 1 | `msgctrlTrainerClientno` | `_TRAINER_CLIENTNO` | `0x804EB25C` | text pointer |
| 0x28 | 1 | `msgctrlWazaName` | `_WAZA_NAME` | `0x804EB260` | move-name text pointer |
| 0x29 | 1 | `msgctrlItemName` | `_ITEM_NAME` | `0x804EB264` | item-name text pointer |
| 0x2A | 1 | `msgctrlPasoName` | `_PASO_NAME` | `0x804EB268` | text pointer |
| 0x41 | 1 | `msgctrlEvStrBuf2` | `_EV_STR_BUF2` | `0x804EB1F8` | text pointer |
| 0x42 | 1 | `msgctrlSideDefenceNameha` | `_SIDE_DEFENCE_NAMEHA` | `0x804EB26C` | side-qualified name |
| 0x43 | 1 | `msgctrlSideDefenceNamewo` | `_SIDE_DEFENCE_NAMEWO` | `0x804EB270` | side-qualified name |
| 0x44 | 1 | `msgctrlSideDefenceNameno` | `_SIDE_DEFENCE_NAMENO` | `0x804EB274` | side-qualified name |
| 0x4B | 1 | `msgctrlMoney` | `_Money` | `0x804EB2A8` | u32, thousands-grouped |
| 0x59 | 2 | `msgctrlNpc` | `_Npc` | `0x804EB2CA` | u16 **message ID** (speaker name) |

`message_render.py` already implements 0x00–0x09, 0x2B–0x39, 0x3D/0x3E,
0x4B–0x57, 0x5A–0x5E, 0x6A, 0x6D/0x6E. The rows above are the missing half.

### 2b. `msgctrlAttackMons` and friends are not plain reads

Disassembly of `msgctrlAttackMons` (`0x801541C4`):

```
_ATTACK_MONS  ->  fightFloorGetFightOutPokemonPtrToFightTrainerPtr
              ->  if fightFloorIsNowEncountTuusinTaisen()   (link battle only)
                     compose "<trainer>'s <nickname>" via message 0x4FE4
                  else
                     return fightOutPokemonGetNicknamePtr(_ATTACK_MONS)
```

So in every non-link battle these four opcodes are exactly
"`FightOutPokemon*` → nickname pointer". `msgctrlClientnowork` (0x1E) is the
same function body over `_CLIENTNOWORK`.

### 2c. Side-qualified names (0x1F–0x21, 0x42–0x44)

`_msgctrlSideName(FightOutPokemon*, particle)` (`0x80153CF0`) picks one of
six messages — `0x4F67`–`0x4F6C` (20327–20332) — based on
`fightTargetIsHostSide()` and the particle index. It returns a GSchar
pointer to already-substituted text, so the renderer only has to decode it
recursively. **No English needs to be written for this.**

> **Corrected 2026-08-06 (Phase 2).** This section originally speculated
> that these six messages might supply a per-battler position word usable to
> tell two identical species apart. Reading them out of the shipped
> `fight_common` table disproved it: they are `Foe's party` /
> `Ally's party` / `Foe's party is` / `Ally's party is` — three grammatical
> variants of a **whole-side** qualifier, used by side-wide messages such as
> 20071 `[0x1F] covered by a veil!`. The game has no built-in per-battler
> disambiguation. See
> [BATTLE_IDENTITY_MODEL.md](BATTLE_IDENTITY_MODEL.md) §4.

### 2d. The fight-mode override — why "the same opcode" has two sources

`fightMsgctrlSetValue(opcode, value)` (`fightMenu.s:0x802370EC`):

```
if (ServerWork[7] == 2)                      # ServerWork = .sdata:0x804E85C0
    switch (opcode)
        0x0F -> msgCtrlVal[0]   0x804187D0
        0x0D -> msgCtrlVal[1]   0x804187D4
        0x28 -> msgCtrlVal[2]   0x804187D8
        0x0E -> msgCtrlVal[3]   0x804187DC
        default -> msgctrlSetValue(opcode, value)
else
    msgctrlSetValue(opcode, value)           # writes the .sbss msgvar
```

`msgCtrlVal = .data:0x804187D0`, size `0x10`. Gate byte = `ServerWork + 7`
= **`0x804E85C7`**.

This is why `resolver.py` needs two different addresses for what the
template calls the same `[opcode_0x0D]`: message 20003 reads
`_EV_STR_BUF0`, messages 20007–20013 read `msgCtrlVal[1]`. Today that choice
is hardcoded per message ID. **The correct rule is to read the gate byte.**

### 2e. Number formatting

`msgctrlDigit` (0x2F) calls `_msgctrlMakeDigit(buf, 16, _Digit, 0)`;
`msgctrlMoney` (0x4B) calls it with flag `4`. Flag 4 takes the
`index % 3 == 0` branch that inserts the locale separator every three
digits. Python `f"{value:,}"` matches the English behaviour.

---

## 3. Message families, grouped by owner

Counts are real occurrences in the production log. "Status" is today's
behaviour.

### 3a. Currently suppressed for "unverified controls" (the largest group)

Every one of these is fully resolvable from §2a. Selected rows:

| ID | Template (from the game's own table) | Opcodes | n | Reported as |
|---|---|---|---|---|
| 20023 | `[Player Battle 19] got $[opcode_0x4B] for winning!` | 0x13, 0x4B | 98 | issue 11 (reward) |
| 20103 | `[Pokemon 15] is fast asleep.` | 0x0F | 48 | issue 7 |
| 20003 | `[0x0D] gained [0x0E] [Quantity 47] EXP. Points!` | 0x0D,0x0E,0x2F | 44 | (partly works) |
| 20489 | `The REVERSE MODE attack hurts [Pokemon 15]!` | 0x0F | 40 | issue 21 |
| 20451 | `[Pokemon 15] is in REVERSE MODE!` | 0x0F | 40 | issue 21 |
| 20441 | `[Player Battle 19] threw a SNAG BALL!` | 0x13 | 37 | issue 21 |
| 20048 | `[Pokemon 18] is paralyzed! It may be unable to move!` | 0x12 | 32 | — |
| 20432 | `[Player Battle 19] called [Pokemon 15]!` | 0x13,0x0F | 26 | **issue 2 (Call)** |
| 20433 | `[Pokemon 15]!` | 0x0F | 26 | **issue 2 (Call)** |
| 20435 | `[Pokemon 15] came to its senses from the TRAINER's call!` | 0x0F | 19 | **issue 2 (Call)** |
| 20314/20315/20316/20317 | `Go! [0x0D]!` / `Do it!` / `Go for it,` / `Get 'em,` | 0x0D | 46 | issue 12 |
| 20319/20321/20322 | `[0x0D], that's enough! Come back!` etc. | 0x0D | 24 | issue 12 (recall) |
| 20027 | `[Pokemon 18] fell asleep!` | 0x12 | 20 | **issue 7** |
| 20104 | `[Pokemon 15] woke up!` | 0x0F | 10 | **issue 7** |
| 20074 | `[Pokemon 15] went to sleep!` | 0x0F | 2 | **issue 7** |
| 20036 | `[Pokemon 18] is badly poisoned!` | 0x12 | 5 | **issue 8** |
| 20044 | `[Pokemon 15] is frozen solid!` | 0x0F | 4 | **issue 3** |
| 20042 | `[Pokemon 18] was frozen solid!` | 0x12 | 2 | **issue 3** |
| 20176 | `[Pokemon 15] made [Pokemon 16] drowsy!` | 0x0F,0x10 | 2 | **issue 4** |
| 20020 | `It doesn't affect [Pokemon 16]...` | 0x10 | 7 | **issue 6** |
| 20357 | `Give a nickname to the captured [0x16]?` | 0x16 | 3 | **issue 10** |
| 20301/20304/20305/20300 | trainer challenge / send-outs / defeat | 0x22,0x23,0x16,0x17 | 42 | issues 12, 13 |
| 20313 | `Go! [Switch Pokemon 21] and [Switch Pokemon 20]!` | 0x15,0x14 | 13 | issues 12, 14 |
| 20217/20049/20203/20215/20206/20208 | ability messages | 0x1B,0x1C,0x1E | 39 | — |
| 20476/20377/20374 | `[Player Battle 19] threw the [Item 41]!` etc. | 0x13,0x29,0x1E | 10 | issue 19-adjacent |
| 22xxx/23xxx/24xxx | `[Speaker]: ...` trainer defeat lines | 0x59 | ~40 | — |

Full inventory: 118 distinct suppressed IDs. The `[Speaker]` family alone is
~40 of them and resolves through opcode 0x59 → `_Npc` → message ID.

### 3b. Sampled but rejected (mode chosen, live read failed)

| ID | Template | n rejected | Reason logged |
|---|---|---|---|
| 20470 | `A wild [0x16] appeared!` | 195 | `FightOutPokemon: invalid address 0x00000000` |
| 20473 | `Gotcha! [0x16] was caught!` | 229 | same |
| 20448 | `Gotcha! [0x16] was caught!` | 1636 | same |
| 20304 | opponent single send-out | 211 | same |
| 20312 | `Go! [Switch Pokemon 20]!` | 333 | same |
| 20022 | `[Pokemon 16] fainted!` | 41 | same |
| 20247 | target-side stat change | 1790 | same |
| 20007–20013 | move learning | ~2200 | `learning Pokemon name: invalid address 0x00000000` |
| 20003 | EXP gained | 253 | `experience Pokemon name: invalid 0x00000000` |
| 20301/20305/20300 | trainer name/class | 1142 | `opponent trainer name: invalid address 0x00000000` |

**Every one of these reads the wrong global.** 20470/20473/20448/20304 use
opcode **0x16 (`_ENEMY_MONS`, `0x804EB218`)** but the code samples
`_TSUIKA_MONS` (`0x804EB208`). 20312 uses **0x14 (`_MY_MONS`,
`0x804EB210`)** but the code samples `_ATTACK_MONS`. 20301/20305/20300 need
**0x22/0x23 (`_TRAINER_TYPE`/`_TRAINER_NAME`)** but the code walks the
persistent `FightTrainer` record instead.

This closes a question left open since 2026-07-30, when four candidate
globals (`_ATTACK_MONS`/`_DEFENCE_MONS`/`_CLIENT_MONS`/`_TSUIKA_MONS`) were
all logged as null at every send-out. They were the wrong four; the
send-out opcodes were never backed by any of them.

### 3c. Spoken today

45 IDs, of which 20430 (`Oh! A Shadow Pokémon!`) and 20481 have **no
substitution opcodes at all** — their text can be read verbatim from the
game's own table with no substitution machinery whatsoever.

---

## 4. Battler identity

| Question | Authoritative answer | Address / symbol |
|---|---|---|
| Who is acting? | `_ATTACK_MONS` | `0x804EB1FC` |
| Who is being hit? | `_DEFENCE_MONS` | `0x804EB200` |
| Who is the message's extra subject? | `_TSUIKA_MONS` | `0x804EB208` |
| Who did the player just send out? | `_MY_MONS` / `_MY_MONS2` (text) | `0x804EB210` / `0x804EB214` |
| Who did the foe just send out? | `_ENEMY_MONS` / `_ENEMY_MONS2` (text) | `0x804EB218` / `0x804EB21C` |
| Who is on the field right now? | active battler array | `fight_floor_root + 0xDE44`, 8 × `FightOutPokemon*` |
| Who owns a given battler? | `fightFloorGetFightOutPokemonPtrToFightTrainerPtr` | — |
| Which side is a battler on? | `fightTargetIsHostSide` | — |
| Who receives EXP / levels up? | **`get_exp_fight_pokemon_ptr`** | **`.sbss:0x804EB964`** |
| Stable per-instance key | `FightOutPokemon*` + `FightPokemon*` + embedded `Pokemon*` | `health.BattlerIdentity` |

**Known hazard, already documented in the 2026-07-25 handoff and still
true:** the active battler array compacts after a faint, so array index is
not a stable visual position. `health.py` handles this by keying on the
pointer triple, not the slot. The send-out/double-send-out code in
`narrator.py` does *not* — it calls `resolver.trainer_party_names(side, n)`,
which returns the first *n* non-empty nicknames from the persistent
`FightTrainer` party array, i.e. **party order, never send-out order**. That
is the direct cause of issues 12, 13 and 14.

Duplicate-species disambiguation is unaddressed anywhere in the codebase.
*(Phase 2 update: `_msgctrlSideName`'s messages turned out to be whole-side
qualifiers, not per-battler labels — see §2c. The model now uses the game's
side word plus an accessibility-owned first-appearance ordinal; see
[BATTLE_IDENTITY_MODEL.md](BATTLE_IDENTITY_MODEL.md) §4.)*

**Phase 2 resolved this section's gaps.** The canonical model lives in
`battle_narrator/battle_identity.py`: a `FightPokemon*` determines
`(side, trainer, party slot)` by pure arithmetic, the personality value at
`Pokemon+0x28` makes the key unique, and `BattlefieldSlotTracker` gives each
active-array slot a replacement epoch so a stale battler can never be
announced as current.

---

## 5. Experience, level-up, stat gains, move learning

Sequence steps live in `fightSeqSpAction.s` / `fightSeqBasis.s` and are
driven by `fightSeq_NextWazaSeq`.

| Stage | Owner | Runtime state |
|---|---|---|
| EXP recipient | `WS_STATUS_WINDOW` | `get_exp_fight_pokemon_ptr` = `0x804EB964` (`FightPokemon*`) |
| EXP amount / level number | message opcodes | `_Digit` = `0x804EB27C` (opcode 0x2F) |
| Recipient name in 20003/20006 | message opcode 0x0D | `_EV_STR_BUF0` = `0x804EB1F0`, or `msgCtrlVal[1]` when `ServerWork[7]==2` |
| Pre-level stat snapshot | `old_menu_lvup_status` | **`.bss:0x804B0A20`**, 0xE bytes |
| Post-level stats | `fightPokemonToMenuLvupStatus(get_exp_fight_pokemon_ptr, &dst)` | computed from the live Pokémon |
| Displayed gains | `fightMenuSubMenuLvupStatus(new, old, &diff)` then `fightMenuOpenLevelUpStatusMenu(diff, 1)` | stack buffer, but `new - old` reproduces it exactly |
| Move the Pokémon wants | **`OboeWazaNo`** | **`.sbss:0x804EB93C`** (u16 move ID) |
| Which move slot | `waza_oboe_banme` | `.sbss:0x804EB968` (u8) |
| Move-learn sequence steps | `WS_WAZAOBOE_CHECK` (`0x8021AB88`), `WS_OBOEWAZANO_SET` (`0x8021AC80`) | — |

### MENU_LVUP_STATUS layout (0xE bytes)

Derived from `getPokemonLvupStatus` (`menuUseItem.s:0x800A57C0`) and
`fightPokemonToMenuLvupStatus` (`0x802008BC`), which agree field for field:

| Offset | Type | Field | Accessor |
|---|---|---|---|
| +0x00 | u8 | flag (zeroed) | — |
| +0x02 | u16 | Max HP | `pokemon_GetMaxHp` / status 0x87 |
| +0x04 | u16 | Attack | `pokemon_GetPhyAtk` / 0x88 |
| +0x06 | u16 | Defense | `pokemon_GetPhyDef` / 0x89 |
| +0x08 | u16 | **Speed** | `pokemon_GetNimbleness` / 0x8C |
| +0x0A | u16 | Special Attack | `pokemon_GetSpeAtk` / 0x8A |
| +0x0C | u16 | Special Defense | `pokemon_GetSpeDef` / 0x8B |

Note Speed sits between Defense and Special Attack in memory. Reading these
in on-screen order would silently swap three stats.

**This is the authoritative old/new buffer the task asked for.** No formula
is needed and none should be used.

---

## 6. In-battle bag

The in-battle bag is a **different module** from the overworld bag that
`bag_menu.py` models (`menuPocket2`). Its owner is
`menuPocketBattleDisk.cpp`:

| Concern | Symbol | Address |
|---|---|---|
| Main loop | `menuPocketBattleDiskMain` | `0x8000EE78` |
| Cursor control | `_controlCursor__34@unnamed@menuPocketBattleDisk_cpp@Fv` | `0x8000EF40` |
| Item ID at a menu position | `getItemIDFromMenuPos(int)` | `0x8000F470` |
| Number of filled slots | `getNbItemSlot()` | `0x8000F528` |
| Item name message ID | `getItemNameMsg(u32)` | `0x8000F5C0` |
| Selection | `selectItem()` | `0x8000F404` |
| Used-mark display | `diskUsedMarkDisplay(...)` | `0x8000F358` |
| List drawing | `menuPocketBattleDiskPrintItemList` | `0x8000ED84` |
| Category label | `menuPocketBattleDiskPrintItemKind` | `0x8000ED0C` |

`getItemNameMsg` means the battle disk resolves names through the ordinary
item-name message pipeline `item_database.py` already uses — so the existing
authoritative item chain (item record → item ID → database record → name
message ID → localized name) is reusable without widening scope.

`diskUsedMarkDisplay` is the "already used this turn" mark; a blind player
has no other way to know an item is unusable.

The battle-item confirmation window and the return-to-command-menu path are
not yet located and are the main open item for Phase 5.

---

## 7. Yes/No windows

Three separate mechanisms exist today:

1. `menus.yes_no_focus` — hardcodes `("Yes", "No")` and requires cursor 0/1.
   Used for the generic `(51, 53)` overlay.
2. `profile.new_game_confirmation_labels` — two full hardcoded sentences.
3. `choice_menu.ChoiceMenuReader` — **generic and correct**: reads a
   zero/garbage-bounded `u32` array of *message IDs* from the window's
   allocation at `window_alloc_offset`, resolves each through
   `RuntimeMessageCatalog`, and reports "label, n of m". Nothing hardcoded.
   Its own docstring already flags folding (1) and (2) into it as "a strict
   improvement".

`winMsgCtrlYesNo` (`0x80116D60`) is the engine-side owner and is the place to
confirm whether the battle move-learn prompt uses the same widget.

---

## 8. Where each reported issue is owned

| # | Reported issue | Owner | Root cause |
|---|---|---|---|
| 1 | Purification messages hardcoded | `resolver.FIXED_SENTENCES` | copied literals, incl. mojibake |
| 2 | "Call Pokémon" missing | 20432/20433/20435 | opcodes 0x13/0x0F unimplemented |
| 3 | Frozen missing | 20044/20042 | opcodes 0x0F/0x12 unimplemented |
| 4 | Grew drowsy missing | 20176 | opcodes 0x0F/0x10 unimplemented |
| 5 | `h! A Shadow PokÃ©mon!` | `FIXED_SENTENCES[20430]` | source literal is UTF-8-as-cp1252 mojibake; message has *no* opcodes and needs no literal at all. Leading-`O` loss not reproduced in the log (log shows `Oh!`) — open, see §9 |
| 6 | Immunity missing | 20020 | opcode 0x10 unimplemented |
| 7 | Sleep messages missing | 20027/20103/20104/20074 | opcodes 0x0F/0x12 unimplemented |
| 8 | Badly poisoned missing | 20036 | opcode 0x12 unimplemented |
| 9 | Wild appeared missing | 20470 | samples `_TSUIKA_MONS`, needs `_ENEMY_MONS` |
| 10 | Nickname prompt missing | 20357 | opcode 0x16 unimplemented |
| 11 | Reward missing | 20023 | opcodes 0x13/0x4B unimplemented |
| 12 | Send-out reads wrong Pokémon | `trainer_party_names` | party order, not `_MY_MONS`/`_ENEMY_MONS` |
| 13 | Duplicate species ambiguous | identity model | no disambiguation; `_msgctrlSideName` unused |
| 14 | Baton Pass corrupts identity | same as 12 | party order survives the swap, send-out order does not |
| 15 | Wrong Pokémon levels up | `level_sample()` | samples `_ATTACK_MONS`, needs `get_exp_fight_pokemon_ptr` / opcode 0x0D |
| 16 | Stat gains not announced | not implemented | `old_menu_lvup_status` never read |
| 17 | "wants to learn" not read | 20008 | sample rejected; `OboeWazaNo` never read |
| 18 | Yes/No for move learning not read | `menus.yes_no_focus` | hardcoded pair, not wired to this prompt |
| 19 | Item confirmation not read | `menuPocketBattleDisk` | no reader exists |
| 20 | Bag doesn't refresh after use | `bag_menu.py` | models the overworld pocket, not the battle disk |
| 21 | Shadow/purification battle events | 20430/20451/20462/20481/20489/20441 | mix of literals and unimplemented opcodes |

---

## 9. Open unknowns after Phase 1

1. **Leading-`O` loss in "Oh! A Shadow Pokémon!"** — the narrator log records
   the full `'Oh! A Shadow PokÃ©mon!'` for all 28 occurrences, so the
   truncation happens downstream of `SpeechCoordinator.emit` (Tolk/NVDA), not
   in the composed string. `BATTLE_EVENT` defaults to `interrupt=True`, so
   the most likely mechanism is a self-interrupt race between consecutive
   battle events. Needs one live capture to confirm; the mojibake half is
   fixed regardless by resolving 20430 from the game's own table.
2. **Battle item-confirmation window** — not yet located; `selectItem()` and
   `winMsgCtrlYesNo` are the entry points to trace.
3. **`ServerWork[7]` values other than 2** — only the `== 2` branch is
   characterised. Non-2 must be treated as "use the ordinary msgvar".
4. **Link-battle branch of `msgctrlAttackMons`** — composes via message
   `0x4FE4`; irrelevant to single-player but must not crash the decoder.
5. **Whether an unsent party slot's HP reads 0** — carried over from
   2026-07-30, still unresolved, still blocks a "Pokémon remaining" count.

---

## 10. Provenance

- `msgctrlcode` dumped from `xd-decomp/orig/GXXE01/sys/main.dol` at file
  offset `0x401710` via the DOL section table; every handler address matched
  a named symbol in `config/GXXE01/symbols.txt`.
- `r13` (`_SDA_BASE_`) derived as `0x804EFE20` from
  `lwz r30, -0x4C24(r13)` resolving to `_ATTACK_MONS = 0x804EB1FC`; used to
  resolve `ServerWork` and `get_exp_fight_pokemon_ptr` from their `@sda21`
  displacements.
- Message templates and opcode sets come from the running game's own
  `fight_common` table as recorded by the narrator, not from any external
  script dump.
