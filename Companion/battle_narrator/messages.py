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
    context: str = "battle"


class FsysMessageCatalog:
    """Messages owned by one named table inside one FSYS archive."""

    def __init__(self, path, entry_name, context):
        path = Path(path)
        if not path.is_file():
            raise LocalDataError(
                f"Local {path.name} data is missing. Run the existing dialogue "
                "extraction process against your own verified game image."
            )
        try:
            files = extraction.parse_fsys(path.read_bytes())
            entry = next(
                item for item in files
                if item["type"] == 5 and item["name"] == entry_name
            )
        except Exception as exc:
            raise LocalDataError(
                f"Could not load local {path.name} data: {exc}") from exc
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
                context,
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


class FightCommonCatalog(FsysMessageCatalog):
    def __init__(self, extraction_dir):
        path = Path(extraction_dir) / "raw" / "files" / "fight_common.fsys"
        super().__init__(path, "fight", "battle")


class PocketMenuCatalog(FsysMessageCatalog):
    """Item-use and other pocket-menu-owned message tasks."""

    def __init__(self, pocket_menu_fsys_path):
        super().__init__(pocket_menu_fsys_path, "pocket_menu", "pocket_menu")


class RoomMessageCatalog(FsysMessageCatalog):
    """Map-owned field dialogue from one extracted room archive."""

    def __init__(self, room_fsys_path, room_name):
        super().__init__(room_fsys_path, room_name, "field")


class RoutedMessageCatalog:
    """Route lookups through catalogs with optional live ownership gates."""

    def __init__(self, routes):
        self.routes = tuple(routes)

    def get(self, message_id):
        for catalog, active in self.routes:
            if active is None or active():
                message = catalog.get(message_id)
                if message is not None:
                    return message
        return None
