# Settings menu (F1)

**Status: implemented 2026-08-16, not yet live-tested.** One claim in §3
requires live confirmation before this can be called done — see §7.

A spoken, keyboard-navigable settings menu for the companion itself. It
changes how the *accessibility layer* behaves — beacon volume, footsteps,
announcements, guide distances. It does not touch the game's own options
screen, and it writes no emulated memory.

---

## 1. Keys

| Key | Action |
| --- | --- |
| `F1` | Open the menu; press again to close |
| `Up` / `Down` | Move one item, across category boundaries |
| `H` / `Shift+H` | Jump to the next / previous heading |
| `Left` / `Right` | Change the selected setting |
| `Enter` / `Space` | Flip the selected toggle, or play the selected sound |
| `Home` / `End` | First / last item |
| `Escape` | Close |

Everything is spoken through the existing `SpeechCoordinator` as
`MENU_FOCUS`, the same class the in-game menu readers use, so a new
announcement interrupts a stale one.

The instructions are spoken on the first open of a session only. Repeating
them on every open puts a long sentence in front of the thing the player
came for.

### Navigation model

Chosen to match what a screen-reader user already knows, rather than
inventing a game-menu idiom:

- **Up/Down move item by item** through the whole list. Crossing into a new
  category announces the heading first — "Speech. Room announcements, on."
- **H is NVDA's browse-mode heading jump**, wrapping at the ends.
  `Shift+H` from the middle of a category goes to the top of the *current*
  category first, exactly as NVDA does, so "back to the start of this
  section" is one press.
- **Item movement stops at the ends** and says "Top of list." / "End of
  list." rather than wrapping. Wrapping is right for entity-nav's category
  ring — a ring of live entities has no meaningful end — but a settings list
  does have one, and silently arriving back at the top is how a player loses
  their place.
- **Left/Right change the value in place.** No sub-menu and no confirm step:
  every setting here is a toggle or a stepped number, both fully described
  by re-speaking the item.
- At the end of a numeric range the value is spoken with "Minimum." /
  "Maximum." appended, so a key that appears to do nothing is explained.

---

## 2. What the menu contains

Every value already existed as a named constant. Several of those constants
carry a comment saying they were named *because* a settings UI would need
them (`npc_beacons.PASSIVE_BEACON_GAIN_SCALE`,
`TerrainTonePlayer.STEP_GAIN`). Defaults are read from those constants at
build time, so retuning one moves the default with it.

**Sounds** — Entity beacons (on/off), Beacon volume, Warp beacon volume,
Beacon range, Footstep cues (on/off), Footstep volume, Blocked movement cue
(on/off).

**Speech** — Room announcements (on/off), Interaction cues (on/off), Repeat
selection when you stop (on/off), Repeat delay.

**Navigation** — Guide range, Guide arrival distance, Autowalk arrival
distance.

**Hotkeys** — read-only. Every companion hotkey and what it does, built from
the *parsed arguments* of the running session rather than from the profile
defaults, so it can never describe a key the companion is not actually
listening for. Not a rebinding UI.

**Sound library** — playable. One entry per non-speech cue the companion
makes; see §2a.

That property paid for itself immediately. Listing the hotkeys is what
surfaced a chord collision when autowalk was moved to `ctrl+shift+/` later
the same day — see the note below.

### Same-day hotkey changes (2026-08-16)

Autowalk moved from `ctrl+w` to `ctrl+shift+/` at the project owner's
request. `ctrl+shift+/` was the entity-nav **refresh** hotkey, and looking
into the collision showed refresh had never worked: `WindowsForegroundHotkey`
tested only that every key in its chord was *down*, so `ctrl+slash` (repeat)
matched every `ctrl+shift+slash` press as well, and `EntityNavigator.poll_once`
checks repeat first in the same `elif` chain. Two changes followed:

- **Chords now mean exactly themselves.** A modifier the chord does not name
  must be up (`WindowsForegroundHotkey._pressed`). This is what makes the new
  autowalk binding distinguishable from repeat at all.
- **Refresh was removed** rather than rehomed, at the owner's request.
  `ctrl+w` is left unbound: a key that has meant "walk me there" should go
  quiet rather than start doing something else.

---

## 2a. The Sound library (added 2026-08-18)

The companion speaks a great deal, but it also makes eleven distinct
non-speech sounds. Until this heading existed, the only way to learn any of
them was to encounter it in play and infer what had just happened — and a
cue you *misidentify* is worse than silence, because you act on it.

Each entry names a cue, says what it means, and plays it on `Enter`:

| Group | Entries |
| --- | --- |
| Ambient beacons | Person, Poké Mart, Item, Door, Warp, Elevator |
| Navigation cues | Beacon on your selection (`ctrl+g`), Routed navigation guide (`ctrl+n`), Navigation waypoint reached |
| Movement | Footstep, Blocked movement |

Three properties, all deliberate:

- **`Enter` plays and says nothing.** The player pressed it to *hear* the
  cue; talking over it is precisely what would stop them recognising it in
  play. Focus alone speaks the label and the explanation.
- **The description is spoken.** `Sound` is the only item kind whose
  `description` reaches the player's ears. For every other setting the
  label already says what it does; for a cue, the explanation is the whole
  point. The wording says what the sound *means*, never what it sounds like
  — the player is about to hear it.
- **Only sounds that are actually wired up appear.** `phase1b_app.
  build_sound_library` passes the same paths it hands the readers
  themselves (`PASSIVE_BEACON_SOUND_FILES`, `GUIDE_SOUND_FILES`, and
  `terrain_footsteps.resolve_step_paths` / `resolve_blocked_path`). A
  catalogue that could name a sound nothing plays would teach a cue that
  never comes. `GUIDE_SOUND_FILES` and the terrain path resolvers were
  extracted for this — previously those filenames were spelled inline in
  the guide factory and inside `TerrainTonePlayer.__init__`, so a library
  built from its own copy would have been a second place for them to drift.

The warp entry plays at the same 0.2 trim the real warp beacon uses, so the
example sounds like the thing it is teaching.

**Every beacon is silenced while the menu is open** (project owner's
request, 2026-08-18) — the passive category beacons and both guide modes.
This heading is why it matters: it exists to play cues one at a time so
they can be told apart, which the ambient beacons were playing over. They
are silenced, not switched off, and resume when the menu closes;
`LifecycleController._beacons_silenced` is the single place that decides,
and it answers the same for an open conversation.

**The blocked-movement cue was retuned from 90 Hz to 200 Hz** on the same
day, after the project owner reported hearing nothing for it here. The file
was never silent — full-scale peak, −9 dBFS RMS — but it is a square wave,
and 84% of a 90 Hz square's energy sits below 150 Hz, which laptop speakers
and most earbuds do not reproduce. `terrain_footsteps.BLOCKED_CUE_FILENAME`
changed alongside the frequency on purpose: the file is generated only `if
not path.exists()`, so under the old name every existing install would have
kept its cached 90 Hz copy forever.

Note that the cue itself is **off by default** (`Sounds` → `Blocked
movement cue`, marked experimental), so retuning it changes what the Sound
library plays but not what happens in play until that toggle is switched
on.

A file that is missing or cannot be rendered drops its own entry and logs a
warning; it never stops the menu from opening. The beacons already
pre-flight their own files at startup with `npc_beacons.check_playable` and
fail loudly there, which is the right place for that error. An entirely
empty library contributes no heading at all rather than an empty one.

Nothing here is a preference, so `Sound` — like `Info` — carries no stored
value. Both kinds are listed in `settings.VALUELESS_KINDS`, which the
store, the loader and the menu all consult, so they cannot drift into
disagreeing about which entries have a value to save.

---

## 3. Why a keyboard hook, and not `GetAsyncKeyState`

Every other hotkey in this project is a chord with a mandatory modifier —
`hotkeys.parse_hotkey` refuses a bare key outright — and is read by polling
`GetAsyncKeyState`. Polling *observes*; it cannot stop Dolphin from acting on
the same press. That is fine for `ctrl+g`, which Dolphin ignores. It is not
fine here. From the project owner's own Dolphin configuration:

```
Config/Hotkeys.ini     Load State/Load State Slot 1 = F1
Config/GCPadNew.ini    Main Stick Up/Down/Left/Right = UP/DOWN/LEFT/RIGHT
                       D-Pad/Right = H
                       Buttons/Start = RETURN
```

A polled settings menu on those keys would **load a save state every time it
opened**, walk the player around while they moved through the list, and press
Start on the way out. The keys have to be taken away from the game, not
merely noticed. `key_capture.py` installs a `WH_KEYBOARD_LL` hook, which sees
each event before the foreground application and can consume it.

**Scope, kept as narrow as the feature allows:**

- Only keys in `MenuKeyPolicy` are ever consumed; everything else is passed
  straight through in the same call.
- Nothing is consumed unless **Dolphin owns foreground focus** — the same
  rule every other hotkey follows. Alt-tab away and the keyboard behaves as
  if this module did not exist.
- Outside the menu, exactly **one** key is consumed: `F1`. The arrows, `H`,
  `Enter` and `Escape` are consumed only while the menu is open.
- Key-*up* is swallowed alongside key-down. Letting an up through on its own
  leaves DirectInput holding a key it never saw pressed — that is how a
  swallowed arrow would become a stuck walk.
- `--no-settings-menu` disables the whole thing, hook included.

**Threading.** A low-level hook runs on the thread that installed it, and
Windows silently removes a hook whose callback does not return within
`LowLevelHooksTimeout` (300 ms default). The narrator's poll loop sleeps up
to 500 ms between ticks and does memory reads and pathfinding in between, so
the hook gets a dedicated thread that does nothing but pump messages. The
callback only classifies the key and appends to a `deque`; everything slow
(speech, game memory) happens later on the poll thread when `poll()` drains
it. `deque.append`/`popleft` are atomic, so no lock is involved.

---

## 4. How a setting reaches the running companion

Two mechanisms, chosen per setting:

**Applied** (`settings.py` appliers). The value is pushed into whatever live
reader objects exist, and **re-applied every time the lifecycle rebuilds
them** — a Dolphin reattach throws every reader away. Nothing is remembered
inside a reader, so nothing is lost on a rebuild. The frozen `XD_US_REV0`
profile is never mutated; defaults are read from it and the live values are
held in the store.

**Gated** (`LifecycleController._feature_enabled`). The on/off toggles are
read at poll time. Switching one off stops the feature from speaking or
sounding *without destroying its reader*, so switching it back on costs
nothing — several of these readers load collision geometry or decode sound
files to construct. The falling edge is detected so the reader is cleared
exactly once, which matters for the ones that accumulate state: footstep
cadence and the last-announced room would otherwise resume mid-stride.
Switching beacons off additionally stops whatever is mid-loop, so silence is
immediate rather than one sound later.

Turning a gate off is not the same as `--no-<feature>`: the reader is still
built. `--no-terrain-footsteps` and `--collision-feedback` now set the
*starting value* of their settings and are deliberately **not** written back
to disk — a launcher shortcut should not silently rewrite a preference set in
the menu. With `--no-settings-menu`, those flags are all there is, and the
factories fall back to gating on them directly.

The menu is polled in **every** lifecycle state, before the state machine
runs, including before Dolphin exists: it reads no emulated memory, and a
player who wants to turn the beacons down should not have to boot a game
first. It is also isolated like every reader — an exception that killed the
poll loop would leave a keyboard hook installed with nothing draining it.

---

## 5. Storage

`Companion/companion_settings.json`, under an `"accessibility"` key.
Merged, never overwritten: that file also holds the Dolphin and game-image
paths `Setup.cmd` records. Two consequences were handled:

- `setup_companion.write_settings` now **merges** rather than rewriting, so
  re-running Setup to point at a moved Dolphin does not reset volumes
  someone tuned by ear.
- `launch_accessible.py` no longer treats the *existence* of the file as
  proof Setup has run — the settings menu can create it first. It checks for
  the recorded paths, so a player who adjusted the volume before running
  Setup still gets "Run Setup.cmd first" rather than "Dolphin is no longer
  at .".

Saved immediately on every change. A file that cannot be written is logged,
announced once, and the value still applies for the session. Unknown stored
keys are dropped rather than carried forward; out-of-range numbers are
clamped, not rejected.

---

## 6. Tests

`tests/test_settings_menu.py`, 80 `unittest.TestCase` tests (the whole suite
is 1688, with the two pre-existing `test_passability.DestinationProjectionTests`
failures that already reproduced before this work):

- **Values** — spoken forms, stepping, clamping, and that six 0.05 steps
  land on exactly `0.3` rather than float dust.
- **Store** — defaults, round-trip, Setup's keys preserved, unknown keys
  ignored, corrupt file, unwritable path reported once.
- **Appliers** — against the real attributes they target, including
  `npc_beacons`'s module-level gains, the shared `TerrainTonePlayer`, and
  both halves of `GuideModes`. Also: no readers yet, no controller at all,
  and an applier that raises.
- **Navigation** — headings, wrapping, edge stops, empty categories, an
  entirely empty menu.
- **Key policy** — that `X`, `Z`, `T`, `G`, `F`, `F2` and the rest of the
  game's keys are never owned, and that arrows reach the game while the menu
  is closed.
- **Gating** — polls stop, the reader clears exactly once, beacons are
  stopped as well as cleared, and everything runs when settings are absent.

A separate manual smoke run installed the real hook, confirmed it installs,
pumps and uninstalls cleanly, and never consumed a key (foreground forced
false).

---

## 7. Open — needs a live run

**Does swallowing at the hook stop Dolphin from seeing the key?** Dolphin
reads the keyboard through DirectInput in non-exclusive mode, which is built
on the same input stream low-level hooks filter, so it should. That is a
mechanism argument, not a measurement, and this project does not count those
as verified. The test:

1. Start the companion and Dolphin, load a game.
2. Press `F1`. **Expected:** the menu opens and the game does *not* jump
   back to save state slot 1.
3. Arrow through the list. **Expected:** the character does not move.
4. Press `H`. **Expected:** heading jump, no D-pad right in game.
5. Close with `Escape`, then confirm arrows walk normally again.

If any key reaches the game as well, the fallbacks are: rebind that key in
Dolphin, or move the menu onto keys Dolphin does not use. Neither needs a
redesign — `MenuKeyPolicy` is the single place both live.

Also unverified by a live run: that the volume and distance settings sound
the way their numbers suggest. They are applied to the same attributes the
constants fed, so the mechanism is the one already in use, but nobody has
listened to them yet.

---

## 8. Vertical slice record

Per [VERTICAL_SLICE_TEMPLATE.md](VERTICAL_SLICE_TEMPLATE.md), which requires
every section to be filled in and "not applicable" only where genuinely true.

**Blind-player failure.** Every knob in the accessibility layer — beacon
volume, footstep volume, which announcements are spoken, guide distances —
could only be changed by editing Python source or by passing command-line
flags from a launcher script. A blind player who finds the warp beacons too
loud, or the room announcements intrusive, has no way to change either while
playing, and no way to make the change survive to the next session.

**Intended behavior.** `F1` opens a spoken menu. Arrow keys move through
it and change values; `H` jumps by heading; each move speaks the item and
its current value; each change speaks the new value and takes effect
immediately. Settings persist to disk and are re-applied at the next launch.

**In-scope behavior.** The 14 settings listed in §2, across four categories,
plus a read-only hotkey reference. Changing a value, persisting it, applying
it to live readers, and re-applying it after a Dolphin reattach.

**Out-of-scope behavior.** Rebinding hotkeys (the Hotkeys category is a
reference list, deliberately read-only). Any game option — this menu is the
companion's own settings, not `TITLE_MAIN_OPTIONS_ACCESSIBILITY.md`'s
in-game options screen. Free text entry, profiles/presets, and a
reset-to-defaults action. Per-category beacon volumes beyond warps, which is
the only trim that exists.

**Game contexts.** All of them, and deliberately so: the menu is polled at
the top of `LifecycleController.step`, before the state machine, so it works
in `DOLPHIN_ABSENT`, `ATTACHING`, `PROFILE_PENDING`, `GSMSG_WAITING` and
`ACTIVE` alike. It reads no emulated memory, so no context can make it
unsafe. No context suppresses it. The only gate is foreground focus, which
is `hotkeys.WindowsForegroundProcess`, the same mechanism every other hotkey
uses.

**Data sources.** None in emulated memory. It reads
`Companion/companion_settings.json` (its own `"accessibility"` key) and, for
defaults, the constants the features themselves use:
`npc_beacons.PASSIVE_BEACON_GAIN_SCALE`, `PASSIVE_BEACON_CATEGORY_GAIN`,
`TerrainTonePlayer.STEP_GAIN`, and the frozen profile's
`npc_sound_max_distance`, `entity_nav_auto_repeat_seconds`,
`audio_guide_max_distance`, `audio_guide_arrival_distance`,
`default_autowalk_arrival_distance`. The Hotkeys list is read from the
session's parsed arguments. Windows APIs used: `SetWindowsHookExW`,
`CallNextHookEx`, `UnhookWindowsHookEx`, `GetMessageW`,
`PostThreadMessageW`, `GetAsyncKeyState`.

**Address validation.** Not applicable in the usual sense — no emulated
address is read or written. The equivalent guards are on the file and the
hook: stored values are coerced and clamped to each setting's declared
range, unknown keys are dropped, an unreadable or corrupt file falls back to
defaults, and `SetWindowsHookExW` returning 0 is handled as "the menu is
unavailable this session" (announced, stored settings still applied) rather
than as a fatal error. ctypes prototypes are declared explicitly, since
without them the 64-bit handles these calls traffic in are silently
truncated.

**Speech or sound behavior.** All menu speech is
`SpeechEventClass.MENU_FOCUS` with `interrupt=True` and no deduplication, so
a new announcement replaces a stale one and pressing the same key twice
speaks twice. Wording: `"{label}, {value}."`, prefixed with `"{Category}. "`
when the heading changes, `"Top of list. "` / `"End of list. "` at the
edges, and suffixed `" Minimum."` / `" Maximum."` at the ends of a numeric
range. Opening speaks `"Settings."` plus, on the first open of a session
only, the instruction line. Closing speaks `"Settings closed."` A failed
save is announced once as `SpeechEventClass.WARNING`, non-interrupting. No
sounds of its own.

**Input behavior.** `F1` (open/close), `Up`/`Down`, `Left`/`Right`,
`H`/`Shift+H`, `Enter`, `Space`, `Home`, `End`, `Escape`. **No game-facing
input is ever sent** — this feature is the opposite case: it *withholds*
input Windows would otherwise deliver to Dolphin, which is a distinct thing
from `teleport.py`/`autowalk.py`'s authorized writes and required its own
explicit authorization (project owner, 2026-08-16, choosing "swallow the
keys" from the three options they were given after being shown the F1 =
Load State Slot 1 conflict). Nothing is withheld while Dolphin is not
foreground, and outside the menu only `F1` is.

**Safety conditions.** The hook consumes an event only when the key is in
`MenuKeyPolicy` for the current open/closed state *and* Dolphin owns
foreground focus. The callback can never raise into the Windows hook chain
(it is wrapped, and a failure logs and passes the key through). The hook
lives on a dedicated message-pumping thread because Windows silently removes
a hook whose callback exceeds `LowLevelHooksTimeout`, and the narrator's
poll loop can be half a second between ticks. Appliers are individually
wrapped, so one that raises costs its own setting and nothing else.

**Cancellation behavior.** `Escape` or a second `F1` closes. A lifecycle
disconnect closes it silently via `clear()` — Dolphin has gone, so nobody is
in front of the game to hear a close announcement, and the menu must not be
left holding the arrow keys for a window that no longer exists. The hook is
removed in `run()`'s `finally`, which is why `key_capture` is bound before
the `try`: leaving a low-level hook installed after the process stops
draining it is the one failure here with consequences outside this program.

**Automated tests.** `tests/test_settings_menu.py`, 73 tests — see §6. Not
unit-tested directly, by the project's established convention: the actual
`SetWindowsHookExW` install (covered by a manual smoke run instead) and
whether a swallowed key really fails to reach Dolphin (only a live run can
answer that; see §7).

**Live-test procedure.** §7. Five actions, one at a time. No milestone save
is needed — any booted game in the field will do, since the menu is
independent of game state.

**Regression targets.** Every existing hotkey must keep working, and the
narrator must behave identically with `--no-settings-menu` or with no
settings file present. Covered by `test_cli_defaults.py` (all default chords
present, no two colliding), `test_settings_menu.py`'s
`test_everything_runs_when_there_are_no_settings_at_all`, and the unchanged
`test_phase1b_lifecycle.py`. The footstep and blocked-movement readers are
now always built and gated by setting rather than by flag, so
`test_cli_defaults.py`'s flag assertions and `test_terrain_footsteps.py`
both still apply.

**Known limitations.** The hook's effectiveness against DirectInput is
unproven (§7). Other companion announcements are not muted while the menu is
open, so a room change or a stand-still repeat can speak over it. There is
no reset-to-defaults action. Values that are off-range in a hand-edited file
are clamped silently rather than reported to the player. `--no-settings-menu`
is the only way to release `F1`, which is all-or-nothing: there is no way to
keep the menu but give `F1` back to Dolphin, because that is the key the
menu opens with.

**Completion decision.** Implemented: **yes**. Regression-tested: **yes**
(73 tests). Live-tested: **no**. By the master plan's three-part definition
this slice is **not complete**, and the coverage matrix says so.
