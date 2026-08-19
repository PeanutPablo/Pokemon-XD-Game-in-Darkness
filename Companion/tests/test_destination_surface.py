"""Which walk surface does an interaction region belong to? (2026-08-13)

A region-backed destination is a trigger VOLUME, and the point routing is
handed is the nearest point on that volume -- which slides along the volume as
the player walks. Where the volume overhangs its own floor, that point can
land at an XZ with no walkable surface beneath it at all, and `resolve_node`
then falls back to its own 2-ring search and returns whatever column is
nearest laterally, at any height. `resolve_destination_node` used to accept
that as "direct, offset 0.0" with no vertical test.

Live, `M3_out` region 6 -- the Relic Stone cave trigger, a 2-triangle vertical
curtain at z=-23.86 spanning x -39.58..5.18, y -10.00..36.67, standing on the
cave floor at y=-5.04, whose floor only exists beneath roughly x -32..-1. With
the player west of that, the destination resolved to the CLIFFTOP at y=120.00
two tiles away -- 130 units above the trigger -- and the route targeted a
1637-node component ("8 units away") instead of the 1861-node cave ("686 units
away"), flipping with the player's x.

**The authoritative discriminator is the region's own vertical extent.**
`Region.anchor[1]` is the minimum Y of the region's own triangles, and the
lateral ring search already refuses any surface more than
`DESTINATION_PROJECTION_MAX_VERTICAL_GAP` from it. Measured over every
`M3_out` region, the walk surface a trigger stands on sits 1.4-5.0 units above
that minimum; the clifftop is 130 away. Nothing here consults the player.
"""
import unittest
from pathlib import Path

from battle_narrator.collision_probe import (
    WalkTriangle, parse_environment_triangles, parse_walk_model_triangles)
from battle_narrator.npc_beacons import Position
from battle_narrator.pathfinding import (
    DESTINATION_PROJECTION_MAX_VERTICAL_GAP,
    build_room_geometry,
    resolve_destination_node,
    walk_height_candidates,
)
from battle_narrator.region_geometry import parse_regions

COLLISION = (Path(__file__).resolve().parents[1]
             / "_dialogue_extraction" / "collision")


def walk_quad(x0, x1, z0, z1, y, layer, entry_index=0):
    """One flat surface, as a grid of 8-unit tiles so tile-centre sampling
    finds it wherever it is probed."""
    out = []
    step = 8.0
    x = x0
    while x < x1 - 1e-9:
        z = z0
        while z < z1 - 1e-9:
            nx, nz = min(x + step, x1), min(z + step, z1)
            out.append(WalkTriangle(
                ((x, y, z), (nx, y, z), (nx, y, nz)),
                (0.0, 1.0, 0.0), layer, layer, 0xFF, entry_index))
            out.append(WalkTriangle(
                ((x, y, z), (nx, y, nz), (x, y, nz)),
                (0.0, 1.0, 0.0), layer, layer, 0xFF, entry_index))
            z = nz
        x = nx
    return out


class Disable33:
    def is_enabled(self, floor_id, entry_index):
        return entry_index != 33


class RelicCaveDestinationSurfaceTests(unittest.TestCase):
    """The live case, from the real room."""

    CAVE_FLOOR_Y = -5.04
    CLIFFTOP_Y = 120.0

    @classmethod
    def setUpClass(cls):
        ccd = COLLISION / "M3_out.ccd"
        if not ccd.is_file():
            raise unittest.SkipTest(f"missing fixture {ccd}")
        data = ccd.read_bytes()
        cls.geometry = build_room_geometry(
            parse_walk_model_triangles(data),
            parse_environment_triangles(data),
            enable_state=Disable33())
        cls.region = parse_regions(data)[6]

    def _target_for(self, player_x):
        """What the guide hands routing when the player is at this x: the
        nearest point of the trigger, at the region's own floor Y."""
        point = self.region.nearest_point(player_x, -40.0)
        return Position(point[0], self.region.anchor[1], point[1])

    def test_the_trigger_overhangs_its_own_floor(self):
        """Fixture guard. If floor existed everywhere under the trigger the
        fallback path would never run and these tests would be vacuous."""
        covered = []
        for player_x in (-38.04, -28.43):
            target = self._target_for(player_x)
            covered.append(bool(
                walk_height_candidates(self.geometry, target.x, target.z)))
        self.assertEqual(
            covered, [False, True],
            "expected no walk surface under the trigger at x=-38.04 and a "
            "surface at x=-28.43")

    def test_the_same_region_resolves_to_one_surface_across_the_clifftop(self):
        """The player walks laterally along the clifftop; the destination
        surface must not move with them."""
        heights = set()
        layers = set()
        for player_x in range(-70, 20, 2):
            node = resolve_destination_node(
                self.geometry, self._target_for(float(player_x)))
            self.assertIsNotNone(node, f"no seed at player x={player_x}")
            _tile, node_layers, height, _offset = node
            heights.add(round(height, 2))
            layers.add(tuple(sorted(node_layers)))
        self.assertEqual(
            heights, {round(self.CAVE_FLOOR_Y, 2)},
            f"the destination surface moved with the player: {sorted(heights)}")
        self.assertEqual(layers, {(0,)})

    def test_the_two_live_positions_agree(self):
        """The exact pair from the log: x=-28 resolved to the cave, x=-38 to
        the clifftop."""
        for player_x in (-27.97, -28.43, -38.04):
            with self.subTest(player_x=player_x):
                _tile, _layers, height, _offset = resolve_destination_node(
                    self.geometry, self._target_for(player_x))
                self.assertAlmostEqual(height, self.CAVE_FLOOR_Y, places=1)

    def test_the_clifftop_is_never_selected(self):
        for player_x in range(-70, 20, 2):
            node = resolve_destination_node(
                self.geometry, self._target_for(float(player_x)))
            self.assertLess(
                node[2], self.CLIFFTOP_Y - 50.0,
                f"clifftop selected at player x={player_x}")


class StackedSurfaceTests(unittest.TestCase):
    """Two walkable surfaces at the same XZ. Which one a region belongs to is
    decided by the region's own floor Y, never by proximity to anything the
    player is doing."""

    LOWER_Y = 0.0
    UPPER_Y = 100.0

    def _geometry(self):
        return build_room_geometry(
            tuple(walk_quad(-40.0, 40.0, -40.0, 40.0, self.LOWER_Y, 0)
                  + walk_quad(-40.0, 40.0, -40.0, 40.0, self.UPPER_Y, 3)),
            ())

    def test_a_region_on_the_lower_surface_resolves_down(self):
        node = resolve_destination_node(
            self._geometry(), Position(0.0, self.LOWER_Y - 4.0, 0.0))
        self.assertAlmostEqual(node[2], self.LOWER_Y, places=2)
        self.assertEqual(tuple(sorted(node[1])), (0,))

    def test_a_region_on_the_upper_surface_resolves_up(self):
        node = resolve_destination_node(
            self._geometry(), Position(0.0, self.UPPER_Y - 4.0, 0.0))
        self.assertAlmostEqual(node[2], self.UPPER_Y, places=2)
        self.assertEqual(tuple(sorted(node[1])), (3,))

    def _overhang_geometry(self):
        """`M3_out`'s real shape, synthesised: the destination point lands
        past the edge of its own floor, in a column with NO surface at all,
        while a surface at a very different height sits nearby laterally.

        That is the configuration the game actually contains. A column that
        holds ONLY a wrong-height surface is deliberately *not* tested,
        because it does not occur: measured over all 843 interaction regions,
        the surface beneath a region's anchor lies inside that region's own
        band in 835 cases, is absent in 6, and is outside in 2 -- and in those
        2 no better candidate exists at that XZ either. A rule strict enough
        to override a wrong-height surface standing directly under a
        destination would refuse those 2 and gain nothing."""
        return build_room_geometry(
            tuple(walk_quad(-40.0, 0.0, -40.0, 40.0, self.LOWER_Y, 0)
                  + walk_quad(24.0, 60.0, -40.0, 40.0, self.UPPER_Y, 3)),
            ())

    def test_a_region_overhanging_its_floor_resolves_to_that_floor(self):
        node = resolve_destination_node(
            self._overhang_geometry(), Position(16.0, self.LOWER_Y - 4.0, 0.0))
        self.assertIsNotNone(node)
        self.assertAlmostEqual(
            node[2], self.LOWER_Y, places=2,
            msg="a region overhanging its own floor was projected onto the "
                "surface at a different height nearby")
        self.assertGreater(node[3], 0.0, "expected a non-zero seed offset")

    def test_the_mirror_case_resolves_up(self):
        """So the rule is not just 'prefer lower'."""
        node = resolve_destination_node(
            self._overhang_geometry(), Position(16.0, self.UPPER_Y - 4.0, 0.0))
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node[2], self.UPPER_Y, places=2)

    def test_the_overhang_column_really_is_empty(self):
        """Fixture guard for both cases above."""
        self.assertEqual(
            walk_height_candidates(self._overhang_geometry(), 16.0, 0.0), [])


class OrdinaryAndCrossLevelTests(unittest.TestCase):
    def test_a_single_surface_region_is_unaffected(self):
        geometry = build_room_geometry(
            tuple(walk_quad(-40.0, 40.0, -40.0, 40.0, 0.0, 0)), ())
        node = resolve_destination_node(geometry, Position(4.0, -3.0, 4.0))
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node[2], 0.0, places=2)
        self.assertEqual(node[3], 0.0, "an in-place seed gained an offset")

    def test_a_destination_above_its_own_ground_still_seeds_in_place(self):
        """`M3_out`'s worldmap exit sits well above the terrace it belongs
        to. That case must keep its zero-offset direct seed."""
        geometry = build_room_geometry(
            tuple(walk_quad(-40.0, 40.0, -40.0, 40.0, 0.0, 0)), ())
        gap = DESTINATION_PROJECTION_MAX_VERTICAL_GAP - 1.0
        node = resolve_destination_node(geometry, Position(4.0, gap, 4.0))
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node[2], 0.0, places=2)
        self.assertEqual(node[3], 0.0)

    def test_a_stairwell_destination_a_storey_down_is_refused(self):
        """`D1_garage_1F`'s basement warps sit ~48 units below the only
        floor. Projecting them onto it seeded a route in a component the
        player cannot reach; refusing hands the case to the reachability
        path instead. This must stay refused."""
        ccd = COLLISION / "D1_garage_1F.ccd"
        if not ccd.is_file():
            raise unittest.SkipTest(f"missing fixture {ccd}")
        data = ccd.read_bytes()
        geometry = build_room_geometry(
            parse_walk_model_triangles(data),
            parse_environment_triangles(data))
        regions = parse_regions(data)
        basement = [
            region for region in regions.values()
            if region.anchor[1] < -30.0]
        self.assertTrue(basement, "expected a below-floor region here")
        for region in basement:
            with self.subTest(index=region.index):
                self.assertIsNone(
                    resolve_destination_node(
                        geometry,
                        Position(region.anchor[0], region.anchor[1],
                                 region.anchor[2])),
                    "a cross-level destination was projected onto this floor")


if __name__ == "__main__":
    unittest.main()
