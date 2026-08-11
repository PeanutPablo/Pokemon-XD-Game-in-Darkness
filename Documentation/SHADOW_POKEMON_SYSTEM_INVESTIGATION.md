# Shadow Pokémon system investigation

**Date:** 2026-08-03  
**Scope:** research and documentation only; no production accessibility code changed.

## Executive result

XD uses three linked representations: an ordinary 0xC4-byte `Pokemon` with a `u16` Shadow-data ID at `+0xBA`; static `_deckDarkPokemon` design records (stride 0x18); and persistent save-relative `DarkPokemon` state records (stride 0x48).

The active predicate is not merely `pokemon+0xBA != 0`. `Pokemon::isDarkPokemon()` requires a nonzero ID and a false purified flag; the ID may persist after purification.

The Heart Gauge counts down from static initial Dark Point (`deck[id]+0x08`) to persistent current Dark Point zero (`savedata+0xE380+id*0x48+0x24`). The existing `(initial-current)/initial` percent-open direction is correct. Teddiursa's prior `0/3000` read is prior live evidence, not a new independent test in this pass.

## Confirmed lifecycle

- `Pokemon::getDarkpokemonDataID()` reads `u16` at `+0xBA` (`pokemonStatusPokemon.s`, `0x8014B394`).
- `darkPokemonGetDarkPokemon()` selects savedata kind `0xF`, bounds ID below `0x80`, and returns `base+id*0x48`.
- Status values: 0 not seen; 1 seen as spectator; 2 seen in battle; 3 caught; 4 purified (`XGScriptClassFunctionsData.swift`, `XDSExpr.swift`).
- Engine counters use status >0 for met, >=3 for snag success, and ==4 for purified.

| State | ID | Status | Active? |
|---|---:|---:|---|
| Ordinary | 0 | n/a | No |
| Encountered | encounter-specific | 1 or 2 | Context-dependent |
| Snagged | nonzero | 3 | Yes |
| Purified | may remain nonzero | 4 | No |

## Gauge, moves, and Reverse Mode

Nature data supplies separate multiplier indices for battling, walking, calling out of Reverse Mode, Day Care, and Cologne massage. A walking accumulator exists. Exact arithmetic, threshold values, and multiplier values remain unknown.

Static record `+0x0C..+0x12` contains four `u16` Shadow move overrides. Ordinary `Pokemon+0x80` move records retain restored moves. Nonzero override replaces its corresponding slot; zero uses the ordinary slot. Prior Teddiursa evidence was ordinary `{216,287,122,232}`, overrides `{356,369,0,0}`, yielding Shadow Blitz, Shadow Mist, Lick, Metal Claw.

The local extraction has 375 move records, usable Shadow IDs 356–373, and locked placeholder 374. All usable records store type byte 0, so Shadow behavior is applied by engine logic; type byte 18 is not a valid detector here.

Reverse Mode is a packed persistent flag at `DarkPokemon+0x01` (conventional mask appears `0x40`). Aggression is static `+0x14`. Exact probability/transitions remain unknown. XG patch comments mention Aura Stabiliser preventing Reverse Mode, but comments do not prove the installed image contains that patch.

## Purification and rewards

Status 4 is purified; stored EXP and pooled friendship are distinct persistent values; ordinary move slots contain restored moves. Exact Relic/Purify Chamber message sequence, move restoration, ribbon, EXP/levels/stats, and XG reward differences require controlled live capture.

## XD versus installed XG

| Area | Evidence | Result |
|---|---|---|
| ID/record chains | retail assembly + prior Teddiursa live sample | Compatible in tested session |
| Move table | local extraction: 375 records, canonical block | Confirmed local data |
| XG mechanic patches | patch-development comments/tool affordances | Candidates only |
| Aura Stabiliser | comment only | Unknown installed status |

The local assets are structurally XD-compatible. This supports data-driven narration, not a claim that runtime XG mechanics are identical.

## Accessibility boundary

Safe: ID plus purified status; bounded current/max gauge; per-slot overrides; local canonical names/descriptions; lifecycle status.

Not safe: predicted unlock time or gauge gains; probability-derived Reverse announcements; XG-only effects from comments; nonzero ID alone as active status.

## Sources

`xd-decomp` Pokémon/dark Pokémon headers, assembly and US symbols; `Pokemon-XD-Code` trainer/deck/save/nature/move/script schemas; local `common.fsys` and `dol_strings.json`.

