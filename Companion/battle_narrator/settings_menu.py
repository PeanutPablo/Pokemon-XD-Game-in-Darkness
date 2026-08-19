"""The spoken settings menu: F1 to open, arrows to move and change, H to
jump by heading.

Navigation model, chosen to match what a screen-reader user already knows
rather than inventing a game-menu idiom:

- **Up and down move item by item** through the whole list, across category
  boundaries. Crossing into a new category announces its heading first
  ("Speech. Room announcements, on."), so the structure is audible without
  having to go looking for it.
- **H jumps to the next heading**, shift+H to the previous one, wrapping at
  the ends -- NVDA's browse-mode convention. Shift+H from the middle of a
  category goes to the top of the CURRENT category first, again matching
  what NVDA does, so "back to the start of this section" is one press.
- **Left and right change the value in place.** No sub-menu, no confirm
  step: every setting here is a toggle or a stepped number, and both are
  fully described by re-speaking the item after the change.
- **Enter and space activate** (flip a toggle); **escape and F1 close**.

Item movement stops at the ends and says so rather than wrapping. Wrapping
is right for the entity-nav category cycle -- a ring of live entities has no
meaningful "end" -- but a settings list does have one, and silently arriving
back at the top is how a player loses track of where they are.

Nothing here reads or writes emulated memory. The menu is companion state
and speech only; the game keeps running underneath it, exactly as it does
while any other companion hotkey is used.
"""
from .settings import VALUELESS_KINDS
from .key_capture import (
    VK_DOWN, VK_END, VK_ESCAPE, VK_F1, VK_H, VK_HOME, VK_LEFT, VK_RETURN,
    VK_RIGHT, VK_SPACE, VK_UP,
)
from .speech import SpeechEventClass


HELP_TEXT = (
    "Up and down arrows to move, H for the next heading, "
    "left and right to change a setting, escape to close."
)
EMPTY_MESSAGE = "Settings. No settings are available."
CLOSED_MESSAGE = "Settings closed."
SAVE_FAILED_MESSAGE = "Settings could not be saved to disk."


class SettingsMenu:
    """Owns the open/closed state, the cursor, and everything spoken.

    `controller` is the lifecycle whose readers the appliers push values
    into. It is assigned after construction (and reassigned on every
    reattach) because the readers do not exist yet when this is built.
    """

    def __init__(self, store, capture, speech, logger, controller=None):
        self.store = store
        self.capture = capture
        self.speech = speech
        self.logger = logger
        self.controller = controller
        self.open = False
        self.index = 0
        self.helped = False
        self.entries = tuple(
            (category, item)
            for category in store.categories
            for item in category.items
        )

    # -- state ---------------------------------------------------------

    @property
    def category(self):
        return self.entries[self.index][0] if self.entries else None

    @property
    def item(self):
        return self.entries[self.index][1] if self.entries else None

    def clear(self, reason):
        """Close on a lifecycle reset. The menu owns keys the game also
        wants, so leaving it open across a disconnect would keep swallowing
        arrows with nothing listening."""
        if self.open:
            self.logger.debug("SETTINGS MENU closed: %s", reason)
        self.open = False
        self.capture.menu_open = False
        self.capture.discard()

    # -- polling -------------------------------------------------------

    def poll_once(self):
        for event in self.capture.poll():
            self.handle(event)

    def handle(self, event):
        if event.vk == VK_F1:
            if self.open:
                self.close()
            else:
                self.open_menu()
            return
        if not self.open:
            # Nothing else is captured while closed, so this only happens if
            # a key arrived in the same tick the menu was closed by another
            # path. Dropping it is right: it was meant for the menu.
            return
        if event.vk == VK_ESCAPE:
            self.close()
        elif event.vk == VK_DOWN:
            self._move(1)
        elif event.vk == VK_UP:
            self._move(-1)
        elif event.vk == VK_RIGHT:
            self._adjust(1)
        elif event.vk == VK_LEFT:
            self._adjust(-1)
        elif event.vk == VK_H:
            self._heading(-1 if event.shift else 1)
        elif event.vk in (VK_RETURN, VK_SPACE):
            self._activate()
        elif event.vk == VK_HOME:
            self._jump(0)
        elif event.vk == VK_END:
            self._jump(len(self.entries) - 1)

    # -- opening and closing -------------------------------------------

    def open_menu(self):
        if not self.entries:
            self._say(EMPTY_MESSAGE)
            return
        self.open = True
        self.capture.menu_open = True
        self.capture.discard()
        pieces = ["Settings."]
        if not self.helped:
            # Spoken once per session. A player who opens the menu twenty
            # times does not need the instructions twenty times, and one
            # long sentence in front of the thing they came for is the
            # fastest way to make a menu feel slow.
            pieces.append(HELP_TEXT)
            self.helped = True
        pieces.append(self._entry_text(include_heading=True))
        self._say(" ".join(pieces))
        self.logger.info("SETTINGS MENU opened at %s", self.item.key)

    def close(self):
        self.open = False
        self.capture.menu_open = False
        self.capture.discard()
        self._say(CLOSED_MESSAGE)
        self.logger.info("SETTINGS MENU closed")

    # -- movement ------------------------------------------------------

    def _move(self, direction):
        previous_category = self.category
        target = self.index + direction
        if target < 0:
            self._say("Top of list. " + self._entry_text())
            return
        if target >= len(self.entries):
            self._say("End of list. " + self._entry_text())
            return
        self.index = target
        self._say(self._entry_text(
            include_heading=self.category is not previous_category))

    def _jump(self, index):
        if not self.entries:
            return
        self.index = max(0, min(len(self.entries) - 1, index))
        self._say(self._entry_text(include_heading=True))

    def _category_bounds(self):
        """(first index, category) for each non-empty category, in order.

        Built from the flattened entry list rather than from the categories
        themselves so an empty category -- Hotkeys, if no hotkeys were
        passed -- simply is not a heading to land on."""
        bounds = []
        for index, (category, _) in enumerate(self.entries):
            if not bounds or bounds[-1][1] is not category:
                bounds.append((index, category))
        return bounds

    def _heading(self, direction):
        bounds = self._category_bounds()
        if not bounds:
            return
        starts = [index for index, _ in bounds]
        if direction > 0:
            following = [index for index in starts if index > self.index]
            target = following[0] if following else starts[0]
        else:
            # Shift+H from inside a category goes to that category's own
            # heading first (NVDA's behaviour), so it takes two presses to
            # leave a category you are in the middle of -- which is what
            # makes "back to the top of this section" reachable at all.
            preceding = [index for index in starts if index < self.index]
            target = preceding[-1] if preceding else starts[-1]
        self.index = target
        self._say(self._entry_text(include_heading=True))

    # -- changing values -----------------------------------------------

    def _adjust(self, direction):
        item = self.item
        if item is None or item.kind in VALUELESS_KINDS:
            self._say(self._entry_text())
            return
        current = self.store.get(item.key)
        updated = item.adjust(current, direction)
        if updated == current:
            edge = "minimum" if direction < 0 else "maximum"
            self._say(f"{self._entry_text()} {edge.capitalize()}.")
            return
        self.store.set(item.key, updated, self.controller)
        self._say(self._entry_text())
        self.logger.info("SETTINGS %s = %s", item.key, updated)

    def _activate(self):
        item = self.item
        if item is None:
            return
        if item.kind == "sound":
            # The only item kind whose activation does something to the
            # world rather than to a stored value. Nothing is re-spoken:
            # the player pressed Enter to HEAR the cue, and talking over it
            # is exactly what would stop them recognising it later.
            item.play()
            self.logger.info("SETTINGS played %s", item.key)
            return
        if item.kind == "info":
            self._say(self._entry_text())
            return
        current = self.store.get(item.key)
        updated = item.activate(current)
        if updated == current:
            self._say(self._entry_text())
            return
        self.store.set(item.key, updated, self.controller)
        self._say(self._entry_text())
        self.logger.info("SETTINGS %s = %s", item.key, updated)

    # -- speech --------------------------------------------------------

    def _entry_text(self, include_heading=False):
        category, item = self.entries[self.index]
        value = item.speak_value(
            None if item.kind in VALUELESS_KINDS else self.store.get(item.key))
        text = f"{item.label}, {value}."
        if item.kind == "sound" and item.description:
            # Spoken for sound cues alone -- see `settings.Sound`. Every
            # other item's label already says what it does; a cue's meaning
            # is the thing the player came here to be told.
            text += f" {item.description}"
        return f"{category.title}. {text}" if include_heading else text

    def _say(self, text):
        self.speech.emit(
            SpeechEventClass.MENU_FOCUS, text, deduplicate=False,
            interrupt=True)
