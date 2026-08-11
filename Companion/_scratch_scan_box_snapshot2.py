"""Passive, offline scan of the already-captured MEM1 snapshot for
isolated plausible box-Pokemon structs at the confirmed 0xC4 stride,
WITHOUT requiring several consecutive non-empty slots (a real box is
mostly empty -- the first scan's "4 consecutive valid slots" requirement
was too strict for sparse data). Confirmed struct format (same as party,
per Pokemon-XD-Code SaveFileTables.swift + XGSaveManager.swift, box slot
size 0xC4, 30 slots/box, 8 boxes): species@0x0, level@0x11, nickname@0x4E.
"""
import struct
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = path.read_bytes()
base_addr = 0x80000000
STRIDE = 0xC4


def looks_like_nickname(chunk):
    end = chunk.find(b"\x00")
    if end <= 0:
        return False
    text = chunk[:end]
    if not all(32 <= b < 127 for b in text):
        return False
    return chunk[end:] == b"\x00" * (len(chunk) - end)


hits = []
limit = len(data) - STRIDE
pos = 0
while pos < limit:
    species = struct.unpack_from(">H", data, pos)[0]
    if 1 <= species <= 440:
        level = data[pos + 0x11]
        if 1 <= level <= 100:
            nick_chunk = data[pos + 0x4E: pos + 0x4E + 11]
            if looks_like_nickname(nick_chunk):
                hits.append(pos)
    pos += 4  # scan every 4 bytes, not assuming alignment yet

print(f"Total loose hits (any alignment): {len(hits)}")

# Now group by (address mod STRIDE) to find which alignment has clusters.
from collections import defaultdict
by_mod = defaultdict(list)
for h in hits:
    by_mod[h % STRIDE].append(h)

ranked = sorted(by_mod.items(), key=lambda kv: -len(kv[1]))
for mod, positions in ranked[:10]:
    addrs = [base_addr + p for p in positions]
    print(f"mod=0x{mod:X}: {len(positions)} hit(s) -> addrses (first 10): {[hex(a) for a in addrs[:10]]}")
