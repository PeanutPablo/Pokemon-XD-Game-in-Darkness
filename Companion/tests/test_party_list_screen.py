import logging
import unittest

from battle_narrator.memory import MemoryError as MemErr, MemoryReader
from battle_narrator.party import PartyMove, PartySlot, PartyStats
from battle_narrator.party_list_screen import PartyListScreenReader
from battle_narrator.profile import XD_US_REV0


class WindowBackend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + offset, 0) for offset in range(size))


def be32(value):
    return value.to_bytes(4, "big")


class Speech:
    def __init__(self): self.calls = []
    def emit(self, event, text, interrupt=None):
        self.calls.append((event, text, interrupt))


class Source:
    def __init__(self, slots): self.items = slots
    def slots(self): return list(self.items)


class FailingSource:
    def slots(self):
        raise MemErr("boom")


def sample_slot():
    return PartySlot(
        0, "EEVEE", 10, 29, 33, 0,
        PartyStats(18, 18, 14, 18, 18),
        (PartyMove("TACKLE", 35),),
        "LEON", 1305, "Bashful", 0, "RUN AWAY", "Makes escaping easier.",
    )


class PartyListScreenReaderTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.speech = Speech()
        self.source = Source([sample_slot()])
        self.reader = PartyListScreenReader(
            self.memory, self.profile, self.source, self.speech,
            logging.getLogger("party-list-screen-test"))

    def _put_window(self, address, menu_id, index, next_address=0):
        p = self.profile
        self.backend.put(address + p.window_menu_id_offset, be32(menu_id))
        self.backend.put(address + p.window_next_offset, be32(next_address))
        self.backend.put(address + p.party_list_index_offset, bytes([index]))

    def _set_head(self, address):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(address))

    def test_screen_not_open_is_silent(self):
        self._set_head(0)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_other_menu_open_is_silent(self):
        self._put_window(0x80700000, 94, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_occupied_slot_announces_pokemon(self):
        self._put_window(0x80700000, 76, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls[-1][1], "Eevee, level 10, 29 of 33 HP, 88 percent.")

    def test_empty_slot_announces_empty(self):
        self._put_window(0x80700000, 76, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls[-1][1], "Empty slot.")

    def test_index_beyond_party_slots_is_cancel(self):
        self._put_window(0x80700000, 76, 6)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls[-1][1], "Cancel.")

    def test_same_index_does_not_repeat(self):
        self._put_window(0x80700000, 76, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.reader.poll_once()
        self.assertEqual(len(self.speech.calls), 1)

    def test_index_change_reannounces(self):
        self._put_window(0x80700000, 76, 6)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self._put_window(0x80700000, 76, 0)
        self.reader.poll_once()
        self.assertEqual(len(self.speech.calls), 2)
        self.assertEqual(self.speech.calls[-1][1], "Eevee, level 10, 29 of 33 HP, 88 percent.")

    def test_screen_closing_clears_state(self):
        self._put_window(0x80700000, 76, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self._set_head(0)
        self.reader.poll_once()
        self.assertFalse(self.reader.active)
        self.assertIsNone(self.reader.last_index)

    def test_read_failure_is_silent(self):
        self.reader.party_source = FailingSource()
        self._put_window(0x80700000, 76, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])


if __name__ == "__main__":
    unittest.main()
