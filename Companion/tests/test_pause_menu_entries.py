"""The overworld pause menu hides entries the player has not unlocked.

Reported live, 2026-08-13: before obtaining the P*DA the start menu reads
wrong. The project owner confirmed what is actually on screen -- "its
everything but pda. pokemon items save exit" -- so the game DROPS the
entry rather than greying it out, and the five-name list was being
indexed by a four-row cursor. Row 1 is Items but was announced as P*DA,
row 2 is Save announced as Items, and so on.

The game does not leave this to be guessed. `menuTop` (0x8002F718) walks
five candidates, tests each with `menuItemBiosGetSelectFlag`, and calls
`menuTitleSetSelect(row, candidate)` for the visible ones, storing a s16
at `_menuTitleWork+0x40` indexed by row (`sth r4, 0x40(r3)`,
0x800A31BC). The identity case below is live-confirmed: on a save that
owns the P*DA the real table reads (0, 1, 2, 3, 4)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.party_action_menu import PartyActionMenuReader
from battle_narrator.profile import XD_US_REV0
from battle_narrator.speech import SpeechEventClass

WINDOW = 0x80300000


class Memory:
    def __init__(self, row, entries):
        self.row = row
        self.entries = entries

    def u8(self, address, label="u8"):
        return self.row

    def u16(self, address, label="u16"):
        index = (address - XD_US_REV0.pause_menu_entry_map) // 2
        if 0 <= index < len(self.entries):
            return self.entries[index]
        return 0xFFFF


class Speech:
    def __init__(self):
        self.said = []

    def emit(self, event_class, text, interrupt=True):
        self.said.append(text)
        return True


class Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, fmt, *args):
        self.warnings.append(fmt % args if args else fmt)

    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def read(row, entries):
    speech, logger = Speech(), Logger()
    reader = PartyActionMenuReader(
        Memory(row, entries), XD_US_REV0, speech, logger,
        menu_id=XD_US_REV0.pause_menu_id,
        labels=XD_US_REV0.pause_menu_labels,
        entry_map=XD_US_REV0.pause_menu_entry_map,
        entry_stride=XD_US_REV0.pause_menu_entry_stride)
    reader._find_window = lambda: WINDOW
    reader.poll_once()
    return speech.said, logger


WITH_PDA = (0, 1, 2, 3, 4)
"""Live-confirmed identity mapping when every entry is visible."""
WITHOUT_PDA = (0, 2, 3, 4)
"""P*DA (candidate 1) hidden, so four rows naming candidates 0, 2, 3, 4."""


class WithThePdaTests(unittest.TestCase):
    def test_every_row_reads_as_before(self):
        expected = ["Pokemon.", "P star D A.", "Items.", "Save.", "Exit."]
        for row, want in enumerate(expected):
            said, _ = read(row, WITH_PDA)
            self.assertEqual(said, [want], f"row {row}")


class WithoutThePdaTests(unittest.TestCase):
    """The reported bug, row by row."""

    def test_the_menu_reads_what_is_actually_on_screen(self):
        expected = ["Pokemon.", "Items.", "Save.", "Exit."]
        for row, want in enumerate(expected):
            said, _ = read(row, WITHOUT_PDA)
            self.assertEqual(said, [want], f"row {row}")

    def test_the_pda_is_never_announced_when_it_is_not_there(self):
        for row in range(4):
            said, _ = read(row, WITHOUT_PDA)
            self.assertNotIn("P star D A.", said)

    def test_the_old_behaviour_would_have_failed_this(self):
        """Guards the fix, not just the result: indexing the label tuple
        by the row is exactly what shipped, and it names P*DA on row 1."""
        self.assertEqual(XD_US_REV0.pause_menu_labels[1], "P star D A")
        said, _ = read(1, WITHOUT_PDA)
        self.assertEqual(said, ["Items."])


class UnknownEntryTests(unittest.TestCase):
    def test_an_unrecognised_entry_says_nothing(self):
        """Silence beats naming the wrong option -- the player is about to
        press A on whatever the row really is."""
        said, logger = read(0, (99,))
        self.assertEqual(said, [])
        self.assertTrue(logger.warnings)


class OtherMenusTests(unittest.TestCase):
    def test_a_menu_without_a_map_still_uses_its_row(self):
        """Only the pause menu hides entries; the party action popup, bag
        tabs and stone list must keep working unchanged."""
        speech, logger = Speech(), Logger()
        reader = PartyActionMenuReader(
            Memory(1, ()), XD_US_REV0, speech, logger,
            menu_id=XD_US_REV0.party_action_menu_id,
            labels=XD_US_REV0.party_action_labels)
        reader._find_window = lambda: WINDOW
        reader.poll_once()
        self.assertEqual(
            speech.said, [XD_US_REV0.party_action_labels[1] + "."])


if __name__ == "__main__":
    unittest.main()
