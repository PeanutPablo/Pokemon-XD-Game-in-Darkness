from dataclasses import dataclass
from pathlib import Path

import _dialogue_extraction_tool as extraction


class LocalDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class Message:
    message_id: int
    tokens: tuple
    template: str
    opcodes: tuple
    raw: bytes


class FightCommonCatalog:
    def __init__(self, extraction_dir):
        path = Path(extraction_dir) / "raw" / "files" / "fight_common.fsys"
        if not path.is_file():
            raise LocalDataError(
                "Local fight_common data is missing. Run the existing dialogue "
                "extraction process against your own verified game image."
            )
        try:
            files = extraction.parse_fsys(path.read_bytes())
            entry = next(
                item for item in files if item["type"] == 5 and item["name"] == "fight"
            )
        except Exception as exc:
            raise LocalDataError(f"Could not load local fight_common data: {exc}") from exc
        data = entry["data"]
        decoded = extraction.decode_string_table(data)
        count = int.from_bytes(data[4:6], "big")
        self.messages = {}
        for index in range(count):
            offset = 0x10 + index * 8
            message_id = int.from_bytes(data[offset : offset + 4], "big") & 0xFFFFF
            string_offset = int.from_bytes(data[offset + 4 : offset + 8], "big")
            raw, opcodes = self._encoded(data, string_offset)
            tokens = tuple(decoded[message_id])
            self.messages[message_id] = Message(
                message_id,
                tokens,
                extraction.render_tokens(tokens),
                tuple(opcodes),
                raw,
            )

    @staticmethod
    def _encoded(data, offset):
        start = offset
        opcodes = []
        while True:
            if offset + 2 > len(data):
                raise LocalDataError("Unterminated fight_common string")
            value = int.from_bytes(data[offset : offset + 2], "big")
            offset += 2
            if value == 0:
                return data[start:offset], opcodes
            if value == 0xFFFF:
                if offset >= len(data):
                    raise LocalDataError("Truncated fight_common control")
                opcode = data[offset]
                opcodes.append(opcode)
                offset += 1 + extraction.extra_bytes_for_opcode(opcode)
                if offset > len(data):
                    raise LocalDataError("Truncated fight_common control parameters")

    def get(self, message_id):
        return self.messages.get(message_id)
