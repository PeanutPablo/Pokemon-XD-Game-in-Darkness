import unittest

from battle_narrator.battle_targets import (
    TargetFacts, TargetFactsSource, status_panel_hp, target_detail,
)
from battle_narrator.memory import MemoryReader
from battle_narrator.profile import XD_US_REV0


def be16(value):
    return value.to_bytes(2, "big")


def be32(value):
    return value.to_bytes(4, "big")


def gschar(value):
    return b"".join(be16(ord(char)) for char in value) + b"\0\0"


class Backend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + i, 0) for i in range(size))


class TargetDetailTests(unittest.TestCase):
    def test_nothing_known_produces_no_clause(self):
        self.assertEqual(target_detail(), "")

    def test_hp_alone(self):
        self.assertEqual(
            target_detail(hp=41, max_hp=160), "41 of 160 HP, 26 percent")

    def test_level_alone(self):
        self.assertEqual(target_detail(TargetFacts(level=25)), "level 25")

    def test_everything_in_order(self):
        self.assertEqual(
            target_detail(TargetFacts(level=25, condition=6), 20, 80),
            "level 25, 20 of 80 HP, 25 percent, burned")

    def test_a_downed_target_is_called_fainted(self):
        self.assertEqual(
            target_detail(TargetFacts(level=9), 0, 170),
            "level 9, 0 of 170 HP, zero percent, fainted")

    def test_a_healthy_condition_adds_nothing(self):
        self.assertEqual(
            target_detail(TargetFacts(level=9, condition=0)), "level 9")

    def test_an_unknown_condition_is_not_invented(self):
        self.assertEqual(target_detail(TargetFacts(condition=99)), "")

    def test_a_zero_max_hp_is_not_divided_by(self):
        self.assertEqual(target_detail(TargetFacts(level=5), 0, 0), "level 5")


class StatusPanelHPTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.memory = MemoryReader(self.backend, XD_US_REV0)
        self.allocation = 0x80020000

    def write(self, current, maximum):
        self.backend.put(
            self.allocation + XD_US_REV0.status_max_hp_offset,
            be16(maximum & 0xFFFF) + be16(current & 0xFFFF))

    def test_a_populated_panel(self):
        self.write(41, 160)
        self.assertEqual(
            status_panel_hp(self.memory, XD_US_REV0, self.allocation, "t"),
            (41, 160))

    def test_an_unpopulated_panel_reports_nothing(self):
        self.assertEqual(
            status_panel_hp(self.memory, XD_US_REV0, self.allocation, "t"),
            (None, None))

    def test_a_negative_value_is_rejected_not_wrapped(self):
        self.write(-1, 160)
        self.assertEqual(
            status_panel_hp(self.memory, XD_US_REV0, self.allocation, "t"),
            (None, None))

    def test_hp_above_maximum_is_rejected(self):
        self.write(200, 160)
        self.assertEqual(
            status_panel_hp(self.memory, XD_US_REV0, self.allocation, "t"),
            (None, None))

    def test_an_implausible_maximum_is_rejected(self):
        self.write(1, XD_US_REV0.maximum_plausible_hp + 1)
        self.assertEqual(
            status_panel_hp(self.memory, XD_US_REV0, self.allocation, "t"),
            (None, None))


class TargetFactsSourceTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.memory = MemoryReader(self.backend, XD_US_REV0)
        self.source = TargetFactsSource(self.memory, XD_US_REV0)

    def place(self, slot, name, level=30, condition=0, attached=True):
        p = XD_US_REV0
        base = p.fight_floor_root + p.active_battler_array_offset
        fight_out = 0x80100000 + slot * 0x1000
        fight_pokemon = 0x80200000 + slot * 0x1000
        self.backend.put(base + slot * 4, be32(fight_out))
        self.backend.put(
            fight_out + p.fight_out_fight_pokemon_offset,
            be32(fight_pokemon if attached else 0))
        if not attached:
            return
        self.backend.put(
            fight_pokemon + p.health_nickname_offset, gschar(name))
        pokemon = fight_pokemon + p.fight_pokemon_embedded_offset
        self.backend.put(pokemon + p.pokemon_level_offset, bytes((level,)))
        self.backend.put(
            pokemon + p.pokemon_condition_offset, bytes((condition,)))

    def test_an_empty_field_yields_nothing(self):
        self.assertEqual(self.source.facts(), {})

    def test_each_battler_by_normalised_nickname(self):
        self.place(0, "LATIOS", level=50, condition=3)
        self.place(1, "RAIKOU", level=44)
        self.assertEqual(self.source.facts(), {
            "latios": TargetFacts(level=50, condition=3),
            "raikou": TargetFacts(level=44, condition=0),
        })

    def test_a_duplicated_nickname_yields_nothing_for_either(self):
        self.place(0, "EEVEE", level=10)
        self.place(1, "EEVEE", level=40)
        self.place(2, "UMBREON", level=40)
        self.assertEqual(self.source.facts(), {
            "umbreon": TargetFacts(level=40, condition=0)})

    def test_a_detached_wrapper_is_skipped(self):
        self.place(0, "LATIOS", level=50)
        self.place(1, "GONE", attached=False)
        self.assertEqual(set(self.source.facts()), {"latios"})

    def test_an_implausible_level_is_dropped_but_the_battler_is_kept(self):
        self.place(0, "LATIOS", level=0, condition=5)
        self.assertEqual(
            self.source.facts(),
            {"latios": TargetFacts(level=None, condition=5)})

    def test_an_invalid_condition_is_dropped(self):
        self.place(0, "LATIOS", level=50, condition=2)
        self.assertEqual(
            self.source.facts(),
            {"latios": TargetFacts(level=50, condition=None)})


if __name__ == "__main__":
    unittest.main()
