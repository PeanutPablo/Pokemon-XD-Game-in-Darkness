import struct
import unittest

from battle_narrator.item_database import (
    ITEM_RECORD_DESCRIPTION_MESSAGE_ID_OFFSET,
    ITEM_RECORD_KIND_OFFSET,
    ITEM_RECORD_NAME_MESSAGE_ID_OFFSET,
    ITEM_RECORD_STRIDE,
    ItemDatabase,
    ItemDescriptionResolver,
    ItemDescriptionTable,
    ItemNameResolver,
)


def make_database(valid_items, records):
    """`valid_items`: list of dense indexes, one per raw item ID (index
    in the list == raw item ID). `records`: list of (kind, name_message_id)
    or (kind, name_message_id, description_message_id) tuples, one per
    dense index -- description defaults to 0 when omitted."""
    db = ItemDatabase.__new__(ItemDatabase)
    valid_items_bytes = b"".join(struct.pack(">H", i) for i in valid_items)
    records_bytes = bytearray()
    for entry in records:
        if len(entry) == 2:
            kind, name_message_id = entry
            description_message_id = 0
        else:
            kind, name_message_id, description_message_id = entry
        record = bytearray(ITEM_RECORD_STRIDE)
        record[ITEM_RECORD_KIND_OFFSET] = kind
        struct.pack_into(
            ">I", record, ITEM_RECORD_NAME_MESSAGE_ID_OFFSET, name_message_id)
        struct.pack_into(
            ">I", record, ITEM_RECORD_DESCRIPTION_MESSAGE_ID_OFFSET,
            description_message_id)
        records_bytes.extend(record)
    data = bytearray(len(valid_items_bytes) + len(records_bytes) + 0x10)
    data[0:len(valid_items_bytes)] = valid_items_bytes
    records_offset = len(valid_items_bytes) + 0x8
    data[records_offset:records_offset + len(records_bytes)] = records_bytes
    db._data = bytes(data)
    db._valid_items_ptr = 0
    db._total_number_of_items = len(valid_items)
    db._items_ptr = records_offset
    db._number_of_items = len(records)
    return db


def make_description_table(strings):
    table = ItemDescriptionTable.__new__(ItemDescriptionTable)
    table.strings = strings
    return table


def chars(text):
    return [("char", ord(ch)) for ch in text]


class FakeNameTable:
    def __init__(self, names):
        self.names = names

    def resolve(self, message_id):
        return self.names.get(message_id)


class ItemDatabaseTests(unittest.TestCase):
    def test_resolves_kind_and_name_message_id_for_identity_mapped_item(self):
        db = make_database(
            valid_items=[0, 1, 2, 3],
            records=[(1, 100), (2, 101), (3, 102), (4, 103)],
        )
        record = db.lookup(2)
        self.assertEqual(record.item_id, 2)
        self.assertEqual(record.kind, 3)
        self.assertEqual(record.name_message_id, 102)

    def test_resolves_through_a_non_identity_remap(self):
        # item ID 5 maps to dense index 1, not 5 -- the remap table is
        # what makes this correct, not coincidence.
        db = make_database(
            valid_items=[3, 0, 2, 1],
            records=[(9, 900), (9, 901), (9, 902), (9, 903)],
        )
        record = db.lookup(0)
        self.assertEqual(record.name_message_id, 903)
        record = db.lookup(1)
        self.assertEqual(record.name_message_id, 900)

    def test_item_id_beyond_total_number_of_items_returns_none(self):
        db = make_database(valid_items=[0], records=[(1, 100)])
        self.assertIsNone(db.lookup(5))

    def test_negative_item_id_returns_none(self):
        db = make_database(valid_items=[0], records=[(1, 100)])
        self.assertIsNone(db.lookup(-1))

    def test_dense_index_beyond_number_of_items_returns_none(self):
        # ValidItems entry points past the real records table -- must
        # not be trusted blindly.
        db = make_database(valid_items=[99], records=[(1, 100)])
        self.assertIsNone(db.lookup(0))

    def test_resolves_description_message_id_alongside_name(self):
        db = make_database(valid_items=[0], records=[(2, 5013, 10013)])
        record = db.lookup(0)
        self.assertEqual(record.name_message_id, 5013)
        self.assertEqual(record.description_message_id, 10013)


class ItemNameResolverTests(unittest.TestCase):
    def test_resolves_full_chain_to_a_name(self):
        db = make_database(valid_items=[0], records=[(2, 5013)])
        resolver = ItemNameResolver(db, FakeNameTable({5013: "Potion"}))
        self.assertEqual(resolver.resolve_name(0), "Potion")

    def test_unknown_item_id_returns_none(self):
        db = make_database(valid_items=[0], records=[(2, 5013)])
        resolver = ItemNameResolver(db, FakeNameTable({5013: "Potion"}))
        self.assertIsNone(resolver.resolve_name(999))

    def test_message_id_not_in_name_table_returns_none(self):
        db = make_database(valid_items=[0], records=[(2, 9999)])
        resolver = ItemNameResolver(db, FakeNameTable({5013: "Potion"}))
        self.assertIsNone(resolver.resolve_name(0))


class ItemDescriptionTableTests(unittest.TestCase):
    def test_resolves_plain_description(self):
        table = make_description_table(
            {10013: chars("Restores the HP of a POKEMON by 20 points.")})
        self.assertEqual(
            table.resolve(10013),
            "Restores the HP of a POKEMON by 20 points.")

    def test_collapses_embedded_newlines_for_speech(self):
        # Real game text encodes a line break as a control token
        # (opcode 0x00 -> render_tokens emits "\n"), not a plain "char"
        # token with codepoint 0x0A (render_tokens silently drops those).
        newline = ("ctrl", 0x00, b"")
        tokens = (
            chars("Restores the HP of") + [newline]
            + chars("a POKEMON by") + [newline] + chars("20 points.")
        )
        table = make_description_table({10013: tokens})
        self.assertEqual(
            table.resolve(10013),
            "Restores the HP of a POKEMON by 20 points.")

    def test_missing_message_id_returns_none(self):
        table = make_description_table({})
        self.assertIsNone(table.resolve(9999))

    def test_unexpected_control_code_tokens_rejected(self):
        table = make_description_table(
            {100: [("ctrl", 0x2B, b"")] + chars("X")})
        self.assertIsNone(table.resolve(100))

    def test_newline_control_token_is_not_rejected(self):
        # Opcode 0x00 (newline) is routine in multi-line description
        # text -- must not be treated as unexpected/bad data.
        table = make_description_table(
            {100: chars("A") + [("ctrl", 0x00, b"")] + chars("B")})
        self.assertEqual(table.resolve(100), "A B")

    def test_empty_rendered_text_returns_none(self):
        table = make_description_table({100: [("char", 0x0A)]})
        self.assertIsNone(table.resolve(100))


class ItemDescriptionResolverTests(unittest.TestCase):
    def test_resolves_full_chain_to_a_description(self):
        db = make_database(valid_items=[0], records=[(2, 5013, 10013)])
        table = make_description_table({10013: chars("Restores 20 HP.")})
        resolver = ItemDescriptionResolver(db, table)
        self.assertEqual(resolver.resolve_description(0), "Restores 20 HP.")

    def test_unknown_item_id_returns_none(self):
        db = make_database(valid_items=[0], records=[(2, 5013, 10013)])
        table = make_description_table({10013: chars("Restores 20 HP.")})
        resolver = ItemDescriptionResolver(db, table)
        self.assertIsNone(resolver.resolve_description(999))

    def test_message_id_not_in_description_table_returns_none(self):
        db = make_database(valid_items=[0], records=[(2, 5013, 99999)])
        table = make_description_table({10013: chars("Restores 20 HP.")})
        resolver = ItemDescriptionResolver(db, table)
        self.assertIsNone(resolver.resolve_description(0))


if __name__ == "__main__":
    unittest.main()
