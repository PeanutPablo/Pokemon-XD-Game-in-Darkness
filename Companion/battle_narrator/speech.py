from enum import Enum, auto


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

    def __init__(self, speaker, logger):
        self.speaker = speaker
        self.logger = logger
        self.last_by_class = {}
        self.last_class = None

    def emit(self, event_class, text, deduplicate=False, interrupt=None):
        if deduplicate and self.last_by_class.get(event_class) == text:
            self.logger.debug(
                "SPEECH DEDUP class=%s text=%r", event_class.name, text
            )
            return False
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



