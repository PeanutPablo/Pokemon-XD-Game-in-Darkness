"""Static, read-only resolver for the game's item database -- shared
infrastructure for every inventory-related screen (Bag, Shops, PC
Storage, the Evolution Stone menu, and any future item list), not a
bag-specific helper. Loads entirely from the already-extracted
common.fsys; the only live-memory input any caller needs to supply is a
raw item ID read from wherever that specific screen stores its own item
records -- this module has no concept of bags, cursors, or windows.

Ownership chain (2026-07-29, static analysis first per the project's
reverse-engineering philosophy, one narrow live read used only to
confirm the final result against a real, project-owner-confirmed item):

    raw item ID
      -> ValidItems[item ID]        (REL pointer 68, bounded by
                                     TotalNumberOfItems, REL pointer 69)
      -> dense database index
      -> Items[dense index]         (REL pointer 70, bounded by
                                     NumberOfItems, REL pointer 71;
                                     0x28-byte-stride records)
      -> name message ID at record offset +0x10
      -> resolved string via `entity_names.ScriptedSpeakerNameTable`,
         the same general message-table resolver (REL pointer 136)
         already used for move/ability/species/scripted-speaker names
         -- reused directly here, not reimplemented, so this module
         deliberately stops at the message ID and leaves final text
         resolution to that existing class.

Description text is a SEPARATE chain, not the same table: the item
record's description message ID (offset +0x14, immediately after the
name ID, cross-confirmed via the community tool's field ordering and by
computing the full 0x28-byte record layout field-by-field) resolves
through `pocket_menu.fsys`'s own local message table -- the same
per-context "local .fsys message table" pattern `messages.
FightCommonCatalog` already uses for battle text, just a different file
and message-ID range entirely disjoint from the general common.rel
table. Confirmed 2026-07-29 by reading item #13's real description
("Restores the HP of a POKéMON by 20 points.") straight out of a fresh,
one-file targeted extraction of `pocket_menu.fsys` -- matches the
well-known real Potion description exactly.

Cross-confirmed four independent ways: static PowerPC disassembly of
`itemDataBiosGetPtr`/`itemDataBiosGetName`/`itemDB_GetName`
(xd-decomp's asm output), the community `Pokemon-XD-Code` tool's own
documented item struct layout (Name ID at the same +0x10 offset,
resolved via common_rel -- see its `ItemsTable.swift`), that same
tool's `XGBagSlots`/`XDRelIndexes` enums (bag-slot "kind" values and
these exact REL pointer indices), and one live memory read the project
owner directly confirmed against a real item ("yes its a potion" --
item ID 13, message ID 5013, resolved name "Potion").
"""
import struct
from dataclasses import dataclass
from pathlib import Path

import _dialogue_extraction_tool as extraction

from .messages import LocalDataError

VALID_ITEMS_REL_POINTER = 68
TOTAL_NUMBER_OF_ITEMS_REL_POINTER = 69
ITEMS_REL_POINTER = 70
NUMBER_OF_ITEMS_REL_POINTER = 71
GENERAL_STRING_TABLE_REL_POINTER = 136

ITEM_RECORD_STRIDE = 0x28
ITEM_RECORD_KIND_OFFSET = 0x00
# +0x06, u16 -- confirmed via xd-decomp's itemDataBiosGetPrice
# (game/pxdvs/app/item/itemBios.s:1634, `lhz r3, 0x6(r3)`), then live cross-
# checked 2026-07-30 against a real shop's Pokémart stock: item 13 (Potion)
# read 300, item 22 (Super Potion) 700, item 14 (Antidote) 100 -- all
# matching this series' well-known, publicly documented real prices, not
# just internally self-consistent.
ITEM_RECORD_PRICE_OFFSET = 0x06
ITEM_RECORD_COUPON_PRICE_OFFSET = 0x08
ITEM_RECORD_NAME_MESSAGE_ID_OFFSET = 0x10
ITEM_RECORD_DESCRIPTION_MESSAGE_ID_OFFSET = 0x14

DESCRIPTION_FSYS_ENTRY_TYPE = 5
DESCRIPTION_FSYS_ENTRY_NAME = "pocket_menu"

# Bag-slot "kind" values an item record's own +0x0 byte can hold (from
# static disassembly of heroItemGetItemKindToItemAryPtr's dispatch table,
# cross-confirmed by Pokemon-XD-Code's XGBagSlots enum). Not needed by
# this module operationally -- kept only for callers that want to
# sanity-check a record's kind against the category they expect it in.
BAG_SLOT_POKEBALLS = 1
BAG_SLOT_ITEMS = 2
BAG_SLOT_BERRIES = 3
BAG_SLOT_TMS = 4
BAG_SLOT_KEY_ITEMS = 5


@dataclass(frozen=True)
class ItemRecord:
    item_id: int
    kind: int
    price: int
    coupon_price: int
    name_message_id: int
    description_message_id: int


class ItemDatabase:
    """Item ID -> (kind, name message ID) only. Deliberately does not
    resolve the message ID to text itself -- pair with
    `entity_names.ScriptedSpeakerNameTable` (already built and tested
    for exactly this general message-table resolution) for the final
    localized string, keeping database lookup and text resolution as
    separate, independently reusable layers."""

    def __init__(self, common_fsys_path):
        path = Path(common_fsys_path)
        try:
            files = extraction.parse_fsys(path.read_bytes())
            data = next(
                item["data"] for item in files
                if item["name"] in {"common.rel", "common_rel"}
            )
            rel = extraction.RelFile(data)
            self._data = data
            self._valid_items_ptr = rel.get_pointer(VALID_ITEMS_REL_POINTER)
            self._total_number_of_items = struct.unpack_from(
                ">I", data,
                rel.get_pointer(TOTAL_NUMBER_OF_ITEMS_REL_POINTER))[0]
            self._items_ptr = rel.get_pointer(ITEMS_REL_POINTER)
            self._number_of_items = struct.unpack_from(
                ">I", data,
                rel.get_pointer(NUMBER_OF_ITEMS_REL_POINTER))[0]
        except Exception as exc:
            raise LocalDataError(
                f"Could not load item database: {exc}") from exc

    def _dense_index(self, item_id):
        if not (0 <= item_id < self._total_number_of_items):
            return None
        offset = self._valid_items_ptr + item_id * 2
        dense_index = struct.unpack_from(">H", self._data, offset)[0]
        if not (0 <= dense_index < self._number_of_items):
            return None
        return dense_index

    def lookup(self, item_id):
        dense_index = self._dense_index(item_id)
        if dense_index is None:
            return None
        record_addr = self._items_ptr + dense_index * ITEM_RECORD_STRIDE
        kind = self._data[record_addr + ITEM_RECORD_KIND_OFFSET]
        price = struct.unpack_from(
            ">H", self._data, record_addr + ITEM_RECORD_PRICE_OFFSET)[0]
        coupon_price = struct.unpack_from(
            ">H", self._data,
            record_addr + ITEM_RECORD_COUPON_PRICE_OFFSET)[0]
        name_message_id = struct.unpack_from(
            ">I", self._data,
            record_addr + ITEM_RECORD_NAME_MESSAGE_ID_OFFSET)[0]
        description_message_id = struct.unpack_from(
            ">I", self._data,
            record_addr + ITEM_RECORD_DESCRIPTION_MESSAGE_ID_OFFSET)[0]
        return ItemRecord(
            item_id=item_id, kind=kind, price=price,
            coupon_price=coupon_price,
            name_message_id=name_message_id,
            description_message_id=description_message_id)


class ItemNameResolver:
    """Combines `ItemDatabase` (item ID -> kind/name message ID) with a
    general message-table resolver (an `entity_names.
    ScriptedSpeakerNameTable` instance in production) into the one call
    every inventory screen actually needs: item ID -> localized name.
    Kept separate from both so each half stays independently testable
    and reusable on its own."""

    def __init__(self, item_database, name_table):
        self.item_database = item_database
        self.name_table = name_table

    def resolve_name(self, item_id):
        record = self.item_database.lookup(item_id)
        if record is None:
            return None
        return self.name_table.resolve(record.name_message_id)


class ItemDescriptionTable:
    """Item description text -- a completely separate local message
    table bundled in `pocket_menu.fsys` (NOT the general common.rel
    table move/ability/item names resolve through; a disjoint message-ID
    range entirely). Same "standalone .fsys local message table" shape
    as `messages.FightCommonCatalog`, applied to this different file."""

    def __init__(self, pocket_menu_fsys_path):
        path = Path(pocket_menu_fsys_path)
        try:
            files = extraction.parse_fsys(path.read_bytes())
            entry = next(
                item for item in files
                if item["type"] == DESCRIPTION_FSYS_ENTRY_TYPE
                and item["name"] == DESCRIPTION_FSYS_ENTRY_NAME
            )
            self.strings = extraction.decode_string_table(entry["data"])
        except Exception as exc:
            raise LocalDataError(
                f"Could not load item description table: {exc}") from exc

    def resolve(self, message_id):
        tokens = self.strings.get(message_id)
        if not tokens:
            return None
        # Unlike names (ScriptedSpeakerNameTable), descriptions routinely
        # wrap across lines -- a plain newline control token (opcode
        # 0x00) is normal here, not a sign of bad data. Any OTHER
        # control opcode is unexpected for description text and treated
        # the same as missing data, rather than rendered as a raw
        # "[opcode_0xNN]" placeholder.
        if any(token[0] == "ctrl" and token[1] != 0x00 for token in tokens):
            return None
        rendered = " ".join(extraction.render_tokens(tokens).split())
        return rendered or None


class ItemDescriptionResolver:
    """Combines `ItemDatabase` (item ID -> description message ID) with
    an `ItemDescriptionTable` into the one call an inventory screen
    needs for description text: item ID -> localized description."""

    def __init__(self, item_database, description_table):
        self.item_database = item_database
        self.description_table = description_table

    def resolve_description(self, item_id):
        record = self.item_database.lookup(item_id)
        if record is None:
            return None
        return self.description_table.resolve(record.description_message_id)
