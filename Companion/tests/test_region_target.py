"""Region component selection, hysteresis, and the centroid guard.

The invariant under test: **the component entity navigation speaks must be
the component the route is targeting.** Before this, speech took the
Euclidean-nearest point over the whole region while routing took whichever
arrival tile the graph could reach, so a multi-volume region could have the
two naming different places.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.region_geometry import Region
from battle_narrator.region_target import RegionTargetSelector, SWITCH_MARGIN

COLLISION = (Path(__file__).resolve().parents[1]
             / "_dialogue_extraction" / "collision")


def quad(x0, x1, z0, z1, y=0.0):
    """A trigger volume footprint as two triangles sharing an edge."""
    return (
        ((x0, y, z0), (x1, y, z0), (x1, y, z1)),
        ((x0, y, z0), (x1, y, z1), (x0, y, z1)),
    )


def region(*quads, index=1):
    triangles = tuple(t for q in quads for t in q)
    xs = [v[0] for t in triangles for v in t]
    zs = [v[2] for t in triangles for v in t]
    anchor = (sum(xs) / len(xs), 0.0, sum(zs) / len(zs))
    return Region(index=index, triangles=triangles, anchor=anchor)


class RegionComponentTests(unittest.TestCase):
    def test_a_single_volume_is_one_component(self):
        self.assertEqual(len(region(quad(0, 10, 0, 10)).components()), 1)

    def test_two_disjoint_volumes_split(self):
        both = region(quad(0, 10, 0, 10), quad(200, 210, 0, 10))
        self.assertEqual(len(both.components()), 2)

    def test_touching_volumes_stay_one(self):
        """Conservative direction: volumes that share a vertex are mutually
        reachable by definition, so merging them costs nothing."""
        joined = region(quad(0, 10, 0, 10), quad(10, 20, 0, 10))
        self.assertEqual(len(joined.components()), 1)

    def test_the_centroid_of_a_disjoint_region_lies_outside_it(self):
        """A centroid can land far outside the region it names.

        **Two independent causes, measured 2026-08-12 and not to be
        conflated.** Fragmentation: 126 of 843 regions have more than one
        component (124 with two, 2 with four). Concavity: the two worst
        centroid errors in the game -- `D3_out` index 1 at 168.9 units and
        `D1_out` index 2 at 161.9 -- are each a SINGLE connected concave
        strip whose centroid falls in the empty middle, not a pair of
        volumes. Nearest-point targeting fixes both; only fragmentation
        needs component selection.

        This fixture covers the fragmentation case."""
        both = region(quad(0, 10, 0, 10), quad(300, 310, 0, 10))
        centroid_x, _, centroid_z = both.anchor
        self.assertGreater(
            both.distance(centroid_x, centroid_z), 100.0,
            "this fixture no longer demonstrates a centroid outside its "
            "own region")
        for component in both.components():
            self.assertEqual(
                component.distance(*_centre_xz(component)), 0.0,
                "a single component's own centre should be inside it")


def _centre_xz(component):
    xs = [v[0] for t in component.triangles for v in t]
    zs = [v[2] for t in component.triangles for v in t]
    return sum(xs) / len(xs), sum(zs) / len(zs)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.near = quad(0, 10, 0, 10)
        self.far = quad(100, 110, 0, 10)
        self.region = region(self.near, self.far)
        self.selector = RegionTargetSelector()

    def _component_at(self, x):
        for component in self.region.components():
            if any(abs(v[0] - x) < 20 for t in component.triangles for v in t):
                return component
        raise AssertionError("no component there")

    def test_inside_a_component_wins_outright(self):
        component, inside, reachable = self.selector.select(
            self.region, 5.0, 5.0, cost=lambda c: 1000.0)
        self.assertTrue(inside)
        self.assertTrue(reachable)
        self.assertEqual(component.triangles, self._component_at(5).triangles)

    def test_a_reachable_far_component_beats_an_unreachable_near_one(self):
        """Rule 3: never prefer a nearer wall-separated volume."""
        near = self._component_at(5)

        def cost(component):
            return None if component.triangles == near.triangles else 40.0

        component, inside, reachable = self.selector.select(
            self.region, -50.0, 5.0, cost=cost)
        self.assertFalse(inside)
        self.assertTrue(reachable)
        self.assertEqual(
            component.triangles, self._component_at(105).triangles,
            "chose the nearer component even though it is unreachable")

    def test_no_reachable_component_reports_unreachable(self):
        component, _inside, reachable = self.selector.select(
            self.region, -50.0, 5.0, cost=lambda c: None)
        self.assertFalse(
            reachable,
            "claimed a reachable target when the graph reaches none")
        self.assertIsNotNone(
            component, "speech still needs a direction to announce")

    def test_lowest_route_cost_wins_among_reachable(self):
        near = self._component_at(5)
        costs = {near.triangles: 90.0}
        component, _inside, _reachable = self.selector.select(
            self.region, -50.0, 5.0,
            cost=lambda c: costs.get(c.triangles, 10.0))
        self.assertEqual(component.triangles,
                         self._component_at(105).triangles)


class HysteresisTests(unittest.TestCase):
    """Small player movement must not flip the beacon between two edges or
    two volumes. Same class of thrashing the committed waypoint sequence
    exists to prevent for routing."""

    def setUp(self):
        self.region = region(quad(0, 10, 0, 10), quad(100, 110, 0, 10))
        self.selector = RegionTargetSelector()

    def _pick(self, x):
        component, _inside, _reachable = self.selector.select(
            self.region, x, 5.0, cost=lambda c: 10.0)
        return component.triangles

    def test_crossing_the_midpoint_does_not_immediately_flip(self):
        first = self._pick(20.0)          # clearly nearer the left volume
        just_past = self._pick(56.0)      # a hair past the midpoint at 55
        self.assertEqual(
            first, just_past,
            "the target flipped the moment the player crossed the midpoint")

    def test_a_materially_better_component_does_switch(self):
        """Hysteresis must not become stickiness. Walking well past the
        margin has to move the target, or the beacon strands the player on
        a volume they have left behind."""
        first = self._pick(20.0)
        moved = self._pick(120.0)
        self.assertNotEqual(
            first, moved,
            f"the target never switched despite the player walking 100 "
            f"units past it (margin is {SWITCH_MARGIN})")

    def test_the_switch_is_stable_once_made(self):
        self._pick(20.0)
        moved = self._pick(120.0)
        self.assertEqual(moved, self._pick(118.0))
        self.assertEqual(moved, self._pick(122.0))

    def test_movement_parallel_to_one_volume_never_switches(self):
        chosen = self._pick(5.0)
        for z in (1.0, 3.0, 6.0, 9.0):
            component, _inside, _r = self.selector.select(
                self.region, 5.0, z, cost=lambda c: 10.0)
            self.assertEqual(component.triangles, chosen)

    def test_hysteresis_never_keeps_an_unreachable_target(self):
        left = self.region.components()[0]
        self._pick(20.0)

        def cost(component):
            return None if component.triangles == left.triangles else 10.0

        component, _inside, reachable = self.selector.select(
            self.region, 20.0, 5.0, cost=cost)
        self.assertTrue(reachable)
        self.assertNotEqual(
            component.triangles, left.triangles,
            "kept a target that became unreachable")


class CentroidGuardTests(unittest.TestCase):
    """Focused guard against player-facing centroid targeting coming back.

    The centroid is legitimate for ordering and diagnostics. It must not be
    the announced position, the route destination, or the arrival test for
    a region-backed entity."""

    def test_the_announced_point_is_not_the_anchor_for_a_disjoint_region(self):
        from battle_narrator.authoritative_warps import _region_position
        from battle_narrator.npc_beacons import PlayerPose, Position

        both = region(quad(0, 10, 0, 10), quad(300, 310, 0, 10), index=2)
        pose = PlayerPose(Position(5.0, 0.0, 5.0), 0.0)
        position = _region_position({2: both}, 2, pose,
                                    RegionTargetSelector())
        self.assertIsNotNone(position)
        self.assertNotAlmostEqual(
            position.x, both.anchor[0], places=1,
            msg="the announced position is the centroid again -- for this "
                "region that is 150 units of empty space")

    def test_region_geometry_is_what_routing_receives(self):
        """`destination_target_tiles` must derive arrival tiles from
        triangles. A centroid tuple would silently fall through to the
        point path."""
        from battle_narrator import pathfinding as pf
        from battle_narrator.npc_beacons import Position

        geometry = pf.build_room_geometry((), ())
        wide = region(quad(0, 64, 0, 64))
        tiles = pf.destination_target_tiles(
            geometry, Position(32.0, 0.0, 32.0), wide)
        point_tiles = pf.destination_target_tiles(
            geometry, Position(32.0, 0.0, 32.0), None)
        self.assertGreater(
            len(tiles), len(point_tiles),
            "a large region produced no more arrival tiles than a bare "
            "point -- its geometry is being ignored")


if __name__ == "__main__":
    unittest.main()


class ClifftopArrivalTests(unittest.TestCase):
    """Live failure 2026-08-13, `M3_out`. Arrival was matched on tile alone,
    so a node on the clifftop counted as arriving at a trigger volume at the
    bottom of the cliff.

    The guide built a confident route, walked the player 341 units across
    Agate Village, reported `route_success` at 3.68 units residual, and left
    them 83 units ABOVE the Relic Stone cave entrance. Region 6 of that room
    spans y -10.00..36.67; the player finished at y=120."""

    def test_a_node_above_the_trigger_volume_is_not_arrival(self):
        from battle_narrator import pathfinding as pf
        low, high = pf.destination_height_band(None, region(quad(0, 10, 0, 10)))
        self.assertLessEqual(low, 0.0)
        self.assertGreaterEqual(high, 0.0)
        self.assertFalse(
            low <= 120.0 <= high,
            "a node 120 units above the trigger counts as arriving at it")

    def test_the_real_agate_region_rejects_the_clifftop(self):
        ccd = COLLISION / "M3_out.ccd"
        if not ccd.is_file():
            self.skipTest(f"missing fixture {ccd}")
        from battle_narrator import pathfinding as pf
        from battle_narrator.region_geometry import parse_regions
        regions = parse_regions(ccd.read_bytes())
        cave = regions[6]
        band = pf.destination_height_band(None, cave)
        self.assertIsNotNone(band)
        self.assertFalse(
            band[0] <= 120.0 <= band[1],
            f"the clifftop (y=120) is inside this region's arrival band "
            f"{band} -- the live false route would build again")
        ys = [v[1] for t in cave.triangles for v in t]
        self.assertTrue(band[0] <= min(ys) and max(ys) <= band[1],
                        "the region's own extent must be inside its band")

    def test_a_point_destination_has_no_band(self):
        from battle_narrator import pathfinding as pf
        self.assertIsNone(pf.destination_height_band(None, None))
