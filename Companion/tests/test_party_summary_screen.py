import logging
import unittest

from battle_narrator.memory import MemoryError as MemErr, MemoryReader
from battle_narrator.party import PartyMove, PartySlot, PartyStats
from battle_narrator.party_summary_screen import PartySummaryScreenReader
from battle_narrator.profile import XD_US_REV0


class WindowBackend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + offset, 0) for offset in range(size))


def be16(value):
    return value.to_bytes(2, "big")


def be32(value):
    return value.to_bytes(4, "big")


class Speech:
    def __init__(self): self.calls = []
    def emit(self, event, text, interrupt=None):
        self.calls.append((event, text, interrupt))


class Source:
    def __init__(self, slot): self.slot = slot
    def slot_for_pointer(self, pointer): return self.slot


class FailingSource:
    def slot_for_pointer(self, pointer):
        raise MemErr("boom")


def sample_slot(ability_name="RUN AWAY", ability_description="Makes escaping easier."):
    return PartySlot(
        0, "EEVEE", 10, 29, 33, 0,
        PartyStats(18, 18, 14, 18, 18),
        (PartyMove("TACKLE", 35), PartyMove("TAIL WHIP", 29)),
        "LEON", 1305, "Bashful", 0,
        ability_name, ability_description,
    )


class PartySummaryScreenReaderTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.speech = Speech()
        self.source = Source(sample_slot())
        self.reader = PartySummaryScreenReader(
            self.memory, self.profile, self.source, self.speech,
            logging.getLogger("party-summary-screen-test"))

    def _put_window(self, address, menu_id, page, next_address=0):
        p = self.profile
        self.backend.put(address + p.window_menu_id_offset, be32(menu_id))
        self.backend.put(address + p.window_next_offset, be32(next_address))
        self.backend.put(address + p.party_summary_page_offset, bytes([page]))

    def _set_head(self, address):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(address))

    def test_screen_not_open_is_silent(self):
        self._set_head(0)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])
        self.assertFalse(self.reader.active)

    def test_other_menu_open_is_silent(self):
        self._put_window(0x80700000, 70, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_opening_on_info_page_announces_full_info(self):
        self._put_window(0x80700000, 94, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        expected = (
            "Info. Eevee, level 10. Bashful nature. "
            "Original Trainer: Leon. Experience: 1305 points. No item held."
        )
        self.assertEqual(self.speech.calls[-1][1], expected)

    def test_info_page_with_held_item_reports_item_id(self):
        held = PartySlot(
            0, "EEVEE", 10, 29, 33, 0,
            PartyStats(18, 18, 14, 18, 18),
            (PartyMove("TACKLE", 35),), "LEON", 1305, "Bashful", 5,
            "RUN AWAY", "Makes escaping easier.",
        )
        self.reader.party_source = Source(held)
        self._put_window(0x80700000, 94, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertIn("Holding item 5.", self.speech.calls[-1][1])

    def test_status_page_announces_full_stats_and_ability(self):
        self._put_window(0x80700000, 94, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        expected = (
            "Status. Eevee, level 10, 29 of 33 HP, 88 percent. "
            "Attack 18, Defense 18, Special Attack 14, Special Defense 18, Speed 18. "
            "Ability: Run Away. Makes escaping easier."
        )
        self.assertEqual(self.speech.calls[-1][1], expected)

    def test_status_page_without_resolved_ability_omits_ability_sentence(self):
        self.reader.party_source = Source(sample_slot(ability_name="", ability_description=""))
        self._put_window(0x80700000, 94, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertNotIn("Ability:", self.speech.calls[-1][1])

    def test_status_page_speaks_heart_gauge_for_shadow_pokemon(self):
        shadow = PartySlot(
            0, "TEDDIURSA", 10, 29, 33, 0,
            PartyStats(18, 18, 14, 18, 18),
            (PartyMove("TACKLE", 35),), "LEON", 1305, "Bashful", 0,
            "", "", 100,
        )
        self.reader.party_source = Source(shadow)
        self._put_window(0x80700000, 94, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertIn(
            "Heart Gauge: fully open, ready to purify.",
            self.speech.calls[-1][1])

    def test_status_page_speaks_partial_heart_gauge_percentage(self):
        shadow = PartySlot(
            0, "TEDDIURSA", 10, 29, 33, 0,
            PartyStats(18, 18, 14, 18, 18),
            (PartyMove("TACKLE", 35),), "LEON", 1305, "Bashful", 0,
            "", "", 75,
        )
        self.reader.party_source = Source(shadow)
        self._put_window(0x80700000, 94, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertIn("Heart Gauge: 75 percent open.", self.speech.calls[-1][1])

    def test_status_page_omits_heart_gauge_for_non_shadow_pokemon(self):
        self._put_window(0x80700000, 94, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertNotIn("Heart Gauge", self.speech.calls[-1][1])

    def test_moves_page_announces_moves(self):
        self._put_window(0x80700000, 94, 2)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls[-1][1], "Moves. Tackle, 35 P P; Tail Whip, 29 P P.")

    def test_moves_page_reads_full_list_then_each_focused_candidate(self):
        summary, learning = 0x80700000, 0x80700100
        self._put_window(summary, 94, 2, next_address=learning)
        self._put_window(learning, self.profile.move_learning_menu_id, 0)
        self._set_head(summary)
        self.backend.put(
            learning + self.profile.window_cursor_offset, be16(0)
        )
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls[-1][1],
            "Moves. Tackle, 35 P P; Tail Whip, 29 P P.",
        )
        # The initially focused row is already part of the overview. Moving
        # to another row announces just that row.
        self.backend.put(
            learning + self.profile.window_cursor_offset, be16(1)
        )
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls[-1][1], "Tail Whip, 29 P P.")

    def test_ribbons_page_announces_page_name(self):
        self._put_window(0x80700000, 94, 3)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls[-1][1], "Ribbons page.")

    def test_page_change_triggers_new_announcement(self):
        self._put_window(0x80700000, 94, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self._put_window(0x80700000, 94, 1)
        self.reader.poll_once()
        self.assertEqual(len(self.speech.calls), 2)
        self.assertTrue(self.speech.calls[-1][1].startswith("Status."))

    def test_same_page_does_not_repeat(self):
        self._put_window(0x80700000, 94, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.reader.poll_once()
        self.assertEqual(len(self.speech.calls), 1)

    def test_reopening_same_page_reannounces(self):
        self._put_window(0x80700000, 94, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self._set_head(0)
        self.reader.poll_once()
        self.assertFalse(self.reader.active)
        self._put_window(0x80700000, 94, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(len(self.speech.calls), 2)

    def test_empty_party_is_silent(self):
        self.reader.party_source = Source(None)
        self._put_window(0x80700000, 94, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_read_failure_is_silent(self):
        self.reader.party_source = FailingSource()
        self._put_window(0x80700000, 94, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])


if __name__ == "__main__":
    unittest.main()
