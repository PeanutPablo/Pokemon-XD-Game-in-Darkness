"""Read-only live probe for the generic overworld NPC and player structures."""
import struct

import dolphin_memory_engine as dme


def read(address, size):
    return dme.read_bytes(address, size)


def u32(address):
    return int.from_bytes(read(address, 4), "big")


def main():
    dme.hook()
    if not dme.is_hooked():
        raise RuntimeError(f"Dolphin unavailable: {dme.get_status()}")
    try:
        leader = u32(0x804479F0)
        model_id = (100, 101, 104, 105)[leader]
        node = u32(0x804EB008)
        model = 0
        seen = set()
        while node and node not in seen and len(seen) < 4096:
            seen.add(node)
            raw = read(node, 0x18)
            group_id, resource_id = struct.unpack_from(">II", raw, 8)
            if group_id == 0 and resource_id == model_id and raw[1] == 0:
                model = struct.unpack_from(">I", raw, 4)[0]
                break
            node = struct.unpack_from(">I", raw, 0x14)[0]
        if not model:
            raise RuntimeError(f"Leader model resource {model_id} not found")
        player = struct.unpack(">fff", read(model + 0x18, 12))
        rotation = struct.unpack(">fff", read(model + 0x24, 12))
        print(f"leader={leader} model_id={model_id} model=0x{model:08X} player={player} rotation={rotation}")

        floor_id = int.from_bytes(read(0x80814AB6, 2), "big")
        count_root = u32(0x804E8A30)
        floor_data = u32(0x804E8A34)
        count = u32(count_root)
        floor_record = 0
        for index in range(count):
            candidate = floor_data + index * 0x40
            if int.from_bytes(read(candidate + 2, 2), "big") == floor_id:
                floor_record = candidate
                break
        if not floor_record:
            raise RuntimeError(f"Floor record {floor_id} not found")
        char_slot = u32(floor_record + 0x0C)
        header = u32(char_slot)
        count_ptr = u32(header)
        npc_count = u32(count_ptr)
        npc_base = u32(header + 4)
        print(
            f"floor={floor_id} record=0x{floor_record:08X} "
            f"npc_count={npc_count} npc_base=0x{npc_base:08X}"
        )
        people_count_root = u32(0x804E88A0)
        people_table = u32(0x804E88A4)
        people_count = u32(people_count_root)
        print(f"people_count={people_count} people_table=0x{people_table:08X}")
        for index in range(npc_count):
            address = npc_base + index * 0x24
            raw = read(address, 0x24)
            visible = bool(raw[0] & 0x80)
            people_info_id = int.from_bytes(raw[6:8], "big")
            name_id = int.from_bytes(raw[8:10], "big")
            talk_distance = struct.unpack(">f", read(people_table + people_info_id * 0x34 + 0x24, 4))[0]
            talk_id = int.from_bytes(raw[0x14:0x18], "big")
            position = struct.unpack_from(">fff", raw, 0x18)
            print(
                f"npc={index} visible={visible} people_info={people_info_id} name={name_id} talk_distance={talk_distance} "
                f"talk=0x{talk_id:08X} position={position}"
            )
    finally:
        dme.un_hook()


if __name__ == "__main__":
    main()



