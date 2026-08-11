import logging
import unittest

from battle_narrator.player_facing_names import build_room_names
from battle_narrator.room_announcer import RoomChangeReader


class Speech:
    def __init__(self):
        self.calls = []

    def emit(self, event, text, deduplicate=False, interrupt=False):
        self.calls.append(text)


class FloorSource:
    def __init__(self, floor_id=None):
        self.floor_id = floor_id

    def current_floor_id(self):
        return self.floor_id


def _logger():
    return logging.getLogger("room-announcer-test")


class RoomChangeReaderTests(unittest.TestCase):
    def setUp(self):
        self.speech = Speech()
        self.floors = FloorSource()

    def _reader(self, room_names=None):
        return RoomChangeReader(
            self.floors,
            {0x85: "Agate Village Pokemon Center, 1st floor",
             0x84: "Agate Village"} if room_names is None else room_names,
            self.speech, _logger())

    def test_entering_a_room_announces_its_name(self):
        reader = self._reader()
        self.floors.floor_id = 0x85
        reader.poll_once()
        self.assertEqual(
            self.speech.calls, ["Agate Village Pokemon Center, 1st floor."])

    def test_staying_in_the_same_room_announces_once(self):
        reader = self._reader()
        self.floors.floor_id = 0x85
        for _ in range(20):
            reader.poll_once()
        self.assertEqual(len(self.speech.calls), 1)

    def test_changing_rooms_announces_each_change(self):
        reader = self._reader()
        for floor_id in (0x85, 0x84, 0x85):
            self.floors.floor_id = floor_id
            reader.poll_once()
            reader.poll_once()
        self.assertEqual(self.speech.calls, [
            "Agate Village Pokemon Center, 1st floor.",
            "Agate Village.",
            "Agate Village Pokemon Center, 1st floor.",
        ])

    def test_an_unmapped_room_still_reports_the_change(self):
        """An XG-added room must not silently announce nothing -- the player
        still needs to know they changed rooms, and the raw ID is real
        information for reporting the gap. It must never be given an
        invented name."""
        reader = self._reader()
        self.floors.floor_id = 0x777
        reader.poll_once()
        self.assertEqual(self.speech.calls, ["Room 1911."])

    def test_an_unreadable_floor_is_silent(self):
        reader = self._reader()
        self.floors.floor_id = None
        reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_clear_re_announces_the_current_room(self):
        """After a disconnect/reattach the player should be told where they
        are, not met with silence because the ID matches what a previous
        session announced."""
        reader = self._reader()
        self.floors.floor_id = 0x85
        reader.poll_once()
        reader.clear("lifecycle reset")
        reader.poll_once()
        self.assertEqual(len(self.speech.calls), 2)

    def test_names_match_the_ones_entity_nav_speaks_for_doors(self):
        """The project owner asked specifically for the entity-nav names, so
        that walking through a door announced as X arrives somewhere that
        calls itself X. Pinning that they come from the same function rather
        than a parallel table that could drift."""
        room_codes = {0x15: "D2_pc_1F", 0x9A: "M6_pc_1F"}
        reader = self._reader(build_room_names(room_codes))
        self.floors.floor_id = 0x15
        reader.poll_once()
        self.assertEqual(
            self.speech.calls, ["Mt. Battle Pokemon Center, 1st floor."])


if __name__ == "__main__":
    unittest.main()
