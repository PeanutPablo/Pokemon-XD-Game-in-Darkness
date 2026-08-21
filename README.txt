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
  SECTION 11 A guide to the game itself
  SECTION 12 Credits and licence


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

        Avoid Documents, Desktop, Pictures, Videos, Music and
        Favourites too. Windows Security has a feature called
        Controlled Folder Access, switched on by default, which
        stops programs it does not recognise from writing to those
        folders. This download brings its own copy of Python,
        unpacked fresh where Windows has never seen it, so it counts
        as unrecognised and gets blocked. Setup checks for this and
        explains it rather than failing strangely. If it happens,
        either move this folder somewhere like C:\Games\ and run
        Setup.cmd again, or allow it through in Windows Security,
        under Virus and threat protection, Ransomware protection,
        Allow an app through Controlled folder access.

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

Step 3. Run Play.cmd to play.

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

Run Play.cmd

It starts the companion first and then Dolphin, so the title screen
is already being read by the time the game boots.

Play.cmd is the file you run every time you play. It
starts the access layer and Dolphin together, and boots your game.

Let it open Dolphin for you. If you open Dolphin yourself first,
it cannot boot the game for you, because Dolphin will not open
twice. It tells you so, and asks you to start the game in the
window you already have open. It begins speaking once the game
loads.

You do not need to worry about running it twice. Before it starts,
it closes any access layer still running from an earlier session,
so you end up with one rather than two talking over each other.
That also means a new version can replace this folder cleanly: a
companion holding its log file open is what turns an update into a
half-deleted copy.

When you close Dolphin, the access layer stops on its own. It waits
a minute first, in case you are only restarting Dolphin, then says
"Dolphin has closed. Stopping the companion." and exits. You are
not left with something running in the background that you cannot
see.


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
  ctrl plus l       Turn repeat-on-stop on or off
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

When you stop moving, the companion re-announces whatever you have
selected. That is useful when you are walking toward something and
want to know if you have arrived, and it is an interruption when you
have stopped to think.

ctrl plus l turns that off, and says "Repeat on stop, off" so
you know which way it went. Press it again to turn it back on. The
setting is remembered, and it is also in the settings menu under
Speech, as "Repeat on stop".

It only switches off the automatic repeat. ctrl plus / still repeats
the selection whenever you ask for it.


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
  A navigable list of nearby NPCs, items, doors, exits, elevators,
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

Stated plainly, because finding out mid-dungeon is worse.

The navigation guide sometimes says it cannot reach an exit that it
should be able to reach. Confirmed and being worked on. It affects
exits most. It does not refuse outright, it walks you
as close as it can while saying it cannot arrive. Most common in
multi-level interiors.

Teleport can report success without moving you. It now tells you
when that happens, saying "Teleport did not take", which it did not
used to. Two underlying causes are known and not yet fixed: landing
inside a solid object, and landing at the wrong height when the
target is on another floor.

Footsteps can go quiet while beacons keep working. Known and being
worked on. It is not a missing file and not something you did.

Only the US release of Pokemon XD, and hacks built on it, are
supported. Other regions are not.

Gateon Port bridge connections appear under Exits. The list updates
from the live bridge alignment, so only directions you can currently
cross are listed.

Some categories are deliberately silent. Healing spots, for example,
have no beacon sound of their own rather than borrowing another
category's cue.

This has been tested by one person on one machine. Setup is verified
from a clean extraction, but the live gameplay path from a packaged
release has had far less use than the developer's own copy. Expect
rough edges, and please report them.


-----------------------------------------------------------
SECTION 11. A GUIDE TO THE GAME ITSELF
-----------------------------------------------------------

Please treat this section as part of the setup, not an optional
extra.

Pokemon XD expects you to be LOOKING at it. It rarely tells you
where to go next. It assumes you noticed the door in the corner,
that you remember which building the man mentioned two towns ago,
and that you can see the one interactable thing in a room full of
scenery. None of that is something a screen reader can restore,
because the game never said it out loud to anyone. It drew it.

So pay attention to what people tell you, and keep track of where
you have been. This companion can tell you what is around you right
now. It cannot tell you that the plot wants you in Pyrite Town.

Dungeons are the hardest part, and the honest state of it is that
they are still being worked on. Large multi-level interiors, the
Cipher labs especially, are where this companion is weakest. The
routed guide can refuse to reach an exit it should be able to reach,
and getting between floors is the least solved thing here. That is a
known problem being actively worked on, not something you are doing
wrong.

If you get stuck in a dungeon, use the walkthrough. That is what it
is for, and using it is not cheating. It is compensating for
information the game only ever presented visually.

  https://gamefaqs.gamespot.com/gamecube/925945-pokemon-xd-gale-of-darkness/faqs/40528

It is a written guide on GameFAQs, not part of this project, and it
was not written with screen reader users in mind. It covers the
original Pokemon XD. Pokemon XG changes a great deal, so treat it as
a guide to the story and the places, and expect the battles and the
Pokemon you meet to differ.


-----------------------------------------------------------
SECTION 12. CREDITS AND LICENCE
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
