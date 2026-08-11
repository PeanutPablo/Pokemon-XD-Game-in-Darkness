"""Tests for the first-run game-data bootstrap.

Everything here is built from synthetic bytes on purpose. The tool's real
inputs are copyrighted disc images that cannot live in a repository or a
release, so the structures it parses -- the GameCube file table, the DOL
section table, and the localised string tables inside the executable --
are constructed here to the same layout the format documents describe.

The one thing these cannot prove is that the layout description is right;
that was established separately by running the tool against a real disc
and byte-comparing all 189 generated files against the copy the project
had already built by hand. These tests exist to keep the parsing honest
from here on, and to pin the specific traps that cost time to find."""
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import _dialogue_extraction_tool as extraction
from bootstrap_game_data import (
    DISC_MAGIC, DiscError, DiscImage, dol_string_tables, to_plain_iso,
)


def string_table(entries, marker=b"US", table_id=1):
    """A localised string table: 16-byte header, (id, offset) records,
    then UTF-16BE text with a 0x0000 terminator, offsets relative to the
    table start."""
    count = len(entries)
    body = b""
    records = b""
    text_base = 0x10 + count * 8
    for string_id, text in entries:
        records += struct.pack(">II", string_id, text_base + len(body))
        body += b"".join(struct.pack(">H", ord(c)) for c in text)
        body += b"\x00\x00"
    header = struct.pack(">IH", table_id, count) + marker + b"\x00" * 8
    return header + records + body


def dol(sections):
    """A DOL whose header points at `sections` [(load_address, data)]."""
    offsets = [0] * 18
    addresses = [0] * 18
    sizes = [0] * 18
    body = b""
    cursor = 0x100
    for index, (address, data) in enumerate(sections):
        offsets[index] = cursor
        addresses[index] = address
        sizes[index] = len(data)
        body += data
        cursor += len(data)
    header = (
        struct.pack(">18I", *offsets)
        + struct.pack(">18I", *addresses)
        + struct.pack(">18I", *sizes)
    )
    return header.ljust(0x100, b"\x00") + body


def disc(files, dol_bytes=b"", game_id=b"GXXE01", revision=0,
         internal_name=b"POKeMON XD", magic=DISC_MAGIC):
    """A minimal GameCube image: header, file table, then file data."""
    names = b""
    name_offsets = []
    for name in files:
        name_offsets.append(len(names))
        names += name.encode("ascii") + b"\x00"

    entry_count = len(files) + 1
    fst_entries_size = entry_count * 12
    fst_size = fst_entries_size + len(names)
    dol_offset = 0x1000
    fst_offset = dol_offset + max(len(dol_bytes), 1)
    fst_offset += (-fst_offset) % 4
    data_offset = fst_offset + fst_size
    data_offset += (-data_offset) % 4

    entries = struct.pack(">III", 0x01000000, 0, entry_count)
    body = b""
    for index, (name, content) in enumerate(files.items()):
        entries += struct.pack(">I", name_offsets[index] & 0xFFFFFF)
        entries += struct.pack(">II", data_offset + len(body), len(content))
        body += content

    header = bytearray(0x440)
    header[0x00:0x06] = game_id
    header[0x07] = revision
    struct.pack_into(">I", header, 0x1C, magic)
    header[0x20:0x20 + len(internal_name)] = internal_name
    struct.pack_into(">I", header, 0x420, dol_offset)
    struct.pack_into(">I", header, 0x424, fst_offset)
    struct.pack_into(">I", header, 0x428, fst_size)

    image = bytearray(data_offset + len(body))
    image[0:0x440] = header
    image[dol_offset:dol_offset + len(dol_bytes)] = dol_bytes
    image[fst_offset:fst_offset + fst_size] = entries + names
    image[data_offset:data_offset + len(body)] = body
    return bytes(image)


class DiscFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, data, name="test.iso"):
        path = self.root / name
        path.write_bytes(data)
        return path


class DiscImageTests(DiscFixture):
    def test_reads_header_fields_and_files(self):
        image = self.write(disc({"common.fsys": b"ABCD", "other.fsys": b"XY"}))
        with DiscImage(image) as image_reader:
            self.assertEqual(image_reader.game_id, "GXXE01")
            self.assertEqual(image_reader.revision, 0)
            self.assertEqual(image_reader.internal_name, "POKeMON XD")
            self.assertEqual(image_reader.read("common.fsys"), b"ABCD")
            self.assertEqual(image_reader.read("other.fsys"), b"XY")

    def test_a_file_that_is_not_a_disc_is_named_as_such(self):
        """Every offset the reader uses comes from a fixed header
        position, so without this check a wrong file is followed into
        nonsense far from the actual mistake."""
        image = self.write(disc({"a.fsys": b"Z"}, magic=0xDEADBEEF))
        with self.assertRaises(DiscError) as caught:
            DiscImage(image)
        self.assertIn("not a GameCube disc image", str(caught.exception))

    def test_unknown_file_name_is_reported(self):
        image = self.write(disc({"a.fsys": b"Z"}))
        with DiscImage(image) as image_reader:
            with self.assertRaises(DiscError):
                image_reader.read("missing.fsys")

    def test_truncated_image_is_reported_not_silently_short(self):
        full = disc({"a.fsys": b"0123456789"})
        image = self.write(full[:-6])
        with DiscImage(image) as image_reader:
            with self.assertRaises(DiscError) as caught:
                image_reader.read("a.fsys")
        self.assertIn("ends early", str(caught.exception))

    def test_dol_size_comes_from_the_section_table(self):
        """main.dol has no length field anywhere -- not in the disc
        header and not in its own. Its size is the end of its furthest
        section, so a reader that assumes a fixed size either truncates
        the string tables or reads past the executable."""
        payload = dol([(0x80003100, b"\xAA" * 32), (0x80005000, b"\xBB" * 48)])
        image = self.write(disc({"a.fsys": b"Z"}, dol_bytes=payload))
        with DiscImage(image) as image_reader:
            read_back = image_reader.read_dol()
        self.assertEqual(len(read_back), 0x100 + 32 + 48)
        self.assertEqual(read_back[0x100:0x120], b"\xAA" * 32)
        self.assertEqual(read_back[0x120:0x150], b"\xBB" * 48)

    def test_a_dol_with_no_sections_is_rejected(self):
        image = self.write(disc({"a.fsys": b"Z"}, dol_bytes=dol([])))
        with DiscImage(image) as image_reader:
            with self.assertRaises(DiscError):
                image_reader.read_dol()


class DolStringTableTests(unittest.TestCase):
    def test_decodes_a_single_table(self):
        table = string_table([(101, "Hello"), (102, "World")])
        strings, tables = dol_string_tables(dol([(0x80000000, table)]))
        self.assertEqual(strings, {"101": "Hello", "102": "World"})
        self.assertEqual(len(tables), 1)

    def test_tables_marked_other_than_US_are_still_read(self):
        """On a retail US disc most of the English text sits in a table
        whose marker is "JP". Filtering the marker down to "US" -- the
        obvious reading of the field -- silently drops about four fifths
        of the strings, and the loss is invisible because what remains
        decodes perfectly."""
        payload = dol([
            (0x80000000, string_table([(1, "from us")], marker=b"US")),
            (0x80001000, string_table([(2, "from jp")], marker=b"JP",
                                      table_id=3)),
        ])
        strings, tables = dol_string_tables(payload)
        self.assertEqual(strings, {"1": "from us", "2": "from jp"})
        self.assertEqual(len(tables), 2)

    def test_control_codes_survive_the_round_trip(self):
        table = string_table([(5, "plain")])
        strings, _ = dol_string_tables(dol([(0x80000000, table)]))
        self.assertEqual(
            strings["5"],
            extraction.render_tokens(
                extraction.decode_string_table(table)[5]))

    def test_a_lowercase_marker_is_not_a_table(self):
        table = bytearray(string_table([(1, "no")]))
        table[6:8] = b"us"
        strings, tables = dol_string_tables(dol([(0x80000000, bytes(table))]))
        self.assertEqual(tables, [])
        self.assertEqual(strings, {})

    def test_nonzero_padding_is_not_a_table(self):
        """The eight zero bytes after the marker are most of what makes
        the signature specific; without them a scan over four megabytes
        of executable turns up dozens of false positives that decode into
        garbage and collide with real string ids."""
        table = bytearray(string_table([(1, "no")]))
        table[8] = 0x01
        strings, tables = dol_string_tables(dol([(0x80000000, bytes(table))]))
        self.assertEqual(tables, [])
        self.assertEqual(strings, {})

    def test_entries_pointing_into_the_entry_array_are_rejected(self):
        table = bytearray(string_table([(1, "no"), (2, "also no")]))
        struct.pack_into(">I", table, 0x10 + 4, 0x08)
        strings, tables = dol_string_tables(dol([(0x80000000, bytes(table))]))
        self.assertEqual(tables, [])
        self.assertEqual(strings, {})

    def test_an_executable_with_no_tables_yields_nothing(self):
        strings, tables = dol_string_tables(dol([(0x80000000, b"\x00" * 512)]))
        self.assertEqual(strings, {})
        self.assertEqual(tables, [])


class DiscFormatTests(DiscFixture):
    def test_plain_iso_is_used_as_is_with_no_temporary_copy(self):
        path = self.write(b"", "game.iso")
        resolved, temporary = to_plain_iso(path, None, self.root, lambda _: None)
        self.assertEqual(resolved, path)
        self.assertIsNone(temporary)

    def test_gcm_is_also_a_plain_image(self):
        path = self.write(b"", "game.gcm")
        resolved, temporary = to_plain_iso(path, None, self.root, lambda _: None)
        self.assertEqual(resolved, path)
        self.assertIsNone(temporary)

    def test_an_unknown_format_lists_what_is_supported(self):
        path = self.write(b"", "game.7z")
        with self.assertRaises(DiscError) as caught:
            to_plain_iso(path, None, self.root, lambda _: None)
        self.assertIn(".iso", str(caught.exception))
        self.assertIn(".rvz", str(caught.exception))

    def test_a_compressed_format_without_dolphintool_says_so(self):
        path = self.write(b"", "game.rvz")
        with self.assertRaises(DiscError) as caught:
            to_plain_iso(path, "/nonexistent/DolphinTool.exe", self.root,
                         lambda _: None)
        self.assertIn("DolphinTool", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
