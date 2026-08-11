"""Generate Companion/assets/interactables.json from the extracted data.

Offline, run-once-per-extraction. Resolves every 0x0100 interaction record
to its owning room-script handler, classifies the handler from its OWN
standard-library calls, and writes the result. Nothing in the output is
typed in by hand -- re-running it against a different extraction produces
a different table.

    python Companion/build_interactable_table.py
"""
import collections
import json
import struct
from pathlib import Path

import _dialogue_extraction_tool as extraction

from battle_narrator.interactable_roles import GENERIC_LABEL, LABELS, classify
from battle_narrator.npc_roles import function_table, parse_room_script

BASE = Path(__file__).resolve().parent
ROOMS = BASE / "_dialogue_extraction" / "rooms"
COMMON = BASE / "_dialogue_extraction" / "raw" / "files" / "common.fsys"
OUT = BASE / "assets" / "interactables.json"

STRIDE = 0x1C
ROOM_SCRIPT_MARKER = 0x0100


def load_records():
    files = extraction.parse_fsys(COMMON.read_bytes())
    data = next(f["data"] for f in files
                if f["name"] in {"common.rel", "common_rel"})
    rel = extraction.RelFile(data)
    table = rel.get_pointer(62)
    count = struct.unpack_from(">I", data, rel.get_pointer(63))[0]
    for index in range(count):
        offset = table + index * STRIDE
        if struct.unpack_from(">H", data, offset + 0x08)[0] != ROOM_SCRIPT_MARKER:
            continue
        yield {
            "index": index,
            "room": struct.unpack_from(">H", data, offset + 0x02)[0],
            "region": data[offset + 0x07],
            "method": data[offset],
            "function": struct.unpack_from(">H", data, offset + 0x0A)[0],
        }


def main():
    room_codes = {
        int(key, 16): value
        for key, value in json.loads(
            (BASE / "assets" / "room_ids.json").read_text(encoding="utf-8")
        ).items()
    }
    cache = {}

    def room_script(code):
        if code not in cache:
            path = ROOMS / f"{code}.txt"
            if not path.is_file():
                cache[code] = (None, None)
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
                cache[code] = (function_table(text), parse_room_script(text))
        return cache[code]

    entries = {}
    stats = collections.Counter()
    unresolved = collections.Counter()
    for record in load_records():
        code = room_codes.get(record["room"])
        names, graph = room_script(code) if code else (None, None)
        handler = None
        if names and record["function"] < len(names):
            handler = names[record["function"]]
        if handler is None:
            stats["no handler"] += 1
            continue
        direct = set(graph[handler][1]) if graph and handler in graph else set()
        semantic = classify(direct)
        stats[semantic or "unclassified"] += 1
        if semantic is None:
            unresolved[handler] += 1
        entries[str(record["index"])] = {
            "room": record["room"],
            "region": record["region"],
            "method": record["method"],
            "handler": handler,
            "class": semantic,
        }

    OUT.write_text(
        json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")

    print(f"records written: {len(entries)}")
    for name, n in stats.most_common():
        label = LABELS.get(name, GENERIC_LABEL if name == "unclassified" else name)
        print(f"  {n:4d}  {name:14s} -> {label}")
    print(f"\nunclassified handlers ({len(unresolved)} distinct), top 20:")
    for handler, n in unresolved.most_common(20):
        print(f"  {n:4d}  {handler}")


if __name__ == "__main__":
    main()
