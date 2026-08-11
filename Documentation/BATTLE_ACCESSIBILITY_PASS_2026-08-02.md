# Battle accessibility pass ? 2026-08-02

## Implemented

- Ordinary Story-mode target selection (menu ID 92) reads `_target_fight_pokemon_ptr` (`0x804EA650`) and matches it to the verified active-battler array. It announces the highlighted Pok?mon and ownership without guessing cursor geometry.
- Move focus now includes PP, elemental type, power or status classification, and accuracy. These fields come from `common.rel`'s authoritative `0x38`-byte move records.
- Battle stat stages are read from each active `FightOutPokemon + 0x7B0` through `+0x7B6`, converted from the game's neutral-centered 0?12 representation to minus 6 through plus 6, and compared between samples. Resulting-stage narration therefore covers Leer, Growl, and other boosts/drops independently of transient message buffers.
- Active Pok?mon EXP totals are compared between samples; positive deltas announce the exact EXP gained.
- Money is continuously sampled through the already verified Hero money field. Positive deltas announce amount received and resulting total; decreases remain silent.
- Opponent personal name is read from side 1 trainer 0's embedded Hero name, following `fightTrainerGetNamePtr` ? `fightTrainer_GetHeroPtr` ? `heroGetStatus(1,0)`. Challenge, single send-out, and victory messages use it when available and retain safe generic fallbacks.
- Double send-out messages 20305 and 20313 use the appropriate trainer party's first two populated records. Historical live logs prove those records held the exact four Pok?mon displayed for the relevant battles even while transient actor globals were null.
- Post-battle NPC speech continues through the general dialogue reader and scripted-speaker-name resolver; it is not battle-message text and should not be duplicated in the battle narrator.

## Ctrl+Shift+H ownership result

The active array alternates ownership by raw slot: player 0, opponent 1, player 2, opponent 3. The hotkey intentionally reorders it to `0, 2, 1, 3`, so the spoken first and second Pok?mon are the player's and the spoken third and fourth are the opponent's. This is regression-tested.

## Explicit remaining live check

Trainer personal names now have a verified runtime route. Trainer class/prefix has a statically traced route through `fightTrainerGetPrefixNamePtr`, the trainer-kind table, and `GSmsgGetGSchar`, but the final pollable mapping from the current trainer data ID to kind ID has not been live-verified. The implementation therefore says `Eddy wants to battle` rather than guessing `Cool Trainer Eddy` until a live battle is available for validation.

Move archives from the project owner's disc were also inspected. XD's battle/summary menu resources do not provide a canonical per-move prose-effect table through the extracted sources used here, so menu narration gives a concise description made exclusively from verified type/power/accuracy properties rather than importing unverified prose.

## Verification

653 automated tests pass. Live battle verification remains pending because Dolphin had no battle windows open during this pass.
