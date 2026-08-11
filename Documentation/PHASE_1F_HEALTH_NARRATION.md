# Phase 1F Settled Health-Loss Narration

## Implementation attribution

The Phase 1F production module, lifecycle integration, focused tests, and this phase document were implemented by **Codex (OpenAI)** on 2026-07-25. The exact file-level scope and exclusions are recorded in [IMPLEMENTATION_ATTRIBUTION.md](IMPLEMENTATION_ATTRIBUTION.md). Codex does not claim the earlier discovery PoCs or work performed by other collaborators.
## Status

Phase 1F is complete. The generic production health module passes the complete automated suite and the bounded production regression confirmed both ordinary move damage and indirect poison damage through the same reconstruction pipeline.

This distinction is intentional:

- **Live confirmed:** the Phase 1F PoCs observed direct HP loss through the verified battle structures and status-window animation data.
- **Automated confirmed:** production integration and its safety behavior pass 59 tests, including nine focused health tests.
- **Production live confirmed:** Earthquake reduced Metagross from 140 to 0 HP and produced `Metagross lost 100 percent. zero percent remaining.`
- **Indirect live confirmed:** poison reduced Salamence from 23 to 4 HP and produced `Salamence lost 12 percent. 3 percent remaining.`
- **Not required:** no further battles will be repeated solely to force poison damage. Poison was useful during discovery, but production narration is cause-free and event-agnostic.

Pokémon XG remains untested. Every address below is restricted to the verified vanilla US XD profile, `GXXE01`, revision 0.

## User-facing behavior

After a uniquely matched HP animation reaches its final logical HP and remains settled for two consecutive 50 ms samples, NVDA speaks a generic sentence:

`Salamence lost 50 percent. 50 percent remaining.`

The companion does not guess whether the loss came from a move, poison, recoil, weather, or another cause. Battle messages continue to announce causes where the game itself supplies them.

Percentage rules are deterministic:

- round-half-up, rather than Python banker’s rounding;
- a positive amount that rounds to zero is spoken as `less than one percent`;
- an actual zero is spoken as `zero percent`;
- zero remaining is explicitly spoken;
- healing is currently silent and only updates the verified baseline after settling.

Health speech uses the battle-event class without interrupting the GSmsg sentence already being spoken.

## Verified GXXE01 structure chain

The production reader enumerates exactly eight active-battler slots from:

- `FightFloor`: `0x804A1730`
- active-battler array: `FightFloor + 0xDE44`
- slot count: `8`
- slot entry: aligned `FightOutPokemon*`
- `FightOutPokemon + 0x04`: aligned `FightPokemon*`
- embedded `Pokemon`: `FightPokemon + 0x04`
- current HP: embedded `Pokemon + 0x04`, big-endian `u16`
- maximum HP: embedded `Pokemon + 0x90`, big-endian `u16`
- nickname: `FightPokemon + 0x52`, null-terminated big-endian GSchar, maximum 11 characters

A battler’s identity is the complete tuple of slot index, `FightOutPokemon` pointer, `FightPokemon` pointer, and embedded `Pokemon` address. A slot or allocation address alone is never treated as identity.

The status-window list is reconstructed on every poll:

- window manager: `0x80445A68`
- list head: manager `+0x10`
- maximum nodes: `64`
- node size: `0xBC`
- next pointer: node `+0x10`
- allocation pointer: node `+0xB8`
- animation work: node `+0xA8`
- old HP: work `+0x00`, big-endian signed 16-bit
- duration: work `+0x02`, big-endian signed 16-bit
- progress: work `+0x04`, big-endian signed 16-bit
- copied nickname: allocation `+0x00`, bounded GSchar
- maximum HP: allocation `+0x18`, big-endian signed 16-bit
- target HP: allocation `+0x1A`, big-endian signed 16-bit

The old experimental addresses `0x804454B4` and `0x804454BC` are rejected as production hooks. They were useful historical observations but are not stable battler identity or ownership sources.

## Acceptance and settling rules

An HP event is eligible only when all of the following hold:

1. The logical battler identity has a prior baseline.
2. The current HP differs from that baseline.
3. Exactly one current status window matches normalized copied nickname, maximum HP, target HP, and old baseline HP.
4. The status target equals the logical battler’s current HP.
5. Animation duration is zero.
6. The same settled state is observed in two consecutive 50 ms samples.

Window and allocation pointers may change while an event is pending. They are reconstructed and logged, not retained as identity. Zero matches wait for a bounded remap interval; multiple matches suppress the event rather than guessing. Pointer, range, capacity, list-cycle, impossible-HP, or malformed-string failures suppress or reset only health tracking and do not stop menu focus or GSmsg narration.

Multiple HP changes before settlement are grouped from the original baseline to the final target. Simultaneous battlers are tracked independently. Once an event settles, the baseline advances exactly once, preventing duplicate speech.

## Production implementation

- `Companion/battle_narrator/health.py` contains the separate read-only memory source, tracker, percentage composition, and production speech adapter.
- `Companion/battle_narrator/profile.py` centralizes the verified GXXE01 addresses, offsets, bounds, and settling policy.
- `Companion/battle_narrator/phase1b_lifecycle.py` constructs and clears health state with battle lifecycle transitions and isolates health read failures.
- `Companion/battle_narrator/phase1b_app.py` wires the module into the persistent production narrator.
- `Companion/battle_narrator/speech.py` permits non-interrupting battle-event delivery for health announcements.

All access remains read-only through `dolphin_memory_engine`. No game-memory writes, patches, GDB watchpoints, or packaged extracted game data are used.

The confirmed diagnostics remain unchanged:

- `Companion/phase1f_hp_damage_poc.py`
- `Companion/phase1f_hp_poison_separation_poc.py`
- their corresponding UTF-8 logs under `Companion/logs/`

## Automated verification

The full `unittest` suite now passes: **67 tests**, including the later manual HP-summary integration.

The nine focused Phase 1F tests cover:

- two identical settled samples;
- refusal to speak during animation;
- dynamic window/allocation reconstruction;
- ambiguous-match suppression;
- battler replacement and re-baselining;
- multi-hit grouping to the final target;
- silent healing settlement;
- round-half-up and edge wording;
- independent simultaneous battlers.

The pre-existing 50 tests continue to cover GSmsg task handling, message resolution, lifecycle recovery, menu narration, speech ordering, disconnection, and structural validation.

## Completed production regression — 2026-07-25

The bounded live pass succeeded without adding healing or another narration category.

### Indirect poison event

- Logical battler: Salamence
- HP: `23 → 4 / 155`
- Status window: `0x80874DE0`
- Allocation: `0x8099D500`
- Animation: old `23`, target `4`, duration `12 → 0`
- Settlement: two consecutive duration-zero samples
- GSmsg speech: `Salamence is hurt by poison!`
- Health speech: `Salamence lost 12 percent. 3 percent remaining.`
- Result: the same reconstruction pipeline correctly reports indirect HP loss.

### Ordinary Earthquake event

- Logical battler: Metagross
- HP: `140 → 0 / 140`
- Status window: `0x80874E9C`
- Allocation: `0x8099D560`
- Animation: old `140`, target `0`, duration `100 → 0`
- Settlement: two consecutive duration-zero samples
- GSmsg speech: `Salamence used Earthquake!` followed by `It’s super effective!`
- Health speech: `Metagross lost 100 percent. zero percent remaining.`
- Result: ordinary move damage remained correct and produced exactly one settled loss announcement.

During the same session, the user identified that `Pokémon` and `Item` focus labels were reversed. The centralized production order was corrected to `Fight, Item, Pokémon, Call`, and all 59 tests passed afterward.

A naturally observed faint template using unverified opcode `0x10` remained suppressed. It was not implemented because new narration categories were outside this slice.

## Manual HP summary extension

The completed settled-loss pipeline was extended with a foreground-only `Control+Shift+H` live summary without adding a new automatic narration category. See [BATTLE_HP_SUMMARY.md](BATTLE_HP_SUMMARY.md). The post-hotkey poison regression reduced Salamence from `24 → 5 / 155`, spoke one settled 12-percent loss, and the subsequent summary correctly reported 5 HP and poisoned status.
