"""
Read-only single live read of the candidate selection byte, right now,
from the actually-running Dolphin process (not a saved snapshot).
"""
import dolphin_memory_engine as dme

ADDR = 0x804FFCEF

dme.hook()
try:
    if not dme.is_hooked():
        print("ERROR: not hooked.")
    else:
        val = dme.read_byte(ADDR)
        print(f"Live value at 0x{ADDR:08X}: {val}")
finally:
    dme.un_hook()
