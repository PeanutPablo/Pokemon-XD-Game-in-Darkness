"""
Read-only snapshot of the confirmed title-menu symbol addresses from
xd-decomp's config/GXXE01/symbols.txt (symbol-only, no decompiled source
for these -- addresses are Confirmed, the meaning of the values is not
yet Confirmed by us). Purpose: get a first read to see if the game is
currently sitting at the title screen (values look plausible/nonzero)
or somewhere else (e.g. still on a health-and-safety screen, all zero).

No writes performed.
"""
import dolphin_memory_engine as dme

CANDIDATES = {
    "_menuTitleStatus (.sbss:0x804EAA38)": 0x804EAA38,
    "_menuTitleStartStatus (.sbss:0x804EAA30)": 0x804EAA30,
    "_menuTitleOptionWork (.bss:0x8043D2F8)": 0x8043D2F8,
    "_menuTitleWork (.bss:0x8043D2A8)": 0x8043D2A8,
    "_menuTitleDiskCoverOpen (.sbss:0x804EAA34)": 0x804EAA34,
    "TitleMsgID (.sbss:0x804EA7E0)": 0x804EA7E0,
    "_menuTopSelectCursor (.sbss:0x804EA798)": 0x804EA798,
}

dme.hook()
try:
    if not dme.is_hooked():
        print("ERROR: not hooked.")
    else:
        for label, addr in CANDIDATES.items():
            raw = dme.read_bytes(addr, 4)
            as_u32 = int.from_bytes(raw, byteorder="big")
            print(f"{label}: bytes={raw.hex()}  as_u32_BE=0x{as_u32:08X} ({as_u32})")
finally:
    dme.un_hook()
    print("un_hook() called.")
