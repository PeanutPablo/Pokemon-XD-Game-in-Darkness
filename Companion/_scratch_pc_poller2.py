"""Pass 2: wide byte-level diff scanner focused on the Pokemon Storage box
burst windows (menu_ids 89 and its 8 siblings), to find the real grid-slot
cursor field that the narrow +0x9F/+0xA3/+0x9C/+0x9E/+0xB8 scan in pass 1
did not capture (it only ever toggled 0/1, not a real flat slot index).

Read-only. Never sends input. Play normally; no narration needed except a
rough summary afterward.
"""
import functools
import sys
import time

print = functools.partial(print, flush=True)

import dolphin_memory_engine as dme

from battle_narrator.memory import MemoryReader
from battle_narrator.menus import WindowListWalker
from battle_narrator.profile import XD_US_REV0

dme.hook()
if not dme.is_hooked():
    raise SystemExit("Dolphin is not readable.")
memory = MemoryReader(dme, XD_US_REV0)
walker = WindowListWalker(memory, XD_US_REV0)

WATCH_MENU_IDS = {89, 138, 130, 128, 132, 133, 135, 136, 137, 227, 123, 44}
NODE_SIZE = XD_US_REV0.window_node_size  # 0xBC

last_state = {}
last_bytes = {}
print("Pass 2 polling started. Focus on the box grid this time.", flush=True)
start = time.monotonic()
duration = float(sys.argv[1]) if len(sys.argv) > 1 else None
while duration is None or time.monotonic() - start < duration:
    try:
        nodes = walker.walk()
    except Exception:
        nodes = []
    snapshot = {}
    raw = {}
    for node in nodes:
        snapshot[node.address] = node.menu_id
        if node.menu_id in WATCH_MENU_IDS:
            try:
                raw[node.address] = memory.bytes(node.address, NODE_SIZE, "window node")
            except Exception:
                raw[node.address] = None
    if snapshot != last_state:
        t = time.monotonic() - start
        added = set(snapshot) - set(last_state)
        removed = set(last_state) - set(snapshot)
        print(f"\n--- t={t:.1f}s ---")
        for addr in sorted(added):
            print(f"  OPENED  0x{addr:08X} menu_id={snapshot[addr]}")
        for addr in sorted(removed):
            print(f"  CLOSED  0x{addr:08X} menu_id={last_state[addr]}")
        last_state = snapshot
    for addr, data in raw.items():
        if data is None:
            continue
        old = last_bytes.get(addr)
        if old is not None and old != data:
            t = time.monotonic() - start
            diffs = [
                (offset, old[offset], data[offset])
                for offset in range(NODE_SIZE)
                if old[offset] != data[offset]
            ]
            if diffs:
                menu_id = snapshot.get(addr, "?")
                diff_str = ", ".join(f"+0x{o:02X}: {ov}->{nv}" for o, ov, nv in diffs)
                print(f"  [t={t:.1f}s] 0x{addr:08X} menu_id={menu_id} byte diffs: {diff_str}")
        last_bytes[addr] = data
    time.sleep(0.1)
