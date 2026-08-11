"""Read-only live differential probe for standard battle target selection."""
import time
import dolphin_memory_engine as dme

def raw(a, n): return dme.read_bytes(a, n)
def u32(a): return int.from_bytes(raw(a, 4), "big")

dme.hook()
assert dme.is_hooked(), dme.get_status()
last = None
until = time.monotonic() + 8
while time.monotonic() < until:
    node = u32(0x80445A68 + 0x10)
    target_node = 0
    for _ in range(64):
        if not node: break
        if u32(node + 4) & 0xffff == 92:
            target_node = node; break
        node = u32(node + 0x10)
    snap = (
        u32(0x804EA648), u32(0x804EA64C), u32(0x804EA650),
        u32(0x804E8588), raw(0x804139B8, 0xF0),
        target_node, raw(target_node, 0xBC) if target_node else b"",
        raw(u32(target_node + 0x24), 0x300) if target_node else b"",
    )
    if snap != last:
        print(
            f"globals={[hex(x) for x in snap[:4]]} node={hex(target_node)} "
            f"data={snap[4].hex()} node_raw={snap[6].hex()} alloc={snap[7].hex()}", flush=True
        )
        last = snap
    time.sleep(0.01)
dme.un_hook()


