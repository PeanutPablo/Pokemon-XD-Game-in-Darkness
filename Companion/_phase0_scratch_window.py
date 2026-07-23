"""
Print all 2-byte-aligned u16 values in a window around a candidate address,
across three snapshots, to look for a nearby stable max-HP-like companion
value. Read-only, local file comparison only.
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
    center = int(sys.argv[1], 16)
    window = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x40
    s1 = load("paused_before")
    s2 = load("paused_after")
    s3 = load("paused_after2")

    start = center - window
    end = center + window
    for addr in range(start, end, 2):
        off = addr - MEM1_START
        v1 = u16_at(s1, off)
        v2 = u16_at(s2, off)
        v3 = u16_at(s3, off)
        marker = "  <-- candidate" if addr in (0x804454B4, 0x804454BC) else ""
        print(f"0x{addr:08X}: {v1:6d} -> {v2:6d} -> {v3:6d}{marker}")

if __name__ == "__main__":
    main()
