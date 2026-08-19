"""Automatic narration for small, fixed-choice popups opened from the party
list -- the "Do what with <Pokemon>?" menu (Summary/Switch/Item/Cancel) and
the "Do what with an item?" menu (Give/Take/Cancel) it leads into.

Same design convention as `party_summary_screen.py`: reacts to real cursor
movement (a live-confirmed selection-index byte at the same `+0x9F` offset
the summary screen and party list use) rather than being triggered by a
hotkey. Both of these popups' indices wrap around (live-confirmed by the
project owner for both), so the index is taken modulo the label count
defensively rather than assumed to stay in range.

This one class is reused for both popups by passing a different
`menu_id`/`labels` pair at construction time -- they're the same widget
type with different content, not two different mechanisms.
"""
from .memory import MemoryError
from .speech import SpeechEventClass


POKEMON_DATA_NUMBER = 0x804EA634
POKEMON_DATA = 0x804EA638
POKEMON_DATA_STRIDE = 0x124
POKEMON_NAME_OFFSET = 0x18
POKEMON_ABILITY_OFFSET = 0x32


def stone_selection_labels(memory, profile, item_names, species_names,
                           ability_data):
    """Build menu 175 labels from the loaded build's item/species tables."""
    count_pointer = memory.pointer(
        POKEMON_DATA_NUMBER, 4, "species count pointer", 4)
    count = memory.u32(count_pointer, "species count")
    base = memory.pointer(
        POKEMON_DATA, count * POKEMON_DATA_STRIDE, "species data", 4)
    labels = []
    for item_id, species_id in zip(
            profile.stone_selection_item_ids,
            profile.stone_selection_species_ids):
        if not 0 < species_id < count:
            raise ValueError(f"invalid evolution species ID {species_id}")
        item = item_names.resolve_name(item_id)
        record = base + species_id * POKEMON_DATA_STRIDE
        species = species_names.resolve(memory.u32(
            record + POKEMON_NAME_OFFSET, "evolution species name ID"))
        ability_ids = []
        for offset in (POKEMON_ABILITY_OFFSET, POKEMON_ABILITY_OFFSET + 1):
            ability_id = memory.u8(record + offset, "evolution ability ID")
            if ability_id and ability_id not in ability_ids:
                ability_ids.append(ability_id)
        abilities = [
            ability_data.resolve(memory, profile, ability_id)[0]
            for ability_id in ability_ids
        ]
        if not item or not species or not abilities:
            raise ValueError(
                f"incomplete evolution choice {item_id}/{species_id}")
        ability_text = " and ".join(abilities)
        noun = "ability" if len(abilities) == 1 else "abilities"
        labels.append(f"{item}: {species}, {noun} {ability_text}")
    return tuple(labels)


class PartyActionMenuReader:
    def __init__(self, memory, profile, speech, logger,
                 menu_id=None, labels=None, index_offset=None,
                 entry_map=None, entry_stride=2):
        self.memory = memory
        self.profile = profile
        self.speech = speech
        self.logger = logger
        self.menu_id = profile.party_action_menu_id if menu_id is None else menu_id
        self.labels = profile.party_action_labels if labels is None else labels
        self.index_offset = (
            profile.party_action_index_offset if index_offset is None else index_offset)
        # Address of the game's own row -> entry table, for menus that hide
        # entries the player has not unlocked. Without it the cursor
        # position is used directly, which is right only for menus whose
        # rows never change. See `profile.pause_menu_entry_map`.
        self.entry_map = entry_map
        self.entry_stride = entry_stride
        self.active = False
        self.last_index = None

    def clear(self, reason):
        if self.active:
            self.logger.debug("PARTY ACTION MENU CLEAR reason=%s", reason)
        self.active = False
        self.last_index = None

    def _find_window(self):
        p = self.profile
        pointer = self.memory.u32(
            p.window_manager + p.window_list_offset, "action menu window-list head")
        seen = set()
        for _ in range(p.window_max_nodes):
            if pointer == 0:
                return None
            if pointer in seen:
                raise MemoryError("action menu window list contains a cycle")
            seen.add(pointer)
            menu_id = self.memory.u32(
                pointer + p.window_menu_id_offset, "action menu window menu ID")
            if menu_id == self.menu_id:
                return pointer
            pointer = self.memory.u32(
                pointer + p.window_next_offset, "action menu next window")
        raise MemoryError("action menu window list exceeds verified bound")

    def _entry_for_row(self, row):
        """Which menu entry the cursor's row actually is, or None.

        Menus whose rows are fixed answer with the row itself. A menu that
        hides unavailable entries -- the overworld pause menu drops P*DA
        until the player owns one -- keeps its own row-to-entry table, and
        reading that is the only way to know that row 1 of four means
        Items rather than P*DA."""
        if self.entry_map is None:
            return row % len(self.labels)
        entry = self.memory.u16(
            self.entry_map + row * self.entry_stride,
            f"menu {self.menu_id} row {row} entry")
        if entry >= len(self.labels):
            return None
        return entry

    def poll_once(self):
        window = self._find_window()
        if window is None:
            if self.active:
                self.clear("action menu closed")
            return
        index = self.memory.u8(window + self.index_offset, "action menu index")
        if self.active and index == self.last_index:
            return
        entry = self._entry_for_row(index)
        if entry is None:
            # The row names an entry outside the known set. Saying nothing
            # beats naming the wrong option -- the player is about to press
            # A on whatever this actually is.
            self.logger.warning(
                "PARTY ACTION MENU menu_id=%d row=%d has no known entry; "
                "staying silent", self.menu_id, index)
            self.active = True
            self.last_index = index
            return
        label = self.labels[entry]
        self.speech.emit(SpeechEventClass.ENTITY_NAV, f"{label}.", interrupt=True)
        self.logger.info("PARTY ACTION MENU menu_id=%d index=%d label=%r",
                         self.menu_id, index, label)
        self.active = True
        self.last_index = index
