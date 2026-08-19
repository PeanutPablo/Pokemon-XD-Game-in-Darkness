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

The beacon and the routed guide (`ctrl+g` and `ctrl+n`) go quiet on their
own while you are in a conversation, and pick up again when it ends. They
are not switched off, so you keep your target and your route across a
conversation. Every beacon also goes quiet while the settings menu is open,
so the Sound library can be heard one cue at a time.

| Keys | What it does |
|---|---|
| `F1` | Open the settings menu |
| `ctrl+.` / `ctrl+,` | Next / previous nearby entity |
| `ctrl+shift+.` / `ctrl+shift+,` | Next / previous category |
| `ctrl+/` | Repeat the current entity |
| `ctrl+g` | Beacon on the selected entity |
| `ctrl+n` | Routed navigation guide to it |
| `ctrl+shift+/` | Autowalk to the selected entity |
| `ctrl+t` | Teleport to the selected entity |
| `ctrl+h` | Battle HP summary |
| `ctrl+1` – `ctrl+6` | Read party slot 1–6: name, level, HP, status, Heart Gauge, held item |
| `ctrl+s` | Heart Gauge summary |
| `ctrl+m` | Money |

## Settings menu

`F1` opens a spoken settings menu for the companion itself — beacon and
footstep volumes, which announcements you hear, and the guide distances.
Arrow keys move and change values, `H` and `shift+H` jump between the
headings (Sounds, Speech, Navigation, Hotkeys, Sound library), `enter` or
`space` flips a switch, and `escape` closes. Changes take effect
immediately and are saved, so they are still there next time you play. The
Hotkeys heading is a read-only list of every key above.

The **Sound library** heading is where you can learn the companion's
non-speech cues. Moving onto an entry tells you what that sound means —
"Item beacon: an item is lying on the ground nearby" — and `enter` plays
it. Every beacon, both navigation guides, the waypoint cue, a footstep and
the blocked-movement cue are listed, each played from the same file the
game itself uses, so what you hear here is what you will hear in play.

While the menu is open, those keys belong to the companion and are not
passed to the game, so moving through the list does not move your character.
`F1` is taken from Dolphin even when the menu is closed — in a stock Dolphin
setup it loads a save state, which is not what you want when you meant to
open settings. Nothing is taken while Dolphin is not the focused window, and
`--no-settings-menu` turns the whole feature off if you would rather keep
those keys.

Autowalk walks your character to whatever entity navigation currently has
selected. **Any movement input stops it** — nudge the stick or the D-pad and
you have control back immediately. It also stops on its own when you arrive,
when you enter a new area, when a menu or conversation opens, if it stops
making progress, or if it cannot find a walkable route in the first place.
It never guesses: if there is no real route, it says so and does not move.

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
- **Gateon Port bridge connections** appear under Exits. Their names and
  positions come from the room's collision data, and the list updates from
  the live bridge alignment so only currently connected directions appear.
- Categories with no sound of their own (such as healing spots) are
  deliberately silent rather than borrowing another category's cue.

## Credits and licence

This companion is MIT-licensed — see `LICENSE`. Beacon and footstep
sounds are the project's own, except the "Video game beeps" pack by
Freesound user Mossy4, used under CC-BY 4.0. No game data of any kind is
included. See `THIRD-PARTY-NOTICES.md`.
