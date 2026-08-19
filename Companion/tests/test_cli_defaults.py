"""Guards on what the narrator does when launched with NO arguments.

The launcher the project owner actually uses is a desktop `.bat` outside
this repository, so a feature that is "on" only because that file happens
to pass a flag is one edit away from being off with no test noticing.
Anything the owner has asked to be on by default is asserted here against
a bare `parse_args([])`.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.hotkeys import MODIFIER_CODES, WindowsForegroundHotkey
from battle_narrator.phase1b_app import parser


class HotkeyDefaultTests(unittest.TestCase):
    """Every default chord in one place, and the rule that no two of them
    may collide. The collision test is the point: `ctrl+shift+slash` was
    handed to autowalk on 2026-08-16 and had to be taken off refresh first,
    which nothing would have caught."""

    HOTKEY_ARGUMENTS = (
        "hp_summary_hotkey", "heart_gauge_hotkey", "money_hotkey",
        "entity_next_hotkey", "entity_prev_hotkey",
        "entity_next_category_hotkey", "entity_prev_category_hotkey",
        "entity_repeat_hotkey", "autowalk_hotkey",
        "interaction_mark_hotkey", "audio_guide_hotkey",
        "navigation_guide_hotkey", "teleport_hotkey",
    )

    def defaults(self):
        args = parser().parse_args([])
        return {name: getattr(args, name) for name in self.HOTKEY_ARGUMENTS}

    def test_autowalk_is_on_ctrl_shift_slash(self):
        # Project owner's request, 2026-08-16.
        self.assertEqual(self.defaults()["autowalk_hotkey"], "ctrl+shift+slash")

    def test_the_refresh_hotkey_is_gone(self):
        # Removed the same day, rather than rehomed off the chord autowalk
        # took: it had never run in production (see ExactChordTests).
        self.assertFalse(hasattr(parser().parse_args([]),
                                 "entity_refresh_hotkey"))

    def test_no_two_defaults_share_a_chord(self):
        chords = [
            frozenset(value.casefold().split("+"))
            for value in self.defaults().values()
        ]
        self.assertEqual(len(chords), len(set(chords)))


class FakeUser32:
    def __init__(self, held):
        self.held = set(held)

    def GetAsyncKeyState(self, code):
        return 0x8000 if code in self.held else 0


class ExactChordTests(unittest.TestCase):
    """A chord must mean exactly itself: an unnamed modifier being held
    makes it NOT pressed. Before this, `ctrl+slash` matched every
    `ctrl+shift+slash` press, which is why entity-nav's refresh -- checked
    after repeat in the same elif chain -- had never once run."""

    CTRL, SHIFT, SLASH = MODIFIER_CODES["ctrl"], MODIFIER_CODES["shift"], 0xBF

    def hotkey(self, chord, held):
        value = WindowsForegroundHotkey(
            chord, user32=FakeUser32(held), kernel32=object())
        value.user32 = FakeUser32(held)
        return value

    def test_the_shorter_chord_is_not_pressed_while_shift_is_held(self):
        self.assertFalse(
            self.hotkey("ctrl+slash", (self.CTRL, self.SHIFT, self.SLASH))
            ._pressed())

    def test_the_longer_chord_is_pressed(self):
        self.assertTrue(
            self.hotkey(
                "ctrl+shift+slash", (self.CTRL, self.SHIFT, self.SLASH))
            ._pressed())

    def test_the_shorter_chord_is_pressed_on_its_own(self):
        self.assertTrue(
            self.hotkey("ctrl+slash", (self.CTRL, self.SLASH))._pressed())

    def test_a_missing_key_is_still_not_pressed(self):
        self.assertFalse(
            self.hotkey("ctrl+slash", (self.CTRL,))._pressed())


class TerrainFootstepDefaultTests(unittest.TestCase):
    def test_footsteps_are_on_with_no_arguments(self):
        # Requested 2026-08-10: "make sure that enabling footsteps is
        # always turned on when starting the script."
        self.assertTrue(parser().parse_args([]).terrain_footsteps)

    def test_the_old_opt_in_flag_still_parses(self):
        # Existing launchers pass it; it is now a no-op, not an error.
        self.assertTrue(
            parser().parse_args(["--terrain-footsteps"]).terrain_footsteps)

    def test_footsteps_can_still_be_turned_off(self):
        self.assertFalse(
            parser().parse_args(["--no-terrain-footsteps"]).terrain_footsteps)

    def test_collision_feedback_is_still_off_by_default(self):
        # Deliberately NOT swept along: it is gated on an unverified
        # movement-input read (see movement_input.py), and the two flags
        # were split precisely so one could not enable the other.
        self.assertFalse(parser().parse_args([]).collision_feedback)


if __name__ == "__main__":
    unittest.main()
