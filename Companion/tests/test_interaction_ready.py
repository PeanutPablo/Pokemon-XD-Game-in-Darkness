"""Tests for the "Press A to interact with X." cue.

Replaces the earlier proximity-discovery tests: the project owner is
building sound beacons, which convey position far better than speech, so
the remaining job for speech is signalling *actionability* -- close enough
AND facing the right way, so the button press will actually land.
"""
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.entities import Entity
from battle_narrator.interaction_ready import InteractionReadyReader
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.profile import XD_US_REV0


class Speech:
    def __init__(self):
        self.texts = []

    def emit(self, event, text, deduplicate=False, interrupt=None):
        self.texts.append(text)


class FakeMemory:
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


def logger():
    log = logging.getLogger(f"ready-test-{id(object())}")
    log.addHandler(logging.NullHandler())
    return log


def entity(index, x, z, label=None, interaction=3.0, category="npc"):
    return Entity(
        category=category,
        identity=(category, index),
        label=label,
        position=Position(x, 0, z),
        interaction_distance=interaction,
    )


def reader(entities, pose=None, memory=None):
    # facing 0 == looking down -Z, matching the engine's heading convention.
    pose = pose or PlayerPose(Position(0, 0, 0), 0.0, facing=0.0)
    speech = Speech()
    return (
        InteractionReadyReader(
            memory or FakeMemory(), XD_US_REV0,
            {"npc": FakeSource(entities, pose)}, speech, logger()),
        speech,
    )


class InteractionReadyTests(unittest.TestCase):

    def test_announces_when_close_and_facing(self):
        read, speech = reader([entity(0, 0, -2, label="Berk")])
        read.poll_once()
        self.assertEqual(speech.texts, ["Press A to interact with Berk."])

    def test_silent_when_close_but_facing_away(self):
        """The live NPC G case: 1.72 units inside a 3.0 reach, but 149.6
        degrees off, and the game refused to talk. Prompting for A there is
        exactly the bug this cue must not reproduce."""
        read, speech = reader([entity(0, 0, 2, label="NPC G")])
        read.poll_once()
        self.assertEqual(speech.texts, [])

    def test_silent_when_facing_but_too_far(self):
        read, speech = reader([entity(0, 0, -80, label="Berk")])
        read.poll_once()
        self.assertEqual(speech.texts, [])

    def test_not_repeated_while_still_in_the_zone(self):
        read, speech = reader([entity(0, 0, -2, label="Berk")])
        for _ in range(10):
            read.poll_once()
        self.assertEqual(speech.texts, ["Press A to interact with Berk."])

    def test_leaving_and_returning_re_announces(self):
        near = entity(0, 0, -2, label="Berk")
        far = entity(0, 0, -80, label="Berk")
        pose = PlayerPose(Position(0, 0, 0), 0.0, facing=0.0)
        source = FakeSource([near], pose)
        speech = Speech()
        read = InteractionReadyReader(
            FakeMemory(), XD_US_REV0, {"npc": source}, speech, logger())
        read.poll_once()
        source._entities = [far]
        read.poll_once()
        source._entities = [near]
        read.poll_once()
        self.assertEqual(speech.texts, ["Press A to interact with Berk."] * 2)

    def test_nearest_usable_target_wins(self):
        read, speech = reader([
            entity(0, 0, -3, label="Further"),
            entity(1, 0, -1, label="Closer"),
        ])
        read.poll_once()
        self.assertEqual(speech.texts, ["Press A to interact with Closer."])

    def test_walk_into_categories_never_prompt_for_a(self):
        """Warps, doors and elevators trigger by walking into them, so a
        button prompt would be actively wrong."""
        for category in ("warp", "door", "elevator"):
            read, speech = reader(
                [entity(0, 0, -2, label="Door", category=category)])
            read.poll_once()
            self.assertEqual(speech.texts, [], category)

    def test_entities_without_their_own_radius_use_the_default(self):
        read, speech = reader(
            [entity(0, 0, -6, label="PC", interaction=None, category="interact")])
        read.poll_once()
        self.assertEqual(speech.texts, ["Press A to interact with PC."])

    def test_facing_hysteresis_prevents_retrigger_while_shuffling(self):
        """Facing changes with every step, so an announced target must not
        re-announce when the player wobbles just past the cone edge."""
        import math
        cone = XD_US_REV0.talk_cone_degrees
        margin = XD_US_REV0.interaction_ready_facing_hysteresis
        target = entity(0, 0, -2, label="Berk")
        speech = Speech()
        pose = PlayerPose(Position(0, 0, 0), 0.0, facing=0.0)
        source = FakeSource([target], pose)
        read = InteractionReadyReader(
            FakeMemory(), XD_US_REV0, {"npc": source}, speech, logger())
        read.poll_once()
        # Wobble just inside cone + hysteresis and back. No new cue.
        for angle in (cone + margin / 2, 0.0, cone + margin / 2, 0.0):
            source.pose = PlayerPose(
                Position(0, 0, 0), 0.0, facing=math.radians(angle))
            read.poll_once()
        self.assertEqual(speech.texts, ["Press A to interact with Berk."])

    def test_silent_while_a_window_is_open(self):
        read, speech = reader(
            [entity(0, 0, -2, label="Berk")],
            memory=FakeMemory(window_head=0x80000000))
        read.poll_once()
        self.assertEqual(speech.texts, [])

    def test_silent_during_dialogue(self):
        read, speech = reader([entity(0, 0, -2, label="Berk")])
        read.poll_once(dialogue_active=True)
        self.assertEqual(speech.texts, [])

    def test_map_change_clears_and_allows_re_announcement(self):
        memory = FakeMemory(floor_id=1)
        read, speech = reader([entity(0, 0, -2, label="Berk")], memory=memory)
        read.poll_once()
        memory.floor_id = 2
        read.poll_once()
        self.assertEqual(speech.texts, ["Press A to interact with Berk."] * 2)

    def test_unreadable_facing_falls_back_to_distance_only(self):
        pose = PlayerPose(Position(0, 0, 0), 0.0, facing=None)
        read, speech = reader([entity(0, 0, 2, label="Berk")], pose=pose)
        read.poll_once()
        self.assertEqual(speech.texts, ["Press A to interact with Berk."])


if __name__ == "__main__":
    unittest.main()
