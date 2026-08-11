"""Room-script interactable objects and hazards (Phase 4).

`RealTableTests` run against the generated `assets/interactables.json` and
the owner's extracted collision data, so the classification is checked
against the real game rather than only against fixtures.
"""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.interactable_roles import (
    BED, FALL, GENERIC_LABEL, HEALING, LABELS, PLATE, SHRINE, TELEVISION,
    VENDING, build_table, classify,
)
from battle_narrator.interactables import (
    InteractableRecord, RoomScriptInteractableSource, load_records,
)
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.profile import XD_US_REV0
from battle_narrator.region_geometry import Region, parse_regions

COMPANION = Path(__file__).parents[1]
ASSET = COMPANION / "assets" / "interactables.json"
COLLISION = COMPANION / "_dialogue_extraction" / "collision"
HAVE_ASSET = ASSET.exists()
HAVE_COLLISION = COLLISION.is_dir()

ROOM = 0x86


class Pose:
    def __init__(self, x=0.0, z=0.0):
        self.position = Position(x, 0.0, z)

    def player_pose(self):
        return PlayerPose(self.position, 0.0, 0.0)


class Memory:
    def __init__(self, room=ROOM):
        self.room = room

    def u16(self, address, label):
        return self.room


class Logger:
    def __init__(self):
        self.lines = []

    def debug(self, *args):
        self.lines.append(args)

    def info(self, *args):
        self.lines.append(args)

    def warning(self, *args):
        self.lines.append(args)


def square(index, x0, x1, z0, z1, y=0.0):
    """A rectangular region, as the two triangles the CCD would carry."""
    return Region(
        index=index,
        triangles=(
            (((x0, y, z0), (x1, y, z0), (x1, y, z1))),
            (((x0, y, z0), (x1, y, z1), (x0, y, z1))),
        ),
        anchor=((x0 + x1) / 2, y, (z0 + z1) / 2),
    )


def record(index=0, room=ROOM, region=0, method=3, handler="watch_tv",
           semantic=TELEVISION):
    return InteractableRecord(
        index=index, room_id=room, region_index=region, method=method,
        handler=handler, semantic=semantic)


def make_source(records, regions, category="interact", pose=None, room=ROOM):
    source = RoomScriptInteractableSource(
        Memory(room), XD_US_REV0, pose or Pose(), records, Path("."), {},
        category=category, logger=Logger())
    source._regions[room] = regions
    return source


class ClassificationTests(unittest.TestCase):
    """Markers are direct calls, and each was checked for exclusivity
    across all 89 handlers before adoption."""

    def test_bed_is_recognised_by_its_rest_call(self):
        self.assertEqual(classify({"Player::57", "Dialogs::18"}), BED)

    def test_healing_needs_both_of_its_calls(self):
        self.assertEqual(
            classify({"Character::101", "Player::countPartyPkm"}), HEALING)
        self.assertIsNone(classify({"Character::101"}))

    def test_tako_machine_classifies_as_healing_not_by_its_name(self):
        # The finding that could not have come from the name: tako_machine
        # calls useHealingMachine exactly as the Centre handlers do.
        self.assertEqual(
            classify({"Character::101", "Player::countPartyPkm",
                      "Dialogs::displayYesNoQuestion"}), HEALING)

    def test_television_is_recognised_by_its_playback_call(self):
        self.assertEqual(classify({"UnknownClass38::50"}), TELEVISION)

    def test_a_television_that_prints_nothing_still_classifies(self):
        # watch_tv_l / watch_tv_r make no message call at all.
        self.assertEqual(
            classify({"Tasks::sleep", "Transition::setup",
                      "UnknownClass38::50"}), TELEVISION)

    def test_plate_shrine_and_vending_markers(self):
        self.assertEqual(classify({"UnknownClass60::16"}), PLATE)
        self.assertEqual(
            classify({"Player::countPurfiedPkm", "UnknownClass50::17"}),
            SHRINE)
        self.assertEqual(classify({"Dialogs::openPokemartMenu"}), VENDING)

    def test_fall_hazard_marker(self):
        self.assertEqual(
            classify({"Character::76", "UnknownClass38::42"}), FALL)

    def test_a_single_shared_call_is_not_enough_to_classify(self):
        """The two false positives the first pass shipped: a bookshelf
        variant also calls `Character::76`, and a fortune-teller's talk
        script also calls `countPurfiedPkm`. Either alone would have
        announced a bookshelf as a hole and an NPC as the Relic Stone."""
        self.assertIsNone(classify({"Character::76"}))
        self.assertIsNone(classify({"Player::countPurfiedPkm"}))

    def test_an_unmatched_handler_classifies_as_nothing(self):
        self.assertIsNone(classify({"Character::talk", "getFlag"}))
        self.assertIsNone(classify(set()))

    def test_healing_wins_over_a_weaker_marker_on_the_same_handler(self):
        self.assertEqual(
            classify({"Character::101", "Player::countPartyPkm",
                      "Player::57"}), HEALING)

    def test_build_table_omits_unclassified_records(self):
        table = build_table([
            (1, {"Player::57"}), (2, {"Character::talk"}),
            (3, {"UnknownClass38::50"}),
        ])
        self.assertEqual(table, {1: BED, 3: TELEVISION})


class RegionGeometryTests(unittest.TestCase):
    def test_the_nearest_point_is_returned_not_the_centroid(self):
        region = square(0, 100.0, 200.0, 0.0, 10.0)
        self.assertEqual(region.nearest_point(0.0, 5.0), (100.0, 5.0))
        self.assertEqual(region.anchor[0], 150.0)

    def test_a_player_inside_the_region_gets_their_own_position(self):
        region = square(0, -10.0, 10.0, -10.0, 10.0)
        self.assertEqual(region.nearest_point(3.0, 4.0), (3.0, 4.0))
        self.assertEqual(region.distance(3.0, 4.0), 0.0)

    def test_the_nearest_point_tracks_the_player(self):
        region = square(0, 0.0, 100.0, 0.0, 10.0)
        left = region.nearest_point(-50.0, 5.0)
        right = region.nearest_point(150.0, 5.0)
        self.assertEqual(left, (0.0, 5.0))
        self.assertEqual(right, (100.0, 5.0))

    def test_a_centroid_far_outside_a_narrow_l_shape_is_not_used(self):
        # Two arms meeting at a corner: the centroid of the vertex cloud
        # sits in the empty quadrant.
        region = Region(
            index=0,
            triangles=(
                (((0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 0.0, 5.0))),
                (((0.0, 0.0, 0.0), (0.0, 0.0, 100.0), (5.0, 0.0, 100.0))),
            ),
            anchor=(35.0, 0.0, 35.0),
        )
        distance = region.distance(35.0, 35.0)
        self.assertGreater(distance, 20.0)

    def test_a_very_large_region_still_answers_from_its_edge(self):
        region = square(0, -500.0, 500.0, -500.0, 500.0)
        self.assertEqual(region.distance(0.0, 0.0), 0.0)
        self.assertAlmostEqual(region.distance(600.0, 0.0), 100.0, places=3)

    def test_a_vertical_face_does_not_contain_the_whole_plane(self):
        """Every vertical face of a trigger volume is degenerate in XZ.
        Treating one as containing the player is how a wall reports
        distance 0 from anywhere in the room."""
        wall = Region(
            index=0,
            triangles=(
                (((0.0, 0.0, 0.0), (6.0, 0.0, 0.0), (0.0, 3.0, 0.0))),
            ),
            anchor=(2.0, 0.0, 0.0),
        )
        self.assertEqual(wall.nearest_point(-50.0, 0.0), (0.0, 0.0))
        self.assertEqual(wall.nearest_point(50.0, 0.0), (6.0, 0.0))
        self.assertAlmostEqual(wall.distance(-50.0, 0.0), 50.0, places=3)

    def test_regions_parse_from_a_synthetic_ccd(self):
        # One entry, slot 0x2C, one triangle carrying interaction index 7.
        entry_base, tri_list, tri = 0x40, 0x100, 0x110
        data = bytearray(0x200)
        struct.pack_into(">I", data, 0, entry_base)
        struct.pack_into(">I", data, 4, 1)
        struct.pack_into(">I", data, entry_base + 0x2C, tri_list)
        struct.pack_into(">I", data, tri_list, tri)
        struct.pack_into(">I", data, tri_list + 4, 1)
        struct.pack_into(">9f", data, tri,
                         0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0)
        struct.pack_into(">H", data, tri + 0x32, 7)
        regions = parse_regions(bytes(data))
        self.assertEqual(list(regions), [7])
        self.assertEqual(len(regions[7].triangles), 1)


class PublicationTests(unittest.TestCase):
    def test_a_classified_press_a_object_uses_its_class_label(self):
        source = make_source([record()], {0: square(0, 5.0, 10.0, 0.0, 5.0)})
        entity = source.entities()[0]
        self.assertEqual(entity.label, LABELS[TELEVISION])
        self.assertEqual(entity.category, "interact")
        self.assertEqual(entity.subtype, TELEVISION)

    def test_an_unclassified_press_a_object_is_generic_not_guessed(self):
        source = make_source(
            [record(handler="check_bookshelf", semantic=None)],
            {0: square(0, 5.0, 10.0, 0.0, 5.0)})
        entity = source.entities()[0]
        self.assertEqual(entity.label, GENERIC_LABEL)
        self.assertIsNone(entity.subtype)

    def test_an_unclassified_walk_in_record_is_suppressed(self):
        # Cutscene and battle triggers are not destinations.
        source = make_source(
            [record(method=1, handler="booth_battle_1", semantic=None)],
            {0: square(0, 5.0, 10.0, 0.0, 5.0)})
        self.assertEqual(source.entities(), [])

    def test_position_is_the_nearest_point_not_the_anchor(self):
        source = make_source(
            [record()], {0: square(0, 100.0, 200.0, -5.0, 5.0)},
            pose=Pose(x=0.0, z=0.0))
        entity = source.entities()[0]
        self.assertAlmostEqual(entity.position.x, 100.0, places=3)
        self.assertAlmostEqual(entity.metadata["anchor"].x, 150.0, places=3)

    def test_the_position_follows_the_player(self):
        region = {0: square(0, 0.0, 100.0, -5.0, 5.0)}
        near = make_source([record()], region, pose=Pose(x=-20.0)).entities()[0]
        far = make_source([record()], region, pose=Pose(x=200.0)).entities()[0]
        self.assertAlmostEqual(near.position.x, 0.0, places=3)
        self.assertAlmostEqual(far.position.x, 100.0, places=3)

    def test_no_interaction_radius_is_invented(self):
        source = make_source([record()], {0: square(0, 0.0, 5.0, 0.0, 5.0)})
        self.assertIsNone(source.entities()[0].interaction_distance)

    def test_a_record_naming_a_missing_region_publishes_nothing(self):
        source = make_source([record(region=9)],
                             {0: square(0, 0.0, 5.0, 0.0, 5.0)})
        self.assertEqual(source.entities(), [])

    def test_another_room_publishes_nothing(self):
        source = make_source([record(room=0x99)],
                             {0: square(0, 0.0, 5.0, 0.0, 5.0)})
        self.assertEqual(source.entities(), [])

    def test_a_room_with_no_geometry_publishes_nothing(self):
        source = make_source([record()], {})
        self.assertEqual(source.entities(), [])


class IdentityTests(unittest.TestCase):
    def test_two_televisions_sharing_a_handler_stay_distinct(self):
        source = make_source(
            [record(index=1, region=0), record(index=2, region=1)],
            {0: square(0, 0.0, 5.0, 0.0, 5.0),
             1: square(1, 50.0, 55.0, 0.0, 5.0)})
        entities = source.entities()
        self.assertEqual(len(entities), 2)
        self.assertEqual(len({e.identity for e in entities}), 2)
        self.assertEqual([e.label for e in entities],
                         [LABELS[TELEVISION], LABELS[TELEVISION]])

    def test_identity_is_the_record_index_not_the_region(self):
        # Three (room, region) pairs are shared with the 0x0596 family, so
        # the region cannot be the key.
        self.assertEqual(record(index=42, region=3).identity, ("interact", 42))

    def test_ordering_is_stable_across_calls(self):
        regions = {0: square(0, 0.0, 5.0, 0.0, 5.0),
                   1: square(1, 50.0, 55.0, 0.0, 5.0)}
        source = make_source(
            [record(index=7, region=1), record(index=2, region=0)], regions)
        first = [e.identity for e in source.entities()]
        second = [e.identity for e in source.entities()]
        self.assertEqual(first, second)
        self.assertEqual(first, [("interact", 2), ("interact", 7)])


class HazardTests(unittest.TestCase):
    """Hazards are warnings, not destinations."""

    def hazard_source(self, **kwargs):
        return make_source(
            [record(method=1, handler="hero_fall", semantic=FALL)],
            {0: square(0, 10.0, 20.0, 0.0, 5.0)},
            category="hazard", **kwargs)

    def test_a_fall_region_publishes_as_a_hazard(self):
        entity = self.hazard_source().entities()[0]
        self.assertEqual(entity.category, "hazard")
        self.assertEqual(entity.label, LABELS[FALL])

    def test_a_hazard_never_beacons(self):
        self.assertFalse(self.hazard_source().entities()[0].metadata["beacon"])

    def test_a_hazard_has_no_interaction_wording(self):
        entity = self.hazard_source().entities()[0]
        self.assertIsNone(entity.interaction_distance)
        self.assertNotIn("verdict", entity.metadata)

    def test_a_hazard_still_reports_direction_and_distance(self):
        entity = self.hazard_source(pose=Pose(x=0.0, z=2.0)).entities()[0]
        self.assertAlmostEqual(entity.position.x, 10.0, places=3)

    def test_hazards_do_not_appear_in_the_interact_category(self):
        source = make_source(
            [record(method=1, handler="hero_fall", semantic=FALL)],
            {0: square(0, 0.0, 5.0, 0.0, 5.0)}, category="interact")
        self.assertEqual(source.entities(), [])

    def test_objects_do_not_appear_in_the_hazard_category(self):
        source = make_source(
            [record()], {0: square(0, 0.0, 5.0, 0.0, 5.0)}, category="hazard")
        self.assertEqual(source.entities(), [])


class AssetTests(unittest.TestCase):
    def test_a_generated_table_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interactables.json"
            path.write_text(json.dumps({
                "5": {"room": 134, "region": 2, "method": 3,
                      "handler": "watch_tv", "class": "television"},
            }), encoding="utf-8")
            records = load_records(path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].semantic, TELEVISION)
        self.assertEqual(records[0].identity, ("interact", 5))

    def test_a_null_class_survives_the_round_trip_as_unclassified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interactables.json"
            path.write_text(json.dumps({
                "5": {"room": 134, "region": 2, "method": 3,
                      "handler": "mystery", "class": None},
            }), encoding="utf-8")
            records = load_records(path)
        self.assertIsNone(records[0].semantic)
        self.assertEqual(records[0].label, GENERIC_LABEL)


class RealTableTests(unittest.TestCase):
    """Against the generated asset and the owner's own extraction."""

    @unittest.skipUnless(HAVE_ASSET, "interactables.json not generated")
    def setUp(self):
        self.records = load_records(ASSET)

    @unittest.skipUnless(HAVE_ASSET, "interactables.json not generated")
    def test_all_241_records_are_present_with_a_handler(self):
        self.assertEqual(len(self.records), 241)
        self.assertTrue(all(r.handler for r in self.records))

    @unittest.skipUnless(HAVE_ASSET, "interactables.json not generated")
    def test_every_method_is_one_of_the_three_known_values(self):
        self.assertEqual({r.method for r in self.records}, {1, 2, 3})

    @unittest.skipUnless(HAVE_ASSET, "interactables.json not generated")
    def test_the_traced_classes_are_present_in_the_expected_shape(self):
        counts = {}
        for r in self.records:
            if r.semantic:
                counts[r.semantic] = counts.get(r.semantic, 0) + 1
        self.assertEqual(counts.get(TELEVISION), 17)
        self.assertEqual(counts.get(HEALING), 10)
        self.assertEqual(counts.get(BED), 5)
        self.assertEqual(counts.get(PLATE), 3)
        self.assertEqual(counts.get(VENDING), 1)
        self.assertEqual(counts.get(FALL), 8)
        self.assertEqual(counts.get(SHRINE), 1)

    @unittest.skipUnless(HAVE_ASSET, "interactables.json not generated")
    def test_tako_machine_is_classified_as_a_healing_machine(self):
        tako = [r for r in self.records if r.handler == "tako_machine"]
        self.assertEqual(len(tako), 6)
        self.assertTrue(all(r.semantic == HEALING for r in tako))

    @unittest.skipUnless(HAVE_ASSET, "interactables.json not generated")
    def test_the_pokespot_plates_are_the_three_esaba_rooms(self):
        plates = [r for r in self.records if r.semantic == PLATE]
        self.assertEqual(sorted(r.room_id for r in plates),
                         [0x5A, 0x5B, 0x5C])
        self.assertTrue(all(r.handler == "esa_set" for r in plates))

    @unittest.skipUnless(HAVE_ASSET, "interactables.json not generated")
    def test_the_relic_stone_is_in_the_shrine_room(self):
        shrines = [r for r in self.records if r.semantic == SHRINE]
        self.assertIn(0x87, [r.room_id for r in shrines])

    @unittest.skipUnless(HAVE_ASSET, "interactables.json not generated")
    def test_every_fall_hazard_is_a_walk_in_trigger(self):
        for r in self.records:
            if r.semantic == FALL:
                self.assertIn(r.method, (1, 2))
                self.assertTrue(r.is_hazard)

    @unittest.skipUnless(HAVE_ASSET, "interactables.json not generated")
    def test_every_classified_object_except_hazards_is_press_a(self):
        for r in self.records:
            if r.semantic and not r.is_hazard:
                self.assertEqual(
                    r.method, 3,
                    f"{r.handler} in room 0x{r.room_id:02X} is method "
                    f"{r.method}")

    @unittest.skipUnless(HAVE_ASSET, "interactables.json not generated")
    def test_unclassified_walk_in_records_are_not_publishable(self):
        for r in self.records:
            if r.method in (1, 2) and not r.is_hazard:
                self.assertFalse(r.publishable)

    @unittest.skipUnless(HAVE_ASSET, "interactables.json not generated")
    def test_no_room_region_pair_carries_two_records(self):
        seen = set()
        for r in self.records:
            key = (r.room_id, r.region_index)
            self.assertNotIn(key, seen)
            seen.add(key)

    @unittest.skipUnless(
        HAVE_ASSET and HAVE_COLLISION, "extraction not present")
    def test_every_publishable_record_resolves_to_real_geometry(self):
        room_codes = {
            int(k, 16): v for k, v in json.loads(
                (COMPANION / "assets" / "room_ids.json").read_text("utf-8")
            ).items()
        }
        missing = []
        for r in self.records:
            if not r.publishable:
                continue
            code = room_codes.get(r.room_id)
            path = COLLISION / f"{code}.ccd" if code else None
            if path is None or not path.exists():
                continue
            regions = parse_regions(path.read_bytes())
            if r.region_index not in regions:
                missing.append((code, r.region_index, r.handler))
        self.assertEqual(missing, [], f"{len(missing)} records name a region "
                                      f"their room's geometry lacks")


if __name__ == "__main__":
    unittest.main()
