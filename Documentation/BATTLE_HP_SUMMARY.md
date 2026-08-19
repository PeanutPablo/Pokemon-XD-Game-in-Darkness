# Manual Battle HP Summary

## Status

Implemented and live-confirmed on 2026-07-25 for verified vanilla US XD, `GXXE01` revision 0. Pokémon XG compatibility remains unverified.

The production narrator exposes a foreground-scoped manual battle-health summary. The default hotkey is:

`Control+Shift+H`

It can be changed at startup:

```powershell
python Companion/run_battle_narrator.py --hp-summary-hotkey alt+f12
```

A modifier is mandatory. Supported primary keys are letters, digits, and F1 through F12.

## Input safety

The hotkey uses Windows key-state polling but fires only when the foreground process is exactly `Dolphin.exe`. A chord pressed in another application is marked held and cannot fire merely because focus later moves to Dolphin. It must be released and pressed again while Dolphin has focus. Activation is rising-edge-only, so holding the chord produces one summary rather than repeated lines.

## Live data and stability

The summary reads current active battlers directly through the verified FightFloor chain. It does not reconstruct HP from prior damage announcements.

One press begins a two-sample transaction:

1. Read every occupied battler from the bounded eight-entry active array.
2. Select the four ordinary field positions in presentation order.
3. Wait for the next 50 ms lifecycle poll.
4. Require the complete identity, nickname, current HP, maximum HP, and major-condition tuple to be identical.
5. Speak one combined utterance, or suppress the request if anything changed.

No unused slot is spoken. Null slots are omitted. Fainted Pokémon include zero HP, zero percent, and `fainted`.

## Ownership and presentation order

**Corrected 2026-08-18.** Both the side each battler is attributed to and
the order they are spoken in are now *derived*, not read from a positional
table.

`hotkeys.BattleHPSummary._ordered` used to index
`profile.summary_slot_ownership` — a fixed `("Player", "Player",
"Opponent", "Opponent")` tuple — by active-array index. That tuple's own
comment in `profile.py` records why it cannot be trusted for this: the
2026-07-25 handoff recorded the *opposite* interleaving, and a positional
tuple cannot be correct for both. It also cannot survive the active array
compacting after a faint, which is exactly when the summary matters most —
the wrong side would be stated confidently.

Ownership now comes from `health.owner_for_battler`, which asks which
trainer's party array the battler's own `FightPokemon` record physically
sits in. That is pure arithmetic over the verified chain documented in
`BATTLE_IDENTITY_MODEL.md`, needs no extra read, and is exact. The
positional tuple survives only as `owner_for_battler`'s fallback for a
pointer that lands outside every party range, which does not happen for a
real battler.

Speaking order is derived from the same answer: **every player battler
first, in active-slot order, then every opponent battler**. For an
uncompacted field that is the same order the old tuple produced; unlike the
tuple it stays grouped by side after a replacement lands in a different
slot.

The spoken ownership labels are concise: `Player` and `Opponent`. The
double-battle layout has not yet received a dedicated live regression;
`tests/test_battle_hp_summary.py` covers the compacted-field case
synthetically, with battler pointers placed on real party-array cells so
the derivation itself is what is being exercised.

## Fields and wording

Each occupied battler includes:

- ownership;
- live nickname;
- current HP;
- maximum HP;
- round-half-up HP percentage;
- fainted state when HP is zero;
- major status when nonzero.

Major condition is read directly from embedded `Pokemon + 0x16`:

- `0`: none
- `3`: poisoned
- `4`: badly poisoned
- `5`: paralyzed
- `6`: burned
- `7`: frozen
- `8`: asleep

Unknown condition values suppress that read instead of guessing.

## Live evidence

Initial hotkey test:

`Player Salamence, 155 of 155 HP, 100 percent. Opponent Metagross, 140 of 140 HP, 100 percent.`

Post-poison hotkey test:

`Player Salamence, 5 of 155 HP, 3 percent, poisoned. Opponent Metagross, 140 of 140 HP, 100 percent.`

The post-hotkey indirect regression also confirmed:

- direct Sludge Bomb damage settled separately;
- poison application was spoken by GSmsg;
- poison reduced Salamence from `24 → 5 / 155`;
- poison HP speech was `Salamence lost 12 percent. 3 percent remaining.`;
- the later hotkey reflected live HP and poison status rather than replaying prior announcements.

## Automated verification

The complete suite passes **67 tests**. The new summary coverage includes:

- stable player-left, player-right, opponent-left, opponent-right ordering;
- single-battle empty-slot omission;
- one combined utterance per press;
- changed second-sample suppression;
- all verified major-status names;
- fainted wording;
- configurable chord parsing;
- mandatory modifiers;
- foreground-application isolation;
- held-key edge deduplication;
- lifecycle factory wiring.

## Scope exclusions

This slice did not add healing speech, stat-stage narration, abilities, weather, targets, or another narration category. Existing stat messages were preserved unchanged. Health restoration caused by reloading the save was silently re-baselined as designed.

## Attribution

Implemented by **Codex (OpenAI)** on 2026-07-25 at the project owner’s request.