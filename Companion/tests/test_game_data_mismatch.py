"""The move menu must say why it has gone quiet when the data is wrong.

Twice now, in both directions, the companion has been run against a disc
its `_dialogue_extraction` was not built from:

  2026-08-12  vanilla data, XG running: live 'Zen Headbutt' / local 'MEGA PUNCH'
  2026-08-13  XG data, vanilla running: live 'SOFTBOILED' / local 'Psychic Fangs'

Both times the reader did the right thing -- refusing to speak a name it
could not confirm -- and both times the player was left with a move menu
that read one move and ignored the rest, with nothing said about why.
Only 192 of 373 move IDs name the same move in both builds, so the
handful that keep working are the ones whose IDs happen to agree.

These tests pin the reporting, not the refusal. The refusal is already
correct and must not change: announcing the local name would mean saying
"MEGA PUNCH" for Zen Headbutt."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.memory import MemoryError
from battle_narrator.menus import (
    GAME_DATA_MISMATCH_ADVICE, GameDataMismatch, MenuReadError,
)
from battle_narrator.speech import SpeechEventClass


class Speech:
    def __init__(self):
        self.events = []

    def emit(self, event_class, text, interrupt=True):
        self.events.append((event_class, text))
        return True


class Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, fmt, *args):
        self.warnings.append(fmt % args if args else fmt)

    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass


class Reader:
    """The smallest thing carrying the reader's warning behaviour."""

    from battle_narrator.menus import ProductionMenuReader as _source
    _warn_game_data_mismatch = _source._warn_game_data_mismatch

    def __init__(self):
        self.speech = Speech()
        self.logger = Logger()


class ExceptionShapeTests(unittest.TestCase):
    def test_it_is_still_an_ordinary_rejected_sample(self):
        """Subclassing matters: every existing handler catches
        MemoryError/MenuReadError and must keep refusing to speak."""
        error = GameDataMismatch("live='A' local='B'")
        self.assertIsInstance(error, MenuReadError)
        self.assertIsInstance(error, MemoryError)


class WarningTests(unittest.TestCase):
    def test_the_advice_names_the_action_that_fixes_it(self):
        """The message has to be useful to someone who cannot see the
        screen and does not know what an extraction is."""
        self.assertIn("does not match", GAME_DATA_MISMATCH_ADVICE)
        self.assertIn("disc image you are playing", GAME_DATA_MISMATCH_ADVICE)

    def test_it_speaks_the_advice_as_a_warning(self):
        reader = Reader()
        reader._warn_game_data_mismatch(
            GameDataMismatch("live='SOFTBOILED' local='Psychic Fangs'"))
        self.assertEqual(
            reader.speech.events,
            [(SpeechEventClass.WARNING, GAME_DATA_MISMATCH_ADVICE)])

    def test_it_speaks_only_once_per_session(self):
        """It repeats at the poll rate for as long as the menu is open --
        the real log recorded it dozens of times per second."""
        reader = Reader()
        for _ in range(50):
            reader._warn_game_data_mismatch(GameDataMismatch("x"))
        self.assertEqual(len(reader.speech.events), 1)

    def test_the_detail_goes_to_the_log_not_the_speech(self):
        """The player gets the action; the log keeps the evidence."""
        reader = Reader()
        reader._warn_game_data_mismatch(
            GameDataMismatch("live='SOFTBOILED' local='Psychic Fangs'"))
        self.assertEqual(len(reader.logger.warnings), 1)
        self.assertIn("SOFTBOILED", reader.logger.warnings[0])
        self.assertNotIn(
            "SOFTBOILED", reader.speech.events[0][1],
            "raw move names are diagnostic detail, not something to say")


if __name__ == "__main__":
    unittest.main()
