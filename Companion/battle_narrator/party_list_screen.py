"""Automatic narration for the party list screen (the overworld screen
showing all 6 party slots, opened from the main menu).

Same automatic, cursor-driven design as `party_summary_screen.py` and
`party_action_menu.py`: reacts to a live-confirmed selection-index byte
(the same `+0x9F` offset those two screens use) rather than a hotkey.
Live-confirmed on the screen's head window (`menu_id` 76): the index
changed from 6 back to 0 when the project owner moved the selection.

Interpretation of index 6 as "Cancel" is an inference (there are 6 real
party slots, indices 0-5, so 6 is the one position beyond them), not
independently confirmed by OCR the way the other two screens' labels
were -- flagged honestly rather than asserted as fact.
"""
from .memory import MemoryError
from .health import round_percent, speech_name
from .speech import SpeechEventClass


class PartyListScreenReader:
    def __init__(self, memory, profile, party_source, speech, logger):
        self.memory = memory
        self.profile = profile
        self.party_source = party_source
        self.speech = speech
        self.logger = logger
        self.active = False
        self.last_index = None

    def clear(self, reason):
        if self.active:
            self.logger.debug("PARTY LIST SCREEN CLEAR reason=%s", reason)
        self.active = False
        self.last_index = None

    def _find_window(self):
        p = self.profile
        pointer = self.memory.u32(
            p.window_manager + p.window_list_offset, "party list window-list head")
        seen = set()
        for _ in range(p.window_max_nodes):
            if pointer == 0:
                return None
            if pointer in seen:
                raise MemoryError("party list window list contains a cycle")
            seen.add(pointer)
            menu_id = self.memory.u32(
                pointer + p.window_menu_id_offset, "party list window menu ID")
            if menu_id == p.party_list_menu_id:
                return pointer
            pointer = self.memory.u32(
                pointer + p.window_next_offset, "party list next window")
        raise MemoryError("party list window list exceeds verified bound")

    @staticmethod
    def _slot_text(slot):
        _, percentage = round_percent(slot.hp, slot.max_hp)
        percent = "zero percent" if percentage == 0 else f"{percentage} percent"
        return (
            f"{speech_name(slot.raw_nickname)}, level {slot.level}, "
            f"{slot.hp} of {slot.max_hp} HP, {percent}."
        )

    def poll_once(self):
        window = self._find_window()
        if window is None:
            if self.active:
                self.clear("party list screen closed")
            return
        index = self.memory.u8(
            window + self.profile.party_list_index_offset, "party list index")
        if self.active and index == self.last_index:
            return
        if index >= self.profile.hero_party_slots:
            text = "Cancel."
        else:
            try:
                slots = self.party_source.slots()
            except MemoryError as exc:
                self.logger.debug("PARTY LIST SCREEN read failed: %s", exc)
                return
            by_index = {slot.index: slot for slot in slots}
            slot = by_index.get(index)
            text = self._slot_text(slot) if slot is not None else "Empty slot."
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
        self.logger.info("PARTY LIST SCREEN index=%d text=%r", index, text)
        self.active = True
        self.last_index = index
