import logging
import unittest

from battle_narrator.memory import MemoryReader
from battle_narrator.party_action_menu import (
    POKEMON_ABILITY_OFFSET, POKEMON_DATA, POKEMON_DATA_NUMBER,
    POKEMON_DATA_STRIDE, POKEMON_NAME_OFFSET, PartyActionMenuReader,
    stone_selection_labels,
)
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


class StoneDataMemory:
    def __init__(self):
        self.count_address = 0x80001000
        self.base = 0x80002000
        self.words = {self.count_address: 300}
        self.bytes = {}

    def pointer(self, address, *_args):
        return {POKEMON_DATA_NUMBER: self.count_address,
                POKEMON_DATA: self.base}[address]

    def u32(self, address, _label):
        return self.words[address]

    def u8(self, address, _label):
        return self.bytes.get(address, 0)


class DictResolver:
    def __init__(self, values): self.values = values
    def resolve_name(self, key): return self.values.get(key)
    def resolve(self, key): return self.values.get(key)


class AbilityResolver:
    def __init__(self, values): self.values = values
    def resolve(self, _memory, _profile, key): return self.values[key], ""


class StoneSelectionLabelTests(unittest.TestCase):
    def test_reads_species_and_abilities_from_the_loaded_build(self):
        memory = StoneDataMemory()
        species = (134, 135, 136, 197, 196)
        for index, species_id in enumerate(species):
            record = memory.base + species_id * POKEMON_DATA_STRIDE
            memory.words[record + POKEMON_NAME_OFFSET] = 5000 + species_id
            memory.bytes[record + POKEMON_ABILITY_OFFSET] = 80 + index
        labels = stone_selection_labels(
            memory, XD_US_REV0,
            DictResolver(dict(zip(
                XD_US_REV0.stone_selection_item_ids,
                ("Water Stone", "Thunderstone", "Fire Stone",
                 "Moon Shard", "Sun Shard")))),
            DictResolver(dict(zip(
                (5000 + value for value in species),
                ("Vaporeon", "Jolteon", "Flareon", "Umbreon", "Espeon")))),
            AbilityResolver({80: "Hydration", 81: "Volt Absorb",
                             82: "Flash Fire", 83: "Synchronize",
                             84: "Magic Bounce"}),
        )
        self.assertEqual(labels[0],
                         "Water Stone: Vaporeon, ability Hydration")
        self.assertEqual(labels[-1],
                         "Sun Shard: Espeon, ability Magic Bounce")


class PartyActionMenuReaderTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.speech = Speech()
        self.reader = PartyActionMenuReader(
            self.memory, self.profile, self.speech,
            logging.getLogger("party-action-menu-test"))

    def _put_window(self, address, menu_id, index, next_address=0):
        p = self.profile
        self.backend.put(address + p.window_menu_id_offset, be32(menu_id))
        self.backend.put(address + p.window_next_offset, be32(next_address))
        self.backend.put(address + p.party_action_index_offset, bytes([index]))

    def _set_head(self, address):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(address))

    def test_menu_not_open_is_silent(self):
        self._set_head(0)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])
        self.assertFalse(self.reader.active)

    def test_other_menu_open_is_silent(self):
        self._put_window(0x80700000, 94, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_opening_on_first_option_announces_summary(self):
        self._put_window(0x80700000, 79, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls[-1][1], "Summary.")

    def test_each_option_announced_by_index(self):
        expected = ["Summary.", "Switch.", "Item.", "Cancel."]
        for index, label in enumerate(expected):
            self._put_window(0x80700000, 79, index)
            self._set_head(0x80700000)
            self.reader.poll_once()
            self.assertEqual(self.speech.calls[-1][1], label)

    def test_wraparound_index_is_handled(self):
        self._put_window(0x80700000, 79, 4)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls[-1][1], "Summary.")

    def test_same_index_does_not_repeat(self):
        self._put_window(0x80700000, 79, 1)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.reader.poll_once()
        self.assertEqual(len(self.speech.calls), 1)

    def test_menu_closing_clears_state(self):
        self._put_window(0x80700000, 79, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self._set_head(0)
        self.reader.poll_once()
        self.assertFalse(self.reader.active)
        self.assertIsNone(self.reader.last_index)

    def test_reopening_reannounces_current_index(self):
        self._put_window(0x80700000, 79, 2)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self._set_head(0)
        self.reader.poll_once()
        self._put_window(0x80700000, 79, 2)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(len(self.speech.calls), 2)
        self.assertEqual(self.speech.calls[-1][1], "Item.")


class PartyItemActionMenuReaderTests(unittest.TestCase):
    """The same class, reused for the "Do what with an item?" popup
    (Give/Take/Cancel) via a different menu_id/labels pair at construction."""
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.speech = Speech()
        self.reader = PartyActionMenuReader(
            self.memory, self.profile, self.speech,
            logging.getLogger("party-item-action-menu-test"),
            menu_id=self.profile.party_item_action_menu_id,
            labels=self.profile.party_item_action_labels)

    def _put_window(self, address, menu_id, index, next_address=0):
        p = self.profile
        self.backend.put(address + p.window_menu_id_offset, be32(menu_id))
        self.backend.put(address + p.window_next_offset, be32(next_address))
        self.backend.put(address + p.party_action_index_offset, bytes([index]))

    def _set_head(self, address):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(address))

    def test_other_action_menu_is_ignored(self):
        # menu_id 79 is the OTHER action popup, not this one.
        self._put_window(0x80700000, 79, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_each_option_announced(self):
        expected = ["Give.", "Take.", "Cancel."]
        for index, label in enumerate(expected):
            self._put_window(0x80700000, 93, index)
            self._set_head(0x80700000)
            self.reader.poll_once()
            self.assertEqual(self.speech.calls[-1][1], label)


class BagCategoryReaderTests(unittest.TestCase):
    """The same class again, reused for the bag menu's category tab row.

    Index-to-category mapping is NOT simple visual order -- it's a fixed
    per-category ID (0=Items, 1=Balls, 2=TMs, 3=Berries, 4=Key Items),
    confirmed one category at a time via the project owner's own OCR at
    each step (see profile.py's `bag_category_labels` comment)."""
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.speech = Speech()
        self.reader = PartyActionMenuReader(
            self.memory, self.profile, self.speech,
            logging.getLogger("bag-category-test"),
            menu_id=self.profile.bag_menu_id,
            labels=self.profile.bag_category_labels,
            index_offset=self.profile.bag_category_index_offset)

    def _put_window(self, address, menu_id, index, next_address=0):
        p = self.profile
        self.backend.put(address + p.window_menu_id_offset, be32(menu_id))
        self.backend.put(address + p.window_next_offset, be32(next_address))
        self.backend.put(address + p.bag_category_index_offset, bytes([index]))

    def _set_head(self, address):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(address))

    def test_other_menu_is_ignored(self):
        self._put_window(0x80700000, 79, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_each_category_announced_by_confirmed_index(self):
        expected = {0: "Items.", 1: "Balls.", 2: "TMs.", 3: "Berries.", 4: "Key Items."}
        for index, label in expected.items():
            self._put_window(0x80700000, 44, index)
            self._set_head(0x80700000)
            self.reader.poll_once()
            self.assertEqual(self.speech.calls[-1][1], label)


class PauseMenuReaderTests(unittest.TestCase):
    """The same class again, reused for the overworld pause menu.

    Index-to-option mapping includes P?DA, Items, Save, Pokemon,
    4=Exit) was confirmed one step at a time live -- see profile.py's
    `pause_menu_labels` comment for the false-collision correction."""
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.speech = Speech()
        self.reader = PartyActionMenuReader(
            self.memory, self.profile, self.speech,
            logging.getLogger("pause-menu-test"),
            menu_id=self.profile.pause_menu_id,
            labels=self.profile.pause_menu_labels)

    def _put_window(self, address, menu_id, index, next_address=0):
        p = self.profile
        self.backend.put(address + p.window_menu_id_offset, be32(menu_id))
        self.backend.put(address + p.window_next_offset, be32(next_address))
        self.backend.put(address + p.party_action_index_offset, bytes([index]))

    def _set_head(self, address):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(address))

    def test_other_menu_is_ignored(self):
        self._put_window(0x80700000, 44, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_each_option_announced_by_confirmed_index(self):
        expected = {0: "Pokemon.", 1: "P star D A.", 2: "Items.",
                   3: "Save.", 4: "Exit."}
        for index, label in expected.items():
            self._put_window(0x80700000, 87, index)
            self._set_head(0x80700000)
            self.reader.poll_once()
            self.assertEqual(self.speech.calls[-1][1], label)

    def test_pokemon_and_exit_do_not_collide(self):
        # Regression test for the off-by-one mapping error found during
        # live investigation (a "reset to Pokemon" step actually landed
        # one option past Pokemon without being noticed) -- these must
        # resolve to different labels despite being adjacent indices.
        self._put_window(0x80700000, 87, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        pokemon_label = self.speech.calls[-1][1]
        self._put_window(0x80700000, 87, 4)
        self.reader.poll_once()
        exit_label = self.speech.calls[-1][1]
        self.assertNotEqual(pokemon_label, exit_label)
        self.assertEqual(pokemon_label, "Pokemon.")
        self.assertEqual(exit_label, "Exit.")


class StoneSelectionMenuReaderTests(unittest.TestCase):
    """The same class again, reused for the Eevee evolution-stone
    selection screen. Unlike every other reuse of this class, the
    labels here are NOT independently re-derivable -- both candidate
    data sources near the menu's own window were investigated and
    ruled out as UI decoration (see profile.py's
    `stone_selection_labels` comment and ACCESSIBILITY_COVERAGE_MATRIX.md).
    They are exactly and only what the project owner read via their own
    OCR: Water Stone, Thunder Stone, Fire Stone, Moon Shard, Sun Shard."""
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.speech = Speech()
        self.reader = PartyActionMenuReader(
            self.memory, self.profile, self.speech,
            logging.getLogger("stone-selection-menu-test"),
            menu_id=self.profile.stone_selection_menu_id,
            labels=("Water Stone", "Thunderstone", "Fire Stone",
                    "Moon Shard", "Sun Shard"))

    def _put_window(self, address, menu_id, index, next_address=0):
        p = self.profile
        self.backend.put(address + p.window_menu_id_offset, be32(menu_id))
        self.backend.put(address + p.window_next_offset, be32(next_address))
        self.backend.put(address + p.party_action_index_offset, bytes([index]))

    def _set_head(self, address):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(address))

    def test_other_menu_is_ignored(self):
        self._put_window(0x80700000, 87, 0)
        self._set_head(0x80700000)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_each_option_announced_by_confirmed_index(self):
        expected = {
            0: "Water Stone.", 1: "Thunderstone.", 2: "Fire Stone.",
            3: "Moon Shard.", 4: "Sun Shard.",
        }
        for index, label in expected.items():
            self._put_window(0x80700000, 175, index)
            self._set_head(0x80700000)
            self.reader.poll_once()
            self.assertEqual(self.speech.calls[-1][1], label)


if __name__ == "__main__":
    unittest.main()
