import math
import logging
import unittest
from pathlib import Path

from battle_narrator import navigation_service as ns_module
from battle_narrator.collision_probe import (
    CollisionTriangle, WalkTriangle, parse_environment_triangles,
    parse_walk_model_triangles,
)
from battle_narrator.navigation_service import (
    HELD_WAYPOINT_TIMEOUT,
    MIN_REBUILD_INTERVAL,
    NavigationService,
    RouteConfidence,
    STALL_MOVEMENT_EPSILON,
)
from battle_narrator.npc_beacons import Position
from battle_narrator.pathfinding import (
    TILE_SIZE, build_room_geometry, flow_field_from, flow_field_toward,
    reconstruct_route, resolve_node, simplify_route, walk_height_candidates,
)


def walk_tile(ix, iz, tile_size=TILE_SIZE, y=0.0, layer=0):
    x0, z0 = ix * tile_size, iz * tile_size
    x1, z1 = x0 + tile_size, z0 + tile_size
    return [
        WalkTriangle(
            ((x0, y, z0), (x1, y, z0), (x1, y, z1)), (0.0, 1.0, 0.0),
            layer, layer, 0xFF, 0),
        WalkTriangle(
            ((x0, y, z0), (x1, y, z1), (x0, y, z1)), (0.0, 1.0, 0.0),
            layer, layer, 0xFF, 0),
    ]


def walk_rect(ix0, ix1, iz0, iz1, tile_size=TILE_SIZE, y=0.0, layer=0, exclude=()):
    triangles = []
    for ix in range(ix0, ix1):
        for iz in range(iz0, iz1):
            if (ix, iz) in exclude:
                continue
            triangles.extend(walk_tile(ix, iz, tile_size, y, layer))
    return triangles


def wall_segment(p0, p1, y0=-10.0, y1=10.0):
    (x0, z0), (x1, z1) = p0, p1
    return [
        CollisionTriangle(
            ((x0, y0, z0), (x1, y0, z1), (x1, y1, z1)), (0.0, 0.0, 1.0), 0, 0),
        CollisionTriangle(
            ((x0, y0, z0), (x1, y1, z1), (x0, y1, z0)), (0.0, 0.0, 1.0), 0, 0),
    ]


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def advance(self, dt):
        self.t += dt

    def __call__(self):
        return self.t


def _logger():
    return logging.getLogger("navigation-service-test")


def force_waypoint_failure(test, service, clock, x=4.0,
                           z_lo=9.0, z_hi=13.0, max_polls=80):
    """Induce a genuine waypoint-progress failure the way a live player
    would: by MOVING without closing distance.

    Standing still deliberately stopped counting as of 2026-08-03 (see
    `navigation_service.STALL_MOVEMENT_EPSILON` -- pausing to orient is
    exactly what an audio guide asks a blind player to do), so tests can no
    longer just advance the clock on a motionless player.

    Oscillates WITHIN a single tile and perpendicular to the route, so each
    poll's step clears STALL_MOVEMENT_EPSILON while the player's tile -- and
    therefore the active waypoint -- stays fixed, and the distance to that
    waypoint never improves by WAYPOINT_PROGRESS_EPSILON.

    Returns the NavigationResult from the poll on which the failure fired."""
    before = service._route.rebuild_attempts if service._route else 0
    toggle = True
    for _ in range(max_polls):
        clock.advance(0.5)
        z = z_lo if toggle else z_hi
        toggle = not toggle
        result = service.next_waypoint(Position(x, 0.0, z))
        if service._route is None or service._route.abandoned:
            return result
        if service._route.rebuild_attempts != before:
            return result
    raise AssertionError(
        "could not induce a waypoint-progress failure by moving")


class NavigationServiceTests(unittest.TestCase):
    def _service_with_geometry(self, floor_id, walk_triangles, wall_triangles=(), clock=None):
        service = NavigationService(
            collision_dir="unused", room_codes={}, logger=_logger(),
            clock=clock or FakeClock())
        service._geometry_cache[floor_id] = build_room_geometry(
            tuple(walk_triangles), tuple(wall_triangles))
        return service

    def test_open_floor_routes_toward_a_waypoint_not_the_raw_destination(self):
        service = self._service_with_geometry(1, walk_rect(-10, 10, -10, 10))
        destination = Position(70.0, 0.0, 70.0)
        service.begin(1, destination)
        result = service.next_waypoint(Position(-70.0, 0.0, -70.0))
        self.assertTrue(result.path_available)
        self.assertFalse(result.fallback_started)
        self.assertNotEqual(
            (result.target_position.x, result.target_position.z),
            (destination.x, destination.z),
        )

    def test_reaching_destination_tile_hands_off_to_the_real_destination(self):
        service = self._service_with_geometry(1, walk_rect(-2, 2, -2, 2))
        destination = Position(6.0, 0.0, 6.0)  # tile (0, 0)
        service.begin(1, destination)
        result = service.next_waypoint(Position(5.0, 0.0, 5.0))  # same tile
        self.assertEqual(result.target_position, destination)

    def test_unreachable_destination_falls_back_once(self):
        # A destination with no walk-model coverage anywhere near the
        # player is genuinely unreachable now -- there's no default-open
        # fallback anymore (routing requires real walk-model coverage; see
        # pathfinding.py's own top docstring). This isolated walk patch
        # sits nowhere near the player.
        far = walk_rect(50, 55, 50, 55)
        service = self._service_with_geometry(1, far)
        service.begin(1, Position(420.0, 0.0, 420.0))
        player = Position(20.0, 0.0, 20.0)
        first = service.next_waypoint(player)
        self.assertFalse(first.path_available)
        self.assertTrue(first.fallback_started)
        second = service.next_waypoint(player)
        self.assertFalse(second.path_available)
        self.assertFalse(second.fallback_started)

    def test_recovers_cleanly_after_a_later_successful_rebuild(self):
        far = walk_rect(50, 55, 50, 55)
        near = walk_rect(0, 5, 0, 5)
        clock = FakeClock()
        service = self._service_with_geometry(1, far, clock=clock)
        service.begin(1, Position(420.0, 0.0, 420.0))
        player = Position(20.0, 0.0, 20.0)
        failed = service.next_waypoint(player)
        self.assertFalse(failed.path_available)
        self.assertTrue(failed.fallback_started)

        # Swap in geometry that actually covers the player's own area too,
        # simulating "a rebuild against reachable geometry now succeeds."
        service._geometry_cache[1] = build_room_geometry(tuple(near), ())
        clock.advance(MIN_REBUILD_INTERVAL + 0.1)
        service.update(1, Position(35.0, 0.0, 35.0))  # now reachable from player
        recovered = service.next_waypoint(player)
        self.assertTrue(recovered.path_available)
        self.assertFalse(recovered.fallback_started)

    def test_failed_rebuild_preserves_the_existing_route(self):
        # A genuine _try_build FAILURE (not just "unreachable from the
        # player," which next_waypoint handles separately) requires
        # actually exceeding MAX_TILES -- a large enough walk-covered area
        # does that reliably now that walkability requires real coverage
        # (the old "stretch the bounds with two tiny wall markers" trick no
        # longer works: an empty/near-empty walk model just fails to seed
        # at all instead of flooding an open default-walkable void).
        clock = FakeClock()
        service = self._service_with_geometry(
            1, walk_rect(-10, 10, -10, 10), clock=clock)
        service.begin(1, Position(70.0, 0.0, 70.0))
        player = Position(-70.0, 0.0, -70.0)
        before = service.next_waypoint(player)
        self.assertTrue(before.path_available)

        huge_walk_area = walk_rect(-75, 75, -75, 75)  # 150x150 = 22500 tiles
        service._geometry_cache[1] = build_room_geometry(tuple(huge_walk_area), ())
        clock.advance(MIN_REBUILD_INTERVAL + 0.1)
        service.update(1, Position(1500.0, 0.0, 1500.0))
        after = service.next_waypoint(player)
        self.assertTrue(after.path_available)
        self.assertEqual(
            (after.target_position.x, after.target_position.z),
            (before.target_position.x, before.target_position.z),
        )

    def test_room_change_with_failed_rebuild_falls_back(self):
        clock = FakeClock()
        service = self._service_with_geometry(
            1, walk_rect(-10, 10, -10, 10), clock=clock)
        service.begin(1, Position(70.0, 0.0, 70.0))
        player = Position(-70.0, 0.0, -70.0)
        self.assertTrue(service.next_waypoint(player).path_available)

        # Room 2 has no matching collision geometry at all.
        service._geometry_cache[2] = build_room_geometry((), ())
        clock.advance(MIN_REBUILD_INTERVAL + 0.1)
        service.update(2, Position(0.0, 0.0, 0.0))
        result = service.next_waypoint(player)
        self.assertFalse(result.path_available)
        self.assertTrue(result.fallback_started)

    def test_room_change_rebuilds_immediately_without_waiting_for_cooldown(self):
        clock = FakeClock()
        service = self._service_with_geometry(
            1, walk_rect(-10, 10, -10, 10), clock=clock)
        service.begin(1, Position(70.0, 0.0, 70.0))
        service._geometry_cache[2] = build_room_geometry(
            tuple(walk_rect(-10, 10, -10, 10)), ())
        clock.advance(0.05)  # well inside MIN_REBUILD_INTERVAL
        service.update(2, Position(70.0, 0.0, 70.0))
        self.assertEqual(service._route.floor_id, 2)

    def test_small_target_drift_does_not_trigger_a_rebuild(self):
        clock = FakeClock()
        service = self._service_with_geometry(
            1, walk_rect(-10, 10, -10, 10), clock=clock)
        service.begin(1, Position(70.0, 0.0, 70.0))
        built_at = service._route.built_at
        clock.advance(MIN_REBUILD_INTERVAL + 0.1)
        service.update(1, Position(72.0, 0.0, 70.0))  # under the drift threshold
        self.assertEqual(service._route.built_at, built_at)

    def test_large_target_drift_rebuilds_only_after_the_cooldown(self):
        clock = FakeClock()
        service = self._service_with_geometry(
            1, walk_rect(-10, 10, -10, 10), clock=clock)
        service.begin(1, Position(70.0, 0.0, 70.0))
        built_at = service._route.built_at

        clock.advance(0.1)  # still inside the cooldown window
        service.update(1, Position(70.0, 0.0, -70.0))
        self.assertEqual(service._route.built_at, built_at)

        clock.advance(MIN_REBUILD_INTERVAL)
        service.update(1, Position(70.0, 0.0, -70.0))
        self.assertGreater(service._route.built_at, built_at)

    def test_waypoint_hysteresis_prevents_flicker_and_advances_only_when_close(self):
        # Sample distances updated 2026-08-02 for the recalibrated
        # WAYPOINT_STABLE_RADIUS_RATIO (0.5 -> 0.9, i.e. a 4.0 -> 7.2 unit
        # capture window; see that constant's docstring for the live
        # evidence). The property under test is unchanged -- jitter outside
        # the window must not move the target, crossing into it must, and
        # drifting back must never revert -- only the distances that
        # represent "outside" and "inside" have moved with the window.
        service = self._service_with_geometry(1, walk_rect(0, 20, 0, 3))
        service.begin(1, Position(150.0, 0.0, 12.0))

        first = service.next_waypoint(Position(4.0, 0.0, 12.0))
        self.assertTrue(first.path_available)
        first_tile = (round(first.target_position.x), round(first.target_position.z))
        capture_radius = TILE_SIZE * ns_module.WAYPOINT_STABLE_RADIUS_RATIO

        # Distances are taken RELATIVE to wherever the waypoint actually is,
        # rather than hardcoded: since route simplification (2026-08-02)
        # waypoints sit at turns / MAX_WAYPOINT_SPAN checkpoints rather than
        # on adjacent tiles, so absolute coordinates would silently stop
        # exercising the boundary this test is about.
        wp = first.target_position

        # Just OUTSIDE the capture window -- must not change the target.
        jittered = service.next_waypoint(
            Position(wp.x - (capture_radius + 0.5), 0.0, wp.z))
        self.assertEqual(
            (round(jittered.target_position.x), round(jittered.target_position.z)),
            first_tile,
        )

        # Just INSIDE the capture window -- a real advance.
        advanced = service.next_waypoint(
            Position(wp.x - (capture_radius - 0.5), 0.0, wp.z))
        advanced_tile = (
            round(advanced.target_position.x), round(advanced.target_position.z))
        self.assertNotEqual(advanced_tile, first_tile)

        # Drifting back outside the window must NOT revert the waypoint --
        # the guide never flickers backward.
        reverted_check = service.next_waypoint(
            Position(wp.x - (capture_radius + 0.5), 0.0, wp.z))
        self.assertEqual(
            (round(reverted_check.target_position.x),
             round(reverted_check.target_position.z)),
            advanced_tile,
        )

    def test_held_waypoint_falls_back_after_timeout(self):
        # Live-caught 2026-07-30: a player who climbed onto a raised area
        # left the region this route's flow field linked, and next_waypoint
        # kept repeating a now-stale waypoint (behind them, across a real
        # wall) for over 90 seconds straight instead of ever giving up.
        clock = FakeClock()
        service = self._service_with_geometry(
            1, walk_rect(-10, 10, -10, 10), clock=clock)
        service.begin(1, Position(70.0, 0.0, 70.0))
        linked_player = Position(-70.0, 0.0, -70.0)
        first = service.next_waypoint(linked_player)
        self.assertTrue(first.path_available)

        # Well outside this route's walk-model coverage -- simulates having
        # wandered/climbed somewhere never linked.
        unlinked_player = Position(5000.0, 0.0, 5000.0)
        held = service.next_waypoint(unlinked_player)
        self.assertTrue(held.path_available)
        self.assertFalse(held.fallback_started)
        self.assertEqual(
            (held.target_position.x, held.target_position.z),
            (first.target_position.x, first.target_position.z),
        )

        clock.advance(HELD_WAYPOINT_TIMEOUT - 0.1)
        still_held = service.next_waypoint(unlinked_player)
        self.assertTrue(still_held.path_available)
        self.assertFalse(still_held.fallback_started)

        clock.advance(0.2)  # crosses the timeout
        gave_up = service.next_waypoint(unlinked_player)
        self.assertFalse(gave_up.path_available)
        self.assertTrue(gave_up.fallback_started)

        # Fallback keeps being reported, but the one-shot warning doesn't
        # repeat every poll.
        still_gave_up = service.next_waypoint(unlinked_player)
        self.assertFalse(still_gave_up.path_available)
        self.assertFalse(still_gave_up.fallback_started)

    def test_recovering_before_timeout_resets_the_held_clock(self):
        clock = FakeClock()
        service = self._service_with_geometry(
            1, walk_rect(-10, 10, -10, 10), clock=clock)
        service.begin(1, Position(70.0, 0.0, 70.0))
        linked_player = Position(-70.0, 0.0, -70.0)
        unlinked_player = Position(5000.0, 0.0, 5000.0)

        service.next_waypoint(linked_player)
        clock.advance(HELD_WAYPOINT_TIMEOUT - 0.1)
        service.next_waypoint(unlinked_player)  # held, not yet timed out

        # Re-linking well before the timeout clears the held clock.
        clock.advance(0.05)
        relinked = service.next_waypoint(linked_player)
        self.assertTrue(relinked.path_available)

        # Going unlinked again gets a FRESH grace period, not a continuation
        # of the old one (which would already be past the timeout by now).
        clock.advance(HELD_WAYPOINT_TIMEOUT - 0.1)
        still_held = service.next_waypoint(unlinked_player)
        self.assertTrue(still_held.path_available)
        self.assertFalse(still_held.fallback_started)

    def test_remaining_route_reports_none_when_unreachable(self):
        far = walk_rect(50, 55, 50, 55)
        service = self._service_with_geometry(1, far)
        service.begin(1, Position(420.0, 0.0, 420.0))
        self.assertIsNone(
            service.remaining_route(Position(20.0, 0.0, 20.0)))

    def test_remaining_route_reports_positions_when_reachable(self):
        service = self._service_with_geometry(1, walk_rect(-10, 10, -10, 10))
        service.begin(1, Position(70.0, 0.0, 70.0))
        route = service.remaining_route(Position(-70.0, 0.0, -70.0))
        self.assertIsNotNone(route)
        self.assertGreater(len(route), 1)

    def test_reachable_reflects_whether_a_route_exists(self):
        service = self._service_with_geometry(1, walk_rect(-10, 10, -10, 10))
        self.assertFalse(service.reachable())
        service.begin(1, Position(70.0, 0.0, 70.0))
        self.assertTrue(service.reachable())
        service.clear()
        self.assertFalse(service.reachable())


class RouteProgressValidationTests(unittest.TestCase):
    """The guide must detect and reject a bad route instead of confidently
    repeating it. Live incident that prompted this (2026-07-31): pitch
    pinned near maximum confidence for 2.5 seconds while the player's real
    position barely moved, then 90+ seconds chasing a single waypoint
    across 40x50 world units."""

    def _service_with_geometry(self, floor_id, walk_triangles, wall_triangles=(), clock=None):
        service = NavigationService(
            collision_dir="unused", room_codes={}, logger=_logger(),
            clock=clock or FakeClock())
        service._geometry_cache[floor_id] = build_room_geometry(
            tuple(walk_triangles), tuple(wall_triangles))
        return service

    def test_waypoint_progress_steadily_improving_survives_beyond_the_timeout(self):
        clock = FakeClock()
        service = self._service_with_geometry(1, walk_rect(0, 20, 0, 3), clock=clock)
        service.begin(1, Position(150.0, 0.0, 12.0))
        result = service.next_waypoint(Position(4.0, 0.0, 12.0))
        self.assertTrue(result.path_available)

        # Move steadily closer to the destination across several polls, with
        # the clock advancing generously each step
        # -- whether the active waypoint tile stays fixed or advances along
        # the way, genuinely closing distance must never trip a failure.
        player_x = 4.0
        for _ in range(8):
            clock.advance(3.5)
            player_x += 3.0
            result = service.next_waypoint(Position(player_x, 0.0, 12.0))
            self.assertTrue(result.path_available)
            self.assertNotEqual(result.confidence, RouteConfidence.DIRECT_FALLBACK)

    def test_moving_player_eventually_abandons_after_two_failures(self):
        # Renamed from "stationary" 2026-08-03: standing still deliberately
        # no longer counts as failure evidence (see STALL_MOVEMENT_EPSILON),
        # so a player who never closes distance must be MOVING to trip this.
        clock = FakeClock()
        service = self._service_with_geometry(
            1, walk_rect(0, 30, 0, 3), clock=clock)
        service.begin(1, Position(230.0, 0.0, 12.0))
        first = service.next_waypoint(Position(4.0, 0.0, 12.0))
        self.assertTrue(first.path_available)

        after_first_failure = force_waypoint_failure(self, service, clock)
        # The first rebuild starts afresh from the player's new position and
        # keeps the authoritative graph intact.
        self.assertTrue(after_first_failure.path_available)
        self.assertEqual(service._route.rebuild_attempts, 1)
        self.assertFalse(after_first_failure.progress_invalidated)

        after_second_failure = force_waypoint_failure(self, service, clock)
        self.assertFalse(after_second_failure.path_available)
        self.assertEqual(after_second_failure.confidence, RouteConfidence.DIRECT_FALLBACK)
        self.assertTrue(after_second_failure.progress_invalidated)

        # No repeated announcement on the next poll, even though still
        # abandoned.
        still_abandoned = service.next_waypoint(Position(4.0, 0.0, 12.0))
        self.assertFalse(still_abandoned.path_available)
        self.assertFalse(still_abandoned.progress_invalidated)
        self.assertEqual(still_abandoned.confidence, RouteConfidence.DIRECT_FALLBACK)

    def test_sustained_wide_circling_is_caught(self):
        # Amplitude updated 2026-08-01 alongside the
        # SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS recalibration (24 -> 160) so
        # it takes realistic wide circling to trigger, not a 2-unit wobble.
        # Renamed 2026-08-03: there is no stall timeout to be "before" any
        # more -- distance covered without closing is now the SOLE failure
        # signal (see WAYPOINT_PROGRESS_TIMEOUT), which makes this test the
        # primary guard that genuinely bad routes are still rejected.
        clock = FakeClock()
        service = self._service_with_geometry(1, walk_rect(0, 20, 0, 3), clock=clock)
        service.begin(1, Position(150.0, 0.0, 12.0))
        result = service.next_waypoint(Position(4.0, 0.0, 12.0))
        self.assertTrue(result.path_available)
        self.assertEqual(service._route.rebuild_attempts, 0)

        # Oscillate between two points EQUIDISTANT from the waypoint (z=4 and
        # z=20 straddle the corridor's centreline at z=12), so distance never
        # improves while real displacement piles up 16 units per poll --
        # ~35 units/s, matching measured in-game running speed.
        toggle = True
        for _ in range(40):
            clock.advance(0.1)
            z = 4.0 if toggle else 20.0
            toggle = not toggle
            service.next_waypoint(Position(4.0, 0.0, z))
            if service._route is not None and service._route.rebuild_attempts > 0:
                break
        self.assertGreater(
            service._route.rebuild_attempts, 0,
            "sustained circling that never closes distance was not caught")

    def test_failed_waypoint_is_not_removed_from_authoritative_geometry(self):
        clock = FakeClock()
        service = self._service_with_geometry(
            1, walk_rect(0, 30, 0, 3), clock=clock)
        service.begin(1, Position(230.0, 0.0, 12.0))
        service.next_waypoint(Position(4.0, 0.0, 12.0))
        failed_node = service._route.current_waypoint_node

        result = force_waypoint_failure(self, service, clock)
        self.assertTrue(result.path_available)
        self.assertIn(failed_node, service._route.failed_nodes)
        self.assertIn(failed_node, service._route.flow_field.node_height)

    def test_consecutive_waypoints_are_joined_by_verified_collinear_hops(self):
        # Consecutive waypoints must still be joined by a straight line of
        # nothing but walkable tiles. Route simplification (2026-08-02)
        # changed the GRANULARITY of that guarantee -- waypoints now sit at
        # turns / MAX_WAYPOINT_SPAN checkpoints instead of on every tile --
        # but not its substance: simplification only ever drops EXACTLY
        # collinear nodes, and every hop it collapses was individually
        # validated during the flood fill (layer connectivity, wall-crossing,
        # height continuity, corner-cut prevention). So the straight line
        # between two consecutive waypoints still passes through nothing but
        # verified hops. This asserts that directly, which is the property
        # that actually matters -- the old test asserted single-tile
        # adjacency, which was only ever a means to it.
        service = self._service_with_geometry(1, walk_rect(0, 20, 0, 3))
        service.begin(1, Position(150.0, 0.0, 12.0))
        seen = []
        x = 4.0
        while x < 145.0:
            result = service.next_waypoint(Position(x, 0.0, 12.0))
            self.assertTrue(result.path_available)
            node = service._route.current_waypoint_node
            if not seen or seen[-1] != node:
                seen.append(node)
            x += 3.0
        self.assertGreater(len(seen), 2)
        flow_field = service._route.flow_field
        for previous, current in zip(seen, seen[1:]):
            # Walk the verified next_hop chain from one waypoint to the next.
            chain = [previous]
            cursor = previous
            for _ in range(64):
                cursor = flow_field.next_hop.get(cursor)
                if cursor is None:
                    break
                chain.append(cursor)
                if cursor == current:
                    break
            self.assertEqual(
                chain[-1], current,
                f"waypoint {previous} -> {current} is not reachable by "
                f"following verified next_hop edges at all")
            # Every node collapsed in between must be exactly collinear with
            # the pair, so the straight line really does pass through them.
            (ax, az), _ = previous
            (cx, cz), _ = current
            for (bx, bz), _ in chain[1:-1]:
                cross = (bx - ax) * (cz - az) - (bz - az) * (cx - ax)
                self.assertEqual(
                    cross, 0,
                    f"collapsed node ({bx},{bz}) is not collinear with "
                    f"{previous} -> {current}, so the straight line between "
                    f"those waypoints was never validated as walkable")

    def test_confidence_is_verified_for_a_successfully_built_route(self):
        # Since routing now requires real walk-model coverage throughout
        # (no default-open inference), a successfully built route is always
        # VERIFIED -- there is no more "successful but built on inferred
        # ground" middle state (see RouteConfidence's own docstring).
        service = self._service_with_geometry(1, walk_rect(-10, 10, -10, 10))
        service.begin(1, Position(70.0, 0.0, 70.0))
        result = service.next_waypoint(Position(-70.0, 0.0, -70.0))
        self.assertEqual(result.confidence, RouteConfidence.VERIFIED)


class LiveRegression20260801Tests(unittest.TestCase):
    """Two defects found during the controlled live validation run on
    2026-08-01, in which the guide abandoned its route 2.18 seconds after
    activation while the project owner was genuinely trying to follow it."""

    def _service(self, floor_id, walk_triangles, wall_triangles=(), clock=None):
        service = NavigationService(
            collision_dir="unused", room_codes={}, logger=_logger(),
            clock=clock or FakeClock())
        service._geometry_cache[floor_id] = build_room_geometry(
            tuple(walk_triangles), tuple(wall_triangles))
        return service

    def test_realistic_running_speed_during_reaction_lag_does_not_abandon_the_route(self):
        """DEFECT 1: `SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS` was TILE_SIZE*3
        (24 units) -- only ~0.7-1.4 seconds of real movement at the measured
        in-game speed (~17 units/s walking, ~32-38 running). Live, both
        waypoint failures fired on this check at displacements of 24.07 and
        26.01, abandoning the route before the player could physically react
        to the newly-started audio cue.

        Simulates exactly that: a player moving at a realistic ~35 units/s
        who spends the first two seconds NOT yet converging (reaction lag,
        modelled here as movement perpendicular to the waypoint). The route
        must survive -- the 4-second stall timeout, not this displacement
        backstop, is what should judge a genuinely stalled approach."""
        clock = FakeClock()
        service = self._service(1, walk_rect(-20, 20, -20, 20), clock=clock)
        service.begin(1, Position(150.0, 0.0, 0.0))
        first = service.next_waypoint(Position(-150.0, 0.0, 0.0))
        self.assertTrue(first.path_available)

        # 20 polls x 0.1s = 2.0s of realistic running,
        # 3.5 units each = 35 units/s, total 70 units of displacement --
        # comfortably over the OLD 24-unit threshold, under the new one.
        z = 0.0
        for _ in range(20):
            clock.advance(0.1)
            z += 3.5  # perpendicular to the east-west route: no convergence
            result = service.next_waypoint(Position(-150.0, 0.0, z))
            self.assertTrue(
                result.path_available,
                f"route abandoned after only {clock.t:.1f}s of realistic "
                f"movement -- the displacement backstop is firing during "
                f"ordinary travel instead of catching sustained circling",
            )
            self.assertFalse(result.progress_invalidated)

    def test_player_on_a_differently_tagged_triangle_still_maps_into_the_route(self):
        """DEFECT 2: a node's `(tile, layer_set)` key is not well-defined
        from position alone -- one tile can hold walk-model triangles
        carrying DIFFERENT layer nibbles, so the key depends on exactly which
        XZ point inside the tile is sampled. `flow_field_from` samples tile
        centers; `resolve_node` samples where the player actually stands.

        Confirmed live in `M3_out` at tile (15,-21): tile centre resolved to
        layers {3} at height 120.005, while the project owner's real position
        3.6 units away resolved to layers {3,4} at the SAME height -- so the
        field held ((15,-21),{3}) but the player resolved to ((15,-21),{3,4}),
        producing a spurious 'player node not linked to destination'.

        Reproduced here with two non-overlapping, same-height triangles in
        one tile: a large one covering the centre tagged layer 0, and a small
        corner one tagged as a 0->1 transition. Standing on the corner
        triangle must still resolve into the route."""
        # Tile (0,0) is excluded from the bulk rect and rebuilt by hand from
        # two DISJOINT same-height triangles carrying different layer tags.
        # `walk_height_candidates` de-duplicates by height, so the two sample
        # points must land on genuinely different triangles (not merely
        # overlapping ones) for the tagging difference to survive -- which is
        # exactly the real M3_out situation.
        walk = list(walk_rect(-10, 10, -10, 10, y=0.0, layer=0, exclude={(0, 0)}))
        # Large triangle covering the tile centre (4,4), tagged layer 0.
        walk.append(WalkTriangle(
            ((0.0, 0.0, 0.0), (8.0, 0.0, 0.0), (4.0, 0.0, 8.0)),
            (0.0, 1.0, 0.0), 0, 0, 0xFF, 0))
        # Small corner triangle, same height, tagged as a 0->1 transition,
        # disjoint from the one above.
        walk.append(WalkTriangle(
            ((7.0, 0.0, 7.0), (8.0, 0.0, 7.0), (8.0, 0.0, 8.0)),
            (0.0, 1.0, 0.0), 0, 1, 0xFF, 0))
        service = self._service(1, walk)
        service.begin(1, Position(70.0, 0.0, 70.0))

        geometry = service._geometry_cache[1]
        centre = resolve_node(geometry, Position(4.0, 0.0, 4.0))
        corner = resolve_node(geometry, Position(7.8, 0.0, 7.5))
        self.assertIsNotNone(centre)
        self.assertIsNotNone(corner)
        self.assertEqual(centre[0], corner[0], "expected the same tile")
        self.assertNotEqual(
            centre[1], corner[1],
            "fixture no longer reproduces the defect: both sample points "
            "resolved to the same layer set, so there is nothing to rescue")

        # The player standing on the corner (transition-tagged) triangle must
        # still be located within the route rather than reported unlinked.
        result = service.next_waypoint(Position(7.8, 0.0, 7.5))
        self.assertTrue(
            result.path_available,
            "player standing on a differently-tagged triangle in a routed "
            "tile was not matched to any flow-field node")
        self.assertIsNotNone(service.remaining_route(Position(7.8, 0.0, 7.5)))

    def test_waypoint_captures_on_a_realistic_near_miss_of_the_tile_centre(self):
        """DEFECT 3: the waypoint capture window was
        `WAYPOINT_STABLE_RADIUS_RATIO` 0.5 -> 4.0 units. Live, the project
        owner's closest approaches to successive waypoints were 4.72, 4.30,
        6.36 and 8.57 units -- all just outside it -- so the waypoint never
        advanced and the 4-second stall timeout abandoned the route, even
        though every one of those waypoint tile centres was a genuinely
        standable walk-model surface.

        A player passing within a realistic near-miss of a waypoint's tile
        centre must capture it and advance."""
        service = self._service(1, walk_rect(0, 20, 0, 3))
        service.begin(1, Position(150.0, 0.0, 12.0))
        first = service.next_waypoint(Position(4.0, 0.0, 12.0))
        self.assertTrue(first.path_available)
        start_node = service._route.current_waypoint_node
        wp = service._route.flow_field.node_position(start_node)

        # Stand at the worst observed live near-miss distance (4.72 units)
        # from the waypoint centre -- offset purely in z so the approach is
        # unambiguous -- and require the waypoint to advance.
        near_miss = service.next_waypoint(Position(wp.x, 0.0, wp.z + 4.72))
        self.assertTrue(near_miss.path_available)
        self.assertNotEqual(
            service._route.current_waypoint_node, start_node,
            "waypoint did not advance despite a 4.72-unit approach -- the "
            "capture window is still too small for real walking")

    def test_capture_window_cannot_skip_a_hop(self):
        """The widened capture window must stay below the spacing between
        consecutive waypoints, so standing exactly on one waypoint never
        also captures the next."""
        self.assertLess(
            TILE_SIZE * ns_module.WAYPOINT_STABLE_RADIUS_RATIO, TILE_SIZE,
            "capture radius reached the orthogonal waypoint spacing -- "
            "waypoints could advance without the player moving")

    def test_standing_still_to_orient_does_not_abandon_the_route(self):
        """DEFECT 5: the stall timer ran on wall-clock, so simply standing
        still long enough abandoned the route outright. Live, two
        failures in one session fired at cumulative displacements of 0.00 and
        0.65 units -- the project owner was stationary, orienting.

        That is exactly what an audio guide asks a blind player to do (stop,
        listen, turn, get bearings), and standing still carries no evidence
        about whether the waypoint is reachable, which is the only thing this
        check exists to detect."""
        clock = FakeClock()
        service = self._service(1, walk_rect(0, 30, 0, 3), clock=clock)
        service.begin(1, Position(230.0, 0.0, 12.0))
        spot = Position(4.0, 0.0, 12.0)
        self.assertTrue(service.next_waypoint(spot).path_available)

        # Stand still far longer than the stall timeout, polling throughout.
        for _ in range(30):
            clock.advance(1.0)
            result = service.next_waypoint(spot)
            self.assertTrue(
                result.path_available,
                f"route abandoned after {clock.t:.0f}s of standing still -- "
                f"pausing to orient must not be treated as a bad route")
            self.assertFalse(result.progress_invalidated)

    def test_moving_without_closing_distance_still_fails(self):
        """The protection must survive the stationary fix: a player who is
        genuinely MOVING and still not closing distance is the real
        pathological signal, and must still fail."""
        clock = FakeClock()
        service = self._service(1, walk_rect(0, 30, 0, 3), clock=clock)
        service.begin(1, Position(230.0, 0.0, 12.0))
        service.next_waypoint(Position(4.0, 0.0, 12.0))

        # Shuffle back and forth well above STALL_MOVEMENT_EPSILON without
        # ever getting closer to the waypoint.
        toggle = True
        failed = False
        for _ in range(40):
            clock.advance(0.5)
            z = 8.0 if toggle else 16.0
            toggle = not toggle
            service.next_waypoint(Position(4.0, 0.0, z))
            if service._route is None or service._route.rebuild_attempts > 0:
                failed = True
                break
        self.assertTrue(
            failed,
            "a genuinely moving player who never closes distance should "
            "still trip progress validation")

    def test_reaching_a_waypoint_replenishes_the_rebuild_budget(self):
        """DEFECT 4: MAX_ROUTE_REBUILDS_PER_ACTIVATION was a never-resetting
        per-activation lifetime count, so a long journey got exactly one
        recovery in total. Live: rebuild #1 at t=5.0s, route permanently
        abandoned at t=9.7s -- despite the player having genuinely REACHED a
        waypoint at t=5.7s in between, in a perfectly routable area.

        Reaching a waypoint is proof the route works and must replenish the
        budget, so failures separated by real progress don't accumulate
        toward a permanent give-up."""
        clock = FakeClock()
        service = self._service(1, walk_rect(0, 30, 0, 3), clock=clock)
        service.begin(1, Position(230.0, 0.0, 12.0))
        service.next_waypoint(Position(4.0, 0.0, 12.0))

        # Burn the budget: move without closing distance until a waypoint
        # fails and forces a rebuild.
        force_waypoint_failure(self, service, clock)
        self.assertEqual(
            service._route.rebuild_attempts, 1,
            "expected the failed waypoint to consume one rebuild")

        # Now genuinely reach a waypoint -- walk onto its own centre.
        wp = service._route.flow_field.node_position(
            service._route.current_waypoint_node)
        advanced = service.next_waypoint(Position(wp.x, 0.0, wp.z))
        self.assertTrue(advanced.waypoint_advanced, "fixture did not advance")
        self.assertEqual(
            service._route.rebuild_attempts, 0,
            "reaching a waypoint did not replenish the rebuild budget -- a "
            "long journey still gets only one lifetime recovery")

        # A later, unrelated failure must therefore still get a rebuild
        # rather than immediately abandoning the whole activation.
        later = force_waypoint_failure(self, service, clock)
        self.assertTrue(
            later.path_available,
            "route was abandoned on the next failure even though the player "
            "had made real progress in between")
        self.assertFalse(later.progress_invalidated)

    def test_repeated_failures_without_progress_still_abandon(self):
        """The protection must remain intact where it was actually aimed:
        consecutive failures with NO waypoint reached in between still give
        up rather than rebuilding forever. Uses a MOVING player, since
        standing still stopped counting as failure evidence 2026-08-03."""
        clock = FakeClock()
        service = self._service(1, walk_rect(0, 30, 0, 3), clock=clock)
        service.begin(1, Position(230.0, 0.0, 12.0))
        self.assertTrue(
            service.next_waypoint(Position(4.0, 0.0, 12.0)).path_available)

        force_waypoint_failure(self, service, clock)   # failure 1 -> rebuild
        result = force_waypoint_failure(self, service, clock)  # failure 2 -> abandon
        self.assertFalse(result.path_available)
        self.assertTrue(result.progress_invalidated)

    def test_field_node_lookup_returns_the_nearest_height_node_at_that_tile(self):
        """Contract test for the tile+height fallback: whatever nodes the
        field happens to hold at a tile, the lookup must return the one whose
        height is closest to the query -- never an arbitrary pick. Asserted
        directly against the field's own contents rather than assuming a
        particular stacked-surface layout (two decks with no transition
        between them are correctly UNREACHABLE from one another, so a single
        field legitimately cannot contain both)."""
        service = self._service(1, walk_rect(-10, 10, -10, 10))
        service.begin(1, Position(70.0, 0.0, 70.0))
        route = service._route
        self.assertIsNotNone(route)

        sample_tile = next(iter(route.flow_field.node_height))[0]
        nodes_here = [n for n in route.flow_field.node_height if n[0] == sample_tile]
        self.assertGreaterEqual(len(nodes_here), 1)

        expected = min(
            nodes_here, key=lambda n: abs(route.flow_field.node_height[n]))
        self.assertEqual(service._field_node_at(route, sample_tile, 0.0), expected)

        # A tile the field never reached must report no node at all rather
        # than silently snapping the player onto an unrelated one.
        self.assertIsNone(service._field_node_at(route, (9999, 9999), 0.0))

    def test_field_node_lookup_refuses_a_node_far_above_or_below_the_player(self):
        """"Nearest height" is only an identification when something near is
        actually there. Unbounded, this lookup answered a query 500 units
        below the field with "you are standing on the surface 500 units above
        you" -- the same discarded-Y mistake that let a fallen player capture
        a waypoint on the terrace over their head (see
        `TerraceFallCaptureTests`). Past the tolerance the honest answer is
        None, which the caller already handles."""
        service = self._service(1, walk_rect(-10, 10, -10, 10))
        service.begin(1, Position(70.0, 0.0, 70.0))
        route = service._route
        sample_tile = next(iter(route.flow_field.node_height))[0]

        for query_height in (-500.0, 500.0):
            self.assertIsNone(
                service._field_node_at(route, sample_tile, query_height),
                f"a player at height {query_height} was matched onto a node "
                f"on a completely different surface")


REAL_M3_OUT_CCD = (
    Path(__file__).resolve().parent.parent
    / "_dialogue_extraction" / "collision" / "M3_out.ccd"
)


class UTurnWaypointCommitmentTests(unittest.TestCase):
    """Reproduces the live ping-pong the project owner hit in M3_out (0x84),
    against that room's REAL geometry.

    The route there doubles back: its two arms lie in ADJACENT tile rows
    (-16 and -15) whose flow-field hops point in opposite directions. The
    boundary between them is exactly z = -120.0, and the logged positions
    show the player walking along z ~= -120.5 -- straddling it. Sub-tile
    drift flipped which row they resolved to, and re-deriving the next
    waypoint from that row handed back the opposite arm each time:
    "go west", "go east", "go west" -- eight reversals in seventy seconds
    and 160 units of movement with no progress, until they turned the guide
    off and walked it manually.

    Destination (-12.0, -68.0) was recovered by searching the room for one
    that reproduces the logged signature exactly: from node (-9,-15) the
    next waypoint is (-6,-15) while from (-7,-16) it is (-8,-16), with
    chain lengths 12 and 14 -- the same numbers the live log recorded.
    """

    DESTINATION = Position(-12.0, 120.0, -68.0)
    # Real positions from the live log, straddling the z = -120 boundary.
    LOGGED_WALK = (
        Position(-46.87, 120.0, -120.80), Position(-59.00, 120.0, -121.78),
        Position(-66.11, 120.0, -119.95), Position(-48.91, 120.0, -121.02),
        Position(-56.09, 120.0, -121.78), Position(-70.92, 120.0, -119.08),
        Position(-46.66, 120.0, -120.78), Position(-58.11, 120.0, -121.81),
    )

    @classmethod
    def setUpClass(cls):
        if not REAL_M3_OUT_CCD.exists():
            raise unittest.SkipTest(f"missing fixture {REAL_M3_OUT_CCD}")
        raw = REAL_M3_OUT_CCD.read_bytes()
        cls.geometry = build_room_geometry(
            parse_walk_model_triangles(raw), parse_environment_triangles(raw))

    def _service(self):
        service = NavigationService(
            collision_dir="unused", room_codes={}, logger=_logger(),
            clock=FakeClock())
        service._geometry_cache[0x84] = self.geometry
        return service

    def test_the_logged_walk_really_straddles_the_row_boundary(self):
        """Guard the live input that drives the two behavioral tests below.

        Flow fields may now be a validated player-origin chain when the
        relocated graph cannot be rediscovered backward, so a full-field
        opposing-hop assertion is no longer an invariant. The actual
        regression remains what matters: crossing this boundary must not
        repoint or reverse the committed guide.
        """
        rows = {
            resolve_node(self.geometry, position)[0][1]
            for position in self.LOGGED_WALK
        }
        self.assertGreaterEqual(len(rows), 2)

    def test_walking_the_row_boundary_does_not_reverse_the_waypoint(self):
        service = self._service()
        # Production ALWAYS supplies the player position at activation
        # (`audio_guide.poll_once` passes `source.player_pose().position`),
        # and it has to: this destination sits in a small pocket, so
        # `flow_field_toward` needs an origin to run its reachability
        # reseed. Calling begin() without one was never representative.
        service.begin(0x84, self.DESTINATION, self.LOGGED_WALK[0])
        aims = []
        for position in self.LOGGED_WALK:
            result = service.next_waypoint(position)
            if result.path_available and result.target_position is not None:
                aims.append((round(result.target_position.x, 1),
                             round(result.target_position.z, 1)))
        self.assertTrue(aims, "no waypoints were produced at all")
        order = []
        for aim in aims:
            if not order or order[-1] != aim:
                order.append(aim)
        self.assertEqual(
            len(order), len(set(order)),
            f"the aim point reversed and came back: {order}")

    def test_crossing_the_boundary_does_not_repoint_the_guide(self):
        service = self._service()
        # Production ALWAYS supplies the player position at activation
        # (`audio_guide.poll_once` passes `source.player_pose().position`),
        # and it has to: this destination sits in a small pocket, so
        # `flow_field_toward` needs an origin to run its reachability
        # reseed. Calling begin() without one was never representative.
        service.begin(0x84, self.DESTINATION, self.LOGGED_WALK[0])
        service.next_waypoint(Position(-46.87, 120.0, -120.80))
        committed = service._route.current_waypoint_node
        # One step across z = -120, nowhere near the current waypoint.
        service.next_waypoint(Position(-46.87, 120.0, -119.20))
        self.assertEqual(
            service._route.current_waypoint_node, committed,
            "crossing the row boundary changed the aim point")


class WaypointOvershootTests(unittest.TestCase):
    """The cursor could only ever step forward ONE place, and only on coming
    within the capture radius (7.2 units) of the CURRENT waypoint. Walk wide
    of one and it never advanced, so the beacon kept pointing at a waypoint
    the player had already passed -- behind them -- until they walked back
    for it. See `_advance_past_reached_waypoints`.

    Note on scope: this is NOT established as the cause of the project
    owner's "a waypoint at west, then east, then west again" report. Two
    candidate explanations for that report have now been ruled out by them
    directly -- this overshoot, and the grid staircase (see
    `pathfinding.simplify_route`). What is asserted below is only the
    demonstrable defect: the guide aimed at a waypoint behind a player
    walking steadily away from it."""

    def _service(self, geometry, floor=0x1):
        service = NavigationService(
            collision_dir="unused", room_codes={}, logger=_logger(),
            clock=FakeClock())
        service._geometry_cache[floor] = geometry
        return service

    def _corridor(self):
        """A wide-open east-west floor, 3 rows deep and 20 tiles long."""
        return build_room_geometry(walk_rect(0, 20, 0, 3), ())

    def test_walking_wide_of_a_waypoint_does_not_send_the_player_back(self):
        geometry = self._corridor()
        service = self._service(geometry)
        start = Position(4.0, 0.0, 12.0)
        destination = Position(150.0, 0.0, 12.0)
        service.begin(0x1, destination, start)
        service.next_waypoint(start)

        # March east along the row ABOVE the route's own row, so every
        # waypoint is missed by more than the 7.2-unit capture window.
        aims = []
        for x in range(8, 150, 6):
            position = Position(float(x), 0.0, 20.0)
            result = service.next_waypoint(position)
            if result.path_available and result.target_position is not None:
                aims.append((position.x, result.target_position.x))

        self.assertTrue(aims, "no guidance was produced at all")
        behind = [(px, ax) for px, ax in aims if ax < px - TILE_SIZE]
        self.assertEqual(
            behind, [],
            f"the guide aimed BEHIND a player walking steadily east: {behind}")


class TerraceFallCaptureTests(unittest.TestCase):
    """Reproduces the live failure of 2026-08-04 00:10 in `M3_out` (0x84).

    Waypoint capture compared XZ only (`_distance_xz` discards Y), so a
    player who fell off a terrace onto the ground DIRECTLY BENEATH their
    waypoint was credited with reaching it:

        00:10:00.849 player=(83.09, 40.00, 91.65) node=((10,11),{1}) -> wp=((2,11),{1})
        00:10:06.622 player=(19.23, -5.04, 98.97) node=((2,12),{0})  -> wp=((2,15),{1})

    Tile (2,11) really does carry both surfaces -- checked against the room's
    own walk model: height -4.41 layers [0], height 39.66 layers [1]. The
    player's XZ distance to the waypoint centre was 7.01 against the 7.20
    capture radius, so the cursor advanced and the committed sequence kept
    marching along the upper terrace while they stood 44.7 units below it.
    Remaining route length then GREW (54 -> 61 -> 65 -> 66) and the guide
    only gave up 160.5 units of walking later.

    The fixture mirrors that shape rather than the room byte-for-byte: one
    continuous lower ground, an upper terrace stacked directly above part of
    it, and a ramp joining them at the far end -- so the fallen position is
    genuinely inside the flow field, exactly as it was live (the real field
    held 2968 nodes spanning both layers)."""

    ROWS = range(0, 3)
    LOWER_Y = 0.0
    UPPER_Y = 30.0
    RAMP_ROW = 0
    RAMP_HEIGHTS = {10: 30.0, 11: 24.0, 12: 18.0, 13: 12.0, 14: 6.0}
    """A ramp descending east from the terrace, in row 0 only.

    It deliberately does NOT share tiles with the lower ground.
    `pathfinding._connected_walk_candidate` returns exactly ONE surface per
    neighbouring tile -- the nearest in height -- so where a flat floor and a
    ramp surface occupy the same tile within the height tolerance, the flood
    always takes the flat one and the ramp is never entered. Step size is 6
    so no rung lands exactly on the tolerance boundary."""

    def _walk_model(self):
        triangles = []
        for iz in self.ROWS:
            for ix in range(0, 26):
                if iz == self.RAMP_ROW and ix in self.RAMP_HEIGHTS:
                    # Transition triangles carrying BOTH layer tags, the way
                    # the walk model marks a real ramp (byte +0x31's nibbles).
                    height = self.RAMP_HEIGHTS[ix]
                    x0, z0 = ix * TILE_SIZE, iz * TILE_SIZE
                    x1, z1 = x0 + TILE_SIZE, z0 + TILE_SIZE
                    triangles.append(WalkTriangle(
                        ((x0, height, z0), (x1, height, z0), (x1, height, z1)),
                        (0.0, 1.0, 0.0), 0, 1, 0xFF, 0))
                    triangles.append(WalkTriangle(
                        ((x0, height, z0), (x1, height, z1), (x0, height, z1)),
                        (0.0, 1.0, 0.0), 0, 1, 0xFF, 0))
                    continue
                triangles.extend(walk_tile(ix, iz, y=self.LOWER_Y, layer=0))
            for ix in range(0, 10):
                # The terrace, stacked directly above the lower ground -- the
                # arrangement that made the fall possible.
                triangles.extend(walk_tile(ix, iz, y=self.UPPER_Y, layer=1))
        return triangles

    def _service(self, clock=None):
        service = NavigationService(
            collision_dir="unused", room_codes={}, logger=_logger(),
            clock=clock or FakeClock())
        service._geometry_cache[1] = build_room_geometry(
            tuple(self._walk_model()), ())
        return service

    def test_the_fixture_reproduces_the_stacked_terrace(self):
        """Guard: if the fixture ever stops holding two surfaces at one XZ,
        or stops connecting them through the ramp, the tests below would pass
        vacuously."""
        service = self._service()
        geometry = service._geometry_cache[1]
        heights = sorted(
            c.height for c in walk_height_candidates(geometry, 44.0, 12.0))
        self.assertEqual(
            heights, [self.LOWER_Y, self.UPPER_Y],
            "expected one tile to carry both a lower and an upper surface")

        service.begin(1, Position(4.0, self.LOWER_Y, 12.0))
        field = service._route.flow_field
        self.assertIn(
            ((5, 1), frozenset({1})), field.node_height,
            "the upper terrace never joined the field -- the ramp is broken")
        self.assertIn(
            ((5, 1), frozenset({0})), field.node_height,
            "the lower ground never joined the field")

    def _walk_east_along_the_terrace(self, service):
        """Follow the guide east along the upper terrace until it hands back
        a waypoint that is genuinely on that terrace, and return it."""
        for ix in range(2, 9):
            result = service.next_waypoint(
                Position(ix * TILE_SIZE + 4.0, self.UPPER_Y, 12.0))
            self.assertTrue(result.path_available)
            node = service._route.current_waypoint_node
            if service._route.flow_field.node_height[node] == self.UPPER_Y:
                return node
        self.fail("the guide never aimed at a waypoint on the upper terrace")

    def test_falling_beneath_a_waypoint_does_not_count_as_reaching_it(self):
        service = self._service()
        service.begin(1, Position(4.0, self.LOWER_Y, 12.0))
        service.next_waypoint(Position(20.0, self.UPPER_Y, 12.0))
        upper_waypoint = self._walk_east_along_the_terrace(service)
        upper_position = service._route.flow_field.node_position(upper_waypoint)
        committed = list(service._route.waypoint_sequence)
        cursor = service._route.waypoint_cursor

        # Fall: same XZ as the waypoint, but down on the lower ground. This
        # is inside the capture window, which is precisely why the XZ-only
        # rule credited it as an arrival.
        fallen = Position(upper_position.x, self.LOWER_Y, upper_position.z)
        self.assertLessEqual(
            ((fallen.x - upper_position.x) ** 2
             + (fallen.z - upper_position.z) ** 2) ** 0.5,
            TILE_SIZE * ns_module.WAYPOINT_STABLE_RADIUS_RATIO,
            "fixture no longer lands inside the capture window, so it would "
            "not exercise the defect")

        result = service.next_waypoint(fallen)

        self.assertTrue(result.path_available)
        new_waypoint = service._route.current_waypoint_node
        new_height = service._route.flow_field.node_height[new_waypoint]
        self.assertLessEqual(
            abs(new_height - self.LOWER_Y),
            ns_module.WAYPOINT_CAPTURE_HEIGHT_TOLERANCE,
            f"after falling to y={self.LOWER_Y} the guide is still aiming at "
            f"a waypoint at y={new_height} -- it is steering along a surface "
            f"the player is no longer on")
        if cursor + 1 < len(committed):
            self.assertNotEqual(
                new_waypoint, committed[cursor + 1],
                "the committed sequence advanced as though the waypoint had "
                "been reached")

    def test_after_the_fall_the_guide_leads_back_along_the_players_own_route(self):
        """Not just "a different waypoint" -- the recommitted one has to be a
        real next step of the route the player can actually walk from where
        they now are. Here that means heading WEST along the lower ground
        toward the destination, not east toward the ramp they fell off."""
        service = self._service()
        destination = Position(4.0, self.LOWER_Y, 12.0)
        service.begin(1, destination)
        service.next_waypoint(Position(20.0, self.UPPER_Y, 12.0))
        upper_waypoint = self._walk_east_along_the_terrace(service)
        upper_position = service._route.flow_field.node_position(upper_waypoint)

        fallen = Position(upper_position.x, self.LOWER_Y, upper_position.z)
        result = service.next_waypoint(fallen)

        self.assertLess(
            result.target_position.x, fallen.x,
            "the guide is not pointing toward the destination along the "
            "surface the player is actually standing on")
        route = service.remaining_route(fallen)
        self.assertIsNotNone(route)
        for step in route:
            self.assertLessEqual(
                abs(step.y - self.LOWER_Y),
                ns_module.WAYPOINT_CAPTURE_HEIGHT_TOLERANCE,
                "the remaining route climbs back onto the terrace the player "
                "just fell off")

    def test_a_real_slope_step_still_captures(self):
        """The gate must not break ordinary ramp walking. The steepest real
        same-layer slope step measured in `M3_out` is 7.40 units per tile, so
        a height difference of that order at capture range is legitimate
        terrain, not a fall, and must still advance the waypoint."""
        service = self._service()
        service.begin(1, Position(4.0, self.LOWER_Y, 12.0))
        service.next_waypoint(Position(20.0, self.UPPER_Y, 12.0))
        waypoint = self._walk_east_along_the_terrace(service)
        position = service._route.flow_field.node_position(waypoint)

        # Standing right at the waypoint but 7.4 units below it, as a player
        # part-way up a real slope would be.
        result = service.next_waypoint(
            Position(position.x, position.y - 7.4, position.z))

        self.assertTrue(result.path_available)
        self.assertNotEqual(
            service._route.current_waypoint_node, waypoint,
            "a legitimate slope-height difference blocked the waypoint from "
            "advancing -- the capture tolerance is too tight for real terrain")


if __name__ == "__main__":
    unittest.main()
