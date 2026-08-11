"""
Read-only, non-pausing live memory snapshot tool via dolphin_memory_engine.
Takes a single bulk read_bytes() snapshot of a given address range and
writes it to disk as raw bytes -- no pausing, no watchpoints, game keeps
running at full normal speed/audio throughout (same rationale as the
other _phase0_scratch_*_poll.py scripts).

Usage:
    python _phase0_scratch_live_snapshot.py <hex_addr> <hex_size> <out_name>

Read-only: only dme.hook()/read_bytes()/un_hook() are ever called.
"""
import sys
import os

import dolphin_memory_engine as dme

OUT_DIR = os.path.join(os.path.dirname(__file__), "logs")


def main():
    addr = int(sys.argv[1], 16)
    size = int(sys.argv[2], 16)
    out_name = sys.argv[3]

    dme.hook()
    if not dme.is_hooked():
        print(f"Failed to hook Dolphin. Status: {dme.get_status()}")
        return 1

    data = dme.read_bytes(addr, size)
    dme.un_hook()

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, out_name)
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"Wrote {len(data)} bytes from 0x{addr:08X} to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
