"""Single-purpose, single-write teleport: moves the player to a position
entity-nav has ALREADY resolved for its current selection -- never a
free-typed coordinate. Built at the project owner's explicit request and
explicit acceptance of the risk this represents, after being asked to
choose between this and staying fully read-only (they chose to build it).

This is the ONLY place in this entire project that writes emulated
memory. Every other feature -- battle narration, dialogue, menus, entity
navigation, the audio guide -- is strictly read-only, by long-standing,
repeatedly-reinforced project design ("never send input, never move the
player, never touch the emulated controller"). This module is a
deliberate, explicit exception, scoped as narrowly as possible:

- Teleport targets are restricted to whatever entity-nav's *current
  selection* already resolves to. You cannot teleport anywhere entity-nav
  doesn't already know about, and entity-nav only ever surfaces entities
  in the player's CURRENT room -- so this can only move the player within
  a room they're already physically in, never to a different, unprepared
  area. That bounds the blast radius considerably compared to a general
  "warp anywhere" feature: it cannot skip story-critical rooms or land
  the player somewhere the game never expected them to be able to reach
  yet.
- For "npc" category entities, the live-read ground-level Y is used, but
  the X/Z landing point is pulled back along the line from the player's
  current position toward the NPC, stopping short by the NPC's own
  interaction_distance. NPCs (unlike warps/doors/elevators) have real
  collision -- landing exactly on their coordinates puts the player
  inside that collision and the game immediately shoves them back out,
  which looked like "teleport does nothing" for this category
  specifically (confirmed: warps, which have no solid body, worked fine
  from the first implementation).
- For every other category (door/elevator/warp/healing/item), the
  entity's Y coordinate is deliberately NOT used -- those positions are
  CCD collision-trigger centroids, and earlier investigation this session
  confirmed they can sit at an arbitrary height unrelated to actual floor
  level (e.g. an elevator's CCD region resolving to y=15 while the floor
  is y=0). The player's own current Y is used instead, so teleporting to
  one of these categories can't drop the player into the air or through
  the floor.
- Landing on a warp/door's resolved position is landing on the same
  trigger point a real walk-in would reach, not bypassing it -- room-
  entry/warp logic still fires from proximity, the same as it would for
  a real, player-walked approach.
"""
import math
import struct
import time

from .memory import MemoryError as GameMemoryError
from .npc_beacons import Position
from .speech import SpeechEventClass

NO_SELECTION_MESSAGE = "No entity selected to teleport to."
INVALID_POSITION_MESSAGE = "Teleport target position is invalid."
UNREADABLE_MESSAGE = "Cannot teleport right now, try again."
DID_NOT_TAKE_MESSAGE = "Teleport did not take. You did not move."

VERIFY_AFTER_SECONDS = 0.35
"""How long to wait before checking the player actually ended up there.

Not optional, and not zero. The write goes straight into MEM1, so reading
the position back immediately returns the bytes we just wrote -- which is
why this reported success for every teleport it ever performed, including
the ones the player watched do nothing. Only after the game has run a few
frames does the position reflect what the ENGINE thinks, which is what
decides whether the player really moved.

0.35s is long enough for the engine to resolve collision and shove the
player back out if it is going to, and short enough that the correction
still arrives while the player is wondering."""

VERIFY_TOLERANCE = 8.0
"""How far from the requested point still counts as having arrived.

Generous on purpose. The engine legitimately adjusts a landing: it
resolves collision, snaps to the floor, and the player may already be
walking. The question this answers is "did anything happen at all", not
"did it land on the exact float"."""

NPC_LIKE_CATEGORIES = frozenset({"npc"})
DEFAULT_APPROACH_BUFFER = 6.0
MINIMUM_APPROACH_BUFFER = 1.0


def _npc_approach_position(entity_position, entity_interaction_distance, player_position):
    """A point short of entity_position by the NPC's own interaction
    distance, approached along the line from the player's current
    position -- avoids landing inside the NPC's collision (see module
    docstring)."""
    buffer = MINIMUM_APPROACH_BUFFER
    if entity_interaction_distance and entity_interaction_distance > 0:
        buffer = max(MINIMUM_APPROACH_BUFFER, entity_interaction_distance * 0.8)
    dx = entity_position.x - player_position.x
    dz = entity_position.z - player_position.z
    horizontal = math.hypot(dx, dz)
    if horizontal < 1e-6:
        return Position(entity_position.x, entity_position.y, entity_position.z + buffer)
    scale = max(0.0, horizontal - buffer) / horizontal
    return Position(
        player_position.x + dx * scale,
        entity_position.y,
        player_position.z + dz * scale,
    )


class TeleportReader:
    def __init__(self, memory, profile, npc_source, entity_nav, hotkey, speech,
                 logger, clock=time.monotonic):
        self.memory = memory
        self.profile = profile
        self.npc_source = npc_source
        self.entity_nav = entity_nav
        self.hotkey = hotkey
        self.speech = speech
        self.logger = logger
        self.clock = clock
        self._pending = None
        """(target, label, deadline) for a teleport whose outcome has not
        been checked yet, or None. See `VERIFY_AFTER_SECONDS`."""

    def _say(self, text):
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, deduplicate=False, interrupt=True)
        self.logger.info("TELEPORT %s", text)

    def _current_target(self):
        state = self.entity_nav.state
        if state.category_key is None or state.selected_identity is None:
            return None, None
        source = self.entity_nav.sources.get(state.category_key)
        if source is None:
            return None, None
        entities = {entity.identity: entity for entity in source.entities()}
        return state.category_key, entities.get(state.selected_identity)

    def poll_once(self):
        self._check_pending()
        triggered = self.hotkey.poll()
        if not triggered:
            return
        category, entity = self._current_target()
        if entity is None:
            self._say(NO_SELECTION_MESSAGE)
            return
        try:
            pose = self.npc_source.player_pose()
        except GameMemoryError as problem:
            # Same reason as the hero-model read below: the lifecycle
            # catches this and logs it at debug, so an unreadable pose used
            # to mean the key did nothing and said nothing.
            self.logger.debug("TELEPORT player pose unreadable: %s", problem)
            self._say(UNREADABLE_MESSAGE)
            return
        if category in NPC_LIKE_CATEGORIES:
            target = _npc_approach_position(
                entity.position, entity.interaction_distance, pose.position
            )
        else:
            target = Position(entity.position.x, pose.position.y, entity.position.z)
        if not all(math.isfinite(value) for value in (target.x, target.y, target.z)):
            self._say(INVALID_POSITION_MESSAGE)
            return
        try:
            model = self.npc_source.hero_model_address()
        except GameMemoryError as problem:
            # Said, not swallowed. The lifecycle catches this and logs it at
            # debug, so before this the player pressed the key and got
            # silence -- indistinguishable from the key not registering.
            self.logger.debug("TELEPORT hero model unreadable: %s", problem)
            self._say(UNREADABLE_MESSAGE)
            return
        data = struct.pack(">fff", target.x, target.y, target.z)
        self.memory.write_bytes(
            model + self.profile.model_position_offset, data, "teleport position write", 4
        )
        label = entity.label or category
        self._say(f"Teleported to {label}.")
        # Confirmed now, checked shortly. The confirmation stays immediate
        # because a delayed one reads as an unresponsive key; only a FAILURE
        # produces a second message, so an ordinary teleport is still one
        # sentence.
        self._pending = (target, label, self.clock() + VERIFY_AFTER_SECONDS)
        self.logger.info(
            "TELEPORT wrote category=%s label=%s target=(%.2f, %.2f, %.2f)",
            category, label, target.x, target.y, target.z)

    def _check_pending(self):
        """Did the player actually end up where they were sent?

        This is the question the module never asked. It wrote the position,
        announced success and moved on, so every failure mode the docstring
        above describes -- landing inside collision and being shoved out,
        landing at a height the room does not have -- was reported to the
        player as a teleport that worked."""
        if self._pending is None:
            return
        target, label, deadline = self._pending
        if self.clock() < deadline:
            return
        self._pending = None
        try:
            landed = self.npc_source.player_pose().position
        except GameMemoryError as problem:
            # Cannot tell either way. Saying nothing is right: the player
            # already heard the confirmation, and inventing a failure from
            # a bad read would be its own defect.
            self.logger.debug("TELEPORT could not verify: %s", problem)
            return
        distance = math.dist(
            (landed.x, landed.y, landed.z), (target.x, target.y, target.z))
        if distance <= VERIFY_TOLERANCE:
            self.logger.info("TELEPORT verified label=%s off_by=%.2f",
                             label, distance)
            return
        self.logger.warning(
            "TELEPORT DID NOT TAKE label=%s off_by=%.2f "
            "target=(%.2f, %.2f, %.2f) landed=(%.2f, %.2f, %.2f)",
            label, distance, target.x, target.y, target.z,
            landed.x, landed.y, landed.z)
        self._say(DID_NOT_TAKE_MESSAGE)
