"""The development-only interaction diagnostic.

Two properties matter most and are asserted first: it never synthesises
input, and it is absent unless explicitly enabled.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import people_fixture as fx
from battle_narrator.interaction_diagnostics import (
    DIALOGUE_WINDOW, InteractionDiagnostics,
)
from battle_narrator.model_parts import NeckPositionResolver
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.people_runtime import PeopleRuntimeSource
from battle_narrator.profile import XD_US_REV0


class Hotkey:
    def __init__(self):
        self.queued = []

    def fire(self):
        self.queued.append(True)

    def poll(self):
        return bool(self.queued) and self.queued.pop(0)


class Pose:
    def __init__(self, position=None, model=None):
        self.position = position or Position(0.0, 0.0, 0.0)
        self.model = model

    def player_pose(self):
        return PlayerPose(self.position, 0.0, 0.0)

    def hero_model_address(self):
        return self.model


class Logger:
    def __init__(self):
        self.info_lines = []
        self.debug_lines = []

    def info(self, template, *args):
        self.info_lines.append(template % args if args else template)

    def debug(self, template, *args):
        self.debug_lines.append(template % args if args else template)

    def warning(self, *args):
        pass


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def build(characters=None, selected=(fx.DEFAULT_GROUP, 0), dialogue=False,
          **kwargs):
    characters = characters or [fx.Character(res_id=0, name_id=0)]
    memory, backend = fx.build(characters, **kwargs)
    runtime = PeopleRuntimeSource(memory, XD_US_REV0)
    hotkey, logger, clock = Hotkey(), Logger(), Clock()
    state = {"dialogue": dialogue}
    reader = InteractionDiagnostics(
        memory, XD_US_REV0, runtime,
        NeckPositionResolver(memory, XD_US_REV0), Pose(),
        lambda: ("npc",) + selected if selected else None,
        hotkey, logger, dialogue_active=lambda: state["dialogue"],
        clock=clock)
    return reader, hotkey, logger, clock, state, backend


class SafetyTests(unittest.TestCase):
    def test_module_never_sends_input(self):
        source = (Path(__file__).parents[1] / "battle_narrator"
                  / "interaction_diagnostics.py").read_text(encoding="utf-8")
        for forbidden in ("press", "send_input", "keybd_event", "SendInput",
                          "write_bytes", "dme.write"):
            self.assertNotIn(f"{forbidden}(", source)

    def test_reader_is_absent_unless_enabled(self):
        from battle_narrator.phase1b_lifecycle import LifecycleController
        controller = LifecycleController.__new__(LifecycleController)
        controller.interaction_diagnostics_reader = None
        # poll must be a no-op with no factory configured.
        LifecycleController.poll_interaction_diagnostics(controller)


class SampleTests(unittest.TestCase):
    def test_sample_records_every_predicate_field(self):
        reader, _, logger, _, _, _ = build()
        reader.poll_once(room_code="M3_shop_1F")
        line = next(l for l in logger.info_lines if l.startswith("INTERACTION DIAG "))
        for field in ("identity=", "gen=", "work=", "group=", "res=", "info=",
                      "talk_sct=", "model=", "static=", "neck=", "hero=",
                      "dist3d=", "hero_ball=", "npc_ball=", "talk_live=",
                      "talk_static=", "threshold=", "flags=", "bit0=",
                      "disp=", "start_type=", "wall_through=",
                      "facing_error=", "ELIGIBLE=", "reason="):
            self.assertIn(field, line)

    def test_sampling_is_throttled(self):
        reader, _, logger, clock, _, _ = build()
        reader.poll_once()
        reader.poll_once()
        first = len([l for l in logger.info_lines if "INTERACTION DIAG " in l])
        clock.advance(1.0)
        reader.poll_once()
        second = len([l for l in logger.info_lines if "INTERACTION DIAG " in l])
        self.assertEqual(first, 1)
        self.assertEqual(second, 2)

    def test_no_selection_logs_nothing(self):
        reader, _, logger, _, _, _ = build(selected=None)
        reader.poll_once()
        self.assertEqual(logger.info_lines, [])

    def test_selection_with_no_live_actor_is_reported_on_a_mark(self):
        reader, hotkey, logger, _, _, _ = build(
            selected=(fx.DEFAULT_GROUP, 99))
        hotkey.fire()
        reader.poll_once()
        self.assertTrue(any("NOT_LIVE" in l for l in logger.info_lines))

    def test_navigator_agreement_is_logged_when_supplied(self):
        reader, _, logger, _, _, _ = build()
        reader.poll_once(announced_in_range=True)
        self.assertTrue(any("INTERACTION DIAG NAV" in l and "AGREE=" in l
                            for l in logger.info_lines))


class MarkTests(unittest.TestCase):
    def test_mark_records_the_prediction(self):
        reader, hotkey, logger, _, _, _ = build()
        hotkey.fire()
        reader.poll_once()
        self.assertTrue(any(l.startswith("INTERACTION MARK identity=")
                            and "predicted_eligible=" in l
                            for l in logger.info_lines))
        self.assertIsNotNone(reader.pending)

    def test_dialogue_opening_scores_the_mark(self):
        reader, hotkey, logger, clock, state, _ = build()
        hotkey.fire()
        reader.poll_once()
        predicted = reader.pending.predicted
        state["dialogue"] = True
        clock.advance(0.2)
        reader.poll_once()
        result = next(l for l in logger.info_lines
                      if "INTERACTION MARK RESULT" in l)
        self.assertIn("outcome=DIALOGUE_OPENED", result)
        self.assertIn(f"AGREES={predicted}", result)
        self.assertIsNone(reader.pending)

    def test_no_dialogue_within_the_window_scores_the_mark(self):
        reader, hotkey, logger, clock, _, _ = build(
            characters=[fx.Character(res_id=0,
                                     live_position=(400.0, 0.0, 400.0))])
        hotkey.fire()
        reader.poll_once()
        self.assertFalse(reader.pending.predicted)
        clock.advance(DIALOGUE_WINDOW + 0.1)
        reader.poll_once()
        result = next(l for l in logger.info_lines
                      if "INTERACTION MARK RESULT" in l)
        self.assertIn("outcome=NO_DIALOGUE", result)
        # Predicted ineligible and nothing happened -- the prediction agrees.
        self.assertIn("AGREES=True", result)

    def test_a_wrong_prediction_is_reported_as_disagreement(self):
        reader, hotkey, logger, clock, _, _ = build(
            characters=[fx.Character(res_id=0,
                                     live_position=(400.0, 0.0, 400.0))])
        hotkey.fire()
        reader.poll_once()
        reader.pending.predicted = True  # pretend we predicted eligible
        clock.advance(DIALOGUE_WINDOW + 0.1)
        reader.poll_once()
        result = next(l for l in logger.info_lines
                      if "INTERACTION MARK RESULT" in l)
        self.assertIn("AGREES=False", result)

    def test_clear_drops_a_pending_mark(self):
        reader, hotkey, _, _, _, _ = build()
        hotkey.fire()
        reader.poll_once()
        reader.clear("room changed")
        self.assertIsNone(reader.pending)


if __name__ == "__main__":
    unittest.main()
