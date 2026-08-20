import logging
import math
import struct
import unittest

from battle_narrator.entities import Entity
from battle_narrator.entity_nav import NavState
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.phase1b_lifecycle import LifecycleController
from battle_narrator.memory import MemoryError as GameMemoryError
from battle_narrator.teleport import (
    DID_NOT_TAKE_MESSAGE,
    INVALID_POSITION_MESSAGE,
    NO_SELECTION_MESSAGE,
    UNREADABLE_MESSAGE,
    VERIFY_AFTER_SECONDS,
    TeleportReader,
)


class Hotkey:
    def __init__(self):
        self.fire = False

    def poll(self):
        result = self.fire
        self.fire = False
        return result


class Speech:
    def __init__(self):
        self.calls = []

    def emit(self, event, text, deduplicate=False, interrupt=False):
        self.calls.append(text)


class FakeMemory:
    def __init__(self):
        self.writes = []

    def write_bytes(self, address, data, label="memory", alignment=1):
        self.writes.append((address, data))


class FakeProfile:
    model_position_offset = 0x18


class FakeNpcSource:
    def __init__(self, pose, model_address=0x80500000):
        self.pose = pose
        self.model_address = model_address

    def player_pose(self):
        return self.pose

    def hero_model_address(self):
        return self.model_address


class Source:
    def __init__(self, entities, pose=None):
        self.items = entities
        self.pose = pose or PlayerPose(Position(0, 0, 0), 0)

    def entities(self):
        return list(self.items)

    def player_pose(self):
        return self.pose


class FakeEntityNav:
    def __init__(self, sources, category_key=None, selected_identity=None):
        self.sources = sources
        self.state = NavState(category_key=category_key, selected_identity=selected_identity)


def entity(category, identity="e1", x=10.0, y=5.0, z=-3.0, label="Thing"):
    return Entity(category=category, identity=identity, label=label, position=Position(x, y, z))


class TeleportReaderTests(unittest.TestCase):
    def setUp(self):
        self.memory = FakeMemory()
        self.profile = FakeProfile()
        self.hotkey = Hotkey()
        self.speech = Speech()

    def _reader(self, entity_nav, npc_source):
        return TeleportReader(
            self.memory, self.profile, npc_source, entity_nav,
            self.hotkey, self.speech, logging.getLogger("teleport-test"),
        )

    def test_no_selection_announces_and_writes_nothing(self):
        nav = FakeEntityNav({"npc": Source([])})
        npc_source = FakeNpcSource(PlayerPose(Position(0, 0, 0), 0))
        reader = self._reader(nav, npc_source)
        self.hotkey.fire = True
        reader.poll_once()
        self.assertEqual(self.memory.writes, [])
        self.assertIn(NO_SELECTION_MESSAGE, self.speech.calls)

    def test_npc_category_stops_short_of_collision(self):
        target = entity("npc", x=11.0, y=6.0, z=-9.0)
        source = Source([target])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        npc_source = FakeNpcSource(PlayerPose(Position(0, 0, 0), 0), model_address=0x80500000)
        reader = self._reader(nav, npc_source)
        self.hotkey.fire = True
        reader.poll_once()
        self.assertEqual(len(self.memory.writes), 1)
        address, data = self.memory.writes[0]
        self.assertEqual(address, 0x80500000 + 0x18)
        x, y, z = struct.unpack(">fff", data)
        # Ground-level Y is preserved from the NPC's own live-read position.
        self.assertAlmostEqual(y, 6.0, places=4)
        # Landing point is NOT the NPC's exact coordinates (that would be
        # inside its collision) -- it's closer to the player than the NPC
        # itself, along the same line.
        distance_to_npc = math.hypot(x - 11.0, z - (-9.0))
        distance_to_player = math.hypot(x - 0.0, z - 0.0)
        self.assertGreater(distance_to_npc, 0.5)
        self.assertLess(distance_to_player, math.hypot(11.0, -9.0))
        self.assertIn("Teleported to Thing.", self.speech.calls)

    def test_npc_approach_buffer_scales_with_interaction_distance(self):
        target = Entity(
            category="npc", identity="e1", label="Big",
            position=Position(20.0, 0.0, 0.0), interaction_distance=10.0,
        )
        source = Source([target])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        npc_source = FakeNpcSource(PlayerPose(Position(0, 0, 0), 0))
        reader = self._reader(nav, npc_source)
        self.hotkey.fire = True
        reader.poll_once()
        _, data = self.memory.writes[0]
        x, y, z = struct.unpack(">fff", data)
        # Buffer is 80% of interaction_distance (10.0) = 8.0 short of the NPC.
        self.assertAlmostEqual(x, 20.0 - 8.0, places=3)
        self.assertAlmostEqual(z, 0.0, places=3)

    def test_npc_already_at_same_position_nudges_back(self):
        target = entity("npc", x=5.0, y=0.0, z=5.0)
        source = Source([target])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        npc_source = FakeNpcSource(PlayerPose(Position(5.0, 0.0, 5.0), 0))
        reader = self._reader(nav, npc_source)
        self.hotkey.fire = True
        reader.poll_once()
        _, data = self.memory.writes[0]
        x, y, z = struct.unpack(">fff", data)
        self.assertNotEqual((x, z), (5.0, 5.0))

    def test_non_npc_category_uses_player_y_not_entity_y(self):
        target = entity("door", x=20.0, y=15.0, z=-40.0)
        source = Source([target])
        nav = FakeEntityNav({"door": source}, category_key="door", selected_identity="e1")
        npc_source = FakeNpcSource(PlayerPose(Position(1.0, 0.5, 2.0), 0))
        reader = self._reader(nav, npc_source)
        self.hotkey.fire = True
        reader.poll_once()
        address, data = self.memory.writes[0]
        x, y, z = struct.unpack(">fff", data)
        self.assertEqual((x, y, z), (20.0, 0.5, -40.0))

    def test_selected_entity_no_longer_available_announces_and_writes_nothing(self):
        nav = FakeEntityNav({"npc": Source([])}, category_key="npc", selected_identity="gone")
        npc_source = FakeNpcSource(PlayerPose(Position(0, 0, 0), 0))
        reader = self._reader(nav, npc_source)
        self.hotkey.fire = True
        reader.poll_once()
        self.assertEqual(self.memory.writes, [])
        self.assertIn(NO_SELECTION_MESSAGE, self.speech.calls)

    def test_inactive_without_hotkey_does_nothing(self):
        target = entity("npc")
        source = Source([target])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        npc_source = FakeNpcSource(PlayerPose(Position(0, 0, 0), 0))
        reader = self._reader(nav, npc_source)
        reader.poll_once()
        self.assertEqual(self.memory.writes, [])
        self.assertEqual(self.speech.calls, [])

    def test_non_finite_target_is_rejected(self):
        target = entity("npc", x=float("nan"))
        source = Source([target])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        npc_source = FakeNpcSource(PlayerPose(Position(0, 0, 0), 0))
        reader = self._reader(nav, npc_source)
        self.hotkey.fire = True
        reader.poll_once()
        self.assertEqual(self.memory.writes, [])
        self.assertIn(INVALID_POSITION_MESSAGE, self.speech.calls)

    def test_lifecycle_accepts_teleport_factory(self):
        factory = lambda entity_nav_reader: self._reader(
            FakeEntityNav({"npc": Source([])}), FakeNpcSource(PlayerPose(Position(0, 0, 0), 0)))
        controller = LifecycleController(
            object(), lambda: None, lambda tasks: None, object(),
            logging.getLogger("lifecycle-teleport-test"),
            teleport_factory=factory,
        )
        self.assertIs(controller.teleport_factory, factory)
        self.assertIsNone(controller.teleport_reader)


if __name__ == "__main__":
    unittest.main()


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def advance(self, dt):
        self.t += dt

    def __call__(self):
        return self.t


class MovableNpcSource(FakeNpcSource):
    """An npc source whose player can be put somewhere else afterwards --
    which is what the engine does when it rejects a landing."""

    def __init__(self, pose, model_address=0x80500000):
        super().__init__(pose, model_address)
        self.fail_model = False
        self.fail_pose = False

    def place_at(self, x, y, z):
        self.pose = PlayerPose(Position(x, y, z), self.pose.yaw)

    def player_pose(self):
        if self.fail_pose:
            raise GameMemoryError("player pose unreadable")
        return self.pose

    def hero_model_address(self):
        if self.fail_model:
            raise GameMemoryError("hero model resource 100 not found")
        return self.model_address


class TeleportVerificationTests(unittest.TestCase):
    """Whether the player actually ended up there -- the question this
    module never asked.

    It wrote the position, announced success and moved on. Every failure
    the module docstring itself describes (landing inside collision and
    being shoved back out; landing at a height the room does not have) was
    therefore reported to the player as a teleport that worked, which is
    what "it doesn't work all the time" sounds like from a chair.

    The check has to be DEFERRED. The write goes straight into MEM1, so
    reading the position back immediately returns the bytes just written
    and would confirm every teleport, including the ones that did nothing.
    Only after the engine has run a few frames does the position mean
    anything."""

    def setUp(self):
        self.memory = FakeMemory()
        self.profile = FakeProfile()
        self.hotkey = Hotkey()
        self.speech = Speech()
        self.clock = FakeClock()

    def reader(self, npc_source, category="exit"):
        target = entity(category, x=100.0, y=0.0, z=100.0)
        nav = FakeEntityNav(
            {category: Source([target])},
            category_key=category, selected_identity="e1")
        return TeleportReader(
            self.memory, self.profile, npc_source, nav, self.hotkey,
            self.speech, logging.getLogger("teleport-test"),
            clock=self.clock)

    def teleport(self, reader):
        self.hotkey.fire = True
        reader.poll_once()

    def test_a_landing_that_holds_says_nothing_further(self):
        source = MovableNpcSource(PlayerPose(Position(0, 0, 0), 0))
        reader = self.reader(source)
        self.teleport(reader)
        source.place_at(100.0, 0.0, 100.0)
        self.clock.advance(VERIFY_AFTER_SECONDS + 0.01)
        reader.poll_once()
        self.assertEqual(
            self.speech.calls, ["Teleported to Thing."],
            "an ordinary teleport must stay one sentence")

    def test_being_shoved_back_is_reported(self):
        source = MovableNpcSource(PlayerPose(Position(0, 0, 0), 0))
        reader = self.reader(source)
        self.teleport(reader)
        # The engine rejected it: the player is still where they started.
        self.clock.advance(VERIFY_AFTER_SECONDS + 0.01)
        reader.poll_once()
        self.assertIn(DID_NOT_TAKE_MESSAGE, self.speech.calls)

    def test_nothing_is_claimed_before_the_engine_has_had_its_frames(self):
        """An immediate check would read back our own write and pass."""
        source = MovableNpcSource(PlayerPose(Position(0, 0, 0), 0))
        reader = self.reader(source)
        self.teleport(reader)
        reader.poll_once()
        self.assertNotIn(DID_NOT_TAKE_MESSAGE, self.speech.calls)

    def test_a_small_engine_adjustment_still_counts_as_arrived(self):
        """Collision resolution and floor snapping move the landing a
        little; that is not a failure."""
        source = MovableNpcSource(PlayerPose(Position(0, 0, 0), 0))
        reader = self.reader(source)
        self.teleport(reader)
        source.place_at(102.0, 1.0, 101.0)
        self.clock.advance(VERIFY_AFTER_SECONDS + 0.01)
        reader.poll_once()
        self.assertNotIn(DID_NOT_TAKE_MESSAGE, self.speech.calls)

    def test_it_is_checked_once_not_every_tick(self):
        source = MovableNpcSource(PlayerPose(Position(0, 0, 0), 0))
        reader = self.reader(source)
        self.teleport(reader)
        self.clock.advance(VERIFY_AFTER_SECONDS + 0.01)
        for _ in range(5):
            reader.poll_once()
        self.assertEqual(self.speech.calls.count(DID_NOT_TAKE_MESSAGE), 1)

    def test_an_unverifiable_read_stays_quiet_rather_than_inventing_failure(self):
        source = MovableNpcSource(PlayerPose(Position(0, 0, 0), 0))
        reader = self.reader(source)
        self.teleport(reader)
        source.fail_pose = True
        self.clock.advance(VERIFY_AFTER_SECONDS + 0.01)
        reader.poll_once()
        self.assertNotIn(DID_NOT_TAKE_MESSAGE, self.speech.calls)

    def test_an_unreadable_hero_model_is_spoken_not_silent(self):
        """Before this the lifecycle caught the error, logged it at debug,
        and the player got nothing at all -- indistinguishable from the
        key not registering."""
        source = MovableNpcSource(PlayerPose(Position(0, 0, 0), 0))
        source.fail_model = True
        reader = self.reader(source)
        self.teleport(reader)
        self.assertIn(UNREADABLE_MESSAGE, self.speech.calls)
        self.assertEqual(self.memory.writes, [])


if __name__ == "__main__":
    unittest.main()
