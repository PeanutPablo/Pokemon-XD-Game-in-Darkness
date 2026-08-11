# NOTE: traversal_log.py is SHELVED (2026-08-01) -- not consumed by
# NavigationService or anything else. See that module's own docstring for
# why (the walk-model investigation made its motivating premise moot).
# These tests are kept because the module itself is kept, documented and
# working, not because it's on a path to being wired in.
import unittest

from battle_narrator.npc_beacons import Position
from battle_narrator.traversal_log import TraversalContext, TraversalRecorder


def clear_context(floor_id=1, **overrides):
    base = dict(
        floor_id=floor_id, in_battle=False, in_menu=False, dialogue_active=False,
        cutscene_active=False, teleported=False, collision_stuck=False,
        player_input_active=True,
    )
    base.update(overrides)
    return TraversalContext(**base)


class TraversalRecorderTests(unittest.TestCase):
    def test_valid_consecutive_samples_record_an_edge(self):
        recorder = TraversalRecorder()
        recorder.record(Position(0.0, 0.0, 0.0), clear_context())
        recorder.record(Position(9.0, 0.0, 0.0), clear_context())
        self.assertTrue(recorder.has_edge(1, (0, 0), (1, 0)))

    def test_first_ever_sample_records_nothing(self):
        recorder = TraversalRecorder()
        recorder.record(Position(0.0, 0.0, 0.0), clear_context())
        self.assertFalse(recorder.has_edge(1, (0, 0), (0, 0)))

    def test_standing_still_records_no_self_edge(self):
        recorder = TraversalRecorder()
        recorder.record(Position(0.0, 0.0, 0.0), clear_context())
        recorder.record(Position(0.5, 0.0, 0.0), clear_context())
        self.assertFalse(recorder.has_edge(1, (0, 0), (0, 0)))

    def test_teleported_sample_is_not_recorded(self):
        recorder = TraversalRecorder()
        recorder.record(Position(0.0, 0.0, 0.0), clear_context())
        recorder.record(Position(9.0, 0.0, 0.0), clear_context(teleported=True))
        self.assertFalse(recorder.has_edge(1, (0, 0), (1, 0)))

    def test_room_transition_is_not_recorded_even_with_a_small_delta(self):
        recorder = TraversalRecorder()
        recorder.record(Position(0.0, 0.0, 0.0), clear_context(floor_id=1))
        recorder.record(Position(1.0, 0.0, 0.0), clear_context(floor_id=2))
        self.assertFalse(recorder.has_edge(1, (0, 0), (0, 0)))
        self.assertFalse(recorder.has_edge(2, (0, 0), (0, 0)))

    def test_large_coordinate_jump_is_not_recorded(self):
        recorder = TraversalRecorder()
        recorder.record(Position(0.0, 0.0, 0.0), clear_context())
        recorder.record(Position(500.0, 0.0, 0.0), clear_context())
        self.assertFalse(recorder.has_edge(1, (0, 0), (62, 0)))

    def test_non_finite_position_is_ignored_not_treated_as_the_new_previous_sample(self):
        recorder = TraversalRecorder()
        recorder.record(Position(0.0, 0.0, 0.0), clear_context())
        recorder.record(Position(float("nan"), 0.0, 0.0), clear_context())
        recorder.record(Position(9.0, 0.0, 0.0), clear_context())
        # A single bad momentary read shouldn't poison the chain -- the real
        # movement from (0,0,0) to (9,0,0) is still a legitimate edge, and
        # (crucially) the NaN sample itself never becomes a usable endpoint.
        self.assertTrue(recorder.has_edge(1, (0, 0), (1, 0)))

    def test_excluded_states_are_not_recorded(self):
        exclusion_cases = (
            {"in_battle": True},
            {"in_menu": True},
            {"dialogue_active": True},
            {"cutscene_active": True},
            {"collision_stuck": True},
            {"player_input_active": False},
        )
        for overrides in exclusion_cases:
            with self.subTest(overrides=overrides):
                recorder = TraversalRecorder()
                recorder.record(Position(0.0, 0.0, 0.0), clear_context())
                recorder.record(Position(9.0, 0.0, 0.0), clear_context(**overrides))
                self.assertFalse(recorder.has_edge(1, (0, 0), (1, 0)))

    def test_excluded_previous_sample_also_blocks_the_edge(self):
        # Both ends of a step must be valid -- an excluded PREVIOUS sample
        # (e.g. the player was in a menu one poll ago) must not let the
        # NEXT, otherwise-clean sample form an edge with it.
        recorder = TraversalRecorder()
        recorder.record(Position(0.0, 0.0, 0.0), clear_context(in_menu=True))
        recorder.record(Position(9.0, 0.0, 0.0), clear_context())
        self.assertFalse(recorder.has_edge(1, (0, 0), (1, 0)))

    def test_breadcrumb_route_retraces_the_walked_trail(self):
        recorder = TraversalRecorder()
        for x in (0.0, 9.0, 18.0, 27.0):
            recorder.record(Position(x, 0.0, 0.0), clear_context())
        route = recorder.breadcrumb_route(1, (3, 0))
        self.assertEqual(route, [(3, 0), (2, 0), (1, 0), (0, 0)])

    def test_breadcrumb_route_is_none_for_an_unvisited_tile(self):
        recorder = TraversalRecorder()
        recorder.record(Position(0.0, 0.0, 0.0), clear_context())
        recorder.record(Position(9.0, 0.0, 0.0), clear_context())
        self.assertIsNone(recorder.breadcrumb_route(1, (99, 99)))

    def test_no_extrapolation_from_a_thin_trail(self):
        recorder = TraversalRecorder()
        recorder.record(Position(0.0, 0.0, 0.0), clear_context())
        recorder.record(Position(9.0, 0.0, 0.0), clear_context())
        # Only (0,0)->(1,0) was ever recorded -- a geometric neighbor, or
        # even the exact reverse direction, must not be treated as
        # supported just because it touches a real edge.
        self.assertFalse(recorder.has_edge(1, (1, 0), (2, 0)))
        self.assertFalse(recorder.has_edge(1, (1, 0), (0, 0)))
        self.assertIsNone(recorder.supported_height(1, (2, 0)))
        self.assertIsNotNone(recorder.supported_height(1, (0, 0)))
        self.assertIsNotNone(recorder.supported_height(1, (1, 0)))


if __name__ == "__main__":
    unittest.main()
