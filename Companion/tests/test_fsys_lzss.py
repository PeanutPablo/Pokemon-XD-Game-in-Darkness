"""Tests for the FSYS/LZSS layer, pinned to a real defect.

Pokemon XG 1.2.1's `common.fsys` contains one entry,
`DeckData_DarkPokemon_EU.bin`, whose declared uncompressed size (500) is
larger than its stream actually encodes (208). Because every loader in
the companion reaches its table through `parse_fsys`, which decodes every
entry in the archive, that single short stream in a file nothing reads
made species names, moves, items, warps and dialogue all fail to load.

The bytes here are synthetic, in the same spirit as
`test_bootstrap_game_data.py`: the real archives are copyrighted and
cannot live in a repository. What they encode is the format as the tool
reads it, plus the specific shape of the failure above."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import _dialogue_extraction_tool as extraction


def lzss(payload, declared_size=None, truncate_to=None):
    """An LZSS stream of `payload` as all-literal bytes.

    `declared_size` overrides the size written into the header, and
    `truncate_to` cuts the body short, which together reproduce an entry
    that promises more than it delivers."""
    body = b""
    for start in range(0, len(payload), 8):
        chunk = payload[start:start + 8]
        body += b"\xff" + chunk           # 0xff: this group is 8 literals
    if truncate_to is not None:
        body = body[:truncate_to]
    out_size = len(payload) if declared_size is None else declared_size
    header = b"LZSS" + struct.pack(">III", out_size, 16 + len(body), 0)
    return header + body


def fsys(entries):
    """An FSYS archive of [(name, flags, declared_size, blob)]."""
    header_size = 0x40
    entry_size = 0x50
    entry_table = header_size
    names_table = entry_table + len(entries) * entry_size
    name_bytes = b""
    name_offsets = []
    for name, _flags, _size, _blob in entries:
        name_offsets.append(names_table + len(name_bytes))
        name_bytes += name.encode("ascii") + b"\x00"
    pointer_table = names_table + len(name_bytes)
    data_start = pointer_table + 8 + len(entries) * 4

    blobs = b""
    data_offsets = []
    for _name, _flags, _size, blob in entries:
        data_offsets.append(data_start + len(blobs))
        blobs += blob

    records = b""
    for index, (_name, flags, size, blob) in enumerate(entries):
        record = bytearray(entry_size)
        struct.pack_into(">I", record, 0x00, index + 1)          # id
        struct.pack_into(">I", record, 0x04, data_offsets[index])
        struct.pack_into(">I", record, 0x08, size)
        struct.pack_into(">I", record, 0x0C, flags)
        struct.pack_into(">I", record, 0x14, len(blob))          # compressed
        struct.pack_into(">I", record, 0x20, 5)                  # type
        struct.pack_into(">I", record, 0x24, name_offsets[index])
        records += bytes(record)

    pointers = b"".join(
        struct.pack(">I", entry_table + i * entry_size)
        for i in range(len(entries))
    )
    header = bytearray(header_size)
    header[0:4] = b"FSYS"
    struct.pack_into(">I", header, 0x0C, len(entries))
    struct.pack_into(">I", header, 0x18, pointer_table)

    image = bytearray(data_start + len(blobs))
    image[0:header_size] = header
    image[entry_table:entry_table + len(records)] = records
    image[names_table:names_table + len(name_bytes)] = name_bytes
    struct.pack_into(">I", image, pointer_table, pointer_table + 8)
    image[pointer_table + 8:pointer_table + 8 + len(pointers)] = pointers
    image[data_start:data_start + len(blobs)] = blobs
    return bytes(image)


class DecodeLzssTests(unittest.TestCase):
    def test_round_trips_a_well_formed_stream(self):
        payload = bytes(range(200))
        self.assertEqual(
            extraction.decode_lzss(lzss(payload), len(payload)), payload)

    def test_rejects_a_stream_that_is_not_lzss(self):
        with self.assertRaises(RuntimeError):
            extraction.decode_lzss(b"NOPE" + b"\x00" * 32, 16)

    def test_short_stream_yields_its_real_bytes_then_zeros(self):
        """The XG case: the header promises more than the body encodes.

        The bytes that ARE encoded must come back exactly -- padding them
        with zeros is only acceptable because the padding is inert, and it
        would not be if it displaced real data."""
        payload = bytes(range(1, 209))
        stream = lzss(payload, declared_size=500)
        result = extraction.decode_lzss(stream, 500)
        self.assertEqual(len(result), 500)
        self.assertEqual(result[:208], payload)
        self.assertEqual(result[208:], b"\x00" * 292)

    def test_body_cut_mid_group_still_returns_what_it_had(self):
        payload = bytes(range(1, 65))
        stream = lzss(payload, declared_size=64, truncate_to=20)
        result = extraction.decode_lzss(stream, 64)
        self.assertEqual(len(result), 64)
        # 20 body bytes = two full 9-byte groups (8 literals each) plus a
        # flag byte and one literal, so 17 real bytes decode.
        self.assertEqual(result[:17], payload[:17])
        self.assertEqual(result[17:], b"\x00" * 47)


class ParseFsysTests(unittest.TestCase):
    def archive(self):
        good = bytes(range(1, 65))
        short = bytes(range(1, 33))
        return fsys([
            ("common_rel", extraction.FILE_COMPRESS_FLAG, 64, lzss(good)),
            ("DeckData_DarkPokemon_EU.bin", extraction.FILE_COMPRESS_FLAG,
             500, lzss(short, declared_size=500)),
            ("world_map", extraction.FILE_COMPRESS_FLAG, 64, lzss(good)),
        ]), good, short

    def test_index_reports_every_entry(self):
        data, _good, _short = self.archive()
        names = [e["name"] for e in extraction.parse_fsys_index(data)]
        self.assertEqual(
            names,
            ["common_rel", "DeckData_DarkPokemon_EU.bin", "world_map"])

    def test_one_short_entry_does_not_take_down_the_archive(self):
        """The regression this file exists for.

        Before the fix a single entry whose declared size overran its
        stream raised out of `parse_fsys`, so every table in the archive
        became unreachable -- including `common_rel`, which decodes
        perfectly and is what almost every loader actually wants."""
        data, good, short = self.archive()
        files = extraction.parse_fsys(data)
        by_name = {item["name"]: item["data"] for item in files}
        self.assertEqual(by_name["common_rel"], good)
        self.assertEqual(by_name["world_map"], good)
        self.assertEqual(by_name["DeckData_DarkPokemon_EU.bin"][:32], short)

    def test_uncompressed_entries_are_read_verbatim(self):
        payload = bytes(range(1, 41))
        data = fsys([("plain", 0, len(payload), payload)])
        self.assertEqual(extraction.parse_fsys(data)[0]["data"], payload)


if __name__ == "__main__":
    unittest.main()
