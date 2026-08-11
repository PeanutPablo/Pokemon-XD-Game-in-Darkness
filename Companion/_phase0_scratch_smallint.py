"""
Filter a snapshot diff for small-integer (0-N) changes -- the expected
signature of a menu cursor index. Read-only, local file comparison only.
"""
import sys
import os

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "_phase0_scratch_snapshots")
MEM1_START = 0x80000000

def load(label):
    with open(os.path.join(SNAPSHOT_DIR, f"{label}.bin"), "rb") as f:
        return f.read()

def main():
    before = load(sys.argv[1])
    after = load(sys.argv[2])
    max_val = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    n = min(len(before), len(after))
    count = 0
    for off in range(0, n - 1, 2):
        v1 = (before[off] << 8) | before[off + 1]
        v2 = (after[off] << 8) | after[off + 1]
        if v1 != v2 and v1 <= max_val and v2 <= max_val:
            print(f"0x{MEM1_START+off:08X}: {v1} -> {v2}")
            count += 1
    print(f"TOTAL: {count}")

if __name__ == "__main__":
    main()
