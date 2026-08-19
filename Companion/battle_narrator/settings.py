"""Player-facing accessibility settings: what they are, what they do to the
running companion, and where they are stored.

Every value here already existed as a named constant somewhere in the
project -- `npc_beacons.PASSIVE_BEACON_GAIN_SCALE`,
`TerrainTonePlayer.STEP_GAIN`, the profile's guide distances -- and several
of those constants carry a comment saying they were named *because* the
planned user-settings UI would need them. This module is that UI's model;
`settings_menu.py` is its presentation.

Two deliberate divisions of labour:

- **Values live here, never in the readers.** A setting is applied to
  whatever live reader objects currently exist, and re-applied every time
  the lifecycle rebuilds them (a Dolphin reattach throws every reader away).
  Nothing is remembered inside a reader, so nothing is lost on a rebuild.
- **On/off toggles are NOT applied.** They are read at poll time by
  `LifecycleController`, so switching one off stops the feature from
  speaking or sounding without destroying its reader -- and switching it
  back on costs nothing. Applying "off" by tearing a reader down would
  make the toggle a one-way door on anything with expensive setup.

The profile (`XD_US_REV0`) is a frozen dataclass and is never mutated:
defaults are READ from it, and the live values are held here.

Storage is `companion_settings.json`, the file `Setup.cmd` already writes,
under a separate `"accessibility"` key. Merged, never overwritten -- that
file also holds the Dolphin and game-image paths the launcher needs.
"""
import json

from . import npc_beacons
from .profile import XD_US_REV0
from .terrain_footsteps import TerrainTonePlayer


SETTINGS_SECTION = "accessibility"
"""Our key inside `companion_settings.json`. Setup.cmd owns the top level."""


class Toggle:
    """An on/off setting. `applier` is None for the ones the lifecycle
    gates at poll time (see the module docstring)."""

    kind = "toggle"

    def __init__(self, key, label, default, applier=None, description=""):
        self.key = key
        self.label = label
        self.default = bool(default)
        self.applier = applier
        self.description = description

    def coerce(self, value):
        return bool(value)

    def speak_value(self, value):
        return "on" if value else "off"

    def adjust(self, value, direction):
        """Left and right both flip a two-state setting -- there is only one
        other state to move to, so refusing one direction would just be a
        key that does nothing."""
        return not value

    def activate(self, value):
        return not value


class Number:
    """A numeric setting adjusted in fixed steps.

    `unit` is "percent" for the gain knobs (0.0-1.0 stored, spoken as
    whole percent), "seconds" for delays, and "" for the distance values --
    which are deliberately spoken as bare numbers, matching entity-nav's
    long-standing refusal to call game units metres."""

    kind = "number"

    def __init__(self, key, label, default, minimum, maximum, step,
                 unit="", applier=None, description=""):
        self.key = key
        self.label = label
        self.default = float(default)
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self.step = float(step)
        self.unit = unit
        self.applier = applier
        self.description = description

    def coerce(self, value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return self.default
        return self._clamp(number)

    def _clamp(self, value):
        # Rounded to three places so repeated stepping cannot accumulate
        # binary-float dust into "0.30000000000000004 percent".
        return round(min(self.maximum, max(self.minimum, value)), 3)

    def speak_value(self, value):
        if self.unit == "percent":
            return f"{round(value * 100)} percent"
        if self.unit == "seconds":
            text = f"{value:.1f}".rstrip("0").rstrip(".")
            return f"{text} second" if value == 1 else f"{text} seconds"
        if float(value).is_integer():
            return str(int(value))
        return f"{value:.1f}"

    def adjust(self, value, direction):
        return self._clamp(value + direction * self.step)

    def activate(self, value):
        return value

    def at_minimum(self, value):
        return value <= self.minimum

    def at_maximum(self, value):
        return value >= self.maximum


class Info:
    """A read-only entry. Carries no stored value -- the Hotkeys category is
    a reference list, not a rebinding UI."""

    kind = "info"

    def __init__(self, key, label, value_text, description=""):
        self.key = key
        self.label = label
        self.value_text = value_text
        self.default = None
        self.applier = None
        self.description = description

    def coerce(self, value):
        return None

    def speak_value(self, value):
        return self.value_text

    def adjust(self, value, direction):
        return value

    def activate(self, value):
        return value


class Sound:
    """A playable example of one companion sound cue.

    Holds no value at all -- like `Info`, and for the same reason: nothing
    here is a preference, so there is nothing to store, clamp or restore.
    What it has instead is an action. Enter and space play the sound;
    left and right do nothing, because there is no other state to move to.

    This is the one item kind whose `description` is SPOKEN rather than
    kept as documentation. For every other setting the label already says
    what it does; for a sound cue, the explanation is the entire point --
    the player is about to hear a beep and needs to be told what that beep
    will mean in play."""

    kind = "sound"

    def __init__(self, key, label, play, description=""):
        self.key = key
        self.label = label
        self.play = play
        self.default = None
        self.applier = None
        self.description = description

    def coerce(self, value):
        return None

    def speak_value(self, value):
        return "press enter to play"

    def adjust(self, value, direction):
        return value

    def activate(self, value):
        return value


class Category:
    """One heading and the items under it. `h` jumps between these."""

    def __init__(self, title, items):
        self.title = title
        self.items = tuple(items)


SPOKEN_KEY_NAMES = {
    "ctrl": "control",
    "shift": "shift",
    "alt": "alt",
    "period": "period",
    "comma": "comma",
    "slash": "slash",
}


def spoken_chord(chord):
    """"ctrl+shift+period" -> "control plus shift plus period".

    Single letters are upper-cased so a screen reader says "H" rather than
    reading a lone lowercase letter as a word."""
    parts = []
    for part in str(chord).split("+"):
        part = part.strip().casefold()
        if not part:
            continue
        parts.append(SPOKEN_KEY_NAMES.get(part, part.upper()))
    return " plus ".join(parts)


# ---------------------------------------------------------------------------
# Appliers. Each pushes one value into whatever live objects exist right now.
# They take the LifecycleController because that is what owns the readers, and
# every one of them tolerates a reader being absent: readers are optional
# (a missing sound file disables one), and the whole set is None until the
# first successful attach.
# ---------------------------------------------------------------------------

def _apply_beacon_volume(controller, value):
    npc_beacons.set_passive_beacon_gain(value)


def _apply_warp_beacon_volume(controller, value):
    npc_beacons.set_category_gain("warp", value)


def _apply_beacon_range(controller, value):
    reader = getattr(controller, "npc_sound_reader", None)
    if reader is not None:
        reader.max_distance = value


def _apply_footstep_volume(controller, value):
    # Both readers share one TerrainTonePlayer in production, but not by
    # contract -- either can be absent, and setting it twice on the same
    # object is harmless. Set on the INSTANCE, shadowing the class attribute,
    # so the documented default in terrain_footsteps.py stays readable.
    for name in ("terrain_footstep_reader", "blocked_movement_reader"):
        reader = getattr(controller, name, None)
        player = getattr(reader, "tone_player", None)
        if player is not None:
            player.STEP_GAIN = value


def _apply_auto_repeat(controller, value):
    reader = getattr(controller, "entity_nav_reader", None)
    if reader is not None:
        reader.auto_repeat_enabled = value


def _apply_auto_repeat_delay(controller, value):
    reader = getattr(controller, "entity_nav_reader", None)
    if reader is not None:
        reader.auto_repeat_seconds = value


def _apply_entity_location(controller, value):
    """Push the setting into the reader, and let the reader push back.

    The second half is what stops `ctrl+l` and the settings menu becoming
    two opinions about one setting. The hotkey flips `location_enabled`
    directly -- it has to, the menu may never have been opened -- and
    without this callback the store would still hold the old value, save
    it on the next unrelated change, and quietly undo the player's choice
    at the next launch.

    Wired here rather than at construction because appliers are the one
    place that already runs every time the lifecycle builds or rebuilds a
    reader, so a reader replaced mid-session gets the callback too."""
    reader = getattr(controller, "entity_nav_reader", None)
    if reader is None:
        return
    reader.location_enabled = value
    store = getattr(controller, "settings", None)
    if store is not None:
        reader.on_location_change = lambda new_value: store.set(
            "speech.entity_location", new_value, controller)


def _guide_readers(controller):
    """The beacon and the routed guide, which the lifecycle holds as one
    `GuideModes` pair."""
    modes = getattr(controller, "audio_guide_reader", None)
    if modes is None:
        return ()
    return tuple(
        reader for reader in
        (getattr(modes, "beacon", None), getattr(modes, "navigation", None))
        if reader is not None
    )


def _apply_guide_range(controller, value):
    for reader in _guide_readers(controller):
        reader.max_distance = value


def _apply_guide_arrival(controller, value):
    for reader in _guide_readers(controller):
        reader.arrival_distance = value


def _play_cue(library, key):
    """A no-argument action bound to one cue. A named factory rather than a
    lambda in the comprehension because a lambda closing over the loop
    variable would give every entry the LAST cue's sound."""
    return lambda: library.play(key)


def _apply_autowalk_arrival(controller, value):
    reader = getattr(controller, "autowalk_reader", None)
    if reader is not None:
        reader.arrival_distance = value


# Toggles the lifecycle gates at poll time, keyed by setting. Named here
# rather than spelled into the lifecycle so one file describes the whole
# settings surface.
GATED_FEATURES = {
    "sounds.beacons": "npc_sounds",
    "sounds.footsteps": "terrain_footsteps",
    "sounds.blocked_cue": "blocked_movement",
    "speech.room_changes": "room_change",
    "speech.interaction_ready": "interaction_ready",
}


VALUELESS_KINDS = ("info", "sound")
"""Item kinds that carry no stored value. Named once so the store, the
loader and the menu cannot drift into disagreeing about which entries have
a value to read, save and speak."""


def build_categories(hotkeys=(), profile=XD_US_REV0, sound_library=None):
    """The whole menu, in the order it is navigated.

    Defaults are read from the constants the features actually use, so a
    retuned constant moves the default with it instead of silently
    disagreeing with a number typed a second time here.

    `hotkeys` is a sequence of (label, chord) for the Hotkeys reference
    category -- passed in because the chords are whatever the player
    configured on the command line, not what the profile suggests."""
    return (
        Category("Sounds", (
            Toggle(
                "sounds.beacons", "Entity beacons", True,
                description="Ambient sounds for nearby NPCs, doors, warps, "
                            "items and elevators."),
            Number(
                "sounds.beacon_volume", "Beacon volume",
                npc_beacons.PASSIVE_BEACON_GAIN_SCALE,
                0.0, 1.0, 0.05, unit="percent",
                applier=_apply_beacon_volume),
            Number(
                "sounds.warp_beacon_volume", "Warp beacon volume",
                npc_beacons.PASSIVE_BEACON_CATEGORY_GAIN.get("warp", 1.0),
                0.0, 1.0, 0.05, unit="percent",
                applier=_apply_warp_beacon_volume,
                description="Warps are the densest category; this trims "
                            "them alone."),
            Number(
                "sounds.beacon_range", "Beacon range",
                profile.npc_sound_max_distance,
                40.0, 240.0, 10.0, applier=_apply_beacon_range),
            Toggle(
                "sounds.footsteps", "Footstep cues", True,
                description="Synthetic footsteps that change with the "
                            "ground you are walking on."),
            Number(
                "sounds.footstep_volume", "Footstep volume",
                TerrainTonePlayer.STEP_GAIN,
                0.0, 1.0, 0.05, unit="percent",
                applier=_apply_footstep_volume),
            Toggle(
                "sounds.blocked_cue", "Blocked movement cue", False,
                description="Experimental: a tone when you walk into "
                            "something."),
        )),
        Category("Speech", (
            Toggle(
                "speech.room_changes", "Room announcements", True,
                description="Speak the room name when you enter a new one."),
            Toggle(
                "speech.interaction_ready", "Interaction cues", True,
                description="Speak when something in front of you can be "
                            "interacted with."),
            Toggle(
                "speech.auto_repeat", "Repeat selection when you stop", True,
                applier=_apply_auto_repeat,
                description="Re-announce the selected entity once you stand "
                            "still."),
            Number(
                "speech.auto_repeat_delay", "Repeat delay",
                profile.entity_nav_auto_repeat_seconds,
                0.5, 5.0, 0.5, unit="seconds",
                applier=_apply_auto_repeat_delay),
            Toggle(
                "speech.entity_location", "Direction and distance", True,
                applier=_apply_entity_location,
                description="Say which way a selected thing is and how far, "
                            "as in \"3 o'clock, distance 47\". Also on "
                            "ctrl+L while you play."),
        )),
        Category("Navigation", (
            Number(
                "navigation.guide_range", "Guide range",
                profile.audio_guide_max_distance,
                40.0, 240.0, 10.0, applier=_apply_guide_range,
                description="How far away the beacon and routed guide still "
                            "track a target."),
            Number(
                "navigation.arrival_distance", "Guide arrival distance",
                profile.audio_guide_arrival_distance,
                1.0, 12.0, 1.0, applier=_apply_guide_arrival,
                description="How close counts as having arrived."),
            Number(
                "navigation.autowalk_arrival", "Autowalk arrival distance",
                profile.default_autowalk_arrival_distance,
                1.0, 12.0, 1.0, applier=_apply_autowalk_arrival,
                description="How close autowalk stops to its target."),
        )),
        Category("Hotkeys", tuple(
            Info(f"hotkeys.{index}", label, spoken_chord(chord))
            for index, (label, chord) in enumerate(hotkeys)
        )),
    ) + _sound_library_categories(sound_library)


def _sound_library_categories(sound_library):
    """The Sound library heading, or nothing at all.

    Omitted entirely rather than added empty when no sound file could be
    read. `SettingsMenu._category_bounds` would already skip an empty
    category as a heading, but a category the store knows about and the
    menu refuses to show is two components disagreeing about what exists;
    not building it keeps one answer.

    Last on purpose. It is the one category a player visits to learn
    something rather than to change something, so it belongs after
    everything they might have opened the menu to adjust -- and `H` reaches
    it in one press from anywhere regardless."""
    cues = sound_library.cues if sound_library is not None else ()
    if not cues:
        return ()
    return (Category("Sound library", tuple(
        Sound(
            f"library.{cue.key}", cue.label,
            _play_cue(sound_library, cue.key),
            description=cue.description,
        )
        for cue in cues
    )),)


class SettingsStore:
    """Values, persistence, and applying them to the running companion.

    Never raises on a bad or missing file: a settings file that cannot be
    read or written must not stop the narrator, so both directions log and
    fall back to defaults. `on_save_error` is called once per failing save
    so the menu can say so out loud rather than silently forgetting.
    """

    def __init__(self, categories, path=None, logger=None,
                 on_save_error=None):
        self.categories = tuple(categories)
        self.path = path
        self.logger = logger
        self.on_save_error = on_save_error
        self.items = {}
        self.order = []
        for category in self.categories:
            for item in category.items:
                self.items[item.key] = item
                self.order.append(item.key)
        self.values = {
            key: item.default for key, item in self.items.items()
            if item.kind not in VALUELESS_KINDS
        }
        self.save_failed = False

    # -- persistence --------------------------------------------------

    def _read_document(self):
        if self.path is None or not self.path.is_file():
            return {}
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self._log("warning", "SETTINGS could not be read from %s: %s",
                      self.path, exc)
            return {}
        return document if isinstance(document, dict) else {}

    def load(self):
        """Read stored values, ignoring anything unrecognised.

        Unknown keys are dropped rather than kept: they are either from a
        newer build or a hand-edit, and carrying them forward would let a
        stale name silently outlive the setting it belonged to. Out-of-range
        numbers are clamped by `coerce`, not rejected."""
        stored = self._read_document().get(SETTINGS_SECTION)
        if not isinstance(stored, dict):
            return self
        for key, value in stored.items():
            item = self.items.get(key)
            if item is None or item.kind in VALUELESS_KINDS:
                self._log("debug", "SETTINGS ignoring unknown key %r", key)
                continue
            self.values[key] = item.coerce(value)
        self._log("info", "SETTINGS loaded from %s", self.path)
        return self

    def save(self):
        if self.path is None:
            return False
        document = self._read_document()
        document[SETTINGS_SECTION] = dict(self.values)
        try:
            self.path.write_text(
                json.dumps(document, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            self._log("warning", "SETTINGS could not be saved to %s: %s",
                      self.path, exc)
            if not self.save_failed and self.on_save_error is not None:
                self.on_save_error(exc)
            self.save_failed = True
            return False
        self.save_failed = False
        return True

    # -- values -------------------------------------------------------

    def get(self, key):
        return self.values.get(key, self.items[key].default)

    def enabled(self, key):
        """A gated toggle's state, defaulting to enabled for any key this
        build does not know about -- silence is never the safer default for
        an accessibility cue."""
        item = self.items.get(key)
        if item is None:
            return True
        return bool(self.values.get(key, item.default))

    def set(self, key, value, controller=None):
        item = self.items[key]
        value = item.coerce(value)
        self.values[key] = value
        self.apply_one(key, controller)
        self.save()
        return value

    # -- applying -----------------------------------------------------

    def apply_one(self, key, controller):
        item = self.items.get(key)
        if item is None or item.applier is None or controller is None:
            return
        try:
            item.applier(controller, self.values[key])
        except Exception as exc:
            # One misbehaving applier must not cost the player the rest of
            # their settings, and must never reach the poll loop.
            self._log("warning", "SETTINGS could not apply %s: %s", key, exc)

    def apply_all(self, controller):
        """Push every value into the live readers. Called after the
        lifecycle builds or rebuilds them."""
        for key in self.order:
            self.apply_one(key, controller)

    def _log(self, level, message, *args):
        if self.logger is not None:
            getattr(self.logger, level)(message, *args)
