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
from .npc_beacons import (
    BOOT_SCREEN_LABELS, NO_ROOM_FLOOR_ID, TITLE_SCREEN_FLOOR_ID)
from .speech import SpeechEventClass


class RoomChangeReader:
    def __init__(self, floor_source, room_names, speech, logger,
                 title_provider=None):
        self.floor_source = floor_source
        self.room_names = dict(room_names)
        self.title_provider = title_provider
        """Returns the title-screen line -- which game this is and how to
        start it -- or None. Injected rather than built here because
        naming the game means reading the abilities table's shape out of
        the running code, which is `menus`' business and not this
        module's.

        The title screen is announced HERE rather than by the menu reader
        because the menu reader's own title focus does not fire: across a
        full live boot on 2026-08-20 it produced no title announcement at
        all, while this reader correctly reported the room as "title".
        Rather than leave the first screen of the game unnamed while that
        is investigated, the announcement is made where it demonstrably
        works."""
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
        if floor_id == TITLE_SCREEN_FLOOR_ID:
            title = self.title_provider() if self.title_provider else None
            if title:
                self.speech.emit(
                    SpeechEventClass.ENTITY_NAV, title, deduplicate=False)
                self.logger.info("TITLE SCREEN %r", title)
            return
        if floor_id == NO_ROOM_FLOOR_ID:
            # Before any map is loaded. Nothing is on screen to name, and
            # "Room 0" talked over the health notice. Recorded as
            # announced so the first real screen is not skipped as
            # unchanged.
            #
            # The publisher logos are NOT suppressed here. They were, and
            # the project owner asked for them back: a blind player
            # sitting through two silent splash screens has no way to tell
            # them from a game that has hung. Their duplicate "Map:" line
            # stays suppressed -- saying each of them twice was the actual
            # complaint.
            return
        name = BOOT_SCREEN_LABELS.get(floor_id) or self.room_names.get(floor_id)
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
