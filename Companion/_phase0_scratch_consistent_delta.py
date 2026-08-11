"""
Find small-integer addresses that changed by the SAME delta on two
consecutive, identical inputs (e.g. Right, Right) -- the expected
signature of a cursor index incrementing by a fixed step per press.
Read-only, local file comparison only.
"""
import sys
import os

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "_phase0_scratch_snapshots")
MEM1_START = 0x80000000

def load(label):
    with open(os.path.join(SNAPSHOT_DIR, f"{label}.bin"), "rb") as f:
        return f.read()

def main():
    s1 = load(sys.argv[1])
    s2 = load(sys.argv[2])
    s3 = load(sys.argv[3])
    max_val = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    n = min(len(s1), len(s2), len(s3))
    count = 0
    for off in range(0, n - 1, 2):
        v1 = (s1[off] << 8) | s1[off + 1]
        v2 = (s2[off] << 8) | s2[off + 1]
        v3 = (s3[off] << 8) | s3[off + 1]
        d1 = v2 - v1
        d2 = v3 - v2
        if d1 != 0 and d1 == d2 and v1 <= max_val and v2 <= max_val and v3 <= max_val:
            print(f"0x{MEM1_START+off:08X}: {v1} -> {v2} -> {v3} (step {d1})")
            count += 1
    print(f"TOTAL: {count}")

if __name__ == "__main__":
    main()
