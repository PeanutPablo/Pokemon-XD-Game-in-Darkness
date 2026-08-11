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

from battle_narrator.phase1b_app import parser


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
