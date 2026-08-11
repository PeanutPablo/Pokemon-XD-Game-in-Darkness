"""Read-only probe of the current opponent trainer's authoritative title route."""
import dolphin_memory_engine as dme


def raw(address, size):
    return bytes(dme.read_bytes(address, size))


def u8(address):
    return raw(address, 1)[0]


def u16(address):
    return int.from_bytes(raw(address, 2), "big")


def u32(address):
    return int.from_bytes(raw(address, 4), "big")


def gschar(address, maximum=64):
    out = []
    for offset in range(0, maximum * 2, 2):
        value = u16(address + offset)
        if value == 0:
            return "".join(out)
        out.append(chr(value))
    return "".join(out)


def message_address(message_id):
    work = u32(0x804E8348)
    node = u32(work + 4)
    while 0x80000000 <= node < 0x81800000:
        count = u16(node + 4)
        low, high = 0, count
        while low < high:
            middle = (low + high) // 2
            entry = node + 0x10 + middle * 8
            found = u32(entry)
            if found == message_id:
                return node + u32(entry + 4)
            if found < message_id:
                low = middle + 1
            else:
                high = middle
        node = u32(node + 8)
    return 0


dme.hook()
try:
    trainer = 0x804A1730 + 0x6EF0 + 0x14 + 0x64
    trainer_id = u16(trainer)
    deck = u32(0x804EBB58)
    deck_size = u32(0x804EBB68)
    kind = u8(deck + trainer_id * 0x38 + 5) if trainer_id < deck_size else 0
    kinds = u32(0x804E8954)
    kind_count_ptr = u32(0x804E8950)
    kind_count = u32(kind_count_ptr)
    title_id = u32(kinds + kind * 0x0C + 4) if kind < kind_count else 0
    title_address = message_address(title_id)
    print({
        "trainer": hex(trainer), "trainer_id": trainer_id,
        "deck": hex(deck), "deck_size": deck_size, "kind": kind,
        "kinds": hex(kinds), "kind_count": kind_count,
        "title_id": title_id, "title_address": hex(title_address),
        "title": gschar(title_address) if title_address else "",
        "name": gschar(trainer + 4, 11),
    })
finally:
    dme.un_hook()
