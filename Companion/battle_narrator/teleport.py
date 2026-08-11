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

from .npc_beacons import Position
from .speech import SpeechEventClass

NO_SELECTION_MESSAGE = "No entity selected to teleport to."
INVALID_POSITION_MESSAGE = "Teleport target position is invalid."

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
    def __init__(self, memory, profile, npc_source, entity_nav, hotkey, speech, logger):
        self.memory = memory
        self.profile = profile
        self.npc_source = npc_source
        self.entity_nav = entity_nav
        self.hotkey = hotkey
        self.speech = speech
        self.logger = logger

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
        triggered = self.hotkey.poll()
        if not triggered:
            return
        category, entity = self._current_target()
        if entity is None:
            self._say(NO_SELECTION_MESSAGE)
            return
        pose = self.npc_source.player_pose()
        if category in NPC_LIKE_CATEGORIES:
            target = _npc_approach_position(
                entity.position, entity.interaction_distance, pose.position
            )
        else:
            target = Position(entity.position.x, pose.position.y, entity.position.z)
        if not all(math.isfinite(value) for value in (target.x, target.y, target.z)):
            self._say(INVALID_POSITION_MESSAGE)
            return
        model = self.npc_source.hero_model_address()
        data = struct.pack(">fff", target.x, target.y, target.z)
        self.memory.write_bytes(
            model + self.profile.model_position_offset, data, "teleport position write", 4
        )
        label = entity.label or category
        self._say(f"Teleported to {label}.")
