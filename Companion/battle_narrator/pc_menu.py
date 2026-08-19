"""Automatic narration for the two fixed-choice PC menus."""

from .party_action_menu import PartyActionMenuReader
from .memory import MemoryError, valid_range
from .speech import SpeechEventClass


class PCMenuReader:
    """Read the live-confirmed PC home and Pokemon Storage action menus.

    The box itself is deliberately excluded: it is a spatial grid and its
    cursor has not yet been live-confirmed, so treating it as a list would
    announce the wrong Pokemon.
    """

    MAIN_MENU_ID = 122
    ACTION_MENU_ID = 123
    MAIN_LABELS = ("Pokemon Storage", "Item Storage", "Exit")
    """The PC home menu, three entries.

    **Corrected 2026-08-18**, project owner: *"the pc says 'save' instead
    of 'exit'"*. `_poll_fixed` carried its own inline four-entry tuple for
    this same menu -- `("Pokemon Storage", "Item Storage", "Save", "Exit")`
    -- with a "Save" entry the real menu does not have. Every index from 2
    on was therefore shifted: landing on Exit announced "Save", and index 3
    was unreachable.

    This is the second time this exact shape of bug has hit this menu; see
    ACTION_LABELS below, where `_poll_fixed` was announcing the Item-PC's
    labels for the Pokemon-PC window. Both had the same cause -- a second
    copy of the labels living at the call site, free to disagree with the
    one named here -- so `_poll_fixed` now reads these constants and there
    is only one copy left to be right or wrong."""
    # Live 2026-08-10: index 0 opened the grid and deposited TODD; the old
    # unused tuple had Deposit/Withdraw reversed while _poll_fixed used
    # Item-PC labels for this Pokemon-PC window.
    ACTION_LABELS = ("Deposit Pokemon", "Withdraw Pokemon", "Move Pokemon", "Exit")

    STORAGE_OBJECT_POINTER = 0x804EA870
    STORAGE_CURSOR_POINTER_OFFSET = 0x37F0
    STORAGE_CURSOR_INDEX_OFFSET = 0x0C
    STORAGE_BOX_OFFSET = 0x03E0
    STORAGE_HELD_POKEMON_OFFSET = 0x20
    """On the cursor object: the Pokemon currently picked up, if any."""

    # Box contents come from SAVE DATA, not from the menu object.
    #
    # They used to be read as `_decode_slot(obj + 0x3718, slot)` -- but
    # that method's second argument is only an error label, it does no
    # addressing at all, so every one of the thirty cells in a box decoded
    # the SAME address and announced the same Pokemon. A blind player
    # moving across a box heard one name repeated for every cell, which
    # is worse than silence: it is confidently wrong.
    #
    # The fix reads the game's own store instead of a menu-local display
    # copy whose stride was never confirmed. `PCBOX::getPokemon`
    # (0x80156AB0) is unambiguous:
    #
    #     pcbox = savedataGetStatus(savedata, 3)   -> savedata + 0xAD0
    #     if not 0 <= box  < 8:  return NULL
    #     if not 0 <= slot < 30: return NULL
    #     return pcbox + box*0x170C + 0x14 + slot*0xC4
    #
    # and 0x170C == 0x14 + 30*0xC4 exactly, so the header/stride/capacity
    # triple is self-consistent. The same jump table that yields 0xAD0 for
    # section 3 yields 0x140 for section 2, which is already
    # `profile.hero_offset` -- an independent check that the table was
    # read correctly.
    PCBOX_SAVEDATA_OFFSET = 0xAD0
    PCBOX_BOX_STRIDE = 0x170C
    PCBOX_BOX_HEADER = 0x14
    PCBOX_SLOT_STRIDE = 0xC4
    PCBOX_BOX_COUNT = 8
    PCBOX_SLOTS_PER_BOX = 30
    PCBOX_BOX_COLUMNS = 6
    PCBOX_BOX_NAME_MAX = 9
    """The 0x14-byte header is a GSchar box name: nine characters plus a
    two-byte terminator."""

    def __init__(self, memory, profile, speech, logger, party_source=None, world_map_reader=None):
        self.memory = memory
        self.profile = profile
        self.speech = speech
        self.logger = logger
        self.party_source = party_source
        self.world_map_reader = world_map_reader
        self.last_storage_identity = None
        self.last_action_identity = None
        self.last_fixed_identity = None
        self.readers = (
            PartyActionMenuReader(
                memory, profile, speech, logger,
                menu_id=self.MAIN_MENU_ID, labels=self.MAIN_LABELS),
            PartyActionMenuReader(
                memory, profile, speech, logger,
                menu_id=self.ACTION_MENU_ID, labels=self.ACTION_LABELS),
        )

    def poll_once(self):
        if self.world_map_reader is not None and self.world_map_reader.poll_once():
            return
        if self._poll_action():
            return
        if self._poll_fixed():
            return
        self._poll_storage()

    def _find_window(self, menu_id):
        p = self.profile
        pointer = self.memory.u32(p.window_manager + p.window_list_offset, "PC window-list head")
        seen = set()
        for _ in range(p.window_max_nodes):
            if not pointer:
                return None
            if pointer in seen:
                raise MemoryError("PC window list contains a cycle")
            seen.add(pointer)
            if self.memory.u32(pointer + p.window_menu_id_offset, "PC window menu ID") == menu_id:
                return pointer
            pointer = self.memory.u32(pointer + p.window_next_offset, "PC next window")
        raise MemoryError("PC window list exceeds verified bound")

    def _poll_fixed(self):
        definitions = (
            (self.ACTION_MENU_ID, self.ACTION_LABELS),
            (self.MAIN_MENU_ID, self.MAIN_LABELS),
        )
        for menu_id, labels in definitions:
            window = self._find_window(menu_id)
            if window is None:
                continue
            index = self.memory.u32(window + 0x9C, "PC fixed-menu index")
            if index >= len(labels):
                raise MemoryError(f"invalid PC menu {menu_id} index {index}")
            identity = (window, menu_id, index)
            if identity != self.last_fixed_identity:
                label = labels[index]
                self.speech.emit(SpeechEventClass.ENTITY_NAV, f"{label}.", interrupt=True)
                self.logger.info("PC FIXED menu=%d index=%d label=%r", menu_id, index, label)
                self.last_fixed_identity = identity
            return True
        self.last_fixed_identity = None
        return False

    def _box_address(self, box, slot):
        savedata = self.memory.pointer(
            self.profile.savedata_pointer_address,
            self.PCBOX_SAVEDATA_OFFSET
            + self.PCBOX_BOX_COUNT * self.PCBOX_BOX_STRIDE,
            "PC box savedata", 4)
        if not 0 <= box < self.PCBOX_BOX_COUNT:
            raise MemoryError(f"PC box {box} out of range")
        if not 0 <= slot < self.PCBOX_SLOTS_PER_BOX:
            raise MemoryError(f"PC box slot {slot} out of range")
        return (savedata + self.PCBOX_SAVEDATA_OFFSET
                + box * self.PCBOX_BOX_STRIDE + self.PCBOX_BOX_HEADER
                + slot * self.PCBOX_SLOT_STRIDE)

    def _box_pokemon(self, box, slot):
        # `party_source` defaults to None and only the production factory
        # supplies one, so an unguarded call raises AttributeError -- which
        # is NOT a MemoryError and so escapes the lifecycle's per-reader
        # handler, taking the whole narrator down. Found by probing the
        # real readers against a live game with no save loaded.
        if self.party_source is None:
            return None
        try:
            return self.party_source._decode_slot(
                self._box_address(box, slot), slot)
        except MemoryError:
            # An empty cell is the overwhelmingly common case and
            # `_decode_slot` signals "not a Pokemon" by returning None,
            # but it raises on a half-written record. Either way the cell
            # is not speakable as a Pokemon; treat both as empty rather
            # than dropping the whole announcement.
            return None

    def _box_name(self, box):
        try:
            savedata = self.memory.pointer(
                self.profile.savedata_pointer_address,
                self.PCBOX_SAVEDATA_OFFSET
                + self.PCBOX_BOX_COUNT * self.PCBOX_BOX_STRIDE,
                "PC box savedata", 4)
            name = self.memory.gschar(
                savedata + self.PCBOX_SAVEDATA_OFFSET
                + box * self.PCBOX_BOX_STRIDE,
                self.PCBOX_BOX_NAME_MAX, "PC box name", 2)
        except MemoryError:
            return ""
        return name.strip()

    def _box_label(self, box):
        name = self._box_name(box)
        default = f"Box {box + 1}"
        if name.casefold() == default.casefold():
            return default
        return f"{default}, {name}" if name else default

    def _selected_pokemon(self, obj, position):
        """The Pokemon under the grid cursor.

        Indices 4-9 are the party column and 10-39 the thirty box cells --
        the split confirmed live on 2026-08-02. Both are read from their
        real home (the hero's party, the save's PC box); neither is read
        from a menu-local display array."""
        if 4 <= position <= 9:
            slots = {slot.index: slot for slot in self.party_source.slots()}
            return slots.get(position - 4)
        if 10 <= position <= 39:
            box = self.memory.u32(obj + self.STORAGE_BOX_OFFSET, "PC storage box")
            return self._box_pokemon(box, position - 10)
        return None

    def _poll_action(self):
        window = self._find_window(89)
        if window is None:
            self.last_action_identity = None
            return False
        obj = self.memory.u32(self.STORAGE_OBJECT_POINTER, "PC storage object pointer")
        cursor = self.memory.u32(obj + self.STORAGE_CURSOR_POINTER_OFFSET, "PC storage cursor pointer")
        if not valid_range(cursor, self.STORAGE_HELD_POKEMON_OFFSET + 0xC4):
            # Menu 89 is reused by ordinary Yes/No prompts. During the live
            # PC confirmation its would-be cursor was scalar 0x37F0, not a
            # storage cursor object; leave that window to ChoiceMenuReader.
            self.last_action_identity = None
            return False
        position = self.memory.u32(cursor + self.STORAGE_CURSOR_INDEX_OFFSET, "PC storage cursor index")
        selected = self._selected_pokemon(obj, position)
        held = self.party_source._decode_slot(
            cursor + self.STORAGE_HELD_POKEMON_OFFSET, -1)
        action_index = self.memory.u32(window + 0x88, "PC action menu index")
        first = "Shift" if held and selected else "Place" if held else "Move"
        transfer = "Deposit" if 4 <= position <= 9 else "Withdraw"
        labels = (first, "Summary", transfer, "Mark", "Release", "Cancel")
        if action_index >= len(labels):
            raise MemoryError(f"invalid PC action index {action_index}")
        identity = (window, action_index, first, transfer)
        if identity != self.last_action_identity:
            label = labels[action_index]
            self.speech.emit(SpeechEventClass.ENTITY_NAV, f"{label}.", interrupt=True)
            self.logger.info("PC ACTION index=%d label=%r", action_index, label)
            self.last_action_identity = identity
        return True

    def _poll_storage(self):
        obj = self.memory.u32(self.STORAGE_OBJECT_POINTER, "PC storage object pointer")
        if not obj:
            self.last_storage_identity = None
            return
        cursor = self.memory.u32(obj + self.STORAGE_CURSOR_POINTER_OFFSET, "PC storage cursor pointer")
        if not valid_range(cursor, self.STORAGE_HELD_POKEMON_OFFSET + 0xC4):
            self.last_storage_identity = None
            return
        index = self.memory.u32(cursor + self.STORAGE_CURSOR_INDEX_OFFSET, "PC storage cursor index")
        box = self.memory.u32(obj + self.STORAGE_BOX_OFFSET, "PC storage box")
        held = self.party_source._decode_slot(
            cursor + self.STORAGE_HELD_POKEMON_OFFSET, -1)
        held_name = held.raw_nickname if held else None
        previous_held = (self.last_storage_identity[3] if self.last_storage_identity else None)
        identity = (obj, index, box, held_name)
        if identity == self.last_storage_identity:
            return
        if index > 39 or box >= self.PCBOX_BOX_COUNT:
            raise MemoryError(f"invalid PC storage selection index={index} box={box}")
        if index == 0:
            text = f"{self._box_label(box)}."
        elif index == 1:
            text = "Previous box."
        elif index == 2:
            text = "Next box."
        elif index == 3:
            text = "Back."
        elif 4 <= index <= 9:
            party_index = index - 4
            slots = {slot.index: slot for slot in self.party_source.slots()}
            pokemon = slots.get(party_index)
            text = (f"Party slot {party_index + 1}, {pokemon.raw_nickname}, level {pokemon.level}." if pokemon else f"Party slot {party_index + 1}, empty.")
        else:
            slot = index - 10
            row, column = divmod(slot, self.PCBOX_BOX_COLUMNS)
            pokemon = self._box_pokemon(box, slot)
            prefix = (f"{self._box_label(box)}, row {row + 1}, "
                      f"column {column + 1}, slot {slot + 1}")
            # Lead with identity so rapid grid navigation says the useful
            # differentiator before the repeated spatial context.
            text = (f"{pokemon.raw_nickname}, {prefix}, level {pokemon.level}."
                    if pokemon else f"{prefix}, empty.")
        if held_name:
            if held_name != previous_held:
                text = f"Holding {held_name}. {text}"
            else:
                text = f"{text[:-1]}, holding {held_name}."
        elif previous_held:
            text = f"No longer holding {previous_held}. {text}"
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
        self.logger.info("PC STORAGE index=%d box=%d text=%r", index, box, text)
        self.last_storage_identity = identity

    def clear(self, reason="PC menu state cleared"):
        if self.world_map_reader is not None:
            self.world_map_reader.clear(reason)
        self.last_storage_identity = None
        self.last_action_identity = None
        self.last_fixed_identity = None
        for reader in self.readers:
            reader.clear(reason)
