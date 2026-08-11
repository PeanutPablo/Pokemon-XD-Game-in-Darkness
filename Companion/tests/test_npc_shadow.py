"""Shadow comparison between the production and canonical NPC sources.

The case that matters most is `StarvationTests`: the canonical source
returning nothing where production returns entities is exactly what forced
the 2026-08-06 revert, and this reader exists to make that condition loud
and detectable BEFORE anyone swaps the sources over.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import people_fixture as fx
from battle_narrator.entities import Entity
from battle_narrator.entity_sources import LiveNPCEntitySource
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.npc_shadow import NPCSourceShadowReader
from battle_narrator.people_runtime import PeopleRuntimeSource
from battle_narrator.profile import XD_US_REV0


class Pose:
    def __init__(self, position=None, facing=0.0, model=None):
        self.position = position or Position(0.0, 0.0, 0.0)
        self.facing = facing
        self.model = model

    def player_pose(self):
        return PlayerPose(self.position, 0.0, self.facing)

    def hero_model_address(self):
        return self.model


class Logger:
    def __init__(self):
        self.debug_lines = []
        self.info_lines = []
        self.warning_lines = []

    def _render(self, args):
        if not args:
            return ""
        template = args[0]
        try:
            return template % tuple(args[1:]) if len(args) > 1 else template
        except (TypeError, ValueError):
            return " ".join(str(value) for value in args)

    def debug(self, *args):
        self.debug_lines.append(self._render(args))

    def info(self, *args):
        self.info_lines.append(self._render(args))

    def warning(self, *args):
        self.warning_lines.append(self._render(args))

    def all_lines(self):
        return self.debug_lines + self.info_lines + self.warning_lines


class StubPrimary:
    """Stands in for the production `NPCEntitySource`: publishes one entity
    per STATIC record, identified as ("npc", floor_id, index)."""

    def __init__(self, entries, floor_id=0x86):
        self.entries = entries
        self.floor_id = floor_id
        self.calls = 0

    def entities(self):
        self.calls += 1
        return [
            Entity(
                category="npc",
                identity=("npc", self.floor_id, index),
                label=label,
                position=position,
            )
            for index, label, position in self.entries
        ]

    def player_pose(self):
        return PlayerPose(Position(0.0, 0.0, 0.0), 0.0, 0.0)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_shadow(characters, floor_id=0x86, names=None, **kwargs):
    memory, backend = fx.build(characters, floor_id=floor_id, **kwargs)
    runtime = PeopleRuntimeSource(memory, XD_US_REV0)
    source = LiveNPCEntitySource(
        runtime, Pose(), names or {}, logger=Logger())
    return source, runtime, backend


def make_reader(primary, shadow, clock=None, logger=None, **kwargs):
    return NPCSourceShadowReader(
        primary, shadow, logger or Logger(), clock=clock or Clock(), **kwargs)


class StarvationTests(unittest.TestCase):
    """The revert condition. Nothing else in this file matters as much."""

    def test_canonical_source_publishing_nothing_is_a_warning(self):
        # A static record whose actor never spawned: the production source
        # publishes it at its spawn point, the canonical source correctly
        # publishes nothing -- and the player loses the whole category.
        shadow, _, _ = make_shadow(
            [fx.Character(res_id=0, spawned=False)])
        primary = StubPrimary([(0, "A", Position(1.0, 0.0, 1.0))])
        logger = Logger()
        reader = make_reader(primary, shadow, logger=logger)
        reader.poll_once()
        self.assertEqual(len(logger.warning_lines), 1)
        self.assertIn("STARVED", logger.warning_lines[0])
        self.assertIn("Do NOT", logger.warning_lines[0])

    def test_starved_room_is_recorded_for_the_go_no_go_list(self):
        shadow, _, _ = make_shadow([fx.Character(res_id=0, spawned=False)])
        primary = StubPrimary([(0, "A", Position(1.0, 0.0, 1.0))])
        reader = make_reader(primary, shadow)
        reader.poll_once()
        self.assertEqual(reader.empty_rooms, {0x86})

    def test_both_sources_empty_is_not_starvation(self):
        shadow, _, _ = make_shadow([])
        primary = StubPrimary([])
        logger = Logger()
        reader = make_reader(primary, shadow, logger=logger)
        reader.poll_once()
        self.assertEqual(logger.warning_lines, [])
        self.assertEqual(reader.empty_rooms, set())

    def test_agreement_is_not_starvation(self):
        shadow, _, _ = make_shadow([fx.Character(res_id=0)])
        primary = StubPrimary([(0, "A", Position(0.0, 0.0, 0.0))])
        logger = Logger()
        reader = make_reader(primary, shadow, logger=logger)
        reader.poll_once()
        self.assertEqual(logger.warning_lines, [])
        self.assertEqual(reader.empty_rooms, set())


class DriftTests(unittest.TestCase):
    def test_static_spawn_position_versus_live_position_is_reported(self):
        # The "NPC announced where nobody is standing" defect, measured:
        # production publishes the spawn point, the actor has walked away.
        shadow, _, _ = make_shadow([
            fx.Character(res_id=0, position=(0.0, 0.0, 0.0),
                         live_position=(30.0, 0.0, 40.0)),
        ])
        primary = StubPrimary([(0, "A", Position(0.0, 0.0, 0.0))])
        logger = Logger()
        reader = make_reader(primary, shadow, logger=logger)
        reader.poll_once()
        drift = [line for line in logger.info_lines
                 if line.startswith("NPC SHADOW drift ")]
        self.assertEqual(len(drift), 1)
        self.assertIn("d=50.00", drift[0])

    def test_agreeing_positions_produce_no_drift_line(self):
        shadow, _, _ = make_shadow([
            fx.Character(res_id=0, position=(5.0, 0.0, 5.0)),
        ])
        primary = StubPrimary([(0, "A", Position(5.0, 0.0, 5.0))])
        logger = Logger()
        reader = make_reader(primary, shadow, logger=logger)
        reader.poll_once()
        self.assertEqual(
            [line for line in logger.info_lines
             if line.startswith("NPC SHADOW drift ")], [])

    def test_drift_below_the_threshold_is_ignored(self):
        shadow, _, _ = make_shadow([
            fx.Character(res_id=0, position=(0.0, 0.0, 0.0),
                         live_position=(0.4, 0.0, 0.0)),
        ])
        primary = StubPrimary([(0, "A", Position(0.0, 0.0, 0.0))])
        logger = Logger()
        reader = make_reader(primary, shadow, logger=logger)
        reader.poll_once()
        self.assertEqual(
            [line for line in logger.info_lines
             if line.startswith("NPC SHADOW drift ")], [])


class MembershipTests(unittest.TestCase):
    def test_primary_only_entity_is_named_with_its_index(self):
        shadow, _, _ = make_shadow([
            fx.Character(res_id=0),
            fx.Character(res_id=1, spawned=False),
        ])
        primary = StubPrimary([
            (0, "A", Position(0.0, 0.0, 0.0)),
            (1, "B", Position(9.0, 0.0, 9.0)),
        ])
        logger = Logger()
        reader = make_reader(primary, shadow, logger=logger)
        reader.poll_once()
        lines = [line for line in logger.info_lines if "primary-only" in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("index=1", lines[0])
        self.assertIn("no live actor", lines[0])

    def test_shadow_only_entity_is_reported(self):
        shadow, _, _ = make_shadow([fx.Character(res_id=0)])
        primary = StubPrimary([])
        logger = Logger()
        reader = make_reader(primary, shadow, logger=logger)
        reader.poll_once()
        lines = [line for line in logger.info_lines if "shadow-only" in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("index=0", lines[0])

    def test_rejection_reasons_are_summarised(self):
        # An actor whose groupID belongs to another floor: rejected by the
        # canonical source's rule 4, and invisible to the old source's
        # `identity_a != 0` test.
        shadow, _, _ = make_shadow(
            [fx.Character(res_id=0)],
            extra_actors=[fx.Character(res_id=1, group_id=999)])
        primary = StubPrimary([(0, "A", Position(0.0, 0.0, 0.0))])
        logger = Logger()
        reader = make_reader(primary, shadow, logger=logger)
        reader.poll_once()
        lines = [line for line in logger.info_lines if "rejects" in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("does not belong to the current floor", lines[0])


class OpenQuestionTests(unittest.TestCase):
    """The three things Phase 2 could not answer without live evidence."""

    def _answers(self, characters, **kwargs):
        shadow, _, _ = make_shadow(characters, **kwargs)
        primary = StubPrimary([
            (character.res_id, "A", Position(*character.position))
            for character in characters
        ])
        logger = Logger()
        make_reader(primary, shadow, logger=logger).poll_once()
        return [line for line in logger.debug_lines if "answers" in line]

    def test_live_and_static_talk_distance_are_both_reported(self):
        lines = self._answers(
            [fx.Character(res_id=0, info_id=10, talk_distance=6.0)],
            infos={10: (-1, 3.5, 3.0)})
        self.assertEqual(len(lines), 1)
        self.assertIn("talk_live=6.00", lines[0])
        self.assertIn("talk_static=3.00", lines[0])
        self.assertIn("talk_match=False", lines[0])

    def test_matching_talk_distances_are_reported_as_matching(self):
        lines = self._answers(
            [fx.Character(res_id=0, info_id=10, talk_distance=3.0)],
            infos={10: (-1, 3.5, 3.0)})
        self.assertIn("talk_match=True", lines[0])

    def test_neck_offset_is_reported(self):
        # No neck resolver wired, so the interaction position falls back to
        # the actor position -- an offset of zero, which is still the
        # honest measurement rather than a missing field.
        lines = self._answers([fx.Character(res_id=0)])
        self.assertIn("neck_offset=0.00", lines[0])

    def test_talk_script_id_is_reported(self):
        lines = self._answers(
            [fx.Character(res_id=0, talk_script_id=122)])
        self.assertIn("talk_sct=122", lines[0])

    def test_spawn_drift_is_reported_against_the_static_record(self):
        lines = self._answers([
            fx.Character(res_id=0, position=(0.0, 0.0, 0.0),
                         live_position=(3.0, 0.0, 4.0)),
        ])
        self.assertIn("spawn_drift=5.00", lines[0])


class SafetyTests(unittest.TestCase):
    """A shadow must never be able to disturb what it shadows."""

    class Exploding:
        def entities(self):
            raise RuntimeError("boom")

        def current_floor_id(self):
            raise RuntimeError("boom")

    def test_a_failing_shadow_source_does_not_raise(self):
        primary = StubPrimary([(0, "A", Position(0.0, 0.0, 0.0))])
        logger = Logger()
        reader = make_reader(primary, self.Exploding(), logger=logger)
        reader.poll_once()
        self.assertTrue(
            any("sample failed" in line for line in logger.debug_lines))

    def test_a_failing_primary_source_does_not_raise(self):
        shadow, _, _ = make_shadow([fx.Character(res_id=0)])
        logger = Logger()
        reader = make_reader(self.Exploding(), shadow, logger=logger)
        reader.poll_once()
        self.assertTrue(
            any("sample failed" in line for line in logger.debug_lines))

    def test_a_failure_still_consumes_the_interval(self):
        clock = Clock()
        primary = StubPrimary([(0, "A", Position(0.0, 0.0, 0.0))])
        reader = make_reader(
            primary, self.Exploding(), clock=clock, logger=Logger())
        reader.poll_once()
        reader.poll_once()
        self.assertEqual(reader.samples, 0)
        self.assertGreater(reader.next_sample, clock.now)

    def test_the_reader_publishes_no_entities_of_its_own(self):
        shadow, _, _ = make_shadow([fx.Character(res_id=0)])
        reader = make_reader(StubPrimary([]), shadow)
        self.assertFalse(hasattr(reader, "entities"))


class ThrottleTests(unittest.TestCase):
    """`InteractionReadyReader` calls `entities()` on every source every
    tick, and the canonical source does a linear people-info search per
    actor. Sampling per tick would be a real performance regression."""

    def test_repeated_polls_inside_the_interval_sample_once(self):
        clock = Clock()
        shadow, _, _ = make_shadow([fx.Character(res_id=0)])
        primary = StubPrimary([(0, "A", Position(0.0, 0.0, 0.0))])
        reader = make_reader(primary, shadow, clock=clock)
        for _ in range(50):
            reader.poll_once()
        self.assertEqual(reader.samples, 1)
        self.assertEqual(primary.calls, 1)

    def test_a_sample_happens_once_the_interval_elapses(self):
        clock = Clock()
        shadow, _, _ = make_shadow([fx.Character(res_id=0)])
        primary = StubPrimary([(0, "A", Position(0.0, 0.0, 0.0))])
        reader = make_reader(primary, shadow, clock=clock)
        reader.poll_once()
        clock.advance(5.0)
        reader.poll_once()
        self.assertEqual(reader.samples, 2)

    def test_an_invalid_context_never_samples(self):
        shadow, _, _ = make_shadow([fx.Character(res_id=0)])
        primary = StubPrimary([(0, "A", Position(0.0, 0.0, 0.0))])
        reader = make_reader(primary, shadow)
        reader.poll_once(context_valid=False)
        self.assertEqual(reader.samples, 0)
        self.assertEqual(primary.calls, 0)

    def test_the_summary_line_is_not_repeated_while_it_is_unchanged(self):
        clock = Clock()
        shadow, _, _ = make_shadow([fx.Character(res_id=0)])
        primary = StubPrimary([(0, "A", Position(0.0, 0.0, 0.0))])
        logger = Logger()
        reader = make_reader(primary, shadow, clock=clock, logger=logger)
        for _ in range(4):
            reader.poll_once()
            clock.advance(5.0)
        summaries = [
            line for line in logger.info_lines if line.startswith("NPC SHADOW room=")
        ]
        self.assertEqual(len(summaries), 1)
        self.assertEqual(reader.samples, 4)

    def test_clear_resets_the_throttle_and_re_emits_the_summary(self):
        # A room change must produce a fresh summary even though the counts
        # happen to be identical -- otherwise the log silently implies the
        # player never left.
        clock = Clock()
        shadow, _, _ = make_shadow([fx.Character(res_id=0)])
        primary = StubPrimary([(0, "A", Position(0.0, 0.0, 0.0))])
        logger = Logger()
        reader = make_reader(primary, shadow, clock=clock, logger=logger)
        reader.poll_once()
        reader.clear("map changed")
        reader.poll_once()
        summaries = [
            line for line in logger.info_lines
            if line.startswith("NPC SHADOW room=")
        ]
        self.assertEqual(reader.samples, 2)
        self.assertEqual(len(summaries), 2)


class CorrelationTests(unittest.TestCase):
    def test_the_two_identity_shapes_correlate_on_their_trailing_element(self):
        # Old: ("npc", floor_id, index).  New: ("npc", groupID, resID).
        # resID IS the floor_character index, so the trailing element is the
        # only comparable part -- and mismatched middles must not split a
        # matched NPC into a primary-only plus a shadow-only.
        shadow, _, _ = make_shadow([fx.Character(res_id=3)])
        primary = StubPrimary([(3, "A", Position(0.0, 0.0, 0.0))])
        logger = Logger()
        reader = make_reader(primary, shadow, logger=logger)
        reader.poll_once()
        summary = next(
            line for line in logger.info_lines if "primary=" in line)
        self.assertIn("both=1", summary)
        self.assertIn("primary_only=0", summary)
        self.assertIn("shadow_only=0", summary)


if __name__ == "__main__":
    unittest.main()
