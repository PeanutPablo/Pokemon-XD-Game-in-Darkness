# Pokémon XD: Game in Darkness

**A screen-reader companion that makes Pokémon XD: Gale of Darkness — and
the XG: NeXt Gen ROM hack — playable without sight.**

It runs alongside Dolphin, reads the game's live state, and speaks it
through NVDA. You need Windows, NVDA, Dolphin, and your own copy of the
game. You do **not** need to install Python or anything else.

---

## 1. What this is, and how it works

Pokémon XD is a GameCube game. It was never designed to be played without
looking at it, and nothing about the game itself has been changed here.

Instead, this is a **separate program that watches the game while you
play**. Dolphin (the GameCube emulator) keeps the entire running game in
your computer's memory. This companion reads that memory — the same way a
tool that shows you a live map or a speedrun timer would — works out what
is currently on screen and around you, and says it out loud.

Three things follow from that, and they are worth understanding before you
start:

- **It never changes the game.** It does not patch anything, does not
  modify your disc image, does not alter Dolphin, and does not send
  anything over the internet. It only reads. The two exceptions are
  Autowalk and Teleport, which move your character *because you pressed
  their key*, and both announce themselves when they do.
- **It reads the game's own data, not a script someone typed in.** Item
  names, move names, room layouts, what an NPC is called, where the walls
  are — all of it comes out of your own copy of the game as you play. That
  is why setup asks for your disc image once, and why nothing here is a
  guess that goes stale.
- **You are still playing the real game.** Nothing is simplified, skipped
  or automated for you. What changes is that you can hear what is there.

---

## 2. Features

### In battle

- **Move menu** — each move with its type and remaining PP
- **Damage and health** — HP spoken as percentages as it changes
- **Stat changes, status conditions, faints** — as they happen
- **Shadow moves and the Heart Gauge** — XD's own mechanics, read out
- **How many Pokémon the opponent brought**, announced once per battle —
  what a sighted player reads off the row of Poké Balls before committing
  to a move
- **What you are aiming at** — when choosing a target, the companion says
  what that target actually *is*, not just its name
- **On-demand summaries** — party HP, Heart Gauge, and any party slot's
  full details, on their own keys

### Finding your way around

- **A navigable list of everything nearby**, grouped into categories you
  cycle through: NPCs, items, doors, exits (warps and elevators),
  interactables, Gateon Port's bridges, and hazards
- **Direction and distance** for whatever you have selected, as a clock
  bearing — "3 o'clock, distance 47"
- **A steerable audio beacon** you can lock onto something and walk toward
- **A routed navigation guide** that follows walkable ground rather than
  pointing through walls, and that tells you when it *cannot* reach
  something instead of walking you into a corner
- **Autowalk** — walks your character to the selected thing. Any movement
  input stops it instantly
- **Teleport** — moves you to the selected thing directly
- **Terrain footsteps** that change with the ground you are on, plus a
  cue when you walk into something
- **Interaction cues** — whether the thing in front of you can actually be
  interacted with right now, using the game's own rule for that
- **Key items on the floor are named.** Ordinary pickups announce as
  "Item" deliberately, because the game does not reveal what a sparkle
  holds until you take it. Progression-critical items are the exception —
  "ID Card", "Elevator Key", "Machine Part" — because those are what leave
  you stuck. New drops are announced as they appear

### Menus, screens and text

- **Dialogue**, spoken a page at a time with the speaker named
- **The bag and shops**
- **The party list and the full summary screen**
- **The PC and the Purify Chamber**
- **The PDA**
- **The title screen and pause menu**

### The companion's own settings

- **A spoken settings menu on `F1`** — beacon and footstep volumes, which
  announcements you hear, guide distances, and a full list of every hotkey
- **A Sound library** where you can play every non-speech cue the
  companion uses and be told what each one means, so you can learn them
  somewhere calm instead of mid-dungeon

---

## 3. Controls

Hotkeys work while Dolphin is the focused window. Nothing is taken from
other programs.

| Keys | What it does |
|---|---|
| `F1` | Open the settings menu |
| `ctrl` + `.` / `ctrl` + `,` | Next / previous nearby thing |
| `ctrl` + `shift` + `.` / `,` | Next / previous category |
| `ctrl` + `/` | Repeat the current selection |
| `ctrl` + `L` | Turn the repeat-when-you-stop on or off |
| `ctrl` + `G` | Audio beacon on the selection |
| `ctrl` + `N` | Routed navigation guide to it |
| `ctrl` + `shift` + `/` | Autowalk to it |
| `ctrl` + `T` | Teleport to it |
| `ctrl` + `H` | Battle HP summary |
| `ctrl` + `1` – `ctrl` + `6` | Read party slot 1–6 in full |
| `ctrl` + `S` | Heart Gauge summary |
| `ctrl` + `M` | Money |

**In the settings menu:** arrows move and change values, `H` and
`shift`+`H` jump between headings, `enter` or `space` flips a switch,
`escape` closes.

The beacon and the routed guide go quiet on their own during a
conversation and pick up again when it ends — you keep your target and
your route across dialogue.

---

## 4. This game does not hold your hand — read this before you start

**A walkthrough for Pokémon XD:**
https://gamefaqs.gamespot.com/gamecube/925945-pokemon-xd-gale-of-darkness/faqs/40528

Please treat that link as part of the setup, not an optional extra.

Pokémon XD expects you to be *looking* at it. It rarely tells you where to
go next. It assumes you noticed the door in the corner, that you remember
which building the man mentioned two towns ago, and that you can see the
one interactable thing in a room full of scenery. None of that is
something a screen reader can restore, because the game never said it out
loud to anyone — it drew it.

So: **pay attention to what people tell you, and keep track of where you
have been.** The companion can tell you what is around you right now. It
cannot tell you that the plot wants you in Pyrite Town.

**Dungeons are the hardest part, and the honest state of it is that they
are still being worked on.** Large multi-level interiors — the Cipher labs
especially — are where this companion is weakest. The routed guide can
refuse to reach an exit it should be able to reach, and getting between
floors is the least solved thing here. That is an active, known problem
(see Known issues below), not something you are doing wrong.

If you get stuck in a dungeon, use the walkthrough. That is what it is for,
and using it is not cheating — it is compensating for information the game
only ever presented visually.

The guide covers the original **XD**. XG changes Pokémon, levels and
movesets throughout, so treat it as a guide to the story and the places,
and expect the battles and the Pokémon you meet to differ.

---

## 5. Known issues

Stated plainly, because finding out mid-dungeon is worse.

- **The navigation guide sometimes says it cannot reach an exit that it
  should be able to reach.** Confirmed and diagnosed, not yet fixed. It
  affects elevators and warps most, and it does not refuse outright — it
  walks you as close as it can while saying it cannot arrive. Most common
  in multi-level interiors.
- **Teleport can report success without moving you.** It now tells you
  when this happens ("Teleport did not take"), which it previously did
  not. Two underlying causes are diagnosed and unfixed: landing inside a
  solid object, and landing at the wrong height when the target is on
  another floor.
- **Footsteps can go quiet while beacons keep working.** Diagnosed, not
  fixed. It is not a missing file and not something you did.
- **Only the US release** of Pokémon XD, and hacks built on it, are
  supported. Other regions are not.
- **Some categories are deliberately silent** — healing spots, for
  instance, have no beacon sound of their own rather than borrowing
  another category's cue.
- **This has been tested by one person on one machine.** Setup is verified
  end to end from a clean extraction, but the live gameplay path from a
  packaged release has had far less use than the developer's own checkout.
  Expect rough edges, and please report them.

---

## 6. Anything else worth knowing

### Installing

1. Download the release, extract it somewhere you can write to — `C:\Games\`
   is ideal. Three places to avoid, all of which setup detects and explains
   rather than failing cryptically:
   - **Program Files** — Windows protects it and setup cannot write there.
   - **A very deep folder** — Windows refuses to load parts of this from a
     path over 260 characters.
   - **Documents, Desktop, Pictures, Videos, Music or Favourites** — see
     below.
2. Run **`Setup.cmd`**. It finds Dolphin and your game image by itself and
   asks you to confirm — press Enter, or pick a number from a list. No
   typing paths. It then reads the data it needs from your game image,
   which takes about a minute.
3. Run **`Launch Accessible XD.cmd`** to play.

If you use portable Dolphin, extracting this **inside or beside your
Dolphin folder** means setup finds it immediately.

### If you put it in Documents or on the Desktop

**Controlled Folder Access** — part of Windows Security, on by default —
stops programs Windows doesn't recognise from writing to Documents,
Desktop, Pictures, Videos, Music and Favourites. This download brings its
own copy of Python, freshly unpacked at a path that has never existed
before, so Windows treats it as unrecognised and blocks it.

You'd otherwise see a confusing `FileNotFoundError` mentioning
`__pycache__`, which looks like a corrupt download and isn't. Setup now
checks for this first and explains it. Either:

1. **Move the folder** somewhere like `C:\Games\` and run `Setup.cmd`
   again — easiest, and what I'd suggest, or
2. **Allow it through:** Windows Security → Virus & threat protection →
   Ransomware protection → Allow an app through Controlled folder access →
   add `Runtime\python.exe` from this folder.

### What you need to supply

**Your own copy of the game.** It is not included and cannot be downloaded
for you. The companion needs the game's own text, item, move and collision
tables to say anything useful, and those are copyrighted — so setup
generates them locally from your copy instead. Your disc image is only ever
read, never modified, and nothing about it leaves your computer.

For **XG** specifically you need the XG patch applied to a clean XD image.
That step is not yet handled by this installer.

### Privacy and safety

No network access, no telemetry, nothing installed system-wide, no
registry changes, no administrator prompts. Everything it creates stays
inside its own folder, and deleting that folder removes it completely. The
bundled Python in `Runtime` does not touch or interfere with any Python you
already have.

### Reporting problems

Please open an issue. What helps most:

- What you were doing and what you expected
- The contents of `Companion\logs\` — most failures are already recorded
  there in detail, and that log is usually enough to diagnose without
  guesswork

### Licence and credits

MIT — see [LICENSE](LICENSE).

Beacon and footstep sounds are the project's own, except the "Video game
beeps" pack by the Freesound user **Mossy4**, used under CC-BY 4.0. See
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

Pokémon and Pokémon XD are trademarks of Nintendo, Creatures Inc. and GAME
FREAK Inc. This project is not affiliated with, endorsed by, or connected
to any of them, and distributes no game code or game data.

### For developers

Full instructions for running from source, running the test suite, and
building a release are in
[README-DISTRIBUTION.md](README-DISTRIBUTION.md), and the design record —
what each feature does, how it was verified, and what is still open —
lives in [`Documentation/`](Documentation/), starting with
[MASTER.md](Documentation/MASTER.md).
