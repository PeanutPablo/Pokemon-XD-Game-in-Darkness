"""Tells the player when pressing A will actually do something.

Replaces an earlier proximity-discovery cue ("NPC G nearby, behind-right").
That was made redundant by the planned sound beacons, which convey where
things are far better than speech can. What speech is still needed for is
the moment of actionability: you are close enough AND turned the right way,
so the button press will land.

Being in range is NOT sufficient. The game's own `peopleTalkCheck`
(0x802A3444) refuses to talk unless the player is facing the target within
`profile.talk_cone_degrees` -- 40 degrees, read out of updateChat's literal
argument, not guessed. Announcing on distance alone is what produced the
live "NPC G isn't interactable" report: the player stood 1.72 units away,
inside a 3.0 reach, but 149.6 degrees off, and the game ignored them.

Walk-into categories (warp, door, elevator) are excluded: they trigger by
entering them, not by pressing A, so a button prompt would be wrong.

Read-only.
"""
import time

from .entity_nav import facing_error, relative_geometry
from .speech import SpeechEventClass

WALK_INTO_CATEGORIES = frozenset({"warp", "door", "elevator"})


class InteractionReadyReader:
    """Announces "Press A to interact with X." on entering an interactable's
    usable zone, once, and re-arms after leaving it.

    Hysteresis applies to both gates, because the player is usually moving
    when this fires:

    - distance must exceed radius + `hysteresis` before the target counts
      as left, so walking the boundary cannot re-announce repeatedly;
    - facing must exceed the cone + `facing_hysteresis` before it counts as
      turned away, since facing changes with every step in a game with no
      turn-in-place.
    """

    def __init__(self, memory, profile, sources, speech, logger,
                 hysteresis=None, facing_hysteresis=None, clock=None):
        self.memory = memory
        self.profile = profile
        self.sources = sources
        self.speech = speech
        self.logger = logger
        self.hysteresis = (
            profile.interaction_ready_hysteresis
            if hysteresis is None else hysteresis)
        self.facing_hysteresis = (
            profile.interaction_ready_facing_hysteresis
            if facing_hysteresis is None else facing_hysteresis)
        self.context_valid = None
        self.floor_id = None
        self.announced_identity = None
        self.clock = clock or time.monotonic
        self.suppress_until = 0.0

    def clear(self, reason):
        if self.announced_identity is not None or self.context_valid is not None:
            self.logger.debug("INTERACTION READY cleared: %s", reason)
        self.context_valid = None
        self.floor_id = None
        self.announced_identity = None

    def _window_open(self):
        p = self.profile
        return self.memory.u32(
            p.window_manager + p.window_list_offset,
            "interaction ready window head",
        ) != 0

    def _current_pose(self):
        for source in self.sources.values():
            try:
                return source.player_pose()
            except Exception:
                continue
        return None

    def _radius(self, entity):
        if entity.interaction_distance is not None:
            return (entity.interaction_distance
                    + self.profile.interaction_collision_allowance)
        return self.profile.interaction_ready_default_radius

    def _usable(self, pose, entity, already):
        """Is pressing A on `entity` going to work right now? `already` is
        True for the entity currently announced, which widens both gates by
        the hysteresis margins."""
        if entity.category in WALK_INTO_CATEGORIES:
            return False
        horizontal, _, _, _ = relative_geometry(pose, entity.position)
        radius = self._radius(entity)
        if already:
            radius += self.hysteresis
        if horizontal > radius:
            return False
        error = facing_error(pose, entity.position)
        if error is None:
            # Facing unreadable: fall back to distance alone rather than
            # suppressing the cue entirely.
            return True
        cone = self.profile.talk_cone_degrees
        if already:
            cone += self.facing_hysteresis
        return error <= cone

    def _candidates(self, pose):
        found = []
        for source in self.sources.values():
            try:
                entities = source.entities()
            except Exception:
                continue
            for entity in entities:
                horizontal, _, _, _ = relative_geometry(pose, entity.position)
                found.append((horizontal, entity))
        return found

    def poll_once(self, dialogue_active=False):
        p = self.profile
        now = self.clock()
        floor_id = self.memory.u16(
            p.current_floor_id, "interaction ready floor id")
        valid = not self._window_open() and not dialogue_active
        if self.floor_id is not None and floor_id != self.floor_id:
            self.clear("map changed")
            self.suppress_until = (
                now + p.interaction_ready_map_change_grace)
        elif self.context_valid and not valid:
            self.clear("left free-roaming overworld control")
        self.context_valid = valid
        self.floor_id = floor_id
        if not valid:
            return
        if now < self.suppress_until:
            return

        pose = self._current_pose()
        if pose is None:
            return

        candidates = self._candidates(pose)
        # Keep the announced target while it is still usable under the
        # widened gates, so small movements do not retrigger.
        if self.announced_identity is not None:
            current = next(
                (e for _, e in candidates
                 if e.identity == self.announced_identity), None)
            if current is not None and self._usable(pose, current, True):
                return
            self.announced_identity = None

        usable = [(d, e) for d, e in candidates if self._usable(pose, e, False)]
        if not usable:
            return
        _, entity = min(usable, key=lambda item: item[0])
        self.announced_identity = entity.identity
        label = entity.label or "it"
        text = f"Press A to interact with {label}."
        self.speech.emit(
            SpeechEventClass.ENTITY_NAV, text,
            deduplicate=False, interrupt=False)
        self.logger.info("INTERACTION READY %s", text)
