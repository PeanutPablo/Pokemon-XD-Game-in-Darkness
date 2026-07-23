"""
Three-way narrowing: find 2-byte-aligned addresses where the value changed
between 'before' and 'after' (any direction, any magnitude), but then
stayed EXACTLY stable between 'after' and a subsequent 'idle' snapshot.
This eliminates continuously-fluctuating noise (animation/audio/timers)
and keeps only values that changed once, due to the specific action taken,
and then held steady -- exactly the profile a real HP/status field should
have. Read-only, local file comparison only.
"""
import sys
import os

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "_phase0_scratch_snapshots")
MEM1_START = 0x80000000

def load(label):
    with open(os.path.join(SNAPSHOT_DIR, f"{label}.bin"), "rb") as f:
        return f.read()

def main():
    if len(sys.argv) != 4:
        print("Usage: python _phase0_scratch_narrow.py <before> <after> <idle>")
        return 1
    before = load(sys.argv[1])
    after = load(sys.argv[2])
    idle = load(sys.argv[3])
    n = min(len(before), len(after), len(idle))

    stable_changes = []
    for off in range(0, n - 1, 2):
        b = (before[off] << 8) | before[off + 1]
        a = (after[off] << 8) | after[off + 1]
        i = (idle[off] << 8) | idle[off + 1]
        if b != a and a == i:
            stable_changes.append((MEM1_START + off, b, a))

    print(f"Stable single-transition candidates: {len(stable_changes)}")
    for addr, b, a in stable_changes[:300]:
        print(f"  0x{addr:08X}: {b} -> {a} (delta {a - b})")
    if len(stable_changes) > 300:
        print(f"  ... and {len(stable_changes) - 300} more")
    return 0

if __name__ == "__main__":
    sys.exit(main())
