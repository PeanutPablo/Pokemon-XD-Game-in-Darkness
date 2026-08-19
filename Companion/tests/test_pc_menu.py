import unittest
from types import SimpleNamespace

from battle_narrator.memory import MemoryError, MemoryReader
from battle_narrator.pc_menu import PCMenuReader
from battle_narrator.profile import XD_US_REV0


class Memory:
    def __init__(self, values):
        self.values = values

    def u32(self, address, _label):
        return self.values.get(address, 0)

    def u8(self, address, _label):
        return self.values.get(address, 0)


class Speech:
    def __init__(self):
        self.events = []

    def emit(self, _kind, text, interrupt=False):
        self.events.append((text, interrupt))


class Logger:
    def debug(self, *_args): pass
    def info(self, *_args): pass


class Profile:
    window_manager = 0x1000
    window_list_offset = 0
    window_next_offset = 4
    window_menu_id_offset = 8
    window_max_nodes = 10
    party_action_index_offset = 0x9F


def test_pc_main_and_action_menus_are_announced_from_live_cursor():
    # main -> action linked-window list; each widget owns its cursor byte.
    memory = Memory({
        0x1000: 0x2000,
        0x2000 + 4: 0x3000,
        0x2000 + 8: 122,
        0x2000 + 0x9F: 1,
        0x3000 + 4: 0,
        0x3000 + 8: 123,
        0x3000 + 0x9F: 2,
    })
    speech = Speech()
    reader = PCMenuReader(memory, Profile(), speech, Logger())

    reader.poll_once()

    assert speech.events == [
        ("Item Storage.", True),
        ("Move Pokemon.", True),
    ]


class Backend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + i, 0) for i in range(size))


class RecordingParty:
    """Records the address every decode is asked for.

    The point of the test below is *which address* gets read, so this
    deliberately records rather than returning canned Pokemon: the bug it
    guards against was thirty different cells all decoding one address,
    which no assertion about the returned value can catch."""

    def __init__(self):
        self.addresses = []

    def _decode_slot(self, base, _index):
        self.addresses.append(base)
        return None

    def slots(self):
        return []


class PCBoxAddressingTests(unittest.TestCase):
    """`PCBOX::getPokemon` (0x80156AB0) resolves a cell as

        savedata + 0xAD0 + box*0x170C + 0x14 + slot*0xC4

    Before this was ported, box cells were read as `_decode_slot(obj +
    0x3718, slot)` -- and that method's second argument is only an error
    label, so all thirty cells decoded the same address and the reader
    announced one Pokemon for every cell in the box."""

    SAVEDATA = 0x80500000

    def reader(self):
        backend = Backend()
        backend.put(XD_US_REV0.savedata_pointer_address,
                    self.SAVEDATA.to_bytes(4, "big"))
        memory = MemoryReader(backend, XD_US_REV0)
        party = RecordingParty()
        return PCMenuReader(memory, XD_US_REV0, Speech(), Logger(), party), party

    def test_box_address_matches_the_engine_formula(self):
        reader, _ = self.reader()
        for box, slot in ((0, 0), (0, 29), (3, 17), (7, 29)):
            self.assertEqual(
                reader._box_address(box, slot),
                self.SAVEDATA + 0xAD0 + box * 0x170C + 0x14 + slot * 0xC4,
                f"box {box} slot {slot}")

    def test_box_stride_is_header_plus_thirty_slots(self):
        # 0x170C == 0x14 + 30*0xC4. If any one of the three constants is
        # wrong this identity breaks, and every box past the first would
        # silently read into the neighbouring box.
        self.assertEqual(
            PCMenuReader.PCBOX_BOX_STRIDE,
            PCMenuReader.PCBOX_BOX_HEADER
            + PCMenuReader.PCBOX_SLOTS_PER_BOX * PCMenuReader.PCBOX_SLOT_STRIDE)

    def test_every_cell_in_a_box_reads_a_distinct_address(self):
        reader, party = self.reader()
        for slot in range(PCMenuReader.PCBOX_SLOTS_PER_BOX):
            reader._box_pokemon(2, slot)
        self.assertEqual(len(party.addresses), 30)
        self.assertEqual(len(set(party.addresses)), 30)
        # ...and consecutively, one Pokemon record apart.
        gaps = {b - a for a, b in zip(party.addresses, party.addresses[1:])}
        self.assertEqual(gaps, {PCMenuReader.PCBOX_SLOT_STRIDE})

    def test_boxes_do_not_overlap(self):
        reader, _ = self.reader()
        last = reader._box_address(0, PCMenuReader.PCBOX_SLOTS_PER_BOX - 1)
        first_of_next = reader._box_address(1, 0)
        self.assertGreater(first_of_next, last + PCMenuReader.PCBOX_SLOT_STRIDE - 1)

    def test_out_of_range_box_or_slot_is_rejected(self):
        reader, _ = self.reader()
        for box, slot in ((-1, 0), (8, 0), (0, -1), (0, 30)):
            with self.assertRaises(MemoryError):
                reader._box_address(box, slot)

    def test_missing_party_source_does_not_crash_the_narrator(self):
        # `party_source` is an optional constructor argument. An unguarded
        # call raises AttributeError, which is not a MemoryError and so is
        # not caught by the lifecycle's per-reader handler -- it would take
        # the whole narrator down rather than silencing one screen.
        backend = Backend()
        backend.put(XD_US_REV0.savedata_pointer_address,
                    self.SAVEDATA.to_bytes(4, "big"))
        reader = PCMenuReader(
            MemoryReader(backend, XD_US_REV0), XD_US_REV0, Speech(), Logger())
        self.assertIsNone(reader._box_pokemon(0, 0))

    def test_grid_position_maps_to_six_columns(self):
        # Slot 6 is row 2 column 1: the box grid is six across by five
        # down, which is what the announcement's row/column wording means.
        self.assertEqual(divmod(6, PCMenuReader.PCBOX_BOX_COLUMNS), (1, 0))
        self.assertEqual(divmod(29, PCMenuReader.PCBOX_BOX_COLUMNS), (4, 5))


class PCFixedMenuTests(unittest.TestCase):
    def test_default_box_name_is_not_spoken_twice(self):
        reader = PCMenuReader(Memory({}), Profile(), Speech(), Logger())
        reader._box_name = lambda _box: "BOX 1"
        self.assertEqual(reader._box_label(0), "Box 1")

    def test_menu_123_uses_live_confirmed_pokemon_actions(self):
        for index, expected in enumerate((
            "Deposit Pokemon.", "Withdraw Pokemon.",
            "Move Pokemon.", "Exit.",
        )):
            memory = Memory({
                0x1000: 0x2000,
                0x2000 + 4: 0,
                0x2000 + 8: 123,
                0x2000 + 0x9C: index,
            })
            speech = Speech()
            reader = PCMenuReader(memory, Profile(), speech, Logger())
            self.assertTrue(reader._poll_fixed())
            self.assertEqual(speech.events[-1], (expected, True))

    def test_scalar_confirmation_value_is_not_a_storage_cursor(self):
        obj = 0x80700000
        memory = Memory({
            PCMenuReader.STORAGE_OBJECT_POINTER: obj,
            obj + PCMenuReader.STORAGE_CURSOR_POINTER_OFFSET: 0x37F0,
        })
        speech = Speech()
        reader = PCMenuReader(memory, Profile(), speech, Logger())
        reader._poll_storage()
        self.assertEqual(speech.events, [])
        self.assertIsNone(reader.last_storage_identity)

    def test_occupied_box_cell_says_pokemon_name_before_coordinates(self):
        obj, cursor = 0x80700000, 0x80704000
        memory = Memory({
            PCMenuReader.STORAGE_OBJECT_POINTER: obj,
            obj + PCMenuReader.STORAGE_CURSOR_POINTER_OFFSET: cursor,
            cursor + PCMenuReader.STORAGE_CURSOR_INDEX_OFFSET: 16,
            obj + PCMenuReader.STORAGE_BOX_OFFSET: 0,
        })
        speech = Speech()
        party = RecordingParty()
        party._decode_slot = lambda _address, _index: None
        reader = PCMenuReader(memory, Profile(), speech, Logger(), party)
        reader._box_label = lambda _box: "Box 1"
        reader._box_pokemon = lambda _box, _slot: SimpleNamespace(
            raw_nickname="TODD", level=31)
        reader._poll_storage()
        self.assertEqual(
            speech.events,
            [("TODD, Box 1, row 2, column 1, slot 7, level 31.", True)])


class PCMainMenuLabelTests(unittest.TestCase):
    """The project owner's 2026-08-18 report: "the pc says 'save' instead
    of 'exit'".

    `_poll_fixed` carried its own inline four-entry tuple for menu 122 with
    a "Save" the real menu does not have, shifting every index from 2 on.
    The labels now come from the one named constant, so there is no second
    copy left to disagree."""

    def test_the_home_menu_has_no_phantom_save_entry(self):
        self.assertEqual(
            PCMenuReader.MAIN_LABELS,
            ("Pokemon Storage", "Item Storage", "Exit"))
        self.assertNotIn("Save", PCMenuReader.MAIN_LABELS)

    def test_exit_is_the_entry_the_player_lands_on(self):
        # Index 2 is the one that used to announce "Save".
        self.assertEqual(PCMenuReader.MAIN_LABELS[2], "Exit")

    def test_poll_fixed_reads_the_named_constants(self):
        # Pinning the fix itself: a re-introduced literal tuple at the call
        # site is exactly how this menu broke twice.
        import inspect
        source = inspect.getsource(PCMenuReader._poll_fixed)
        self.assertIn("self.MAIN_LABELS", source)
        self.assertIn("self.MAIN_MENU_ID", source)
        self.assertNotIn('"Save"', source)


if __name__ == "__main__":
    unittest.main()
