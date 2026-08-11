# Phase 0I static analysis: Phase 0H control opcodes

Scope is limited to opcodes `0x0D`, `0x41`, `0x12`, `0x13`, and `0x02`.
Dolphin was closed. Phases 0D, 0F, 0G, and 0H were not modified.

## Encoded messages

All values are big-endian GSchar/control words.

### ID 20243 (`0x4F13`)

Bytes:

`FF FF 0F 00 27 00 73 FF FF 00 FF FF 0D 00 20 FF FF 0E FF FF 00 FF FF 41 00 21 00 00`

Verified representation:

```text
[Pokemon 15]'s
[opcode_0x0D] [opcode_0x0E]
[opcode_0x41]!
```

### ID 20032 (`0x4E40`)

Bytes:

`FF FF 12 00 20 00 77 00 61 00 73 00 20 00 70 00 6F 00 69 00 73 00 6F 00 6E 00 65 00 64 00 21 00 00`

Verified representation:

```text
[Pokemon 18] was poisoned!
```

### ID 20024 (`0x4E38`)

Bytes:

`FF FF 13 00 20 00 69 00 73 00 20 00 6F 00 75 00 74 00 20 00 6F 00 66 00 20 00 75 00 73 00 61 00 62 00 6C 00 65 FF FF 00 00 50 00 4F 00 4B 00 E9 00 4D 00 4F 00 4E 00 21 FF FF 02 00 00`

Verified representation:

```text
[Player Battle 19] is out of usable
POKéMON![Dialogue End]
```

## Dispatch entries

`msgctrlcode` begins at `0x80404710`; each entry is eight bytes: flags followed
by callback.

| Opcode | Entry | Flags | Callback | Backing value |
|---|---:|---:|---|---|
| `0x0D` | `0x80404778` | `0x58000000` | `msgctrlEvStrBuf0` at `0x8015426C` | pointer `_EV_STR_BUF0` at `0x804EB1F0` |
| `0x41` | `0x80404918` | `0x58000000` | `msgctrlEvStrBuf2` at `0x8015425C` | pointer `_EV_STR_BUF2` at `0x804EB1F8` |
| `0x12` | `0x804047A0` | `0x58000000` | `msgctrlTsuikaMons` at `0x80153FFC` | pointer `_TSUIKA_MONS` at `0x804EB208` |
| `0x13` | `0x804047A8` | `0x58000000` | `msgctrlMyName` at `0x80153FF4` | pointer `_MY_NAME` at `0x804EB20C` |
| `0x02` | `0x80404720` | `0x30000000` | `msgctrlKeyEnd` at `0x80154DDC` | GSmsg task control state |

`msgctrlSetValue` at `0x80155144` is the common writer into these globals.
Battle code normally calls it through `fightMsgctrlSetValue` at `0x802370EC`.

## ID 20243: Dragon Dance stat changes

`fightSeqCondChgAct` at `0x80221F98` constructs the substitutions.

1. The condition-change type is converted by
   `fightSeqCondChgActTypeToPokemonStatusId` at `0x80222484`.
2. The type indexes `AbiCntMsgTbl` at `0x802F90BC`.
3. `AbiCntMsgTbl` contains these fight-common IDs:
   `20339 HP`, `20340 ATTACK`, `20341 DEFENSE`, `20342 SPEED`,
   `20343 SP. ATK`, `20344 SP. DEF`, `20345 accuracy`,
   `20346 evasiveness`.
4. `GSmsgGetGSchar` resolves the selected ID. At `0x80222080`–`0x80222084`,
   the resulting pointer is written as msgctrl value `0x0D`, hence
   `_EV_STR_BUF0`.
5. `fightSeqCondChgActParaIdToValue` at `0x80222428` maps encoded amounts:
   `0x10 -> +1`, `0x20 -> +2`, `0x90 -> -1`, `0xA0 -> -2`.
6. For increases, `_EV_STR_BUF1`/opcode `0x0E` receives ID 20239
   (`"sharply"`) for +2 or ID 20380 (empty string) for +1.
7. `_EV_STR_BUF2`/opcode `0x41` receives ID 20240 (`"rose"`) for an
   increase. For decreases, opcode `0x0E` receives ID 20241
   (`"harshly"`) for -2 or the empty ID 20380 for -1, and opcode `0x41`
   receives ID 20242 (`"fell"`).

Therefore:

- `0x0D` is a live GSchar pointer to the stat name.
- `0x0E` is the already-verified magnitude adverb buffer.
- `0x41` is a live GSchar pointer to the direction verb.

Dragon Dance applies +1 Attack and +1 Speed. Its exact sentences are:

```text
Salamence's ATTACK rose!
Salamence's SPEED rose!
```

Phase 0H observed one ID-20243 GSmsg task allocation per Dragon Dance, not two
separate `0 -> allocated -> 0` lifetimes. The condition-change engine prepares
Attack and Speed separately, but the display slot is reused while its packed ID
remains 20243. Phase 0I must therefore watch substitution-pointer changes while
an ID-20243 task remains allocated; deduplication solely by task address and
packed ID would suppress the second sentence.

For read-only polling:

- `_EV_STR_BUF0`, `_EV_STR_BUF1`, and `_EV_STR_BUF2` are aligned four-byte
  pointer globals.
- Their targets are message-table GSchar strings and may begin at an odd byte
  address. Decode with bounded byte-pair reads and one-byte pointer alignment.
- Cross-check the live strings against locally extracted fight-common IDs:
  stat IDs 20339–20346, magnitude IDs 20239/20241/20380, and direction IDs
  20240/20242.
- Require two consecutive identical 50 ms samples of all three pointers and
  their decoded strings before speaking.

## ID 20032: poison recipient

Opcode `0x12` dispatches to `msgctrlTsuikaMons`. It reads `_TSUIKA_MONS`,
an aligned `FightOutPokemon*`, and normally calls
`fightOutPokemonGetNicknamePtr` at `0x80203548`.

The writer is `fightFloor_SetTuikakoukaPokemonPtr` at `0x801F6934`. After
validating the supplied `FightOutPokemon*`, it calls
`fightMsgctrlSetValue(0x12, pokemon)`. The additional-effect engine
`_fightSeqTuikaActSub` at `0x80213ED0` selects battle target type `0x12` and
passes that recipient to `fightFloor_SetTuikakoukaPokemonPtr`. Poison's
`WAZA_AddDoku` sequence selects message ID 20032 from `AddDokuMsgTbl`.

Thus `0x12` means the Pokémon receiving the additional effect—not generically
the current attacker or defender. During Sludge Bomb's poison application it
is Salamence.

Stable live chain:

```text
0x804EB208 (_TSUIKA_MONS)
  -> aligned FightOutPokemon*
  -> FightOutPokemon+0x04, aligned FightPokemon*
  -> FightPokemon+0x52, two-byte-aligned GSchar nickname[11]
  -> "SALAMENCE"
```

The callback's accessor provides the same nickname. The external poller can
use the already-verified Phase 0G structural chain and maximum of 11 GSchar
characters. A nickname is player-defined, so local species-name data is not an
independent exact nickname source; cross-check the two live paths
(`_TSUIKA_MONS` accessor-equivalent chain and the target's FightPokemon
nickname buffer) and log the species separately if desired.

Final sentence:

```text
Salamence was poisoned!
```

## ID 20024: local-player name and key-end behavior

Opcode `0x13` dispatches to `msgctrlMyName`, a trivial load of `_MY_NAME`.

`fightActionFlowSyuuryou` at `0x80209138` obtains:

- target type `0x0B` as the local/player `FIGHT_TRAINER*` (`r26`);
- target type `0x09` as the opposing trainer (`r31`).

It calls `fightTrainerGetNamePtr(r26)` and at `0x802092B0`–`0x802092B4`
writes the result with `fightMsgctrlSetValue(0x13, name)`. Opponent name and
prefix are written to different control slots. Consequently opcode `0x13`
unambiguously means the local player's battle-trainer name.

`fightTrainerGetNamePtr` at `0x801F93B0` follows the trainer's `Hero*`, then
calls `heroGetStatus(hero, 1, 0)`, which returns `heroBiosGetNamePtr(hero)`.
The Hero object begins with the GSchar player-name buffer. Writes use
`heroBiosSetNamePtr` at `0x8014DF40`, which calls `GScharLenCpy` with a strict
maximum of 11 GSchar characters.

Stable live value:

```text
0x804EB20C (_MY_NAME) -> GSchar player name, maximum 11 characters
```

The global is four-byte aligned; its GSchar target should be validated over
the full 24-byte bounded range and decoded from byte pairs. Because the name
is user-created, extracted static game data cannot independently supply it.
Phase 0I can cross-check `_MY_NAME` against the Hero name reached from the
local player `FIGHT_TRAINER*` if that structure pointer is retained alongside
the loss event; otherwise two identical samples plus the 11-character bound
are the safe validation.

Opcode `0x02` dispatches to `msgctrlKeyEnd`. It does not return text. It
manipulates GSmsg task bytes `+0x44/+0x45`, checks input through
`menuIsCheck(10)`, rewinds the control-stream pointer by three bytes while
waiting, and returns `1`. It is an end-of-dialogue acknowledgement/input gate.
It must be silent in NVDA output. The companion must not reproduce its input
check, pointer rewind, timing, acknowledgement, or task-state mutation; it
only omits the control and speaks the completed visible sentence once.

Final sentence:

```text
<actual player name> is out of usable POKéMON!
```

## Proposed bounded Phase 0I validation

Create a separate script derived from Phase 0H without changing Phases
0D/0F/0G/0H. Repeat only the known two-turn sequence:

1. Salamence uses Dragon Dance.
2. Metagross uses Sludge Bomb and poisons Salamence.
3. Salamence uses Dragon Dance again.
4. Metagross uses Sludge Bomb.
5. Poison damage makes Salamence faint and the player loses.

Keep GSmsg as the only event source and poll at 50 ms. For ID 20243, add a
secondary deduplication key consisting of task address plus the stable triple
of decoded `(_EV_STR_BUF0, _EV_STR_BUF1, _EV_STR_BUF2)` so Attack and Speed
are both announced within one packed-ID allocation. Require two identical
samples and local fight-common cross-validation before speaking.

For ID 20032, sample `_TSUIKA_MONS` twice, validate the aligned structures and
two-byte-aligned nickname buffer, and speak the resolved nickname. Preserve
the existing verified handling of IDs 20333, 20034, and 20021.

For ID 20024, sample `_MY_NAME` twice with the strict 11-GSchar bound, omit
opcode `0x02`, and speak the completed loss sentence once. Never perform the
key-end behavior externally.

Stop immediately after ID 20024 closes or the loss sequence is otherwise
confirmed complete. Do not test any unrelated message or opcode.
