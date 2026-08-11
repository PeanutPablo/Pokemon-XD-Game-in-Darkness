"""Automatic read-only narration for the Pokemon XD P-star-DA."""
from pathlib import Path

import _dialogue_extraction_tool as extraction

from .memory import MemoryError, require_range
from .menus import WindowListWalker
from .messages import LocalDataError
from .resolver import display_case
from .speech import SpeechEventClass
from .purify_chamber import (
    POKEMON_DATA, POKEMON_DATA_NUMBER, POKEMON_NAME_OFFSET,
    POKEMON_DATA_STRIDE,
)


PDA_HOME_MENU_IDS = frozenset((0xA8, 0x6C, 0x6B))
PDA_HOME_CURSOR_ADDRESS = 0x8042990C
# _menuPdaSetMenuItem assigns these pda_menu.fsys message pairs to the
# corresponding runtime selection IDs.  They are routing identifiers only;
# all spoken wording remains in the user's extracted game catalog.
PDA_HOME_MESSAGE_IDS = {
    0: (15184, 15187),
    1: (15182, 15188),
    2: (15183, 15189),
    3: (15359, 15363),
    4: (15185, 15190),
}

# menuPdaSearcher / esabadata.  The screen draws the three records directly;
# its words come from pda_menu.fsys and its values from GSflagGet.
PDA_PARENT_MENU_ID = 0x77
SPOT_MONITOR_MENU_ID = 0x6D
SPOT_DATA_COUNT_ADDRESS = 0x804E8988
SPOT_DATA_ADDRESS = 0x804E898C
SPOT_RECORD_SIZE = 0x1C
SPOT_FOOD_FLAG_OFFSET = 0x00
SPOT_SPECIES_FLAG_OFFSET = 0x0C
SPOT_TITLE_MESSAGE_ID = 15359
SPOT_LOCATION_MESSAGE_IDS = (15383, 15384, 15385)
WORLD_MAP_DATA_ADDRESS = 0x804E87DC
WORLD_MAP_RECORD_SIZE = 0x24
WORLD_MAP_FLAG_OFFSET = 4
# @1992 in menuPdaSearcher.s; indices into worldmapXD_data, not text/data.
SPOT_WORLD_MAP_INDICES = (15, 16, 17)

# menuPdaDPMonitorList owns this sorted display array while menu 0x74 is open.
SHADOW_MONITOR_MENU_ID = 0x74
SHADOW_LIST_OBJECT_ADDRESS = 0x804EA850
SHADOW_LIST_RECORDS_OFFSET = 0x50
SHADOW_LIST_RECORD_SIZE = 8
SHADOW_LIST_SPECIES_OFFSET = 4
SHADOW_CURSOR_ADDRESS = 0x80445C10  # cursorBios slot 12
SHADOW_TITLE_MESSAGE_ID = 15184

MAIL_PARENT_MENU_ID = 0x6F
MAIL_CONTENT_MENU_ID = 0x77
MAIL_ID_ADDRESS = 0x804EA8E4
MAIL_OPEN_FLAG_ADDRESS = 0x804EA8E8
FIRST_MAIL_MESSAGE_ID = 53001
MAIL_COUNT = 19


def _clean(text):
    return text.replace("[Change Font]", "").strip()


class PdaCatalog:
    """Static P-star-DA strings extracted from the user's own game image."""

    def __init__(self, pda_fsys_path):
        path = Path(pda_fsys_path)
        try:
            files = extraction.parse_fsys(path.read_bytes())
            tables = []
            for item in files:
                try:
                    table = extraction.decode_string_table(item["data"])
                except Exception:
                    continue
                if FIRST_MAIL_MESSAGE_ID in table:
                    tables.append(table)
            if len(tables) != 1:
                raise ValueError(f"expected one PDA text table, found {len(tables)}")
            self.table = tables[0]
            required = range(FIRST_MAIL_MESSAGE_ID, FIRST_MAIL_MESSAGE_ID + MAIL_COUNT * 3)
            missing = [message_id for message_id in required if message_id not in self.table]
            if missing:
                raise ValueError(f"PDA text table is missing {len(missing)} mail strings")
        except Exception as exc:
            raise LocalDataError(f"Could not load P-star-DA messages: {exc}") from exc

    def text(self, message_id):
        tokens = self.table.get(message_id)
        if tokens is None:
            raise LocalDataError(f"P-star-DA message {message_id} is missing")
        return _clean(extraction.render_tokens(tokens))

    def mail(self, mail_id, player_name):
        if not 1 <= mail_id <= MAIL_COUNT:
            raise MemoryError(f"invalid P-star-DA mail ID {mail_id}")
        first = FIRST_MAIL_MESSAGE_ID + (mail_id - 1) * 3
        values = tuple(self.text(first + offset) for offset in range(3))
        replacement = display_case(player_name) if player_name else "Player"
        values = tuple(value.replace("[Player Field 43]", replacement) for value in values)
        return display_case(values[0]), values[1], values[2]

    def home_option(self, cursor):
        message_ids = PDA_HOME_MESSAGE_IDS.get(cursor)
        if message_ids is None:
            raise MemoryError(f"invalid P-star-DA home cursor {cursor}")
        return tuple(self.text(message_id) for message_id in message_ids)


class PdaReader:
    """Announce source-derived PDA screens automatically, without hotkeys."""

    def __init__(self, memory, profile, catalog, speech, logger,
                 flag_reader=None, runtime_catalog=None):
        self.memory = memory
        self.profile = profile
        self.catalog = catalog
        self.speech = speech
        self.logger = logger
        self.flag_reader = flag_reader
        self.runtime_catalog = runtime_catalog
        self.walker = WindowListWalker(memory, profile)
        self.identity = None

    def clear(self, reason="P-star-DA state cleared"):
        if self.identity is not None:
            self.logger.debug("PDA CLEAR reason=%s", reason)
        self.identity = None

    def poll_once(self):
        menu_ids = {node.menu_id for node in self.walker.walk()}
        if self._read_spot_monitor(menu_ids):
            return
        if self._read_shadow_monitor(menu_ids):
            return
        detail_open = {MAIL_PARENT_MENU_ID, MAIL_CONTENT_MENU_ID}.issubset(menu_ids)
        open_flag = self.memory.u8(MAIL_OPEN_FLAG_ADDRESS, "PDA mail-open flag")
        if not detail_open or not open_flag:
            if PDA_HOME_MENU_IDS.issubset(menu_ids):
                cursor = self.memory.u32(
                    PDA_HOME_CURSOR_ADDRESS, "PDA home cursor"
                )
                option = self.catalog.home_option(cursor)
                identity = ("home", cursor)
                if identity == self.identity:
                    return
                label, description = option
                self.speech.emit(
                    SpeechEventClass.MENU_FOCUS,
                    f"{label}. {description}",
                    deduplicate=False, interrupt=True,
                )
                self.logger.info("PDA HOME cursor=%d label=%r", cursor, label)
                self.identity = identity
                return
            self.identity = None
            return
        mail_id = self.memory.u32(MAIL_ID_ADDRESS, "PDA current mail ID")
        identity = ("mail", mail_id)
        if identity == self.identity:
            return
        savedata = self.memory.u32(
            self.profile.savedata_pointer_address,
            "PDA saved-data pointer",
        )
        require_range(
            savedata,
            self.profile.hero_offset + self.profile.hero_name_offset + 22,
            "PDA saved data",
            self.profile,
            4,
        )
        player_name = self.memory.gschar(
            savedata + self.profile.hero_offset + self.profile.hero_name_offset,
            11, "PDA player name", 2,
        )
        sender, subject, body = self.catalog.mail(mail_id, player_name)
        separator = " " if subject.endswith((".", "!", "?")) else ". "
        text = f"Mailbox. From {sender}. Subject: {subject}{separator}{body}"
        self.speech.emit(
            SpeechEventClass.MENU_FOCUS, text,
            deduplicate=False, interrupt=True,
        )
        self.logger.info("PDA MAIL id=%d sender=%r subject=%r", mail_id, sender, subject)
        self.identity = identity

    def _species_name(self, species_id):
        count = self.memory.u32(POKEMON_DATA_NUMBER, "species count")
        if not 0 < species_id < count:
            raise MemoryError(f"invalid species ID {species_id}")
        base = self.memory.pointer(
            POKEMON_DATA, count * POKEMON_DATA_STRIDE, "species data")
        message_id = self.memory.u32(
            base + species_id * POKEMON_DATA_STRIDE + POKEMON_NAME_OFFSET,
            "species name message ID")
        if self.runtime_catalog is None:
            raise MemoryError("runtime message catalog unavailable")
        text = self.runtime_catalog.text(message_id)
        if not text:
            raise MemoryError(f"species name message {message_id} unavailable")
        return display_case(text)

    def _read_spot_monitor(self, menu_ids):
        if not {PDA_PARENT_MENU_ID, SPOT_MONITOR_MENU_ID}.issubset(menu_ids):
            return False
        if self.flag_reader is None:
            raise MemoryError("general flag reader unavailable")
        count = self.memory.u32(SPOT_DATA_COUNT_ADDRESS, "Spot Monitor record count")
        if count < len(SPOT_LOCATION_MESSAGE_IDS):
            raise MemoryError(f"invalid Spot Monitor record count {count}")
        records = self.memory.pointer(
            SPOT_DATA_ADDRESS, count * SPOT_RECORD_SIZE, "Spot Monitor records")
        values = []
        world_map = self.memory.pointer(
            WORLD_MAP_DATA_ADDRESS,
            (max(SPOT_WORLD_MAP_INDICES) + 1) * WORLD_MAP_RECORD_SIZE,
            "world-map data")
        for index, (location_id, world_index) in enumerate(zip(
                SPOT_LOCATION_MESSAGE_IDS, SPOT_WORLD_MAP_INDICES)):
            visible_flag = self.memory.u32(
                world_map + world_index * WORLD_MAP_RECORD_SIZE
                + WORLD_MAP_FLAG_OFFSET,
                "Poke Spot world-map flag")
            if not self.flag_reader.value(visible_flag):
                continue
            record = records + index * SPOT_RECORD_SIZE
            food_flag = self.memory.u32(
                record + SPOT_FOOD_FLAG_OFFSET, "Poke Spot food flag")
            species_flag = self.memory.u32(
                record + SPOT_SPECIES_FLAG_OFFSET, "Poke Spot species flag")
            food = self.flag_reader.value(food_flag)
            species = self.flag_reader.value(species_flag)
            if food is None or species is None:
                raise MemoryError("Poke Spot flag is outside the general-flag table")
            location = self.catalog.text(location_id)
            parts = [location]
            if species:
                parts.append(self._species_name(species))
            parts.append(str(food))
            values.append(tuple(parts))
        identity = ("spot", tuple(values))
        if identity != self.identity:
            title = self.catalog.text(SPOT_TITLE_MESSAGE_ID)
            text = f"{title}. " + ". ".join(": ".join(parts) for parts in values)
            self.speech.emit(SpeechEventClass.MENU_FOCUS, text,
                             deduplicate=False, interrupt=True)
            self.logger.info("PDA SPOT values=%r", values)
            self.identity = identity
        return True

    def _read_shadow_monitor(self, menu_ids):
        if not {PDA_PARENT_MENU_ID, SHADOW_MONITOR_MENU_ID}.issubset(menu_ids):
            return False
        obj = self.memory.pointer(
            SHADOW_LIST_OBJECT_ADDRESS, 0x60, "Shadow Monitor list object")
        total = self.memory.u32(obj, "Shadow Monitor list count")
        if total > 256:
            raise MemoryError(f"invalid Shadow Monitor list count {total}")
        title = self.catalog.text(SHADOW_TITLE_MESSAGE_ID)
        if not total:
            identity = ("shadow", 0)
            text = title
        else:
            records = self.memory.pointer(
                obj + SHADOW_LIST_RECORDS_OFFSET,
                total * SHADOW_LIST_RECORD_SIZE,
                "Shadow Monitor sorted records")
            raw = self.memory.bytes(
                SHADOW_CURSOR_ADDRESS, 4, "Shadow Monitor cursor", 2)
            row = int.from_bytes(raw[:2], "big", signed=True)
            scroll = int.from_bytes(raw[2:], "big", signed=True)
            selected = row + scroll
            if not 0 <= selected < total:
                raise MemoryError(f"invalid Shadow Monitor selection {selected}/{total}")
            species = self.memory.u16(
                records + selected * SHADOW_LIST_RECORD_SIZE
                + SHADOW_LIST_SPECIES_OFFSET,
                "Shadow Monitor selected species")
            name = self._species_name(species)
            identity = ("shadow", selected, species)
            text = f"{title}. {name}"
        if identity != self.identity:
            self.speech.emit(SpeechEventClass.MENU_FOCUS, text,
                             deduplicate=False, interrupt=True)
            self.logger.info("PDA SHADOW identity=%r", identity)
            self.identity = identity
        return True
