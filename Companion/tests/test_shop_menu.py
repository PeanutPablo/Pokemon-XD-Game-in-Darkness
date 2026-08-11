import unittest

from battle_narrator.shop_menu import (
    CANCEL_ROW_LABEL,
    ShopBuyMenuModel,
    ShopBuyMenuReader,
    ShopBuyQuantityModel,
    ShopBuyQuantityReader,
    ShopBuyQuantitySelection,
    ShopBuySelection,
    ShopNotificationModel,
    ShopNotificationReader,
    UNKNOWN_ITEM_LABEL,
)
from battle_narrator.memory import MemoryReader
from battle_narrator.profile import XD_US_REV0


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


class Logger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass


class FakeRecord:
    def __init__(self, price, coupon_price=None):
        self.price = price
        self.coupon_price = price if coupon_price is None else coupon_price


class FakeItemDatabase:
    def __init__(self, prices):
        self.prices = prices

    def lookup(self, item_id):
        if item_id not in self.prices:
            return None
        value = self.prices[item_id]
        return FakeRecord(*value) if isinstance(value, tuple) else FakeRecord(value)


class FakeNameResolver:
    def __init__(self, names):
        self.names = names

    def resolve_name(self, item_id):
        return self.names.get(item_id)


WINDOW = 0x80874DE0
ARG = 0x80E4BA5C
ARRAY = 0x807E7558


class ShopBuyMenuModelTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.model = ShopBuyMenuModel(self.memory, self.profile)

    def _open(self, item_ids, page=0, cursor=0):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(WINDOW))
        self.backend.put(WINDOW + p.window_menu_id_offset, be32(p.shop_buy_menu_id))
        self.backend.put(WINDOW + p.window_next_offset, be32(0))
        self.backend.put(WINDOW + p.shop_buy_arg_pointer_offset, be32(ARG))
        self.backend.put(WINDOW + p.window_cursor_base_offset, be16(page))
        self.backend.put(WINDOW + p.window_cursor_offset, be16(cursor))
        self.backend.put(ARG + p.shop_buy_arg_item_array_offset, be32(ARRAY))
        self.backend.put(ARG + p.shop_buy_arg_item_count_offset, be32(len(item_ids)))
        for index, item_id in enumerate(item_ids):
            self.backend.put(ARRAY + index * 2, be16(item_id))

    def _close(self):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(0))

    def test_not_open_returns_none(self):
        self._close()
        self.assertIsNone(self.model.current_selection())

    def test_resolves_item_at_cursor_zero(self):
        self._open([13, 22, 14], cursor=0)
        selection = self.model.current_selection()
        self.assertEqual(
            selection,
            ShopBuySelection(
                index=0, item_count=3, item_id=13, is_cancel=False),
        )

    def test_page_plus_in_page_cursor_gives_absolute_index(self):
        # Live-confirmed 2026-07-30 shape: window_cursor_base_offset (0x9C)
        # is the page/scroll offset, window_cursor_offset (0x9E) is the
        # in-page position -- they're added, not used independently.
        self._open([13, 22, 14, 15, 16], page=2, cursor=1)
        selection = self.model.current_selection()
        self.assertEqual(selection.index, 3)
        self.assertEqual(selection.item_id, 15)

    def test_index_one_past_last_item_is_the_cancel_row(self):
        self._open([13, 22], cursor=2)
        selection = self.model.current_selection()
        self.assertEqual(
            selection,
            ShopBuySelection(
                index=2, item_count=2, item_id=None, is_cancel=True),
        )

    def test_index_beyond_the_cancel_row_returns_none(self):
        self._open([13, 22], cursor=5)
        self.assertIsNone(self.model.current_selection())

    def test_implausible_item_count_raises(self):
        p = self.profile
        self._open([13])
        self.backend.put(
            ARG + p.shop_buy_arg_item_count_offset, be32(50000))
        with self.assertRaises(Exception):
            self.model.current_selection()


class ShopBuyMenuReaderTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.model = ShopBuyMenuModel(self.memory, self.profile)
        self.speech = Speech()
        self.item_database = FakeItemDatabase({13: 300, 22: 700})
        self.name_resolver = FakeNameResolver({13: "Potion", 22: "Super Potion"})
        self.reader = ShopBuyMenuReader(
            self.memory, self.profile, self.model, self.item_database,
            self.name_resolver, self.speech, Logger(),
        )

    def _open(self, item_ids, cursor=0):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(WINDOW))
        self.backend.put(WINDOW + p.window_menu_id_offset, be32(p.shop_buy_menu_id))
        self.backend.put(WINDOW + p.window_next_offset, be32(0))
        self.backend.put(WINDOW + p.shop_buy_arg_pointer_offset, be32(ARG))
        self.backend.put(WINDOW + p.window_cursor_base_offset, be16(0))
        self.backend.put(WINDOW + p.window_cursor_offset, be16(cursor))
        self.backend.put(ARG + p.shop_buy_arg_item_array_offset, be32(ARRAY))
        self.backend.put(ARG + p.shop_buy_arg_item_count_offset, be32(len(item_ids)))
        for index, item_id in enumerate(item_ids):
            self.backend.put(ARRAY + index * 2, be16(item_id))

    def _close(self):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(0))

    def test_speaks_name_and_real_price_on_first_poll(self):
        self._open([13, 22], cursor=0)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, ["Potion. 300 Pokédollars."])

    def test_coupon_exchange_uses_coupon_price_and_label(self):
        self.reader.item_database = FakeItemDatabase({13: (300, 20)})
        self.model.uses_coupons = True
        self._open([13], cursor=0)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, ["Potion. 20 Poké Coupons."])

    def test_cursor_move_speaks_the_new_item(self):
        self._open([13, 22], cursor=0)
        self.reader.poll_once()
        self._open([13, 22], cursor=1)
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls, ["Potion. 300 Pokédollars.", "Super Potion. 700 Pokédollars."])

    def test_unchanged_cursor_does_not_repeat(self):
        self._open([13, 22], cursor=0)
        self.reader.poll_once()
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, ["Potion. 300 Pokédollars."])

    def test_cancel_row_speaks_the_cancel_label_not_an_item(self):
        self._open([13, 22], cursor=2)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [f"{CANCEL_ROW_LABEL}."])

    def test_moving_from_cancel_row_back_to_an_item_speaks_it(self):
        self._open([13, 22], cursor=2)
        self.reader.poll_once()
        self._open([13, 22], cursor=0)
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls, [f"{CANCEL_ROW_LABEL}.", "Potion. 300 Pokédollars."])

    def test_unresolved_name_falls_back_to_unknown_label(self):
        self.item_database = FakeItemDatabase({})
        self.name_resolver = FakeNameResolver({})
        self.reader = ShopBuyMenuReader(
            self.memory, self.profile, self.model, self.item_database,
            self.name_resolver, self.speech, Logger(),
        )
        self._open([9999], cursor=0)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [UNKNOWN_ITEM_LABEL])

    def test_closing_the_screen_clears_state_and_reopening_speaks_again(self):
        self._open([13], cursor=0)
        self.reader.poll_once()
        self._close()
        self.reader.poll_once()
        self._open([13], cursor=0)
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls,
            ["Potion. 300 Pokédollars.", "Potion. 300 Pokédollars."],
        )


QUANTITY_WINDOW = 0x80874E9C


class ShopBuyQuantityModelTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.buy_model = ShopBuyMenuModel(self.memory, self.profile)
        self.model = ShopBuyQuantityModel(
            self.memory, self.profile, self.buy_model)

    def _open_buy_grid(self, item_ids, cursor=0):
        p = self.profile
        self.backend.put(WINDOW + p.window_menu_id_offset, be32(p.shop_buy_menu_id))
        self.backend.put(WINDOW + p.shop_buy_arg_pointer_offset, be32(ARG))
        self.backend.put(WINDOW + p.window_cursor_base_offset, be16(0))
        self.backend.put(WINDOW + p.window_cursor_offset, be16(cursor))
        self.backend.put(ARG + p.shop_buy_arg_item_array_offset, be32(ARRAY))
        self.backend.put(ARG + p.shop_buy_arg_item_count_offset, be32(len(item_ids)))
        for index, item_id in enumerate(item_ids):
            self.backend.put(ARRAY + index * 2, be16(item_id))

    def _open_quantity(self, quantity, item_ids=(13, 22), cursor=0):
        p = self.profile
        self._open_buy_grid(item_ids, cursor=cursor)
        self.backend.put(WINDOW + p.window_next_offset, be32(QUANTITY_WINDOW))
        self.backend.put(
            QUANTITY_WINDOW + p.window_menu_id_offset,
            be32(p.shop_buy_quantity_menu_id))
        self.backend.put(QUANTITY_WINDOW + p.window_next_offset, be32(0))
        self.backend.put(p.window_manager + p.window_list_offset, be32(WINDOW))
        self.backend.put(
            p.shop_buy_quantity_value_address, be32(quantity))

    def _close(self):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(0))

    def test_not_open_returns_none(self):
        self._close()
        self.assertIsNone(self.model.current_selection())

    def test_buy_grid_alone_without_quantity_window_returns_none(self):
        self._open_buy_grid([13, 22], cursor=0)
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(WINDOW))
        self.assertIsNone(self.model.current_selection())

    def test_resolves_quantity_and_item_from_the_still_open_grid(self):
        self._open_quantity(quantity=1, item_ids=[13, 22], cursor=1)
        selection = self.model.current_selection()
        self.assertEqual(
            selection, ShopBuyQuantitySelection(quantity=1, item_id=22))

    def test_quantity_change_is_reflected(self):
        self._open_quantity(quantity=3, item_ids=[13, 22], cursor=0)
        selection = self.model.current_selection()
        self.assertEqual(selection.quantity, 3)

    def test_cancel_row_selected_returns_none(self):
        self._open_quantity(quantity=1, item_ids=[13, 22], cursor=2)
        self.assertIsNone(self.model.current_selection())


class ShopBuyQuantityReaderTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.buy_model = ShopBuyMenuModel(self.memory, self.profile)
        self.model = ShopBuyQuantityModel(
            self.memory, self.profile, self.buy_model)
        self.speech = Speech()
        self.item_database = FakeItemDatabase({13: 300, 22: 700})
        self.name_resolver = FakeNameResolver({13: "Potion", 22: "Super Potion"})
        self.reader = ShopBuyQuantityReader(
            self.memory, self.profile, self.model, self.item_database,
            self.name_resolver, self.speech, Logger(),
        )

    def _open_quantity(self, quantity, item_ids=(13, 22), cursor=0):
        p = self.profile
        self.backend.put(WINDOW + p.window_menu_id_offset, be32(p.shop_buy_menu_id))
        self.backend.put(WINDOW + p.shop_buy_arg_pointer_offset, be32(ARG))
        self.backend.put(WINDOW + p.window_cursor_base_offset, be16(0))
        self.backend.put(WINDOW + p.window_cursor_offset, be16(cursor))
        self.backend.put(WINDOW + p.window_next_offset, be32(QUANTITY_WINDOW))
        self.backend.put(ARG + p.shop_buy_arg_item_array_offset, be32(ARRAY))
        self.backend.put(ARG + p.shop_buy_arg_item_count_offset, be32(len(item_ids)))
        for index, item_id in enumerate(item_ids):
            self.backend.put(ARRAY + index * 2, be16(item_id))
        self.backend.put(
            QUANTITY_WINDOW + p.window_menu_id_offset,
            be32(p.shop_buy_quantity_menu_id))
        self.backend.put(QUANTITY_WINDOW + p.window_next_offset, be32(0))
        self.backend.put(p.window_manager + p.window_list_offset, be32(WINDOW))
        self.backend.put(
            p.shop_buy_quantity_value_address, be32(quantity))

    def _close(self):
        p = self.profile
        self.backend.put(p.window_manager + p.window_list_offset, be32(0))

    def test_speaks_name_quantity_and_running_total(self):
        self._open_quantity(quantity=1, item_ids=[13], cursor=0)
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls, ["Potion. Quantity 1. 300 Pokédollars."])

    def test_coupon_quantity_uses_coupon_total_and_label(self):
        self.reader.item_database = FakeItemDatabase({13: (300, 20)})
        self.buy_model.uses_coupons = True
        self._open_quantity(quantity=2, item_ids=[13], cursor=0)
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls,
            ["Potion. Quantity 2. 40 Poké Coupons."],
        )

    def test_quantity_increase_updates_the_total(self):
        self._open_quantity(quantity=1, item_ids=[13], cursor=0)
        self.reader.poll_once()
        self._open_quantity(quantity=2, item_ids=[13], cursor=0)
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls,
            ["Potion. Quantity 1. 300 Pokédollars.",
             "Potion. Quantity 2. 600 Pokédollars."],
        )

    def test_unchanged_quantity_does_not_repeat(self):
        self._open_quantity(quantity=1, item_ids=[13], cursor=0)
        self.reader.poll_once()
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls, ["Potion. Quantity 1. 300 Pokédollars."])

    def test_closing_clears_and_reopening_speaks_again(self):
        self._open_quantity(quantity=1, item_ids=[13], cursor=0)
        self.reader.poll_once()
        self._close()
        self.reader.poll_once()
        self._open_quantity(quantity=1, item_ids=[13], cursor=0)
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls,
            ["Potion. Quantity 1. 300 Pokédollars.",
             "Potion. Quantity 1. 300 Pokédollars."],
        )


class FakeShopMessages:
    def __init__(self, texts):
        self.texts = texts

    def resolve(self, message_id, **kwargs):
        return self.texts.get(message_id)


class ShopNotificationModelTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.model = ShopNotificationModel(self.memory, self.profile)

    def _set_task(self, message_id, state=2, index=0):
        p = self.profile
        manager = 0x80008000
        tasks = 0x80008100
        self.backend.put(p.manager_root, be32(manager))
        self.backend.put(manager + p.manager_tasks_offset, be32(tasks))
        task = tasks + index * p.task_stride
        self.backend.put(task + p.task_state_offset, bytes([state]))
        self.backend.put(task + p.task_id_offset, be32(message_id))

    def test_no_manager_returns_none(self):
        self.assertIsNone(self.model.current_message_id())

    def test_known_notification_id_is_returned(self):
        self._set_task(50602)
        self.assertEqual(self.model.current_message_id(), 50602)

    def test_unrecognized_message_id_returns_none(self):
        # e.g. the shop's own greeting (50601) -- a real, known message
        # ID, but not one of this reader's watched notification IDs
        # (that one has real menu structure, handled by ShopMenuModel
        # via menus.py instead).
        self._set_task(50601)
        self.assertIsNone(self.model.current_message_id())

    def test_inactive_task_state_returns_none(self):
        self._set_task(50602, state=0)
        self.assertIsNone(self.model.current_message_id())


class ShopNotificationReaderTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.model = ShopNotificationModel(self.memory, self.profile)
        self.speech = Speech()
        self.shop_messages = FakeShopMessages({
            50602: "May I help you with anything else?",
            50603: "We look forward to your next visit.",
        })
        self.reader = ShopNotificationReader(
            self.memory, self.profile, self.model, self.shop_messages,
            self.speech, Logger(),
        )

    def _set_task(self, message_id, state=2):
        p = self.profile
        manager = 0x80008000
        tasks = 0x80008100
        self.backend.put(p.manager_root, be32(manager))
        self.backend.put(manager + p.manager_tasks_offset, be32(tasks))
        self.backend.put(tasks + p.task_state_offset, bytes([state]))
        self.backend.put(tasks + p.task_id_offset, be32(message_id))

    def test_speaks_resolved_text_once(self):
        self._set_task(50602)
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls, ["May I help you with anything else?"])

    def test_unchanged_message_does_not_repeat(self):
        self._set_task(50602)
        self.reader.poll_once()
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls, ["May I help you with anything else?"])

    def test_new_message_replaces_the_old_one(self):
        self._set_task(50602)
        self.reader.poll_once()
        self._set_task(50603)
        self.reader.poll_once()
        self.assertEqual(
            self.speech.calls,
            ["May I help you with anything else?",
             "We look forward to your next visit."],
        )

    def test_no_active_task_is_silent(self):
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_unresolved_text_is_silent_but_still_marks_active(self):
        self.shop_messages = FakeShopMessages({})
        self.reader = ShopNotificationReader(
            self.memory, self.profile, self.model, self.shop_messages,
            self.speech, Logger(),
        )
        self._set_task(50602)
        self.reader.poll_once()
        self.assertEqual(self.speech.calls, [])
