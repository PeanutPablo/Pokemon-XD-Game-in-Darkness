"""
Local, read-only, offline dialogue-text extraction tool for the user's own
legally-owned vanilla US Pokemon XD disc image. Never touches a running
game/Dolphin -- purely static file parsing. Output (decoded game text) is
written under Companion/_dialogue_extraction/, which is gitignored per
TEXT_AND_DIALOGUE_PIPELINE.md section 11 (copyrighted game text must stay
local, never committed/distributed).

Implements, in Python, the same format understanding documented in
TEXT_AND_DIALOGUE_PIPELINE.md, cross-checked directly against source in
this session:
  - FSYS container format: Research/ThirdParty/pokemon_fsys_tool/pokemon_fsys_tool.cpp
    (struct fsys_header_data / fsys_offsets_data / fsys_file_entry, all
    big-endian; LZSS decompression for compressed entries).
  - REL (relocatable module) header + section table + relocation-command
    walking to reconstruct the "common pointer table" (CommonIndexes enum):
    Pokemon-XD-Code/Objects/file formats/XGRelocationTable.swift.
  - String table format + control-code table:
    Pokemon-XD-Code/Objects/file formats/XGStringTable.swift and
    enums/XGSpecialStringCharacters.swift.

All multi-byte fields are big-endian (GameCube-native).
"""
import struct
import sys
import os
import json

# ---------------------------------------------------------------------------
# FSYS container parsing (ported from pokemon_fsys_tool.cpp)
# ---------------------------------------------------------------------------

FILE_COMPRESS_FLAG = 0x80000000


def u32(data, off):
    return struct.unpack_from(">I", data, off)[0]


def cstr(data, off):
    end = data.index(b"\x00", off)
    return data[off:end].decode("shift_jis", errors="replace")


def decode_lzss(src, out_size):
    """Decompress one LZSS stream into a fixed `out_size` buffer.

    The output buffer is allocated at `out_size` and zero-filled, and
    decoding stops when either the buffer is full or the compressed input
    runs out -- whichever happens first. The input running out first is
    NOT treated as an error, because a declared size larger than the
    stream is a real condition in real images rather than a sign of
    corruption.

    It was found in Pokemon XG 1.2.1's `common.fsys`, whose
    `DeckData_DarkPokemon_EU.bin` declares 500 bytes (in both the FSYS
    entry and the LZSS header) from a stream that encodes exactly 208.
    208 is not an arbitrary stopping point: the decoded bytes begin with
    a `DECK` header whose own self-declared length field reads 208, so
    the stream is complete for the data that actually exists and only the
    outer size fields disagree. The console never notices -- it
    decompresses into a fixed-size allocation and reads only the length
    the `DECK` header gives -- and neither does a US build, which does
    not read the EU deck at all.

    Raising here instead cost far more than the entry is worth: every
    loader in the companion reaches its own table through `parse_fsys`,
    which decodes every entry in the archive, so one short stream in a
    file nothing reads took down species names, moves, items, warps and
    dialogue together. Zero-padding keeps the failure proportional to the
    damage: callers that want the short entry get its real bytes followed
    by zeros, and callers that want any other entry are unaffected."""
    N = 4096
    F = 18
    THRESHOLD = 2
    text_buf = bytearray(N + F - 1)
    magic = src[0:4]
    if magic != b"LZSS":
        raise RuntimeError(f"Invalid LZSS magic: {magic!r}")
    in_size = u32(src, 8)
    src = src[16:16 + (in_size - 16)]
    available = len(src)
    dst = bytearray(out_size)
    dst_pos = 0
    text_buf_pos = N - F
    flag = 0
    pos = 0
    while dst_pos < out_size:
        if not (flag & 0x100):
            if pos >= available:
                break
            value = src[pos]
            pos += 1
            flag = 0xFF00 | value
        if flag & 1:
            if pos >= available:
                break
            value = src[pos]
            pos += 1
            dst[dst_pos] = value
            text_buf[text_buf_pos] = value
            dst_pos += 1
            text_buf_pos = (text_buf_pos + 1) % N
        else:
            if pos + 1 >= available:
                break
            byte1 = src[pos]
            byte2 = src[pos + 1]
            pos += 2
            ofs = ((byte2 & 0xF0) << 4) | byte1
            copy_size = (byte2 & 0xF) + THRESHOLD + 1
            for _ in range(copy_size):
                # A back-reference near the end of the buffer can name
                # more bytes than remain; the surplus belongs to nothing
                # and is dropped rather than overrunning the allocation.
                if dst_pos >= out_size:
                    break
                v = text_buf[ofs]
                dst[dst_pos] = v
                text_buf[text_buf_pos] = v
                ofs = (ofs + 1) % N
                text_buf_pos = (text_buf_pos + 1) % N
                dst_pos += 1
        flag >>= 1
    return bytes(dst)


def parse_fsys_index(data):
    """Entry metadata for one archive, WITHOUT decompressing anything.

    Split out of `parse_fsys` for the whole-disc sweeps: hunting one file
    type across every archive on the disc costs about a second per archive
    if each entry is LZSS-decoded on the way past, which is a quarter of
    an hour over a full disc. The index alone is enough to decide which
    entries are wanted; `read_fsys_entry` then pays that cost only for
    those."""
    magic = data[0:4]
    if magic != b"FSYS":
        raise RuntimeError(f"Invalid FSYS magic: {magic!r}")
    num_files = u32(data, 12)
    ofs_table_ofs = u32(data, 24)
    file_list_ofs = u32(data, ofs_table_ofs)

    entries = []
    for i in range(num_files):
        entry_ofs = u32(data, file_list_ofs + i * 4)
        entries.append({
            "id": u32(data, entry_ofs),
            "offset": u32(data, entry_ofs + 4),
            "size": u32(data, entry_ofs + 8),
            "flags": u32(data, entry_ofs + 12),
            "compressed_size": u32(data, entry_ofs + 20),
            "type": u32(data, entry_ofs + 32),
            "name": cstr(data, u32(data, entry_ofs + 36)),
        })
    return entries


def read_fsys_entry(data, entry):
    """Decode a single entry returned by `parse_fsys_index`."""
    if entry["flags"] & FILE_COMPRESS_FLAG:
        raw = data[entry["offset"]:entry["offset"] + entry["compressed_size"]]
        return decode_lzss(raw, entry["size"])
    return data[entry["offset"]:entry["offset"] + entry["size"]]


def parse_fsys(data):
    return [
        {"id": entry["id"], "name": entry["name"], "type": entry["type"],
         "data": read_fsys_entry(data, entry)}
        for entry in parse_fsys_index(data)
    ]


# ---------------------------------------------------------------------------
# REL parsing + common pointer-table reconstruction
# (ported from Pokemon-XD-Code/Objects/file formats/XGRelocationTable.swift)
# ---------------------------------------------------------------------------

class RelFile:
    def __init__(self, data):
        self.data = data
        self._parse_header()
        self._parse_pointers()

    def _parse_header(self):
        d = self.data
        self.num_sections = u32(d, 0x0C)
        self.section_info_ofs = u32(d, 0x10)
        self.rel_version = u32(d, 0x1C)
        self.relocations_ofs = u32(d, 0x24)

        self.sections = {}
        for i in range(self.num_sections):
            entry_ofs = self.section_info_ofs + i * 8
            word0 = u32(d, entry_ofs)
            length = u32(d, entry_ofs + 4)
            is_exec = bool(word0 & 1)
            offset = word0 & 0xFFFFFFFE
            self.sections[i] = {
                "section_data_offset": offset,
                "is_text": is_exec,
                "length": length,
            }

    def _parse_pointers(self):
        d = self.data
        self.pointers = {}  # id -> (section, dataPointer)
        pointer_by_target = {}
        current_offset = self.relocations_ofs
        current_id = 0

        while current_offset <= len(d) - 8:
            command = d[current_offset + 2]
            section_id = d[current_offset + 3]
            symbol_offset = u32(d, current_offset + 4)

            if command == 203:  # R_DOLPHIN_END
                break

            if 0 < command <= 13:
                section = self.sections.get(section_id)
                if section is None:
                    raise RuntimeError(f"Invalid section {section_id} in relocation command @0x{current_offset:X}")
                file_offset = section["section_data_offset"] + symbol_offset
                if file_offset in pointer_by_target:
                    pass  # already assigned an id
                else:
                    pointer_by_target[file_offset] = current_id
                    self.pointers[current_id] = {"section": section_id, "data_pointer": file_offset}
                    current_id += 1
            current_offset += 8

    def get_pointer(self, index):
        info = self.pointers.get(index)
        return info["data_pointer"] if info else -1


# ---------------------------------------------------------------------------
# String table parsing (ported from XGStringTable.swift)
# ---------------------------------------------------------------------------

# opcode -> (name, extra_byte_count)
K2_BYTE = {0x07, 0x09, 0x38, 0x52, 0x53, 0x5B, 0x5C}
K5_BYTE = {0x08}

OPCODE_NAMES = {
    0x00: "New Line", 0x02: "Dialogue End", 0x03: "Clear Window",
    0x04: "Kanji", 0x05: "Furigana Start", 0x06: "Furigana End",
    0x07: "Change Font", 0x08: "Change Colour (RGBA)", 0x09: "Pause",
    0x13: "Player Battle 19", 0x14: "Switch Pokemon 20", 0x15: "Switch Pokemon 21",
    0x22: "Foe Tr Class 34", 0x23: "Foe Tr Name 35",
    0x2B: "Player Field 43", 0x2C: "Rui 44",
    0x38: "Change Colour (Predef)", 0x4D: "MsgID 77", 0x50: "Pokemon Cry 80",
    0x59: "Speaker", 0x6A: "Set Speaker 106", 0x6D: "Wait Input 109",
    0x0F: "Pokemon 15", 0x10: "Pokemon 16", 0x11: "Pokemon 17", 0x12: "Pokemon 18",
    0x28: "Move 40", 0x29: "Item 41", 0x2D: "Item 45", 0x2E: "Item 46",
    0x2F: "Quantity 47",
    0x1A: "Ability 26", 0x1B: "Ability 27", 0x1C: "Ability 28", 0x1D: "Ability 29",
}


def extra_bytes_for_opcode(opcode):
    if opcode in K2_BYTE:
        return 1
    if opcode in K5_BYTE:
        return 4
    return 0


def decode_string_table(table_data):
    """Returns {id: [tokens]} where each token is ('char', codepoint) or ('ctrl', opcode, extra_bytes)."""
    num_entries = struct.unpack_from(">H", table_data, 0x04)[0]
    entries = []
    cur = 0x10
    for _ in range(num_entries):
        sid = u32(table_data, cur) & 0xFFFFF
        offset = u32(table_data, cur + 4)
        entries.append((sid, offset))
        cur += 8

    result = {}
    for sid, offset in entries:
        tokens = []
        pos = offset
        while True:
            if pos + 2 > len(table_data):
                break
            ch = struct.unpack_from(">H", table_data, pos)[0]
            pos += 2
            if ch == 0x0000:
                break
            if ch == 0xFFFF:
                opcode = table_data[pos]
                pos += 1
                extra = extra_bytes_for_opcode(opcode)
                extra_bytes = table_data[pos:pos + extra]
                pos += extra
                tokens.append(("ctrl", opcode, extra_bytes))
            else:
                tokens.append(("char", ch))
        result[sid] = tokens
    return result


def render_tokens(tokens):
    out = []
    for tok in tokens:
        if tok[0] == "char":
            cp = tok[1]
            if cp == 0x0A or cp == 0x00:
                continue
            try:
                out.append(chr(cp))
            except ValueError:
                out.append(f"<U+{cp:04X}>")
        else:
            _, opcode, extra = tok
            if opcode == 0x00:
                out.append("\n")
            else:
                name = OPCODE_NAMES.get(opcode, f"opcode_0x{opcode:02X}")
                out.append(f"[{name}]")
    return "".join(out)


# ---------------------------------------------------------------------------
# Main: extract common.fsys -> common.rel -> string tables 98/99/100
# ---------------------------------------------------------------------------

COMMON_INDEXES = {"StringTable1": 98, "StringTable2": 99, "StringTable3": 100}


def main():
    fsys_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "_dialogue_extraction", "raw", "files", "common.fsys")
    out_dir = os.path.join(os.path.dirname(__file__), "_dialogue_extraction")
    os.makedirs(out_dir, exist_ok=True)

    with open(fsys_path, "rb") as f:
        fsys_data = f.read()

    files = parse_fsys(fsys_data)
    print(f"common.fsys contains {len(files)} entries")
    for f in files:
        print(f"  id={f['id']} type={f['type']} name={f['name']!r} size={len(f['data'])}")

    rel_entry = next((f for f in files if f["name"] == "common.rel"), None)
    if rel_entry is None:
        rel_entry = next((f for f in files if f["type"] == 14), None)
    if rel_entry is None:
        print("ERROR: could not find common.rel inside common.fsys")
        return 1

    print(f"\nFound {rel_entry['name']!r}, {len(rel_entry['data'])} bytes")
    rel = RelFile(rel_entry["data"])
    print(f"REL: {rel.num_sections} sections, version {rel.rel_version}")
    for i, s in rel.sections.items():
        print(f"  section {i}: offset=0x{s['section_data_offset']:X} length=0x{s['length']:X} exec={s['is_text']}")

    combined = {}
    for name, idx in COMMON_INDEXES.items():
        ptr = rel.get_pointer(idx)
        print(f"\n{name} (index {idx}): file offset = 0x{ptr:X}" if ptr >= 0 else f"\n{name}: NOT FOUND")
        if ptr < 0:
            continue
        table_data = rel_entry["data"][ptr:]
        try:
            decoded = decode_string_table(table_data)
        except Exception as exc:
            print(f"  ERROR decoding {name}: {exc}")
            continue
        print(f"  {len(decoded)} strings decoded")
        for sid, tokens in decoded.items():
            if sid not in combined:
                combined[sid] = tokens

    out_json = os.path.join(out_dir, "common_strings.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({str(k): render_tokens(v) for k, v in combined.items()}, f, ensure_ascii=False, indent=1)
    print(f"\nWrote {len(combined)} combined common-table strings to {out_json}")

    # Sanity check against the observed live battle message IDs
    test_ids = [337, 89, 188, 349]
    print("\n--- Lookup of observed battle message IDs ---")
    for tid in test_ids:
        if tid in combined:
            print(f"  id {tid}: {render_tokens(combined[tid])!r}")
        else:
            print(f"  id {tid}: NOT FOUND in common tables")

    return 0


if __name__ == "__main__":
    sys.exit(main())
