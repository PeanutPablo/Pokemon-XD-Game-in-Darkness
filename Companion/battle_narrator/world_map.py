"""Automatic narration for the Pokémon XD world-travel map."""
from pathlib import Path

import _dialogue_extraction_tool as extraction

from .memory import MemoryError
from .messages import LocalDataError
from .resolver import display_case
from .speech import SpeechEventClass


class WorldMapCatalog:
    def __init__(self, fsys_path):
        try:
            files = extraction.parse_fsys(Path(fsys_path).read_bytes())
            entry = next(x for x in files if x["type"] == 5 and x["name"] == "world_map")
            self.table = extraction.decode_string_table(entry["data"])
        except Exception as exc:
            raise LocalDataError(f"Could not load world-map text: {exc}") from exc

    def resolve(self, message_id):
        tokens = self.table.get(message_id)
        if tokens is None:
            raise LocalDataError(f"World-map message {message_id} is missing")
        text = extraction.render_tokens(tokens).replace("[Change Font]", "")
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        if not lines:
            raise LocalDataError(f"World-map message {message_id} is empty")
        return display_case(lines[0]), " ".join(lines[1:])


class WorldMapReader:
    POINTER = 0x804EA6F8
    CURSOR_COUNT = 0x804EA700
    CURSOR_INDEX = 0x80428080
    MESSAGE_DATA_POINTER = 0x804E87D4

    def __init__(self, memory, catalog, speech, logger):
        self.memory = memory
        self.catalog = catalog
        self.speech = speech
        self.logger = logger
        self.identity = None

    def clear(self, reason="world map closed"):
        self.identity = None

    def poll_once(self):
        world = self.memory.u32(self.POINTER, "world-map pointer")
        if not world:
            self.clear()
            return False
        state = self.memory.u32(world + 8, "world-map state pointer")
        if not state:
            self.clear()
            return False
        cursor = self.memory.u32(state + 0x30, "world-map cursor")
        count = self.memory.u16(self.CURSOR_COUNT, "world-map cursor count")
        if not 1 <= count <= 30 or cursor >= count:
            raise MemoryError(f"invalid world-map cursor {cursor}/{count}")
        data_index = self.memory.u16(
            self.CURSOR_INDEX + cursor * 2, "world-map destination index")
        message_data = self.memory.u32(
            self.MESSAGE_DATA_POINTER, "world-map message-data pointer")
        message_id = self.memory.u32(
            message_data + 4 + data_index * 4, "world-map information message")
        identity = (world, cursor, data_index, message_id)
        if identity == self.identity:
            return True
        name, description = self.catalog.resolve(message_id)
        position = f"Destination {cursor + 1} of {count}"
        text = f"{name}. {description} {position}."
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
        self.logger.info(
            "WORLD MAP cursor=%d/%d data=%d message=%d name=%r",
            cursor, count, data_index, message_id, name)
        self.identity = identity
        return True
