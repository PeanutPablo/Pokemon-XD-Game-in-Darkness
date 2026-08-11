"""Shop Buy-screen item-grid narration -- built on the same shared
item-identity infrastructure `bag_menu.py` uses (`item_database.
ItemNameResolver`), not a one-off. Two layers, matching `bag_menu.py`'s own
split so nothing shop-specific leaks into the reusable pieces:

- `ShopBuyMenuModel` (this file): the pure "what item is the cursor on"
  question -- resolved item ID, absolute list position, item count. No
  speech, no dedup, so it stays independently testable.
- `ShopBuyMenuReader` (this file): the speech adapter. Polls the model,
  dedups on position change, speaks the item's name and price.

This is a genuinely different widget from the shop's own greeting/Buy-
Sell-Quit list (`menus.py`'s `shop_menu_node`/`ProductionMenuReader`) --
selecting "Buy" opens a standalone window with none of the generic
window-manager cursor/alloc machinery populated the way other menus use
it. See `profile.py`'s `shop_buy_menu_id`/`shop_buy_arg_*` fields for the
full static-disassembly-then-live-verification derivation (xd-decomp's
`menuShopCursor`/`getItem__FP13SHOP_MENU_ARGi`, cross-checked live 2026-
07-30 against this series' well-known real Pokémart prices).

`ShopBuyQuantityModel`/`ShopBuyQuantityReader` cover the second step:
selecting a real item opens a SECOND window (menu_id 61) for quantity
entry, alongside the still-open item-grid window (menu_id 60) underneath
it -- the quantity model reuses `ShopBuyMenuModel` directly (constructor-
injected) rather than re-deriving which item is selected, since that
window's own cursor position is unchanged while the quantity overlay is
open. See `profile.py`'s `shop_buy_quantity_*` fields for the
static-then-live derivation (xd-decomp's `inputBuyNum__Fiiii`, and a
same-name-symbol disambiguation resolved by watching which of two
candidate global addresses actually moved when the live quantity did).

`ShopNotificationModel`/`ShopNotificationReader` cover simple one-shot
clerk lines ("May I help you with anything else?", "We look forward to
your next visit.", etc.) -- these carry no menu/cursor structure at all,
just a GSmsg task whose message ID names which line is active. Reuses
the same task-array-walking shape `menus.py`'s own `active_gsmsg_prompt()`
already uses, kept as an independent copy (matching
`interaction_announcer.py`'s own stated reasoning) rather than coupling
to that already-working reader.

Still not covered: the purchase confirmation Yes/No and the purchase
result message's own window/cursor structure are separate, not-yet-
investigated screens (see IMPLEMENTATION_ATTRIBUTION.md's dated entry for
what's left) -- though `shop_messages.ShopMessageTable` can already
render their text once that structure is found."""
from dataclasses import dataclass

from .memory import MemoryError
from .speech import SpeechEventClass

MAX_PLAUSIBLE_ITEM_COUNT = 200


@dataclass(frozen=True)
class ShopBuySelection:
    index: int
    item_count: int
    item_id: int | None
    is_cancel: bool
    uses_coupons: bool = False


class ShopBuyMenuModel:
    """The pure "what item is currently highlighted" read. Returns `None`
    when the Buy item-grid isn't open."""

    def __init__(self, memory, profile):
        self.memory = memory
        self.profile = profile
        self.uses_coupons = False

    def _observe_currency_context(self):
        """Remember which greeting opened the shop after its task closes."""
        p = self.profile
        try:
            manager = self.memory.u32(p.manager_root, "shop currency manager")
        except MemoryError:
            return
        if not manager:
            return
        task_array = self.memory.pointer(
            manager + p.manager_tasks_offset,
            p.task_capacity * p.task_stride, "shop currency task array", 4)
        for index in range(p.task_capacity):
            task = task_array + index * p.task_stride
            state = self.memory.u8(
                task + p.task_state_offset, "shop currency task state")
            if state not in (1, 2):
                continue
            message_id = self.memory.u32(
                task + p.task_id_offset, "shop currency message id") & 0xFFFFFF
            if message_id in p.shop_coupon_menu_message_ids:
                self.uses_coupons = True
            elif message_id == 50601:
                self.uses_coupons = False

    def _find_window(self):
        p = self.profile
        pointer = self.memory.u32(
            p.window_manager + p.window_list_offset,
            "shop buy window-list head")
        seen = set()
        for _ in range(p.window_max_nodes):
            if pointer == 0:
                return None
            if pointer in seen:
                raise MemoryError("shop buy window list contains a cycle")
            seen.add(pointer)
            menu_id = self.memory.u32(
                pointer + p.window_menu_id_offset, "shop buy window menu ID")
            if menu_id == p.shop_buy_menu_id:
                return pointer
            pointer = self.memory.u32(
                pointer + p.window_next_offset, "shop buy next window")
        raise MemoryError("shop buy window list exceeds verified bound")

    def current_selection(self):
        self._observe_currency_context()
        window = self._find_window()
        if window is None:
            return None
        p = self.profile
        arg = self.memory.u32(
            window + p.shop_buy_arg_pointer_offset, "shop buy arg pointer")
        if arg == 0:
            return None
        item_count = self.memory.u32(
            arg + p.shop_buy_arg_item_count_offset, "shop buy item count")
        if not (0 < item_count < MAX_PLAUSIBLE_ITEM_COUNT):
            raise MemoryError(
                f"shop buy item count implausible: {item_count}")
        array_ptr = self.memory.u32(
            arg + p.shop_buy_arg_item_array_offset, "shop buy item array")
        page = self.memory.u16(
            window + p.window_cursor_base_offset, "shop buy page offset")
        in_page = self.memory.u16(
            window + p.window_cursor_offset, "shop buy in-page cursor")
        index = page + in_page
        # One cursor position past the last real item is a real, selectable
        # trailing row -- project-owner-confirmed live 2026-07-30 ("cancel"
        # or "quit"). Matches xd-decomp's own `getItem__FP13SHOP_MENU_ARGi`
        # (game/menuShop.s:1252), which explicitly bounds-checks and
        # returns 0 for `index >= getNbItem(arg)` rather than reading past
        # the array -- and `shopBuyMain` (menuShop.s:3024) closes the shop
        # outright when `selectItem` returns that 0, i.e. this row's
        # meaning is "leave the buy screen," matching Cancel/Quit exactly.
        if index == item_count:
            return ShopBuySelection(
                index=index, item_count=item_count, item_id=None,
                is_cancel=True, uses_coupons=self.uses_coupons)
        if not (0 <= index < item_count):
            return None
        item_id = self.memory.u16(
            array_ptr + index * 2, "shop buy item id")
        return ShopBuySelection(
            index=index, item_count=item_count, item_id=item_id,
            is_cancel=False, uses_coupons=self.uses_coupons)


UNKNOWN_ITEM_LABEL = "Unknown item"
# Live-confirmed 2026-07-30 that this trailing row exists and its meaning
# is to leave the buy screen -- its exact on-screen wording ("Cancel" vs
# "Quit") was not itself pinned down (the project owner named both as
# possibilities). "Cancel" is a placeholder pending confirmation of the
# real word, same treatment as bag_menu.py's own CLOSE_ROW_LABEL.
CANCEL_ROW_LABEL = "Cancel"


class ShopBuyMenuReader:
    def __init__(self, memory, profile, model, item_database, name_resolver,
                 speech, logger):
        self.memory = memory
        self.profile = profile
        self.model = model
        self.item_database = item_database
        self.name_resolver = name_resolver
        self.speech = speech
        self.logger = logger
        self.active = False
        self.last_index = None

    def clear(self, reason):
        if self.active:
            self.logger.debug("SHOP BUY MENU CLEAR reason=%s", reason)
        self.active = False
        self.last_index = None

    def _say(self, text):
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
        self.logger.info("SHOP BUY MENU %s", text)

    def poll_once(self):
        selection = self.model.current_selection()
        if selection is None:
            if self.active:
                self.clear("shop buy screen closed")
            return
        if self.active and selection.index == self.last_index:
            return
        if selection.is_cancel:
            self._say(f"{CANCEL_ROW_LABEL}.")
            self.active = True
            self.last_index = selection.index
            return
        record = self.item_database.lookup(selection.item_id)
        name = self.name_resolver.resolve_name(selection.item_id)
        if name is None:
            name = UNKNOWN_ITEM_LABEL
        if record is not None and selection.uses_coupons:
            self._say(f"{name}. {record.coupon_price} Pok\u00e9 Coupons.")
        elif record is not None:
            self._say(f"{name}. {record.price} Pokédollars.")
        else:
            self._say(name)
        self.active = True
        self.last_index = selection.index


@dataclass(frozen=True)
class ShopBuyQuantitySelection:
    quantity: int
    item_id: int
    uses_coupons: bool = False


class ShopBuyQuantityModel:
    """The pure "what quantity is currently entered, for which item" read.
    Returns `None` when the quantity overlay isn't open. Takes an existing
    `ShopBuyMenuModel` rather than re-deriving the selected item -- the
    item-grid window stays open, unchanged, underneath this overlay."""

    def __init__(self, memory, profile, buy_menu_model):
        self.memory = memory
        self.profile = profile
        self.buy_menu_model = buy_menu_model

    def _quantity_window_open(self):
        p = self.profile
        pointer = self.memory.u32(
            p.window_manager + p.window_list_offset,
            "shop buy quantity window-list head")
        seen = set()
        for _ in range(p.window_max_nodes):
            if pointer == 0:
                return False
            if pointer in seen:
                raise MemoryError(
                    "shop buy quantity window list contains a cycle")
            seen.add(pointer)
            menu_id = self.memory.u32(
                pointer + p.window_menu_id_offset,
                "shop buy quantity window menu ID")
            if menu_id == p.shop_buy_quantity_menu_id:
                return True
            pointer = self.memory.u32(
                pointer + p.window_next_offset,
                "shop buy quantity next window")
        raise MemoryError(
            "shop buy quantity window list exceeds verified bound")

    def current_selection(self):
        if not self._quantity_window_open():
            return None
        buy_selection = self.buy_menu_model.current_selection()
        if buy_selection is None or buy_selection.is_cancel:
            return None
        quantity = self.memory.u32(
            self.profile.shop_buy_quantity_value_address,
            "shop buy quantity")
        return ShopBuyQuantitySelection(
            quantity=quantity, item_id=buy_selection.item_id,
            uses_coupons=buy_selection.uses_coupons)


class ShopBuyQuantityReader:
    def __init__(self, memory, profile, model, item_database, name_resolver,
                 speech, logger):
        self.memory = memory
        self.profile = profile
        self.model = model
        self.item_database = item_database
        self.name_resolver = name_resolver
        self.speech = speech
        self.logger = logger
        self.active = False
        self.last_quantity = None
        self.last_item_id = None

    def clear(self, reason):
        if self.active:
            self.logger.debug("SHOP BUY QUANTITY CLEAR reason=%s", reason)
        self.active = False
        self.last_quantity = None
        self.last_item_id = None

    def _say(self, text):
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
        self.logger.info("SHOP BUY QUANTITY %s", text)

    def poll_once(self):
        selection = self.model.current_selection()
        if selection is None:
            if self.active:
                self.clear("shop buy quantity screen closed")
            return
        unchanged = (
            self.active
            and selection.quantity == self.last_quantity
            and selection.item_id == self.last_item_id
        )
        if unchanged:
            return
        record = self.item_database.lookup(selection.item_id)
        name = self.name_resolver.resolve_name(selection.item_id)
        if name is None:
            name = UNKNOWN_ITEM_LABEL
        if record is not None and selection.uses_coupons:
            total = selection.quantity * record.coupon_price
            self._say(
                f"{name}. Quantity {selection.quantity}. "
                f"{total} Pok\u00e9 Coupons."
            )
        elif record is not None:
            total = selection.quantity * record.price
            self._say(
                f"{name}. Quantity {selection.quantity}. "
                f"{total} Pokédollars."
            )
        else:
            self._say(f"{name}. Quantity {selection.quantity}.")
        self.active = True
        self.last_quantity = selection.quantity
        self.last_item_id = selection.item_id


class ShopNotificationModel:
    """The pure "which known shop notification message is currently
    active" read. Returns `None` when no watched message ID is active.
    Independent copy of the same GSmsg-task-array walk `menus.py`'s
    `ProductionMenuReader.active_gsmsg_prompt()` already does -- kept
    separate rather than coupling to that reader, matching
    `interaction_announcer.py`'s own stated reasoning for doing the
    same."""

    def __init__(self, memory, profile):
        self.memory = memory
        self.profile = profile

    def current_message_id(self):
        p = self.profile
        manager = self.memory.u32(p.manager_root, "shop notification manager")
        if not manager:
            return None
        task_array = self.memory.pointer(
            manager + p.manager_tasks_offset,
            p.task_capacity * p.task_stride,
            "shop notification task array",
            4,
        )
        for index in range(p.task_capacity):
            task = task_array + index * p.task_stride
            state = self.memory.u8(
                task + p.task_state_offset, "shop notification task state")
            if state not in (1, 2):
                continue
            message_id = self.memory.u32(
                task + p.task_id_offset, "shop notification message id"
            ) & 0xFFFFFF
            if message_id in p.shop_notification_message_ids:
                return message_id
        return None


class ShopNotificationReader:
    def __init__(self, memory, profile, model, shop_messages, speech, logger):
        self.memory = memory
        self.profile = profile
        self.model = model
        self.shop_messages = shop_messages
        self.speech = speech
        self.logger = logger
        self.active = False
        self.last_message_id = None

    def clear(self, reason):
        if self.active:
            self.logger.debug("SHOP NOTIFICATION CLEAR reason=%s", reason)
        self.active = False
        self.last_message_id = None

    def _say(self, text):
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
        self.logger.info("SHOP NOTIFICATION %s", text)

    def poll_once(self):
        message_id = self.model.current_message_id()
        if message_id is None:
            if self.active:
                self.clear("no shop notification active")
            return
        if self.active and message_id == self.last_message_id:
            return
        text = self.shop_messages.resolve(message_id)
        if text:
            self._say(text)
        self.active = True
        self.last_message_id = message_id
