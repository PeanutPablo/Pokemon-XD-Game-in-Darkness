"""Generic battle-message rendering, against REAL shipped templates.

How these fixtures work
-----------------------
Nothing here types a game sentence into Python. `FightCommonCatalog` gives
each message's own encoded GSchar bytes (`Message.raw`); the fixture plants
those bytes into a synthetic runtime string table laid out exactly the way
`GSmsgGetGSchar` reads one, sets the msgvars the message's opcodes name, and
lets `MessageRenderer` decode it. The asserted sentence is therefore a
regression expectation *observed from game data*, not a duplicate of a
production table -- which is the whole point of retiring those tables.

The expected strings below were produced by running this fixture, reading
what the shipped bytes decode to, and pinning it.
"""
import io
import logging
import unittest
from pathlib import Path

from battle_narrator.battle_identity import (
    BattleIdentityResolver, BattlefieldSlotTracker, IdentityLabeller,
    PartyPosition, party_slot_address,
)
from battle_narrator.battle_opcodes import REGISTRY
from battle_narrator.memory import MemoryReader
from battle_narrator.message_render import MessageRenderer
from battle_narrator.messages import FightCommonCatalog
from battle_narrator.narrator import BattleNarrator
from battle_narrator.profile import XD_US_REV0
from battle_narrator.runtime_messages import RuntimeMessageCatalog
from battle_narrator.speech import SpeechCoordinator, SpeechEventClass
from battle_narrator.tasks import TaskSnapshot
from battle_narrator.text_safety import is_double_encoded, repair_double_encoded

EXTRACTION = (Path(__file__).resolve().parents[1] / "_dialogue_extraction")

MANAGER = 0x80200000
TABLE = 0x80210000
SCRATCH = 0x80300000
WRAPPER = 0x80400000


def be16(value):
    return value.to_bytes(2, "big")


def be32(value):
    return value.to_bytes(4, "big")


def gschar(text):
    return b"".join(be16(ord(char)) for char in text) + b"\0\0"


def logger():
    value = logging.getLogger(f"msg-{id(object())}")
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


class SequenceTasks:
    profile = XD_US_REV0

    def __init__(self, sequence):
        self.sequence = iter(sequence)

    def snapshots(self):
        return next(self.sequence)


class Speaker:
    def __init__(self):
        self.spoken = []

    def speak(self, text, interrupt=False):
        self.spoken.append((text, interrupt))
        return True


class Battle:
    """Synthetic memory holding real shipped message bytes."""

    catalog = FightCommonCatalog(EXTRACTION)

    def __init__(self, *message_ids):
        self.backend = Backend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self._cursor = SCRATCH
        self._wrappers = 0
        self.backend.put(self.profile.manager_root, be32(MANAGER))
        self._install(message_ids)
        self.renderer = MessageRenderer(
            self.memory, self.profile,
            RuntimeMessageCatalog(self.memory, self.profile),
            lambda: "LEON")
        self.identity = BattleIdentityResolver(self.memory, self.profile)

    def _install(self, message_ids):
        """Lay out one string table exactly the way GSmsgGetGSchar reads
        it: u16 table id, u16 count, next at +0x08, ascending (id, offset)
        pairs from +0x10."""
        wanted = set(message_ids)
        # Nested lookups the messages themselves perform: side-name
        # qualifiers, and any message spliced in by a mode-2 opcode.
        wanted |= set(range(0x4F67, 0x4F6D))
        entries = sorted(mid for mid in wanted if self.catalog.get(mid))
        self.backend.put(MANAGER + 0x04, be32(TABLE))
        self.backend.put(TABLE + 0x00, be16(0))
        self.backend.put(TABLE + 0x04, be16(len(entries)))
        self.backend.put(TABLE + 0x08, be32(0))
        body = 0x10 + len(entries) * 8
        for index, message_id in enumerate(entries):
            raw = self.catalog.get(message_id).raw
            self.backend.put(TABLE + 0x10 + index * 8, be32(message_id))
            self.backend.put(TABLE + 0x10 + index * 8 + 4, be32(body))
            self.backend.put(TABLE + body, raw)
            body += len(raw)

    def _text(self, value):
        address = self._cursor
        self.backend.put(address, gschar(value))
        self._cursor += 0x200
        return address

    def set_text(self, field, value):
        """Point a text-pointer msgvar at some GSchar text."""
        self.backend.put(getattr(self.profile, field), be32(self._text(value)))

    def set_number(self, field, value, width=4):
        raw = be16(value) if width == 2 else be32(value)
        self.backend.put(getattr(self.profile, field), raw)

    def battler(self, field, nickname, side=1, trainer=0, slot=0, level=20,
                personality=None):
        """Point a FightOutPokemon msgvar at a battler whose persistent
        record really lives in the right trainer's party array."""
        p = self.profile
        fight_pokemon = party_slot_address(p, side, trainer, slot)
        embedded = fight_pokemon + p.fight_pokemon_embedded_offset
        self.backend.put(
            fight_pokemon + p.health_nickname_offset, gschar(nickname))
        self.backend.put(embedded + p.pokemon_level_offset, bytes([level]))
        self.backend.put(embedded + p.pokemon_species_offset, be16(25))
        self.backend.put(
            embedded + p.pokemon_personality_offset,
            be32(personality if personality is not None
                 else 0x100 + side * 16 + slot))
        self._wrappers += 1
        wrapper = WRAPPER + self._wrappers * 0x1000
        self.backend.put(
            wrapper + p.fight_out_fight_pokemon_offset, be32(fight_pokemon))
        if field is not None:
            self.backend.put(getattr(self.profile, field), be32(wrapper))
        return wrapper

    def field(self, *wrappers):
        p = self.profile
        base = p.fight_floor_root + p.active_battler_array_offset
        for slot in range(p.active_battler_slots):
            self.backend.put(
                base + slot * 4,
                be32(wrappers[slot] if slot < len(wrappers) else 0))

    def render(self, message_id):
        return self.renderer.render(message_id)

    def spoken(self, message_id, **kwargs):
        """Run the real narrator over this message and return what it said."""
        speaker = Speaker()
        allocated = [TaskSnapshot(0, 0x80003000, 2, message_id)]
        narrator = BattleNarrator(
            _Connection(), SequenceTasks([allocated] * 2), self.catalog,
            _Resolver(self.identity), speaker, logger(),
            poll_interval=0, renderer=self.renderer, **kwargs)
        narrator.poll_once()
        narrator.poll_once()
        return [text for text, _ in speaker.spoken]


class _Connection:
    def is_readable(self):
        return True


class _Resolver:
    """Only the parts BattleNarrator still asks a resolver for."""

    def __init__(self, identity):
        self.identity = identity
        self.profile = XD_US_REV0

    def send_out_event(self, side, opcodes):
        return self.identity.send_out_event(side, opcodes)


# ---------------------------------------------------------------------------
# Opcode registry
# ---------------------------------------------------------------------------


class RegistryTests(unittest.TestCase):
    def test_every_opcode_fight_common_uses_is_registered(self):
        """The registry is sized by the shipped data, not by what one
        playthrough happened to show."""
        catalog = FightCommonCatalog(EXTRACTION)
        used = {code for message in catalog.messages.values()
                for code in message.opcodes}
        self.assertEqual(sorted(used - set(REGISTRY)), [])

    def test_the_battle_range_is_covered(self):
        for code in range(0x0D, 0x2B):
            self.assertIn(code, REGISTRY, f"0x{code:02X} missing")

    def test_narrow_msgvars_are_declared_two_bytes_wide(self):
        # _Item/_Item2/_Waza/_PokemonID/_Tribe/_Npc are u16 in symbols.txt.
        # Reading one as u32 picks up the neighbouring variable's bytes and
        # yields a plausible-looking wrong ID.
        for code in (0x2D, 0x2E, 0x39, 0x4E, 0x58, 0x59):
            self.assertEqual(REGISTRY[code].width, 2, f"0x{code:02X}")

    def test_argument_widths_are_recorded_for_skipped_opcodes(self):
        # A formatting opcode this project ignores must still know how many
        # argument bytes follow it, or the rest of the string decodes as
        # garbage.
        self.assertEqual(REGISTRY[0x08].extra_bytes, 4)
        for code in (0x07, 0x09, 0x38, 0x52, 0x53, 0x5B, 0x5C):
            self.assertEqual(REGISTRY[code].extra_bytes, 1, f"0x{code:02X}")


# ---------------------------------------------------------------------------
# Real templates -- the reported missing messages
# ---------------------------------------------------------------------------


class StatusMessageTests(unittest.TestCase):
    def one_battler(self, message_id, field, nickname="GARDEVOIR"):
        battle = Battle(message_id)
        battle.battler(field, nickname)
        return battle.render(message_id)

    def test_frozen_solid_attacker_side(self):
        r = self.one_battler(20044, "attack_mons")
        self.assertEqual(r.text, "GARDEVOIR is frozen solid!")

    def test_was_frozen_solid_target_side(self):
        r = self.one_battler(20042, "tsuika_mons")
        self.assertEqual(r.text, "GARDEVOIR was frozen solid!")

    def test_fell_asleep(self):
        r = self.one_battler(20027, "tsuika_mons")
        self.assertEqual(r.text, "GARDEVOIR fell asleep!")

    def test_is_fast_asleep(self):
        r = self.one_battler(20103, "attack_mons")
        self.assertEqual(r.text, "GARDEVOIR is fast asleep.")

    def test_woke_up(self):
        r = self.one_battler(20104, "attack_mons")
        self.assertEqual(r.text, "GARDEVOIR woke up!")

    def test_went_to_sleep(self):
        r = self.one_battler(20074, "attack_mons")
        self.assertEqual(r.text, "GARDEVOIR went to sleep!")

    def test_badly_poisoned(self):
        r = self.one_battler(20036, "tsuika_mons")
        self.assertEqual(r.text, "GARDEVOIR is badly poisoned!")

    def test_immunity_does_not_affect(self):
        r = self.one_battler(20020, "defence_mons")
        self.assertEqual(r.text, "It doesn't affect GARDEVOIR...")

    def test_grew_drowsy_names_both_battlers(self):
        battle = Battle(20176)
        battle.battler("attack_mons", "ESPEON", side=0)
        battle.battler("defence_mons", "ODDISH", side=1)
        self.assertEqual(
            battle.render(20176).text, "ESPEON made ODDISH drowsy!")

    def test_call_pokemon_family(self):
        battle = Battle(20432, 20433, 20435)
        battle.battler("attack_mons", "TEDDIURSA", side=0)
        battle.set_text("my_name", "LEON")
        self.assertEqual(
            battle.render(20432).text, "LEON called TEDDIURSA!")
        self.assertEqual(battle.render(20433).text, "TEDDIURSA!")
        self.assertEqual(
            battle.render(20435).text,
            "TEDDIURSA came to its senses from the TRAINER's call!")

    def test_reverse_mode_messages(self):
        battle = Battle(20450, 20451, 20489)
        battle.battler("attack_mons", "HOUNDOUR")
        self.assertEqual(
            battle.render(20451).text, "HOUNDOUR is in REVERSE MODE!")
        self.assertEqual(
            battle.render(20489).text,
            "The REVERSE MODE attack hurts HOUNDOUR!")
        self.assertEqual(
            battle.render(20450).text,
            "HOUNDOUR's emotions rose to a fever pitch! "
            "It entered REVERSE MODE!")


class ShadowMessageTests(unittest.TestCase):
    def test_shadow_discovery_keeps_its_accent_and_its_first_letter(self):
        # The reported "h! A Shadow PokAcmon!". Two faults, both gone:
        # the text is the game's own so the accent is a real e-acute, and
        # nothing here can lose a leading character because nothing slices.
        battle = Battle(20430)
        text = battle.render(20430).text
        self.assertEqual(text, "Oh! A SHADOW POKéMON!")
        self.assertTrue(text.startswith("Oh!"))
        self.assertIn("é", text)
        self.assertNotIn("Ã", text)
        self.assertFalse(is_double_encoded(text))

    def test_not_a_shadow_pokemon(self):
        battle = Battle(20481)
        self.assertEqual(
            battle.render(20481).text, "It's not a SHADOW POKéMON!")

    def test_snag_ball_throw_uses_the_player_name_global(self):
        battle = Battle(20441)
        battle.set_text("my_name", "LEON")
        self.assertEqual(
            battle.render(20441).text, "LEON threw a SNAG BALL!")

    def test_shadow_aura_flavour_needs_no_substitution(self):
        battle = Battle(20462)
        self.assertEqual(
            battle.render(20462).text,
            "Bursts of light showered from the shadowy aura!")


class RewardAndCaptureTests(unittest.TestCase):
    def test_money_reward_groups_thousands(self):
        # opcode 0x4B -> msgctrlMoney -> _msgctrlMakeDigit flag 4, the
        # branch that inserts a separator every three digits.
        battle = Battle(20023)
        battle.set_text("my_name", "LEON")
        battle.set_number("msg_money", 1350)
        self.assertEqual(
            battle.render(20023).text, "LEON got $1,350 for winning!")

    def test_plain_quantity_does_not_group(self):
        # opcode 0x2F -> msgctrlDigit -> flag 0, no separator.
        battle = Battle(20026)
        battle.set_number("msg_digit", 3)
        self.assertEqual(battle.render(20026).text, "Hit 3 time(s)!")

    def test_wild_pokemon_appeared(self):
        battle = Battle(20470)
        battle.set_text("enemy_mons", "PHANPY")
        self.assertEqual(battle.render(20470).text, "A wild PHANPY appeared!")

    def test_capture_success(self):
        battle = Battle(20473)
        battle.set_text("enemy_mons", "PINECO")
        self.assertEqual(battle.render(20473).text, "Gotcha! PINECO was caught!")

    def test_nickname_prompt(self):
        battle = Battle(20357)
        battle.set_text("enemy_mons", "PINECO")
        self.assertEqual(
            battle.render(20357).text,
            "Give a nickname to the captured PINECO?")

    def test_experience_gained(self):
        battle = Battle(20003)
        battle.set_text("ev_str_buf0", "JOLTEON")
        battle.set_text("ev_str_buf1", "133")
        battle.set_number("msg_digit", 133)
        self.assertEqual(
            battle.render(20003).text, "JOLTEON gained 133 133 EXP. Points!")

    def test_level_up(self):
        battle = Battle(20006)
        battle.set_text("ev_str_buf0", "BALTOY")
        battle.set_number("msg_digit", 18)
        self.assertEqual(battle.render(20006).text, "BALTOY grew to Lv. 18!")


class SendOutAndTrainerTests(unittest.TestCase):
    def test_player_single_send_out(self):
        battle = Battle(20312)
        battle.set_text("my_mons", "JOLTEON")
        self.assertEqual(battle.render(20312).text, "Go! JOLTEON!")

    def test_player_double_send_out_uses_template_order(self):
        battle = Battle(20313)
        battle.set_text("my_mons2", "JOLTEON")
        battle.set_text("my_mons", "TEDDIURSA")
        self.assertEqual(
            battle.render(20313).text, "Go! JOLTEON and TEDDIURSA!")

    def test_opponent_send_out_names_the_trainer(self):
        battle = Battle(20304)
        battle.set_text("trainer_type_name", "CIPHER PEON")
        battle.set_text("trainer_personal_name", "GREESIX")
        battle.set_text("enemy_mons", "ODDISH")
        self.assertEqual(
            battle.render(20304).text,
            "CIPHER PEON GREESIX sent out ODDISH!")

    def test_opponent_double_send_out(self):
        battle = Battle(20305)
        battle.set_text("trainer_type_name", "CIPHER PEON")
        battle.set_text("trainer_personal_name", "PURPSIX")
        battle.set_text("enemy_mons", "KOFFING")
        battle.set_text("enemy_mons2", "GRIMER")
        self.assertEqual(
            battle.render(20305).text,
            "CIPHER PEON PURPSIX sent out KOFFING and GRIMER!")

    def test_trainer_challenge(self):
        # Previously spoken as the invented "A trainer wants to battle!"
        # because opcodes 0x22/0x23 were considered unresolvable.
        battle = Battle(20301)
        battle.set_text("trainer_type_name", "CIPHER ADMIN")
        battle.set_text("trainer_personal_name", "LOVRINA")
        self.assertEqual(
            battle.render(20301).text,
            "CIPHER ADMIN LOVRINA would like to battle!")

    def test_speaker_opcode_resolves_through_the_npc_message_id(self):
        # 0x59 is mode 2: `_Npc` holds a NAME MESSAGE ID. In battle it is
        # written by fightTrainerSetNameHearFlag from
        # fightTrainerDB_GetName. The old code guessed the opponent
        # trainer's name and pasted it over a "[Speaker]" marker.
        battle = Battle(23501, 20326)
        battle.set_number("msg_npc", 20326, width=2)   # -> "Foe"
        self.assertEqual(battle.render(23501).text, "Foe: CHOBIN lost!")


class ClientMonsTests(unittest.TestCase):
    """Opcode 0x11, `_CLIENT_MONS` -- the Pokémon whose move or action is
    unavailable.

    Established from its writers, not the sentences: three branches of
    `fightSeqAttackPokemonJoutaiCheck` (Disable / Taunt / Imprison) pass the
    BLOCKED battler after setting a `*NoAttackFlag`, and the player's own
    command and move menus pass it when the move cannot be selected. All six
    shipped templates agree."""

    FAMILY = {
        20197: "GARDEVOIR has no moves left!",
        20198: None,      # also needs a move name
        20199: "GARDEVOIR can't use the same move twice in a row "
               "due to the TORMENT!",
        20200: None,
        20201: None,
        20384: "GARDEVOIR",
    }

    def test_every_template_naming_only_the_blocked_pokemon(self):
        for message_id, expected in self.FAMILY.items():
            if expected is None:
                continue
            battle = Battle(message_id)
            battle.battler("client_mons", "GARDEVOIR")
            self.assertEqual(battle.render(message_id).text, expected,
                             f"message {message_id}")

    def test_the_move_carrying_templates_resolve_with_a_move_name(self):
        # 0x28 (_WAZA_NAME) is a text pointer the game has already
        # rendered; 0x11 names who cannot use it.
        for message_id, expected in (
            (20198, "GARDEVOIR's SURF is disabled!"),
            (20200, "GARDEVOIR can't use SURF after the TAUNT!"),
            (20201, "GARDEVOIR can't use the sealed SURF!"),
        ):
            battle = Battle(message_id)
            battle.battler("client_mons", "GARDEVOIR")
            battle.set_text("waza_name", "SURF")
            self.assertEqual(battle.render(message_id).text, expected)

    def test_it_is_independent_of_attacker_and_defender(self):
        # The blocked Pokémon is a third role. Planting different battlers
        # in the attacker and defender globals must not change this.
        battle = Battle(20197)
        battle.battler("attack_mons", "ESPEON", side=0, slot=0)
        battle.battler("defence_mons", "ODDISH", side=1, slot=0)
        battle.battler("client_mons", "TEDDIURSA", side=0, slot=1)
        self.assertEqual(
            battle.render(20197).text, "TEDDIURSA has no moves left!")

    def test_it_works_for_a_foe_side_battler(self):
        battle = Battle(20197)
        battle.battler("client_mons", "CACNEA", side=1, slot=3)
        self.assertEqual(battle.render(20197).text, "CACNEA has no moves left!")

    def test_a_null_pointer_suppresses_the_message(self):
        battle = Battle(20197)
        rendering = battle.render(20197)
        self.assertIsNone(rendering.text)
        self.assertEqual(rendering.unresolved[0][0], 0x11)

    def test_a_stale_pointer_with_no_pokemon_attached_is_refused(self):
        # A fainted or withdrawing battler keeps its wrapper with its
        # FightPokemon detached. It must not inherit a previous nickname.
        battle = Battle(20197)
        stale = WRAPPER + 0x8000
        battle.backend.put(
            stale + XD_US_REV0.fight_out_fight_pokemon_offset, be32(0))
        battle.backend.put(battle.profile.client_mons, be32(stale))
        self.assertFalse(battle.render(20197).is_speakable)

    def test_it_resolves_through_the_canonical_identity_model(self):
        battle = Battle(20197)
        wrapper = battle.battler(
            "client_mons", "GARDEVOIR", side=1, trainer=0, slot=2,
            personality=0xC0FFEE)
        rendering = battle.render(20197)
        self.assertEqual(rendering.subjects[0x11], wrapper)
        identity = battle.identity.from_fight_out(rendering.subjects[0x11])
        self.assertEqual(identity.party, PartyPosition(1, 0, 2))
        self.assertEqual(identity.personality, 0xC0FFEE)


class ClientNoWorkTests(unittest.TestCase):
    """Opcode 0x1E, `_CLIENTNOWORK` -- the FightFloor's *appointed* Pokémon.

    Its canonical setter, `fightFloor_SetAppointPokemonPtr`, writes this
    opcode and opcode 0x1C (`_SPEABI_NAMEC`) as a pair -- the battler and
    that same battler's ability name -- and zeroes both when the pointer is
    invalid. That is why most of its 41 templates read
    "[0x1E]'s [Ability] ...", but it is not only an ability holder."""

    def test_the_ability_family_names_holder_target_and_ability(self):
        for message_id, expected in (
            (20028, "ESPEON's INSOMNIA made ODDISH sleep."),
            (20033, "ESPEON's INSOMNIA poisoned ODDISH!"),
            (20039, "ESPEON's INSOMNIA burned ODDISH!"),
            (20043, "ESPEON's INSOMNIA froze ODDISH solid!"),
        ):
            battle = Battle(message_id)
            battle.battler("clientnowork", "ESPEON", side=0, slot=0)
            battle.battler("tsuika_mons", "ODDISH", side=1, slot=0)
            battle.set_text("speabi_name_c", "INSOMNIA")
            self.assertEqual(battle.render(message_id).text, expected,
                             f"message {message_id}")

    def test_the_ability_pair_must_both_resolve(self):
        # The writer sets 0x1E and 0x1C together and clears them together,
        # so a message using both and finding only one is not in a state
        # the game produces -- suppress rather than speak half of it.
        battle = Battle(20028)
        battle.battler("clientnowork", "ESPEON", side=0, slot=0)
        battle.battler("tsuika_mons", "ODDISH", side=1, slot=0)
        rendering = battle.render(20028)
        self.assertFalse(rendering.is_speakable)
        self.assertEqual(rendering.unresolved[0][0], 0x1C)

    def test_templates_with_no_ability_at_all(self):
        # Proof that "ability holder" was too narrow a reading.
        for message_id, expected in (
            (20144, "ESPEON is hurt by SPIKES!"),
            (20093, "ESPEON is protected by MIST!"),
            (20105, "But ESPEON's UPROAR kept it awake!"),
        ):
            battle = Battle(message_id)
            battle.battler("clientnowork", "ESPEON", side=0, slot=0)
            self.assertEqual(battle.render(message_id).text, expected,
                             f"message {message_id}")

    def test_a_two_battler_template_keeps_the_roles_apart(self):
        battle = Battle(20185)
        battle.battler("defence_mons", "ODDISH", side=1, slot=0)
        battle.battler("clientnowork", "ESPEON", side=0, slot=0)
        self.assertEqual(
            battle.render(20185).text, "ODDISH SNATCHED ESPEON's move!")

    def test_the_item_family_resolves(self):
        battle = Battle(20192)
        battle.battler("clientnowork", "ESPEON", side=0, slot=0)
        battle.set_text("item_name", "SITRUS BERRY")
        self.assertEqual(
            battle.render(20192).text, "ESPEON used SITRUS BERRY to hustle!")

    def test_a_null_pointer_suppresses_the_message(self):
        battle = Battle(20144)
        rendering = battle.render(20144)
        self.assertIsNone(rendering.text)
        self.assertEqual(rendering.unresolved[0][0], 0x1E)

    def test_a_replacement_battler_is_named_not_the_outgoing_one(self):
        battle = Battle(20144)
        battle.battler("clientnowork", "JOLTEON", side=0, slot=0)
        self.assertEqual(battle.render(20144).text, "JOLTEON is hurt by SPIKES!")
        battle.battler("clientnowork", "FLAAFFY", side=0, slot=2)
        self.assertEqual(battle.render(20144).text, "FLAAFFY is hurt by SPIKES!")

    def test_baton_pass_keeps_the_wrapper_and_changes_the_name(self):
        # A Baton Pass retains the on-field wrapper and repoints its
        # FightPokemon. The rendered subject must follow the Pokemon, not
        # the wrapper address.
        p = XD_US_REV0
        battle = Battle(20144)
        wrapper = battle.battler("clientnowork", "JOLTEON", side=0, slot=0)
        self.assertEqual(battle.render(20144).text, "JOLTEON is hurt by SPIKES!")
        incoming = party_slot_address(p, 0, 0, 2)
        battle.battler(None, "FLAAFFY", side=0, slot=2)
        battle.backend.put(
            wrapper + p.fight_out_fight_pokemon_offset, be32(incoming))
        self.assertEqual(battle.render(20144).text, "FLAAFFY is hurt by SPIKES!")

    def test_duplicate_species_are_separated_by_canonical_identity(self):
        battle = Battle(20144)
        wrapper = battle.battler(
            "clientnowork", "GARDEVOIR", side=1, slot=1, personality=0xB2)
        battle.battler(None, "GARDEVOIR", side=1, slot=0, personality=0xA1)
        rendering = battle.render(20144)
        self.assertEqual(rendering.text, "GARDEVOIR is hurt by SPIKES!")
        identity = battle.identity.from_fight_out(rendering.subjects[0x1E])
        self.assertEqual(identity.personality, 0xB2)
        self.assertEqual(identity.party, PartyPosition(1, 0, 1))


class TrainerNameTests(unittest.TestCase):
    """0x22/0x23 are one trainer's class and name; 0x25/0x26 are two
    different trainers' names. Both pairs go through different accessors --
    `fightTrainerGetPrefixNamePtr` versus `fightTrainerGetNamePtr`."""

    def test_class_and_name_are_distinct_fields(self):
        for trainer_class, trainer_name in (
            ("CIPHER PEON", "GREESIX"),
            ("CIPHER ADMIN", "LOVRINA"),
        ):
            battle = Battle(20301)
            battle.set_text("trainer_type_name", trainer_class)
            battle.set_text("trainer_personal_name", trainer_name)
            self.assertEqual(
                battle.render(20301).text,
                f"{trainer_class} {trainer_name} would like to battle!")

    def test_the_class_is_never_substituted_for_the_name(self):
        battle = Battle(20304)
        battle.set_text("trainer_type_name", "CHASER")
        battle.set_text("trainer_personal_name", "DABIL")
        battle.set_text("enemy_mons", "CYNDAQUIL")
        text = battle.render(20304).text
        self.assertEqual(text, "CHASER DABIL sent out CYNDAQUIL!")
        self.assertEqual(text.count("CHASER"), 1)
        self.assertEqual(text.count("DABIL"), 1)

    def test_a_missing_class_suppresses_rather_than_falling_back(self):
        battle = Battle(20301)
        battle.set_text("trainer_personal_name", "LOVRINA")
        rendering = battle.render(20301)
        self.assertFalse(rendering.is_speakable)
        self.assertEqual(rendering.unresolved[0][0], 0x22)

    def test_two_trainers_on_one_side_use_the_other_name_pair(self):
        # 20309 is the two-trainers-each-sending-one form, distinct from
        # 20305's one-trainer-sending-two. Each trainer's name pairs with
        # its own Pokemon global.
        battle = Battle(20309)
        battle.set_text("trainer_first_name", "MIRU")
        battle.set_text("trainer_second_name", "BARDO")
        battle.set_text("enemy_tmons", "WURMPLE")
        battle.set_text("enemy_tmons2", "DODUO")
        self.assertEqual(
            battle.render(20309).text,
            "MIRU sent out WURMPLE! BARDO sent out DODUO!")

    def test_the_two_trainer_result_messages_name_both(self):
        for message_id, expected in (
            (20259, "Player beat MIRU and BARDO!"),
            (20261, "Player lost to MIRU and BARDO!"),
            (20263, "Player tied against MIRU and BARDO!"),
        ):
            battle = Battle(message_id)
            battle.set_text("trainer_first_name", "MIRU")
            battle.set_text("trainer_second_name", "BARDO")
            self.assertEqual(battle.render(message_id).text, expected)

    def test_the_single_trainer_result_message_names_one(self):
        battle = Battle(20258)
        battle.set_text("trainer_first_name", "GREESIX")
        self.assertEqual(
            battle.render(20258).text, "Player defeated GREESIX!")


class NullOpcodeTests(unittest.TestCase):
    """0x0B and 0x0C: null handlers in the shipped table, mode 0."""

    def test_they_are_registered_as_inert_with_no_argument_bytes(self):
        for code in (0x0B, 0x0C):
            self.assertEqual(REGISTRY[code].kind, "nothing")
            self.assertEqual(REGISTRY[code].handler, 0x00000000)
            self.assertEqual(REGISTRY[code].extra_bytes, 0)

    def test_they_neither_suppress_nor_eat_the_following_text(self):
        # If they consumed argument bytes, the text after the marker would
        # decode as garbage. It does not, in any of the nine.
        for message_id, expected in (
            (20414, "Win"),
            (20415, "Loss"),
            (20416, "Tie"),
        ):
            battle = Battle(message_id)
            rendering = battle.render(message_id)
            self.assertTrue(rendering.is_speakable, f"message {message_id}")
            self.assertEqual(rendering.text, expected)

    def test_these_panels_carry_textual_markup_not_a_control_code(self):
        """A finding, pinned rather than papered over.

        Six of the nine also contain the literal ASCII text
        `<SCOL=0x0d0e0f>` -- menu-panel markup written into the string data,
        NOT the binary colour opcode 0x08 (which would render as nothing).
        The renderer is faithful and passes it through. Stripping it belongs
        to whoever consumes these panels, where the markup grammar can be
        established; inventing a regex to eat anything in angle brackets
        here would be a guess, and no battle message uses this form."""
        battle = Battle(20391)
        self.assertEqual(
            battle.render(20391).text,
            "<SCOL=0x0d0e0f>Switch which moves?")

    def test_the_battle_yes_no_panel_is_a_real_resource(self):
        # 20390 carries the Yes/No labels `menus.yes_no_focus` currently
        # hardcodes. Recorded for the Yes/No work; not consumed yet, and it
        # needs the markup question above answered first.
        battle = Battle(20390)
        self.assertEqual(battle.render(20390).text, "<SCOL=0x0d0e0f>Yes No")


class SideNameTests(unittest.TestCase):
    def test_whole_side_qualifier_is_the_games_own_wording(self):
        # 0x1F..0x21 / 0x42..0x44 resolve through _msgctrlSideName to
        # messages 20327-20332. They are side-wide, not per-battler --
        # which is why the Phase 1 plan to use them for duplicate-species
        # disambiguation was dropped.
        battle = Battle(20071)
        battle.battler("side_attack_name_ha", "ESPEON", side=0)
        self.assertEqual(
            battle.render(20071).text, "Ally's party is covered by a veil!")

    def test_the_foe_side_selects_the_other_message(self):
        # Side comes from which trainer's party array the battler sits in,
        # the same answer `fightTargetIsHostSide` gives.
        battle = Battle(20071)
        battle.battler("side_attack_name_ha", "ODDISH", side=1)
        self.assertEqual(
            battle.render(20071).text, "Foe's party is covered by a veil!")


# ---------------------------------------------------------------------------
# The safety contract
# ---------------------------------------------------------------------------


class SuppressionTests(unittest.TestCase):
    def test_an_unset_battler_global_suppresses_the_whole_message(self):
        battle = Battle(20044)   # "[Pokemon 15] is frozen solid!"
        rendering = battle.render(20044)
        self.assertIsNone(rendering.text)
        self.assertTrue(rendering.unresolved)
        self.assertEqual(rendering.unresolved[0][0], 0x0F)

    def test_an_unset_send_out_global_never_yields_a_bare_go(self):
        battle = Battle(20312)
        rendering = battle.render(20312)
        self.assertIsNone(rendering.text)
        self.assertFalse(rendering.is_speakable)

    def test_a_partially_populated_double_send_out_is_refused(self):
        battle = Battle(20305)
        battle.set_text("trainer_type_name", "CIPHER PEON")
        battle.set_text("trainer_personal_name", "PURPSIX")
        battle.set_text("enemy_mons", "KOFFING")
        # enemy_mons2 left null
        self.assertFalse(battle.render(20305).is_speakable)

    def test_an_unloaded_message_is_silent(self):
        battle = Battle(20044)
        rendering = battle.render(29999)
        self.assertIsNone(rendering.text)
        self.assertIn("not loaded", rendering.unresolved[0][1])

    def test_the_narrator_stays_silent_for_an_unresolved_message(self):
        battle = Battle(20044)
        self.assertEqual(battle.spoken(20044), [])

    def test_the_narrator_speaks_a_fully_resolved_message(self):
        battle = Battle(20044)
        battle.battler("attack_mons", "GARDEVOIR")
        self.assertEqual(battle.spoken(20044), ["GARDEVOIR is frozen solid!"])

    def test_a_battler_wrapper_with_no_pokemon_is_not_spoken(self):
        battle = Battle(20044)
        battle.backend.put(battle.profile.attack_mons, be32(WRAPPER + 0x9000))
        self.assertEqual(battle.spoken(20044), [])


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


class EncodingTests(unittest.TestCase):
    def test_accented_game_text_survives_decoding(self):
        battle = Battle(20430)
        self.assertIn("é", battle.render(20430).text)

    def test_poke_ball_style_text_round_trips(self):
        for value in ("Pokémon", "Poké Ball", "POKéMON", "ordinary ascii",
                      "It's not very effective...", "$1,350"):
            battle = Battle()
            address = battle._text(value)
            self.assertEqual(
                battle.memory.gschar(address, len(value), "t", 2), value)
            self.assertFalse(is_double_encoded(value), value)

    def test_a_deliberately_double_encoded_string_is_caught(self):
        broken = "Oh! A Shadow PokÃ©mon!"
        self.assertTrue(is_double_encoded(broken))
        self.assertEqual(repair_double_encoded(broken),
                         "Oh! A Shadow Pokémon!")

    def test_double_encoded_text_is_never_spoken(self):
        battle = Battle(20044)
        battle.battler("attack_mons", "PokÃ©mon")
        rendering = battle.render(20044)
        self.assertFalse(rendering.is_speakable)
        self.assertIn("double-encoding",
                      " ".join(why for _, why in rendering.unresolved))

    def test_plain_latin1_accents_are_not_mistaken_for_mojibake(self):
        for value in ("Pokémon", "café", "naïve", "Poké Ball"):
            self.assertFalse(is_double_encoded(value), value)

    def test_no_production_source_file_carries_a_codec_round_trip(self):
        """The guard that would have caught the original bug.

        Running this over the tree found six genuinely corrupted lines
        besides the Shadow sentence -- including a quadruple-encoded
        `--help` string and a captured live dialogue fixture whose POKéMON
        had rotted to POKÃ©MON. All repaired; this keeps them repaired."""
        root = Path(__file__).resolve().parents[1] / "battle_narrator"
        offenders = []
        for path in sorted(root.glob("*.py")):
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                if is_double_encoded(line):
                    offenders.append(f"{path.name}:{number}")
        self.assertEqual(offenders, [])

    def test_every_source_file_is_valid_utf8_without_a_bom(self):
        root = Path(__file__).resolve().parents[1] / "battle_narrator"
        for path in sorted(root.glob("*.py")):
            raw = path.read_bytes()
            self.assertNotIn(b"\xef\xbb\xbf", raw, path.name)
            raw.decode("utf-8")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class LifecycleTests(unittest.TestCase):
    def narrator(self, battle, sequence, **kwargs):
        speaker = Speaker()
        narrator = BattleNarrator(
            _Connection(), SequenceTasks(sequence), Battle.catalog,
            _Resolver(battle.identity), speaker, logger(),
            poll_interval=0, renderer=battle.renderer, **kwargs)
        return narrator, speaker

    def test_the_same_event_is_spoken_once(self):
        battle = Battle(20044)
        battle.battler("attack_mons", "GARDEVOIR")
        allocated = [TaskSnapshot(0, 0x80003000, 2, 20044)]
        narrator, speaker = self.narrator(battle, [allocated] * 5)
        for _ in range(5):
            narrator.poll_once()
        self.assertEqual(len(speaker.spoken), 1)

    def test_the_same_id_with_a_different_subject_speaks_again(self):
        battle = Battle(20044)
        first = battle.battler("attack_mons", "GARDEVOIR")
        allocated = [TaskSnapshot(0, 0x80003000, 2, 20044)]
        closed = [TaskSnapshot(0, 0x80003000, 0, None)]
        narrator, speaker = self.narrator(
            battle, [allocated] * 2 + [closed] + [allocated] * 2)
        narrator.poll_once(); narrator.poll_once()
        narrator.poll_once()
        battle.battler("attack_mons", "ODDISH", slot=1)
        narrator.poll_once(); narrator.poll_once()
        self.assertEqual(
            [text for text, _ in speaker.spoken],
            ["GARDEVOIR is frozen solid!", "ODDISH is frozen solid!"])

    def test_a_reward_with_a_changed_amount_speaks_again(self):
        battle = Battle(20023)
        battle.set_text("my_name", "LEON")
        battle.set_number("msg_money", 1350)
        allocated = [TaskSnapshot(0, 0x80003000, 2, 20023)]
        closed = [TaskSnapshot(0, 0x80003000, 0, None)]
        narrator, speaker = self.narrator(
            battle, [allocated] * 2 + [closed] + [allocated] * 2)
        narrator.poll_once(); narrator.poll_once()
        narrator.poll_once()
        battle.set_number("msg_money", 900)
        narrator.poll_once(); narrator.poll_once()
        self.assertEqual(
            [text for text, _ in speaker.spoken],
            ["LEON got $1,350 for winning!", "LEON got $900 for winning!"])

    def test_a_substitution_still_settling_does_not_speak_early(self):
        # The gate double-samples the RENDERED string, so a name that is
        # still being written re-arms instead of being spoken half-formed.
        battle = Battle(20044)
        battle.battler("attack_mons", "GARDEVOIR")
        allocated = [TaskSnapshot(0, 0x80003000, 2, 20044)]
        narrator, speaker = self.narrator(battle, [allocated] * 3)
        narrator.poll_once()
        self.assertEqual(speaker.spoken, [])
        battle.battler("attack_mons", "ODDISH", slot=2)
        narrator.poll_once()
        self.assertEqual(speaker.spoken, [])
        narrator.poll_once()
        self.assertEqual(
            [text for text, _ in speaker.spoken], ["ODDISH is frozen solid!"])

    def test_an_unresolved_message_is_logged_once(self):
        battle = Battle(20044)
        records = []

        class Recorder(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        allocated = [TaskSnapshot(0, 0x80003000, 2, 20044)]
        narrator, _speaker = self.narrator(battle, [allocated] * 4)
        narrator.logger.handlers.clear()
        narrator.logger.addHandler(Recorder())
        for _ in range(4):
            narrator.poll_once()
        suppressed = [line for line in records if "SUPPRESSED" in line]
        self.assertEqual(len(suppressed), 1)

    def test_battle_transition_cleanup_rearms_suppression(self):
        battle = Battle(20044)
        allocated = [TaskSnapshot(0, 0x80003000, 2, 20044)]
        narrator, _speaker = self.narrator(battle, [allocated] * 4)
        narrator.poll_once()
        self.assertTrue(narrator._reported)
        narrator.clear("battle ended")
        self.assertFalse(narrator._reported)

    def test_a_message_that_becomes_resolvable_later_is_spoken(self):
        battle = Battle(20044)
        allocated = [TaskSnapshot(0, 0x80003000, 2, 20044)]
        narrator, speaker = self.narrator(battle, [allocated] * 4)
        narrator.poll_once()
        self.assertEqual(speaker.spoken, [])
        battle.battler("attack_mons", "GARDEVOIR")
        narrator.poll_once(); narrator.poll_once()
        self.assertEqual(
            [text for text, _ in speaker.spoken], ["GARDEVOIR is frozen solid!"])


class DisambiguationTests(unittest.TestCase):
    def test_two_identical_names_on_the_field_get_a_clarifier(self):
        battle = Battle(20044)
        first = battle.battler(
            "attack_mons", "GARDEVOIR", side=1, slot=0, personality=0xA1)
        second = battle.battler(
            None, "GARDEVOIR", side=1, slot=1, personality=0xB2)
        battle.field(first, second)
        tracker = BattlefieldSlotTracker(battle.identity, XD_US_REV0, logger())
        labeller = IdentityLabeller()
        speaker = Speaker()
        allocated = [TaskSnapshot(0, 0x80003000, 2, 20044)]
        narrator = BattleNarrator(
            _Connection(), SequenceTasks([allocated] * 3), Battle.catalog,
            _Resolver(battle.identity), speaker, logger(),
            poll_interval=0, renderer=battle.renderer,
            slot_tracker=tracker, labeller=labeller)
        for _ in range(3):
            narrator.poll_once()
        self.assertEqual(
            [text for text, _ in speaker.spoken],
            ["GARDEVOIR is frozen solid! The foe's first Gardevoir."])

    def test_a_unique_name_gets_no_clarifier(self):
        battle = Battle(20044)
        first = battle.battler("attack_mons", "GARDEVOIR", side=1, slot=0)
        second = battle.battler(None, "ODDISH", side=1, slot=1)
        battle.field(first, second)
        tracker = BattlefieldSlotTracker(battle.identity, XD_US_REV0, logger())
        speaker = Speaker()
        allocated = [TaskSnapshot(0, 0x80003000, 2, 20044)]
        narrator = BattleNarrator(
            _Connection(), SequenceTasks([allocated] * 3), Battle.catalog,
            _Resolver(battle.identity), speaker, logger(),
            poll_interval=0, renderer=battle.renderer,
            slot_tracker=tracker, labeller=IdentityLabeller())
        for _ in range(3):
            narrator.poll_once()
        self.assertEqual(
            [text for text, _ in speaker.spoken],
            ["GARDEVOIR is frozen solid!"])


class SpeechSequencingTests(unittest.TestCase):
    """The leading-character loss, and the interruption rules around it."""

    def coordinator(self):
        speaker = Speaker()
        return SpeechCoordinator(speaker, logger()), speaker

    def test_a_battle_event_does_not_interrupt_another_battle_event(self):
        # Reproduces the production-log pair that clipped "Oh!" to "h!":
        #   00:05:50.837 interrupt=False "Blastoise's Accuracy fell!"
        #   00:05:50.901 interrupt=True  "Blastoise's accuracy fell!"
        coordinator, speaker = self.coordinator()
        coordinator.emit(SpeechEventClass.BATTLE_EVENT, "Oh! A SHADOW POKéMON!")
        coordinator.emit(SpeechEventClass.BATTLE_EVENT, "GARDEVOIR fell asleep!")
        self.assertEqual([interrupt for _, interrupt in speaker.spoken],
                         [True, False])

    def test_a_battle_event_still_interrupts_stale_menu_speech(self):
        coordinator, speaker = self.coordinator()
        coordinator.emit(SpeechEventClass.MENU_FOCUS, "Fight")
        coordinator.emit(SpeechEventClass.BATTLE_EVENT, "GARDEVOIR fainted!")
        self.assertEqual(speaker.spoken[-1][1], True)

    def test_the_first_battle_event_after_other_speech_interrupts(self):
        coordinator, speaker = self.coordinator()
        coordinator.emit(SpeechEventClass.BATTLE_EVENT, "one")
        coordinator.emit(SpeechEventClass.DIALOGUE, "some dialogue")
        coordinator.emit(SpeechEventClass.BATTLE_EVENT, "two")
        self.assertEqual([interrupt for _, interrupt in speaker.spoken],
                         [True, True, True])

    def test_a_run_of_battle_events_keeps_every_sentence_whole(self):
        coordinator, speaker = self.coordinator()
        for sentence in ("a", "b", "c", "d"):
            coordinator.emit(SpeechEventClass.BATTLE_EVENT, sentence)
        self.assertEqual([interrupt for _, interrupt in speaker.spoken],
                         [True, False, False, False])
        self.assertEqual([text for text, _ in speaker.spoken],
                         ["a", "b", "c", "d"])

    def test_clear_forgets_the_last_class(self):
        coordinator, speaker = self.coordinator()
        coordinator.emit(SpeechEventClass.BATTLE_EVENT, "one")
        coordinator.clear()
        coordinator.emit(SpeechEventClass.BATTLE_EVENT, "two")
        self.assertEqual(speaker.spoken[-1][1], True)


class RetiredTableTests(unittest.TestCase):
    """The migration guard: these IDs must not be findable in any Python
    table of game sentences ever again."""

    RETIRED = (20430, 20481, 20462, 20498, 20349, 20352, 20353, 20444,
               20446, 20474, 20475, 20351, 20355, 20356, 20448, 20470,
               20471, 20472, 20473, 20477, 20479, 20493, 20494, 20304,
               20015, 20034, 20021, 20022, 20050, 20065, 20058, 20450,
               20258, 20300, 20301, 20024, 20025, 20032)

    def test_no_retired_sentence_table_survives(self):
        from battle_narrator import resolver
        for name in ("FIXED_SENTENCES", "FIXED_SENTENCE_IDS",
                     "CATCH_TARGET_TEMPLATES", "CATCH_TARGET_IDS",
                     "ACTOR_SENTENCE_TEMPLATES", "ACTOR_MESSAGE_IDS",
                     "VICTORY_SENTENCE", "PARTIAL_TRAINER_SENTENCES",
                     "SUPPORTED_IDS"):
            self.assertFalse(hasattr(resolver, name), name)

    def test_the_narrator_has_no_opcode_allow_list(self):
        from battle_narrator import narrator
        self.assertFalse(hasattr(narrator, "VERIFIED_OPCODES"))
        self.assertFalse(hasattr(narrator, "STRUCTURAL_TEXT_OPCODES"))

    def test_no_retired_message_id_appears_in_resolver_source(self):
        source = (Path(__file__).resolve().parents[1]
                  / "battle_narrator" / "resolver.py").read_text(
                      encoding="utf-8")
        # Comments recording what was retired are fine; a dict literal
        # mapping one of these IDs to a string is not.
        for message_id in self.RETIRED:
            self.assertNotIn(f"{message_id}: \"", source, str(message_id))
            self.assertNotIn(f"{message_id}: '", source, str(message_id))


if __name__ == "__main__":
    unittest.main()
