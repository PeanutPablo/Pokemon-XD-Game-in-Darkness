"""Accessible status for Gateon Port's two moving bridges.

The retail M6_out script uses general flag 968 for the four combined
alignments.  Its ``pier_def`` function toggles CCD objects 23-31 and
``pier_move`` selects the next flag value from the control pad on which the
player is standing.  Bridge deck objects 58 and 59 are the southern and
northern walk surfaces respectively.
"""
from dataclasses import dataclass

from .pathfinding import build_room_geometry, walk_height_candidates
from .speech import SpeechEventClass


GATEON_OUTDOORS = 0x99
BRIDGE_FLAG = 968

ALIGNMENTS = {
    0: ("north and west", "east and west", False),
    1: ("south and west", "north and south", False),
    2: ("east and south", "east and west", True),
    3: ("east and north", "north and south", True),
}


@dataclass(frozen=True)
class ControlPad:
    bridge: str
    minimum_x: float
    maximum_x: float
    minimum_z: float
    maximum_z: float
    next_state: int

    def contains(self, x, z):
        return self.minimum_x <= x <= self.maximum_x and self.minimum_z <= z <= self.maximum_z


# Character::25 receives z1,x1,z2,x2 in this script.  These are the exact
# player regions which dominate each setFlag(968, next_state) call.
_RAW_PAD_TRANSITIONS = {
    3: ((130, -235, 140, -245, 2), (104, -210, 116, -220, 0),
        (-70, -235, -60, -245, 2), (-120, -235, -110, -245, 0)),
    0: ((104, -260, 116, -270, 3), (130, -235, 140, -245, 1),
        (-100, -260, -80, -270, 3), (-95, -210, -80, -220, 1)),
    1: ((80, -235, 90, -245, 0), (104, -260, 116, -270, 2),
        (-120, -235, -110, -245, 0), (-70, -235, -60, -245, 2)),
    2: ((104, -210, 116, -220, 1), (80, -235, 90, -245, 3),
        (-95, -210, -80, -220, 1), (-100, -260, -80, -270, 3)),
}


def control_pads(state):
    pads = []
    for z1, x1, z2, x2, next_state in _RAW_PAD_TRANSITIONS.get(state, ()):
        center_z = (z1 + z2) / 2
        pads.append(ControlPad(
            "northern" if center_z > 0 else "southern",
            min(x1, x2), max(x1, x2), min(z1, z2), max(z1, z2), next_state))
    return tuple(pads)


def alignment_text(state, prefix="Current alignment"):
    north, south, center_open = ALIGNMENTS[state]
    center = "open" if center_open else "closed"
    return (f"{prefix}: northern bridge connects {north}; southern bridge connects "
            f"{south}; center passage is {center}.")


class GateonBridgeReader:
    def __init__(self, memory, profile, flag_reader, pose_source,
                 walk_triangles, wall_triangles, speech, logger):
        self.memory = memory
        self.profile = profile
        self.flag_reader = flag_reader
        self.pose_source = pose_source
        self.speech = speech
        self.logger = logger
        self.geometry = build_room_geometry(walk_triangles, wall_triangles)
        self.last_room = None
        self.last_state = None
        self.last_deck = None
        self.last_pad = None

    def _deck_under_player(self, pose):
        candidates = walk_height_candidates(
            self.geometry, pose.position.x, pose.position.z)
        if not candidates:
            return None
        closest = min(candidates, key=lambda value: abs(value.height - pose.position.y))
        return {58: "southern", 59: "northern"}.get(closest.triangle.entry_index)

    @staticmethod
    def _pad_at(state, pose):
        for pad in control_pads(state):
            if pad.contains(pose.position.x, pose.position.z):
                return pad
        return None

    def _speak(self, text, interrupt=True):
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=interrupt)
        self.logger.info("GATEON BRIDGE %s", text)

    def clear(self):
        self.last_state = self.last_deck = self.last_pad = None

    def poll_once(self):
        room = self.memory.u16(self.profile.current_floor_id, "Gateon bridge room")
        if room != GATEON_OUTDOORS:
            if self.last_room == GATEON_OUTDOORS:
                self.clear()
            self.last_room = room
            return
        pose = self.pose_source.player_pose()
        state = self.flag_reader.value(BRIDGE_FLAG)
        if state not in ALIGNMENTS:
            self.logger.debug("GATEON BRIDGE invalid flag 968 value %r", state)
            return
        deck = self._deck_under_player(pose)
        pad = self._pad_at(state, pose)
        pad_identity = None if pad is None else (pad.bridge, pad.next_state)

        if self.last_room != room:
            self._speak("Gateon Port bridge system. " + alignment_text(state), False)
        elif self.last_state is not None and state != self.last_state:
            self._speak("Bridges moved. " + alignment_text(state))

        if deck != self.last_deck:
            if deck is not None:
                self._speak(f"You are on the {deck} bridge. " + alignment_text(state))
            elif self.last_deck is not None:
                self._speak(f"You stepped off the {self.last_deck} bridge.")

        if pad_identity != self.last_pad and pad is not None:
            self._speak(
                f"{pad.bridge.capitalize()} bridge control pad. Activating it will change "
                f"the system to alignment {pad.next_state + 1}. "
                + alignment_text(pad.next_state, "After activation"))

        self.last_room = room
        self.last_state = state
        self.last_deck = deck
        self.last_pad = pad_identity
