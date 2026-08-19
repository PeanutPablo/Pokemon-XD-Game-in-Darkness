import logging
import unittest

from battle_narrator.bag_menu import (
    BagMenuModel,
    BagMenuReader,
    HeroItemArraySource,
)
from battle_narrator.memory import MemoryReader
from battle_narrator.profile import XD_US_REV0

FAKE_SAVEDATA = 0x80700000
ITEMS_CATEGORY = 0
BALLS_CATEGORY = 1


def be32(value):
    return value.to_bytes(4, "big")


def be16(value):
    return value.to_bytes(2, "big")


class WindowBackend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + offset, 0) for offset in range(size))


class Speech:
    def __init__(self):
        self.calls = []

    def emit(self, event, text, interrupt=None, deduplicate=None):
        self.calls.append(text)


class FakeNameResolver:
    def __init__(self, names):
        self.names = names

    def resolve_name(self, item_id):
        return self.names.get(item_id)


class FakeDescriptionResolver:
    def __init__(self, descriptions):
        self.descriptions = descriptions

    def resolve_description(self, item_id):
        return self.descriptions.get(item_id)


class BagMenuTestCase(unittest.TestCase):
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        p = self.profile
        # hero savedata pointer chain
        self.backend.put(p.savedata_pointer_address, be32(FAKE_SAVEDATA))
        self.hero_base = FAKE_SAVEDATA + p.hero_offset

    def _open_bag(self, window_addr, category):
        p = self.profile
        self.backend.put(window_addr + p.window_menu_id_offset, be32(p.bag_menu_id))
        self.backend.put(window_addr + p.window_next_offset, be32(0))
        self.backend.put(window_addr + p.bag_category_index_offset, bytes([category]))
        self.backend.put(p.window_manager + p.window_list_offset, be32(window_addr))

    def _close_bag(self):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(0))

    def _set_slot(self, category, slot_index, item_id, quantity):
        p = self.profile
        base = (self.hero_base + p.bag_category_array_offsets[category]
                + slot_index * p.hero_item_record_stride)
        self.backend.put(base + p.hero_item_record_id_offset, be16(item_id))
        self.backend.put(base + p.hero_item_record_quantity_offset, be16(quantity))

    def _set_cursor(self, category, x, y=0):
        p = self.profile
        cursor_id = p.bag_category_cursor_ids[category]
        addr = p.pocket_cursor_table_address + cursor_id * p.pocket_cursor_stride
        self.backend.put(addr, be16(x))
        self.backend.put(addr + 2, be16(y))


class HeroItemArraySourceTests(BagMenuTestCase):
    def setUp(self):
        super().setUp()
        self.source = HeroItemArraySource(self.memory, self.profile)

    def test_reads_a_populated_slot(self):
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        slot = self.source.slot(ITEMS_CATEGORY, 0)
        self.assertEqual(slot.item_id, 13)
        self.assertEqual(slot.quantity, 2)

    def test_skips_empty_slots_to_find_the_nth_valid_one(self):
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        # slot 1 left empty (item_id 0)
        self._set_slot(ITEMS_CATEGORY, 2, item_id=17, quantity=1)
        first = self.source.valid_slot_at_row(ITEMS_CATEGORY, 0)
        second = self.source.valid_slot_at_row(ITEMS_CATEGORY, 1)
        self.assertEqual(first.item_id, 13)
        self.assertEqual(second.item_id, 17)

    def test_row_beyond_last_valid_slot_returns_none(self):
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self.assertIsNone(self.source.valid_slot_at_row(ITEMS_CATEGORY, 1))

    def test_valid_slot_count_ignores_empty_slots(self):
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_slot(ITEMS_CATEGORY, 5, item_id=17, quantity=1)
        self.assertEqual(self.source.valid_slot_count(ITEMS_CATEGORY), 2)

    def test_each_category_uses_its_own_array(self):
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_slot(BALLS_CATEGORY, 0, item_id=1, quantity=5)
        items_slot = self.source.slot(ITEMS_CATEGORY, 0)
        balls_slot = self.source.slot(BALLS_CATEGORY, 0)
        self.assertEqual(items_slot.item_id, 13)
        self.assertEqual(balls_slot.item_id, 1)


class BagMenuModelTests(BagMenuTestCase):
    def setUp(self):
        super().setUp()
        self.source = HeroItemArraySource(self.memory, self.profile)
        self.model = BagMenuModel(self.memory, self.profile, self.source)

    def test_bag_not_open_returns_none(self):
        self._close_bag()
        self.assertIsNone(self.model.current_selection())

    def test_selection_reflects_category_and_cursor(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_cursor(ITEMS_CATEGORY, x=0, y=0)
        selection = self.model.current_selection()
        self.assertEqual(selection.category, ITEMS_CATEGORY)
        self.assertEqual(selection.category_label, "Items")
        self.assertEqual(selection.row, 0)
        self.assertEqual(selection.item_id, 13)
        self.assertEqual(selection.quantity, 2)

    def test_cursor_x_and_y_are_summed_for_scrolled_position(self):
        # x = position within visible page, y = scroll offset -- the
        # real row is their sum, not x alone (see bag_menu.py's
        # module docstring for the disassembly citation).
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=1, quantity=1)
        self._set_slot(ITEMS_CATEGORY, 1, item_id=2, quantity=1)
        self._set_cursor(ITEMS_CATEGORY, x=1, y=0)
        selection = self.model.current_selection()
        self.assertEqual(selection.row, 1)
        self.assertEqual(selection.item_id, 2)

    def test_empty_category_reports_no_row(self):
        self._open_bag(0x80700100, BALLS_CATEGORY)
        selection = self.model.current_selection()
        self.assertEqual(selection.category, BALLS_CATEGORY)
        self.assertTrue(selection.is_empty)
        self.assertTrue(selection.is_close)
        self.assertIsNone(selection.item_id)

    def test_row_one_past_last_item_is_the_close_row(self):
        # Live-confirmed 2026-07-29: the item list always has exactly
        # one extra selectable row immediately after the last real item.
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_slot(ITEMS_CATEGORY, 1, item_id=17, quantity=1)
        self._set_cursor(ITEMS_CATEGORY, x=2)
        selection = self.model.current_selection()
        self.assertTrue(selection.is_close)
        self.assertFalse(selection.is_empty)
        self.assertIsNone(selection.item_id)
        self.assertEqual(selection.row, 2)

    def test_category_isolation_in_model(self):
        self._open_bag(0x80700100, BALLS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        # Balls category has no items even though Items does.
        selection = self.model.current_selection()
        self.assertTrue(selection.is_empty)


class BagMenuReaderTests(BagMenuTestCase):
    def setUp(self):
        super().setUp()
        self.source = HeroItemArraySource(self.memory, self.profile)
        self.model = BagMenuModel(self.memory, self.profile, self.source)
        self.speech = Speech()
        self.resolver = FakeNameResolver({13: "Potion", 17: "Super Potion"})
        self.reader = BagMenuReader(
            self.memory, self.profile, self.model, self.resolver,
            self.speech, logging.getLogger("bag-menu-test"))

    def test_opening_announces_category_item_and_quantity(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.assertIn("Potion. Quantity 2. Items.", self.speech.calls)

    def test_opening_speaks_item_identity_before_category(self):
        # Live log 2026-08-11 showed rapid tab changes interrupting the
        # utterance after only "Key Items" / "TMs". Identity must lead.
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.assertTrue(self.speech.calls[0].startswith("Potion."))

    def test_cursor_movement_announces_item_only_not_category(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_slot(ITEMS_CATEGORY, 1, item_id=17, quantity=1)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.speech.calls.clear()
        self._set_cursor(ITEMS_CATEGORY, x=1)
        self.reader.poll_once()
        self.assertIn("Super Potion. Quantity 1.", self.speech.calls)
        self.assertNotIn("Items. Super Potion. Quantity 1.", self.speech.calls)

    def test_same_row_does_not_repeat(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls.count("Potion. Quantity 2. Items."), 1)

    def test_category_change_reannounces_category_and_item(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.speech.calls.clear()
        self._open_bag(0x80700100, BALLS_CATEGORY)
        self._set_slot(BALLS_CATEGORY, 0, item_id=17, quantity=1)
        self._set_cursor(BALLS_CATEGORY, x=0)
        self.reader.poll_once()
        self.assertIn("Super Potion. Quantity 1. Balls.", self.speech.calls)

    def test_empty_category_announced_once(self):
        # An empty category's only row (0) IS the trailing close row --
        # both facts are combined into one utterance.
        self._open_bag(0x80700100, BALLS_CATEGORY)
        self.reader.poll_once()
        self.assertIn("Balls. No items. Close.", self.speech.calls)
        self.speech.calls.clear()
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_unknown_item_name_falls_back_without_id(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=999, quantity=3)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.assertIn(
            "Unknown item. Quantity 3. Items.", self.speech.calls)
        for call in self.speech.calls:
            self.assertNotIn("999", call)

    def test_close_then_reopen_reannounces_cleanly(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self._close_bag()
        self.reader.poll_once()
        self.assertFalse(self.reader.active)
        self.speech.calls.clear()
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self.reader.poll_once()
        self.assertIn("Potion. Quantity 2. Items.", self.speech.calls)

    def test_zero_quantity_still_announced_plainly(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=0)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.assertIn("Potion. Quantity 0. Items.", self.speech.calls)

    def test_close_row_announced_after_last_real_item(self):
        # Live-confirmed 2026-07-29: moving down past the last real item
        # lands on a trailing row, one past the last valid item, that
        # exits the bag on A -- not a separate popup or window.
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_slot(ITEMS_CATEGORY, 1, item_id=17, quantity=1)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.speech.calls.clear()
        self._set_cursor(ITEMS_CATEGORY, x=2)
        self.reader.poll_once()
        self.assertIn("Close.", self.speech.calls)

    def test_close_row_on_open_includes_category(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_cursor(ITEMS_CATEGORY, x=1)
        self.reader.poll_once()
        self.assertIn("Items. Close.", self.speech.calls)

    def test_close_row_does_not_repeat(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_cursor(ITEMS_CATEGORY, x=1)
        self.reader.poll_once()
        self.reader.poll_once()
        self.assertEqual(self.speech.calls.count("Items. Close."), 1)

    def test_moving_back_from_close_row_reannounces_the_item(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_cursor(ITEMS_CATEGORY, x=1)
        self.reader.poll_once()
        self.speech.calls.clear()
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.assertIn("Potion. Quantity 2.", self.speech.calls)


class BagMenuReaderWithDescriptionsTests(BagMenuTestCase):
    """Descriptions are spoken on every announcement, not just open/
    category-change -- the most verbose of three options offered, and
    the one the project owner explicitly chose (2026-07-29)."""

    def setUp(self):
        super().setUp()
        self.source = HeroItemArraySource(self.memory, self.profile)
        self.model = BagMenuModel(self.memory, self.profile, self.source)
        self.speech = Speech()
        self.name_resolver = FakeNameResolver({13: "Potion", 17: "Super Potion"})
        self.description_resolver = FakeDescriptionResolver(
            {13: "Restores 20 HP.", 17: "Restores 50 HP."})
        self.reader = BagMenuReader(
            self.memory, self.profile, self.model, self.name_resolver,
            self.speech, logging.getLogger("bag-menu-description-test"),
            description_resolver=self.description_resolver,
        )

    def test_description_appended_on_open(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.assertIn(
            "Potion. Quantity 2. Items. Restores 20 HP.",
            self.speech.calls,
        )

    def test_description_appended_on_cursor_movement(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_slot(ITEMS_CATEGORY, 1, item_id=17, quantity=1)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.speech.calls.clear()
        self._set_cursor(ITEMS_CATEGORY, x=1)
        self.reader.poll_once()
        self.assertIn(
            "Super Potion. Quantity 1. Restores 50 HP.", self.speech.calls)

    def test_missing_description_omits_the_clause_cleanly(self):
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=999, quantity=3)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        self.reader.poll_once()
        self.assertIn(
            "Unknown item. Quantity 3. Items.", self.speech.calls)

    def test_no_resolver_means_no_description_clause(self):
        # BagMenuReader must work with description_resolver omitted
        # entirely (the default) -- e.g. before this feature existed.
        reader = BagMenuReader(
            self.memory, self.profile, self.model, self.name_resolver,
            self.speech, logging.getLogger("bag-menu-no-description-test"))
        self._open_bag(0x80700100, ITEMS_CATEGORY)
        self._set_slot(ITEMS_CATEGORY, 0, item_id=13, quantity=2)
        self._set_cursor(ITEMS_CATEGORY, x=0)
        reader.poll_once()
        self.assertIn("Potion. Quantity 2. Items.", self.speech.calls)


if __name__ == "__main__":
    unittest.main()
