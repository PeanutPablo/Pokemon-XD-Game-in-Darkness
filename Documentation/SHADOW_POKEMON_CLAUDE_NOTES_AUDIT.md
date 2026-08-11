# Audit of prior Claude Shadow Pokémon notes

| Prior claim | Verdict | Result |
|---|---|---|
| `Pokemon+0xBA` is Shadow ID | Correct | Direct assembly confirmation. |
| static pointer `0x804EBB60`, stride 0x18 | Correct retail baseline | Address is revision-specific. |
| four overrides at `+0x0C` | Correct | Assembly/schema/prior Teddiursa agree. |
| ordinary slots hold restored moves | Correct for sample | Teddiursa confirms per-slot substitution. |
| zero override uses ordinary slot | Correct for moves | Not sufficient for whole-Pokémon status. |
| saved `+0xE380`, stride 0x48, gauge `+0x24` | Correct | Jump table/getter confirm. |
| `0/3000` means fully open | Correct with provenance caveat | Owner-confirmed prior save; not newly retested. |
| percent `(max-current)/max` | Correct with guards | Clamp, stable snapshot, nonzero max required. |
| nonzero ID means active Shadow | Incorrect/incomplete | Purified Pokémon may retain ID. |
| overrides decide all Shadow state | Overstated | Moves only, not lifecycle/gauge/Reverse. |
| header's 60-byte body is true size | Incorrect/outdated | Assembly uses 0x48. |
| deck `GetDarkPoint` is live gauge | Incorrect | It is static initial; live is persistent `+0x24`. |
| find Shadow moves by type byte 18 | Incorrect locally | Usable records store 0; engine supplies behavior. |
| Aura Stabiliser patch is installed | Unverified | Comment only. |
| status enum unknown | Resolved | 0 unseen, 1 spectator, 2 battled, 3 caught, 4 purified. |

Implementation caution: `LocalMoveData` currently reads a `u16` PP at `+0x00`, but the record is priority `s8` at 0 and PP `u8` at 1. Priority zero masks this for Shadow moves. Type byte zero does not imply Normal-type behavior.

Unknown: exact purification formulas/thresholds; clearing routine; Reverse probability/transitions; complete packed bits; purification messages/rewards; installed XG executable deltas.

