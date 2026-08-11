"""
Check the exact byte(s) at and around a candidate address across snapshots,
to determine the real field width (is it a u8 at the low byte, or a genuine
u16?). Read-only, local file comparison only.
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
        byte_hi = data[off]
        byte_lo = data[off + 1]
        print(f"{label}: byte[{addr:08X}]={byte_hi:02X}  byte[{addr+1:08X}]={byte_lo:02X}")

if __name__ == "__main__":
    main()
