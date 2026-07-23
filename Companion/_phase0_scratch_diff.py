"""
Read-only diff of two MEM1 snapshots taken by _phase0_scratch_snapshot.py.
Filters 2-byte-aligned, big-endian u16 values that changed by a small,
HP-plausible amount (1-999) in either direction. No memory access here at
all -- purely local file comparison.
"""
import sys
import os

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "_phase0_scratch_snapshots")
MEM1_START = 0x80000000

def main():
    if len(sys.argv) != 3:
        print("Usage: python _phase0_scratch_diff.py <before_label> <after_label>")
        return 1
    before_path = os.path.join(SNAPSHOT_DIR, f"{sys.argv[1]}.bin")
    after_path = os.path.join(SNAPSHOT_DIR, f"{sys.argv[2]}.bin")

    with open(before_path, "rb") as f:
        before = f.read()
    with open(after_path, "rb") as f:
        after = f.read()

    if len(before) != len(after):
        print(f"WARNING: snapshot sizes differ ({len(before)} vs {len(after)})")

    decreased = []
    increased = []
    n = min(len(before), len(after))
    for off in range(0, n - 1, 2):
        old_val = (before[off] << 8) | before[off + 1]
        new_val = (after[off] << 8) | after[off + 1]
        if old_val == new_val:
            continue
        delta = new_val - old_val
        if -999 <= delta <= -1:
            decreased.append((MEM1_START + off, old_val, new_val, delta))
        elif 1 <= delta <= 999:
            increased.append((MEM1_START + off, old_val, new_val, delta))

    print(f"Decreased candidates (old > new, delta -1..-999): {len(decreased)}")
    for addr, old, new, delta in decreased[:200]:
        print(f"  0x{addr:08X}: {old} -> {new} (delta {delta})")
    if len(decreased) > 200:
        print(f"  ... and {len(decreased) - 200} more")

    print(f"\nIncreased candidates (old < new, delta +1..+999): {len(increased)}")
    for addr, old, new, delta in increased[:200]:
        print(f"  0x{addr:08X}: {old} -> {new} (delta {delta})")
    if len(increased) > 200:
        print(f"  ... and {len(increased) - 200} more")

    return 0

if __name__ == "__main__":
    sys.exit(main())
