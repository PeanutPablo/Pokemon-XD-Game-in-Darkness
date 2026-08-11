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


class PartyActionMenuReader:
    def __init__(self, memory, profile, speech, logger,
                 menu_id=None, labels=None, index_offset=None):
        self.memory = memory
        self.profile = profile
        self.speech = speech
        self.logger = logger
        self.menu_id = profile.party_action_menu_id if menu_id is None else menu_id
        self.labels = profile.party_action_labels if labels is None else labels
        self.index_offset = (
            profile.party_action_index_offset if index_offset is None else index_offset)
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

    def poll_once(self):
        window = self._find_window()
        if window is None:
            if self.active:
                self.clear("action menu closed")
            return
        index = self.memory.u8(window + self.index_offset, "action menu index")
        if self.active and index == self.last_index:
            return
        label = self.labels[index % len(self.labels)]
        self.speech.emit(SpeechEventClass.ENTITY_NAV, f"{label}.", interrupt=True)
        self.logger.info("PARTY ACTION MENU menu_id=%d index=%d label=%r",
                         self.menu_id, index, label)
        self.active = True
        self.last_index = index
