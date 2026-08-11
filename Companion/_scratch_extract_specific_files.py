"""Extract a small, specific set of files from a plain GameCube ISO by
parsing its FST directly -- avoids re-running a full multi-thousand-file
extraction (wit.exe EXTRACT has no per-file filter) when disk space is
tight and only a handful of files are actually needed.

Read-only against the ISO. GC disc header: DOL offset @0x420, FST offset
@0x424, FST size @0x428. FST entry = 12 bytes (type, name_offset[3],
file_offset/parent[4], file_length/next[4]); root entry's third field is
the total entry count. String table follows the entry array immediately.
"""
import struct
import sys
from pathlib import Path

iso_path = Path(sys.argv[1])
dest_dir = Path(sys.argv[2])
targets = set(sys.argv[3:])
dest_dir.mkdir(parents=True, exist_ok=True)

with open(iso_path, "rb") as handle:
    handle.seek(0x424)
    fst_offset = struct.unpack(">I", handle.read(4))[0]
    handle.seek(fst_offset)
    root = handle.read(12)
    entry_count = struct.unpack(">I", root[8:12])[0]
    print(f"FST offset=0x{fst_offset:X} entry_count={entry_count}")

    entries_bytes = entry_count * 12
    handle.seek(fst_offset)
    raw_entries = handle.read(entries_bytes)
    string_table_offset = fst_offset + entries_bytes
    handle.seek(string_table_offset)
    # String table runs to end of FST region; read generously.
    handle.seek(0x428)
    fst_size = struct.unpack(">I", handle.read(4))[0]
    string_table = None
    handle.seek(string_table_offset)
    string_table = handle.read(fst_size - entries_bytes)

    def name_at(name_offset):
        end = string_table.index(b"\0", name_offset)
        return string_table[name_offset:end].decode("ascii", errors="replace")

    found = {}
    for index in range(1, entry_count):
        entry = raw_entries[index * 12: index * 12 + 12]
        entry_type = entry[0]
        name_offset = int.from_bytes(entry[1:4], "big")
        field2 = struct.unpack(">I", entry[4:8])[0]
        field3 = struct.unpack(">I", entry[8:12])[0]
        if entry_type != 0:
            continue
        name = name_at(name_offset)
        if name in targets:
            found[name] = (field2, field3)

    print(f"Matched {len(found)} of {len(targets)} target files: {sorted(found)}")
    for name, (file_offset, file_length) in found.items():
        handle.seek(file_offset)
        data = handle.read(file_length)
        out_path = dest_dir / name
        out_path.write_bytes(data)
        print(f"  wrote {name}: {file_length} bytes -> {out_path}")

    missing = targets - set(found)
    if missing:
        print(f"NOT FOUND: {sorted(missing)}")
