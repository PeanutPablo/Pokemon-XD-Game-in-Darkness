import unittest

from battle_narrator.phase1b_lifecycle import (
    LifecycleController,
    LifecycleState,
)
from battle_narrator.phase1b_tasks import GSmsgUnavailable
from test_phase1b_lifecycle import (
    FakeConnection,
    FakeNarrator,
    FakeSpeaker,
    FakeTasks,
    test_logger,
)


class ShutdownAndResetTests(unittest.TestCase):
    def test_stale_runtime_object_is_discarded_between_battles(self):
        speaker = FakeSpeaker()
        task_objects = [FakeTasks(["valid"]), FakeTasks(["valid"])]
        first = FakeNarrator([GSmsgUnavailable("battle ended")])
        first.samples.add("old battle signature")
        second = FakeNarrator()
        narrators = [first, second]

        controller = LifecycleController(
            FakeConnection(),
            lambda: task_objects.pop(0),
            lambda _tasks: narrators.pop(0),
            speaker,
            test_logger(),
            waiting_interval=0,
            active_interval=0,
        )
        controller.step()
        controller.step()
        self.assertIsNone(controller.narrator)
        controller.step()
        self.assertIs(controller.narrator, second)
        self.assertNotIn("old battle signature", second.samples)

    def test_keyboard_interrupt_is_clean_shutdown(self):
        speaker = FakeSpeaker()
        controller = LifecycleController(
            FakeConnection(),
            lambda: FakeTasks(["valid"]),
            lambda _tasks: FakeNarrator(),
            speaker,
            test_logger(),
            waiting_interval=0,
            active_interval=0,
        )

        def interrupt():
            raise KeyboardInterrupt

        controller.step = interrupt
        controller.run()
        self.assertEqual(controller.state, LifecycleState.SHUTDOWN)
        self.assertEqual(speaker.spoken, [])


if __name__ == "__main__":
    unittest.main()
