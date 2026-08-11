"""Read-only probe for the live floor door and treasure arrays."""
import struct

import dolphin_memory_engine as dme


def u32(address):
    return struct.unpack(">I", dme.read_bytes(address, 4))[0]


def dump(label, count_address, list_address, record_size=0x80):
    count = u32(count_address)
    pointer = u32(list_address)
    print(f"{label}: count={count} pointer=0x{pointer:08X}")
    if count > 256 or not (0x80000000 <= pointer < 0x81800000):
        return
    for index in range(count):
        base = pointer + index * record_size
        data = dme.read_bytes(base, record_size)
        words = struct.unpack(">" + "I" * (record_size // 4), data)
        floats = []
        for offset, word in enumerate(words):
            value = struct.unpack(">f", struct.pack(">I", word))[0]
            if abs(value) < 100000 and value == value and abs(value) > 0.001:
                floats.append(f"+{offset * 4:02X}={value:.3f}")
        print(
            f"  {index}: "
            + " ".join(f"{word:08X}" for word in words)
            + " floats="
            + ",".join(floats)
        )


if not dme.hook():
    raise SystemExit("Dolphin not available")

dump("treasures", 0x804E88F0, 0x804E88F4)
dump("doors", 0x804E8908, 0x804E890C)
