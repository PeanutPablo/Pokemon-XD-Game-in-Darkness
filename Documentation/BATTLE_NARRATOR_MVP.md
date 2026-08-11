# Pokémon XD Battle Narrator MVP

## Supported edition

The address profile is exclusively for:

- Pokémon XD: Gale of Darkness
- US
- GXXE01
- revision 0

The companion checks the running GameCube disc header before polling. It stops
safely for any other game ID or revision and does not claim Pokémon XG
compatibility.

## Safety and local data

The companion uses Dolphin Memory Engine read operations only. It never writes,
patches, or injects game memory. Battle strings and move records are loaded at
runtime from the existing gitignored `Companion/_dialogue_extraction` directory.
If those files are absent, run the repository's existing extraction process
against a legally owned, verified game image.

## Supported speech

Phase 1A resolves only the behavior verified through Phase 0I:

- move announcements, message 20333;
- stat changes, message 20243, including multiple changing substitutions in one
  task allocation;
- “It's super effective!”, message 20256;
- poison application, message 20032;
- poison damage, message 20034;
- fainting, message 20021;
- battle loss with the live player name, message 20024;
- fully literal `fight_common` messages containing no control opcodes.

Messages containing other controls are logged and suppressed. Opcode names,
numbers, and bracketed placeholders are never spoken.

## Running

With Dolphin already running the verified game:

```powershell
python Companion/run_battle_narrator.py
```

The detailed UTF-8 log is written to
`Companion/logs/battle_narrator.log`.

## Pokémon XG boundary

The GSmsg task-array concept and the companion's memory validation, event
tracking, stability, logging, and speech modules may be reusable for XG.
However, every static address must be rediscovered. XG's message tables and
control-code behavior also require independent verification. No vanilla address
or decoded message behavior is assumed to transfer.

## Distribution boundary

This is a source-level MVP, not a distributable package. Distribution still
requires a clean dependency/bootstrap story, an accessible user-facing
configuration and launcher, licensing review, and testing on clean systems. No
extracted game data may be bundled.
