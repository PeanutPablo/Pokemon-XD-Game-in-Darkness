import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.authoritative_warps import (
    AuthoritativeDoorEntitySource,
    AuthoritativeElevatorEntitySource,
    AuthoritativePCEntitySource,
    AuthoritativeTextEntitySource,
    parse_door_records,
    parse_elevator_records,
    parse_interactable_region_centers,
    parse_pc_records,
    parse_text_records,
    parse_warp_records,
)
from battle_narrator.npc_beacons import PlayerPose, Position


def interaction(method=1, room=0x8D, region=9, marker=0x596, script=4,
                target=0x8B, entry=1):
    value = bytearray(0x1C)
    value[0] = method
    struct.pack_into(">H", value, 2, room)
    value[7] = region
    struct.pack_into(">HH", value, 8, marker, script)
    struct.pack_into(">H", value, 0x0E, target)
    value[0x13] = entry
    return bytes(value)


def elevator_interaction(method=1, room=0x8A, region=7, marker=0x596,
                          script=6, elevator_id=144, target_room=0x8B,
                          target_elevator=145, direction=0):
    value = bytearray(0x1C)
    value[0] = method
    struct.pack_into(">H", value, 2, room)
    value[7] = region
    struct.pack_into(">HH", value, 8, marker, script)
    struct.pack_into(">H", value, 0x0E, elevator_id)
    struct.pack_into(">H", value, 0x12, target_room)
    struct.pack_into(">H", value, 0x16, target_elevator)
    value[0x1B] = direction
    return bytes(value)


class FakeMemory:
    def __init__(self, floor_id):
        self.floor_id = floor_id

    def u16(self, address, label=""):
        return self.floor_id


class FakePoseSource:
    def player_pose(self):
        return PlayerPose(Position(0, 0, 0), 0)


class FakeProfile:
    current_floor_id = 0x1234


def ccd_with_triangle(region=9, slot=0x2C):
    data = bytearray(0x200)
    struct.pack_into(">II", data, 0, 0x20, 1)
    struct.pack_into(">I", data, 0x20 + slot, 0x80)
    struct.pack_into(">II", data, 0x80, 0xA0, 1)
    struct.pack_into(">9f", data, 0xA0, 0, 0, 0, 6, 0, 0, 0, 3, 0)
    index_offset = 0x32 if slot == 0x2C else 0x30
    struct.pack_into(">H", data, 0xA0 + index_offset, region)
    return bytes(data)


class WarpRecordTests(unittest.TestCase):
    def test_accepts_only_warp_and_cutscene_warp(self):
        data = b"".join((
            interaction(script=4),
            interaction(script=0x0D, region=10),
            interaction(script=5),
            interaction(marker=0x100, script=4),
        ))
        records = parse_warp_records(data, 0, 4)
        self.assertEqual([record.kind for record in records],
                         ["warp", "cutscene_warp"])
        self.assertEqual(records[0].room_id, 0x8D)
        self.assertEqual(records[0].region_index, 9)
        self.assertEqual(records[0].target_room_id, 0x8B)
        self.assertEqual(records[0].target_entry_id, 1)

    def test_rejects_unbounded_count_and_truncated_table(self):
        with self.assertRaises(ValueError):
            parse_warp_records(b"", 0, 4097)
        with self.assertRaises(ValueError):
            parse_warp_records(b"\0" * 0x1B, 0, 1)


class DoorRecordTests(unittest.TestCase):
    def test_accepts_only_door_records(self):
        data = b"".join((
            interaction(script=5, target=201),
            interaction(script=4, region=10),
            interaction(marker=0x100, script=5),
        ))
        records = parse_door_records(data, 0, 3)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].room_id, 0x8D)
        self.assertEqual(records[0].region_index, 9)
        self.assertEqual(records[0].door_id, 201)

    def test_rejects_unbounded_count_and_truncated_table(self):
        with self.assertRaises(ValueError):
            parse_door_records(b"", 0, 4097)
        with self.assertRaises(ValueError):
            parse_door_records(b"\0" * 0x1B, 0, 1)


class ElevatorRecordTests(unittest.TestCase):
    def test_accepts_only_elevator_records(self):
        data = b"".join((
            elevator_interaction(),
            interaction(script=4),
            elevator_interaction(marker=0x100),
        ))
        records = parse_elevator_records(data, 0, 3)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].room_id, 0x8A)
        self.assertEqual(records[0].region_index, 7)
        self.assertEqual(records[0].elevator_id, 144)
        self.assertEqual(records[0].target_room_id, 0x8B)
        self.assertEqual(records[0].target_elevator_id, 145)
        self.assertEqual(records[0].direction, 0)

    def test_rejects_unbounded_count_and_truncated_table(self):
        with self.assertRaises(ValueError):
            parse_elevator_records(b"", 0, 4097)
        with self.assertRaises(ValueError):
            parse_elevator_records(b"\0" * 0x1B, 0, 1)


class AuthoritativeElevatorEntitySourceTests(unittest.TestCase):
    def test_resolves_position_and_scopes_to_current_room(self):
        records = parse_elevator_records(elevator_interaction(), 0, 1)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "M5_apart_1F.ccd").write_bytes(
                ccd_with_triangle(region=7))
            source = AuthoritativeElevatorEntitySource(
                FakeMemory(0x8A), FakeProfile(), FakePoseSource(), records,
                directory, {0x8A: "M5_apart_1F", 0x8B: "M5_apart_2F"},
                {0x8B: "Pokémon HQ Lab"},
            )
            entities = source.entities()
            self.assertEqual(len(entities), 1)
            entity = entities[0]
            self.assertEqual(entity.category, "elevator")
            # Phase 3b: the NEAREST point of the region to the player,
            # not its centroid (which was 2.0). The fixture triangle
            # spans x 0..6 at z=0 and the player stands at the origin.
            self.assertEqual(entity.position, Position(0.0, 0.0, 0.0))
            self.assertEqual(entity.label, "Elevator to Pokémon HQ Lab")
            self.assertEqual(entity.metadata["elevator_id"], 144)
            self.assertEqual(entity.metadata["target_elevator_id"], 145)
            self.assertEqual(entity.metadata["direction"], "up")

    def test_other_room_returns_nothing(self):
        records = parse_elevator_records(elevator_interaction(), 0, 1)
        with tempfile.TemporaryDirectory() as directory:
            source = AuthoritativeElevatorEntitySource(
                FakeMemory(0x99), FakeProfile(), FakePoseSource(), records,
                directory, {0x8A: "M5_apart_1F"},
            )
            self.assertEqual(source.entities(), [])


class NearestPointTests(unittest.TestCase):
    """Phase 3b. The audit measured 210 of 843 regions whose centroid lies
    OUTSIDE the region, worst case 168.9 units of empty space, and the
    project owner reported Agate's cave entrances as unreachable."""

    class Pose:
        def __init__(self, x):
            self.x = x

        def player_pose(self):
            return PlayerPose(Position(self.x, 0, 0), 0)

    def _position(self, player_x):
        records = parse_door_records(
            interaction(script=5, room=0x8F, target=201), 0, 1)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "room.ccd").write_bytes(
                ccd_with_triangle(region=9))
            source = AuthoritativeDoorEntitySource(
                FakeMemory(0x8F), FakeProfile(), self.Pose(player_x), records,
                directory, {0x8F: "room"},
            )
            return source.entities()[0].position

    def test_the_announced_point_tracks_the_player(self):
        # The region spans x 0..6. From the left the near edge is 0; from
        # far right it is 6. A centroid would answer 2.0 to both.
        self.assertEqual(self._position(-50.0).x, 0.0)
        self.assertEqual(self._position(50.0).x, 6.0)

    def test_a_player_inside_the_region_is_already_there(self):
        self.assertEqual(self._position(3.0).x, 3.0)


class AuthoritativeDoorEntitySourceTests(unittest.TestCase):
    def test_resolves_position_and_scopes_to_current_room(self):
        records = parse_door_records(
            interaction(script=5, room=0x8F, target=201), 0, 1)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "room.ccd").write_bytes(
                ccd_with_triangle(region=9))
            source = AuthoritativeDoorEntitySource(
                FakeMemory(0x8F), FakeProfile(), FakePoseSource(), records,
                directory, {0x8F: "room"},
            )
            entities = source.entities()
            self.assertEqual(len(entities), 1)
            entity = entities[0]
            self.assertEqual(entity.category, "door")
            # Phase 3b: the NEAREST point of the region to the player,
            # not its centroid (which was 2.0). The fixture triangle
            # spans x 0..6 at z=0 and the player stands at the origin.
            self.assertEqual(entity.position, Position(0.0, 0.0, 0.0))
            self.assertEqual(entity.label, "Door")
            self.assertEqual(entity.metadata["door_id"], 201)

    def _door_in_room(self, warp_records):
        """One door at room 0x8F region 9, with whatever warp table the
        caller wants compared against it."""
        records = parse_door_records(
            interaction(script=5, room=0x8F, target=201), 0, 1)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "room.ccd").write_bytes(
                ccd_with_triangle(region=9))
            source = AuthoritativeDoorEntitySource(
                FakeMemory(0x8F), FakeProfile(), FakePoseSource(), records,
                directory, {0x8F: "room"}, warp_records=warp_records,
            )
            return source.entities()[0]

    def test_a_door_sharing_a_warps_region_is_published_silent(self):
        """The project owner's 2026-08-10 request. Such a door IS the warp
        -- same trigger region -- so beaconing both played two sounds from
        one point. The entity survives; only its sound goes."""
        warps = parse_warp_records(interaction(script=4, room=0x8F), 0, 1)
        entity = self._door_in_room(warps)
        self.assertIs(entity.metadata["warp_attached"], True)
        self.assertIs(entity.metadata["beacon"], False)

    def test_a_door_of_its_own_still_beacons(self):
        # Same room as a warp, but a DIFFERENT region: an interior door,
        # not an entrance. Untouched.
        warps = parse_warp_records(
            interaction(script=4, room=0x8F, region=10), 0, 1)
        entity = self._door_in_room(warps)
        self.assertIs(entity.metadata["warp_attached"], False)
        self.assertNotIn("beacon", entity.metadata)

    def test_a_warp_in_the_same_region_of_another_room_does_not_match(self):
        # Region indices are per-room, so comparing on region alone would
        # silence doors all over the game.
        warps = parse_warp_records(interaction(script=4, room=0x90), 0, 1)
        self.assertIs(self._door_in_room(warps).metadata["warp_attached"],
                      False)

    def test_no_warp_table_leaves_every_door_beaconing(self):
        self.assertNotIn("beacon", self._door_in_room(()).metadata)


class PCRecordTests(unittest.TestCase):
    def test_accepts_only_pc_records(self):
        data = b"".join((
            interaction(script=0x0E, target=301),
            interaction(script=4, region=10),
            interaction(marker=0x100, script=0x0E),
        ))
        records = parse_pc_records(data, 0, 3)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].room_id, 0x8D)
        self.assertEqual(records[0].region_index, 9)
        self.assertEqual(records[0].secondary_field, 301)

    def test_rejects_unbounded_count_and_truncated_table(self):
        with self.assertRaises(ValueError):
            parse_pc_records(b"", 0, 4097)
        with self.assertRaises(ValueError):
            parse_pc_records(b"\0" * 0x1B, 0, 1)


class AuthoritativePCEntitySourceTests(unittest.TestCase):
    def test_resolves_position_and_scopes_to_current_room(self):
        records = parse_pc_records(
            interaction(script=0x0E, room=0x8F, target=301), 0, 1)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "room.ccd").write_bytes(
                ccd_with_triangle(region=9))
            source = AuthoritativePCEntitySource(
                FakeMemory(0x8F), FakeProfile(), FakePoseSource(), records,
                directory, {0x8F: "room"},
            )
            entities = source.entities()
            self.assertEqual(len(entities), 1)
            entity = entities[0]
            self.assertEqual(entity.category, "pc")
            # Phase 3b: the NEAREST point of the region to the player,
            # not its centroid (which was 2.0). The fixture triangle
            # spans x 0..6 at z=0 and the player stands at the origin.
            self.assertEqual(entity.position, Position(0.0, 0.0, 0.0))
            self.assertEqual(entity.label, "PC")
            self.assertEqual(entity.metadata["secondary_field"], 301)


class TextRecordTests(unittest.TestCase):
    def test_accepts_only_text_records(self):
        data = b"".join((
            interaction(script=0x0C, target=401),
            interaction(script=4, region=10),
            interaction(marker=0x100, script=0x0C),
        ))
        records = parse_text_records(data, 0, 3)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].room_id, 0x8D)
        self.assertEqual(records[0].region_index, 9)
        self.assertEqual(records[0].message_field, 401)

    def test_rejects_unbounded_count_and_truncated_table(self):
        with self.assertRaises(ValueError):
            parse_text_records(b"", 0, 4097)
        with self.assertRaises(ValueError):
            parse_text_records(b"\0" * 0x1B, 0, 1)


class AuthoritativeTextEntitySourceTests(unittest.TestCase):
    def test_resolves_position_and_scopes_to_current_room(self):
        records = parse_text_records(
            interaction(script=0x0C, room=0x8F, target=401), 0, 1)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "room.ccd").write_bytes(
                ccd_with_triangle(region=9))
            source = AuthoritativeTextEntitySource(
                FakeMemory(0x8F), FakeProfile(), FakePoseSource(), records,
                directory, {0x8F: "room"},
            )
            entities = source.entities()
            self.assertEqual(len(entities), 1)
            entity = entities[0]
            self.assertEqual(entity.category, "sign")
            # Phase 3b: the NEAREST point of the region to the player,
            # not its centroid (which was 2.0). The fixture triangle
            # spans x 0..6 at z=0 and the player stands at the origin.
            self.assertEqual(entity.position, Position(0.0, 0.0, 0.0))
            self.assertEqual(entity.label, "Sign")
            self.assertEqual(entity.metadata["message_field"], 401)


class CollisionRegionTests(unittest.TestCase):
    def test_centroid_and_interaction_index_from_both_slots(self):
        # X and Z are the centroid; Y is the region's FLOOR, not its
        # centroid -- these are tall trigger volumes standing on the
        # walkable surface, and the player's own Y is their feet. Using the
        # centroid put every warp, door, elevator, PC and sign ~16 units
        # "above" the player and made entity-nav announce it on 200 of 422
        # utterances in one live log.
        for slot in (0x2C, 0x30):
            centers = parse_interactable_region_centers(
                ccd_with_triangle(slot=slot))
            self.assertEqual(centers[9], (2.0, 0.0, 0.0))

    def test_rejects_invalid_top_level_table(self):
        data = bytearray(8)
        struct.pack_into(">II", data, 0, 0x100, 1)
        with self.assertRaises(ValueError):
            parse_interactable_region_centers(bytes(data))


if __name__ == "__main__":
    unittest.main()
