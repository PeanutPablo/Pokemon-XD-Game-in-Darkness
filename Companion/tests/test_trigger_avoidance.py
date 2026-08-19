"""Routes must not walk the player through a warp they did not ask for.

Live failure, 2026-08-17, `M6_out` (Gateon Port): the project owner
autowalked to the world-map exit and arrived in the parts shop. The route
was geometrically sound -- its second leg ran (92, 196) -> (89, 223) -- but
warp region 7, `common.rel` record 727 targeting room 0x97, is a trigger
curtain 25 units wide at z=214.0, and that leg crossed it 0.69 units from
its centre. Nothing in the router had any concept of warp triggers.

The exact live route cannot be replayed offline: it was built against the
engine's live collision-object enable state, and Gateon Port is precisely
the room whose piers toggle. What CAN be replayed is the defect, from the
same real data -- and it reproduces on a second destination in the same
room (region 11), which is what these tests pin.
"""
import json
import logging
import math
import unittest
from pathlib import Path

from battle_narrator.navigation_service import NavigationService
from battle_narrator.npc_beacons import Position
from battle_narrator.pathfinding import (
    TRIGGER_CROSSING_MARGIN, _crosses_blocked_segment, region_crossing_segments,
)
from battle_narrator.region_geometry import parse_regions

COMPANION = Path(__file__).resolve().parents[1]
COLLISION = COMPANION / "_dialogue_extraction" / "collision"
ROOM_IDS = COMPANION / "assets" / "room_ids.json"
GATEON = 0x99

LOGGER = logging.getLogger("trigger-avoidance-test")
LOGGER.addHandler(logging.NullHandler())

# `common.rel` region indices for M6_out's ten exits, pinned here rather
# than re-parsed: these tests are about routing, and reading them from the
# warp table would make a routing test fail for a data-loading reason.
GATEON_EXIT_REGIONS = frozenset({4, 5, 6, 7, 8, 9, 10, 11, 12, 13})
PARTS_SHOP_REGION = 7
"""Warp record 727, target room 0x97 -- the door the live failure went
through."""


class CrossingTests(unittest.TestCase):
    """The primitive, on synthetic segments."""

    CURTAIN = ((0.0, 0.0), (10.0, 0.0))

    def test_a_leg_straight_through_is_refused(self):
        self.assertTrue(_crosses_blocked_segment(
            (5.0, -10.0), (5.0, 10.0), (self.CURTAIN,)))

    def test_a_leg_alongside_is_allowed(self):
        """The point of measuring crossings rather than blocking tiles: a
        route may walk right past a shop door."""
        self.assertFalse(_crosses_blocked_segment(
            (5.0, -10.0), (5.0, -2.0), (self.CURTAIN,)))

    def test_a_leg_around_the_end_is_allowed(self):
        self.assertFalse(_crosses_blocked_segment(
            (15.0, -10.0), (15.0, 10.0), (self.CURTAIN,)))

    def test_a_grazing_leg_is_refused(self):
        """Float geometry must not decide whether a trigger fires."""
        self.assertTrue(_crosses_blocked_segment(
            (5.0, -10.0), (5.0, -TRIGGER_CROSSING_MARGIN / 2), (self.CURTAIN,)))

    def test_no_segments_never_refuses(self):
        self.assertFalse(_crosses_blocked_segment(
            (5.0, -10.0), (5.0, 10.0), ()))


@unittest.skipUnless((COLLISION / "M6_out.ccd").is_file(),
                     "extracted Gateon Port collision data not present")
class GateonPortTests(unittest.TestCase):
    """The real room, the real trigger, the real failure."""

    @classmethod
    def setUpClass(cls):
        cls.regions = parse_regions((COLLISION / "M6_out.ccd").read_bytes())
        cls.room_codes = {
            int(key, 16): value for key, value in
            json.loads(ROOM_IDS.read_text(encoding="utf-8")).items()}
        cls.player = Position(70.76, 0.00, 113.10)
        """The player node the live route was built from, 20:26:18."""

    def _service(self, guard):
        return NavigationService(
            COLLISION, self.room_codes, LOGGER,
            room_change_regions=(
                (lambda floor_id: GATEON_EXIT_REGIONS) if guard else None))

    def _route_to(self, region_index, guard):
        region = self.regions[region_index]
        service = self._service(guard)
        service.begin(GATEON, Position(*region.anchor), self.player,
                      destination_region=region)
        return service, service.remaining_route(self.player) or []

    def _closest_to_parts_shop(self, route):
        curtain = self.regions[PARTS_SHOP_REGION]
        closest = math.inf
        points = [self.player] + list(route)
        for start, end in zip(points, points[1:]):
            for step in range(21):
                x = start.x + (end.x - start.x) * step / 20
                z = start.z + (end.z - start.z) * step / 20
                distance = curtain.distance(x, z)
                if distance is not None:
                    closest = min(closest, distance)
        return closest

    def test_the_parts_shop_curtain_is_what_the_log_described(self):
        """Pins the diagnosis itself, so a future data change cannot quietly
        invalidate every test below it."""
        curtain = self.regions[PARTS_SHOP_REGION]
        xs = [vertex[0] for triangle in curtain.triangles for vertex in triangle]
        zs = [vertex[2] for triangle in curtain.triangles for vertex in triangle]
        self.assertAlmostEqual(min(zs), 214.0, places=3)
        self.assertAlmostEqual(max(zs), 214.0, places=3)
        self.assertAlmostEqual(min(xs), 75.0, places=3)
        self.assertAlmostEqual(max(xs), 100.0, places=3)

    def test_routing_to_region_11_used_to_walk_through_the_parts_shop(self):
        """The unguarded behaviour, pinned so the fix cannot be mistaken for
        the room simply not having the problem."""
        _service, route = self._route_to(11, guard=False)
        self.assertTrue(route)
        self.assertLess(self._closest_to_parts_shop(route), 1.0)

    def test_the_guard_keeps_that_route_out_of_the_parts_shop(self):
        _service, route = self._route_to(11, guard=True)
        self.assertTrue(route)
        self.assertGreater(self._closest_to_parts_shop(route), 8.0)

    def test_every_exit_still_routes_with_the_guard_on(self):
        """The regression that would matter most if this were too strict.

        An earlier version blocked whole TILES a trigger touched; measured
        on this room it cut the reachable component from 23,488 tiles to
        1,961, because Gateon Port's doors sit in narrow gaps. Crossing-level
        avoidance costs none of the ten exits their route."""
        for index in sorted(GATEON_EXIT_REGIONS):
            with self.subTest(region=index):
                service, route = self._route_to(index, guard=True)
                result = service.next_waypoint(self.player)
                self.assertTrue(route, "route disappeared")
                self.assertTrue(result.path_available)

    def test_a_destination_may_still_be_reached_through_its_own_trigger(self):
        """The exemption. Routing to the parts shop has to be allowed to
        arrive at the parts shop."""
        service, route = self._route_to(PARTS_SHOP_REGION, guard=True)
        self.assertTrue(route)
        result = service.next_waypoint(self.player)
        self.assertTrue(result.path_available)
        self.assertLess(self._closest_to_parts_shop(route), 8.0)

    def test_no_provider_restores_the_old_behaviour(self):
        """`room_change_regions=None` must stay a faithful no-op, since every
        offline tool and most tests construct the service without one."""
        service = self._service(guard=False)
        self.assertEqual(service._avoid_segments(GATEON, None), ())


class SegmentDerivationTests(unittest.TestCase):
    @unittest.skipUnless((COLLISION / "M6_out.ccd").is_file(),
                         "extracted Gateon Port collision data not present")
    def test_a_curtain_becomes_one_segment_per_triangle(self):
        regions = parse_regions((COLLISION / "M6_out.ccd").read_bytes())
        segments = region_crossing_segments(regions[PARTS_SHOP_REGION])
        self.assertEqual(len(segments), 2)
        for start, end in segments:
            self.assertAlmostEqual(start[1], 214.0, places=3)
            self.assertAlmostEqual(end[1], 214.0, places=3)


if __name__ == "__main__":
    unittest.main()
