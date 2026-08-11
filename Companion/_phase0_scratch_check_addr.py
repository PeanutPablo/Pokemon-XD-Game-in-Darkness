"""
Check a specific address's value across an arbitrary list of snapshots.
Read-only, local file comparison only.
"""
import sys
import os

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "_phase0_scratch_snapshots")
MEM1_START = 0x80000000

def main():
    addr = int(sys.argv[1], 16)
    labels = sys.argv[2:]
    off = addr - MEM1_START
    for label in labels:
        with open(os.path.join(SNAPSHOT_DIR, f"{label}.bin"), "rb") as f:
            data = f.read()
        val = (data[off] << 8) | data[off + 1]
        print(f"{label}: {val}")

if __name__ == "__main__":
    main()
