# Shadow Pokémon memory map

US retail XD baseline; integers big-endian; addresses revision-specific.

```text
dark_id = u16(Pokemon + 0xBA)
static  = *0x804EBB60 + dark_id * 0x18
saved   = savedata_base + 0xE380 + dark_id * 0x48
active  = dark_id != 0 and saved.status != 4
```

Runtime requires `dark_id < 0x80`; that is capacity, not populated count.

## Static record, stride 0x18

| Offset | Meaning | Confidence |
|---:|---|---|
| 00 | Miror B weighting | Secondary label |
| 01 | capture-rate override | Confirmed |
| 02 | caught level | Confirmed |
| 03 | in-use flags | Partial |
| 04 | story-deck index (u32) | Confirmed |
| 08 | initial/max Dark Point (u16) | Confirmed |
| 0A | bonus/purification EXP (u16) | Field confirmed |
| 0C | four Shadow move IDs (4×u16) | Confirmed + prior live |
| 14 | aggression | Field confirmed, formula unknown |
| 15 | flee/Miror B behavior | Secondary label |

`_deckDarkPokemon` pointer is retail `0x804EBB60`; size pointer `0x804EBB70`.

## Persistent record, stride 0x48

| Offset | Meaning | Confidence |
|---:|---|---|
| 00 | packed 3-bit lifecycle status/place | Confirmed; preserve other bits |
| 01 | packed Reverse/other flags; Reverse appears `0x40` | Confirmed getter/setter; mask wording pending |
| 04 | stored EXP in upper 20 bits (`value<<12`) | Confirmed |
| 08–12 | walk/random/status counters/flags | Partial |
| 11 | additional packed place bits | Confirmed |
| 13 | snag index | Confirmed |
| 14 | original trainer ID/index (u16) | Confirmed |
| 16 | catch floor/location (u16) | Confirmed |
| 18 | pooled friendship (u16) | Confirmed |
| 1A | species ID (u16) | Confirmed |
| 24 | current Dark Point (s32) | Confirmed + prior live |
| 28 | original trainer name (10 UTF-16 units) | Confirmed |
| 3E | Shadow ID (u16) | Confirmed |
| 40–47 | unresolved tail | Unknown |

Status: 0 unseen, 1 spectator, 2 battled, 3 caught, 4 purified.

## Safe read

Validate ID/pointers, take a stable snapshot, use status for active identity, require positive initial value, and clamp `round(100*(initial-current)/initial)`. Reject implausible values. Never write.

Known retail routines: ID getter `0x8014B394`; active predicate `0x8014AEB8`; persistent lookup `0x8014BDA4`. Revalidate against ordinary, active Shadow, and purified Pokémon before production expansion.

