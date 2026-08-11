"""Read-only differential of menu 92's four target item records."""
import time
import dolphin_memory_engine as dme

def b(a,n): return dme.read_bytes(a,n)
def u16(a): return int.from_bytes(b(a,2),'big')
def u32(a): return int.from_bytes(b(a,4),'big')

dme.hook(); assert dme.is_hooked(), dme.get_status()
last=None; end=time.monotonic()+35
while time.monotonic()<end:
    n=u32(0x80445A78)
    while n and (u32(n+4)&0xffff)!=92: n=u32(n+0x10)
    if not n: time.sleep(.01); continue
    work=u32(n+0x24)
    items=tuple((u16(work+i*0x78+4),u16(work+i*0x78+6),b(work+i*0x78,0x78).hex()) for i in range(4))
    snap=(u16(n+0x9c),u16(n+0x9e),items)
    if snap!=last:
        print(f"selectors={snap[:2]} items={[(hex(x[0]),x[1]) for x in items]}",flush=True)
        last=snap
    time.sleep(.01)
dme.un_hook()
