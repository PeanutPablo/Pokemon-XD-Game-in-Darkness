===========================================================
POKEMON XD: GAME IN DARKNESS
A screen reader companion for Pokemon XD and Pokemon XG
===========================================================

This program reads Pokemon XD: Gale of Darkness, and the XG: NeXt
Gen ROM hack, out loud through NVDA while you play in Dolphin.

It only ever reads. It never writes to the game, never changes your
disc image, never alters Dolphin, and never sends anything over the
network. Two features are the deliberate exception and both say so
when you use them: Autowalk and Teleport move your character, and
you have to press their key to start them.


-----------------------------------------------------------
CONTENTS
-----------------------------------------------------------

To jump to a section, search this file for its number, such as
"SECTION 4".

  SECTION 1  What you need before you start
  SECTION 2  Installing
  SECTION 3  Why setup asks for your game
  SECTION 4  Starting the game
  SECTION 5  Hotkeys
  SECTION 6  The settings menu
  SECTION 7  Autowalk
  SECTION 8  If something goes wrong
  SECTION 9  What it reads out
  SECTION 10 Known limitations
  SECTION 11 Credits and licence


-----------------------------------------------------------
SECTION 1. WHAT YOU NEED BEFORE YOU START
-----------------------------------------------------------

1. Windows, with NVDA running.

2. Dolphin, the GameCube emulator. Either the installer version or
   the portable zip works. This program does not include Dolphin
   and does not change it.

3. Your own copy of the game as a disc image. Accepted types are
   iso, gcm, rvz, gcz, wia, ciso and wbfs. This download does not
   include the game and cannot get it for you.

You do NOT need to install Python. This download brings its own
Python, in the folder named Runtime. It does not touch, replace or
interfere with any Python already on your computer, and it adds
nothing to your system.

Nothing here is installed system wide. There are no registry
changes and no administrator prompts. Everything this program
creates stays inside this folder, and deleting this folder removes
it completely.


-----------------------------------------------------------
SECTION 2. INSTALLING
-----------------------------------------------------------

Step 1. Extract this folder somewhere you can write to, such as
        C:\Games\

        Do not extract it into Program Files. Windows protects that
        folder and setup will not be able to write there.

        Keep the path reasonably short. Windows refuses to load
        parts of this program from a path longer than 260
        characters, so a folder buried very deep will not work.
        Setup checks this and tells you plainly if it is a problem.

        Optional shortcut: if you use the portable version of
        Dolphin, extracting this folder INSIDE your Dolphin folder,
        or directly beside it, means setup finds Dolphin
        immediately and you just press Enter.

Step 2. Run Setup.cmd

        Setup does not ask you to type any paths. It looks for
        Dolphin and for your game image in the places they usually
        are: in this folder, next to it, in the folders Dolphin is
        already set to scan for games, and in the usual places such
        as your desktop, your downloads and Program Files.

        It then reads out what it found and asks you to confirm.
        Press Enter to accept what it suggests. If it found more
        than one possibility it reads a numbered list, and you type
        a number. If it found nothing, you can still type the full
        path yourself. Typing q at any prompt stops setup.

        Setup then reads the data it needs out of your game image,
        which takes about a minute, and saves your settings.

        Setup installs nothing and does not need an internet
        connection.

Step 3. Run Launch Accessible XD.cmd to play.

If you move Dolphin or your game image later, run Setup.cmd again.


-----------------------------------------------------------
SECTION 3. WHY SETUP ASKS FOR YOUR GAME
-----------------------------------------------------------

To say anything useful about the game, this program has to know the
game's own text, item, move and collision tables. That data is
copyrighted, so it cannot be included in this download.

Setup reads it out of the copy you already own and stores it
locally, in Companion\_dialogue_extraction

This is read only. Your disc image is never modified, and nothing
about it leaves your computer.

You can also do that step on its own:

  Runtime\python.exe Companion\bootstrap_game_data.py --disc "D:\your\game.iso"


-----------------------------------------------------------
SECTION 4. STARTING THE GAME
-----------------------------------------------------------

Run Launch Accessible XD.cmd

It starts the companion first and then Dolphin, so the title screen
is already being read by the time the game boots.

Only run one copy at a time. If everything is spoken twice, an
older copy is still running. Close it and start again.


-----------------------------------------------------------
SECTION 5. HOTKEYS
-----------------------------------------------------------

Hotkeys work while Dolphin is the focused window. Nothing is taken
from other programs.

  F1                Open the settings menu
  ctrl plus .       Next nearby thing
  ctrl plus ,       Previous nearby thing
  ctrl shift .      Next category
  ctrl shift ,      Previous category
  ctrl plus /       Repeat the current thing
  ctrl plus g       Beacon on the selected thing
  ctrl plus n       Routed navigation guide to it
  ctrl shift /      Autowalk to the selected thing
  ctrl plus t       Teleport to the selected thing
  ctrl plus h       Battle HP summary
  ctrl plus 1 to 6  Read party slot 1 to 6: name, level, HP,
                    status, Heart Gauge and held item
  ctrl plus s       Heart Gauge summary
  ctrl plus m       Money

The beacon and the routed guide, ctrl g and ctrl n, go quiet on
their own during a conversation and pick up again when it ends.
They are not switched off, so you keep your target and your route
across a conversation.

Every beacon also goes quiet while the settings menu is open, so
you can hear the Sound library one cue at a time.


-----------------------------------------------------------
SECTION 6. THE SETTINGS MENU
-----------------------------------------------------------

Press F1 to open a spoken settings menu for the companion itself.
It changes how this program behaves. It does not touch the game's
own options screen.

  Up and Down       Move through the list
  Left and Right    Change the value you are on
  H                 Jump to the next heading
  shift plus H      Jump to the previous heading
  Enter or Space    Flip a switch on or off
  Escape            Close the menu

The headings are Sounds, Speech, Navigation, Hotkeys and Sound
library. Changes take effect immediately and are saved, so they are
still there next time you play.

Hotkeys is a read only list of every key in SECTION 5.

Sound library is where you learn what the non speech sounds mean.
Moving onto an entry tells you what that sound is, for example
"Item beacon: an item is lying on the ground nearby", and Enter
plays it. Every beacon, both navigation guides, the waypoint cue, a
footstep and the blocked movement cue are listed. Each one plays
from the same file the game itself uses, so what you hear here is
exactly what you will hear in play.

While the menu is open those keys belong to the companion and are
not passed to the game, so moving through the list does not move
your character.

F1 is taken from Dolphin even when the menu is closed. In a stock
Dolphin setup F1 loads a save state, which is not what you want
when you meant to open settings. Nothing is taken while Dolphin is
not the focused window. If you would rather keep those keys for
Dolphin, the option --no-settings-menu turns the whole feature off.


-----------------------------------------------------------
SECTION 7. AUTOWALK
-----------------------------------------------------------

Autowalk, ctrl shift /, walks your character to whatever entity
navigation currently has selected.

ANY movement input stops it. Nudge the stick or the D-pad and you
have control back immediately.

It also stops on its own when you arrive, when you enter a new
area, when a menu or a conversation opens, if it stops making
progress, or if it cannot find a walkable route in the first place.

It never guesses. If there is no real route, it says so and does
not move.


-----------------------------------------------------------
SECTION 8. IF SOMETHING GOES WRONG
-----------------------------------------------------------

"This folder is too deep inside your drive for Windows"
  Move this whole folder somewhere with a shorter path, such as
  C:\Games\ and run Setup.cmd again.

Setup could not find Dolphin or your game
  Type the full path when it asks. Setup only searches a few levels
  down from the usual places, so a game image kept somewhere
  unusual will not be found on its own.

Nothing is spoken
  Check that NVDA is running, and that Dolphin is the focused
  window. The companion starts speaking once a game is loaded.

"Battle narrator stopped after an error"
  Usually missing game data. Run Setup.cmd again.

Everything is said twice
  An older copy of the companion is still running. Close it and
  start again.

Setup talks about installing Python 3.12
  You are running a source checkout from the code repository
  rather than a release. A release brings its own Python and never
  asks for one.

Beacons work but you hear no footsteps
  This is a known open problem and it is being investigated. It is
  not caused by anything you did or by a missing file.

Details of what failed are written to Companion\logs\


-----------------------------------------------------------
SECTION 9. WHAT IT READS OUT
-----------------------------------------------------------

Battles
  Move menus with type and PP, damage and HP as percentages, stat
  changes, status, faints, Shadow moves, Heart Gauge, how many
  Pokemon the opponent brought, and what each target actually is
  while you are aiming at it.

The overworld
  A navigable list of nearby NPCs, items, doors, warps, elevators,
  PCs and shops, with a steerable audio beacon, terrain footsteps
  and a routed navigation guide.

Menus and screens
  The bag, shops, the party list and summary, the PC and Purify
  Chamber, the PDA, and the title screen.

Dialogue
  NPC conversations, spoken a page at a time with the speaker
  named.


-----------------------------------------------------------
SECTION 10. KNOWN LIMITATIONS
-----------------------------------------------------------

Only the US release, and hacks built on it, are supported. Other
regions are not.

Gateon Port bridge connections appear under Exits. Their names and
positions come from the room's own collision data, and the list
updates from the live bridge alignment, so only directions you can
currently cross are listed.

Categories with no sound of their own, such as healing spots, are
deliberately silent rather than borrowing another category's cue.

Footsteps can go quiet while beacons keep working. The cause is
known and written up, and it is not a missing file. See SECTION 8.


-----------------------------------------------------------
SECTION 11. CREDITS AND LICENCE
-----------------------------------------------------------

This companion is MIT licensed. See the file named LICENSE.

Beacon and footstep sounds are the project's own, except the
"Video game beeps" pack by the Freesound user Mossy4, used under
CC-BY 4.0. See THIRD-PARTY-NOTICES.md for the full attribution,
which is a licence obligation and not a courtesy.

No game data of any kind is included in this download.

Pokemon and Pokemon XD are trademarks of Nintendo, Creatures Inc.
and GAME FREAK Inc. This project is not affiliated with, endorsed
by, or connected to any of them.
