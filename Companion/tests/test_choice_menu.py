"""Tests for the generic multiple-choice popup reader and the runtime
message catalog it resolves option text through.

Both were built for a real screen: Mt. Battle's "Would you care to take the
MT. BATTLE knockout battle challenge?" (message 31044) with three options
31045/31046/31047 -> YES / INFO / EXIT, which entity-nav previously left
silent as "UNSUPPORTED MENU id=174".
"""
import logging
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.choice_menu import ChoiceMenuReader
from battle_narrator.memory import MemoryReader
from battle_narrator.profile import XD_US_REV0
from battle_narrator.runtime_messages import RuntimeMessageCatalog

P_MW = 0x804E8348
MW = 0x80444D08
TABLE = 0x80A451C0
WINDOW_A = 0x80874E9C
ALLOC_A = 0x80FCFC80
DIALOGUE_WINDOW = 0x80874DE0


def gschar(text, prefix=b"\xFF\xFF\x07\x01"):
    """Encode as the game stores a menu label: a LETTER_FORMAT control code
    (0xFFFF 0x07 with one argument byte) then UTF-16BE, null terminated --
    exactly the shape live message 31045 has."""
    return prefix + text.encode("utf-16-be") + b"\x00\x00"


class FakeBackend:
    def __init__(self, regions):
        self.regions = dict(regions)

    def read_bytes(self, address, size):
        out = bytearray(size)
        for base, blob in self.regions.items():
            for offset in range(len(blob)):
                index = base + offset - address
                if 0 <= index < size:
                    out[index] = blob[offset]
        return bytes(out)


class Speech:
    def __init__(self):
        self.texts = []

    def emit(self, event, text, deduplicate=False, interrupt=None):
        self.texts.append(text)


def logger():
    log = logging.getLogger(f"choice-test-{id(object())}")
    log.addHandler(logging.NullHandler())
    return log


def build(messages, choice_ids, cursor=0, menu_id=174,
          window_chain=((DIALOGUE_WINDOW, 82), (WINDOW_A, 174)),
          trailing=b""):
    """A memory image with one string table and a choice widget."""
    p = XD_US_REV0
    regions = {
        P_MW: struct.pack(">I", MW),
        MW + 0x04: struct.pack(">I", TABLE),
        TABLE + 0x00: struct.pack(">H", 0),
        TABLE + 0x04: struct.pack(">H", len(messages)),
        TABLE + 0x08: struct.pack(">I", 0),
    }
    # Entry array must be sorted ascending -- the engine binary-searches it.
    payload_offset = 0x10 + len(messages) * 8 + 0x40
    for index, (message_id, text) in enumerate(sorted(messages.items())):
        blob = gschar(text)
        regions[TABLE + 0x10 + index * 8] = struct.pack(
            ">II", message_id & 0xFFFFF, payload_offset)
        regions[TABLE + payload_offset] = blob
        payload_offset += len(blob) + 4

    for index, (address, node_menu_id) in enumerate(window_chain):
        regions[address + p.window_menu_id_offset] = struct.pack(">I", node_menu_id)
        nxt = window_chain[index + 1][0] if index + 1 < len(window_chain) else 0
        regions[address + p.window_next_offset] = struct.pack(">I", nxt)
    regions[p.window_manager + p.window_list_offset] = struct.pack(
        ">I", window_chain[0][0])

    regions[WINDOW_A + p.window_alloc_offset] = struct.pack(">I", ALLOC_A)
    regions[WINDOW_A + p.window_param_offset + 2 * 4] = struct.pack(
        ">I", len(choice_ids) - (1 if choice_ids and choice_ids[-1] == 0 else 0)
    )
    regions[ALLOC_A] = b"".join(
        struct.pack(">I", value) for value in choice_ids) + trailing
    regions[WINDOW_A + p.window_cursor_base_offset] = struct.pack(">H", 0)
    regions[WINDOW_A + p.window_cursor_offset] = struct.pack(">H", cursor)

    memory = MemoryReader(FakeBackend(regions), p)
    catalog = RuntimeMessageCatalog(memory, p)
    speech = Speech()
    reader = ChoiceMenuReader(memory, p, catalog, speech, logger())
    return reader, speech, catalog, regions


MT_BATTLE = {
    31044: "Welcome to MT. BATTLE.",
    31045: "YES",
    31046: "INFO",
    31047: "EXIT",
}


class RuntimeMessageCatalogTests(unittest.TestCase):

    def test_resolves_a_message_through_the_binary_search(self):
        _, _, catalog, _ = build(MT_BATTLE, [31045, 31046, 31047, 0])
        self.assertEqual(catalog.text(31045), "YES")
        self.assertEqual(catalog.text(31046), "INFO")
        self.assertEqual(catalog.text(31047), "EXIT")

    def test_unknown_message_resolves_to_none(self):
        _, _, catalog, _ = build(MT_BATTLE, [31045, 31046, 0])
        self.assertIsNone(catalog.text(99999))

    def test_zero_message_id_is_not_looked_up(self):
        _, _, catalog, _ = build(MT_BATTLE, [31045, 31046, 0])
        self.assertIsNone(catalog.text(0))

    def test_speaker_opcode_value_is_not_stripped_from_ordinary_text(self):
        """Regression: SPEAKER is 0x59, which is also the letter 'Y'.
        Treating a bare character equal to an opcode as that opcode ate the
        Y from 'YES' -- live, the label came back as 'ES'."""
        _, _, catalog, _ = build({31045: "YES"}, [31045, 0])
        self.assertEqual(catalog.text(31045), "YES")


class ChoiceMenuReaderTests(unittest.TestCase):

    def test_announces_selected_option_with_position(self):
        reader, speech, _, _ = build(MT_BATTLE, [31045, 31046, 31047, 0])
        reader.poll_once()
        self.assertEqual(speech.texts, ["YES. 1 of 3."])

    def test_cursor_movement_announces_the_new_option(self):
        reader, speech, _, regions = build(
            MT_BATTLE, [31045, 31046, 31047, 0], cursor=0)
        reader.poll_once()
        regions[XD_US_REV0.window_cursor_offset + 0x80874E9C] = struct.pack(">H", 2)
        reader.memory.backend.regions[
            0x80874E9C + XD_US_REV0.window_cursor_offset] = struct.pack(">H", 2)
        reader.poll_once()
        self.assertEqual(speech.texts, ["YES. 1 of 3.", "EXIT. 3 of 3."])

    def test_same_selection_is_not_repeated(self):
        reader, speech, _, _ = build(MT_BATTLE, [31045, 31046, 31047, 0])
        for _ in range(8):
            reader.poll_once()
        self.assertEqual(speech.texts, ["YES. 1 of 3."])

    def test_garbage_after_the_options_is_not_counted(self):
        """Parameter 2 bounds the copied array; trailing allocation bytes
        are not options even if they happen to resolve as message IDs."""
        messages = {31049: "CONTINUE", 31050: "QUIT"}
        reader, speech, _, _ = build(
            messages, [31049, 31050],
            trailing=struct.pack(">II", 0xFFFFFFFE, 0x0007083F))
        reader.poll_once()
        self.assertEqual(speech.texts, ["CONTINUE. 1 of 2."])

    def test_single_option_is_not_treated_as_a_choice_list(self):
        reader, speech, _, _ = build(MT_BATTLE, [31045, 0])
        reader.poll_once()
        self.assertEqual(speech.texts, [])

    def test_ignored_menu_ids_are_skipped(self):
        """menus.py already narrates the yes/no overlay from its own labels;
        this reader must not speak over it."""
        reader, speech, catalog, _ = build(MT_BATTLE, [31045, 31046, 31047, 0])
        reader.ignored_menu_ids = frozenset({174})
        reader.poll_once()
        self.assertEqual(speech.texts, [])

    def test_closing_the_widget_clears_and_allows_re_announcement(self):
        reader, speech, _, _ = build(MT_BATTLE, [31045, 31046, 31047, 0])
        reader.poll_once()
        reader.memory.backend.regions[
            XD_US_REV0.window_manager + XD_US_REV0.window_list_offset
        ] = struct.pack(">I", DIALOGUE_WINDOW)
        reader.memory.backend.regions[
            DIALOGUE_WINDOW + XD_US_REV0.window_next_offset] = struct.pack(">I", 0)
        reader.poll_once()
        self.assertFalse(reader.active)


if __name__ == "__main__":
    unittest.main()
