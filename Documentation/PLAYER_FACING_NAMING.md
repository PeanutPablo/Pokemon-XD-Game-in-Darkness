# Player-facing naming convention

**Status:** Implemented 2026-08-02.

Internal room codes and numeric IDs remain authoritative identifiers, but they are never intended to be spoken to the player. The final presentation layer translates them using these rules:

- **Named people:** the canonical in-game name, such as `Eagun` or `Jovi`.
- **Trainers:** trainer class followed by personal name when both are available, such as `Cool Trainer Eddy`. A class is never guessed when the game data has supplied only a name.
- **Unnamed people:** `Person A`, `Person B`, and so on, stable for the room visit. This is clearer in speech than a bare letter and does not invent a role.
- **Named buildings:** canonical possessive or proper name, such as `Eagun's House`, `ONBS`, or `Relic Stone`.
- **Public services:** location plus familiar service name, such as `Phenac City Pok? Mart` or `Gateon Port Pok?mon Center`.
- **Floors:** appended in natural language, such as `2nd floor` or `basement level 2`.
- **Unknown buildings:** a truthful generic description, such as `house in Agate Village`; ownership is not inferred from internal labels such as `houseD`.
- **Outdoor rooms and battle variants:** the location name only, such as `Agate Village`; suffixes such as `_out` and `_bf` are never spoken.

The translation is centralized in `Companion/battle_narrator/player_facing_names.py`. Warp, door, elevator, PC, proximity, and entity-navigation readers receive the translated room-name map while continuing to key all behavior by the original room ID.

## Current limitation

The overworld PeopleIDs table provides canonical personal names but not a verified trainer-class field. The formatter supports class-plus-name immediately when such a source is established, but current runtime code deliberately says a verified personal name alone instead of inventing a class.
