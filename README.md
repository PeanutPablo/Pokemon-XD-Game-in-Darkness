# Pokémon XD: Game in Darkness

A screen-reader companion for **Pokémon XD: Gale of Darkness** and the
**XG: NeXt Gen** ROM hack, for blind and low-vision players. It runs
beside Dolphin, reads the game's state, and speaks it through NVDA.

It never writes to the game, never modifies your disc image, never sends
anything over the network, and does not patch or alter Dolphin. It only
reads.

## What it reads out

- **Battles** — move menus with type and PP, damage and HP as
  percentages, stat changes, status, faints, Shadow moves and Heart
  Gauge.
- **The overworld** — a navigable list of nearby NPCs, items, doors,
  warps, elevators, PCs and shops, with a steerable audio beacon, plus
  terrain footsteps and a routed navigation guide.
- **Menus and screens** — the bag, shops, the party list and summary,
  the PC and Purify Chamber, the P✩DA, and the title screen.
- **Dialogue** — NPC conversations, spoken per page with the speaker
  named.

## What you need before you start

1. **Windows** with **NVDA** running.
2. **Python 3.12.** Newer versions do not work: one of the required
   packages has no build for them. Get it from python.org and tick
   "Add python.exe to PATH" while installing.
3. **Dolphin** (the GameCube emulator).
4. **Your own copy of the game**, as a disc image — `.iso`, `.gcm`,
   `.rvz`, `.gcz`, `.wia` or `.ciso`. This download does not include the
   game and cannot get it for you.

## Installing

1. Extract this folder anywhere you like.
2. Run **`Setup.cmd`**. It asks for your disc image and for Dolphin,
   builds the Python environment, and reads the game data it needs.
3. Run **`Launch Accessible XD.cmd`** to play.

Setup takes a few minutes, mostly downloading packages. Everything it
creates stays inside this folder.

If you move Dolphin or your game image later, run `Setup.cmd` again.

### Why setup needs your game

The companion has to know the game's own text, item, move and collision
tables to say anything useful about it. That data is copyrighted, so it
cannot be included in this download. Setup reads it out of the copy you
already own and stores it locally, in `Companion/_dialogue_extraction`.
It is read-only: your disc image is never modified, and nothing about it
leaves your computer.

You can also do that step on its own:

```bash
Companion\.venv\Scripts\python.exe Companion\bootstrap_game_data.py --disc "D:\path\to\your\game.iso"
```

## Hotkeys

Hotkeys work while Dolphin has focus.

| Keys | What it does |
|---|---|
| `ctrl+.` / `ctrl+,` | Next / previous nearby entity |
| `ctrl+shift+.` / `ctrl+shift+,` | Next / previous category |
| `ctrl+/` | Repeat the current entity |
| `ctrl+shift+/` | Rescan what is nearby |
| `ctrl+shift+g` | Beacon on the selected entity |
| `ctrl+shift+n` | Routed navigation guide to it |
| `ctrl+shift+t` | Teleport to the selected entity |
| `ctrl+shift+h` | Battle HP summary |
| `ctrl+shift+j` | Heart Gauge summary |
| `ctrl+shift+m` | Money |

## If something goes wrong

- **"Battle narrator stopped after an error"** — usually missing game
  data. Run `Setup.cmd` again.
- **Nothing is spoken** — check NVDA is running, and that Dolphin has
  focus. The companion starts speaking once a game is loaded.
- **Setup says your Python is too new** — install Python 3.12
  alongside; Setup prefers it automatically.
- **Everything is said twice** — an older copy of the companion is
  still running. Close it and relaunch.

Details of what failed go to `Companion/logs/`.

## Known limitations

- Only the **US** release and hacks built on it are supported. Other
  regions are not.
- The **Gateon Port moving bridges** are not narrated in this build: that
  feature needs a room script that setup does not yet generate, so it
  disables itself.
- Categories with no sound of their own (such as healing spots) are
  deliberately silent rather than borrowing another category's cue.

## Credits and licence

This companion is MIT-licensed — see `LICENSE`. Beacon and footstep
sounds are the project's own, except the "Video game beeps" pack by
Freesound user Mossy4, used under CC-BY 4.0. No game data of any kind is
included. See `THIRD-PARTY-NOTICES.md`.
