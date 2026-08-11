"""
Read-only raw hex dump of a region for manual inspection, from a saved
snapshot file rather than a live read. No writes, no live connection needed.
"""
import sys
import os

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "_phase0_scratch_snapshots")
MEM1_START = 0x80000000

def main():
    label = sys.argv[1]
    addr = int(sys.argv[2], 16)
    length = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x100
    with open(os.path.join(SNAPSHOT_DIR, f"{label}.bin"), "rb") as f:
        data = f.read()
    off = addr - MEM1_START
    chunk_all = data[off - length//2 : off + length//2]
    start_addr = addr - length//2
    for i in range(0, len(chunk_all), 16):
        chunk = chunk_all[i:i+16]
        hex_str = " ".join(f"{b:02X}" for b in chunk)
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"0x{start_addr+i:08X}: {hex_str:<48} {ascii_str}")

if __name__ == "__main__":
    main()
