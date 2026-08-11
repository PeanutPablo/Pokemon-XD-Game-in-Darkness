import unittest

from battle_narrator.battle_identity import PartyPosition, party_slot_address
from battle_narrator.memory import MemoryError, MemoryReader
from battle_narrator.profile import XD_US_REV0
from battle_narrator.resolver import VerifiedResolver

FIGHT_OUT_ADDR = 0x80700000
FIGHT_POKEMON_ADDR = 0x80700100


def be16(value):
    return value.to_bytes(2, "big")


def be32(value):
    return value.to_bytes(4, "big")


def gschar(text):
    return b"".join(be16(ord(char)) for char in text) + b"\0\0"


class FakeBackend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + offset, 0) for offset in range(size))


class VerifiedResolverTests(unittest.TestCase):
    """Direct coverage for VerifiedResolver against synthetic memory bytes
    -- previously missing entirely (every existing narrator test used a
    FakeResolver stub), which is exactly how a real, live-confirmed bug in
    level_sample() (reading 4 bytes too early, "grew to level 0!" instead
    of the real level) went undetected. See IMPLEMENTATION_ATTRIBUTION.md's
    2026-07-30 entry for the live discovery."""

    def setUp(self):
        self.backend = FakeBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        p = self.profile
        self.backend.put(p.attack_mons, be32(FIGHT_OUT_ADDR))
        self.backend.put(
            FIGHT_OUT_ADDR + p.fight_out_pokemon_offset, be32(FIGHT_POKEMON_ADDR)
        )
        self.backend.put(
            FIGHT_POKEMON_ADDR + p.nickname_offset, gschar("SALAMENCE")
        )
        self.resolver = VerifiedResolver(self.memory, p, catalog=None, move_data=None)

    def test_actor_resolves_fight_pokemon_and_nickname(self):
        actor = self.resolver.actor(self.profile.attack_mons)
        self.assertEqual(actor.fight_out, FIGHT_OUT_ADDR)
        self.assertEqual(actor.fight_pokemon, FIGHT_POKEMON_ADDR)
        self.assertEqual(actor.nickname, "SALAMENCE")

    def test_opponent_full_name_uses_authoritative_trainer_kind_title(self):
        p = self.profile
        trainer = p.fight_floor_root + 0x6EF0 + 0x14 + 0x64
        trainer_id = 3
        deck = 0x80710000
        kinds = 0x80720000
        count_pointer = 0x80730000
        work = 0x80740000
        table = 0x80741000
        kind = 7
        title_id = 45678

        self.backend.put(trainer, be16(trainer_id))
        self.backend.put(trainer + 4, gschar("EDDY"))
        self.backend.put(p.deck_trainer_pointer, be32(deck))
        self.backend.put(p.deck_trainer_size, be32(10))
        self.backend.put(
            deck + trainer_id * p.deck_trainer_stride + p.deck_trainer_kind_offset,
            bytes([kind]),
        )
        self.backend.put(p.trainer_kind_data_pointer, be32(kinds))
        self.backend.put(p.trainer_kind_count_pointer, be32(count_pointer))
        self.backend.put(count_pointer, be32(20))
        self.backend.put(
            kinds + kind * p.trainer_kind_stride + p.trainer_kind_title_id_offset,
            be32(title_id),
        )
        self.backend.put(p.manager_root, be32(work))
        self.backend.put(work + 4, be32(table))
        self.backend.put(table, be16(0))
        self.backend.put(table + 4, be16(1))
        self.backend.put(table + 8, be32(0))
        self.backend.put(table + 0x10, be32(title_id))
        self.backend.put(table + 0x14, be32(0x40))
        self.backend.put(table + 0x40, gschar("COOL TRAINER"))

        self.assertEqual(
            self.resolver.opponent_trainer_full_name(), "Cool Trainer Eddy"
        )
    def _plant_party_pokemon(self, side, trainer, slot, nickname, level,
                             personality=0x11223344, species=25):
        """Write a party Pokemon into its real FightTrainer party cell, so
        the address arithmetic that derives (side, trainer, slot) is
        exercised rather than bypassed."""
        p = self.profile
        fight_pokemon = party_slot_address(p, side, trainer, slot)
        embedded = fight_pokemon + p.fight_pokemon_embedded_offset
        self.backend.put(fight_pokemon + p.health_nickname_offset,
                         gschar(nickname))
        self.backend.put(embedded + p.pokemon_level_offset, bytes([level]))
        self.backend.put(embedded + p.pokemon_personality_offset,
                         be32(personality))
        self.backend.put(embedded + p.pokemon_species_offset, be16(species))
        return fight_pokemon

    def test_level_sample_reads_the_exp_recipient_not_the_attacker(self):
        # The reported bug: in a double battle where both party members
        # level, the two announcements named each other's Pokemon, because
        # level_sample() read _ATTACK_MONS. WS_GET_EXP publishes the real
        # recipient in get_exp_fight_pokemon_ptr for exactly the span in
        # which 20003/20006 are displayed.
        p = self.profile
        recipient = self._plant_party_pokemon(0, 0, 1, "TEDDIURSA", 19)
        # The attacker is a DIFFERENT party member, planted at the address
        # the old implementation would have read.
        attacker = self._plant_party_pokemon(0, 0, 0, "JOLTEON", 14)
        self.backend.put(p.attack_mons, be32(FIGHT_OUT_ADDR))
        self.backend.put(
            FIGHT_OUT_ADDR + p.fight_out_pokemon_offset, be32(attacker))
        self.backend.put(p.exp_recipient_pointer_address, be32(recipient))

        sample = self.resolver.level_sample()
        self.assertEqual(sample.level, 19)
        self.assertEqual(sample.recipient.nickname, "TEDDIURSA")
        self.assertEqual(sample.recipient.party, PartyPosition(0, 0, 1))

    def test_level_sample_refuses_an_unset_recipient(self):
        # Falling back to _ATTACK_MONS would reintroduce the bug silently.
        self.backend.put(self.profile.exp_recipient_pointer_address, be32(0))
        with self.assertRaises(MemoryError):
            self.resolver.level_sample()


if __name__ == "__main__":
    unittest.main()
