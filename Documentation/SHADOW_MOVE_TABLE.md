# Shadow move table

Extracted 2026-08-03 from local `common.fsys`: pointer 124, count pointer 125 = 375, stride 0x38. All usable records store type byte 0; Shadow behavior is runtime-special.

| ID | Name | Cat. | Pow. | Acc. | PP | Target | Effect | Local description |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 356 | Shadow Blitz | 1 | 40 | 100 | 5 | 0 | 0 | A Pokémon throws this tackle while casting a shadowy aura. |
| 357 | Shadow Rush | 1 | 55 | 100 | 5 | 0 | 0 | A Pokémon executes a tackle while exuding a shadowy aura. |
| 358 | Shadow Break | 1 | 75 | 100 | 5 | 0 | 0 | A shattering ram attack with a shadowy aura. |
| 359 | Shadow End | 1 | 120 | 60 | 5 | 0 | 48 | A shadowy ram attack that also rebounds on the user. |
| 360 | Shadow Wave | 2 | 50 | 100 | 5 | 4 | 0 | Shadowy aura waves are loosed to inflict damage. |
| 361 | Shadow Rave | 2 | 70 | 100 | 5 | 4 | 0 | A shadowy aura in the ground is used to launch spikes. |
| 362 | Shadow Storm | 2 | 95 | 100 | 5 | 4 | 0 | A shadowy aura is used to whip up a vicious tornado. |
| 363 | Shadow Fire | 2 | 75 | 100 | 5 | 0 | 4 | A shadowy fireball attack that may inflict a burn. |
| 364 | Shadow Bolt | 2 | 75 | 100 | 5 | 0 | 6 | A shadowy thunder attack that may paralyze. |
| 365 | Shadow Chill | 2 | 75 | 100 | 5 | 0 | 5 | A shadowy ice attack that may cause freezing. |
| 366 | Shadow Blast | 1 | 80 | 100 | 5 | 0 | 0 | A wicked blade of air formed using a shadowy aura. |
| 367 | Shadow Sky | 2 | — | 100 | 5 | 5 | 215 | Darkness hurts all except Shadow Pokémon for 5 turns. |
| 368 | Shadow Hold | 2 | — | 80 | 5 | 4 | 106 | A shadowy aura descends to prevent fleeing. |
| 369 | Shadow Mist | 2 | — | 100 | 5 | 4 | 214 | A shadowy aura sharply cuts the foe's evasiveness. |
| 370 | Shadow Panic | 2 | — | 60 | 5 | 4 | 49 | A shadowy aura emanates to cause confusion. |
| 371 | Shadow Down | 2 | — | 100 | 5 | 4 | 59 | A shadowy aura sharply cuts the foe's Defense. |
| 372 | Shadow Shed | 2 | — | 100 | 5 | 1 | 216 | A shadowy aura eliminates Reflect and similar moves. |
| 373 | Shadow Half | 2 | — | 100 | 5 | 2 | 217 | A shadowy aura's energy cuts everyone's HP by half. |

ID 355 is blank/unrelated-looking and is not exposed. ID 374 is `????`, PP 5: “This can't be used because the heart's door is shut.” It is the locked placeholder.

Target labels are inferred pending native/live tracing: 0 single target, 4 opposing side/all foes, 5 battlefield, 1 field side, 2 everyone. Runtime XG patches may alter mechanics despite the canonical XD-sized local table.

