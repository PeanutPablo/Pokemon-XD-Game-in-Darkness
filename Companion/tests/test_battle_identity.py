"""Canonical battle-identity coverage (Phase 2).

Everything here runs against synthetic memory laid out at the REAL
addresses `profile.XD_US_REV0` specifies, so the party-array arithmetic
that derives (side, trainer, slot) is exercised rather than stubbed. That
matters: the bug class this module exists to kill -- naming the wrong
Pokemon -- is exactly the class a stubbed resolver cannot catch, which is
how `level_sample()` shipped reading `_ATTACK_MONS` for two months.
"""
import io
import logging
import unittest

from battle_narrator.battle_identity import (
    AMBIGUOUS,
    FOE,
    PLAYER,
    RESOLVED,
    BattleIdentityResolver,
    BattlefieldSlotTracker,
    IdentityLabeller,
    PartyPosition,
    party_position,
    party_slot_address,
)
from battle_narrator.health import (
    BattlerIdentity as HealthIdentity,
    BattlerSample,
    HealthMemorySource,
    HealthTracker,
    owner_for_battler,
    recovery_sentence,
)
from battle_narrator.memory import MemoryReader
from battle_narrator.profile import XD_US_REV0


def be16(value):
    return value.to_bytes(2, "big")


def be32(value):
    return value.to_bytes(4, "big")


def gschar(text):
    return b"".join(be16(ord(char)) for char in text) + b"\0\0"


def logger():
    value = logging.getLogger(f"identity-{id(object())}")
    value.handlers.clear()
    value.addHandler(logging.StreamHandler(io.StringIO()))
    value.setLevel(logging.DEBUG)
    return value


class Backend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + n, 0) for n in range(size))


# Somewhere well clear of the fight-floor structures, for the transient
# FightOutPokemon wrappers.
WRAPPER_BASE = 0x80900000
WRAPPER_STRIDE = 0x1000


class Battlefield:
    """A synthetic battle: party Pokemon in their real party cells, plus an
    active-battler array pointing at wrappers that point back at them."""

    def __init__(self):
        self.backend = Backend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.resolver = BattleIdentityResolver(self.memory, self.profile)
        self._wrappers = 0

    def party(self, side, trainer, slot, nickname, level=20,
              personality=None, species=25, hp=40, max_hp=40):
        p = self.profile
        fight_pokemon = party_slot_address(p, side, trainer, slot)
        embedded = fight_pokemon + p.fight_pokemon_embedded_offset
        if personality is None:
            personality = 0x1000 + side * 0x100 + trainer * 0x10 + slot
        self.backend.put(
            fight_pokemon + p.health_nickname_offset, gschar(nickname))
        self.backend.put(embedded + p.pokemon_level_offset, bytes([level]))
        self.backend.put(
            embedded + p.pokemon_personality_offset, be32(personality))
        self.backend.put(embedded + p.pokemon_species_offset, be16(species))
        self.backend.put(embedded + p.pokemon_current_hp_offset, be16(hp))
        self.backend.put(embedded + p.pokemon_max_hp_offset, be16(max_hp))
        return fight_pokemon

    def wrapper(self, fight_pokemon):
        self._wrappers += 1
        address = WRAPPER_BASE + self._wrappers * WRAPPER_STRIDE
        self.backend.put(
            address + self.profile.fight_out_fight_pokemon_offset,
            be32(fight_pokemon))
        return address

    def field(self, *occupants):
        """Set the active battler array. `occupants` are FightOutPokemon
        addresses or None for an empty slot."""
        p = self.profile
        base = p.fight_floor_root + p.active_battler_array_offset
        for slot in range(p.active_battler_slots):
            value = occupants[slot] if slot < len(occupants) else 0
            self.backend.put(base + slot * 4, be32(value or 0))

    def exp_recipient(self, fight_pokemon):
        self.backend.put(
            self.profile.exp_recipient_pointer_address,
            be32(fight_pokemon or 0))

    def send_out_globals(self, **names):
        """`send_out_globals(my_mons="JOLTEON", enemy_mons=...)`."""
        p = self.profile
        cursor = 0x80950000
        for attribute, text in names.items():
            if text is None:
                self.backend.put(getattr(p, attribute), be32(0))
                continue
            self.backend.put(cursor, gschar(text))
            self.backend.put(getattr(p, attribute), be32(cursor))
            cursor += 0x100

    def trainer_globals(self, trainer_class, trainer_name):
        p = self.profile
        self.backend.put(0x80960000, gschar(trainer_class))
        self.backend.put(p.trainer_type_name, be32(0x80960000))
        self.backend.put(0x80960100, gschar(trainer_name))
        self.backend.put(p.trainer_personal_name, be32(0x80960100))


class PartyGeometryTests(unittest.TestCase):
    def test_side_zero_trainer_zero_slot_zero_matches_the_standalone_constant(self):
        # These were derived independently and MUST agree. When this test
        # was first written they did not: the standalone constant was 0xA04
        # while the component sum is 0x14 + 0x64 + 0x97C = 0x9F4, each term
        # confirmed by disassembly (fightFloor_GetFightSidePtr,
        # fightSide_GetFightTrainerPtr, fightTrainer_GetFightPokemonPtr).
        # The constant was wrong and was corrected; this test is what keeps
        # the two from silently drifting apart again.
        p = XD_US_REV0
        self.assertEqual(
            party_slot_address(p, 0, 0, 0),
            p.fight_floor_root + p.fight_trainer_first_pokemon_offset)
        self.assertEqual(p.fight_trainer_first_pokemon_offset, 0x9F4)

    def test_every_party_cell_round_trips_to_its_own_position(self):
        p = XD_US_REV0
        for side in range(p.fight_sides):
            for trainer in range(p.fight_trainers_per_side):
                for slot in range(p.fight_trainer_party_slots):
                    address = party_slot_address(p, side, trainer, slot)
                    self.assertEqual(
                        party_position(p, address),
                        PartyPosition(side, trainer, slot))

    def test_an_address_inside_but_not_on_a_cell_is_not_a_party_position(self):
        # Treating a mid-record address as a party slot would invent a
        # position for something that is not a party Pokemon at all.
        p = XD_US_REV0
        self.assertIsNone(
            party_position(p, party_slot_address(p, 0, 0, 0) + 4))

    def test_addresses_outside_every_party_range_return_none(self):
        self.assertIsNone(party_position(XD_US_REV0, 0x80900000))
        self.assertIsNone(party_position(XD_US_REV0, 0))
        self.assertIsNone(party_position(XD_US_REV0, None))

    def test_side_is_derived_not_assumed_from_array_order(self):
        p = XD_US_REV0
        self.assertTrue(party_position(p, party_slot_address(p, 0, 1, 3))
                        .is_player_side)
        self.assertFalse(party_position(p, party_slot_address(p, 1, 0, 0))
                         .is_player_side)


class IdentityResolutionTests(unittest.TestCase):
    def setUp(self):
        self.battle = Battlefield()

    def test_resolves_full_identity_from_a_battler_wrapper(self):
        pokemon = self.battle.party(
            1, 0, 2, "GARDEVOIR", level=31, personality=0xDEADBEEF,
            species=282)
        wrapper = self.battle.wrapper(pokemon)
        identity = self.battle.resolver.from_fight_out(wrapper, battler_slot=3)
        self.assertEqual(identity.resolution, RESOLVED)
        self.assertEqual(identity.party, PartyPosition(1, 0, 2))
        self.assertEqual(identity.nickname, "GARDEVOIR")
        self.assertEqual(identity.personality, 0xDEADBEEF)
        self.assertEqual(identity.species, 282)
        self.assertEqual(identity.level, 31)
        self.assertEqual(identity.battler_slot, 3)
        self.assertEqual(identity.owner, FOE)

    def test_a_detached_wrapper_has_no_identity(self):
        # A fainted or withdrawing battler keeps its wrapper with no
        # Pokemon attached. It must not inherit the previous occupant's.
        wrapper = self.battle.wrapper(0)
        identity = self.battle.resolver.from_fight_out(wrapper, battler_slot=0)
        self.assertEqual(identity.resolution, AMBIGUOUS)
        self.assertIsNone(identity.personality)

    def test_two_identical_species_have_different_keys(self):
        first = self.battle.party(1, 0, 0, "GARDEVOIR", personality=0xAAAA1111,
                                  species=282)
        second = self.battle.party(1, 0, 1, "GARDEVOIR", personality=0xBBBB2222,
                                   species=282)
        a = self.battle.resolver.from_fight_pokemon(first)
        b = self.battle.resolver.from_fight_pokemon(second)
        self.assertEqual(a.species, b.species)
        self.assertEqual(a.nickname, b.nickname)
        self.assertNotEqual(a.key, b.key)

    def test_active_battlers_skip_empty_and_detached_slots(self):
        one = self.battle.wrapper(self.battle.party(0, 0, 0, "JOLTEON"))
        detached = self.battle.wrapper(0)
        two = self.battle.wrapper(self.battle.party(1, 0, 0, "ODDISH"))
        self.battle.field(one, 0, detached, two)
        identities = self.battle.resolver.active_battlers()
        self.assertEqual([i.nickname for i in identities],
                         ["JOLTEON", "ODDISH"])
        self.assertEqual([i.battler_slot for i in identities], [0, 3])


class SendOutTests(unittest.TestCase):
    def setUp(self):
        self.battle = Battlefield()

    def test_names_follow_the_template_opcode_order(self):
        # 20313 prints 0x15 then 0x14.
        self.battle.send_out_globals(
            my_mons="TEDDIURSA", my_mons2="JOLTEON")
        self.assertEqual(
            self.battle.resolver.send_out_names((0x15, 0x00, 0x14)),
            ("JOLTEON", "TEDDIURSA"))
        # 20305 prints 0x16 then 0x17, the other way round.
        self.battle.send_out_globals(
            enemy_mons="CORPHISH", enemy_mons2="SWABLU")
        self.assertEqual(
            self.battle.resolver.send_out_names((0x22, 0x23, 0x16, 0x17)),
            ("CORPHISH", "SWABLU"))

    def test_a_pairs_second_global_is_the_fallback_for_the_first(self):
        # The writer stores each entering Pokemon into BOTH members of a
        # pair, so either read works; only one being populated must still
        # yield the name.
        self.battle.send_out_globals(my_mons=None, enemy_mons="PINECO")
        self.assertEqual(
            self.battle.resolver.send_out_names((0x14,)), ("PINECO",))

    def test_initial_opponent_send_out_matches_the_live_battler(self):
        oddish = self.battle.party(1, 0, 0, "ODDISH")
        self.battle.field(self.battle.wrapper(oddish))
        self.battle.send_out_globals(enemy_mons="ODDISH")
        self.battle.trainer_globals("CIPHER PEON", "GREESIX")
        event = self.battle.resolver.send_out_event(FOE, (0x16,))
        self.assertEqual(event.names, ("ODDISH",))
        self.assertEqual(event.identities[0].party, PartyPosition(1, 0, 0))
        self.assertEqual(event.trainer_label, "Cipher Peon Greesix")

    def test_mid_battle_opponent_replacement_is_not_the_first_party_slot(self):
        # The reported failure. The trainer's party still starts with
        # Shroomish; the Pokemon entering is Pineco from slot 4.
        self.battle.party(1, 0, 0, "SHROOMISH")
        pineco = self.battle.party(1, 0, 4, "PINECO")
        self.battle.field(self.battle.wrapper(pineco))
        self.battle.send_out_globals(enemy_mons="PINECO")
        event = self.battle.resolver.send_out_event(FOE, (0x16,))
        self.assertEqual(event.names, ("PINECO",))
        self.assertEqual(event.identities[0].party, PartyPosition(1, 0, 4))

    def test_player_mid_battle_replacement_resolves_on_the_player_side(self):
        self.battle.party(0, 0, 0, "JOLTEON")
        silcoon = self.battle.party(0, 0, 3, "SILCOON")
        self.battle.field(self.battle.wrapper(silcoon))
        self.battle.send_out_globals(my_mons="SILCOON")
        event = self.battle.resolver.send_out_event(PLAYER, (0x14,))
        self.assertEqual(event.identities[0].party, PartyPosition(0, 0, 3))

    def test_a_send_out_never_matches_a_battler_on_the_other_side(self):
        # Same nickname on both sides: the side filter is what keeps them
        # apart, and it is derived from the address, not from the global.
        self.battle.party(0, 0, 0, "ODDISH")
        foe = self.battle.party(1, 0, 0, "ODDISH")
        self.battle.field(
            self.battle.wrapper(party_slot_address(XD_US_REV0, 0, 0, 0)),
            self.battle.wrapper(foe))
        self.battle.send_out_globals(enemy_mons="ODDISH")
        event = self.battle.resolver.send_out_event(FOE, (0x16,))
        self.assertEqual(event.identities[0].party, PartyPosition(1, 0, 0))

    def test_two_identical_nicknames_on_one_side_stay_unresolved(self):
        # Picking either would be a coin flip. The NAME is still returned,
        # because it came from the game and is not wrong -- only the
        # live-record attribution is withheld.
        first = self.battle.party(1, 0, 0, "GARDEVOIR", personality=0xA1)
        second = self.battle.party(1, 0, 1, "GARDEVOIR", personality=0xB2)
        self.battle.field(
            self.battle.wrapper(first), self.battle.wrapper(second))
        self.battle.send_out_globals(enemy_mons="GARDEVOIR")
        event = self.battle.resolver.send_out_event(FOE, (0x16,))
        self.assertEqual(event.names, ("GARDEVOIR",))
        self.assertIsNone(event.identities[0])

    def test_identical_species_with_different_nicknames_both_resolve(self):
        first = self.battle.party(1, 0, 0, "ROSE", species=282,
                                  personality=0xA1)
        second = self.battle.party(1, 0, 1, "THORN", species=282,
                                   personality=0xB2)
        self.battle.field(
            self.battle.wrapper(first), self.battle.wrapper(second))
        self.battle.send_out_globals(enemy_mons="ROSE", enemy_mons2="THORN")
        event = self.battle.resolver.send_out_event(FOE, (0x16, 0x17))
        self.assertEqual(
            [i.party for i in event.identities],
            [PartyPosition(1, 0, 0), PartyPosition(1, 0, 1)])

    def test_two_trainers_on_one_side_are_distinguished_by_trainer_index(self):
        a = self.battle.party(1, 0, 0, "KOFFING", personality=0xA1)
        b = self.battle.party(1, 1, 0, "GRIMER", personality=0xB2)
        self.battle.field(self.battle.wrapper(a), self.battle.wrapper(b))
        identities = self.battle.resolver.active_battlers()
        self.assertEqual([i.party.trainer for i in identities], [0, 1])


class LevelUpRecipientTests(unittest.TestCase):
    def setUp(self):
        self.battle = Battlefield()

    def test_recipient_comes_from_the_exp_pointer_not_the_active_array(self):
        jolteon = self.battle.party(0, 0, 0, "JOLTEON", level=14)
        teddiursa = self.battle.party(0, 0, 1, "TEDDIURSA", level=19)
        self.battle.field(
            self.battle.wrapper(jolteon), self.battle.wrapper(teddiursa))
        self.battle.exp_recipient(teddiursa)
        identity = self.battle.resolver.resolve_level_up_recipient()
        self.assertEqual(identity.nickname, "TEDDIURSA")
        self.assertEqual(identity.level, 19)
        self.assertEqual(identity.party, PartyPosition(0, 0, 1))

    def test_two_recipients_in_sequence_resolve_independently(self):
        # WS_GET_EXP loops over the party, setting and clearing the pointer
        # once per recipient. Order need not match the battler array.
        jolteon = self.battle.party(0, 0, 0, "JOLTEON", level=14)
        teddiursa = self.battle.party(0, 0, 1, "TEDDIURSA", level=19)
        self.battle.field(
            self.battle.wrapper(jolteon), self.battle.wrapper(teddiursa))
        seen = []
        for recipient in (teddiursa, jolteon):
            self.battle.exp_recipient(recipient)
            seen.append(
                self.battle.resolver.resolve_level_up_recipient().nickname)
        self.assertEqual(seen, ["TEDDIURSA", "JOLTEON"])

    def test_recipient_carries_its_battlefield_slot_when_it_is_on_the_field(self):
        jolteon = self.battle.party(0, 0, 0, "JOLTEON")
        self.battle.field(0, self.battle.wrapper(jolteon))
        self.battle.exp_recipient(jolteon)
        identity = self.battle.resolver.resolve_level_up_recipient()
        self.assertEqual(identity.battler_slot, 1)

    def test_an_off_field_recipient_still_resolves(self):
        # Exp. Share, or a participant that fainted. Absence from the field
        # must not downgrade the identity.
        active = self.battle.party(0, 0, 0, "JOLTEON")
        benched = self.battle.party(0, 0, 5, "BALTOY", level=18)
        self.battle.field(self.battle.wrapper(active))
        self.battle.exp_recipient(benched)
        identity = self.battle.resolver.resolve_level_up_recipient()
        self.assertEqual(identity.resolution, RESOLVED)
        self.assertEqual(identity.nickname, "BALTOY")
        self.assertIsNone(identity.battler_slot)

    def test_duplicate_species_recipients_are_told_apart_by_personality(self):
        first = self.battle.party(0, 0, 0, "EEVEE", species=133,
                                  personality=0xAAAA, level=10)
        second = self.battle.party(0, 0, 1, "EEVEE", species=133,
                                   personality=0xBBBB, level=12)
        self.battle.field(
            self.battle.wrapper(first), self.battle.wrapper(second))
        self.battle.exp_recipient(second)
        identity = self.battle.resolver.resolve_level_up_recipient()
        self.assertEqual(identity.personality, 0xBBBB)
        self.assertEqual(identity.party, PartyPosition(0, 0, 1))

    def test_an_unset_pointer_is_ambiguous_rather_than_a_guess(self):
        self.battle.party(0, 0, 0, "JOLTEON")
        self.battle.exp_recipient(0)
        self.assertEqual(
            self.battle.resolver.resolve_level_up_recipient().resolution,
            AMBIGUOUS)


class SlotTrackerTests(unittest.TestCase):
    def setUp(self):
        self.battle = Battlefield()
        self.tracker = BattlefieldSlotTracker(
            self.battle.resolver, XD_US_REV0, logger())

    def settle(self, times=None):
        for _ in range(times or XD_US_REV0.identity_stable_samples):
            changed = self.tracker.poll()
        return changed

    def test_an_occupant_is_not_published_until_it_is_stable(self):
        wrapper = self.battle.wrapper(self.battle.party(0, 0, 0, "JOLTEON"))
        self.battle.field(wrapper)
        self.tracker.poll()
        self.assertIsNone(self.tracker.identity_for_slot(0))
        self.tracker.poll()
        self.assertEqual(
            self.tracker.identity_for_slot(0).nickname, "JOLTEON")

    def test_a_replacement_advances_the_epoch_immediately(self):
        first = self.battle.wrapper(self.battle.party(0, 0, 0, "JOLTEON"))
        second = self.battle.wrapper(self.battle.party(0, 0, 1, "TEDDIURSA"))
        self.battle.field(first)
        self.settle()
        before = self.tracker.epoch_for_slot(0)
        stale = self.tracker.identity_for_slot(0)
        self.battle.field(second)
        self.tracker.poll()
        # Epoch moves on the FIRST sight of the change, before the new
        # occupant has settled -- that is what lets a consumer reject a
        # reading that belongs to the outgoing Pokemon.
        self.assertEqual(self.tracker.epoch_for_slot(0), before + 1)
        self.assertFalse(self.tracker.is_current(stale))
        # And nothing is published in the gap, so no consumer can read the
        # outgoing Pokemon as if it were still out.
        self.assertIsNone(self.tracker.identity_for_slot(0))

    def test_the_new_occupant_publishes_once_it_settles(self):
        first = self.battle.wrapper(self.battle.party(0, 0, 0, "JOLTEON"))
        second = self.battle.wrapper(self.battle.party(0, 0, 1, "TEDDIURSA"))
        self.battle.field(first)
        self.settle()
        self.battle.field(second)
        self.settle()
        settled = self.tracker.identity_for_slot(0)
        self.assertEqual(settled.nickname, "TEDDIURSA")
        self.assertTrue(self.tracker.is_current(settled))

    def test_a_faint_to_empty_slot_vacates_and_bumps_the_epoch(self):
        wrapper = self.battle.wrapper(self.battle.party(0, 0, 0, "JOLTEON"))
        self.battle.field(wrapper)
        self.settle()
        stale = self.tracker.identity_for_slot(0)
        self.battle.field(0)
        self.tracker.poll()
        self.assertIsNone(self.tracker.identity_for_slot(0))
        self.assertFalse(self.tracker.is_current(stale))

    def test_faint_then_replacement_yields_one_clean_generation(self):
        first = self.battle.wrapper(self.battle.party(0, 0, 0, "JOLTEON"))
        second = self.battle.wrapper(self.battle.party(0, 0, 1, "TEDDIURSA"))
        self.battle.field(first)
        self.settle()
        original = self.tracker.identity_for_slot(0)
        self.battle.field(0)
        self.tracker.poll()
        self.battle.field(second)
        self.settle()
        settled = self.tracker.identity_for_slot(0)
        self.assertEqual(settled.nickname, "TEDDIURSA")
        # A distinct, later generation -- the epoch is a token, not a count,
        # so what matters is that it cannot be confused with the first.
        self.assertGreater(settled.epoch, original.epoch)
        self.assertTrue(self.tracker.is_current(settled))
        self.assertFalse(self.tracker.is_current(original))

    def test_baton_pass_keeps_the_wrapper_and_swaps_the_pokemon(self):
        # Baton Pass is implemented as a switch that preserves the on-field
        # wrapper (that is where the stat stages live, at +0x7B0), changing
        # only the FightPokemon behind it. The two Pokemon must NOT merge
        # into one identity just because the wrapper address is unchanged.
        p = XD_US_REV0
        outgoing = self.battle.party(0, 0, 0, "JOLTEON")
        incoming = self.battle.party(0, 0, 2, "FLAAFFY")
        wrapper = self.battle.wrapper(outgoing)
        self.battle.field(wrapper)
        self.settle()
        before = self.tracker.identity_for_slot(0)
        self.battle.backend.put(
            wrapper + p.fight_out_fight_pokemon_offset, be32(incoming))
        self.settle()
        after = self.tracker.identity_for_slot(0)
        self.assertEqual(before.fight_out, after.fight_out)
        self.assertNotEqual(before.key, after.key)
        self.assertEqual(after.nickname, "FLAAFFY")
        self.assertEqual(after.party, PartyPosition(0, 0, 2))
        self.assertFalse(self.tracker.is_current(before))

    def test_baton_pass_then_an_ordinary_switch_keeps_ordering_correct(self):
        p = XD_US_REV0
        jolteon = self.battle.party(0, 0, 0, "JOLTEON")
        flaaffy = self.battle.party(0, 0, 2, "FLAAFFY")
        houndour = self.battle.party(0, 0, 4, "HOUNDOUR")
        wrapper = self.battle.wrapper(jolteon)
        self.battle.field(wrapper)
        self.settle()
        self.battle.backend.put(
            wrapper + p.fight_out_fight_pokemon_offset, be32(flaaffy))
        self.settle()
        later = self.battle.wrapper(houndour)
        self.battle.field(later)
        self.settle()
        settled = self.tracker.identity_for_slot(0)
        self.assertEqual(settled.nickname, "HOUNDOUR")
        self.assertEqual(settled.party, PartyPosition(0, 0, 4))

    def test_baton_pass_then_faint_and_replacement(self):
        p = XD_US_REV0
        jolteon = self.battle.party(0, 0, 0, "JOLTEON")
        flaaffy = self.battle.party(0, 0, 2, "FLAAFFY")
        onix = self.battle.party(0, 0, 5, "ONIX")
        wrapper = self.battle.wrapper(jolteon)
        self.battle.field(wrapper)
        self.settle()
        self.battle.backend.put(
            wrapper + p.fight_out_fight_pokemon_offset, be32(flaaffy))
        self.settle()
        self.battle.field(0)
        self.tracker.poll()
        self.battle.field(self.battle.wrapper(onix))
        self.settle()
        self.assertEqual(self.tracker.identity_for_slot(0).nickname, "ONIX")

    def test_active_array_reconstruction_reassigns_slots_without_merging(self):
        # The array is documented to compact after a faint. Slot index is
        # therefore not identity; the pointer pair is.
        a = self.battle.wrapper(self.battle.party(0, 0, 0, "JOLTEON"))
        b = self.battle.wrapper(self.battle.party(1, 0, 0, "ODDISH"))
        self.battle.field(a, b)
        self.settle()
        self.battle.field(b, 0)
        self.settle()
        moved = self.tracker.identity_for_slot(0)
        self.assertEqual(moved.nickname, "ODDISH")
        self.assertIsNone(self.tracker.identity_for_slot(1))

    def test_an_ordinary_switch_publishes_the_incoming_pokemon(self):
        out = self.battle.wrapper(self.battle.party(0, 0, 0, "JOLTEON"))
        incoming = self.battle.wrapper(self.battle.party(0, 0, 3, "SILCOON"))
        self.battle.field(out)
        self.settle()
        self.battle.field(incoming)
        self.settle()
        self.assertEqual(
            self.tracker.identity_for_slot(0).party, PartyPosition(0, 0, 3))

    def test_a_forced_switch_behaves_the_same_as_a_chosen_one(self):
        # Whirlwind/Roar replace the occupant without the owner choosing.
        # Nothing about identity depends on who initiated it.
        out = self.battle.wrapper(self.battle.party(1, 0, 0, "ODDISH"))
        dragged = self.battle.wrapper(self.battle.party(1, 0, 5, "CACNEA"))
        self.battle.field(out)
        self.settle()
        stale = self.tracker.identity_for_slot(0)
        self.battle.field(dragged)
        self.settle()
        settled = self.tracker.identity_for_slot(0)
        self.assertEqual(settled.nickname, "CACNEA")
        self.assertFalse(self.tracker.is_current(stale))

    def test_doubles_keep_four_independent_generations(self):
        mine = [self.battle.party(0, 0, i, name)
                for i, name in enumerate(("JOLTEON", "TEDDIURSA"))]
        theirs = [self.battle.party(1, 0, i, name)
                  for i, name in enumerate(("CORPHISH", "SWABLU"))]
        wrappers = [self.battle.wrapper(x) for x in mine + theirs]
        self.battle.field(*wrappers)
        self.settle()
        identities = self.tracker.identities()
        self.assertEqual(
            [i.nickname for i in identities],
            ["JOLTEON", "TEDDIURSA", "CORPHISH", "SWABLU"])
        self.assertEqual(
            [i.owner for i in identities], [PLAYER, PLAYER, FOE, FOE])
        # Replacing one slot leaves the other three generations untouched.
        before = {i.battler_slot: i.epoch for i in identities}
        replacement = self.battle.wrapper(
            self.battle.party(1, 0, 2, "SPOINK"))
        self.battle.field(wrappers[0], wrappers[1], wrappers[2], replacement)
        self.settle()
        after = {i.battler_slot: i.epoch for i in self.tracker.identities()}
        self.assertEqual(
            [after[s] for s in (0, 1, 2)], [before[s] for s in (0, 1, 2)])
        self.assertGreater(after[3], before[3])

    def test_clear_resets_every_epoch(self):
        self.battle.field(
            self.battle.wrapper(self.battle.party(0, 0, 0, "JOLTEON")))
        self.settle()
        self.tracker.clear("battle ended")
        self.assertEqual(self.tracker.identities(), [])
        self.assertEqual(self.tracker.epoch_for_slot(0), 0)


class LabellingTests(unittest.TestCase):
    def setUp(self):
        self.battle = Battlefield()
        self.labeller = IdentityLabeller()

    def identity(self, side, trainer, slot, nickname, **kwargs):
        pokemon = self.battle.party(side, trainer, slot, nickname, **kwargs)
        return self.battle.resolver.from_fight_pokemon(pokemon)

    def test_a_unique_nickname_is_spoken_bare(self):
        me = self.identity(0, 0, 0, "JOLTEON")
        foe = self.identity(1, 0, 0, "ODDISH")
        self.assertEqual(self.labeller.label(me, [me, foe]), "Jolteon")

    def test_a_clash_across_sides_is_resolved_by_the_side_word(self):
        me = self.identity(0, 0, 0, "ODDISH", personality=0xA1)
        foe = self.identity(1, 0, 0, "ODDISH", personality=0xB2)
        peers = [me, foe]
        self.assertEqual(self.labeller.label(me, peers), "your Oddish")
        self.assertEqual(self.labeller.label(foe, peers), "the foe's Oddish")

    def test_a_clash_within_one_side_uses_first_appearance_order(self):
        first = self.identity(1, 0, 0, "GARDEVOIR", personality=0xA1)
        second = self.identity(1, 0, 1, "GARDEVOIR", personality=0xB2)
        self.labeller.note(first)
        self.labeller.note(second)
        peers = [first, second]
        self.assertEqual(
            self.labeller.label(first, peers), "the foe's first Gardevoir")
        self.assertEqual(
            self.labeller.label(second, peers), "the foe's second Gardevoir")

    def test_appearance_order_does_not_change_when_slots_reorder(self):
        first = self.identity(1, 0, 0, "GARDEVOIR", personality=0xA1)
        second = self.identity(1, 0, 1, "GARDEVOIR", personality=0xB2)
        self.labeller.note(first)
        self.labeller.note(second)
        before = self.labeller.label(second, [first, second])
        # Re-noting in the opposite order must not renumber anything.
        self.labeller.note(second)
        self.labeller.note(first)
        self.assertEqual(self.labeller.label(second, [second, first]), before)

    def test_an_unseen_clashing_identity_is_refused_rather_than_guessed(self):
        first = self.identity(1, 0, 0, "GARDEVOIR", personality=0xA1)
        second = self.identity(1, 0, 1, "GARDEVOIR", personality=0xB2)
        # Neither noted: no appearance order exists, so there is no
        # authoritative way to tell them apart.
        self.assertIsNone(self.labeller.label(first, [first, second]))

    def test_distinct_nicknames_never_escalate(self):
        first = self.identity(1, 0, 0, "ROSE", species=282, personality=0xA1)
        second = self.identity(1, 0, 1, "THORN", species=282, personality=0xB2)
        peers = [first, second]
        self.assertEqual(self.labeller.label(first, peers), "Rose")
        self.assertEqual(self.labeller.label(second, peers), "Thorn")


class HealthOwnershipTests(unittest.TestCase):
    """The `recovery_sentence` prefix used a fixed slot->side tuple. Two
    project documents recorded opposite interleavings of the active array,
    so it could not have been right in both. It is derived now."""

    def sample(self, fight_pokemon, slot, owner=None):
        return BattlerSample(
            HealthIdentity(slot, 0x80900000, fight_pokemon,
                           fight_pokemon + 4),
            "KINGDRA", 79, 155, 0, 30, 0, (), owner)

    def test_owner_is_derived_from_the_party_address(self):
        p = XD_US_REV0
        player = self.sample(party_slot_address(p, 0, 0, 1), slot=3)
        foe = self.sample(party_slot_address(p, 1, 0, 0), slot=0)
        self.assertEqual(owner_for_battler(p, player), "Player")
        self.assertEqual(owner_for_battler(p, foe), "Opponent")

    def test_the_derived_owner_disagrees_with_the_positional_tuple(self):
        # Slot 3 is "Opponent" in profile.summary_slot_ownership, but this
        # battler physically lives in the PLAYER's party array. The address
        # wins.
        p = XD_US_REV0
        player = self.sample(party_slot_address(p, 0, 0, 1), slot=3)
        self.assertEqual(
            recovery_sentence(p, player, 49, 79).split()[0], "Player")

    def test_an_off_party_pointer_falls_back_without_raising(self):
        p = XD_US_REV0
        stray = self.sample(0x80900000, slot=0)
        self.assertIn(owner_for_battler(p, stray),
                      {"Player", "Opponent", "Battler"})


class HealthSourceOwnerTests(unittest.TestCase):
    def test_sampled_battlers_carry_a_derived_owner(self):
        battle = Battlefield()
        p = XD_US_REV0
        player = battle.party(0, 0, 0, "JOLTEON", level=14, hp=30, max_hp=40)
        foe = battle.party(1, 0, 0, "ODDISH", level=12, hp=20, max_hp=25)
        battle.field(battle.wrapper(player), battle.wrapper(foe))
        source = HealthMemorySource(battle.memory, p)
        owners = [b.owner for b in source.battlers()]
        self.assertEqual(owners, ["Player", "Opponent"])


class NoFalseHealthDuringReplacementTests(unittest.TestCase):
    """A replacement must re-baseline silently. Announcing the difference
    between the outgoing and incoming Pokemon's HP as healing or damage is
    the "health for the wrong Pokemon" symptom."""

    def test_a_healthier_replacement_produces_no_event(self):
        battle = Battlefield()
        p = XD_US_REV0
        hurt = battle.party(0, 0, 0, "JOLTEON", level=14, hp=5, max_hp=40)
        fresh = battle.party(0, 0, 1, "TEDDIURSA", level=19, hp=45, max_hp=45)
        source = HealthMemorySource(battle.memory, p)
        tracker = HealthTracker(source, p, logger())
        battle.field(battle.wrapper(hurt))
        for _ in range(3):
            self.assertEqual(tracker.poll(), [])
        battle.field(battle.wrapper(fresh))
        for _ in range(3):
            self.assertEqual(tracker.poll(), [])


if __name__ == "__main__":
    unittest.main()
