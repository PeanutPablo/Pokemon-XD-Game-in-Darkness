"""Automatic narration for the overworld Pokemon summary screen.

Reacts to real page navigation (the page-index byte confirmed live via the
project owner's own OCR of all 4 pages -- see profile.py's
`party_summary_page_offset` comment) rather than being triggered by a
hotkey, matching this project's standing convention that navigable in-game
menus should be narrated by tracking actual state, not read out on demand.

Reads whichever Pokemon is actually being displayed via the live
`Pokemon*` the game itself tracks (`profile.party_summary_pokemon_pointer`,
`_menuStatus+0x0C` -- written on open and on every L/R party-switch,
found by static trace once the party grew past one member and exposed
the earlier "always slot 0" shortcut). This is read directly via
`PartyMemorySource.slot_for_pointer()` rather than mapped back to a
party index, so it also works correctly for non-party summaries (PC box,
opponent) that reuse the same field and struct layout, not just the
overworld party.

Pages 0 (Info), 1 (Status), and 2 (Moves) are narrated with real content,
all independently confirmed against the project owner's own OCR of the
live screen (nickname, nature, OT, EXP, stats, ability name/description,
and move names/PP all matched exactly -- see resolver.py's
`LocalAbilityData` for the ability lookup chain). Page 1 (Status) also
speaks the Heart Gauge for a Shadow Pokemon (party.py's
`heart_gauge_percent`, silently omitted for a non-Shadow Pokemon) --
direction (0 Dark Point == fully open/ready to purify) confirmed directly
by the project owner against their own live Teddiursa, 2026-07-30. Page 3
(Ribbons) is
announced by name only -- the Ribbon bitfield's live value didn't
plausibly decode as "no ribbons yet" for a freshly-caught Pokemon, so
it's left unimplemented rather than guessed at. Held-item name resolution
(only the raw ID and a "no item" case are handled), "ID No.", Pokemon
type, and the "obtained from" flavor text are also not yet implemented --
each needs its own lookup table or message-system investigation not done
yet.
"""
from .health import round_percent, speech_name
from .memory import MemoryError
from .speech import SpeechEventClass

PAGE_NAMES = ("Info", "Status", "Moves", "Ribbons")


class PartySummaryScreenReader:
    def __init__(self, memory, profile, party_source, speech, logger):
        self.memory = memory
        self.profile = profile
        self.party_source = party_source
        self.speech = speech
        self.logger = logger
        self.active = False
        self.last_page = None

    def clear(self, reason):
        if self.active and self.logger:
            self.logger.debug("PARTY SUMMARY SCREEN CLEAR reason=%s", reason)
        self.active = False
        self.last_page = None

    def _find_windows(self):
        p = self.profile
        pointer = self.memory.u32(
            p.window_manager + p.window_list_offset, "summary window-list head")
        seen = set()
        found = {}
        for _ in range(p.window_max_nodes):
            if pointer == 0:
                return found
            if pointer in seen:
                raise MemoryError("summary window list contains a cycle")
            seen.add(pointer)
            menu_id = self.memory.u32(
                pointer + p.window_menu_id_offset, "summary window menu ID")
            if menu_id in (p.party_summary_menu_id, p.move_learning_menu_id):
                found[menu_id] = pointer
            pointer = self.memory.u32(
                pointer + p.window_next_offset, "summary next window")
        raise MemoryError("summary window list exceeds verified bound")

    def _logical_cursor(self, window):
        p = self.profile
        base = self.memory.u16(
            window + p.window_cursor_base_offset, "summary cursor base")
        offset = self.memory.u16(
            window + p.window_cursor_offset, "summary cursor offset")
        return base + offset

    @staticmethod
    def _info_text(slot):
        item_text = "No item held." if slot.item_id == 0 else f"Holding item {slot.item_id}."
        return (
            f"Info. {speech_name(slot.raw_nickname)}, level {slot.level}. "
            f"{slot.nature} nature. "
            f"Original Trainer: {speech_name(slot.ot_name)}. "
            f"Experience: {slot.exp} points. "
            f"{item_text}"
        )

    @staticmethod
    def _status_text(slot):
        _, percentage = round_percent(slot.hp, slot.max_hp)
        percent = "zero percent" if percentage == 0 else f"{percentage} percent"
        stats = slot.stats
        text = (
            f"Status. {speech_name(slot.raw_nickname)}, level {slot.level}, "
            f"{slot.hp} of {slot.max_hp} HP, {percent}. "
            f"Attack {stats.attack}, Defense {stats.defense}, "
            f"Special Attack {stats.special_attack}, "
            f"Special Defense {stats.special_defense}, Speed {stats.speed}."
        )
        if slot.ability_name:
            text += f" Ability: {speech_name(slot.ability_name)}."
            if slot.ability_description:
                text += f" {slot.ability_description}"
        if slot.heart_gauge_percent is not None:
            if slot.heart_gauge_percent >= 100:
                text += " Heart Gauge: fully open, ready to purify."
            else:
                text += f" Heart Gauge: {slot.heart_gauge_percent} percent open."
        return text

    @staticmethod
    def _move_text(move):
        pp = (
            f"{move.pp}/{move.maximum_pp} P P"
            if move.maximum_pp else f"{move.pp} P P"
        )
        details = []
        if move.type_name:
            details.append(f"{move.type_name}-type")
        if move.description:
            details.append(move.description)
        suffix = f". {'. '.join(details)}" if details else ""
        return f"{speech_name(move.name)}, {pp}{suffix}"

    @classmethod
    def _moves_text(cls, slot):
        if not slot.moves:
            return "Moves. No moves known."
        entries = [cls._move_text(move) for move in slot.moves]
        return f"Moves. {'; '.join(entries)}."

    def _text_for_page(self, page, slot):
        if page == 0:
            return self._info_text(slot)
        if page == 1:
            return self._status_text(slot)
        if page == 2:
            return self._moves_text(slot)
        if 0 <= page < len(PAGE_NAMES):
            return f"{PAGE_NAMES[page]} page."
        return None

    def poll_once(self):
        windows = self._find_windows()
        window = windows.get(self.profile.party_summary_menu_id)
        if window is None:
            if self.active:
                self.clear("summary screen closed")
            return
        page = self.memory.u8(
            window + self.profile.party_summary_page_offset,
            "summary page index",
        )
        learning_window = windows.get(self.profile.move_learning_menu_id)
        # Window 94's +0x9F is the PAGE (and overlaps the generic cursor's
        # low byte), so reading it as a row cursor made page 2 permanently
        # select move 3. Window 98 owns the actual move-row cursor.
        learning_cursor = (
            self._logical_cursor(learning_window)
            if learning_window is not None else None
        )
        identity = (page, learning_cursor)
        if self.active and identity == self.last_page:
            return
        try:
            pointer = self.memory.u32(
                self.profile.party_summary_pokemon_pointer,
                "summary displayed Pokemon pointer")
            slot = self.party_source.slot_for_pointer(pointer)
        except MemoryError as exc:
            self.logger.debug("PARTY SUMMARY SCREEN read failed: %s", exc)
            return
        if slot is None:
            return
        previous_page = (
            self.last_page[0] if self.active and self.last_page is not None
            else None
        )
        if page == 2 and previous_page != 2:
            # Entering Moves must announce the complete move set. Window 98
            # is already present with a cursor, so treating its mere presence
            # as a focused-only overlay skipped three of four moves live.
            text = self._moves_text(slot)
        elif learning_cursor is not None:
            if 0 <= learning_cursor < len(slot.moves):
                # This is the same four-move list as the ordinary Moves page.
                # Reuse its presentation instead of inventing a separate
                # "Forget ...?" sentence that does not belong to the game.
                text = self._move_text(slot.moves[learning_cursor]) + "."
            else:
                text = None
        else:
            text = self._text_for_page(page, slot)
        if text is not None:
            self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
            self.logger.info(
                "PARTY SUMMARY SCREEN page=%d learning_cursor=%r text=%r",
                page, learning_cursor, text,
            )
        self.active = True
        self.last_page = identity

