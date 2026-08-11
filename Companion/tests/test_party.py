import unittest

from battle_narrator.memory import MemoryError as MemErr, MemoryReader
from battle_narrator.party import PartyMemorySource, PartyMove, PartySlot, PartyStats
from battle_narrator.profile import XD_US_REV0


class WindowBackend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + offset, 0) for offset in range(size))


def be16(value):
    return value.to_bytes(2, "big")


def be32(value):
    return value.to_bytes(4, "big")


def nickname_bytes(text):
    return "".join(text).encode("utf-16-be") + b"\x00\x00"


class FakeMoveData:
    NAMES = {
        33: "TACKLE", 39: "TAIL WHIP", 44: "BITE", 28: "SAND-ATTACK",
        216: "FUTURE MOVE A", 287: "FUTURE MOVE B", 122: "LICK", 232: "METAL CLAW",
        356: "SHADOW RUSH", 369: "SHADOW BREAK",
    }

    def resolve(self, move_id):
        if move_id not in self.NAMES:
            raise MemErr(f"unknown move {move_id}")
        return self.NAMES[move_id], "{} used {}!"


class FakeAbilityData:
    # species -> (ability1, ability2); ability index -> (name, description)
    SPECIES = {133: (50, 0), 191: (34, 65)}
    ABILITIES = {50: ("RUN AWAY", "Makes escaping easier."),
                 34: ("CHLOROPHYLL", "Boosts Speed in harsh sunlight."),
                 65: ("EARLY BIRD", "Awakens quickly from sleep.")}

    def species_ability_index(self, species_id, personality):
        if species_id not in self.SPECIES:
            raise MemErr(f"unknown species {species_id}")
        ability1, ability2 = self.SPECIES[species_id]
        if ability2 and personality % 2 == 1:
            return ability2
        return ability1

    def resolve(self, memory, profile, ability_index):
        if ability_index not in self.ABILITIES:
            raise MemErr(f"unknown ability {ability_index}")
        return self.ABILITIES[ability_index]


DEFAULT_STATS = dict(attack=18, defense=18, special_attack=14,
                     special_defense=18, speed=18)
DEFAULT_MOVES = [(33, 35), (39, 29), (44, 23), (28, 15)]


class PartyMemorySourceTests(unittest.TestCase):
    SAVEDATA_ADDRESS = 0x80500000

    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.backend.put(
            self.profile.savedata_pointer_address, be32(self.SAVEDATA_ADDRESS)
        )
        self.source = PartyMemorySource(
            MemoryReader(self.backend, self.profile), self.profile,
            FakeMoveData(), FakeAbilityData())

    def _put_slot(self, index, species=133, level=10, hp=29, maxhp=33,
                  condition=0, nickname="EEVEE", stats=None, moves=None,
                  ot_name="LEON", exp=1305, personality=0x23CFCB26, item_id=0,
                  ability_index=0):
        p = self.profile
        hero = self.SAVEDATA_ADDRESS + p.hero_offset
        base = hero + p.hero_party_offset + index * p.hero_party_stride
        self.backend.put(base + p.party_species_offset, be16(species))
        self.backend.put(base + p.party_current_hp_offset, be16(hp))
        self.backend.put(base + p.party_max_hp_offset, be16(maxhp))
        self.backend.put(base + p.party_level_offset, bytes([level]))
        self.backend.put(base + p.party_condition_offset, bytes([condition]))
        self.backend.put(
            base + p.party_ability_index_offset, bytes([ability_index]))
        self.backend.put(base + p.party_nickname_offset, nickname_bytes(nickname))
        stats = DEFAULT_STATS if stats is None else stats
        self.backend.put(base + p.party_attack_offset, be16(stats["attack"]))
        self.backend.put(base + p.party_defense_offset, be16(stats["defense"]))
        self.backend.put(base + p.party_special_attack_offset, be16(stats["special_attack"]))
        self.backend.put(base + p.party_special_defense_offset, be16(stats["special_defense"]))
        self.backend.put(base + p.party_speed_offset, be16(stats["speed"]))
        moves = DEFAULT_MOVES if moves is None else moves
        for slot, (move_id, pp) in enumerate(moves):
            move_base = base + p.pokemon_moves_offset + slot * p.pokemon_move_stride
            self.backend.put(move_base + p.pokemon_move_id_offset, be16(move_id))
            self.backend.put(move_base + p.pokemon_move_pp_offset, bytes([pp]))
        self.backend.put(base + p.party_ot_offset, nickname_bytes(ot_name))
        self.backend.put(base + p.party_exp_offset, be32(exp))
        self.backend.put(base + p.party_personality_offset, be32(personality))
        self.backend.put(base + p.party_item_offset, be16(item_id))

    def test_single_occupied_slot_is_read(self):
        self._put_slot(0)
        slots = self.source.slots()
        self.assertEqual(slots, [PartySlot(
            0, "EEVEE", 10, 29, 33, 0,
            PartyStats(18, 18, 14, 18, 18),
            (PartyMove("TACKLE", 35), PartyMove("TAIL WHIP", 29),
             PartyMove("BITE", 23), PartyMove("SAND-ATTACK", 15)),
            "LEON", 1305, "Bashful", 0,
            "RUN AWAY", "Makes escaping easier.",
            species=133,
        )])

    def test_empty_slots_are_skipped(self):
        self._put_slot(0)
        # slots 1-5 left as species=0 (all-zero), the natural empty state.
        slots = self.source.slots()
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].index, 0)

    def test_multiple_occupied_slots_read_in_order(self):
        self._put_slot(0, nickname="EEVEE")
        self._put_slot(2, species=191, level=5, hp=18, maxhp=18, nickname="SUNKERN")
        slots = self.source.slots()
        self.assertEqual([s.index for s in slots], [0, 2])
        self.assertEqual(slots[1].raw_nickname, "SUNKERN")

    def test_implausible_level_raises(self):
        self._put_slot(0, level=0)
        with self.assertRaises(MemErr):
            self.source.slots()

    def test_hp_exceeding_max_raises(self):
        self._put_slot(0, hp=40, maxhp=33)
        with self.assertRaises(MemErr):
            self.source.slots()

    def test_invalid_condition_raises(self):
        self._put_slot(0, condition=2)
        with self.assertRaises(MemErr):
            self.source.slots()

    def test_empty_nickname_raises(self):
        self._put_slot(0, nickname="")
        with self.assertRaises(MemErr):
            self.source.slots()

    def test_empty_move_slots_are_omitted(self):
        self._put_slot(0, moves=[(33, 35), (0, 0), (0, 0), (0, 0)])
        slots = self.source.slots()
        self.assertEqual(slots[0].moves, (PartyMove("TACKLE", 35),))

    def test_unresolvable_move_id_falls_back_to_generic_label(self):
        self._put_slot(0, moves=[(999, 10), (0, 0), (0, 0), (0, 0)])
        slots = self.source.slots()
        self.assertEqual(slots[0].moves, (PartyMove("move 999", 10),))

    def test_no_move_data_provided_uses_generic_labels(self):
        source = PartyMemorySource(MemoryReader(self.backend, self.profile), self.profile)
        self._put_slot(0, moves=[(33, 35), (0, 0), (0, 0), (0, 0)])
        slots = source.slots()
        self.assertEqual(slots[0].moves, (PartyMove("move 33", 35),))

    def test_shadow_locked_move_slots_use_dark_waza_override(self):
        # Regression test for the project owner's confirmed live finding
        # (2026-07-30, Teddiursa): normal move1-4 slots hold the eventual
        # post-purification moves for shadow-locked slots, but the real,
        # currently-usable move lives in a separate _deckDarkPokemon[]
        # array indexed by a dark-pokemon ID stored directly on the
        # Pokemon struct (+0xBA). A slot whose dark_waza entry is 0 is
        # not shadow-locked and must keep using its normal move ID.
        p = self.profile
        self._put_slot(
            0, species=216,
            moves=[(216, 35), (287, 10), (122, 20), (232, 10)],
        )
        hero = self.SAVEDATA_ADDRESS + p.hero_offset
        base = hero + p.hero_party_offset
        dark_id = 1
        self.backend.put(base + p.dark_pokemon_data_id_offset, be16(dark_id))
        deck_array = 0x80900000
        self.backend.put(p.deck_dark_pokemon_pointer_address, be32(deck_array))
        record = deck_array + dark_id * p.deck_dark_pokemon_stride
        waza = [356, 369, 0, 0]
        for slot, move_id in enumerate(waza):
            self.backend.put(
                record + p.deck_dark_pokemon_waza_offset + slot * 2,
                be16(move_id))
        slots = self.source.slots()
        self.assertEqual(
            slots[0].moves,
            (
                PartyMove("SHADOW RUSH", 35),
                PartyMove("SHADOW BREAK", 10),
                PartyMove("LICK", 20),
                PartyMove("METAL CLAW", 10),
            ),
        )

    def test_heart_gauge_percent_reflects_dark_point_drained_toward_zero(self):
        # Regression test for the project owner's confirmed live finding
        # (2026-07-30, Teddiursa): Dark Point counts DOWN from InitDarkPoint
        # toward 0 as purification progress accumulates (confirmed by the
        # project owner directly against their own real save); 0 means
        # fully open/ready to purify, i.e. heart_gauge_percent == 100.
        p = self.profile
        self._put_slot(0, species=216)
        hero = self.SAVEDATA_ADDRESS + p.hero_offset
        base = hero + p.hero_party_offset
        dark_id = 1
        self.backend.put(base + p.dark_pokemon_data_id_offset, be16(dark_id))
        deck_array = 0x80900000
        self.backend.put(p.deck_dark_pokemon_pointer_address, be32(deck_array))
        deck_record = deck_array + dark_id * p.deck_dark_pokemon_stride
        self.backend.put(
            deck_record + p.deck_dark_pokemon_init_dark_point_offset, be16(3000))
        dark_pokemon_record = (
            self.SAVEDATA_ADDRESS + p.darkpokemon_array_savedata_offset
            + dark_id * p.dark_pokemon_stride
        )
        self.backend.put(
            dark_pokemon_record + p.dark_point_direct_offset, be32(0))
        slots = self.source.slots()
        self.assertEqual(slots[0].heart_gauge_percent, 100)

    def test_fully_open_heart_ignores_stale_shadow_deck_moves(self):
        p = self.profile
        self._put_slot(
            0, species=82,
            moves=[(33, 20), (39, 11), (44, 28), (28, 4)],
        )
        hero = self.SAVEDATA_ADDRESS + p.hero_offset
        base = hero + p.hero_party_offset
        dark_id = 82
        self.backend.put(base + p.dark_pokemon_data_id_offset, be16(dark_id))
        deck_array = 0x80900000
        self.backend.put(p.deck_dark_pokemon_pointer_address, be32(deck_array))
        deck_record = deck_array + dark_id * p.deck_dark_pokemon_stride
        self.backend.put(
            deck_record + p.deck_dark_pokemon_init_dark_point_offset,
            be16(2500))
        self.backend.put(
            deck_record + p.deck_dark_pokemon_waza_offset,
            be16(356) + be16(368) + be16(0) + be16(0))
        dark_record = (
            self.SAVEDATA_ADDRESS + p.darkpokemon_array_savedata_offset
            + dark_id * p.dark_pokemon_stride)
        self.backend.put(
            dark_record + p.dark_point_direct_offset, be32(0))

        slots = self.source.slots()

        self.assertEqual(
            [move.name for move in slots[0].moves],
            ["TACKLE", "TAIL WHIP", "BITE", "SAND-ATTACK"],
        )

    def test_heart_gauge_percent_partway_drained(self):
        p = self.profile
        self._put_slot(0, species=216)
        hero = self.SAVEDATA_ADDRESS + p.hero_offset
        base = hero + p.hero_party_offset
        dark_id = 1
        self.backend.put(base + p.dark_pokemon_data_id_offset, be16(dark_id))
        deck_array = 0x80900000
        self.backend.put(p.deck_dark_pokemon_pointer_address, be32(deck_array))
        deck_record = deck_array + dark_id * p.deck_dark_pokemon_stride
        self.backend.put(
            deck_record + p.deck_dark_pokemon_init_dark_point_offset, be16(3000))
        dark_pokemon_record = (
            self.SAVEDATA_ADDRESS + p.darkpokemon_array_savedata_offset
            + dark_id * p.dark_pokemon_stride
        )
        self.backend.put(
            dark_pokemon_record + p.dark_point_direct_offset, be32(750))
        slots = self.source.slots()
        self.assertEqual(slots[0].heart_gauge_percent, 75)

    def test_non_shadow_pokemon_is_unaffected_by_dark_waza_lookup(self):
        # dark_pokemon_data_id_offset left at 0 (the natural default for a
        # non-Shadow Pokemon) must never trigger a _deckDarkPokemon read.
        self._put_slot(0)
        slots = self.source.slots()
        self.assertIsNone(slots[0].heart_gauge_percent)
        self.assertEqual(slots[0].moves, (
            PartyMove("TACKLE", 35), PartyMove("TAIL WHIP", 29),
            PartyMove("BITE", 23), PartyMove("SAND-ATTACK", 15),
        ))

    def test_nature_computed_from_personality_modulo(self):
        # personality % 25 == 0 -> first nature in the standard Gen 3 order.
        self._put_slot(0, personality=0)
        slots = self.source.slots()
        self.assertEqual(slots[0].nature, "Hardy")

    def test_ot_name_and_exp_are_read(self):
        self._put_slot(0, ot_name="RED", exp=999)
        slots = self.source.slots()
        self.assertEqual(slots[0].ot_name, "RED")
        self.assertEqual(slots[0].exp, 999)

    def test_nonzero_item_id_is_read(self):
        self._put_slot(0, item_id=5)
        slots = self.source.slots()
        self.assertEqual(slots[0].item_id, 5)

    def test_ability_resolved_from_species_and_personality(self):
        self._put_slot(0, species=133)
        slots = self.source.slots()
        self.assertEqual(slots[0].ability_name, "RUN AWAY")
        self.assertEqual(slots[0].ability_description, "Makes escaping easier.")

    def test_second_ability_slot_used_when_personality_is_odd(self):
        self._put_slot(0, species=191, personality=1)
        slots = self.source.slots()
        self.assertEqual(slots[0].ability_name, "EARLY BIRD")

    def test_first_ability_slot_used_when_personality_is_even(self):
        self._put_slot(0, species=191, personality=2)
        slots = self.source.slots()
        self.assertEqual(slots[0].ability_name, "CHLOROPHYLL")

    def test_live_randomized_ability_overrides_vanilla_species_slots(self):
        # Eevee's vanilla fixture resolves to RUN AWAY (50). The individual
        # Pokemon's live +0x1D byte says 65, so randomized EARLY BIRD wins.
        self._put_slot(0, species=133, personality=2, ability_index=65)
        slots = self.source.slots()
        self.assertEqual(slots[0].ability_name, "EARLY BIRD")
        self.assertEqual(
            slots[0].ability_description,
            "Awakens quickly from sleep.",
        )

    def test_no_ability_data_provided_leaves_ability_blank(self):
        source = PartyMemorySource(
            MemoryReader(self.backend, self.profile), self.profile, FakeMoveData())
        self._put_slot(0)
        slots = source.slots()
        self.assertEqual(slots[0].ability_name, "")
        self.assertEqual(slots[0].ability_description, "")

    def test_unresolvable_species_ability_leaves_ability_blank(self):
        self._put_slot(0, species=999)
        slots = self.source.slots()
        self.assertEqual(slots[0].ability_name, "")


if __name__ == "__main__":
    unittest.main()
