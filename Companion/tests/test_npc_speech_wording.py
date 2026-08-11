"""What the player actually hears, driven by the engine's own verdict.

`describe_entity` must never re-derive range from a horizontal distance
when the source has already evaluated the real predicate -- doing so is how
"Interaction available" got spoken for NPCs the game would ignore.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.entities import Entity
from battle_narrator.entity_nav import describe_entity
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.profile import XD_US_REV0
from battle_narrator.talk_predicate import (
    REJECT_DISTANCE, REJECT_FACING, REJECT_WALL, TalkVerdict,
)


POSE = PlayerPose(Position(0.0, 0.0, 0.0), 0.0, 0.0)


def entity(label, verdict, position=None):
    return Entity(
        category="npc", identity=("npc", 7, 0), label=label,
        position=position or Position(0.0, 0.0, -12.0),
        interaction_distance=verdict.threshold if verdict else None,
        metadata={"verdict": verdict} if verdict else {})


class WordingTests(unittest.TestCase):
    def test_named_npc_out_of_range(self):
        verdict = TalkVerdict(False, REJECT_DISTANCE, 40.0, 10.0, 0.0)
        text = describe_entity(
            XD_US_REV0, "npc", entity("Eagun", verdict), POSE,
            include_category=False)
        self.assertTrue(text.endswith("Out of interaction range."))
        self.assertTrue(text.startswith("Eagun. "))

    def test_unnamed_npc_speaks_a_bare_letter(self):
        verdict = TalkVerdict(False, REJECT_DISTANCE, 40.0, 10.0, 0.0)
        text = describe_entity(
            XD_US_REV0, "npc", entity("A", verdict), POSE,
            include_category=False)
        self.assertTrue(text.startswith("A. "))
        self.assertNotIn("NPC A", text)

    def test_eligible_says_interaction_available(self):
        verdict = TalkVerdict(True, None, 4.0, 10.0, 3.0)
        text = describe_entity(
            XD_US_REV0, "npc", entity("Eagun", verdict), POSE,
            include_category=False)
        self.assertIn("Interaction available.", text)

    def test_in_range_but_facing_away(self):
        verdict = TalkVerdict(False, REJECT_FACING, 4.0, 10.0, 120.0)
        text = describe_entity(
            XD_US_REV0, "npc", entity("Eagun", verdict), POSE,
            include_category=False)
        self.assertIn("In range but facing away, walk toward it.", text)

    def test_in_range_but_blocked_by_a_wall(self):
        verdict = TalkVerdict(False, REJECT_WALL, 4.0, 10.0, 3.0)
        text = describe_entity(
            XD_US_REV0, "npc", entity("Eagun", verdict), POSE,
            include_category=False)
        self.assertIn("In range but something is in the way.", text)

    def test_unverified_gate_does_not_promise_an_interaction(self):
        verdict = TalkVerdict(
            False, "unverified gate", 4.0, 10.0, 3.0, ("wall",))
        text = describe_entity(
            XD_US_REV0, "npc", entity("Eagun", verdict), POSE,
            include_category=False)
        self.assertIn("In range.", text)
        self.assertNotIn("Interaction available", text)

    def test_a_close_but_ineligible_npc_is_never_called_available(self):
        # Distance alone would have said "Interaction available" under the
        # old rule; the verdict says otherwise and the verdict wins.
        verdict = TalkVerdict(False, REJECT_DISTANCE, 11.0, 10.0, 0.0)
        text = describe_entity(
            XD_US_REV0, "npc",
            entity("Eagun", verdict, Position(0.0, 0.0, -1.0)), POSE,
            include_category=False)
        self.assertNotIn("Interaction available", text)

    def test_category_word_is_included_on_request(self):
        verdict = TalkVerdict(True, None, 4.0, 10.0, 3.0)
        text = describe_entity(
            XD_US_REV0, "npc", entity("Eagun", verdict), POSE)
        self.assertTrue(text.startswith("NPC. Eagun. "))

    def test_sources_without_a_verdict_keep_the_old_wording(self):
        # Warps, signs and the rest have no talk predicate; they must not
        # regress just because NPCs gained one.
        #
        # Note the two different things: the entity's own category is still
        # "warp" -- beacon sounds and interaction wording key on it -- while
        # the CYCLING key it is reached under is "exit". Collapsing the
        # cycle to six groups (2026-08-10) deliberately did not rewrite
        # what each entity is.
        plain = Entity(
            category="warp", identity=("warp", 3), label="to Agate Village",
            position=Position(0.0, 0.0, -4.0), interaction_distance=None)
        text = describe_entity(
            XD_US_REV0, "exit", plain, POSE, include_category=False)
        self.assertIn("to Agate Village.", text)
        self.assertNotIn("Interaction available", text)

    def test_the_exit_category_word_leads_a_prepositional_label(self):
        # "Exit to Agate Village", never "Exit. to Agate Village."
        plain = Entity(
            category="warp", identity=("warp", 3), label="to Agate Village",
            position=Position(0.0, 0.0, -4.0), interaction_distance=None)
        text = describe_entity(
            XD_US_REV0, "exit", plain, POSE, include_category=False)
        self.assertTrue(text.startswith("Exit to Agate Village."), text)


if __name__ == "__main__":
    unittest.main()
