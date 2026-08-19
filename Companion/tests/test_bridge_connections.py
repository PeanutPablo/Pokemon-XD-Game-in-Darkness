"""Live bridge connection points for Gateon Port's rotating piers.

`PolarityTests` is the one that matters. Reading `enable` backwards points
a blind player at a wall in every alignment, and this project did exactly
that from 2026-08-09 to 2026-08-18. The tests here now pin the evidence
that actually decides it -- what the collision data IS -- rather than the
`ALIGNMENTS` prose that used to be the oracle, which turned out to be a
field-for-field restatement of the same enable bits and so agreed with
whichever reading produced it.

`RealRoomTests` run against the project owner's own extracted `M6_out`
data when it is present, and skip cleanly when it is not, so this file is
useful on a machine without the extraction and authoritative on one with
it.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.bridge_connections import (
    BLOCKED, BRIDGE_FLAG, OPEN, BridgeConnectionEntitySource, Deck, Segment,
    derive_layout, interior_facing_entries, parse_pier_enable_table,
)
from battle_narrator.collision_probe import (
    parse_environment_triangles, parse_walk_model_triangles,
)
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.profile import XD_US_REV0


# The retired `gateon_bridge.py`'s alignment table. NO LONGER AN ORACLE --
# it is a restatement of the enable bits (state 0's "north and west" is
# exactly {24, 27}; "centre open" is exactly `26 == 1`), so it agrees with
# whichever polarity was used to write it and can decide nothing. Kept only
# so `test_the_retired_prose_cannot_decide_the_polarity` can demonstrate
# that, and so nobody reinstates it as evidence a third time.
ALIGNMENTS = {
    0: ("north and west", "east and west", False),
    1: ("south and west", "north and south", False),
    2: ("east and south", "east and west", True),
    3: ("east and north", "north and south", True),
}


COMPANION = Path(__file__).parents[1]
SCRIPT = COMPANION / "_dialogue_extraction" / "rooms" / "M6_out.txt"
COLLISION = COMPANION / "_dialogue_extraction" / "collision" / "M6_out.ccd"
HAVE_REAL_DATA = SCRIPT.exists() and COLLISION.exists()

GATEON_ROOM = 0x99


class Triangle:
    def __init__(self, vertices, entry_index):
        self.vertices = vertices
        self.entry_index = entry_index


def quad(x0, x1, z0, z1, entry_index, y=0.0):
    return [
        Triangle((( x0, y, z0), (x1, y, z0), (x1, y, z1)), entry_index),
        Triangle((( x0, y, z0), (x1, y, z1), (x0, y, z1)), entry_index),
    ]


class Pose:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.position = Position(x, y, z)

    def player_pose(self):
        return PlayerPose(self.position, 0.0, 0.0)


class Memory:
    def __init__(self, room=GATEON_ROOM):
        self.room = room

    def u16(self, address, label):
        return self.room


class Flags:
    def __init__(self, value=0):
        self.value_by_flag = {BRIDGE_FLAG: value}

    def value(self, flag):
        return self.value_by_flag[flag]


class Logger:
    def __init__(self):
        self.lines = []

    def _render(self, args):
        if len(args) > 1:
            try:
                return args[0] % tuple(args[1:])
            except (TypeError, ValueError):
                pass
        return " ".join(str(a) for a in args)

    def debug(self, *args):
        self.lines.append(self._render(args))

    def info(self, *args):
        self.lines.append(self._render(args))

    def warning(self, *args):
        self.lines.append(self._render(args))


# --------------------------------------------------------------------------
# A miniature pier: two 20x20 decks, four segments each, one centre passage.
# Same shape as the real one, small enough to reason about by hand.
# --------------------------------------------------------------------------

def synthetic():
    walk = quad(-10, 10, 90, 110, 58) + quad(-10, 10, -110, -90, 59)
    walk += quad(-500, 500, -600, 600, 45)          # the ground plane
    hit = []
    hit += quad(12, 60, 95, 105, 1)                 # north deck, east span
    hit += quad(-5, 5, 112, 160, 2)                 # north deck, north span
    hit += quad(-5, 5, 86, 88, 3)                   # north deck, south plate
    hit += quad(-14, -12, 95, 105, 4)               # north deck, west plate
    hit += quad(12, 14, -105, -95, 5)               # south deck, east plate
    hit += quad(-5, 5, -88, -86, 6)                 # south deck, north plate
    hit += quad(-5, 5, -160, -112, 7)               # south deck, south span
    hit += quad(-14, -12, -105, -95, 8)             # south deck, west plate
    hit += quad(-17, 17, -1, 1, 9)                  # the centre passage
    return walk, hit, set(range(1, 10))


def synthetic_layout():
    walk, hit, entries = synthetic()
    return derive_layout(walk, hit, entries)


def make_source(table, alignment=0, room=GATEON_ROOM, pose=None, logger=None):
    decks, segments = synthetic_layout()
    source = BridgeConnectionEntitySource(
        Memory(room), XD_US_REV0, Flags(alignment), pose or Pose(),
        GATEON_ROOM, decks, segments, logger=logger)
    source.enable_table = table
    return source


ALL_OPEN = {0: {entry: OPEN for entry in range(1, 10)}}
"""Every blocker switched off, i.e. every direction crossable."""


class TableParsingTests(unittest.TestCase):
    SCRIPT = "\n".join([
        "pier_def:",
        "\treserve       2",
        "\tldimm         int, =968",
        "\tcallstd       getFlag",
        "\tldvar         $lastResult",
        "\tldimm         int, =0",
        "\toperator      equ",
        "\tjmpfalse      loc_1",
        "\tldimm         int, =1",
        "\tldimm         int, =23",
        "\tcallstd       UnknownClass46::16",
        "\tldimm         int, =0",
        "\tldimm         int, =24",
        "\tcallstd       UnknownClass46::16",
        "loc_1:",
        "\tldimm         int, =968",
        "\tcallstd       getFlag",
        "\tldvar         $lastResult",
        "\tldimm         int, =1",
        "\toperator      equ",
        "\tjmpfalse      loc_2",
        "\tldimm         int, =0",
        "\tldimm         int, =23",
        "\tcallstd       UnknownClass46::16",
        "\tldimm         int, =1",
        "\tldimm         int, =24",
        "\tcallstd       UnknownClass46::16",
        "pier_move:",
        "\tldimm         int, =0",
        "\tldimm         int, =99",
        "\tcallstd       UnknownClass46::16",
    ])

    def test_states_and_entries_are_parsed(self):
        self.assertEqual(
            parse_pier_enable_table(self.SCRIPT),
            {0: {23: 1, 24: 0}, 1: {23: 0, 24: 1}})

    def test_parsing_stops_at_the_next_function(self):
        # `pier_move` also calls SetObjEnable; leaking into it would invent
        # a tenth object nothing drives.
        table = parse_pier_enable_table(self.SCRIPT)
        self.assertNotIn(99, table.get(0, {}))
        self.assertNotIn(99, table.get(1, {}))

    def test_an_unknown_function_yields_nothing(self):
        self.assertEqual(
            parse_pier_enable_table(self.SCRIPT, function="not_a_function"), {})


class LayoutTests(unittest.TestCase):
    def test_two_decks_are_derived_and_the_ground_plane_is_not_one(self):
        decks, _ = synthetic_layout()
        self.assertEqual(len(decks), 2)
        self.assertNotIn(45, [deck.entry_index for deck in decks])

    def test_deck_names_come_from_their_own_z_order(self):
        decks, _ = synthetic_layout()
        northern = next(d for d in decks if d.name == "Northern")
        southern = next(d for d in decks if d.name == "Southern")
        self.assertGreater(northern.centre[1], southern.centre[1])

    def test_every_segment_gets_a_compass_direction_from_geometry(self):
        _, segments = synthetic_layout()
        found = {
            segment.entry_index: (
                None if segment.deck is None
                else (segment.deck.name, segment.direction))
            for segment in segments
        }
        self.assertEqual(found[1], ("Northern", "east"))
        self.assertEqual(found[2], ("Northern", "north"))
        self.assertEqual(found[3], ("Northern", "south"))
        self.assertEqual(found[4], ("Northern", "west"))
        self.assertEqual(found[5], ("Southern", "east"))
        self.assertEqual(found[6], ("Southern", "north"))
        self.assertEqual(found[7], ("Southern", "south"))
        self.assertEqual(found[8], ("Southern", "west"))

    def test_the_passage_between_the_decks_belongs_to_neither(self):
        _, segments = synthetic_layout()
        passage = next(s for s in segments if s.entry_index == 9)
        self.assertIsNone(passage.deck)
        self.assertIsNone(passage.direction)
        self.assertEqual(passage.label, "Centre passage")

    def test_labels_name_the_pier_and_the_direction(self):
        _, segments = synthetic_layout()
        labels = {s.entry_index: s.label for s in segments}
        self.assertEqual(labels[2], "Northern bridge, north connection")
        self.assertEqual(labels[5], "Southern bridge, east connection")

    def test_geometry_with_no_decks_derives_nothing_rather_than_guessing(self):
        _, hit, entries = synthetic()
        decks, segments = derive_layout([], hit, entries)
        self.assertEqual(decks, ())
        self.assertEqual(segments, ())


def row(*blocked):
    """One alignment row: the named entries blocked, the rest open."""
    return {entry: (BLOCKED if entry in blocked else OPEN)
            for entry in range(1, 10)}


class PublicationTests(unittest.TestCase):
    def test_only_currently_open_connections_are_published(self):
        # Entries 1 and 4 have their blockers switched ON, so they are the
        # two that must NOT appear. This is the case that was inverted.
        entities = make_source({0: row(1, 4)}).entities()
        self.assertEqual(
            sorted(e.identity[1] for e in entities), [2, 3, 5, 6, 7, 8, 9])

    def test_a_blocked_direction_is_never_published(self):
        for blocked in range(1, 10):
            with self.subTest(blocked=blocked):
                published = [
                    e.identity[1]
                    for e in make_source({0: row(blocked)}).entities()]
                self.assertNotIn(blocked, published)

    def test_an_entry_this_alignment_does_not_mention_is_withheld(self):
        # Not open, not blocked, not known. A connection that cannot be
        # shown to be open must not be offered.
        table = {0: {entry: OPEN for entry in range(1, 10) if entry != 5}}
        published = [e.identity[1] for e in make_source(table).entities()]
        self.assertNotIn(5, published)

    def test_a_rotation_replaces_the_published_connections(self):
        table = {0: row(1, 4), 1: row(2, 3)}
        source = make_source(table)
        self.assertEqual(
            sorted(e.identity[1] for e in source.entities()),
            [2, 3, 5, 6, 7, 8, 9])
        source.flag_reader.value_by_flag[BRIDGE_FLAG] = 1
        self.assertEqual(
            sorted(e.identity[1] for e in source.entities()),
            [1, 4, 5, 6, 7, 8, 9])

    def test_a_rotation_advances_the_generation(self):
        table = {0: {1: OPEN}, 1: {1: OPEN}}
        source = make_source(table)
        source.entities()
        first = source.generation
        source.flag_reader.value_by_flag[BRIDGE_FLAG] = 1
        source.entities()
        self.assertEqual(source.generation, first + 1)

    def test_repeated_queries_in_one_alignment_do_not_advance_it(self):
        source = make_source(ALL_OPEN)
        for _ in range(5):
            source.entities()
        self.assertEqual(source.generation, 1)

    def test_another_room_publishes_nothing(self):
        self.assertEqual(make_source(ALL_OPEN, room=0x86).entities(), [])

    def test_an_alignment_the_script_does_not_define_publishes_nothing(self):
        source = make_source({0: {1: 1}}, alignment=7)
        self.assertEqual(source.entities(), [])

    def test_an_unreadable_flag_publishes_nothing(self):
        source = make_source(ALL_OPEN)

        class Broken:
            def value(self, flag):
                raise RuntimeError("no flag")

        source.flag_reader = Broken()
        self.assertEqual(source.entities(), [])

    def test_connections_carry_no_interaction_radius(self):
        # Walk-into, not press-A: inventing a radius would make entity nav
        # promise "Interaction available" for something A does nothing to.
        for entity in make_source(ALL_OPEN).entities():
            self.assertIsNone(entity.interaction_distance)

    def test_position_uses_the_deck_walk_height_not_the_wall_top(self):
        # The hit models are tall; the player's Y is their feet. Using the
        # geometry's own Y would report every connection as "above".
        for entity in make_source(ALL_OPEN).entities():
            self.assertLess(abs(entity.position.y), 1.0)

    def test_interaction_position_is_the_nearest_point_not_the_centre(self):
        # Entry 2 is the north span, z 112..160, centred at z=136.
        source = make_source(ALL_OPEN, pose=Pose(x=0.0, z=90.0))
        entity = next(e for e in source.entities() if e.identity[1] == 2)
        self.assertAlmostEqual(entity.position.z, 136.0, places=3)
        self.assertAlmostEqual(
            entity.metadata["interaction_position"].z, 112.0, places=3)

    def test_the_nearest_point_tracks_the_player(self):
        table = ALL_OPEN
        near = make_source(table, pose=Pose(x=0.0, z=90.0))
        far = make_source(table, pose=Pose(x=0.0, z=200.0))
        near_z = next(
            e for e in near.entities() if e.identity[1] == 2
        ).metadata["interaction_position"].z
        far_z = next(
            e for e in far.entities() if e.identity[1] == 2
        ).metadata["interaction_position"].z
        self.assertAlmostEqual(near_z, 112.0, places=3)
        self.assertAlmostEqual(far_z, 160.0, places=3)

    def test_no_layout_publishes_nothing(self):
        source = BridgeConnectionEntitySource(
            Memory(), XD_US_REV0, Flags(0), Pose(), GATEON_ROOM, (), ())
        self.assertEqual(source.entities(), [])


class DeadEndTests(unittest.TestCase):
    """Open is necessary but not sufficient: a gate onto nothing is not a
    place to walk to.

    In the synthetic layout entry 3 is the northern deck's south gate and
    entry 6 the southern deck's north gate -- the two that face each other
    across the centre passage, entry 9.
    """

    def published(self, table):
        return sorted(e.identity[1] for e in make_source(table).entities())

    def test_the_interior_gates_are_derived_from_the_deck_positions(self):
        decks, segments = synthetic_layout()
        self.assertEqual(
            sorted(interior_facing_entries(decks, segments)), [3, 6])

    def test_an_interior_gate_is_withheld_when_the_passage_is_blocked(self):
        published = self.published({0: row(9)})
        self.assertNotIn(3, published)
        self.assertNotIn(6, published)
        self.assertNotIn(9, published)
        # Everything facing outward is unaffected.
        self.assertEqual(published, [1, 2, 4, 5, 7, 8])

    def test_the_passage_is_withheld_when_no_interior_gate_is_open(self):
        published = self.published({0: row(3, 6)})
        self.assertNotIn(9, published)
        self.assertEqual(published, [1, 2, 4, 5, 7, 8])

    def test_one_open_interior_gate_keeps_both_it_and_the_passage(self):
        published = self.published({0: row(6)})
        self.assertIn(3, published)
        self.assertIn(9, published)

    def test_a_fully_open_middle_publishes_the_whole_crossing(self):
        published = self.published({0: row()})
        self.assertEqual(published, [1, 2, 3, 4, 5, 6, 7, 8, 9])

    def test_a_layout_without_two_decks_withholds_nothing(self):
        # The safe direction: with no derivable interior, no gate is
        # dropped, which is the behaviour before this rule existed.
        self.assertEqual(interior_facing_entries((), ()), frozenset())


class PolarityTests(unittest.TestCase):
    """Does `enable == 1` mean CONNECTED or BLOCKED?

    BLOCKED. Getting this backwards points a blind player at a wall in
    every alignment, and this project shipped it backwards from 2026-08-09
    until the project owner reported it on 2026-08-18.

    The tests below pin the evidence that actually decides it -- what the
    room's collision data IS -- plus a demonstration of why the evidence
    originally used could not decide anything.
    """

    ORDER = ("north", "east", "south", "west")

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def setUp(self):
        self.table = parse_pier_enable_table(
            SCRIPT.read_text(encoding="utf-8", errors="replace"))
        self.data = COLLISION.read_bytes()
        self.entries = {
            entry for r in self.table.values() for entry in r}

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def test_no_pier_object_is_walkable(self):
        """The decisive fact. A thing you cannot stand on is not a
        connection -- entries 23-31 contribute nothing to the walk model
        and exist only as collision geometry."""
        walk = parse_walk_model_triangles(self.data)
        walkable = {triangle.entry_index for triangle in walk}
        self.assertEqual(sorted(self.entries & walkable), [])
        # The surfaces that ARE walkable here are the two decks and the
        # ground mesh, so the room is not simply missing a walk model.
        self.assertTrue({58, 59}.issubset(walkable))

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def test_most_pier_objects_are_zero_thickness_planes(self):
        """A quad collapsed onto a single plane has no footprint to stand
        on. Seven of the nine are gates -- six across the 20-unit opening
        in one side of a pier's railing, plus the centre passage. Only 23
        and 24 are closed volumes, and neither is walkable either."""
        environment = parse_environment_triangles(self.data)
        flat = []
        for entry in sorted(self.entries):
            triangles = [t for t in environment if t.entry_index == entry]
            self.assertTrue(triangles, f"entry {entry} has no hit geometry")
            points = [v for t in triangles for v in t.vertices]
            width = max(p[0] for p in points) - min(p[0] for p in points)
            depth = max(p[2] for p in points) - min(p[2] for p in points)
            if min(width, depth) < 1.0:
                flat.append(entry)
        self.assertEqual(flat, [25, 26, 27, 28, 29, 30, 31])
        self.assertEqual(sorted(set(self.entries) - set(flat)), [23, 24])

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def test_the_crossing_between_the_piers_is_possible_under_blocked(self):
        """The corrected reading makes the puzzle solvable; the old one did
        not. Crossing between the piers passes three gates in a line: the
        northern deck's south gate, the centre passage, and the southern
        deck's north gate. Under `1 == blocked` exactly one alignment opens
        all three. Under `1 == connected` no alignment ever did, which
        would make the two piers permanently uncrossable."""
        decks, segments = derive_layout(
            parse_walk_model_triangles(self.data),
            parse_environment_triangles(self.data), self.entries)
        chain = set(interior_facing_entries(decks, segments)) | {
            s.entry_index for s in segments if s.deck is None}
        self.assertEqual(sorted(chain), [25, 26, 29])
        crossable = {
            polarity: [
                state for state, r in sorted(self.table.items())
                if all(r[entry] == polarity for entry in chain)
            ]
            for polarity in (OPEN, BLOCKED)
        }
        self.assertEqual(crossable[OPEN], [0])
        self.assertEqual(crossable[BLOCKED], [])

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def test_the_retired_prose_cannot_decide_the_polarity(self):
        """Why this was got wrong. `ALIGNMENTS` agrees 12 of 12 with
        `enable == 1` -- but only because it is a restatement of those very
        bits, so the agreement is guaranteed and carries no information.
        The check is kept as a warning, not as evidence."""
        decks, segments = derive_layout(
            parse_walk_model_triangles(self.data),
            parse_environment_triangles(self.data), self.entries)
        by_deck = {}
        for segment in segments:
            if segment.deck is not None:
                by_deck.setdefault(segment.deck.name, []).append(segment)
        passage = next(s for s in segments if s.deck is None)
        agreements = {1: 0, 0: 0}
        total = 0
        for state, r in sorted(self.table.items()):
            north_text, south_text, centre_flag = ALIGNMENTS[state]
            for name, text in (("Northern", north_text),
                               ("Southern", south_text)):
                expected = sorted(text.split(" and "), key=self.ORDER.index)
                total += 1
                for polarity in (1, 0):
                    derived = sorted(
                        (seg.direction for seg in by_deck[name]
                         if r.get(seg.entry_index) == polarity),
                        key=self.ORDER.index)
                    agreements[polarity] += derived == expected
            total += 1
            for polarity in (1, 0):
                agreements[polarity] += (
                    (r.get(passage.entry_index) == polarity) == centre_flag)
        self.assertEqual(total, 12)
        # It reproduces the enable bits exactly -- which is the point: this
        # is the same table wearing different words, not a second source.
        self.assertEqual(agreements[1], 12)
        self.assertEqual(agreements[0], 0)


class RealRoomTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def setUp(self):
        self.table = parse_pier_enable_table(
            SCRIPT.read_text(encoding="utf-8", errors="replace"))
        data = COLLISION.read_bytes()
        self.decks, self.segments = derive_layout(
            parse_walk_model_triangles(data), parse_environment_triangles(data),
            {entry for row in self.table.values() for entry in row})

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def test_the_script_defines_four_alignments_over_nine_segments(self):
        self.assertEqual(sorted(self.table), [0, 1, 2, 3])
        for row in self.table.values():
            self.assertEqual(sorted(row), list(range(23, 32)))

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def test_the_two_real_decks_are_the_pier_walk_surfaces(self):
        self.assertEqual(
            sorted(deck.entry_index for deck in self.decks), [58, 59])

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def test_deck_naming_is_derived_and_matches_the_shipped_naming(self):
        # The retired reader used {58: "southern", 59: "northern"}.
        # Deriving it from Z must reproduce that independent observation.
        names = {deck.entry_index: deck.name for deck in self.decks}
        self.assertEqual(names[59], "Northern")
        self.assertEqual(names[58], "Southern")

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def test_each_real_deck_has_exactly_four_directions(self):
        for name in ("Northern", "Southern"):
            directions = sorted(
                s.direction for s in self.segments
                if s.deck is not None and s.deck.name == name)
            self.assertEqual(directions, ["east", "north", "south", "west"])

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def test_entry_26_is_the_passage_and_nothing_else_is(self):
        passages = [s.entry_index for s in self.segments if s.deck is None]
        self.assertEqual(passages, [26])

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def test_every_alignment_offers_exactly_two_connections_per_deck(self):
        for state, row in self.table.items():
            for name in ("Northern", "Southern"):
                live = [
                    s for s in self.segments
                    if s.deck is not None and s.deck.name == name
                    and row[s.entry_index] == OPEN
                ]
                self.assertEqual(
                    len(live), 2,
                    f"alignment {state}, {name} deck offered {len(live)}")

    @unittest.skipUnless(HAVE_REAL_DATA, "extracted M6_out data not present")
    def test_no_alignment_leaves_a_deck_unreachable(self):
        # A pier you can walk onto but not off would be a trap, and one
        # with no connections at all would mean the derivation is wrong.
        for state, row in self.table.items():
            for name in ("Northern", "Southern"):
                self.assertTrue(any(
                    row[s.entry_index] == OPEN for s in self.segments
                    if s.deck is not None and s.deck.name == name))


class BridgeCategoryTests(unittest.TestCase):
    def test_bridge_is_a_separate_aligned_navigation_category(self):
        keys = XD_US_REV0.entity_nav_category_keys
        singular = XD_US_REV0.entity_nav_category_singular_labels
        plural = XD_US_REV0.entity_nav_category_plural_labels
        index = keys.index("bridge")
        self.assertEqual(singular[index], "Bridge")
        self.assertEqual(plural[index], "Bridges")
        self.assertNotEqual(index, keys.index("exit"))


if __name__ == "__main__":
    unittest.main()
