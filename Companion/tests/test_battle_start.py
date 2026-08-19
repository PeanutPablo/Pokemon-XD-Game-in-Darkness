import logging
import unittest

from battle_narrator.battle_identity import (
    BattlerIdentity, PartyPosition, party_slot_address,
)
from battle_narrator.battle_start import (
    BattleStartAnnouncer, OpponentPartySource, announcement,
)
from battle_narrator.memory import MemoryError
from battle_narrator.profile import XD_US_REV0
from battle_narrator.speech import SpeechEventClass


class Speech:
    def __init__(self):
        self.calls = []

    def emit(self, event, text, interrupt=None):
        self.calls.append((event, text, interrupt))


class Resolver:
    """Stands in for BattleIdentityResolver.active_battlers()."""

    def __init__(self, occupied=0):
        self.occupied = occupied
        self.fail = False

    def active_battlers(self):
        if self.fail:
            raise MemoryError("field unreadable")
        return [
            BattlerIdentity(party=PartyPosition(index % 2, 0, 0))
            for index in range(self.occupied)
        ]


class Counts:
    def __init__(self, counts=()):
        self.counts_value = list(counts)

    def counts(self):
        return list(self.counts_value)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeMemory:
    """Only the reads OpponentPartySource makes, off a flat address map."""

    def __init__(self):
        self.u16_values = {}
        self.u8_values = {}
        self.strings = {}
        self.unreadable = set()

    def _check(self, address):
        if address in self.unreadable:
            raise MemoryError(f"unreadable 0x{address:08X}")

    def u16(self, address, label="u16"):
        self._check(address)
        return self.u16_values.get(address, 0)

    def u8(self, address, label="u8"):
        self._check(address)
        return self.u8_values.get(address, 0)

    def gschar(self, address, maximum, label, alignment=1):
        self._check(address)
        return self.strings.get(address, "")


def place(memory, side, trainer, slot, species=25, level=30,
          maximum=80, current=80, nickname="PIKACHU"):
    p = XD_US_REV0
    fight_pokemon = party_slot_address(p, side, trainer, slot)
    pokemon = fight_pokemon + p.fight_pokemon_embedded_offset
    memory.u16_values[pokemon + p.pokemon_species_offset] = species
    memory.u8_values[pokemon + p.pokemon_level_offset] = level
    memory.u16_values[pokemon + p.pokemon_max_hp_offset] = maximum
    memory.u16_values[pokemon + p.pokemon_current_hp_offset] = current
    memory.strings[fight_pokemon + p.health_nickname_offset] = nickname
    return fight_pokemon


class AnnouncementTests(unittest.TestCase):
    def test_no_opponents_says_nothing(self):
        self.assertIsNone(announcement([]))

    def test_single_trainer(self):
        self.assertEqual(announcement([3]), "Opponent has 3 Pokémon.")

    def test_single_pokemon_is_still_counted(self):
        self.assertEqual(announcement([1]), "Opponent has 1 Pokémon.")

    def test_two_trainers_are_listed_and_totalled(self):
        self.assertEqual(
            announcement([3, 4]),
            "Opponents have 3 and 4 Pokémon, 7 in total.")


class OpponentPartySourceTests(unittest.TestCase):
    def setUp(self):
        self.memory = FakeMemory()
        self.source = OpponentPartySource(self.memory, XD_US_REV0)

    def test_empty_outside_a_battle(self):
        self.assertEqual(self.source.counts(), [])

    def test_counts_only_the_opposing_side(self):
        for slot in range(4):
            place(self.memory, 0, 0, slot)
        for slot in range(3):
            place(self.memory, 1, 0, slot)
        self.assertEqual(self.source.counts(), [3])

    def test_second_opposing_trainer_is_its_own_count(self):
        for slot in range(2):
            place(self.memory, 1, 0, slot)
        for slot in range(5):
            place(self.memory, 1, 1, slot)
        self.assertEqual(self.source.counts(), [2, 5])

    def test_implausible_cells_are_not_counted(self):
        place(self.memory, 1, 0, 0)
        place(self.memory, 1, 0, 1, level=0)
        place(self.memory, 1, 0, 2, level=101)
        place(self.memory, 1, 0, 3, nickname="   ")
        place(self.memory, 1, 0, 4, species=0)
        self.assertEqual(self.source.counts(), [1])

    def test_a_pokemon_with_no_hp_yet_is_still_counted(self):
        # At battle start most of the opponent's party has never been sent
        # out, and whether an unsent Pokemon's HP field is populated at all
        # is an open question (see the module docstring). Requiring HP
        # would announce "1 Pokemon" for a full team of six.
        for slot in range(6):
            place(self.memory, 1, 0, slot, maximum=0, current=0)
        self.assertEqual(self.source.counts(), [6])

    def test_accepted_cells_are_logged_for_the_pending_live_check(self):
        records = []
        self.source.logger = type(
            "L", (), {"info": lambda _s, message, *args: records.append(
                message % args)})()
        place(self.memory, 1, 0, 0, species=25, level=30, nickname="PIKACHU")
        place(self.memory, 1, 0, 1, species=6, level=40, nickname="CHARIZARD")
        self.source.counts()
        self.assertEqual(len(records), 1)
        self.assertIn("count=2", records[0])
        self.assertIn("[0] species=25 level=30 'PIKACHU'", records[0])
        self.assertIn("[1] species=6 level=40 'CHARIZARD'", records[0])

    def test_an_unreadable_cell_does_not_lose_the_whole_count(self):
        for slot in range(3):
            place(self.memory, 1, 0, slot)
        broken = party_slot_address(XD_US_REV0, 1, 0, 1)
        self.memory.unreadable.add(
            broken + XD_US_REV0.fight_pokemon_embedded_offset
            + XD_US_REV0.pokemon_species_offset)
        self.assertEqual(self.source.counts(), [2])


class BattleStartAnnouncerTests(unittest.TestCase):
    def setUp(self):
        self.resolver = Resolver()
        self.source = Counts()
        self.speech = Speech()
        self.clock = Clock()
        self.announcer = BattleStartAnnouncer(
            self.resolver, self.source, XD_US_REV0, self.speech,
            logging.getLogger("battle-start-test"), clock=self.clock)

    def start_battle(self, counts=(3,)):
        self.resolver.occupied = 2
        self.source.counts_value = list(counts)

    def poll(self, times=1):
        for _ in range(times):
            self.announcer.poll_once()

    def test_nothing_is_spoken_outside_a_battle(self):
        self.poll(5)
        self.assertEqual(self.speech.calls, [])

    def test_one_announcement_per_battle(self):
        self.start_battle()
        self.poll(10)
        self.assertEqual(len(self.speech.calls), 1)
        event, text, interrupt = self.speech.calls[0]
        self.assertIs(event, SpeechEventClass.BATTLE_EVENT)
        self.assertEqual(text, "Opponent has 3 Pokémon.")
        self.assertFalse(interrupt)

    def test_an_unstable_count_is_not_announced(self):
        self.start_battle(counts=(1,))
        self.poll()
        self.source.counts_value = [3]
        self.poll()
        self.assertEqual(self.speech.calls, [])
        # It settles on the next agreeing pair and is then spoken once.
        self.poll(2)
        self.assertEqual(len(self.speech.calls), 1)
        self.assertEqual(self.speech.calls[0][1], "Opponent has 3 Pokémon.")

    def test_a_replacement_gap_does_not_re_announce(self):
        self.start_battle()
        self.poll(3)
        self.resolver.occupied = 0          # the fainted Pokemon leaves
        self.clock.now += 0.4
        self.poll(2)
        self.resolver.occupied = 2          # its replacement arrives
        self.poll(5)
        self.assertEqual(len(self.speech.calls), 1)

    def test_the_next_battle_is_announced_again(self):
        self.start_battle()
        self.poll(3)
        self.resolver.occupied = 0
        self.poll()
        self.clock.now += 30.0
        self.poll()
        self.start_battle(counts=(5,))
        self.poll(3)
        self.assertEqual(len(self.speech.calls), 2)
        self.assertEqual(self.speech.calls[1][1], "Opponent has 5 Pokémon.")

    def test_an_unreadable_field_is_skipped_not_fatal(self):
        self.resolver.fail = True
        self.poll(3)
        self.assertEqual(self.speech.calls, [])
        self.resolver.fail = False
        self.start_battle()
        self.poll(3)
        self.assertEqual(len(self.speech.calls), 1)

    def test_clear_re_arms(self):
        self.start_battle()
        self.poll(3)
        self.announcer.clear("test")
        self.poll(3)
        self.assertEqual(len(self.speech.calls), 2)


if __name__ == "__main__":
    unittest.main()
