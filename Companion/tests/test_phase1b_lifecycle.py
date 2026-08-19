import io
import logging
import unittest

from battle_narrator.memory import MemoryError, MemoryReader
from battle_narrator.messages import LocalDataError
from battle_narrator.phase1b_connection import (
    ConnectionError,
    PersistentDolphinConnection,
    ProfileNotReady,
    UnsupportedProfile,
)
from battle_narrator.phase1b_lifecycle import (
    LifecycleController,
    LifecycleState,
)
from battle_narrator.phase1b_tasks import (
    GSmsgUnavailable,
    MalformedGSmsg,
    PersistentGSmsgTasks,
)
from battle_narrator.profile import XD_US_REV0


def be16(value):
    return value.to_bytes(2, "big")


def be32(value):
    return value.to_bytes(4, "big")


class MemoryBackend:
    def __init__(self):
        self.data = {}
        self.hooked = True

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(
            self.data.get(address + offset, 0) for offset in range(size)
        )

    def hook(self):
        return None

    def is_hooked(self):
        return self.hooked

    def get_status(self):
        return 2

    def un_hook(self):
        self.hooked = False


class FakeConnection:
    def __init__(self, present=True, profile="valid"):
        self.present = present
        self.readable = present
        self.profile = profile
        self.closed = 0

    def hook(self):
        if not self.present:
            raise ConnectionError("Dolphin absent")
        self.readable = True

    def verify_profile(self):
        if self.profile == "pending":
            raise ProfileNotReady("pending")
        if self.profile == "unsupported":
            raise UnsupportedProfile("unsupported")
        if self.profile == "read_failure":
            raise MemoryError("temporary header read failure")

    def is_readable(self):
        return self.readable

    def close(self):
        self.closed += 1
        self.readable = False


class FakeTasks:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def resolve(self):
        outcome = self.outcomes.pop(0) if self.outcomes else "valid"
        if isinstance(outcome, Exception):
            raise outcome
        return 1, 2, 3


class FakeNarrator:
    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.stop_requested = False
        self.samples = {"stale signature"}

    def poll_once(self):
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome


class FakeSpeaker:
    def __init__(self):
        self.spoken = []

    def speak(self, text, interrupt=False):
        self.spoken.append(text)
        return True


def test_logger():
    logger = logging.getLogger(f"phase1b-{id(object())}")
    logger.handlers.clear()
    logger.addHandler(logging.StreamHandler(io.StringIO()))
    logger.setLevel(logging.DEBUG)
    return logger


class TaskClassificationTests(unittest.TestCase):
    def configured(self, manager=0x80002000, capacity=2, tasks=0x80003000):
        backend = MemoryBackend()
        backend.put(XD_US_REV0.manager_root, be32(manager))
        if manager:
            backend.put(manager, be16(capacity))
            backend.put(
                manager + XD_US_REV0.manager_tasks_offset, be32(tasks)
            )
        return backend, PersistentGSmsgTasks(
            MemoryReader(backend, XD_US_REV0), XD_US_REV0
        )

    def test_null_manager_waits(self):
        _, tasks = self.configured(manager=0)
        with self.assertRaises(GSmsgUnavailable):
            tasks.resolve()

    def test_zero_capacity_waits_then_two_activates(self):
        backend, tasks = self.configured(capacity=0)
        with self.assertRaises(GSmsgUnavailable):
            tasks.resolve()
        manager = int.from_bytes(
            backend.read_bytes(XD_US_REV0.manager_root, 4), "big"
        )
        backend.put(manager, be16(2))
        self.assertEqual(tasks.resolve()[1], 2)

    def test_null_task_array_waits(self):
        _, tasks = self.configured(tasks=0)
        with self.assertRaises(GSmsgUnavailable):
            tasks.resolve()

    def test_malformed_nonzero_capacity_stops(self):
        _, tasks = self.configured(capacity=99)
        with self.assertRaises(MalformedGSmsg):
            tasks.resolve()

    def test_invalid_nonnull_manager_stops(self):
        _, tasks = self.configured(manager=0x70000000)
        with self.assertRaises(MalformedGSmsg):
            tasks.resolve()

    def test_invalid_nonnull_task_array_stops(self):
        _, tasks = self.configured(tasks=0x90000000)
        with self.assertRaises(MalformedGSmsg):
            tasks.resolve()


class ConnectionTests(unittest.TestCase):
    """Compatibility is decided by the engine's own code, not the disc
    label. That is what lets XG -- a hack of the US release that relabels
    the disc but does not move the engine -- run on the US profile, while
    still refusing a genuinely different build."""

    def engine(self, backend, profile=XD_US_REV0, corrupt=None):
        """Write the bytes a real, matching build would have."""
        for name, address, expected in profile.engine_signatures:
            backend.put(address,
                        bytes(len(expected)) if name == corrupt else expected)

    def connected(self, backend):
        connection = PersistentDolphinConnection(backend, XD_US_REV0)
        connection.hook()
        return connection

    def test_profile_pending_until_the_disc_header_appears(self):
        backend = MemoryBackend()
        connection = self.connected(backend)
        with self.assertRaises(ProfileNotReady):
            connection.verify_profile()

    def test_profile_pending_while_code_is_still_loading(self):
        # Disc header present but the DOL's .text not yet copied into MEM1.
        # This MUST be retryable: treating a mid-boot attach as "wrong game"
        # would make the narrator refuse to start whenever it hooked a
        # moment too early.
        backend = MemoryBackend()
        backend.put(0x80000000, b"GXXE01\0\0")
        connection = self.connected(backend)
        with self.assertRaises(ProfileNotReady):
            connection.verify_profile()

    def test_matching_engine_is_accepted(self):
        backend = MemoryBackend()
        backend.put(0x80000000, b"GXXE01\0\0")
        self.engine(backend)
        self.assertEqual(
            self.connected(backend).verify_profile(), ("GXXE01", 0))

    def test_relabelled_disc_with_a_matching_engine_is_accepted(self):
        # The XG case, and the whole point of the change: a different game
        # id and revision, but the engine our addresses target.
        backend = MemoryBackend()
        backend.put(0x80000000, b"GXGE01\0\3")
        self.engine(backend)
        self.assertEqual(
            self.connected(backend).verify_profile(), ("GXGE01", 3))

    def test_matching_label_with_a_wrong_engine_is_refused(self):
        # The failure the old label check could not catch at all.
        backend = MemoryBackend()
        backend.put(0x80000000, b"GXXE01\0\0")
        self.engine(backend)
        name, address, expected = XD_US_REV0.engine_signatures[2]
        backend.put(address, bytes([0x60] * len(expected)))
        with self.assertRaises(UnsupportedProfile) as caught:
            self.connected(backend).verify_profile()
        self.assertIn(name, str(caught.exception))
        self.assertIn(f"0x{address:08X}", str(caught.exception))

    def test_a_partially_loaded_engine_is_not_mistaken_for_ready(self):
        # One signature zeroed while the rest match is NOT "still booting"
        # -- booting zeroes all of them. Refusing is right.
        backend = MemoryBackend()
        backend.put(0x80000000, b"GXXE01\0\0")
        self.engine(backend, corrupt=XD_US_REV0.engine_signatures[0][0])
        with self.assertRaises(UnsupportedProfile):
            self.connected(backend).verify_profile()

    def test_every_signature_is_checked(self):
        # Each one independently gates, so none can silently rot.
        for name, address, expected in XD_US_REV0.engine_signatures:
            backend = MemoryBackend()
            backend.put(0x80000000, b"GXXE01\0\0")
            self.engine(backend)
            backend.put(address, bytes([0x60] * len(expected)))
            with self.assertRaises(UnsupportedProfile, msg=name):
                self.connected(backend).verify_profile()

    def test_signatures_cover_every_subsystem_the_narrator_reads(self):
        # A regression guard on the profile itself: if someone adds a
        # subsystem's addresses without a signature, a build that moved
        # only that subsystem would pass verification and misread it.
        names = {name for name, _, _ in XD_US_REV0.engine_signatures}
        self.assertGreaterEqual(len(names), 8)
        self.assertEqual(len(names), len(XD_US_REV0.engine_signatures))
        for expected_area in ("msgctrlPokemon", "GSmsgSetCtrlFunc",
                              "zokuseiBiosGetWazaJoutai",
                              "relivehallTempoToLevel",
                              "CReliveHall::getStage",
                              "pcboxGetNbPokemonBox",
                              "Pokemon::getPokemonDataId",
                              "savedataGetStatus"):
            self.assertIn(expected_area, names)

    def test_signature_addresses_are_all_in_mem1(self):
        for name, address, expected in XD_US_REV0.engine_signatures:
            self.assertTrue(
                XD_US_REV0.mem1_start <= address < XD_US_REV0.mem1_end, name)
            self.assertTrue(expected, name)
            self.assertEqual(len(expected) % 4, 0, name)


class LifecycleTests(unittest.TestCase):
    def controller(
        self,
        connection,
        task_objects,
        narrator_objects=None,
    ):
        speaker = FakeSpeaker()
        tasks = list(task_objects)
        narrators = list(narrator_objects or [FakeNarrator()])

        def tasks_factory():
            return tasks.pop(0)

        def narrator_factory(_tasks):
            return narrators.pop(0)

        controller = LifecycleController(
            connection,
            tasks_factory,
            narrator_factory,
            speaker,
            test_logger(),
            waiting_interval=0,
            active_interval=0,
        )
        return controller, speaker

    def test_absent_at_start_then_appears(self):
        connection = FakeConnection(present=False)
        controller, speaker = self.controller(
            connection, [FakeTasks(["valid"])]
        )
        controller.step()
        self.assertEqual(controller.state, LifecycleState.DOLPHIN_ABSENT)
        self.assertEqual(speaker.spoken, [])
        connection.present = True
        controller.step()
        self.assertEqual(controller.state, LifecycleState.ACTIVE)
        self.assertEqual(
            speaker.spoken,
            ["Battle narrator connected.", "Battle narration ready."],
        )

    def test_capacity_zero_waits_quietly_then_activates(self):
        controller, speaker = self.controller(
            FakeConnection(),
            [FakeTasks([GSmsgUnavailable("zero"), "valid"])],
        )
        controller.step()
        self.assertEqual(controller.state, LifecycleState.GSMSG_WAITING)
        controller.step()
        self.assertEqual(controller.state, LifecycleState.ACTIVE)
        self.assertEqual(speaker.spoken.count("Battle narration ready."), 1)

    def test_battle_end_and_later_reinitialization_clear_state(self):
        first = FakeNarrator([GSmsgUnavailable("battle ended")])
        second = FakeNarrator()
        controller, speaker = self.controller(
            FakeConnection(),
            [FakeTasks(["valid"]), FakeTasks(["valid"])],
            [first, second],
        )
        controller.step()
        self.assertIs(controller.narrator, first)
        controller.step()
        self.assertEqual(controller.state, LifecycleState.GSMSG_WAITING)
        self.assertIsNone(controller.narrator)
        controller.step()
        self.assertIs(controller.narrator, second)
        self.assertNotIn("stale signature", second.samples - {"stale signature"})
        self.assertEqual(speaker.spoken.count("Battle narration ready."), 1)

    def test_temporary_wait_read_failure_recovers(self):
        controller, _ = self.controller(
            FakeConnection(),
            [FakeTasks([MemoryError("temporary"), "valid"])],
        )
        controller.step()
        self.assertEqual(controller.state, LifecycleState.GSMSG_WAITING)
        controller.step()
        self.assertEqual(controller.state, LifecycleState.ACTIVE)

    def test_continuous_disconnect_announces_once(self):
        connection = FakeConnection()
        controller, speaker = self.controller(
            connection, [FakeTasks(["valid"])]
        )
        controller.step()
        connection.readable = False
        connection.present = False
        controller.step()
        controller.step()
        controller.step()
        self.assertEqual(
            speaker.spoken.count("Battle narrator disconnected."), 1
        )

    def test_reconnect_announces_new_connection_once(self):
        connection = FakeConnection()
        controller, speaker = self.controller(
            connection,
            [FakeTasks(["valid"]), FakeTasks(["valid"])],
            [FakeNarrator(), FakeNarrator()],
        )
        controller.step()
        connection.readable = False
        connection.present = False
        controller.step()
        connection.present = True
        controller.step()
        self.assertEqual(
            speaker.spoken.count("Battle narrator connected."), 2
        )
        self.assertEqual(
            speaker.spoken.count("Battle narrator disconnected."), 1
        )

    def test_unsupported_profile_is_conclusive(self):
        controller, _ = self.controller(
            FakeConnection(profile="unsupported"),
            [FakeTasks(["valid"])],
        )
        with self.assertRaises(UnsupportedProfile):
            controller.step()

    def test_clean_requested_shutdown(self):
        controller, speaker = self.controller(
            FakeConnection(), [FakeTasks(["valid"])]
        )
        controller.stop_requested = True
        controller.step()
        self.assertEqual(controller.state, LifecycleState.SHUTDOWN)
        self.assertEqual(speaker.spoken, [])


class BeaconSilencingTests(unittest.TestCase):
    """Every non-speech cue holds its tongue while the player is listening
    to speech -- a conversation, or the settings menu.

    The settings menu half was the project owner's request, 2026-08-18, and
    the Sound library heading makes it acute: that screen exists to play
    cues one at a time so they can be told apart, and the ambient beacons
    were playing over it.
    """

    class Dialogue:
        def __init__(self, active=False):
            self.active = active

    class Menu:
        def __init__(self, open=False):
            self.open = open
            self.controller = None

    class Beacons:
        def __init__(self):
            self.polls = 0
            self.suppressions = 0

        def poll_once(self):
            self.polls += 1

        def suppress_for_dialogue(self):
            self.suppressions += 1

        def clear(self, reason):
            pass

    class Guide:
        def __init__(self):
            self.calls = []

        def poll_once(self, silenced=False):
            self.calls.append(silenced)

        def clear(self, reason):
            pass

    def _controller(self, dialogue=None, menu=None):
        log = logging.getLogger("lifecycle-beacon-silencing-test")
        log.addHandler(logging.NullHandler())
        controller = LifecycleController(
            connection=None, tasks_factory=lambda: None,
            narrator_factory=lambda: None, speaker=None, logger=log,
            settings_menu=menu)
        controller.dialogue_reader = dialogue
        controller.npc_sound_reader = self.Beacons()
        controller.audio_guide_reader = self.Guide()
        return controller

    def test_nothing_is_silenced_when_neither_is_open(self):
        controller = self._controller(
            dialogue=self.Dialogue(False), menu=self.Menu(False))
        self.assertFalse(controller._beacons_silenced())
        controller.poll_npc_sounds()
        controller.poll_audio_guide()
        self.assertEqual(controller.npc_sound_reader.polls, 1)
        self.assertEqual(controller.npc_sound_reader.suppressions, 0)
        self.assertEqual(controller.audio_guide_reader.calls, [False])

    def test_an_open_settings_menu_silences_the_passive_beacons(self):
        controller = self._controller(
            dialogue=self.Dialogue(False), menu=self.Menu(True))
        self.assertTrue(controller._beacons_silenced())
        controller.poll_npc_sounds()
        self.assertEqual(controller.npc_sound_reader.polls, 0)
        self.assertEqual(controller.npc_sound_reader.suppressions, 1)

    def test_an_open_settings_menu_silences_the_guide(self):
        controller = self._controller(
            dialogue=self.Dialogue(False), menu=self.Menu(True))
        controller.poll_audio_guide()
        self.assertEqual(controller.audio_guide_reader.calls, [True])

    def test_a_conversation_still_silences_both(self):
        controller = self._controller(
            dialogue=self.Dialogue(True), menu=self.Menu(False))
        self.assertTrue(controller._beacons_silenced())
        controller.poll_npc_sounds()
        controller.poll_audio_guide()
        self.assertEqual(controller.npc_sound_reader.suppressions, 1)
        self.assertEqual(controller.audio_guide_reader.calls, [True])

    def test_closing_the_menu_lets_them_speak_again(self):
        menu = self.Menu(True)
        controller = self._controller(
            dialogue=self.Dialogue(False), menu=menu)
        controller.poll_npc_sounds()
        controller.poll_audio_guide()
        menu.open = False
        controller.poll_npc_sounds()
        controller.poll_audio_guide()
        self.assertEqual(controller.npc_sound_reader.polls, 1)
        self.assertEqual(controller.audio_guide_reader.calls, [True, False])

    def test_no_settings_menu_at_all_is_not_treated_as_open(self):
        # `--no-settings-menu` leaves it None. Reading `.open` off None
        # would take the beacons out entirely.
        controller = self._controller(dialogue=self.Dialogue(False), menu=None)
        self.assertFalse(controller._beacons_silenced())

    def test_no_dialogue_reader_at_all_is_not_treated_as_active(self):
        controller = self._controller(dialogue=None, menu=self.Menu(False))
        self.assertFalse(controller._beacons_silenced())


class OptionalReaderFailureTests(unittest.TestCase):
    """One unreadable local data file must not kill the whole narrator.

    Live-caught 2026-08-12: `pda_menu.fsys` holds an entry whose LZSS header
    reads `7f 00 53 53`, `PdaCatalog` raised `LocalDataError`, nothing caught
    it before `main`, and the narrator exited 1 about a second after
    announcing itself -- three times in 61 seconds. Battle narration, menus,
    dialogue and navigation were all lost to the PDA."""

    def _controller(self, **factories):
        log = logging.getLogger("lifecycle-optional-reader-test")
        log.addHandler(logging.NullHandler())
        return LifecycleController(
            connection=None, tasks_factory=lambda: None,
            narrator_factory=lambda: None, speaker=None, logger=log,
            **factories)

    def test_a_bad_local_catalog_disables_only_its_own_reader(self):
        def broken():
            raise LocalDataError("Invalid LZSS magic: b'\\x7f\\x00SS'")

        controller = self._controller(
            pda_factory=broken,
            menu_factory=lambda: "menu",
            dialogue_factory=lambda: "dialogue")
        self.assertIsNone(controller._build(controller.pda_factory, "pda"))
        self.assertEqual(
            controller._build(controller.menu_factory, "menu"), "menu")
        self.assertEqual(
            controller._build(controller.dialogue_factory, "dialogue"),
            "dialogue")

    def test_a_missing_factory_is_still_just_none(self):
        controller = self._controller()
        self.assertIsNone(controller._build(None, "absent"))

    def test_other_failures_still_propagate(self):
        """Scoped to LocalDataError deliberately. A reader failing for a
        reason that is not about its own data is a real defect and must stay
        loud rather than silently disabling a feature."""
        def exploding():
            raise ValueError("this is a bug, not a bad file")

        controller = self._controller(menu_factory=exploding)
        with self.assertRaises(ValueError):
            controller._build(controller.menu_factory, "menu")


if __name__ == "__main__":
    unittest.main()
