# P-star-DA accessibility

## Production status

The canonical narrator reads the P-star-DA home menu, opened Mailbox
messages, the Spot Monitor summary, and the selected Shadow Monitor entry.
No additional accessibility hotkey is used.

## Source and state ownership

No player-facing PDA label, location, or Pokemon name is embedded in the
reader. PDA wording is decoded from the user's extracted `pda_menu.fsys`;
species names are resolved through the live Pokemon database and currently
loaded runtime message tables. Numeric Spot Monitor values come from the
same general flags used by `GSflagGet`.

The native `pdaitemtable` and `_menuPdaGetCurrentID` establish the actual
home selection values: 0 Shadow Monitor, 1 Strategy Memo, 2 Mailbox, 3 Spot
Monitor, and 4 Cancel. Production routes those values to game message IDs,
including Spot Monitor 15359/15363. This corrects the earlier off-by-one map.

## Mail detail

The opened Mailbox detail screen has window IDs `0x77` and `0x6F`.
`_menuScriptMailID` at `0x804EA8E4` owns the selected mail and
`_menuPdaMailOpenFlag` at `0x804EA8E8` owns its open state. The local English
catalog contains 19 authored emails as sender/subject/body triples 53001
through 53057. The narrator reads the complete selected triple and resolves
the player-name placeholder from saved data.

## Spot Monitor

`menuPdaSearcher` opens window IDs `0x77` and `0x6D`. Its draw hook renders
three `esabadata` records at `0x804E898C`, each with a food-count flag at
`+0x00` and current-species flag at `+0x0C`; the record stride is `0x1C`.
The three location names are game messages 15383-15385.

Visibility is not guessed. `_getWorldMapFlag` uses the native `@1992` table
whose three u16 indices are 15, 16, and 17. Production reads those
`worldmapXD_data` records (stride `0x24`, flag ID at `+0x04`) and only speaks
spots whose own world-map flag is active. Each visible spot is summarized
from its game-authored location, live species, and live numeric food value.

## Shadow Monitor

`menuPdaDPMonList` opens window IDs `0x77` and `0x74`. While open, `pDPMList`
at `0x804EA850` points to the list object. Its `+0x00` field is the total
entry count and `+0x50` points to the native sorted records. Records are eight
bytes; the species ID displayed for each row is the u16 at `+0x04`.

The list uses `cursorBios` slot 12 at `0x80445C10`. Production reproduces the
native logical selection as the sum of its signed row and scroll halfwords,
then reads the selected record's species and resolves its name from game data.
The result is re-announced only when the selected row/species changes.

## Validation and remaining work

Targeted PDA tests: 11 passing. Full automated suite: 1,352 passing. Tests
cover mail lifecycle/deduplication, all five corrected home selections, Spot
Monitor source values and visibility plumbing, and Shadow Monitor cursor
movement. Static provenance was checked against the GXXE01 decompilation.

Spot Monitor and Shadow Monitor have not yet been live-tested in Dolphin;
their status is implemented plus static/regression verified, not live proven.
The Mailbox list and Strategy Memo remain to be implemented.

## Signed implementation

Spot Monitor and Shadow Monitor production narration, corrected PDA-home
routing, research validation, regressions, and this documentation were
implemented by **Codex (OpenAI)** on 2026-08-10 at the project owner's request.
