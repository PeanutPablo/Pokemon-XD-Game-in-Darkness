"""Cross-reader duplicate suppression in `SpeechCoordinator`.

The project owner, 2026-08-18: "texts repeat themselves". The production
log had the answer, one millisecond apart:

    17:19:47.634 class=DIALOGUE   'LEON obtained the Cologne Case!'
    17:19:47.635 MENU FOCUS NotificationFocus(message_id=54005, ...)
    17:19:47.635 class=MENU_FOCUS 'LEON obtained the Cologne Case!'

The dialogue reader and the notification-window reader both render the
same game message. 76 occurrences across the logs, in BOTH orders -- which
is why neither reader could simply be muted.
"""
import logging
import unittest

from battle_narrator.speech import SpeechCoordinator, SpeechEventClass


class Speaker:
    def __init__(self):
        self.spoken = []

    def speak(self, text, interrupt=False):
        self.spoken.append(text)
        return True


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def logger():
    log = logging.getLogger("speech-coordinator-test")
    log.addHandler(logging.NullHandler())
    return log


class CrossReaderDedupTests(unittest.TestCase):
    def setUp(self):
        self.speaker = Speaker()
        self.clock = Clock()
        self.speech = SpeechCoordinator(
            self.speaker, logger(), clock=self.clock)

    def test_the_second_reader_of_the_same_message_is_dropped(self):
        text = "LEON obtained the Cologne Case!"
        self.assertTrue(self.speech.emit(SpeechEventClass.DIALOGUE, text))
        self.clock.now += 0.001
        self.assertFalse(self.speech.emit(SpeechEventClass.MENU_FOCUS, text))
        self.assertEqual(self.speaker.spoken, [text])

    def test_it_works_in_the_other_order_too(self):
        # Both orders occur live, which is why neither reader is muted.
        text = "FOOTLEG found 1 Full Heal!"
        self.assertTrue(self.speech.emit(SpeechEventClass.MENU_FOCUS, text))
        self.clock.now += 0.06
        self.assertFalse(self.speech.emit(SpeechEventClass.DIALOGUE, text))
        self.assertEqual(self.speaker.spoken, [text])

    def test_a_message_only_one_reader_claims_is_still_spoken(self):
        # The whole reason for deduping rather than muting a reader.
        text = "Tim: Bring it on!"
        self.assertTrue(self.speech.emit(SpeechEventClass.DIALOGUE, text))
        self.assertEqual(self.speaker.spoken, [text])

    def test_the_same_reader_repeating_itself_is_untouched(self):
        # A player genuinely re-reading a line produces the SAME class
        # twice. That is legitimate and must survive.
        text = "Eagun: LEON, welcome!"
        self.speech.emit(SpeechEventClass.DIALOGUE, text)
        self.clock.now += 0.05
        self.speech.emit(SpeechEventClass.DIALOGUE, text)
        self.assertEqual(self.speaker.spoken, [text, text])

    def test_a_later_genuine_repeat_still_speaks(self):
        text = "LEON obtained the Cologne Case!"
        self.speech.emit(SpeechEventClass.DIALOGUE, text)
        self.clock.now += SpeechCoordinator.CROSS_READER_DEDUP_SECONDS + 0.1
        self.assertTrue(self.speech.emit(SpeechEventClass.MENU_FOCUS, text))
        self.assertEqual(self.speaker.spoken, [text, text])

    def test_different_text_from_the_other_reader_is_never_touched(self):
        self.speech.emit(SpeechEventClass.DIALOGUE, "Tim: But my true identity...")
        self.clock.now += 0.001
        self.speech.emit(SpeechEventClass.MENU_FOCUS, "Bite, 22/25 P P.")
        self.assertEqual(len(self.speaker.spoken), 2)

    def test_unrelated_classes_are_out_of_scope(self):
        # Entity-nav's own repeat hotkey is a legitimate same-text repeat
        # and is deliberately not covered by this window.
        text = "Snag Machine. 12 o'clock, distance 78."
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text)
        self.clock.now += 0.001
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text)
        self.assertEqual(self.speaker.spoken, [text, text])

    def test_a_battle_event_matching_dialogue_text_is_not_suppressed(self):
        text = "Taillow fainted!"
        self.speech.emit(SpeechEventClass.DIALOGUE, text)
        self.clock.now += 0.001
        self.speech.emit(SpeechEventClass.BATTLE_EVENT, text)
        self.assertEqual(self.speaker.spoken, [text, text])

    def test_clear_forgets_the_window(self):
        text = "LEON obtained the Cologne Case!"
        self.speech.emit(SpeechEventClass.DIALOGUE, text)
        self.speech.clear()
        self.clock.now += 0.001
        self.assertTrue(self.speech.emit(SpeechEventClass.MENU_FOCUS, text))
        self.assertEqual(self.speaker.spoken, [text, text])

    def test_the_window_covers_the_worst_gap_seen_live(self):
        # The widest cross-reader duplicate measured in the logs was 0.38s.
        self.assertGreater(SpeechCoordinator.CROSS_READER_DEDUP_SECONDS, 0.38)


if __name__ == "__main__":
    unittest.main()
