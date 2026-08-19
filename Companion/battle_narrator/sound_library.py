"""A place to hear every sound the companion makes, and be told what it means.

The companion speaks a great deal, but it also makes eleven distinct
non-speech sounds -- six ambient category beacons, three navigation cues, a
footstep and a blocked-movement cue -- and until now the only way to learn
any of them was to encounter it in play and infer what had just happened.
That is backwards: a cue you cannot identify is noise, and a cue you
misidentify is worse than silence, because you act on it.

This module is the catalogue. Each entry pairs one real, in-use sound file
with the words for what it means, and can play it on demand. It is browsed
from the settings menu's own "Sound library" heading -- moving onto an
entry speaks the label and explanation, and Enter plays the sound -- so it
needs no key of its own and no new navigation idiom.

Two rules keep it honest
------------------------
**Only sounds that are actually wired up appear.** The paths are supplied
by the caller from the same variables it hands to the readers themselves
(`phase1b_app`), not re-derived here from a filename list. A catalogue
that could name a sound nothing plays would teach the player a cue that
never comes.

**A missing or unplayable file drops its entry, quietly.** The library must
not be the thing that stops the settings menu from opening -- the beacons
themselves already pre-flight their own files at startup with
`npc_beacons.check_playable` and fail loudly there, which is the right
place for that error.
"""
from dataclasses import dataclass
from pathlib import Path
import wave

from .npc_beacons import check_playable


@dataclass(frozen=True)
class SoundCue:
    """One entry: what it is called, what it means, and how to play it."""
    key: str
    label: str
    description: str
    path: Path
    gain: float = 1.0
    pitch: float = 1.0


CUE_TEXT = (
    ("beacon.npc", "Person beacon",
     "A person you can talk to is nearby. It repeats from their "
     "direction and grows louder as you get closer."),
    ("beacon.pokemart", "Poké Mart beacon",
     "The same, for a Poké Mart clerk you can buy from."),
    ("beacon.item", "Item beacon",
     "An item is lying on the ground nearby, waiting to be picked up."),
    ("beacon.door", "Door beacon",
     "An interior door -- one that leads between rooms inside a building. "
     "A building's outside entrance is a warp and sounds like one, not "
     "like this."),
    ("beacon.warp", "Warp beacon",
     "A warp: a building entrance, a staircase, or any other spot that "
     "moves you to another room. These are the quietest beacons, because "
     "a room can hold a great many of them."),
    ("beacon.elevator", "Elevator beacon",
     "An elevator."),
    ("guide.beacon", "Beacon on your selection",
     "What control plus G turns on: a straight-line beacon to the entity "
     "you have selected, ignoring walls."),
    ("guide.navigation", "Routed navigation guide",
     "What control plus N turns on: the same idea, but routed around "
     "obstacles instead of straight through them."),
    ("guide.waypoint", "Navigation waypoint reached",
     "Plays once each time the routed guide's next corner is reached, "
     "while it still has further to take you."),
    ("footstep", "Footstep",
     "One of your own footsteps. Its pitch changes with the ground you "
     "are walking on, so this is only one example of several."),
    ("blocked", "Blocked movement",
     "You walked into something and did not move."),
)
"""Every cue, in the order the library presents them: the ambient beacons
first (the ones heard constantly, without asking), then the navigation cues
(the ones a key press turns on), then movement.

The wording says what the sound MEANS, not what it sounds like. A blind
player is about to hear the sound itself; describing its timbre back to
them would be the one thing in this list they do not need."""

CUE_LABELS = {key: (label, description) for key, label, description in CUE_TEXT}
CUE_ORDER = tuple(key for key, _label, _description in CUE_TEXT)


def build_cues(paths, logger=None, gains=None, check=check_playable):
    """Catalogue entries for whichever of `paths` (key -> file) exist and
    can actually be rendered, in `CUE_ORDER`.

    Unknown keys are ignored rather than shown with a placeholder name: a
    sound the library cannot describe is one the player still could not
    identify after hearing it, which defeats the purpose."""
    gains = gains or {}
    cues = []
    for key in CUE_ORDER:
        path = paths.get(key)
        if path is None:
            continue
        path = Path(path)
        try:
            check(path)
        except (FileNotFoundError, OSError, ValueError, wave.Error) as exc:
            if logger is not None:
                logger.warning(
                    "SOUND LIBRARY omitting %s: %s", key, exc)
            continue
        label, description = CUE_LABELS[key]
        cues.append(SoundCue(
            key, label, description, path, gain=gains.get(key, 1.0)))
    return tuple(cues)


class SoundLibrary:
    """The catalogue plus the one thing it does: play an entry.

    `player_factory` rather than a player, because constructing the real
    one initialises the audio mixer, and the library is built while the
    settings store is loaded -- before anything has been attached and
    possibly before the player ever presses a key. Nothing is initialised
    until a sound is actually asked for."""

    def __init__(self, cues, player_factory, logger):
        self.cues = tuple(cues)
        self.player_factory = player_factory
        self.logger = logger
        self._player = None
        self._by_key = {cue.key: cue for cue in self.cues}

    def cue(self, key):
        return self._by_key.get(key)

    def player(self):
        if self._player is None:
            self._player = self.player_factory()
        return self._player

    def play(self, key):
        """Play one entry. Returns whether it played.

        Never raises: this runs from inside the settings menu's key
        handler, and an audio device that has gone away must cost the
        player one sound, not the menu they are standing in."""
        cue = self._by_key.get(key)
        if cue is None:
            return False
        try:
            self.player().play(cue.path, pan=0.0, pitch=cue.pitch,
                               gain=cue.gain)
        except Exception as exc:
            self.logger.warning(
                "SOUND LIBRARY could not play %s: %s", key, exc)
            return False
        self.logger.info("SOUND LIBRARY played %s (%s)", key, cue.path.name)
        return True
