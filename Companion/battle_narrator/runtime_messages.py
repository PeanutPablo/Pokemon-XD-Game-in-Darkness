"""Resolve a message ID to its text from the GAME'S OWN loaded string
tables, at runtime.

Every other message path in this project is file-based: FightCommonCatalog
reads fight_common.fsys, ShopMessageTable reads pocket_menu.fsys,
load_entity_names reads common.fsys. That works for messages living in the
handful of .fsys files this repo has extracted, but not for map-specific
text -- the Mt. Battle challenge prompt (31044) and its three choices
(31045-31047) are in a D2 file that was never extracted, so no file-based
lookup could ever see them.

This reads the same tables the engine itself searches, so it resolves any
message that is currently loaded, on any map, with no extraction step.

Transcribed from GSmsgGetGSchar (0x80107300 in vanilla GXXE01 rev 0):

    table_index = messageId >> 20
    entry_id    = messageId & 0xFFFFF
    head        = [[_pMw] + 0x04]        linked list, next at +0x08
    each table: +0x00 u16 table id (must equal table_index)
                +0x04 u16 entry count
                +0x10 array of {u32 entry id, u32 string offset}, sorted
                      ascending -- the engine BINARY SEARCHES it, so this
                      does too rather than scanning
    string      = table_base + offset, GSchar (UTF-16BE)

`_pMw` (0x804E8348) is the same address profile.py already calls
`manager_root` -- one struct, two fields: +0x04 is this string-table list,
+0x1C is the GSmsg task array the battle narrator reads.

Deliberately NOT implemented: the engine also filters tables by language
(`fn_8010B208` vs `pokecoloGetLanguage`) for ids below 60000. Five tables
are loaded live and all report table id 0, with differing language bytes,
so a match could in principle come from a non-active language table. In
practice the ids are disjoint across them and the first hit has been
correct in every case checked; if a wrong-language string ever turns up,
that filter is the thing to add.
"""
from .dialogue import (
    CLEAR_WINDOW, DIALOGUE_END, LETTER_FORMAT, NEWLINE, SET_SPEAKER, SPEAKER,
)
from .memory import MemoryError

P_MW_ADDRESS = 0x804E8348
TABLE_LIST_OFFSET = 0x04
TABLE_ID_OFFSET = 0x00
TABLE_COUNT_OFFSET = 0x04
TABLE_NEXT_OFFSET = 0x08
TABLE_ENTRIES_OFFSET = 0x10
ENTRY_STRIDE = 8

MAX_TABLES = 64
"""Bound on the table linked list, matching this project's convention of
bounding every unbounded-looking loop."""
MAX_ENTRIES = 20000
"""Sanity bound on a single table's entry count -- the largest seen live is
3688. A wild count means the pointer is not really a table."""
MAX_STRING_CHARS = 512

# Control opcodes that carry a single argument byte after them, so the
# decoder skips the argument instead of emitting it as text. LETTER_FORMAT
# is the one these choice strings actually use ("<FFFF>0x07 0x01 YES").
ARGUMENT_OPCODES = frozenset({LETTER_FORMAT, SET_SPEAKER})


class RuntimeMessageCatalog:
    """Read-only. Holds no cache: tables are swapped as maps load, and a
    stale entry would resolve to the wrong text on a different map."""

    def __init__(self, memory, profile):
        self.memory = memory
        self.profile = profile

    def _tables(self):
        work = self.memory.u32(P_MW_ADDRESS, "message work pointer")
        if not self._valid(work):
            return
        node = self.memory.u32(work + TABLE_LIST_OFFSET, "message table head")
        seen = set()
        for _ in range(MAX_TABLES):
            if not self._valid(node) or node in seen:
                return
            seen.add(node)
            yield node
            node = self.memory.u32(node + TABLE_NEXT_OFFSET, "next message table")

    def _valid(self, pointer):
        return (
            isinstance(pointer, int)
            and self.profile.mem1_start <= pointer < self.profile.mem1_end
        )

    def address_of(self, message_id):
        """Address of the message's GSchar bytes, or None if not loaded."""
        if not message_id:
            return None
        table_index = message_id >> 20
        entry_id = message_id & 0xFFFFF
        for base in self._tables():
            if self.memory.u16(base + TABLE_ID_OFFSET, "message table id") != table_index:
                continue
            count = self.memory.u16(
                base + TABLE_COUNT_OFFSET, "message table count")
            if not 0 < count <= MAX_ENTRIES:
                continue
            entries = base + TABLE_ENTRIES_OFFSET
            low, high = 0, count
            while low < high:
                middle = (low + high) >> 1
                entry = entries + middle * ENTRY_STRIDE
                found = self.memory.u32(entry, "message entry id")
                if found == entry_id:
                    offset = self.memory.u32(entry + 4, "message entry offset")
                    return base + offset
                if found < entry_id:
                    low = middle + 1
                else:
                    high = middle
        return None

    def text(self, message_id):
        """Plain spoken text for `message_id`, or None if it isn't loaded.

        Control codes are introduced by 0xFFFF; the byte after it is the
        opcode, and some opcodes carry one further argument byte. Anything
        else is a UTF-16BE character. This mirrors how dialogue.decode_page
        treats the same stream -- it is not reused directly because that
        function is built around a whole dialogue PAGE (speaker handling,
        terminator checks, page bounds) rather than a bare menu label."""
        address = self.address_of(message_id)
        if address is None:
            return None
        raw = self.memory.bytes(
            address, MAX_STRING_CHARS * 2, "message text", 1)
        out = []
        index = 0
        while index + 1 < len(raw):
            value = (raw[index] << 8) | raw[index + 1]
            if value == 0:
                break
            if value == 0xFFFF:
                if index + 2 >= len(raw):
                    break
                opcode = raw[index + 2]
                if opcode in (DIALOGUE_END, CLEAR_WINDOW):
                    break
                if opcode == NEWLINE:
                    out.append(" ")
                index += 3 if opcode not in ARGUMENT_OPCODES else 4
                continue
            # NOTE: control opcodes (SPEAKER, SET_SPEAKER, ...) are only
            # meaningful immediately after an 0xFFFF marker, handled above.
            # They must NOT be compared against a bare character value --
            # SPEAKER is 0x59, which is also the letter "Y", so doing that
            # silently ate the Y from "YES".
            out.append(chr(value))
            index += 2
        text = "".join(out).strip()
        # A page whose speaker was stripped can open with a bare ": " before
        # the first word -- the same artefact shop_messages.py documents and
        # swallows rather than speaking.
        if text.startswith(": "):
            text = text[2:].strip()
        return text or None
