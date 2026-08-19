"""Bag menu narration -- built on the shared item-identity infrastructure
in `item_database.py`, not a one-off. Three layers, kept deliberately
separate so nothing bag-specific leaks into the reusable pieces:

- `HeroItemArraySource` (this file): reads raw (item ID, quantity)
  records out of the hero's own save-data item arrays. Bag-specific only
  in the sense that it knows the hero owns these arrays; the array
  layout itself (offsets/slot counts per category) comes from
  `profile.py`, derived from static disassembly of
  `heroItemGetItemKindToItemAryPtr`/`heroGetStatus`/`heroBiosGetItem*Ptr`
  (see ACCESSIBILITY_COVERAGE_MATRIX.md's "Item name resolution
  infrastructure" entry for the full derivation).
- `BagMenuModel` (this file): the pure "what is currently selected"
  question -- active category, current row, resolved item ID/quantity,
  empty/close-row state. No speech, no dedup, so it can be unit-tested
  and reused (e.g. by a future Bag-adjacent screen) without a real
  speech sink.
- `BagMenuReader` (this file): the speech adapter. Polls the model,
  decides what to say and when (dedup, category-change vs. plain
  cursor-move announcements, empty categories, the trailing close row,
  close/reopen), using `item_database.ItemNameResolver` for the actual
  name text and, per the project owner's explicit choice (2026-07-29,
  offered a quieter on-demand-hotkey alternative and a
  category-change-only alternative; picked the most verbose of the
  three), `item_database.ItemDescriptionResolver` for a spoken
  description appended to *every* announcement, not just on open/
  category-change. Real item identity is always spoken first so rapid
  tab navigation cannot repeatedly cut speech off at the category name.

Row-selection mechanism: `menuPocket2Cursor` does NOT read the window
struct's own `+0x9F` byte for the item row (that byte is the category
*tab* index only, already covered by `BagCategoryReaderTests`) -- it
reads a small fixed global array (`_cursor`, address
`profile.pocket_cursor_table_address`), indexed by a per-category
"cursor ID" (`profile.bag_category_cursor_ids`). Each cursor slot packs
two halfwords that the game itself ADDS together to get the true row
index within the filtered (empty-slot-skipped) list -- both must be
read and summed, reading only the first is only correct at zero
scroll.
"""
from dataclasses import dataclass

from .memory import MemoryError
from .speech import SpeechEventClass


@dataclass(frozen=True)
class HeroItemSlot:
    item_id: int
    quantity: int


class HeroItemArraySource:
    """Raw item-record access into the hero's own per-category arrays.
    Knows nothing about the item database or text -- only raw IDs and
    quantities, and how to skip empty slots to find the Nth valid one."""

    def __init__(self, memory, profile):
        self.memory = memory
        self.profile = profile

    def _hero_base(self):
        p = self.profile
        savedata = self.memory.pointer(
            p.savedata_pointer_address,
            p.hero_offset + p.hero_party_offset
            + p.hero_party_slots * p.hero_party_stride,
            "bag hero savedata pointer",
            4,
        )
        return savedata + p.hero_offset

    def _array_base(self, category):
        p = self.profile
        return self._hero_base() + p.bag_category_array_offsets[category]

    def slot(self, category, slot_index):
        p = self.profile
        base = self._array_base(category) + slot_index * p.hero_item_record_stride
        item_id = self.memory.u16(
            base + p.hero_item_record_id_offset, "hero item record id")
        quantity = self.memory.u16(
            base + p.hero_item_record_quantity_offset, "hero item record qty")
        return HeroItemSlot(item_id=item_id, quantity=quantity)

    def valid_slot_at_row(self, category, row):
        """The Nth (0-based) valid (non-empty) slot in this category's
        array, mirroring `_getItemIDFromMenuPos`'s own empty-slot-skipping
        walk. Returns None if `row` is beyond the last valid slot."""
        p = self.profile
        max_slots = p.bag_category_slot_counts[category]
        valid_count = -1
        for slot_index in range(max_slots):
            slot = self.slot(category, slot_index)
            if slot.item_id == 0:
                continue
            valid_count += 1
            if valid_count == row:
                return slot
        return None

    def valid_slot_count(self, category):
        p = self.profile
        max_slots = p.bag_category_slot_counts[category]
        count = 0
        for slot_index in range(max_slots):
            if self.slot(category, slot_index).item_id != 0:
                count += 1
        return count


@dataclass(frozen=True)
class BagSelection:
    category: int
    category_label: str
    row: int
    item_id: int | None
    quantity: int | None
    valid_count: int
    is_close: bool

    @property
    def is_empty(self):
        # True whenever the category has no real items -- true
        # regardless of is_close, since an empty category's only
        # selectable row (0) IS the close row; the reader decides how
        # to combine the two facts into speech.
        return self.valid_count == 0


class BagMenuModel:
    """The pure "what's currently selected" read -- no speech, no
    dedup, so it stays independently testable and reusable. Returns
    `None` when the bag isn't open, otherwise a `BagSelection` (with
    `row`/`item_id`/`quantity` all `None` when the current category has
    no items)."""

    def __init__(self, memory, profile, item_source):
        self.memory = memory
        self.profile = profile
        self.item_source = item_source

    def _find_window(self):
        p = self.profile
        pointer = self.memory.u32(
            p.window_manager + p.window_list_offset, "bag window-list head")
        seen = set()
        for _ in range(p.window_max_nodes):
            if pointer == 0:
                return None
            if pointer in seen:
                raise MemoryError("bag window list contains a cycle")
            seen.add(pointer)
            menu_id = self.memory.u32(
                pointer + p.window_menu_id_offset, "bag window menu ID")
            if menu_id == p.bag_menu_id:
                return pointer
            pointer = self.memory.u32(
                pointer + p.window_next_offset, "bag next window")
        raise MemoryError("bag window list exceeds verified bound")

    def _row(self, category):
        p = self.profile
        cursor_id = p.bag_category_cursor_ids[category]
        slot_addr = (
            p.pocket_cursor_table_address + cursor_id * p.pocket_cursor_stride)
        x = self.memory.u16(slot_addr, "bag cursor x")
        y = self.memory.u16(slot_addr + 2, "bag cursor y")
        return x + y

    def current_selection(self):
        window = self._find_window()
        if window is None:
            return None
        p = self.profile
        category = self.memory.u8(window + p.bag_category_index_offset,
                                   "bag category")
        label = p.bag_category_labels[category]
        valid_count = self.item_source.valid_slot_count(category)
        row = self._row(category)
        # The list always has exactly one extra selectable row
        # immediately after the last real item (row == valid_count,
        # including row 0 when the category has none) -- confirmed live
        # 2026-07-29: pressing A there exits the bag with no sub-menu.
        # See bag_menu.py's module docstring.
        if row >= valid_count:
            return BagSelection(
                category=category, category_label=label,
                row=row, item_id=None, quantity=None,
                valid_count=valid_count, is_close=True,
            )
        slot = self.item_source.valid_slot_at_row(category, row)
        if slot is None:
            return BagSelection(
                category=category, category_label=label,
                row=row, item_id=None, quantity=None,
                valid_count=valid_count, is_close=True,
            )
        return BagSelection(
            category=category, category_label=label,
            row=row, item_id=slot.item_id, quantity=slot.quantity,
            valid_count=valid_count, is_close=False,
        )


UNKNOWN_ITEM_LABEL = "Unknown item"
# Live-confirmed 2026-07-29 that this trailing row exists and exits the
# bag on A -- its exact on-screen wording (Close/Cancel/Exit) is NOT yet
# confirmed (the project owner wasn't certain themselves; static
# disassembly of the draw function didn't reveal it either). "Close" is
# a placeholder pending OCR confirmation -- change this one constant
# once confirmed, nothing else needs to.
CLOSE_ROW_LABEL = "Close"


class BagMenuReader:
    def __init__(self, memory, profile, model, name_resolver, speech, logger,
                 description_resolver=None):
        self.memory = memory
        self.profile = profile
        self.model = model
        self.name_resolver = name_resolver
        self.description_resolver = description_resolver
        self.speech = speech
        self.logger = logger
        self.active = False
        self.last_category = None
        self.last_row = None

    def clear(self, reason):
        if self.active:
            self.logger.debug("BAG MENU CLEAR reason=%s", reason)
        self.active = False
        self.last_category = None
        self.last_row = None

    def _say(self, text):
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
        self.logger.info("BAG MENU %s", text)

    def _item_label(self, item_id):
        name = self.name_resolver.resolve_name(item_id)
        return name if name else UNKNOWN_ITEM_LABEL

    def _description_suffix(self, item_id):
        if self.description_resolver is None:
            return ""
        description = self.description_resolver.resolve_description(item_id)
        return f" {description}" if description else ""

    def poll_once(self):
        selection = self.model.current_selection()
        if selection is None:
            if self.active:
                self.clear("bag closed")
            return

        category_changed = (
            not self.active or selection.category != self.last_category)
        row_changed = category_changed or selection.row != self.last_row
        if not row_changed:
            return

        if selection.is_close:
            prefix = f"{selection.category_label}. " if category_changed else ""
            empty_clause = "No items. " if selection.is_empty else ""
            self._say(f"{prefix}{empty_clause}{CLOSE_ROW_LABEL}.")
            self.active = True
            self.last_category = selection.category
            self.last_row = selection.row
            return

        if category_changed:
            label = self._item_label(selection.item_id)
            text = (
                f"{label}. Quantity {selection.quantity}. "
                f"{selection.category_label}."
                f"{self._description_suffix(selection.item_id)}"
            )
        else:
            label = self._item_label(selection.item_id)
            text = (
                f"{label}. Quantity {selection.quantity}."
                f"{self._description_suffix(selection.item_id)}"
            )

        self._say(text)

        self.active = True
        self.last_category = selection.category
        self.last_row = selection.row
