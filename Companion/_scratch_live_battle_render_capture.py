"""Read-only capture of live GSmsg task pages and substitution buffers."""
import time
import dolphin_memory_engine as dme

TASKS = 0x80834BA0
STRIDE = 0x6C
EV_GLOBALS = (0x804EB1F0, 0x804EB1F4, 0x804EB1F8, 0x804EB200,
              0x804EB204, 0x804EB208, 0x804EB20C, 0x804EB27C)

def u32(a):
    return int.from_bytes(dme.read_bytes(a, 4), "big")

def safe_bytes(a, n):
    try:
        return dme.read_bytes(a, n)
    except Exception as exc:
        return f"<{exc}>".encode()

dme.hook()
assert dme.is_hooked(), dme.get_status()
last = None
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    rows = []
    for i in range(2):
        t = TASKS + i * STRIDE
        raw = safe_bytes(t, STRIDE)
        state = raw[0]
        packed = int.from_bytes(raw[0x1C:0x20], "big")
        start = int.from_bytes(raw[0x28:0x2C], "big")
        end = int.from_bytes(raw[0x30:0x34], "big")
        page = b""
        if 0x80000000 <= start <= end <= 0x81800000 and end-start <= 0x1000:
            page = safe_bytes(start, end-start)
        rows.append((i, state, packed, start, end, raw.hex(), page.hex()))
    globals_ = tuple(u32(a) for a in EV_GLOBALS)
    snap = (tuple(rows), globals_)
    if snap != last:
        print(f"{time.time():.3f} rows={rows} globals={[hex(x) for x in globals_]}", flush=True)
        last = snap
    time.sleep(0.01)
dme.un_hook()

