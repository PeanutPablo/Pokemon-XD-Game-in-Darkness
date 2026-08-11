# PC and Purify Chamber research

Citation convention as elsewhere in this project: **Confirmed** (read
directly from code or live memory), **Inferred**, **Unknown**. Everything
below marked Confirmed was derived static-first from `xd-decomp`'s
`config/GXXE01/symbols.txt` plus PowerPC disassembly of
`build/GXXE01/main.elf`, then checked against live memory where a live
check was possible (2026-08-05, GXXE01 revision 0).

---

## 1. PC

### 1a. Menus (Confirmed live, 2026-08-02)

- Main PC window: menu ID `122`, three wrapping choices.
- Pokémon Storage action window: menu ID `123`, four wrapping choices.
- Opening a box creates windows `138, 130, 128, 132, 133, 135, 136, 137, 227`.
- Item Storage reuses the Bag category window, menu ID `44`.
- Box-grid cursor: `pMenuPokemonLeave` is at `0x804EA870`; the active
  object points at its cursor through `+0x37F0`, and the selector is the
  big-endian word at cursor `+0x0C`. The current box is object `+0x03E0`.
  Indices 4-9 are party slots and 10-39 are the 30 box slots (six columns
  by five rows). The picked-up Pokémon lives at cursor `+0x20`.

### 1b. Where box Pokémon actually live (Confirmed, `PCBOX::getPokemon` 0x80156AB0)

The earlier note that "box Pokémon use the party structure, 0xC4 bytes,
30 slots per box, 8 boxes, 0x14-byte box header" is correct, and the
addressing is now pinned exactly:

```
pcbox = savedataGetStatus(savedata, 3)      -> savedata + 0xAD0
if not 0 <= box  < 8:  return NULL
if not 0 <= slot < 30: return NULL
return pcbox + box*0x170C + 0x14 + slot*0xC4
```

`0x170C == 0x14 + 30*0xC4` exactly, so header, stride and capacity are
self-consistent. The same `savedataGetStatus` jump table (`.rodata`
`0x8040C4F8`, 29 entries) gives section 2 as `savedata + 0x140`, which is
already `profile.hero_offset` — an independent check that the table was
read correctly. Box **names** are the GSchar string in each box's 0x14
header, i.e. at `pcbox + box*0x170C`.

`pcboxGetNbPokemonBox` (`0x801570C0`) returns a literal 8.

### 1c. Box-cell speech order (2026-08-10)

For an occupied box cell, the narrator now speaks the Pokemon's decoded
nickname first, followed by box/row/column/slot coordinates and level. This
does not alter or duplicate any data source; it only changes composition order
so the changing identity is heard before repeated grid context. Empty cells
retain coordinates first because there is no Pokemon name to lead with.

Regression example: `TODD, Box 1, row 2, column 1, slot 7, level 31.`
The targeted PC suite has 11 passing tests; the complete suite has 1,353.

> **Bug this fixed.** `pc_menu.py` previously read box cells as
> `party_source._decode_slot(obj + 0x3718, slot)`. That method's second
> argument is only an error label — it does no addressing — so all thirty
> cells decoded the same address and the reader announced one Pokémon for
> every cell in the box. Regression test:
> `tests/test_pc_menu.py::PCBoxAddressingTests`.

---

## 2. Purify Chamber

Local `relivehall_menu.fsys` message table: IDs `53519`-`53601`. Labels
confirmed straight from the game: nine SETs chosen with L and R;
`PC/PARTY POKéMON`, `SET`, `TEMPO`, `PURIFY`, `FLOW`, `SHIFT`, `Cancel`;
Pokémon actions `EXCHANGE`, `ROTATE`, `SUMMARY`, `PLACE`, `MOVE`,
`CANCEL`; rotation choices `DIRECTION`, `OK`, `CANCEL`. X toggles between
the white menu cursor and the yellow direct-place cursor. The Chamber can
open the familiar PC interface while choosing Pokémon.

The engine's own vocabulary differs from the manual's and is worth
knowing when reading symbols: a SET is a **stage**, the centre Shadow
Pokémon is the **visitor**, the surrounding regular Pokémon are
**dancers**, and a type matchup is an **aisyou** (相性).

### 2a. Stored state (Confirmed, `CReliveHall`/`CReliveStage`)

```
CReliveHall  = savedata + 0x1D690          (savedataGetStatus case 21)
getStage(i)  = base + i*984                 9 SETs
CReliveStage (984 bytes):
    +0x000  dancer[0]   196-byte Pokemon record
    +0x0C4  dancer[1]
    +0x188  dancer[2]
    +0x24C  dancer[3]
    +0x310  visitor     the Shadow Pokemon
    +0x3D4  facing      signed byte: which dancer position it faces
```

`getDancerQuantity` (`0x8028E61C`) stops at the **first** empty slot
rather than scanning all four, so occupied positions are always a
contiguous run from 0. This matters: Tempo pairs positions by index, so
treating a gap as skippable would pair the wrong Pokémon together.

### 2b. Tempo (Confirmed, `CReliveStage::getTempo` 0x8028DB78)

```
tempo = _tempoBase[count]
for i in 0..count-1:
    level = matchup(dancer[i], dancer[(i+1) % count])
    tempo += _tempoNormal[count]  if level == 1
             _tempoGood[count]    if level in (2, 3)
             0                    if level in (-1, 0)
             <previous pair's contribution>  otherwise   # engine quirk
```

Live table values: `_tempoBase` (`0x8041A7B0`) `[0, 5, 14, 27, 48]`,
`_tempoGood` (`0x8041A7C4`) `[0, 6, 6, 6, 12]`, `_tempoNormal`
(`0x8041A7D8`) `[0, 2, 2, 2, 4]`. Maximum Tempo is therefore
`48 + 4*12 = 96`.

With one dancer, `(i+1) % 1 == 0`, so it is compared against itself.

The on-screen bar shows three levels (`relivehallTempoToLevel`
`0x8003AAA4`): `<= 26` low, `<= 53` medium, else high.

### 2c. Matchup level (Confirmed, `reliveHallPokemonToAisyou` 0x8028C5A8)

Best of the four pairings between two Pokémon's type slots. For each
pair, `zokuseiBiosGetWazaJoutai` (`0x80117B28`) reads

```
u16 at zokusei_data + attacker*0x30 + 0x0C + defender*2
```

and that "state" is looked up in `jyoutai2levelTbl` (`0x804E8698`, four
u16, live `[67, 66, 63, 65]`); the engine takes `max(index - 1, 0)`, so
four states collapse to three levels (0, 0, 1, 2). A state not in the
table yields the sentinel 123. `-1` means one of the two Pokémon is
absent.

**Quirk, reproduced deliberately:** if *both* type ids are 0 (both pure
Normal) the engine short-circuits to level 2 without consulting the chart
at all.

Species types are two `u8` at `pokemon_data + id*0x124 + 0x30`. A
single-typed Pokémon stores the same id twice. Type ids are the ordinary
Gen 3 ones — confirmed live against the owner's own party (Houndour read
as Dark 17 / Fire 10, Baltoy as Ground 4 / Psychic 14).

### 2d. Flow (Confirmed, `CReliveStage::getPassionWoBonus` 0x8028DDBC)

```
if no visitor: 0
tempo = <as above>
if tempo == 0: 0
faced = dancer[facing]                      # NULL if that position is empty
flow  = int(tempo * multiplier[matchup(visitor, faced)])
```

The multipliers are three `.rodata` floats at `0x802FAD00`: `[1.0, 1.5,
2.0]`.

**Cross-check that validates the whole port:** maximum Tempo 96 times the
largest multiplier 2.0 is exactly **192**, which is the literal
`CReliveStage::isBonusGet` (`0x8028E1E8`) compares `getPassionWoBonus()`
against to decide a SET is perfect. Two independent paths, same number.
Guarded by
`tests/test_purify_chamber.py::FlowTests::test_perfect_set_reaches_the_engines_own_bonus_threshold`.

**Tempo confirmed live, term by term (2026-08-06)** against a real SET in
the project owner's own game — not just as a total, but pairing by pairing:

| Adjacent pair | Types | Level | Contributes |
|---|---|---|---|
| TODD → BEAUTIFLY | Ground/Rock → Bug/Flying | 2 | +12 |
| BEAUTIFLY → OBAMA | Bug/Flying → Rock/Ground | 1 | +4 |
| OBAMA → FAT | Rock/Ground → Grass | 1 | +4 |
| FAT → TODD | Grass → Ground/Rock | 2 | +12 |

`_tempoBase[4]` = 48, plus 32, gives **80**, which is what the model
returns. Every level matches real type effectiveness (Rock is
super-effective on Bug and Flying; Grass on Ground and Rock; the rest
neutral), so this exercises the chart lookup and the level mapping, not
just the arithmetic. A separate earlier arrangement of the same four
Pokemon read the maximum 96.

**Flow remains verified by construction only.** The project owner had no
Shadow Pokemon available to place, and Flow is identically 0 without one,
so the multiplier path has never run against live data.

### 2e. Perfect-SET bonus (Confirmed)

`getPassion` (`0x8028E248`) = `getPassionWoBonus()` plus, when
`isBonusGet()`, `_bonusStageBonusTbl[getReliveGiveStageQuantity()]`.

- `isBonusGet` = `isPokemonZokuseiAllUnique(stage, includeVisitor=true)`
  **and** `getPassionWoBonus() == 192`.
- `getReliveGiveStageQuantity` (`0x8028D1AC`) counts how many of the nine
  SETs have all-unique types **and** Tempo exactly 96 — the game's own
  definition of a BEST CIRCLE.
- `_bonusStageBonusTbl` (`0x8041A7EC`), live `[0, 0, 1, 5, 10, 15, 25,
  35, 50, 100]`.

In `isPokemonZokuseiAllUnique` (`0x8028DA0C`) a dual-typed Pokémon claims
both types; a single-typed one claims only one, because the engine stops
when the second stored id repeats the first.

### 2f. Live edit screen (Confirmed statically; **awaiting one live pass**)

`pMenuReliveHall` = `0x804EA7F4` (`CMenuReliveHall*`, non-zero only while
the edit screen is open); `_lastViewStage` = `0x804EA7F8`.

```
+0x338     current SET index          (setStage, 0x800405E8)
+0x33C     CReliveStage* for it
+0x80F64   "catch" object             (getCurrentPokemonPointer, 0x800406F4)
    +0x0C  cursor position: 0-5 outer ring, 6 centre
    +0x20  the picked-up Pokemon, if any
```

Cursor positions 0-5 ring the circle but only the first
`getDancerQuantity()` hold a Pokémon; the rest are the empty markers the
game draws where another could go (`_markerDancerEmptyDirTbl`,
`0x8032E674`). The circle's angles per dancer count live in
`_markerDancerOnDirTbl` (`0x8032E5D4`) — e.g. two dancers sit at 0 and π,
three at 0, 2π/3, 4π/3, four at π/4, 3π/4, 5π/4, 7π/4.

**Status (updated 2026-08-06): confirmed live with the screen open**, with
one correction.

Confirmed by watching the fields move while the project owner used the
screen:

- `+0x338` SET index — reads the selected SET.
- `+0x33C` stage pointer — read `0x80496970`, which is **exactly** the
  address `PurifyChamberModel` computes for that SET independently from
  `savedata + 0x1D690 + index*984`. Two derivations, same address: this
  cross-validates the `CReliveHall` base offset and the menu field at once.
- `+0x80F64` catch object, `+0x20` carried Pokémon — tracked a real
  pick-up/swap sequence (`OBAMA` → `TODD` → `BEAUTIFLY`) correctly.
- Window IDs while open: `[218, 103, 113, 114, 136, 118, 207, 227]`. The
  last seven are exactly the game's own `localWindowTable`
  (`0x8032E748`), independently confirming that table.

- `+0x338` SET index also confirmed **changing** with L/R (`SET=0` → `SET=1`).

**The cursor model, resolved from the game's own data.** `+0x0C` was
documented as "0-5 outer ring, 6 centre" from `getCurrentPokemonPointer`'s
branches. Live sampling saw **0,1,2,3,4,5,7,8** and never 6, which looked
like a contradiction. It is not: `_cursorPositionTblDefault` (`0x8032E6B4`)
is the cursor's SCREEN position per index on a 640x480 display, and it
decodes cleanly as `u16` pairs —

| Index | Screen | Meaning |
|---|---|---|
| 0-5 | `-1` | computed at runtime: the ring, which moves with dancer count |
| 6 | (320, 280) | horizontal centre, upper area — the Shadow Pokémon slot |
| 7 | (198, 428) | bottom row, far left |
| 8 | (539, 428) | bottom row, far right |

`_cursorPositionTblAddPc` (`0x804E7F28`) inserts (336, 428) and (379, 428)
between them when the PC option is available. So 6 really is the centre;
it simply was never a valid stop in the sampled sessions, which had no
Shadow Pokémon placed and none being carried.

**Still open: which bottom-row index is which button.** The screen's
bottom-row text includes `PC/PARTY POKéMON` (53539), the SET buttons
(53532/53533) and `Cancel` (53538), but the index-to-label mapping is not
confirmed. The reader therefore announces the *position* ("Bottom menu, far
left"), which the coordinate table makes true, rather than guessing a label
— naming the wrong button would send the player out of the screen they are
trying to use. `BOTTOM_ROW_DESCRIPTIONS` in `purify_chamber.py` is where a
confirmed label goes, and a test guards against a guess being filled in.

### 2g. Action popup (Confirmed, six `.data` tables)

Each is `{count, message id...}`; which one opens depends on whether a
Pokémon is being carried, whether the cursor is on the centre, and
whether the target is occupied:

| Table | Address | Options |
|---|---|---|
| `actionMenuOnDancer` | `0x8032E7E0` | MOVE, SUMMARY, CANCEL |
| `actionMenuOnVisitor` | `0x8032E7C8` | MOVE, ROTATE, SUMMARY, CANCEL |
| `actionMenuCatchDancerOnNone` | `0x8032E7B0` | PLACE, SUMMARY, CANCEL |
| `actionMenuCatchVisitorOnNone` | `0x8032E798` | PLACE, ROTATE, SUMMARY, CANCEL |
| `actionMenuCatchDancerOnPokemon` | `0x8032E780` | EXCHANGE, SUMMARY, CANCEL |
| `actionMenuCatchVisitorOnPokemon` | `0x8032E768` | EXCHANGE, ROTATE, SUMMARY, CANCEL |

Message IDs: 53521 EXCHANGE, 53522 ROTATE, 53523 SUMMARY, 53524 CANCEL,
53525 PLACE, 53526 MOVE — resolved through `RuntimeMessageCatalog`, so no
label is typed into the narrator.

---

## 3. Message substitution (Confirmed, `msgctrlcode`)

Relevant to the Chamber because the purification notices go through it,
and to everything else that shows an info window.

Shipped strings are templates: `<FFFF>0x32 opened the door to its heart!`
`GSmsgMakeGScharStr` (`0x80105FEC`) walks the string and, on the `0xFFFF`
escape, indexes `msgctrlcode` — a 111-entry, 8-byte-stride dispatch table
whose pointer is at `[[0x804E8348] + 0x24]` (installed once by
`pokecoloMain` from `.data:0x80404710`). Entry layout: `u8 flags` at
`+0x00`, `u32 handler` at `+0x04`. Flag bits 6-7 select the mode:

- **0** — pure formatting; contributes no text.
- **1** — handler returns a pointer to GSchar text, spliced in directly.
- **2** — handler returns another message ID, looked up and spliced in.

Every mode-1/mode-2 handler is a small accessor over one global in the
msgvar block at `0x804EB278`-`0x804EB2CC` (`_Pokemon`, `_Item`, `_Digit`,
`_Money`, `_PokemonID`, `_Waza`, …), which the running script writes via
`Dialogs::setMsgVar` immediately before requesting the box.

Name lookups used by the mode-2 handlers (note the counts are a **double**
indirection and the bases a single one — reading both the same way
silently breaks every lookup):

| What | Count | Base | Stride | Name ID at |
|---|---|---|---|---|
| Species | `[[0x804EA634]]` | `[0x804EA638]` | `0x124` | `+0x18` |
| Move | `[[0x804E87F0]]` | `[0x804E87F4]` | `0x38` | `+0x20` |
| Type | `[[0x804E87C8]]` | `[0x804E87CC]` | `0x30` | `+0x08` |
| Item | `[[0x804E8A00]]` valid, `[[0x804E8A08]]` dense | `[0x804E8A04]` index, `[0x804E8A0C]` records | `0x28` | `+0x10` |

All four confirmed live: species names, move names (1 POUND, 85
THUNDERBOLT) and types all resolved correctly against the owner's own
party.

`message_render.py` transcribes the dispatch table and re-checks it at
runtime (`verify_dispatch_table`), so a build that relocated the handlers
reports a mismatch rather than silently substituting the wrong variable.

### 3a. Purification notification messages

The ceremony text lives in the Relic Stone map's own table
(`M3_shrine_1F` / `hologram_menu`), so it resolves only while that map is
loaded — which is exactly when it is shown.

| ID | Template |
|---|---|
| 50502 | There's a POKéMON that may open the door to its heart! |
| 50503 | `<Pokemon>` opened the door to its heart! |
| 50504 | `<Pokemon>` regained `<Quantity>` EXP Points! |
| 50505 | `<Pokemon>` obtained a RIBBON! |
| 50506 | Would you like to give a nickname to `<Pokemon>`? |
| 50507 | It cannot be used now. |
| 50508 | The door to that POKéMON's heart isn't closed. |
| 50509 | The door to that POKéMON's heart can't be opened yet. |
| 50510/50511 | `<Pokemon>` regained the move `<Move>`! |

Always-resident (`main.dol`): 16001/16002 purify-ready notices, 50023
level-up, 50201-50203 evolution, 50459 and 54001-54009 acquisition.

> **What this replaced.** These were previously spoken as typed-in English
> keyed on message ID — 50503/50510/50511 all collapsed to one generic
> "Purification ceremony results for X", discarding the EXP total and the
> regained move, i.e. the entire content of the screen; 50502 and
> 50507-50509 were not covered at all. They now render the game's own
> text. See `menus.progress_notification_focus` and
> `profile.progress_notification_message_ids`.

---

## 4. Still open

- **Awaiting live confirmation:** the `CMenuReliveHall` offsets in §2f,
  with the edit screen actually open.
- **Unknown:** how cursor positions 0-5 map onto the drawn circle when
  fewer than four dancers are present — `makeCursorPositionTbl`
  (`0x8003FCC4`) and `cursorPositionDecideAtStageChange` (`0x8003F998`)
  build that table per SET and have not been decoded.
- **Not implemented:** the ROTATE sub-dialogue (`DIRECTION`/`OK`/`CANCEL`,
  53528-53530) is not narrated as its own widget yet, though the facing
  it changes is reported in the SET summary.
