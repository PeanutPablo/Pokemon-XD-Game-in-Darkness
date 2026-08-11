"""Tests for the ported Purify Chamber Tempo/Flow maths.

These build a real type chart, real tempo tables and real Pokemon records
in fake memory and drive the real model, because the thing under test IS
the arithmetic. A mocked `tempo()` would test nothing.

The strongest assertion here is `test_perfect_set_reaches_the_engines_own
_bonus_threshold`: the maximum Tempo the port produces, times the largest
Flow multiplier, must equal 192 -- the literal `CReliveStage::isBonusGet`
compares against. That number was never typed into the model; it falls
out of the tables. If any table index, the pair loop or the multiplier
lookup is wrong, it stops landing on 192.
"""
import struct
import unittest

from battle_narrator.memory import MemoryReader
from battle_narrator.profile import XD_US_REV0
from battle_narrator import purify_chamber as pc


def be16(value):
    return value.to_bytes(2, "big")


def be32(value):
    return value.to_bytes(4, "big")


def f32(value):
    return struct.pack(">f", value)


def gschar(text):
    return b"".join(be16(ord(c)) for c in text) + b"\0\0"


# Real Gen 3 internal type ids, confirmed live against the project owner's
# own party (Houndour read as Dark/Fire, Baltoy as Ground/Psychic).
NORMAL, FIGHTING, FLYING, POISON, GROUND = 0, 1, 2, 3, 4
FIRE, WATER, GRASS, ELECTRIC, PSYCHIC = 10, 11, 12, 13, 14
DARK = 17

# The four chart states, live values from `jyoutai2levelTbl` (0x804E8698).
# Their INDEX in that table is what maps to a matchup level, via the
# engine's own max(index - 1, 0).
STATE_LEVEL_0A, STATE_LEVEL_0B, STATE_LEVEL_1, STATE_LEVEL_2 = 67, 66, 63, 65


class Backend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + i, 0) for i in range(size))


class ChamberFixture:
    SAVEDATA = 0x80500000
    SPECIES_COUNT_CELL, SPECIES_BASE = 0x80600000, 0x80610000
    TYPE_COUNT_CELL, TYPE_BASE = 0x80700000, 0x80710000

    def __init__(self):
        self.backend = Backend()
        self.memory = MemoryReader(self.backend, XD_US_REV0)
        self.model = pc.PurifyChamberModel(self.memory, XD_US_REV0)
        put = self.backend.put

        put(XD_US_REV0.savedata_pointer_address, be32(self.SAVEDATA))

        # Live table values, so the tests exercise the real numbers.
        for index, value in enumerate((0, 5, 14, 27, 48)):
            put(pc.TEMPO_BASE_TABLE + index * 4, be32(value))
        for index, value in enumerate((0, 6, 6, 6, 12)):
            put(pc.TEMPO_GOOD_TABLE + index * 4, be32(value))
        for index, value in enumerate((0, 2, 2, 2, 4)):
            put(pc.TEMPO_NORMAL_TABLE + index * 4, be32(value))
        for index, value in enumerate((0, 0, 1, 5, 10, 15, 25, 35, 50, 100)):
            put(pc.BONUS_STAGE_TABLE + index * 4, be32(value))
        for index, value in enumerate((1.0, 1.5, 2.0)):
            put(pc.FLOW_MULTIPLIER_TABLE + index * 4, f32(value))
        for index, value in enumerate(
                (STATE_LEVEL_0A, STATE_LEVEL_0B, STATE_LEVEL_1, STATE_LEVEL_2)):
            put(pc.JYOUTAI_TO_LEVEL_TABLE + index * 2, be16(value))

        put(pc.POKEMON_DATA_NUMBER, be32(self.SPECIES_COUNT_CELL))
        put(self.SPECIES_COUNT_CELL, be32(500))
        put(pc.POKEMON_DATA, be32(self.SPECIES_BASE))
        put(pc.ZOKUSEI_DATA_NUMBER, be32(self.TYPE_COUNT_CELL))
        put(self.TYPE_COUNT_CELL, be32(18))
        put(pc.ZOKUSEI_DATA, be32(self.TYPE_BASE))

        # Default every pairing to the neutral state, then override.
        for attacking in range(18):
            for defending in range(18):
                self.set_chart(attacking, defending, STATE_LEVEL_1)

    def set_chart(self, attacking, defending, state):
        self.backend.put(
            self.TYPE_BASE + attacking * pc.ZOKUSEI_STRIDE
            + pc.ZOKUSEI_CHART_OFFSET + defending * 2, be16(state))

    def species(self, data_id, types, name_message=0):
        record = self.SPECIES_BASE + data_id * pc.POKEMON_DATA_STRIDE
        first, second = types
        self.backend.put(record + pc.POKEMON_TYPE_OFFSET, bytes([first, second]))
        self.backend.put(record + pc.POKEMON_NAME_OFFSET, be32(name_message))

    def place(self, set_index, slot, data_id, nickname="MON", level=50):
        stage = self.model.stage_address(set_index)
        address = (stage + pc.VISITOR_OFFSET if slot == "visitor"
                   else stage + slot * pc.DANCER_STRIDE)
        self.backend.put(address + pc.POKEMON_DATA_ID_OFFSET, be16(data_id))
        self.backend.put(address + pc.POKEMON_LEVEL_OFFSET, bytes([level]))
        self.backend.put(address + pc.POKEMON_NICKNAME_OFFSET, gschar(nickname))

    def face(self, set_index, position):
        self.backend.put(
            self.model.stage_address(set_index) + pc.FACING_OFFSET,
            bytes([position & 0xFF]))

    def mon(self, data_id, types, nickname="MON", level=50, slot=0):
        self.species(data_id, types)
        return pc.ChamberPokemon(slot, data_id, nickname, level, types)


class MatchupTests(unittest.TestCase):
    def setUp(self):
        self.f = ChamberFixture()

    def test_chart_states_collapse_to_three_levels(self):
        # max(index - 1, 0) over the four-entry table: two states share
        # level 0, and there is no level 3 despite the switch accepting one.
        self.assertEqual(self.f.model._state_to_level(STATE_LEVEL_0A), 0)
        self.assertEqual(self.f.model._state_to_level(STATE_LEVEL_0B), 0)
        self.assertEqual(self.f.model._state_to_level(STATE_LEVEL_1), 1)
        self.assertEqual(self.f.model._state_to_level(STATE_LEVEL_2), 2)

    def test_unknown_chart_state_yields_the_engines_sentinel(self):
        self.assertEqual(self.f.model._state_to_level(999), pc.UNMATCHED_LEVEL)

    def test_matchup_takes_the_best_of_the_four_pairings(self):
        self.f.set_chart(FIRE, WATER, STATE_LEVEL_0A)
        self.f.set_chart(FIRE, FLYING, STATE_LEVEL_0A)
        self.f.set_chart(GRASS, WATER, STATE_LEVEL_2)
        self.f.set_chart(GRASS, FLYING, STATE_LEVEL_0A)
        first = self.f.mon(1, (FIRE, GRASS))
        second = self.f.mon(2, (WATER, FLYING))
        self.assertEqual(self.f.model.matchup_level(first, second), 2)

    def test_absent_pokemon_gives_minus_one(self):
        mon = self.f.mon(1, (FIRE, FIRE))
        self.assertEqual(self.f.model.matchup_level(mon, None), -1)
        self.assertEqual(self.f.model.matchup_level(None, mon), -1)

    def test_two_pure_normals_use_the_engines_special_case(self):
        # Both type ids zero short-circuits to level 2 without consulting
        # the chart. Proven here by setting the chart entry to the WORST
        # state and still expecting 2.
        self.f.set_chart(NORMAL, NORMAL, STATE_LEVEL_0A)
        first = self.f.mon(1, (NORMAL, NORMAL))
        second = self.f.mon(2, (NORMAL, NORMAL))
        self.assertEqual(self.f.model.matchup_level(first, second), 2)


class TempoTests(unittest.TestCase):
    def setUp(self):
        self.f = ChamberFixture()

    def dancers(self, *specs):
        return tuple(
            self.f.mon(index + 1, types, slot=index)
            for index, types in enumerate(specs))

    def test_empty_set_has_no_tempo(self):
        self.assertEqual(self.f.model.tempo(()), 0)

    def test_single_pokemon_pairs_with_itself(self):
        # count == 1 makes (i+1) % count == 0, so the one Pokemon is
        # compared against itself -- base 5 plus its own self-matchup.
        self.f.set_chart(FIRE, FIRE, STATE_LEVEL_1)
        self.assertEqual(self.f.model.tempo(self.dancers((FIRE, FIRE))), 5 + 2)

    def test_neutral_pairs_use_the_normal_table(self):
        dancers = self.dancers((FIRE, FIRE), (WATER, WATER))
        # Two dancers, two pairs, both neutral: 14 + 2 + 2.
        self.assertEqual(self.f.model.tempo(dancers), 18)

    def test_good_pairs_use_the_good_table(self):
        self.f.set_chart(FIRE, WATER, STATE_LEVEL_2)
        self.f.set_chart(WATER, FIRE, STATE_LEVEL_2)
        dancers = self.dancers((FIRE, FIRE), (WATER, WATER))
        self.assertEqual(self.f.model.tempo(dancers), 14 + 6 + 6)

    def test_worst_pairs_contribute_nothing(self):
        self.f.set_chart(FIRE, WATER, STATE_LEVEL_0A)
        self.f.set_chart(WATER, FIRE, STATE_LEVEL_0A)
        dancers = self.dancers((FIRE, FIRE), (WATER, WATER))
        self.assertEqual(self.f.model.tempo(dancers), 14)

    def test_only_adjacent_positions_pair(self):
        # Four dancers form a ring: 0-1, 1-2, 2-3, 3-0. Position 0 and 2
        # are NOT compared, so making them a great match changes nothing.
        for a, b in ((FIRE, GRASS), (GRASS, FIRE)):
            self.f.set_chart(a, b, STATE_LEVEL_2)
        dancers = self.dancers(
            (FIRE, FIRE), (WATER, WATER), (GRASS, GRASS), (ELECTRIC, ELECTRIC))
        self.assertEqual(self.f.model.tempo(dancers), 48 + 4 * 4)

    def test_maximum_tempo_is_ninety_six(self):
        for attacking in range(18):
            for defending in range(18):
                self.f.set_chart(attacking, defending, STATE_LEVEL_2)
        dancers = self.dancers(
            (FIRE, FIRE), (WATER, WATER), (GRASS, GRASS), (ELECTRIC, ELECTRIC))
        self.assertEqual(self.f.model.tempo(dancers), pc.PERFECT_TEMPO)

    def test_tempo_level_thresholds_match_the_drawn_bar(self):
        # relivehallTempoToLevel: <=26 low, <=53 medium, else high.
        def level(value):
            return pc.ChamberSet(0, (), None, 0, value, 0, 0).tempo_level
        self.assertEqual([level(v) for v in (0, 26, 27, 53, 54, 96)],
                         [0, 0, 1, 1, 2, 2])


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.f = ChamberFixture()

    def dancers(self, *specs):
        return tuple(
            self.f.mon(index + 1, types, slot=index)
            for index, types in enumerate(specs))

    def test_no_shadow_pokemon_means_no_flow(self):
        self.assertEqual(
            self.f.model.flow(self.dancers((FIRE, FIRE)), None, 0), 0)

    def test_zero_tempo_means_no_flow(self):
        self.assertEqual(
            self.f.model.flow((), self.f.mon(9, (DARK, DARK)), 0), 0)

    def test_flow_scales_tempo_by_the_faced_matchup(self):
        dancers = self.dancers((FIRE, FIRE), (WATER, WATER))
        shadow = self.f.mon(9, (DARK, DARK))
        tempo = self.f.model.tempo(dancers)
        for state, multiplier in ((STATE_LEVEL_0A, 1.0),
                                  (STATE_LEVEL_1, 1.5),
                                  (STATE_LEVEL_2, 2.0)):
            self.f.set_chart(DARK, FIRE, state)
            self.assertEqual(
                self.f.model.flow(dancers, shadow, 0), int(tempo * multiplier),
                f"state {state}")

    def test_facing_an_empty_position_gives_no_flow(self):
        dancers = self.dancers((FIRE, FIRE))
        shadow = self.f.mon(9, (DARK, DARK))
        self.assertEqual(self.f.model.flow(dancers, shadow, 3), 0)

    def test_facing_chooses_which_dancer_is_compared(self):
        self.f.set_chart(DARK, FIRE, STATE_LEVEL_0A)
        self.f.set_chart(DARK, WATER, STATE_LEVEL_2)
        dancers = self.dancers((FIRE, FIRE), (WATER, WATER))
        shadow = self.f.mon(9, (DARK, DARK))
        facing_fire = self.f.model.flow(dancers, shadow, 0)
        facing_water = self.f.model.flow(dancers, shadow, 1)
        self.assertLess(facing_fire, facing_water)

    def test_perfect_set_reaches_the_engines_own_bonus_threshold(self):
        # The cross-check that validates the whole port. 96 * 2.0 == 192,
        # and 192 is the literal isBonusGet (0x8028E1E8) compares against.
        # Neither number is written into the model.
        for attacking in range(18):
            for defending in range(18):
                self.f.set_chart(attacking, defending, STATE_LEVEL_2)
        dancers = self.dancers(
            (FIRE, FIRE), (WATER, WATER), (GRASS, GRASS), (ELECTRIC, ELECTRIC))
        shadow = self.f.mon(9, (DARK, DARK))
        self.assertEqual(
            self.f.model.flow(dancers, shadow, 0), pc.PERFECT_FLOW)


class UniqueTypeTests(unittest.TestCase):
    def setUp(self):
        self.f = ChamberFixture()

    def test_repeated_type_is_not_unique(self):
        dancers = (self.f.mon(1, (FIRE, FIRE), slot=0),
                   self.f.mon(2, (FIRE, WATER), slot=1))
        self.assertFalse(self.f.model.types_all_unique(dancers))

    def test_distinct_types_are_unique(self):
        dancers = (self.f.mon(1, (FIRE, FIRE), slot=0),
                   self.f.mon(2, (WATER, GRASS), slot=1))
        self.assertTrue(self.f.model.types_all_unique(dancers))

    def test_single_typed_pokemon_claims_only_one_type(self):
        # A pure Fire type stores (FIRE, FIRE). If the repeat were counted
        # as a second claim it would collide with itself and never be
        # unique.
        self.assertTrue(self.f.model.types_all_unique(
            (self.f.mon(1, (FIRE, FIRE), slot=0),)))

    def test_shadow_pokemon_is_included_when_given(self):
        dancers = (self.f.mon(1, (FIRE, FIRE), slot=0),)
        shadow = self.f.mon(9, (FIRE, DARK))
        self.assertTrue(self.f.model.types_all_unique(dancers))
        self.assertFalse(self.f.model.types_all_unique(dancers, shadow))


class OccupancyTests(unittest.TestCase):
    def setUp(self):
        self.f = ChamberFixture()

    def test_stage_stride_covers_the_whole_record(self):
        # 984 must be at least the visitor offset plus one Pokemon plus
        # the facing byte, or SETs would overlap in save data.
        self.assertGreaterEqual(
            pc.STAGE_SIZE, pc.VISITOR_OFFSET + pc.DANCER_STRIDE)
        self.assertGreater(pc.STAGE_SIZE, pc.FACING_OFFSET)

    def test_sets_are_addressed_consecutively(self):
        addresses = [self.f.model.stage_address(i) for i in range(pc.STAGE_COUNT)]
        gaps = {b - a for a, b in zip(addresses, addresses[1:])}
        self.assertEqual(gaps, {pc.STAGE_SIZE})

    def test_out_of_range_set_is_rejected(self):
        for index in (-1, pc.STAGE_COUNT):
            with self.assertRaises(Exception):
                self.f.model.stage_address(index)

    def test_occupancy_stops_at_the_first_gap(self):
        # getDancerQuantity breaks at the first empty slot, so a Pokemon
        # left in slot 3 with slot 1 empty is NOT counted. Matching this
        # matters because Tempo pairs by index.
        self.f.species(1, (FIRE, FIRE))
        self.f.species(2, (WATER, WATER))
        self.f.place(0, 0, 1, "FIRSTMON")
        self.f.place(0, 2, 2, "STRANDED")
        dancers = self.f.model.dancers(self.f.model.stage_address(0))
        self.assertEqual([d.nickname for d in dancers], ["FIRSTMON"])

    def test_reading_a_set_end_to_end(self):
        self.f.species(1, (FIRE, FIRE))
        self.f.species(2, (WATER, WATER))
        self.f.species(9, (DARK, DARK))
        self.f.place(0, 0, 1, "EMBER")
        self.f.place(0, 1, 2, "SPLASH")
        self.f.place(0, "visitor", 9, "SHADOW", level=30)
        self.f.face(0, 1)
        result = self.f.model.read_set(0)
        self.assertEqual(result.occupied, 2)
        self.assertEqual(result.visitor.nickname, "SHADOW")
        self.assertEqual(result.visitor.level, 30)
        self.assertEqual(result.facing, 1)
        self.assertEqual(result.tempo, 18)
        self.assertEqual(result.flow, 27)
        self.assertFalse(result.is_perfect)

    def test_empty_chamber_reads_as_nine_empty_sets(self):
        sets = self.f.model.read_all()
        self.assertEqual(len(sets), pc.STAGE_COUNT)
        self.assertTrue(all(s.is_empty for s in sets))
        self.assertTrue(all(s.tempo == 0 and s.flow == 0 for s in sets))


class Catalog:
    """Stands in for RuntimeMessageCatalog. The message-id -> text step is
    already covered end to end by test_phase1e_menus; what matters here is
    that the reader asks for the ids the GAME'S OWN tables specify."""

    def __init__(self, texts=None):
        self.texts = texts or {}
        self.asked = []

    def text(self, message_id):
        self.asked.append(message_id)
        return self.texts.get(message_id)


class Speech:
    def __init__(self):
        self.events = []

    def emit(self, _kind, text, interrupt=False, **_kwargs):
        self.events.append(text)


class Logger:
    def debug(self, *_args, **_kwargs): pass
    def info(self, *_args, **_kwargs): pass
    def warning(self, *_args, **_kwargs): pass


TYPE_NAMES = {
    NORMAL: "NORMAL", FIRE: "FIRE", WATER: "WATER", GRASS: "GRASS",
    ELECTRIC: "ELECTRIC", DARK: "DARK",
}


class ReaderFixture(ChamberFixture):
    TYPE_NAME_BASE = 7000
    SPECIES_NAME_BASE = 8000

    def __init__(self):
        super().__init__()
        texts = {}
        for type_id, name in TYPE_NAMES.items():
            message = self.TYPE_NAME_BASE + type_id
            self.backend.put(
                self.TYPE_BASE + type_id * pc.ZOKUSEI_STRIDE
                + pc.ZOKUSEI_NAME_OFFSET, be32(message))
            texts[message] = name
        # The action-menu labels, at the ids the game's own tables hold.
        texts.update({
            53521: "EXCHANGE", 53522: "ROTATE", 53523: "SUMMARY",
            53524: "CANCEL", 53525: "PLACE", 53526: "MOVE",
        })
        self.catalog = Catalog(texts)
        self.speech = Speech()
        self.reader = pc.PurifyChamberReader(
            self.memory, XD_US_REV0, self.model, self.catalog,
            self.speech, Logger())

    def named_species(self, data_id, types, name):
        self.species(data_id, types, self.SPECIES_NAME_BASE + data_id)
        self.catalog.texts[self.SPECIES_NAME_BASE + data_id] = name

    def action_table(self, key, count, message_ids):
        address = pc.ACTION_MENU_TABLES[key]
        self.backend.put(address, be32(count))
        for index, message_id in enumerate(message_ids):
            self.backend.put(address + 4 + index * 4, be32(message_id))


class DescriptionTests(unittest.TestCase):
    def setUp(self):
        self.f = ReaderFixture()

    def test_empty_set_is_said_to_be_empty(self):
        self.assertEqual(
            self.f.reader.describe_set(self.f.model.read_set(0)),
            "SET 1, empty.")

    def test_set_description_carries_tempo_flow_and_facing(self):
        self.f.named_species(1, (FIRE, FIRE), "CHARMANDER")
        self.f.named_species(2, (WATER, WATER), "SQUIRTLE")
        self.f.named_species(9, (DARK, DARK), "UMBREON")
        self.f.place(0, 0, 1, "EMBER")
        self.f.place(0, 1, 2, "SPLASH")
        self.f.place(0, "visitor", 9, "SHADE", level=30)
        self.f.face(0, 1)
        text = self.f.reader.describe_set(self.f.model.read_set(0))
        self.assertIn("SET 1", text)
        self.assertIn("2 of 4 Pokemon placed", text)
        self.assertIn("Tempo 18", text)
        self.assertIn("Shadow SHADE, level 30, DARK", text)
        self.assertIn("facing position 2, SPLASH", text)
        self.assertIn("Flow 27", text)

    def test_set_without_a_shadow_says_flow_is_zero(self):
        self.f.named_species(1, (FIRE, FIRE), "CHARMANDER")
        self.f.place(0, 0, 1, "EMBER")
        text = self.f.reader.describe_set(self.f.model.read_set(0))
        self.assertIn("no Shadow Pokemon, Flow zero", text)

    def test_species_name_is_used_when_there_is_no_nickname(self):
        self.f.named_species(1, (FIRE, FIRE), "CHARMANDER")
        self.f.place(0, 0, 1, "")
        dancers = self.f.model.dancers(self.f.model.stage_address(0))
        self.assertEqual(
            self.f.reader.describe_pokemon(dancers[0]),
            "CHARMANDER, level 50, FIRE")

    def test_dual_type_is_spoken_once_per_distinct_type(self):
        self.f.named_species(1, (FIRE, WATER), "MON")
        self.f.place(0, 0, 1, "DUAL")
        dancers = self.f.model.dancers(self.f.model.stage_address(0))
        self.assertEqual(
            self.f.reader.describe_pokemon(dancers[0]), "DUAL, level 50, FIRE WATER")

    def test_single_type_is_not_said_twice(self):
        # Stored as (FIRE, FIRE); saying "FIRE FIRE" would be noise.
        self.f.named_species(1, (FIRE, FIRE), "MON")
        self.f.place(0, 0, 1, "SOLO")
        dancers = self.f.model.dancers(self.f.model.stage_address(0))
        self.assertEqual(
            self.f.reader.describe_pokemon(dancers[0]), "SOLO, level 50, FIRE")

    def test_cursor_on_an_occupied_outer_position(self):
        self.f.named_species(1, (FIRE, FIRE), "CHARMANDER")
        self.f.place(0, 0, 1, "EMBER")
        result = self.f.model.read_set(0)
        self.assertEqual(
            self.f.reader.describe_cursor(result, 0),
            "Position 1. EMBER, level 50, FIRE.")

    def test_cursor_on_an_empty_outer_position(self):
        result = self.f.model.read_set(0)
        self.assertEqual(
            self.f.reader.describe_cursor(result, 2), "Position 3, empty.")

    def test_cursor_on_the_empty_centre_says_shadow_only(self):
        result = self.f.model.read_set(0)
        self.assertIn("Shadow Pokemon only",
                      self.f.reader.describe_cursor(result, pc.CENTRE_POSITION))

    def test_cursor_on_the_bottom_row_is_announced_by_position(self):
        # Live sampling saw the cursor reach 7 and 8; before this the reader
        # said nothing there, leaving the bottom row unusable. The label is
        # still unknown, so it announces WHERE the cursor is -- true and
        # derived from _cursorPositionTblDefault's screen coordinates --
        # rather than guessing which button it is.
        result = self.f.model.read_set(0)
        for position in pc.BOTTOM_ROW_POSITIONS:
            described = self.f.reader.describe_cursor(result, position)
            self.assertTrue(described, f"position {position} silent")
            self.assertIn("Bottom menu", described)

    def test_bottom_row_descriptions_do_not_claim_a_button_name(self):
        # Guard against someone "helpfully" filling in a guess later.
        for text in pc.BOTTOM_ROW_DESCRIPTIONS.values():
            lowered = text.lower()
            for invented in ("cancel", "pc/party", "set arrangement", "purify"):
                self.assertNotIn(invented, lowered)

    def test_positions_outside_the_known_set_stay_silent(self):
        result = self.f.model.read_set(0)
        self.assertIsNone(self.f.reader.describe_cursor(result, 99))

    def test_cursor_on_the_occupied_centre(self):
        self.f.named_species(9, (DARK, DARK), "UMBREON")
        self.f.place(0, "visitor", 9, "SHADE", level=30)
        result = self.f.model.read_set(0)
        self.assertEqual(
            self.f.reader.describe_cursor(result, pc.CENTRE_POSITION),
            "Centre. SHADE, level 30, DARK.")


class ActionMenuTests(unittest.TestCase):
    """The six option lists come from the game's own data
    (0x8032E768-0x8032E7E0), each shaped {count, message id...}. Which one
    opens is decided by carrying / centre-or-outer / occupied-or-empty."""

    def setUp(self):
        self.f = ReaderFixture()
        self.f.action_table(("empty-handed", "outer", "occupied"),
                            3, (53526, 53523, 53524))
        self.f.action_table(("empty-handed", "centre", "occupied"),
                            4, (53526, 53522, 53523, 53524))
        self.f.action_table(("carrying", "outer", "empty"),
                            3, (53525, 53523, 53524))
        self.f.action_table(("carrying", "outer", "occupied"),
                            3, (53521, 53523, 53524))

    def test_standing_on_a_placed_pokemon_offers_move(self):
        self.assertEqual(
            self.f.reader._action_options(False, 0, True),
            ("MOVE", "SUMMARY", "CANCEL"))

    def test_the_centre_additionally_offers_rotate(self):
        # ROTATE is how the Shadow Pokemon's facing changes, and facing is
        # half of what decides Flow -- so it must never be dropped.
        self.assertEqual(
            self.f.reader._action_options(False, pc.CENTRE_POSITION, True),
            ("MOVE", "ROTATE", "SUMMARY", "CANCEL"))

    def test_carrying_over_an_empty_spot_offers_place(self):
        self.assertEqual(
            self.f.reader._action_options(True, 1, False),
            ("PLACE", "SUMMARY", "CANCEL"))

    def test_carrying_over_an_occupied_spot_offers_exchange(self):
        self.assertEqual(
            self.f.reader._action_options(True, 1, True),
            ("EXCHANGE", "SUMMARY", "CANCEL"))

    def test_an_implausible_option_count_is_rejected(self):
        self.f.action_table(("empty-handed", "outer", "occupied"), 99, ())
        with self.assertRaises(Exception):
            self.f.reader._action_options(False, 0, True)


class ReaderPollTests(unittest.TestCase):
    MENU = 0x80800000
    CATCH = 0x80900000

    def setUp(self):
        self.f = ReaderFixture()
        self.f.named_species(1, (FIRE, FIRE), "CHARMANDER")
        self.f.named_species(2, (WATER, WATER), "SQUIRTLE")
        self.f.place(0, 0, 1, "EMBER")
        self.f.place(0, 1, 2, "SPLASH")
        self.f.place(1, 0, 1, "OTHER")
        self.f.backend.put(pc.MENU_POINTER, be32(self.MENU))
        self.f.backend.put(self.MENU + pc.MENU_CATCH_OFFSET, be32(self.CATCH))
        self.cursor(0)
        self.select(0)

    def select(self, index):
        self.f.backend.put(
            self.MENU + pc.MENU_STAGE_INDEX_OFFSET, be32(index))

    def cursor(self, position):
        self.f.backend.put(
            self.CATCH + pc.CATCH_POSITION_OFFSET, be32(position))

    def carry(self, data_id, nickname="CARRIED"):
        self.f.backend.put(
            self.CATCH + pc.CATCH_POKEMON_OFFSET + pc.POKEMON_DATA_ID_OFFSET,
            be16(data_id))
        self.f.backend.put(
            self.CATCH + pc.CATCH_POKEMON_OFFSET + pc.POKEMON_NICKNAME_OFFSET,
            gschar(nickname))

    def test_closed_chamber_says_nothing(self):
        self.f.backend.put(pc.MENU_POINTER, be32(0))
        self.f.reader.poll_once()
        self.assertEqual(self.f.speech.events, [])

    def test_first_poll_announces_the_set_and_the_cursor(self):
        self.f.reader.poll_once()
        self.assertEqual(len(self.f.speech.events), 2)
        self.assertIn("SET 1", self.f.speech.events[0])
        self.assertIn("Tempo", self.f.speech.events[0])
        self.assertIn("Position 1", self.f.speech.events[1])

    def test_an_unchanged_poll_repeats_nothing(self):
        self.f.reader.poll_once()
        before = len(self.f.speech.events)
        self.f.reader.poll_once()
        self.f.reader.poll_once()
        self.assertEqual(len(self.f.speech.events), before)

    def test_moving_the_cursor_announces_only_the_new_position(self):
        self.f.reader.poll_once()
        self.f.speech.events.clear()
        self.cursor(1)
        self.f.reader.poll_once()
        self.assertEqual(self.f.speech.events, ["Position 2. SPLASH, level 50, WATER."])

    def test_switching_sets_re_announces_the_whole_set(self):
        # Switching with L/R is how SETs get compared, so the full state
        # is repeated rather than just the number.
        self.f.reader.poll_once()
        self.f.speech.events.clear()
        self.select(1)
        self.f.reader.poll_once()
        self.assertIn("SET 2", self.f.speech.events[0])
        self.assertIn("Tempo", self.f.speech.events[0])

    def test_switching_sets_re_announces_the_cursor_too(self):
        # The same cursor index means a different Pokemon on a different
        # SET, so it must not be suppressed as unchanged.
        self.f.reader.poll_once()
        self.f.speech.events.clear()
        self.select(1)
        self.f.reader.poll_once()
        self.assertTrue(
            any("Position 1" in event for event in self.f.speech.events),
            self.f.speech.events)

    def test_picking_a_pokemon_up_is_announced(self):
        self.f.reader.poll_once()
        self.f.speech.events.clear()
        self.carry(1, "EMBER")
        self.f.reader.poll_once()
        self.assertIn("Holding EMBER.", self.f.speech.events)

    def test_putting_a_pokemon_down_is_announced(self):
        self.carry(1, "EMBER")
        self.f.reader.poll_once()
        self.f.speech.events.clear()
        self.f.backend.put(
            self.CATCH + pc.CATCH_POKEMON_OFFSET + pc.POKEMON_DATA_ID_OFFSET,
            be16(0))
        self.f.reader.poll_once()
        self.assertIn("Released EMBER.", self.f.speech.events)

    def test_leaving_the_chamber_clears_state(self):
        self.f.reader.poll_once()
        self.f.backend.put(pc.MENU_POINTER, be32(0))
        self.f.reader.poll_once()
        self.assertFalse(self.f.reader.active)
        self.assertIsNone(self.f.reader.last_set)

    def test_an_impossible_set_index_is_rejected(self):
        self.select(pc.STAGE_COUNT)
        with self.assertRaises(Exception):
            self.f.reader.poll_once()


if __name__ == "__main__":
    unittest.main()
