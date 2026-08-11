import logging
import unittest

from battle_narrator.entities import Entity
from battle_narrator.interaction_announcer import InteractionAnnouncer
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.profile import XD_US_REV0


class FakeMemory:
    """Same two fixed addresses (floor id, window head) entity_nav's own
    fake reads -- see test_entity_nav.py's FakeMemory."""

    def __init__(self, floor_id=1, window_head=0):
        self.floor_id = floor_id
        self.window_head = window_head

    def u16(self, address, label=""):
        return self.floor_id

    def u32(self, address, label=""):
        return self.window_head


class FakeSource:
    def __init__(self, entities, pose):
        self._entities = entities
        self.pose = pose

    def entities(self):
        return list(self._entities)

    def player_pose(self):
        return self.pose


class Speech:
    def __init__(self):
        self.calls = []

    def emit(self, event, text, deduplicate=None, interrupt=None):
        self.calls.append(text)


def entity(category, x, z, y=0, label=None, interaction=None, index=0):
    return Entity(
        category=category,
        identity=(category, index),
        label=label,
        position=Position(x, y, z),
        interaction_distance=interaction,
    )


def pose(x=0, z=0, y=0, yaw=0):
    return PlayerPose(Position(x, y, z), yaw)


class InteractionAnnouncerTests(unittest.TestCase):
    def setUp(self):
        self.memory = FakeMemory(floor_id=1, window_head=0)
        self.speech = Speech()

    def _make(self, sources):
        return InteractionAnnouncer(
            self.memory, XD_US_REV0, sources, self.speech,
            logging.getLogger("interaction-announcer-test"))

    def test_no_announcement_while_nothing_changes(self):
        npc = entity("npc", 0, 5, label="NPC D", interaction=3)
        sources = {"npc": FakeSource([npc], pose())}
        announcer = self._make(sources)
        announcer.poll_once()
        announcer.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_npc_talk_announced_when_window_opens_nearby(self):
        npc = entity("npc", 0, 2, label="NPC D", interaction=3)
        sources = {"npc": FakeSource([npc], pose())}
        announcer = self._make(sources)
        announcer.poll_once()  # baseline: free-roaming
        self.memory.window_head = 0x80700000  # a window just opened
        announcer.poll_once()
        self.assertIn("Talked to NPC D.", self.speech.calls)

    def test_no_announcement_if_nothing_is_close_enough(self):
        npc = entity("npc", 0, 50, label="NPC D", interaction=3)
        sources = {"npc": FakeSource([npc], pose())}
        announcer = self._make(sources)
        announcer.poll_once()
        self.memory.window_head = 0x80700000
        announcer.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_door_or_warp_categories_use_default_trigger_radius(self):
        door = entity("door", 0, 5, label="Door")  # no interaction_distance
        sources = {"door": FakeSource([door], pose())}
        announcer = InteractionAnnouncer(
            self.memory, XD_US_REV0, sources, self.speech,
            logging.getLogger("interaction-announcer-test"),
            default_trigger_radius=10.0,
        )
        announcer.poll_once()
        self.memory.floor_id = 2  # room changed
        announcer.poll_once()
        self.assertIn("Opened Door.", self.speech.calls)

    def test_door_beyond_default_trigger_radius_not_announced(self):
        door = entity("door", 0, 50, label="Door")
        sources = {"door": FakeSource([door], pose())}
        announcer = InteractionAnnouncer(
            self.memory, XD_US_REV0, sources, self.speech,
            logging.getLogger("interaction-announcer-test"),
            default_trigger_radius=10.0,
        )
        announcer.poll_once()
        self.memory.floor_id = 2
        announcer.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_floor_change_uses_position_from_before_the_transition(self):
        # The player's position after a floor change is in the new room
        # and useless for identifying the trigger -- the cached,
        # pre-transition pose must be used instead.
        warp = entity("warp", 0, 5, label="to M6_shop_1F")
        source = FakeSource([warp], pose(x=0, z=5))
        sources = {"warp": source}
        announcer = InteractionAnnouncer(
            self.memory, XD_US_REV0, sources, self.speech,
            logging.getLogger("interaction-announcer-test"),
            default_trigger_radius=10.0,
        )
        announcer.poll_once()  # caches pose near the warp
        source.pose = pose(x=500, z=500)  # now in a totally different room
        self.memory.floor_id = 2
        announcer.poll_once()
        self.assertIn("Entered to M6_shop_1F.", self.speech.calls)

    def test_elevator_uses_default_radius_and_verb(self):
        elevator = entity("elevator", 0, 3, label="Elevator to M5_apart_1F")
        sources = {"elevator": FakeSource([elevator], pose())}
        announcer = InteractionAnnouncer(
            self.memory, XD_US_REV0, sources, self.speech,
            logging.getLogger("interaction-announcer-test"),
            default_trigger_radius=10.0,
        )
        announcer.poll_once()
        self.memory.floor_id = 2
        announcer.poll_once()
        self.assertIn("Used Elevator to M5_apart_1F.", self.speech.calls)

    def test_pc_use_announced_on_window_open(self):
        pc = entity("pc", 0, 2, label="PC")
        sources = {"pc": FakeSource([pc], pose())}
        announcer = InteractionAnnouncer(
            self.memory, XD_US_REV0, sources, self.speech,
            logging.getLogger("interaction-announcer-test"),
            default_trigger_radius=10.0,
        )
        announcer.poll_once()
        self.memory.window_head = 0x80700000
        announcer.poll_once()
        self.assertIn("Used PC.", self.speech.calls)

    def test_sign_read_announced_on_window_open(self):
        sign = entity("sign", 0, 2, label="Sign")
        sources = {"sign": FakeSource([sign], pose())}
        announcer = InteractionAnnouncer(
            self.memory, XD_US_REV0, sources, self.speech,
            logging.getLogger("interaction-announcer-test"),
            default_trigger_radius=10.0,
        )
        announcer.poll_once()
        self.memory.window_head = 0x80700000
        announcer.poll_once()
        self.assertIn("Read Sign.", self.speech.calls)

    def test_dialogue_active_flag_also_counts_as_control_lost(self):
        npc = entity("npc", 0, 2, label="NPC D", interaction=3)
        sources = {"npc": FakeSource([npc], pose())}
        announcer = self._make(sources)
        announcer.poll_once(dialogue_active=False)
        announcer.poll_once(dialogue_active=True)
        self.assertIn("Talked to NPC D.", self.speech.calls)

    def test_missing_label_falls_back_without_crashing(self):
        npc = entity("npc", 0, 2, label=None, interaction=3)
        sources = {"npc": FakeSource([npc], pose())}
        announcer = self._make(sources)
        announcer.poll_once()
        self.memory.window_head = 0x80700000
        announcer.poll_once()
        self.assertIn("Talked to something.", self.speech.calls)

    def test_reopening_a_window_does_not_reannounce_without_a_new_transition(self):
        npc = entity("npc", 0, 2, label="NPC D", interaction=3)
        sources = {"npc": FakeSource([npc], pose())}
        announcer = self._make(sources)
        announcer.poll_once()
        self.memory.window_head = 0x80700000
        announcer.poll_once()
        announcer.poll_once()  # window still open, no new transition
        self.assertEqual(self.speech.calls.count("Talked to NPC D."), 1)

    def test_clear_resets_state_for_a_fresh_announcement_next_time(self):
        npc = entity("npc", 0, 2, label="NPC D", interaction=3)
        sources = {"npc": FakeSource([npc], pose())}
        announcer = self._make(sources)
        announcer.poll_once()
        self.memory.window_head = 0x80700000
        announcer.poll_once()
        announcer.clear("reconnect")
        self.memory.window_head = 0
        announcer.poll_once()
        self.memory.window_head = 0x80700000
        announcer.poll_once()
        self.assertEqual(self.speech.calls.count("Talked to NPC D."), 2)

    def test_multiple_categories_pick_the_closest_one(self):
        far_npc = entity("npc", 0, 8, label="Far NPC", interaction=9)
        near_pc = entity("pc", 0, 2, label="PC")
        sources = {
            "npc": FakeSource([far_npc], pose()),
            "pc": FakeSource([near_pc], pose()),
        }
        announcer = InteractionAnnouncer(
            self.memory, XD_US_REV0, sources, self.speech,
            logging.getLogger("interaction-announcer-test"),
            default_trigger_radius=10.0,
        )
        announcer.poll_once()
        self.memory.window_head = 0x80700000
        announcer.poll_once()
        self.assertIn("Used PC.", self.speech.calls)
        self.assertNotIn("Talked to Far NPC.", self.speech.calls)


if __name__ == "__main__":
    unittest.main()
