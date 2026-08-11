"""Resolve floor-character name indexes from the game's own common.rel."""
from pathlib import Path
import struct

import _dialogue_extraction_tool as extraction

from .messages import LocalDataError
from .resolver import display_case

# The placeholder glyph the game itself renders for an as-yet-unrevealed
# speaker name (message 6002, live-confirmed to decode to this single
# codepoint) -- not a real name, must not be spoken.
UNREVEALED_NAME_CODEPOINT = 0x2031


class ScriptedSpeakerNameTable:
    """Resolves the live "scripted speaker name" message ID (see
    profile.py's `scripted_speaker_message_id`) to rendered text via
    common.rel's general message string table (REL pointer 136 -- the
    same table move/ability names already resolve through), rather than
    the narrower PeopleIDs-keyed table `load_entity_names` builds.

    Found via static disassembly tracing `peopleTalkMsg` -> `charNameBiosGetNameID`
    -> `msgctrlSetValue(89, nameMsgID)`; the live message-ID field
    (`_Npc`, a `.sbss` global) was resolved by decoding `msgctrlSetValue`'s
    jump table. Live-verified: reading it during a real conversation
    resolved to "JOVI", matching the actual on-screen speaker. This
    covers scripted/cutscene dialogue that the pre-existing proximity-
    based `interaction_context.name` mechanism could not (see
    IMPLEMENTATION_ATTRIBUTION.md's "Scripted-NPC speaker-name
    investigation" entry, previously paused pending exactly this trace).
    """

    def __init__(self, common_fsys_path):
        path = Path(common_fsys_path)
        try:
            files = extraction.parse_fsys(path.read_bytes())
            data = next(
                item["data"] for item in files
                if item["name"] in {"common.rel", "common_rel"}
            )
            rel = extraction.RelFile(data)
            self.strings = extraction.decode_string_table(data[rel.get_pointer(136):])
        except Exception as exc:
            raise LocalDataError(f"Could not load scripted speaker name table: {exc}") from exc

    def resolve(self, message_id):
        tokens = self.strings.get(message_id)
        if not tokens or any(token[0] == "ctrl" for token in tokens):
            return None
        codepoints = [token[1] for token in tokens if token[0] == "char"]
        if codepoints == [UNREVEALED_NAME_CODEPOINT]:
            return None
        name = display_case(extraction.render_tokens(tokens).strip())
        return name or None


def load_entity_names(common_fsys_path):
    path = Path(common_fsys_path)
    try:
        files = extraction.parse_fsys(path.read_bytes())
        data = next(
            item for item in files
            if item["name"] in {"common.rel", "common_rel"}
        )["data"]
        rel = extraction.RelFile(data)
        people_base = rel.get_pointer(2)
        count = struct.unpack_from(">I", data, rel.get_pointer(3))[0]
        strings = extraction.decode_string_table(data[rel.get_pointer(136):])
        result = {}
        for index in range(count):
            record = people_base + index * 8
            message_id = struct.unpack_from(">I", data, record + 4)[0]
            tokens = strings.get(message_id)
            if not tokens or any(token[0] == "ctrl" for token in tokens):
                continue
            name = display_case(extraction.render_tokens(tokens).strip())
            if name:
                result[index] = name
        return result
    except Exception as exc:
        raise LocalDataError(f"Could not load entity names: {exc}") from exc
