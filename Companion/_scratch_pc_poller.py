"""Passive, read-only window-state logger for investigating the PC menus.

Runs continuously in the background, polling the window list and a set of
plausible per-window fields, and only prints when something changes. Does
not require the project owner to narrate anything back -- they just play
normally (open the PC, browse storage, open Summary, etc.) while this
captures ground truth for later analysis. No input is ever sent.
"""
import time

import dolphin_memory_engine as dme

from battle_narrator.memory import MemoryReader
from battle_narrator.menus import WindowListWalker
from battle_narrator.profile import XD_US_REV0

dme.hook()
if not dme.is_hooked():
    raise SystemExit("Dolphin is not readable.")
memory = MemoryReader(dme, XD_US_REV0)
walker = WindowListWalker(memory, XD_US_REV0)

FIELD_OFFSETS = {
    "0x9C": 0x9C,   # window_cursor_base_offset
    "0x9E": 0x9E,   # window_cursor_offset
    "0x9F": 0x9F,   # the "+0x9F" selection-index convention used elsewhere
    "0xA3": 0xA3,   # mirror of 0x9F seen elsewhere
    "0xB8": 0xB8,   # window_alloc_offset
}

last_state = {}
print("Polling started. Play normally; this will log every window-state change.", flush=True)
start = time.monotonic()
while True:
    try:
        nodes = walker.walk()
    except Exception as exc:
        nodes = []
    snapshot = {}
    for node in nodes:
        fields = {}
        for name, offset in FIELD_OFFSETS.items():
            try:
                fields[name] = memory.u8(node.address + offset, name)
            except Exception:
                fields[name] = None
        snapshot[node.address] = (node.menu_id, fields)
    if snapshot != last_state:
        t = time.monotonic() - start
        added = set(snapshot) - set(last_state)
        removed = set(last_state) - set(snapshot)
        changed = {
            addr for addr in (set(snapshot) & set(last_state))
            if snapshot[addr] != last_state[addr]
        }
        print(f"\n--- t={t:.1f}s ---")
        for addr in sorted(added):
            menu_id, fields = snapshot[addr]
            print(f"  OPENED  0x{addr:08X} menu_id={menu_id} (0x{menu_id:X}) fields={fields}")
        for addr in sorted(removed):
            menu_id, fields = last_state[addr]
            print(f"  CLOSED  0x{addr:08X} menu_id={menu_id} (0x{menu_id:X})")
        for addr in sorted(changed):
            menu_id, fields = snapshot[addr]
            old_fields = last_state[addr][1]
            diffs = {k: (old_fields[k], v) for k, v in fields.items() if old_fields.get(k) != v}
            print(f"  CHANGED 0x{addr:08X} menu_id={menu_id} (0x{menu_id:X}) diffs={diffs}")
        last_state = snapshot
    time.sleep(0.15)
