"""The game's own talk predicate, gate by gate.

Every threshold and gate here comes from `peopleTalkCheck`'s disassembly
(see battle_narrator/talk_predicate.py's module docstring), not from
tuning. The fixtures use plausible live magnitudes -- collision balls
around 3.5, talk distances in the 3-10 range -- so a regression that
reintroduces the old `talk_distance + 1.5` horizontal rule fails loudly
rather than passing by coincidence.
"""
import math
import unittest

from battle_narrator.npc_beacons import Position
from battle_narrator.talk_predicate import (
    REJECT_DISTANCE, REJECT_FACING, REJECT_MEMBER, REJECT_NOT_DISPLAYED,
    REJECT_NO_PEOPLE_INFO, REJECT_TALK_FLAG, REJECT_TALK_START_TYPE,
    REJECT_WALL, TALK_CONE_DEGREES, TalkInputs, evaluate, talk_threshold,
)


def facing_toward(hero, target):
    """The rot.y value that points the hero exactly at `target`, using the
    engine's convention that rot.y == 0 faces -Z."""
    return math.atan2(-(target.x - hero.x), -(target.z - hero.z))


def inputs(hero=None, neck=None, **overrides):
    hero = hero or Position(0.0, 0.0, 0.0)
    neck = neck or Position(0.0, 0.0, -5.0)
    defaults = dict(
        hero_position=hero,
        neck_position=neck,
        hero_facing=facing_toward(hero, neck),
        hero_col_ball_size=3.5,
        npc_col_ball_size=3.5,
        talk_distance=3.0,
        wall_through=True,
    )
    defaults.update(overrides)
    return TalkInputs(**defaults)


class ThresholdTests(unittest.TestCase):
    def test_threshold_is_the_sum_of_three_live_terms(self):
        self.assertAlmostEqual(talk_threshold(3.5, 3.0, 4.0), 10.5)

    def test_threshold_is_not_the_old_talk_distance_plus_allowance(self):
        # The pre-Phase-2 rule was `talk_distance + 1.5`. With realistic
        # collision balls the real threshold is far larger, so an NPC the
        # game would happily talk to used to be announced out of range.
        self.assertGreater(talk_threshold(3.5, 3.0, 3.5), 3.0 + 1.5)


class DistanceGateTests(unittest.TestCase):
    def test_exact_valid_interaction(self):
        verdict = evaluate(inputs())
        self.assertTrue(verdict.eligible)
        self.assertIsNone(verdict.reason)

    def test_just_inside_the_threshold(self):
        neck = Position(0.0, 0.0, -9.9)
        verdict = evaluate(inputs(neck=neck))
        self.assertAlmostEqual(verdict.threshold, 10.0)
        self.assertTrue(verdict.eligible)

    def test_just_outside_the_threshold(self):
        neck = Position(0.0, 0.0, -10.1)
        verdict = evaluate(inputs(neck=neck))
        self.assertFalse(verdict.eligible)
        self.assertEqual(verdict.reason, REJECT_DISTANCE)
        self.assertFalse(verdict.in_range)

    def test_horizontal_would_pass_but_three_d_fails(self):
        # Same X/Z as a comfortable talk, but well above -- e.g. a balcony.
        # The old horizontal rule called this in range; the engine does not.
        hero = Position(0.0, 0.0, 0.0)
        neck = Position(0.0, 30.0, -5.0)
        verdict = evaluate(inputs(hero=hero, neck=neck))
        horizontal = math.hypot(neck.x - hero.x, neck.z - hero.z)
        self.assertLess(horizontal, verdict.threshold)
        self.assertGreater(verdict.distance, verdict.threshold)
        self.assertEqual(verdict.reason, REJECT_DISTANCE)

    def test_differing_collision_sizes_change_the_threshold(self):
        small = evaluate(inputs(npc_col_ball_size=1.0))
        large = evaluate(inputs(npc_col_ball_size=8.0))
        self.assertGreater(large.threshold, small.threshold)

    def test_live_talk_distance_change_moves_the_threshold(self):
        near = evaluate(inputs(neck=Position(0.0, 0.0, -12.0), talk_distance=3.0))
        far = evaluate(inputs(neck=Position(0.0, 0.0, -12.0), talk_distance=8.0))
        self.assertEqual(near.reason, REJECT_DISTANCE)
        self.assertTrue(far.eligible)

    def test_neck_position_differing_from_model_origin_is_what_is_measured(self):
        hero = Position(0.0, 0.0, 0.0)
        origin = Position(0.0, 0.0, -10.5)
        neck = Position(0.0, 0.0, -9.5)
        self.assertFalse(evaluate(inputs(hero=hero, neck=origin)).eligible)
        self.assertTrue(evaluate(inputs(hero=hero, neck=neck)).eligible)


class FacingGateTests(unittest.TestCase):
    def test_within_the_cone(self):
        hero = Position(0.0, 0.0, 0.0)
        neck = Position(0.0, 0.0, -5.0)
        facing = facing_toward(hero, neck) + math.radians(TALK_CONE_DEGREES - 5)
        self.assertTrue(evaluate(inputs(hero=hero, neck=neck,
                                        hero_facing=facing)).eligible)

    def test_outside_the_cone(self):
        hero = Position(0.0, 0.0, 0.0)
        neck = Position(0.0, 0.0, -5.0)
        facing = facing_toward(hero, neck) + math.radians(TALK_CONE_DEGREES + 5)
        verdict = evaluate(inputs(hero=hero, neck=neck, hero_facing=facing))
        self.assertFalse(verdict.eligible)
        self.assertEqual(verdict.reason, REJECT_FACING)
        # Still in range -- the navigator must say "walk toward it", not
        # "out of range", because the distance is fine.
        self.assertTrue(verdict.in_range)

    def test_unreadable_facing_is_unknown_not_a_pass(self):
        verdict = evaluate(inputs(hero_facing=None))
        self.assertFalse(verdict.eligible)
        self.assertIn("facing", verdict.unknown_gates)


class StateGateTests(unittest.TestCase):
    def test_display_disabled(self):
        verdict = evaluate(inputs(displayed=False))
        self.assertEqual(verdict.reason, REJECT_NOT_DISPLAYED)
        self.assertTrue(verdict.blocked_permanently)

    def test_talk_flag_bit_zero_set(self):
        verdict = evaluate(inputs(talk_flag_blocked=True))
        self.assertEqual(verdict.reason, REJECT_TALK_FLAG)
        self.assertTrue(verdict.blocked_permanently)

    def test_talk_start_type_three_is_never_talkable(self):
        verdict = evaluate(inputs(talk_start_type=3))
        self.assertEqual(verdict.reason, REJECT_TALK_START_TYPE)
        self.assertTrue(verdict.blocked_permanently)

    def test_other_talk_start_types_are_fine(self):
        for value in (0, 1, 2):
            self.assertTrue(evaluate(inputs(talk_start_type=value)).eligible)

    def test_missing_people_info(self):
        verdict = evaluate(inputs(has_people_info=False))
        self.assertEqual(verdict.reason, REJECT_NO_PEOPLE_INFO)
        self.assertTrue(verdict.blocked_permanently)

    def test_distance_rejection_is_not_permanent(self):
        verdict = evaluate(inputs(neck=Position(0.0, 0.0, -100.0)))
        self.assertFalse(verdict.blocked_permanently)


class WallGateTests(unittest.TestCase):
    def test_wall_through_skips_the_sweep_entirely(self):
        verdict = evaluate(inputs(wall_through=True, wall_blocked=True))
        self.assertTrue(verdict.eligible)

    def test_wall_blocks(self):
        verdict = evaluate(inputs(wall_through=False, wall_blocked=True))
        self.assertEqual(verdict.reason, REJECT_WALL)
        self.assertTrue(verdict.in_range)

    def test_clear_line_passes(self):
        self.assertTrue(
            evaluate(inputs(wall_through=False, wall_blocked=False)).eligible)

    def test_unavailable_geometry_is_unknown_not_a_pass(self):
        verdict = evaluate(inputs(wall_through=False, wall_blocked=None))
        self.assertFalse(verdict.eligible)
        self.assertIn("wall", verdict.unknown_gates)
        self.assertTrue(verdict.in_range)


class RemainingGateTests(unittest.TestCase):
    def test_push_box_floor_reports_unknown(self):
        verdict = evaluate(inputs(push_box_floor=True))
        self.assertFalse(verdict.eligible)
        self.assertIn("height band", verdict.unknown_gates)

    def test_following_partner_blocking(self):
        verdict = evaluate(inputs(member_blocked=True))
        self.assertEqual(verdict.reason, REJECT_MEMBER)

    def test_no_position_is_never_eligible(self):
        verdict = evaluate(inputs(neck_position=None))
        self.assertFalse(verdict.eligible)
        self.assertIsNone(verdict.distance)


if __name__ == "__main__":
    unittest.main()
