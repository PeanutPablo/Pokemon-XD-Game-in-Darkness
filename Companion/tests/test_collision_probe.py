import math
import struct
import unittest

from battle_narrator.collision_probe import (
    CollisionTriangle,
    parse_environment_triangles,
    predict_forward_collision,
)
from battle_narrator.npc_beacons import PlayerPose, Position


def triangle(vertices, normal=(0.0, 0.0, 1.0), collision_type=3):
    return CollisionTriangle(
        tuple(vertices), normal, collision_type, entry_index=0)


class CollisionPredictionTests(unittest.TestCase):
    def test_forward_ray_hits_controlled_wall(self):
        wall = triangle((
            (-5.0, 0.0, -5.0),
            (5.0, 0.0, -5.0),
            (5.0, 30.0, -5.0),
        ))
        pose = PlayerPose(Position(0.0, 15.0, 0.0), 0.0)
        hit = predict_forward_collision((wall,), pose, 12.0)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.distance, 5.0)
        self.assertEqual(hit.point, (0.0, 15.0, -5.0))

    def test_opposite_direction_is_clear(self):
        wall = triangle((
            (-5.0, 0.0, -5.0),
            (5.0, 0.0, -5.0),
            (5.0, 30.0, -5.0),
        ))
        pose = PlayerPose(Position(0.0, 15.0, 0.0), math.pi)
        self.assertIsNone(predict_forward_collision((wall,), pose, 12.0))

    def test_floor_triangle_is_not_a_wall(self):
        floor = triangle((
            (-5.0, 15.0, 0.0),
            (5.0, 15.0, 0.0),
            (0.0, 15.0, -10.0),
        ), normal=(0.0, 1.0, 0.0))
        pose = PlayerPose(Position(0.0, 15.0, 0.0), 0.0)
        self.assertIsNone(predict_forward_collision((floor,), pose, 12.0))

    def test_parser_reads_only_environment_slot(self):
        data = bytearray(0x140)
        struct.pack_into(">II", data, 0, 0x10, 1)
        struct.pack_into(">I", data, 0x10 + 0x28, 0x60)
        struct.pack_into(">II", data, 0x60, 0x80, 1)
        values = (
            -5.0, 0.0, -5.0,
            5.0, 0.0, -5.0,
            5.0, 30.0, -5.0,
            0.0, 0.0, 1.0,
        )
        struct.pack_into(">12f", data, 0x80, *values)
        struct.pack_into(">HH", data, 0x80 + 0x30, 3, 99)
        parsed = parse_environment_triangles(bytes(data))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].collision_type, 3)
        self.assertEqual(parsed[0].vertices[2], (5.0, 30.0, -5.0))


if __name__ == "__main__":
    unittest.main()