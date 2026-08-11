import logging
import math
import struct
import unittest

from battle_narrator.entities import Entity
from battle_narrator.entity_nav import NavState
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.phase1b_lifecycle import LifecycleController
from battle_narrator.teleport import (
    INVALID_POSITION_MESSAGE,
    NO_SELECTION_MESSAGE,
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
