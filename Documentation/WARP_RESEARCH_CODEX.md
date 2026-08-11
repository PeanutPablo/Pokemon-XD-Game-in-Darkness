# Warp source correction — Codex / OpenAI

Implementation and static analysis in this document were performed by
Codex (OpenAI), July 2026.

## Retired hypothesis

The production `WarpEntitySource` that reads roots `0x804E88F0` and
`0x804E88F4` is not an authoritative warp source. Its records contain no
room ID, destination, trigger type, or activation method. A 120-unit
distance cutoff cannot safely replace room identity. That source must not
be used for player-facing warp navigation.

## Authoritative source

Vanilla XD stores interaction points in `common.rel`:

- CommonIndexes 62: interaction-point records.
- CommonIndexes 63: record count.
- Record stride: `0x1C`.
- Activation method: byte `+0x00`.
- Current room ID: big-endian `u16` at `+0x02`.
- Collision interaction-region index: byte `+0x07`.
- Script marker: big-endian `u16` at `+0x08`.
- Script index: big-endian `u16` at `+0x0A`.

Only marker `0x0596`, script `0x04` is an ordinary warp. Marker `0x0596`,
script `0x0D` is a cutscene warp. Doors (`0x05`), elevators (`0x06`),
text (`0x0C`), PCs (`0x0E`), current-room scripts, and other common
scripts are distinct interaction types and must not be relabeled.

For ordinary and cutscene warps:

- Target room ID: big-endian `u16` at `+0x0E`.
- Target entry point ID: byte `+0x13`.

The source location comes from the current room's `.ccd`. Interactable
triangle lists are referenced by top-level entry slots `+0x2C` and
`+0x30`. Each triangle is `0x34` bytes. The interaction index is at
triangle `+0x32` for slot `+0x2C`, and triangle `+0x30` for slot `+0x30`.
The navigation position is the centroid of every vertex carrying the
record's interaction-region index.

## Owned-data validation

Read-only extraction from the project's verified USA vanilla XD image
found 832 interaction points:

- 271 ordinary warps.
- 9 cutscene warps.
- 150 doors.
- 46 elevators.
- 89 text points.
- 26 PCs.
- 241 current-room scripts.

The locally extracted collision slice produced exact matches:

- Room `0x8A`, `M5_apart_1F`: warp record 669, region 6, target room
  `0x8F`, entry 2, centroid `(0, 10, 30)`.
- Room `0x8D`, `M5_labo_2F`: warp record 701, region 9, target room
  `0x8B`, entry 1, centroid `(-80, 15, 17.5)`.

Rooms without a locally extracted CCD must return no warp entities. They
must not fall back to the disproven global-table heuristic.

Copyrighted extracted game data remains local under the gitignored
`Companion/_dialogue_extraction` tree and must not be packaged.
