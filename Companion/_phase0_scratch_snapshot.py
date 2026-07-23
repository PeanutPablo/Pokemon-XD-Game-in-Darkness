"""
Read-only MEM1 snapshot tool for controlled unknown-value memory scanning
(Phase 0B/0C methodology). Reads the entire GameCube MEM1 range
(0x80000000-0x817FFFFF, 24MB) in one call and saves it to a local file
for later diffing. No writes performed, ever.

Usage: python _phase0_scratch_snapshot.py <output_label>
Saves to _phase0_scratch_snapshots/<output_label>.bin
"""
import sys
import os
import dolphin_memory_engine as dme

MEM1_START = 0x80000000
MEM1_SIZE = 0x01800000  # 24 MiB

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "_phase0_scratch_snapshots")

def main():
    if len(sys.argv) != 2:
        print("Usage: python _phase0_scratch_snapshot.py <label>")
        return 1
    label = sys.argv[1]
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    out_path = os.path.join(SNAPSHOT_DIR, f"{label}.bin")

    dme.hook()
    try:
        if not dme.is_hooked():
            print("ERROR: not hooked.")
            return 1
        print(f"Reading {MEM1_SIZE} bytes from 0x{MEM1_START:08X}...")
        data = dme.read_bytes(MEM1_START, MEM1_SIZE)
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"Saved snapshot '{label}' ({len(data)} bytes) to {out_path}")
        return 0
    finally:
        dme.un_hook()

if __name__ == "__main__":
    sys.exit(main())
