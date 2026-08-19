"""Tests for reading move-type names from the game rather than a list.

The defect these pin: `LocalMoveData` used to carry a hardcoded tuple of
type names, and its index 9 said "Unknown". Vanilla XD leaves slot 9
unused ("?"), but Pokémon XG puts **Fairy** there, so 15 XG moves were
announced as "Unknown-type". Nothing about the build identifies which
meaning applies — the two discs share a label and pass every engine
signature — so the name has to come from the game's own type table.

The table is REL pointer 130 in `common.rel`: 0x30-byte records with a
u32 name message ID at +0x08. That shape is not invented here; it is what
`purify_chamber.py` already reads live, and the pointer index was found
offline by searching every REL pointer for the one base whose records all
resolve to short control-free strings.

Message ID 3018 below is real: it is slot 9's name ID in both images, and
it resolves to "?" on vanilla and "Fairy" on XG. Building both cases from
the same code is the whole point."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.messages import LocalDataError
from battle_narrator.resolver import LocalMoveData

SLOT_9_NAME_ID = 3018


def tokens(text):
    return [("char", ord(c)) for c in text]


class FakeRel:
    def __init__(self, base):
        self.base = base
        self.asked = []

    def get_pointer(self, index):
        self.asked.append(index)
        return self.base


def build(type_labels, base=0x100, trailing_id=None):
    """A LocalMoveData holding just enough to read the type table."""
    data = LocalMoveData.__new__(LocalMoveData)
    stride = LocalMoveData.TYPE_TABLE_STRIDE
    offset = LocalMoveData.TYPE_TABLE_NAME_OFFSET
    blob = bytearray(base + (len(type_labels) + 2) * stride)
    names = {}
    for index, label in enumerate(type_labels):
        name_id = 3000 + index if label != "?" else SLOT_9_NAME_ID
        struct.pack_into(">I", blob, base + index * stride + offset, name_id)
        names[name_id] = tokens(label)
    if trailing_id is not None:
        struct.pack_into(
            ">I", blob, base + len(type_labels) * stride + offset, trailing_id)
    data.data = bytes(blob)
    data.names = names
    return data, FakeRel(base)


class SpokenTypeNameTests(unittest.TestCase):
    def test_expands_the_battle_ui_abbreviations(self):
        """These are widget truncations, not words; NVDA should not read
        "PSYCHC" aloud."""
        self.assertEqual(LocalMoveData.spoken_type_name("FIGHT"), "Fighting")
        self.assertEqual(LocalMoveData.spoken_type_name("ELECTR"), "Electric")
        self.assertEqual(LocalMoveData.spoken_type_name("PSYCHC"), "Psychic")

    def test_expansion_is_keyed_on_text_not_on_index(self):
        """Vanilla shouts, XG title-cases; both must reach the same word."""
        for stored in ("Psychc", "PSYCHC", "psychc"):
            self.assertEqual(
                LocalMoveData.spoken_type_name(stored), "Psychic")

    def test_an_unlisted_name_passes_through(self):
        """The property that makes this safe for a hack: a type this code
        has never heard of is spoken as the game names it, not mapped to
        something else."""
        self.assertEqual(LocalMoveData.spoken_type_name("Fairy"), "Fairy")
        self.assertEqual(LocalMoveData.spoken_type_name("SPARKLE"), "Sparkle")


class ReadTypeNamesTests(unittest.TestCase):
    VANILLA = ["NORMAL", "FIGHT", "FLYING", "POISON", "GROUND", "ROCK",
               "BUG", "GHOST", "STEEL", "?", "FIRE", "WATER", "GRASS",
               "ELECTR", "PSYCHC", "ICE", "DRAGON", "DARK"]
    XG = ["Normal", "Fight", "Flying", "Poison", "Ground", "Rock",
          "Bug", "Ghost", "Steel", "Fairy", "Fire", "Water", "Grass",
          "Electr", "Psychc", "Ice", "Dragon", "Dark"]

    def test_reads_the_table_through_the_documented_rel_pointer(self):
        data, rel = build(self.VANILLA)
        data._read_type_names(rel)
        self.assertEqual(rel.asked, [LocalMoveData.TYPE_TABLE_POINTER])

    def test_vanilla_layout_yields_the_names_it_always_spoke(self):
        data, rel = build(self.VANILLA)
        names = data._read_type_names(rel)
        self.assertEqual(len(names), 18)
        self.assertEqual(
            names[:9],
            ("Normal", "Fighting", "Flying", "Poison", "Ground", "Rock",
             "Bug", "Ghost", "Steel"))
        self.assertEqual(
            names[10:],
            ("Fire", "Water", "Grass", "Electric", "Psychic", "Ice",
             "Dragon", "Dark"))

    def test_slot_9_follows_the_game_and_not_a_default(self):
        """The regression. Same code, same slot, two builds, two answers --
        and neither is the old invented "Unknown"."""
        vanilla, rel = build(self.VANILLA)
        xg, xg_rel = build(self.XG)
        self.assertEqual(vanilla._read_type_names(rel)[9], "?")
        self.assertEqual(xg._read_type_names(xg_rel)[9], "Fairy")

    def test_stops_where_the_names_stop_resolving(self):
        """Bounds the table without needing a count: the record after the
        last type points at a message that is not in the string table."""
        data, rel = build(self.VANILLA, trailing_id=51)
        self.assertEqual(len(data._read_type_names(rel)), 18)

    def test_a_table_that_resolves_nothing_is_an_error(self):
        """Silence beats guessing: a disc whose type data is not in this
        layout must fail loudly at load rather than fall back to a list."""
        data, rel = build([])
        with self.assertRaises(LocalDataError):
            data._read_type_names(rel)


class NoVanillaFallbackTests(unittest.TestCase):
    def test_there_is_no_hardcoded_type_name_list_left(self):
        """Guards the direction of the fix, not just its result.

        Reintroducing a built-in list of type names would restore the exact
        bug: it would be correct for whichever build it was written from
        and silently wrong for the other."""
        self.assertFalse(
            hasattr(LocalMoveData, "TYPE_NAMES"),
            "LocalMoveData.TYPE_NAMES is back; type names must be read "
            "from the game's own zokusei table, not listed in code.")

    def test_the_spoken_map_holds_no_type_identities(self):
        """The expansion map is allowed to fix pronunciation, never to
        decide what a type IS -- so it must not mention any type absent
        from the abbreviations it exists to expand."""
        self.assertEqual(
            set(LocalMoveData.SPOKEN_TYPE_NAMES),
            {"FIGHT", "ELECTR", "PSYCHC"})


if __name__ == "__main__":
    unittest.main()
