"""Speak the room's name whenever the player enters a different room.

Split out of `npc_beacons.NPCSoundReader` (2026-08-04). The announcement
used to live inside that reader, so when the proximity beacons were muted at
the project owner's request (`npc_sound_factory=None` in `phase1b_app.py`)
room announcements went silent with them -- collateral damage, not a
decision. Live evidence: on 2026-08-04 the project owner changed rooms four
times in two minutes and the log shows only `ENTITY NAV cleared: map
changed` each time, with nothing spoken.

Owning it here means the two features can be enabled independently, and a
room name no longer depends on any NPC being present.

Names come from `player_facing_names.player_facing_room_name`, the SAME
source entity-nav already uses for its warp/door/elevator labels -- at the
project owner's explicit request, so that walking through a door announced
as "Mt. Battle Pokemon Center, 1st floor" arrives in a room that calls
itself exactly that. The old announcement built its own separate
description (`room_description`, a partial re-implementation with its own
`MAP_NAMES` table and its own "1F" -> "1 F" string surgery) and so could
disagree with the door the player had just walked through.

Read-only: one floor-ID read per poll, nothing else.
"""
from .speech import SpeechEventClass


class RoomChangeReader:
    def __init__(self, floor_source, room_names, speech, logger):
        self.floor_source = floor_source
        self.room_names = dict(room_names)
        self.speech = speech
        self.logger = logger
        self.announced_floor_id = None

    def clear(self, reason):
        """Forget which room was last announced, so the next poll speaks the
        current one again. Called on lifecycle reset -- after a
        disconnect/reattach the player deserves to be told where they are
        rather than being met with silence because the ID happens to match
        what a previous session announced."""
        if self.announced_floor_id is not None:
            self.logger.debug("ROOM CHANGE CLEAR reason=%s", reason)
        self.announced_floor_id = None

    def poll_once(self):
        floor_id = self.floor_source.current_floor_id()
        if floor_id is None or floor_id == self.announced_floor_id:
            return
        self.announced_floor_id = floor_id
        name = self.room_names.get(floor_id)
        if not name:
            # An XG-added or otherwise unmapped room. Say something true and
            # useful rather than nothing -- the player still needs to know
            # they changed rooms, and the numeric ID is real information for
            # reporting the gap. Never invent a name.
            name = f"Room {floor_id}"
            self.logger.info("ROOM CHANGE unmapped floor=0x%X", floor_id)
        self.speech.emit(
            SpeechEventClass.ENTITY_NAV, f"{name}.", deduplicate=False)
        self.logger.info(
            "ROOM CHANGE floor=0x%X name=%r", floor_id, name)
