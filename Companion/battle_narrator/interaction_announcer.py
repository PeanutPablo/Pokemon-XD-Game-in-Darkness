"""Announces what interaction the player just started -- "Talked to
<NPC>.", "Opened <target>.", etc. -- reusing the same entity sources
entity_nav.py already resolves names/positions from, rather than adding
a second, competing name-resolution path.

Two independent trigger signals, since a single "free-roam lost" check
does not cover every interaction type:

- NPC dialogue, PC use, and sign text all open a real window (menu_id
  82, per dialogue.py) or otherwise take over free-roam control before
  any room ever changes -- detected the same way entity_nav.py's own
  `_refresh_context` does (not by reading entity_nav's state directly,
  to avoid coupling to or disturbing an already-working, tested
  reader; this module keeps its own independent copy of that check).
- Doors, warps, and elevators change the room directly, often with no
  window ever appearing at all -- detected via `current_floor_id`
  changing, exactly as entity_nav.py's own "map changed" clear reason
  already does. Critically, the player's position at the MOMENT the
  floor changes is already in the new room, useless for finding what
  triggered the transition -- so this module caches the player's last
  known position every poll and uses that cached, pre-transition
  position to find the trigger once the floor id changes.

Disambiguation: whichever known entity (across all watched categories)
is closest to the relevant position and within a trigger radius is
assumed to be the cause. NPCs use their own real, per-entity
`interaction_distance`; door/warp/elevator/PC/sign records don't carry
one (see entities.py -- only treasure records set it), so those use
`DEFAULT_TRIGGER_RADIUS`, a practical disambiguation heuristic (not a
claim about real game data) informally consistent with the ~7-unit
range already observed live to trigger a PC interaction elsewhere this
project. Unverified, expected to need live tuning. If nothing is close
enough, stays silent rather than guessing.
"""
from .entity_nav import relative_geometry
from .speech import SpeechEventClass

DEFAULT_TRIGGER_RADIUS = 10.0

CATEGORY_VERBS = {
    "npc": "Talked to",
    "door": "Opened",
    "warp": "Entered",
    "elevator": "Used",
    "pc": "Used",
    "sign": "Read",
}

FLOOR_CHANGE_CATEGORIES = frozenset({"door", "warp", "elevator"})
WINDOW_OPEN_CATEGORIES = frozenset({"npc", "pc", "sign"})


class InteractionAnnouncer:
    def __init__(self, memory, profile, sources, speech, logger,
                 default_trigger_radius=DEFAULT_TRIGGER_RADIUS):
        self.memory = memory
        self.profile = profile
        self.sources = sources
        self.speech = speech
        self.logger = logger
        self.default_trigger_radius = default_trigger_radius
        self.context_valid = None
        self.floor_id = None
        self.last_pose = None

    def clear(self, reason):
        if self.context_valid is not None:
            self.logger.debug("INTERACTION ANNOUNCER cleared: %s", reason)
        self.context_valid = None
        self.floor_id = None
        self.last_pose = None

    def _window_open(self):
        p = self.profile
        pointer = self.memory.u32(
            p.window_manager + p.window_list_offset,
            "interaction announcer window head",
        )
        return pointer != 0

    def _current_pose(self):
        for source in self.sources.values():
            try:
                return source.player_pose()
            except Exception:
                continue
        return None

    def _closest_trigger(self, pose, categories):
        if pose is None:
            return None
        best = None
        best_distance = None
        for category in categories:
            source = self.sources.get(category)
            verb = CATEGORY_VERBS.get(category)
            if source is None or verb is None:
                continue
            try:
                entities = source.entities()
            except Exception:
                continue
            for entity in entities:
                horizontal, _, _, _ = relative_geometry(pose, entity.position)
                radius = (
                    entity.interaction_distance
                    if entity.interaction_distance is not None
                    else self.default_trigger_radius
                )
                if horizontal > radius:
                    continue
                if best_distance is None or horizontal < best_distance:
                    best_distance = horizontal
                    best = entity
        return best

    def _announce(self, entity):
        verb = CATEGORY_VERBS[entity.category]
        label = entity.label or "something"
        text = f"{verb} {label}."
        self.speech.emit(
            SpeechEventClass.ENTITY_NAV, text, deduplicate=False, interrupt=True)
        self.logger.info("INTERACTION %s", text)

    def poll_once(self, dialogue_active=False):
        p = self.profile
        floor_id = self.memory.u16(
            p.current_floor_id, "interaction announcer floor id")
        window_open = self._window_open()
        valid = not window_open and not dialogue_active
        pose = self._current_pose()

        if self.floor_id is not None and floor_id != self.floor_id:
            trigger = self._closest_trigger(
                self.last_pose, FLOOR_CHANGE_CATEGORIES)
            if trigger is not None:
                self._announce(trigger)
        elif self.context_valid and not valid:
            trigger = self._closest_trigger(pose, WINDOW_OPEN_CATEGORIES)
            if trigger is not None:
                self._announce(trigger)

        self.context_valid = valid
        self.floor_id = floor_id
        if pose is not None:
            self.last_pose = pose
