import logging
import unittest

from battle_narrator.hotkeys import PartySlotSummary
from battle_narrator.memory import MemoryError
from battle_narrator.party import PartyMove, PartySlot, PartyStats
from battle_narrator.phase1b_app import party_slot_hotkeys_value
from battle_narrator.profile import XD_US_REV0
from battle_narrator.speech import SpeechEventClass
import argparse


def slot(index, nickname="EEVEE", level=11, hp=29, max_hp=33, condition=0,
         heart_gauge_percent=None, item_id=0, ability_name=""):
    return PartySlot(
        index, nickname, level, hp, max_hp, condition,
        PartyStats(18, 18, 14, 18, 18),
        (PartyMove("TACKLE", 35),), "LEON", 1305, "Bashful", item_id,
        ability_name, "", heart_gauge_percent,
    )


class Source:
    def __init__(self, slots=()):
        self._slots = list(slots)
        self.fail = False

    def slots(self):
        if self.fail:
            raise MemoryError("party unreadable")
        return list(self._slots)


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

    def emit(self, event, text, interrupt=None):
        self.calls.append((event, text, interrupt))


class Items:
    def __init__(self, names=None):
        self.names = names or {}

    def resolve_name(self, item_id):
        return self.names.get(item_id)


class PartySlotSummaryTests(unittest.TestCase):
    def setUp(self):
        self.source = Source()
        self.hotkeys = {index: Hotkey() for index in range(6)}
        self.speech = Speech()
        self.summary = PartySlotSummary(
            self.source, self.hotkeys, self.speech,
            logging.getLogger("party-slot-test"),
            item_names=Items({13: "Potion"}))

    def press(self, index):
        self.hotkeys[index].fire = True
        self.summary.poll_once()

    def spoken(self):
        return self.speech.calls[-1][1]

    def test_nothing_is_spoken_without_a_press(self):
        self.source._slots = [slot(0)]
        self.summary.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_each_chord_answers_for_its_own_slot(self):
        self.source._slots = [slot(0, "EEVEE"), slot(2, "TEDDIURSA")]
        self.press(0)
        self.assertIn("Slot 1. Eevee", self.spoken())
        self.press(2)
        self.assertIn("Slot 3. Teddiursa", self.spoken())

    def test_full_line_carries_every_requested_fact(self):
        self.source._slots = [slot(
            0, "TEDDIURSA", level=11, hp=29, max_hp=33, condition=5,
            heart_gauge_percent=40, item_id=13, ability_name="PICKUP")]
        self.press(0)
        text = self.spoken()
        self.assertEqual(
            text,
            "Slot 1. Teddiursa, level 11, 29 of 33 HP, 88 percent, "
            "paralyzed. Heart Gauge: 40 percent open. Holding Potion.")
        self.assertIs(self.speech.calls[-1][0], SpeechEventClass.ENTITY_NAV)

    def test_the_ability_is_not_spoken_even_when_the_slot_carries_one(self):
        # Removed 2026-08-18: the project owner reported the ability as
        # wrong. Pinned so it cannot drift back in on the assumption that
        # an available field ought to be spoken -- the value is still on
        # the slot, and still resolves, it is simply not trusted.
        self.source._slots = [slot(0, ability_name="PICKUP")]
        self.press(0)
        self.assertNotIn("Ability", self.spoken())
        self.assertNotIn("Pickup", self.spoken())

    def test_a_fainted_member_says_so(self):
        self.source._slots = [slot(0, "EEVEE", hp=0)]
        self.press(0)
        self.assertIn("zero percent, fainted", self.spoken())

    def test_a_fully_open_heart_gauge_is_called_ready(self):
        self.source._slots = [slot(0, heart_gauge_percent=100)]
        self.press(0)
        self.assertIn("Heart Gauge: fully open, ready to purify.",
                      self.spoken())

    def test_a_non_shadow_member_says_nothing_about_a_gauge(self):
        self.source._slots = [slot(0)]
        self.press(0)
        self.assertNotIn("Heart Gauge", self.spoken())

    def test_an_unresolvable_item_falls_back_to_its_id(self):
        self.source._slots = [slot(0, item_id=999)]
        self.press(0)
        self.assertIn("Holding item 999.", self.spoken())

    def test_no_item_is_stated_rather_than_omitted(self):
        self.source._slots = [slot(0)]
        self.press(0)
        self.assertIn("No item held.", self.spoken())

    def test_an_empty_slot_is_reported_as_empty(self):
        self.source._slots = [slot(0)]
        self.press(3)
        self.assertEqual(self.spoken(), "Slot 4 is empty.")

    def test_a_read_failure_is_spoken_not_silent(self):
        self.source.fail = True
        self.press(0)
        self.assertEqual(self.spoken(), "Party is not available right now.")

    def test_one_press_speaks_once(self):
        self.source._slots = [slot(0)]
        self.press(0)
        self.summary.poll_once()
        self.summary.poll_once()
        self.assertEqual(len(self.speech.calls), 1)


class PartySlotHotkeyArgumentTests(unittest.TestCase):
    def test_the_default_is_one_chord_per_party_slot(self):
        self.assertEqual(
            len(XD_US_REV0.default_party_slot_hotkeys),
            XD_US_REV0.hero_party_slots)
        self.assertEqual(
            party_slot_hotkeys_value(
                ",".join(XD_US_REV0.default_party_slot_hotkeys)),
            XD_US_REV0.default_party_slot_hotkeys)

    def test_a_short_list_is_rejected(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            party_slot_hotkeys_value("ctrl+1,ctrl+2")

    def test_a_repeated_chord_is_rejected(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            party_slot_hotkeys_value(
                "ctrl+1,ctrl+1,ctrl+3,ctrl+4,ctrl+5,ctrl+6")

    def test_a_chord_without_a_modifier_is_rejected(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            party_slot_hotkeys_value("1,ctrl+2,ctrl+3,ctrl+4,ctrl+5,ctrl+6")


if __name__ == "__main__":
    unittest.main()
