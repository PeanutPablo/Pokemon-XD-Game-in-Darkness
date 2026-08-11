"""Narrates the engine's generic multiple-choice popup by reading the REAL
option text out of the game, rather than a typed-in label list.

The widget: a window node parented to the dialogue window, whose own
menu_id is whatever the engine happened to allocate (174 observed at Mt.
Battle) and therefore carries no meaning -- menus.py's existing cursor
handling already notes the same thing. What identifies it is its
allocation at `window_alloc_offset` (+0xB8), which holds a zero-terminated
array of u32 MESSAGE IDS, one per on-screen choice.

Live at Mt. Battle: prompt 31044 ("Welcome to MT. BATTLE. Would you care to
take the MT. BATTLE knockout battle challenge?"), choices 31045/31046/31047
-> "YES" / "INFO" / "EXIT". Those strings are resolved through
RuntimeMessageCatalog, so nothing here is hardcoded and the same reader
works for any other prompt using this widget, on any map.

Why this exists alongside menus.py's yes/no and shop handling: those paths
resolve their labels from typed-in tuples in profile.py, chosen because the
message text was not reachable at the time. This reader is deliberately
scoped to widgets menus.py leaves silent (see `ignored_menu_ids`) so it
cannot double-speak them. Folding those older paths into this mechanism
would be a strict improvement and is worth doing, but is a change to
already-working screens and is not attempted here.
"""
from .memory import MemoryError
from .speech import SpeechEventClass

MAX_CHOICES = 16
"""Bound on the option array. Three observed live; a run longer than this
means the allocation is not really a choice list."""


class ChoiceMenuReader:
    def __init__(self, memory, profile, catalog, speech, logger,
                 ignored_menu_ids=()):
        self.memory = memory
        self.profile = profile
        self.catalog = catalog
        self.speech = speech
        self.logger = logger
        self.ignored_menu_ids = frozenset(ignored_menu_ids)
        self.active = False
        self.last_key = None

    def clear(self, reason):
        if self.active:
            self.logger.debug("CHOICE MENU CLEAR reason=%s", reason)
        self.active = False
        self.last_key = None

    def _windows(self):
        p = self.profile
        pointer = self.memory.u32(
            p.window_manager + p.window_list_offset, "choice window-list head")
        seen = set()
        for _ in range(p.window_max_nodes):
            if pointer == 0:
                return
            if pointer in seen:
                raise MemoryError("choice window list contains a cycle")
            seen.add(pointer)
            yield pointer, self.memory.u32(
                pointer + p.window_menu_id_offset, "choice window menu id")
            pointer = self.memory.u32(
                pointer + p.window_next_offset, "choice next window")

    def _choices(self, window):
        """The window's option message ids paired with their text, or None
        if this window is not a choice widget.

        `menuPanelCtrlSelect` obtains window parameter 2, allocates exactly
        count*4 bytes, and copies that many message IDs. `windowGetParam`
        reads parameter N at window+0x68+N*4, so parameter 2 is the
        authoritative bound. Resolution remains a validation step: every
        counted row must still resolve through the game's loaded tables."""
        p = self.profile
        allocation = self.memory.u32(
            window + p.window_alloc_offset, "choice allocation")
        if not (p.mem1_start <= allocation < p.mem1_end):
            return None
        count = self.memory.u32(
            window + p.window_param_offset + 2 * 4,
            "choice option count",
        )
        if count < 2 or count > MAX_CHOICES:
            return None
        resolved = []
        for index in range(count):
            value = self.memory.u32(
                allocation + index * 4, "choice message id")
            text = self.catalog.text(value)
            if text is None:
                return None
            resolved.append((value, text))
        return resolved

    def _selected(self, window):
        p = self.profile
        page = self.memory.u16(
            window + p.window_cursor_base_offset, "choice cursor page")
        position = self.memory.u16(
            window + p.window_cursor_offset, "choice cursor position")
        return page + position

    def poll_once(self):
        target = None
        for window, menu_id in self._windows():
            if menu_id in self.ignored_menu_ids:
                continue
            resolved = self._choices(window)
            if resolved is not None:
                # Deepest matching window wins: nested prompts put the
                # active one last, the same ordering menus.py relies on.
                target = (window, menu_id, resolved)
        if target is None:
            if self.active:
                self.clear("choice menu closed")
            return
        window, menu_id, resolved = target
        index = self._selected(window)
        if index >= len(resolved):
            return
        ids = tuple(message_id for message_id, _ in resolved)
        key = (menu_id, ids, index)
        if self.active and key == self.last_key:
            return
        label = resolved[index][1]
        self.speech.emit(
            SpeechEventClass.ENTITY_NAV,
            f"{label}. {index + 1} of {len(resolved)}.",
            deduplicate=False, interrupt=True)
        self.logger.info(
            "CHOICE MENU menu_id=%d index=%d of %d label=%r ids=%r",
            menu_id, index, len(resolved), label, ids)
        self.active = True
        self.last_key = key
