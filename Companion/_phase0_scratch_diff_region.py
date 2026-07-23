"""
Like _phase0_scratch_diff.py, but restricted to a specific address range,
and prints ALL changes in that range (not just filtered ones) so they can
be inspected directly. Read-only, local file comparison only.
"""
import sys
import os

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "_phase0_scratch_snapshots")
MEM1_START = 0x80000000

def load(label):
    with open(os.path.join(SNAPSHOT_DIR, f"{label}.bin"), "rb") as f:
        return f.read()

def main():
    if len(sys.argv) != 5:
        print("Usage: python _phase0_scratch_diff_region.py <before> <after> <start_hex> <end_hex>")
        return 1
    before = load(sys.argv[1])
    after = load(sys.argv[2])
    start = int(sys.argv[3], 16)
    end = int(sys.argv[4], 16)

    start_off = start - MEM1_START
    end_off = end - MEM1_START

    changes = []
    for off in range(start_off, end_off - 1, 2):
        b = (before[off] << 8) | before[off + 1]
        a = (after[off] << 8) | after[off + 1]
        if b != a:
            changes.append((MEM1_START + off, b, a))

    print(f"Changes in range 0x{start:08X}-0x{end:08X}: {len(changes)}")
    for addr, b, a in changes:
        print(f"  0x{addr:08X}: {b} -> {a} (delta {a - b})")
    return 0

if __name__ == "__main__":
    sys.exit(main())
