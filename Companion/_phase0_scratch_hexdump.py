"""
Read-only raw hex dump of a region for manual inspection. No writes.
Usage: edit ADDR/LENGTH below and run.
"""
import dolphin_memory_engine as dme

ADDR = 0x80CD6160
LENGTH = 0x200

dme.hook()
try:
    if not dme.is_hooked():
        print("ERROR: not hooked.")
    else:
        data = dme.read_bytes(ADDR, LENGTH)
        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            hex_str = " ".join(f"{b:02X}" for b in chunk)
            ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            print(f"0x{ADDR+i:08X}: {hex_str:<48} {ascii_str}")
finally:
    dme.un_hook()
