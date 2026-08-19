"""A sliding region point is not a moving destination (2026-08-13).

Live, `M3_out` 05:49:31-38, guiding to "Exit. to Relic Stone cave": five full
rebuilds of a 1861-node room in seven seconds, one on every poll that cleared
`MIN_REBUILD_INTERVAL`. Every build's `target_pos.x` equalled that poll's
`start_pos.x` exactly, with `target_pos.z` pinned at -23.86 -- the cave's
trigger volume has a long edge at that z, the player was walking parallel to
it along the clifftop, and `Region.nearest_point` therefore returned
`(player.x, -23.86)` every poll. Drift crossed the 8.0 threshold on every 8
units walked.

The waste was not the worst of it. Reprojecting the sliding point selected a
different SURFACE at different x -- at x=-38.04 the nearest floor beneath
(x, -23.86) is the clifftop itself (y=120.00, 1637 nodes, a 2-waypoint "8
units away") while at x=-27.97 it is the cave floor below (y=-5.04, 1861
nodes, a 30-waypoint "686 units away"). The guide alternated between those
two answers for one unchanged destination.

Three things were conflated and are now separate: the destination's IDENTITY
(the trigger volume), the SPOKEN point (still slides, still updates), and the
route's ARRIVAL SET (already derived from the region's triangles by
`destination_target_tiles`, which never read the sliding point at all).
"""
import unittest

from battle_narrator.collision_probe import WalkTriangle
from battle_narrator.navigation_service import (
    MIN_REBUILD_INTERVAL,
    MOVING_TARGET_REBUILD_DISTANCE,
    NavigationService,
)
from battle_narrator.npc_beacons import Position
from battle_narrator.pathfinding import build_room_geometry


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def advance(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


class FakeLogger:
    def info(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def walk_rect(x0, x1, z0, z1, y=0.0, layer=0):
    out = []
    step = 8.0
    x = x0
    while x < x1:
        z = z0
        while z < z1:
            out.append(WalkTriangle(
                ((x, y, z), (x + step, y, z), (x + step, y, z + step)),
                (0.0, 1.0, 0.0), layer, layer, 0xFF, 0))
            out.append(WalkTriangle(
                ((x, y, z), (x + step, y, z + step), (x, y, z + step)),
                (0.0, 1.0, 0.0), layer, layer, 0xFF, 0))
            z += step
        x += step
    return out


class FakeComponent:
    """One trigger volume. `distance` is 0 inside its XZ box and the
    perpendicular gap outside, which is all the selector and
    `_region_component_key` need."""

    def __init__(self, x0, x1, z0, z1, tag, base_y=0.0):
        self.x0, self.x1, self.z0, self.z1 = x0, x1, z0, z1
        self.tag = tag
        # Real 3-vertex triangles: `_region_component_key` uses them as the
        # component's identity, and `destination_height_band` reads their Y
        # to decide which surface the region belongs to.
        self.triangles = (
            ((x0, base_y, z0), (x1, base_y, z0), (x1, base_y, z1)),
            ((x0, base_y, z0), (x1, base_y, z1), (x0, base_y, z1)),
        )

    def distance(self, x, z):
        dx = max(self.x0 - x, 0.0, x - self.x1)
        dz = max(self.z0 - z, 0.0, z - self.z1)
        return (dx * dx + dz * dz) ** 0.5

    def nearest_point(self, x, z):
        return (min(max(x, self.x0), self.x1), min(max(z, self.z0), self.z1))


class FakeRegion:
    """A region whose near edge runs along constant z, exactly like the
    Relic cave trigger that produced the live churn."""

    def __init__(self, *components):
        self._components = list(components)
        self.triangles = tuple(
            t for c in self._components for t in c.triangles)
        self.anchor = (0.0, 0.0, 0.0)
        self.index = 1

    def components(self):
        return list(self._components)

    def nearest_point(self, x, z):
        best = min(self._components, key=lambda c: c.distance(x, z))
        return best.nearest_point(x, z)


CAVE = FakeComponent(-60.0, 60.0, -24.0, -16.0, "cave")
FAR = FakeComponent(-60.0, 60.0, 200.0, 208.0, "far")


class RegionPointSlideTests(unittest.TestCase):
    """The core case: same volume, player walks, spoken point slides."""

    FLOOR = 0x84

    def _service(self):
        service = NavigationService(
            collision_dir="unused", room_codes={}, logger=FakeLogger(),
            clock=FakeClock())
        service._geometry_cache[self.FLOOR] = build_room_geometry(
            tuple(walk_rect(-80.0, 80.0, -80.0, 80.0)), ())
        return service

    def _builds(self, service):
        return getattr(service, "_build_count", 0)

    def setUp(self):
        self.service = self._service()
        self.clock = self.service.clock
        self.region = FakeRegion(CAVE)
        # Count builds without depending on log text.
        self.built = []
        original = self.service._try_build

        def counting(*args, **kwargs):
            self.built.append(kwargs.get("destination_position", args[1] if len(args) > 1 else None))
            return original(*args, **kwargs)

        self.service._try_build = counting

    def _point_for(self, player_x):
        x, z = self.region.nearest_point(player_x, -40.0)
        return Position(x, 0.0, z)

    def test_the_slide_alone_does_not_rebuild(self):
        """Walk 120 units parallel to the trigger's long edge -- fifteen
        times MOVING_TARGET_REBUILD_DISTANCE -- and the route must be built
        exactly once."""
        self.service.begin(
            self.FLOOR, self._point_for(-60.0),
            player_position=Position(-60.0, 0.0, -40.0),
            destination_region=self.region)
        self.assertEqual(len(self.built), 1)
        route = self.service._route
        self.assertIsNotNone(route)

        for player_x in range(-55, 65, 5):
            self.clock.advance(MIN_REBUILD_INTERVAL + 0.1)
            self.service.update(
                self.FLOOR, self._point_for(float(player_x)),
                player_position=Position(float(player_x), 0.0, -40.0),
                destination_region=self.region)

        self.assertEqual(
            len(self.built), 1,
            f"rebuilt {len(self.built) - 1} times for a destination that "
            f"never left its trigger volume")
        self.assertIs(
            self.service._route, route,
            "the route object was replaced despite no rebuild")

    def test_the_point_really_does_slide_far_enough_to_have_triggered_it(self):
        """Guards the fixture: if the point did not move past the threshold,
        the test above would pass vacuously."""
        first = self._point_for(-60.0)
        last = self._point_for(60.0)
        self.assertGreater(
            abs(last.x - first.x), MOVING_TARGET_REBUILD_DISTANCE * 10)
        self.assertEqual(first.z, last.z, "the near edge should be constant z")

    def test_waypoint_and_progress_state_survive_the_slide(self):
        self.service.begin(
            self.FLOOR, self._point_for(-60.0),
            player_position=Position(-60.0, 0.0, -40.0),
            destination_region=self.region)
        route = self.service._route
        self.service.next_waypoint(Position(-60.0, 0.0, -40.0))
        committed = route.waypoint_sequence
        self.assertIsNotNone(committed)

        for player_x in (-40.0, -20.0, 0.0, 20.0):
            self.clock.advance(MIN_REBUILD_INTERVAL + 0.1)
            self.service.update(
                self.FLOOR, self._point_for(player_x),
                player_position=Position(player_x, 0.0, -40.0),
                destination_region=self.region)

        self.assertIs(self.service._route, route)
        self.assertIs(
            route.waypoint_sequence, committed,
            "the committed waypoint sequence was discarded by a slide")
        self.assertFalse(route.abandoned)


class RebuildStillHappensTests(unittest.TestCase):
    """The suppression must be specific. Everything that genuinely changes
    the destination still rebuilds."""

    FLOOR = 0x84

    def setUp(self):
        self.service = NavigationService(
            collision_dir="unused", room_codes={}, logger=FakeLogger(),
            clock=FakeClock())
        self.service._geometry_cache[self.FLOOR] = build_room_geometry(
            tuple(walk_rect(-80.0, 80.0, -80.0, 240.0)), ())
        self.clock = self.service.clock
        self.built = []
        original = self.service._try_build

        def counting(*args, **kwargs):
            self.built.append(True)
            return original(*args, **kwargs)

        self.service._try_build = counting

    def _begin(self, region, point):
        self.service.begin(
            self.FLOOR, point, player_position=Position(0.0, 0.0, -40.0),
            destination_region=region)

    def test_a_different_component_rebuilds(self):
        region = FakeRegion(CAVE, FAR)
        self._begin(region, Position(0.0, 0.0, -16.0))
        before = len(self.built)
        self.clock.advance(MIN_REBUILD_INTERVAL + 0.1)
        # A point on the FAR volume: different trigger, same region.
        self.service.update(
            self.FLOOR, Position(0.0, 0.0, 200.0),
            player_position=Position(0.0, 0.0, -40.0),
            destination_region=region)
        self.assertGreater(
            len(self.built), before,
            "moving to a different volume of the region did not rebuild")

    def test_a_different_region_rebuilds(self):
        self._begin(FakeRegion(CAVE), Position(0.0, 0.0, -16.0))
        before = len(self.built)
        self.clock.advance(MIN_REBUILD_INTERVAL + 0.1)
        self.service.update(
            self.FLOOR, Position(0.0, 0.0, 200.0),
            player_position=Position(0.0, 0.0, -40.0),
            destination_region=FakeRegion(FAR))
        self.assertGreater(len(self.built), before)

    def test_a_point_destination_still_uses_the_drift_rule(self):
        """No region means a genuinely moving target -- an NPC walking away.
        The drift rebuild must be untouched for it."""
        self.service.begin(
            self.FLOOR, Position(0.0, 0.0, 0.0),
            player_position=Position(0.0, 0.0, -40.0))
        before = len(self.built)
        self.clock.advance(MIN_REBUILD_INTERVAL + 0.1)
        self.service.update(
            self.FLOOR,
            Position(MOVING_TARGET_REBUILD_DISTANCE * 4, 0.0, 0.0),
            player_position=Position(0.0, 0.0, -40.0))
        self.assertGreater(
            len(self.built), before,
            "a real moving-target drift stopped rebuilding")

    def test_a_point_destination_below_the_threshold_still_does_not_rebuild(self):
        self.service.begin(
            self.FLOOR, Position(0.0, 0.0, 0.0),
            player_position=Position(0.0, 0.0, -40.0))
        before = len(self.built)
        self.clock.advance(MIN_REBUILD_INTERVAL + 0.1)
        self.service.update(
            self.FLOOR,
            Position(MOVING_TARGET_REBUILD_DISTANCE * 0.5, 0.0, 0.0),
            player_position=Position(0.0, 0.0, -40.0))
        self.assertEqual(len(self.built), before)

    def test_a_floor_change_still_rebuilds(self):
        region = FakeRegion(CAVE)
        self._begin(region, Position(0.0, 0.0, -16.0))
        self.service._geometry_cache[0x7D] = self.service._geometry_cache[self.FLOOR]
        before = len(self.built)
        self.clock.advance(MIN_REBUILD_INTERVAL + 0.1)
        self.service.update(
            0x7D, Position(0.0, 0.0, -16.0),
            player_position=Position(0.0, 0.0, -40.0),
            destination_region=region)
        self.assertGreater(
            len(self.built), before, "a room change stopped rebuilding")


if __name__ == "__main__":
    unittest.main()
