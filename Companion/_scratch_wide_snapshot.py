"""Take a full-MEM1 snapshot for a before/after diff around one precise
user action. Read-only. Usage: python _scratch_wide_snapshot.py <out_path>
"""
import sys
from pathlib import Path

import dolphin_memory_engine as dme

out_path = Path(sys.argv[1])
dme.hook()
if not dme.is_hooked():
    raise SystemExit("Dolphin is not readable.")

start = 0x80000000
end = 0x81800000
chunk = 0x100000
data = bytearray()
addr = start
while addr < end:
    size = min(chunk, end - addr)
    data.extend(dme.read_bytes(addr, size))
    addr += size

out_path.write_bytes(bytes(data))
print(f"Wrote {len(data)} bytes to {out_path}")
