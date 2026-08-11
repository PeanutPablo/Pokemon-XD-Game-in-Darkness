import logging
import unittest

from battle_narrator.hotkeys import HeartGaugeSummary
from battle_narrator.party import PartyMove, PartySlot, PartyStats
from battle_narrator.phase1b_lifecycle import LifecycleController


def slot(index, nickname, heart_gauge_percent):
    return PartySlot(
        index, nickname, 10, 29, 33, 0,
        PartyStats(18, 18, 14, 18, 18),
        (PartyMove("TACKLE", 35),), "LEON", 1305, "Bashful", 0,
        "", "", heart_gauge_percent,
    )


class Source:
    def __init__(self, slots):
        self._slots = slots

    def slots(self):
        return list(self._slots)


class FailingSource:
    def slots(self):
        raise MemoryError("boom")


class Hotkey:
    def __init__(self):
        self.fire = False

    def poll(self):
        result = self.fire
        self.fire = False
        return result


class Speech:
    def __init__(self):
        self.calls = []

    def emit(self, event, text, interrupt=None):
        self.calls.append((event, text, interrupt))


class HeartGaugeSummaryTests(unittest.TestCase):
    def setUp(self):
        self.hotkey = Hotkey()
        self.speech = Speech()
        self.logger = logging.getLogger("heart-gauge-summary-test")

    def _summary(self, slots):
        return HeartGaugeSummary(
            Source(slots), self.hotkey, self.speech, self.logger)

    def press(self, summary):
        self.hotkey.fire = True
        summary.poll_once()

    def test_no_shadow_pokemon_speaks_placeholder(self):
        summary = self._summary([slot(0, "EEVEE", None)])
        self.press(summary)
        self.assertEqual(
            self.speech.calls[-1][1], "No Shadow Pokemon in your party.")

    def test_partial_heart_gauge_is_spoken(self):
        summary = self._summary([slot(0, "TEDDIURSA", 75)])
        self.press(summary)
        self.assertEqual(
            self.speech.calls[-1][1], "Teddiursa: 75 percent open.")

    def test_fully_open_heart_gauge_is_spoken(self):
        summary = self._summary([slot(0, "TEDDIURSA", 100)])
        self.press(summary)
        self.assertEqual(
            self.speech.calls[-1][1],
            "Teddiursa: fully open, ready to purify.")

    def test_non_shadow_slots_are_omitted_from_a_mixed_party(self):
        summary = self._summary([
            slot(0, "EEVEE", None),
            slot(1, "TEDDIURSA", 50),
        ])
        self.press(summary)
        self.assertEqual(
            self.speech.calls[-1][1], "Teddiursa: 50 percent open.")

    def test_multiple_shadow_pokemon_are_combined_in_one_utterance(self):
        summary = self._summary([
            slot(0, "TEDDIURSA", 50),
            slot(1, "SNUBBULL", 100),
        ])
        self.press(summary)
        self.assertEqual(
            self.speech.calls[-1][1],
            "Teddiursa: 50 percent open. Snubbull: fully open, ready to purify.")

    def test_no_press_is_silent(self):
        summary = self._summary([slot(0, "TEDDIURSA", 50)])
        summary.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_read_failure_is_silent(self):
        summary = HeartGaugeSummary(
            FailingSource(), self.hotkey, self.speech, self.logger)
        self.press(summary)
        self.assertEqual(self.speech.calls, [])

    def test_lifecycle_accepts_heart_gauge_summary_factory(self):
        summary = self._summary([])
        factory = lambda: summary
        controller = LifecycleController(
            object(), lambda: None, lambda tasks: None, object(),
            logging.getLogger("lifecycle-heart-gauge-test"),
            heart_gauge_summary_factory=factory,
        )
        self.assertIs(controller.heart_gauge_summary_factory, factory)
        self.assertIsNone(controller.heart_gauge_summary_reader)


if __name__ == "__main__":
    unittest.main()
