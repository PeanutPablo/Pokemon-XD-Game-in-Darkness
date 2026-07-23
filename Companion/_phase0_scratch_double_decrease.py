"""
Find 2-byte-aligned addresses that decreased by a plausible amount (1-999)
on TWO separate, consecutive hits. This is a much stronger filter than a
single before/after diff, since coincidentally decreasing twice in a row
by a small plausible amount is a rare coincidence for unrelated animation
noise. Read-only, local file comparison only.
"""
import sys
import os

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "_phase0_scratch_snapshots")
MEM1_START = 0x80000000

def load(label):
    with open(os.path.join(SNAPSHOT_DIR, f"{label}.bin"), "rb") as f:
        return f.read()

def u16_at(data, off):
    return (data[off] << 8) | data[off + 1]

def main():
    if len(sys.argv) != 4:
        print("Usage: python _phase0_scratch_double_decrease.py <snap1> <snap2> <snap3>")
        return 1
    s1 = load(sys.argv[1])
    s2 = load(sys.argv[2])
    s3 = load(sys.argv[3])
    n = min(len(s1), len(s2), len(s3))

    candidates = []
    for off in range(0, n - 1, 2):
        v1 = u16_at(s1, off)
        v2 = u16_at(s2, off)
        v3 = u16_at(s3, off)
        d1 = v2 - v1
        d2 = v3 - v2
        if -999 <= d1 <= -1 and -999 <= d2 <= -1:
            candidates.append((MEM1_START + off, v1, v2, v3, d1, d2))

    print(f"Double-decrease candidates: {len(candidates)}")
    for addr, v1, v2, v3, d1, d2 in candidates:
        print(f"  0x{addr:08X}: {v1} -> {v2} -> {v3}  (deltas {d1}, {d2})")
    return 0

if __name__ == "__main__":
    sys.exit(main())
