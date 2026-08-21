import logging
import unittest

from battle_narrator.player_facing_names import (
    build_room_names, player_facing_room_name)
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
        than a parallel table that could drift.

        Asserts the SHARED SOURCE, not a literal. The literal it used to
        hold ("Mt. Battle Pokemon Center, 1st floor.") went stale the moment
        the map-name prefix was dropped on 2026-08-12, even though the
        property this test exists to protect never broke -- which is exactly
        the drift it is supposed to catch, pointed the wrong way."""
        room_codes = {0x15: "D2_pc_1F", 0x9A: "M6_pc_1F"}
        room_names = build_room_names(room_codes)
        reader = self._reader(room_names)
        self.floors.floor_id = 0x15
        reader.poll_once()
        self.assertEqual(
            self.speech.calls,
            [f"{player_facing_room_name('D2_pc_1F')}."],
            "the room announcer and the door label have drifted apart")

    def test_the_map_name_is_not_repeated_on_a_building(self):
        """Project owner, 2026-08-12: "remove the map name from entities...
        especially from buildings list". Standing in Gateon Port, being told
        the Pokemon Center is the "Gateon Port Pokemon Center" is noise.

        Uses `M6_pc_1F` rather than `D2_pc_1F`, which was the example until
        2026-08-18. D2_pc_1F is now an EXACT_ROOM_NAMES entry ("Mt. Battle
        entrance" -- it is the Mt. Battle reception, not a Center at all),
        so it short-circuits the generic rule and can no longer demonstrate
        anything about it. The property itself is unchanged; only the
        example had to move to a room that still goes through the rule."""
        reader = self._reader(build_room_names({0x9A: "M6_pc_1F"}))
        self.floors.floor_id = 0x9A
        reader.poll_once()
        self.assertEqual(self.speech.calls, ["Pokemon Center, 1st floor."])

    def test_an_outdoor_area_still_announces_its_location(self):
        """The complement: outdoors the location IS the room's name, so
        dropping it there would leave the player with nothing."""
        reader = self._reader(build_room_names({0x84: "M3_out"}))
        self.floors.floor_id = 0x84
        reader.poll_once()
        self.assertEqual(self.speech.calls, ["Agate Village."])


if __name__ == "__main__":
    unittest.main()


class BootScreenSilenceTests(unittest.TestCase):
    """Floor 0 is the boot screens, not a room.

    Announcing it produced "Map: Map 0." and "Room 0." on top of the
    health-and-safety notice the player is being read, on the very first
    screen of the game. There is no room there, so there is nothing to
    name -- and the noise arrives at the one moment a new player is still
    working out what this thing does."""

    def test_floor_zero_says_nothing(self):
        speech = Speech()
        reader = RoomChangeReader(FloorSource(0), {}, speech, _logger())
        reader.poll_once()
        self.assertEqual(speech.calls, [])

    def test_an_unmapped_real_room_still_speaks(self):
        """The numeric fallback is still right for a genuine room whose
        name is missing -- the player needs to know they changed rooms."""
        speech = Speech()
        reader = RoomChangeReader(FloorSource(0x2A), {}, speech, _logger())
        reader.poll_once()
        self.assertEqual(speech.calls, ["Room 42."])

    def test_the_first_real_room_after_boot_is_not_swallowed(self):
        """Floor 0 is recorded as announced, so the room entered after it
        must not be skipped as an unchanged floor."""
        floor = FloorSource(0)
        speech = Speech()
        reader = RoomChangeReader(
            floor, {0x2A: "Pyrite Town"}, speech, _logger())
        reader.poll_once()
        self.assertEqual(speech.calls, [])
        floor.floor_id = 0x2A
        reader.poll_once()
        self.assertEqual(speech.calls, ["Pyrite Town."])


class TitleScreenTests(unittest.TestCase):
    """The title screen names the game, not the room.

    Live on 2026-08-20 the boot sequence announced "Map: pokemon logo.",
    "pokemon logo.", "Map: genius logo.", "genius logo.", "title." and
    "Map: title." -- six sentences naming publisher logos, each screen
    said twice, before the player had heard anything useful. The menu
    reader's own title focus produced nothing at all across that whole
    boot, which is why the announcement is made here instead."""

    def test_the_title_screen_says_the_game_and_how_to_start(self):
        speech = Speech()
        reader = RoomChangeReader(
            FloorSource(0x384), {0x384: "title"}, speech, _logger(),
            title_provider=lambda: "Pokemon XG: NeXt Gen. Press A to start.")
        reader.poll_once()
        self.assertEqual(
            speech.calls, ["Pokemon XG: NeXt Gen. Press A to start."])

    def test_it_never_says_the_word_title(self):
        speech = Speech()
        reader = RoomChangeReader(
            FloorSource(0x384), {0x384: "title"}, speech, _logger(),
            title_provider=lambda: "Pokemon XD: Gale of Darkness. Press A to start.")
        reader.poll_once()
        self.assertNotIn("title", " ".join(speech.calls).lower()[:20])

    def test_without_a_provider_it_says_nothing_rather_than_title(self):
        """Better silent than announcing a room called "title"."""
        speech = Speech()
        reader = RoomChangeReader(
            FloorSource(0x384), {0x384: "title"}, speech, _logger())
        reader.poll_once()
        self.assertEqual(speech.calls, [])

    def test_a_provider_that_fails_costs_the_line_not_the_reader(self):
        speech = Speech()
        reader = RoomChangeReader(
            FloorSource(0x384), {0x384: "title"}, speech, _logger(),
            title_provider=lambda: None)
        reader.poll_once()
        self.assertEqual(speech.calls, [])

    def test_the_logo_screens_are_silent(self):
        for floor_id, name in ((0x399, "pokemon logo"), (0x39A, "genius logo")):
            speech = Speech()
            reader = RoomChangeReader(
                FloorSource(floor_id), {floor_id: name}, speech, _logger())
            reader.poll_once()
            self.assertEqual(speech.calls, [], f"{name} was announced")

    def test_a_real_room_after_the_title_still_announces(self):
        floor = FloorSource(0x384)
        speech = Speech()
        reader = RoomChangeReader(
            floor, {0x384: "title", 0x2A: "Pyrite Town"}, speech, _logger(),
            title_provider=lambda: "Pokemon XD: Gale of Darkness. Press A to start.")
        reader.poll_once()
        floor.floor_id = 0x2A
        reader.poll_once()
        self.assertEqual(speech.calls[-1], "Pyrite Town.")
