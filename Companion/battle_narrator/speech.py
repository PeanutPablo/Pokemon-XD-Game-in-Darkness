from enum import Enum, auto
import time


class SpeechError(RuntimeError):
    pass


class SpeechEventClass(Enum):
    LIFECYCLE = auto()
    MENU_FOCUS = auto()
    BATTLE_EVENT = auto()
    DIALOGUE = auto()
    NPC_INTERACTION = auto()
    ENTITY_NAV = auto()
    WARNING = auto()


class NVDASpeaker:
    def __init__(self, tolk):
        self.tolk = tolk
        self.loaded = False

    def open(self):
        self.tolk.load()
        self.loaded = bool(self.tolk.is_loaded())
        if not self.loaded:
            raise SpeechError("NVDA speech support could not be loaded")
        reader = self.tolk.detect_screen_reader()
        if reader is None:
            raise SpeechError("NVDA is unavailable")
        return reader

    def speak(self, text, interrupt=False):
        if not self.loaded:
            raise SpeechError("NVDA speech is not initialized")
        return bool(self.tolk.speak(text, interrupt=interrupt))

    def close(self):
        if self.loaded:
            self.tolk.unload()
            self.loaded = False


class SpeechCoordinator:
    """Coordinates the interruption behavior supported by cytolk.speak.

    cytolk exposes only speak(text, interrupt=False), silence(), and status
    helpers; it has no priority queue. Menu focus replaces stale focus.
    Confirmed battle events also interrupt stale menu speech and are emitted
    immediately, preserving the order in which BattleNarrator submits them.
    Lifecycle/warning messages do not interrupt current player-facing speech.
    """

    CROSS_READER_DEDUP_CLASSES = frozenset({
        SpeechEventClass.DIALOGUE, SpeechEventClass.MENU_FOCUS,
    })
    """Classes between which the SAME text means the same event twice.

    Live 2026-08-18, one millisecond apart:

        17:19:47.634 class=DIALOGUE   'LEON obtained the Cologne Case!'
        17:19:47.635 MENU FOCUS NotificationFocus(message_id=54005, ...)
        17:19:47.635 class=MENU_FOCUS 'LEON obtained the Cologne Case!'

    The dialogue reader and the notification window reader both render the
    same game message, and the player hears it twice. 76 occurrences across
    the production logs -- item pickups and Purify Chamber notices, mostly
    -- in BOTH orders, which is why neither reader can simply be muted:
    each is sometimes the only one that fires, so silencing either would
    lose the message outright.

    Scoped to this pair rather than applied globally, deliberately. A
    player genuinely re-reading a line produces the SAME class twice
    (DIALOGUE then DIALOGUE, or the entity-nav repeat hotkey), and the
    closest such legitimate repeat measured in the logs is 0.49s -- close
    enough to the 0.38s worst observed duplicate that a global window would
    be guessing. Across these two classes there is no legitimate case: one
    reader speaking exactly what the other just said is the duplication
    itself."""

    CROSS_READER_DEDUP_SECONDS = 1.0
    """How long an utterance suppresses its twin from the other reader.
    Comfortably above the 0.38s worst observed gap, and safe to be generous
    because the window only applies across the pair above."""

    def __init__(self, speaker, logger, clock=time.monotonic):
        self.speaker = speaker
        self.logger = logger
        self.clock = clock
        self.last_by_class = {}
        self.last_class = None
        self._recent_cross = None
        """(text, class, time) of the last utterance eligible for
        cross-reader dedup. The class is carried so a repeat from the SAME
        reader can be told from the two-reader race this suppresses."""

    def emit(self, event_class, text, deduplicate=False, interrupt=None):
        if deduplicate and self.last_by_class.get(event_class) == text:
            self.logger.debug(
                "SPEECH DEDUP class=%s text=%r", event_class.name, text
            )
            return False
        if event_class in self.CROSS_READER_DEDUP_CLASSES:
            now = self.clock()
            recent = self._recent_cross
            if (recent is not None and recent[0] == text
                    # CROSS-reader only. The same class saying the same
                    # thing twice is a player re-reading a line, which is
                    # legitimate and must survive -- it is a different
                    # event from two readers racing over one message.
                    and recent[1] is not event_class
                    and now - recent[2] < self.CROSS_READER_DEDUP_SECONDS):
                # Two readers, one message. See CROSS_READER_DEDUP_CLASSES.
                self.logger.info(
                    "SPEECH CROSS DEDUP class=%s text=%r", event_class.name,
                    text)
                self._recent_cross = (text, event_class, now)
                return False
            self._recent_cross = (text, event_class, now)
        if interrupt is None:
            interrupt = event_class in {
                SpeechEventClass.MENU_FOCUS,
                SpeechEventClass.BATTLE_EVENT,
                SpeechEventClass.DIALOGUE,
                SpeechEventClass.NPC_INTERACTION,
                SpeechEventClass.ENTITY_NAV,
            }
        if event_class is SpeechEventClass.MENU_FOCUS and text in {"Yes", "No"}:
            interrupt = False
        if (
            interrupt
            and event_class is SpeechEventClass.BATTLE_EVENT
            and self.last_class is SpeechEventClass.BATTLE_EVENT
        ):
            # A battle event interrupts STALE MENU speech -- that is what
            # the interrupt was for. It must never interrupt another battle
            # event: consecutive battle facts are all things the player
            # needs, and cutting one off loses information.
            #
            # This is the reported "Oh! A Shadow Pokemon!" arriving as
            # "h! A Shadow Pokemon!". Caught in the production log with
            # timestamps rather than guessed at:
            #
            #   00:05:50.837 interrupt=False "Blastoise's Accuracy fell!"
            #   00:05:50.901 interrupt=True  "Blastoise's accuracy fell!"
            #
            # 64 ms apart, the second silencing the first mid-word. The
            # text was never truncated -- the log holds both in full -- so
            # the loss is in playback, and slicing text to compensate would
            # have hidden the real fault.
            interrupt = False
            self.logger.debug(
                "SPEECH NO SELF INTERRUPT class=%s text=%r",
                event_class.name, text,
            )
        result = self.speaker.speak(text, interrupt=interrupt)
        self.last_by_class[event_class] = text
        self.last_class = event_class
        self.logger.debug(
            "SPEECH class=%s interrupt=%s text=%r result=%s",
            event_class.name,
            interrupt,
            text,
            result,
        )
        return result

    def clear(self):
        self.last_by_class.clear()
        self.last_class = None
        self._recent_cross = None



