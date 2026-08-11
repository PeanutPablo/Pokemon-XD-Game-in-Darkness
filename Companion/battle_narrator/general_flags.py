"""Read XD's general script flags from their authoritative common.rel layout."""
from pathlib import Path

import _dialogue_extraction_tool as extraction

REL_TO_RAM = 0x80B18DC0


def load_general_flag_layout(common_fsys_path):
    files = extraction.parse_fsys(Path(common_fsys_path).read_bytes())
    data = next(item["data"] for item in files
                if item["name"] in {"common.rel", "common_rel"})
    rel = extraction.RelFile(data)
    return {
        "records": rel.get_pointer(44) + REL_TO_RAM,
        "count": int.from_bytes(data[rel.get_pointer(45):rel.get_pointer(45) + 4], "big"),
        "metadata": rel.get_pointer(50) + REL_TO_RAM,
    }


class GeneralFlagReader:
    def __init__(self, memory, layout):
        self.memory = memory
        self.layout = layout

    def value(self, flag_id):
        if not 0 <= flag_id < self.layout["count"]:
            return None
        record = self.layout["records"] + flag_id * 6
        width_byte = self.memory.u8(record, f"flag {flag_id} width")
        packed = self.memory.u16(record + 2, f"flag {flag_id} location")
        width = width_byte & 0x3F
        word_index, shift = packed >> 5, packed & 0x1F
        pointer_slot = self.layout["metadata"] + ((width_byte >> 3) & 0x18) + 4
        base = self.memory.u32(pointer_slot, f"flag {flag_id} bank")
        low = self.memory.u32(base + word_index * 4, f"flag {flag_id} value")
        if width < 2:
            return (low >> shift) & 1
        high = self.memory.u32(base + word_index * 4 + 4, f"flag {flag_id} high value")
        combined = ((high << (32 - shift)) | (low >> shift)) if shift else low
        return combined & ((1 << width) - 1)