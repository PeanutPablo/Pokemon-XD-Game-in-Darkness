import math
import unittest
from pathlib import Path

from battle_narrator.collision_probe import (
    CollisionTriangle,
    WalkTriangle,
    parse_environment_triangles,
    parse_walk_model_triangles,
)
from battle_narrator.npc_beacons import Position
from battle_narrator.pathfinding import (
    HEIGHT_CONTINUITY_TOLERANCE,
    MAX_WAYPOINT_SPAN,
    TILE_SIZE,
    build_room_geometry,
    flow_field_from,
    reconstruct_route,
    resolve_node,
    simplify_route,
    walk_height_candidates,
)

REAL_M3_OUT_CCD = (
    Path(__file__).resolve().parent.parent
    / "_dialogue_extraction" / "collision" / "M3_out.ccd"
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


def transition_tile(ix, iz, tile_size=TILE_SIZE, y=0.0, layer_a=0, layer_b=1):
    """A single walk-model tile whose triangles carry TWO different layer
    nibbles -- an explicit transition, e.g. a ramp joining `layer_a` and
    `layer_b`, matching the real triangle found live at M3_out's own
    climb-start position (layer_a=0, layer_b=1)."""
    x0, z0 = ix * tile_size, iz * tile_size
    x1, z1 = x0 + tile_size, z0 + tile_size
    return [
        WalkTriangle(
            ((x0, y, z0), (x1, y, z0), (x1, y, z1)), (0.0, 1.0, 0.0),
            layer_a, layer_b, 0xFF, 0),
        WalkTriangle(
            ((x0, y, z0), (x1, y, z1), (x0, y, z1)), (0.0, 1.0, 0.0),
            layer_a, layer_b, 0xFF, 0),
    ]


def wall_segment(p0, p1, y0=-10.0, y1=10.0):
    (x0, z0), (x1, z1) = p0, p1
    return [
        CollisionTriangle(
            ((x0, y0, z0), (x1, y0, z1), (x1, y1, z1)), (0.0, 0.0, 1.0), 0, 0),
        CollisionTriangle(
            ((x0, y0, z0), (x1, y1, z1), (x0, y1, z0)), (0.0, 0.0, 1.0), 0, 0),
    ]


def wall_box(x0, x1, z0, z1, y0=-10.0, y1=10.0):
    return (
        wall_segment((x0, z0), (x1, z0), y0, y1)
        + wall_segment((x1, z0), (x1, z1), y0, y1)
        + wall_segment((x1, z1), (x0, z1), y0, y1)
        + wall_segment((x0, z1), (x0, z0), y0, y1)
    )


class ResolveNodeTests(unittest.TestCase):
    def test_position_exactly_on_a_walk_tile_resolves_directly(self):
        geometry = build_room_geometry(walk_rect(0, 5, 0, 5), ())
        tile, layers, height = resolve_node(geometry, Position(20.0, 0.0, 20.0))
        self.assertEqual(tile, (2, 2))
        self.assertEqual(layers, frozenset({0}))
        self.assertEqual(height, 0.0)

    def test_position_with_no_walk_coverage_returns_none(self):
        # No default-walkable fallback anymore -- a position with no walk-
        # model coverage anywhere nearby is a genuine "unmapped" result.
        geometry = build_room_geometry(walk_rect(0, 5, 0, 5), ())
        self.assertIsNone(resolve_node(geometry, Position(1000.0, 3.0, 1000.0)))

    def test_ring_search_finds_nearby_coverage_when_exact_tile_is_empty(self):
        geometry = build_room_geometry(
            walk_rect(0, 5, 0, 5, exclude={(2, 2)}), ())
        tile, layers, height = resolve_node(geometry, Position(20.0, 0.0, 20.0))
        self.assertNotEqual(tile, (2, 2))
        self.assertEqual(layers, frozenset({0}))

    def test_layer_selection_picks_the_candidate_closest_to_query_y(self):
        # Two overlapping same-XZ surfaces on different layers -- resolving
        # a known position must pick by nearest height to the real Y, per
        # GScolsys2WalkGetLayer's own algorithm (Phase 2).
        low = walk_tile(0, 0, y=0.0, layer=0)
        high = walk_tile(0, 0, y=20.0, layer=1)
        geometry = build_room_geometry(low + high, ())
        _, layers_low, height_low = resolve_node(geometry, Position(4.0, 1.0, 4.0))
        self.assertEqual(layers_low, frozenset({0}))
        self.assertAlmostEqual(height_low, 0.0)
        _, layers_high, height_high = resolve_node(geometry, Position(4.0, 19.0, 4.0))
        self.assertEqual(layers_high, frozenset({1}))
        self.assertAlmostEqual(height_high, 20.0)

    def test_walk_height_candidates_reports_multiple_stacked_surfaces(self):
        low = walk_tile(0, 0, y=0.0, layer=0)
        mid = walk_tile(0, 0, y=20.0, layer=1)
        high = walk_tile(0, 0, y=40.0, layer=2)
        geometry = build_room_geometry(low + mid + high, ())
        candidates = walk_height_candidates(geometry, 4.0, 4.0)
        heights = sorted(c.height for c in candidates)
        self.assertEqual(heights, [0.0, 20.0, 40.0])


class LayerConnectivityTests(unittest.TestCase):
    def test_two_layers_with_no_transition_stay_disconnected(self):
        # Overlapping height bands, no shared layer, no transition tile --
        # must NOT be bridged just because the heights happen to be close.
        # This is the exact failure mode the 2026-08-01 rewrite fixes.
        layer0 = walk_rect(-10, 10, -10, 10, y=0.0, layer=0)
        layer1 = walk_rect(-10, 10, -10, 10, y=2.0, layer=1)  # 2 units away, well within old tolerance
        geometry = build_room_geometry(layer0 + layer1, ())
        destination = Position(70.0, 2.0, 70.0)  # lands on layer 1
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        player_tile, player_layers, _ = resolve_node(geometry, Position(-70.0, 0.0, -70.0))
        self.assertEqual(player_layers, frozenset({0}))
        route = reconstruct_route(field, (player_tile, player_layers))
        self.assertIsNone(
            route, "layer 0 and layer 1 were bridged by height proximity alone")

    def test_explicit_transition_connects_two_layers(self):
        layer0 = walk_rect(-10, 0, -2, 2, y=0.0, layer=0)
        ramp = transition_tile(0, 0, y=4.0, layer_a=0, layer_b=1)
        layer1 = walk_rect(1, 10, -2, 2, y=8.0, layer=1)
        geometry = build_room_geometry(layer0 + ramp + layer1, ())
        destination = Position(70.0, 8.0, 4.0)  # layer 1
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        player_tile, player_layers, _ = resolve_node(geometry, Position(-70.0, 0.0, 4.0))
        self.assertEqual(player_layers, frozenset({0}))
        route = reconstruct_route(field, (player_tile, player_layers))
        self.assertIsNotNone(
            route, "failed to route across an explicit transition triangle")
        self.assertTrue(
            any(len(layers) > 1 for _, layers in route),
            "route never passed through the transition node",
        )

    def test_diagonal_corner_cut_is_rejected_when_orthogonal_neighbor_is_missing(self):
        wall = wall_segment((8.0, 8.0), (16.0, 8.0))
        walk = walk_rect(-5, 5, -5, 5)
        geometry = build_room_geometry(walk, wall)
        destination = Position(12.0, 0.0, 12.0)  # tile (1, 1) center
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        dest_layers = frozenset({0})
        self.assertNotEqual(
            field.next_hop.get(((0, 0), dest_layers)), ((1, 1), dest_layers))
        route = reconstruct_route(field, ((0, 0), dest_layers))
        self.assertIsNotNone(route)
        self.assertNotIn(((1, 0), dest_layers), route)

    def test_wall_blocks_a_valid_walk_surface_underneath_it(self):
        # A real walk surface exists on both sides, but a wall crosses the
        # tile boundary between them -- the hit model must still block
        # movement even though the walk model alone would allow it.
        walk = walk_rect(-5, 5, -5, 5)
        wall = wall_segment((0.0, -1000.0), (0.0, 1000.0))
        geometry = build_room_geometry(walk, wall)
        destination = Position(20.0, 0.0, 0.0)
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        player_tile, layers, _ = resolve_node(geometry, Position(-20.0, 0.0, 0.0))
        route = reconstruct_route(field, (player_tile, layers))
        self.assertIsNone(route)

    def test_height_within_tolerance_still_requires_a_shared_layer(self):
        # Same layer, small height step (a stair) -- must connect using the
        # defensive tolerance, but only because the layer already matches.
        low = walk_rect(0, 10, 0, 5, y=0.0, layer=0)
        step = walk_rect(10, 20, 0, 5, y=HEIGHT_CONTINUITY_TOLERANCE - 1.0, layer=0)
        geometry = build_room_geometry(low + step, ())
        destination = Position(140.0, HEIGHT_CONTINUITY_TOLERANCE - 1.0, 20.0)
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        player_tile, layers, _ = resolve_node(geometry, Position(20.0, 0.0, 20.0))
        route = reconstruct_route(field, (player_tile, layers))
        self.assertIsNotNone(route)

    def test_height_beyond_tolerance_on_the_same_layer_is_rejected(self):
        low = walk_rect(0, 10, 0, 5, y=0.0, layer=0)
        high = walk_rect(10, 20, 0, 5, y=HEIGHT_CONTINUITY_TOLERANCE + 4.0, layer=0)
        geometry = build_room_geometry(low + high, ())
        destination = Position(140.0, HEIGHT_CONTINUITY_TOLERANCE + 4.0, 20.0)
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        player_tile, layers, _ = resolve_node(geometry, Position(20.0, 0.0, 20.0))
        route = reconstruct_route(field, (player_tile, layers))
        self.assertIsNone(route)


class FlowFieldTests(unittest.TestCase):
    def test_open_floor_produces_a_route_to_the_destination(self):
        geometry = build_room_geometry(walk_rect(-10, 10, -10, 10), ())
        destination = Position(70.0, 0.0, 70.0)
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        player_tile, layers, _ = resolve_node(geometry, Position(-70.0, 0.0, -70.0))
        route = reconstruct_route(field, (player_tile, layers))
        self.assertIsNotNone(route)
        self.assertEqual(route[0], (player_tile, layers))
        self.assertEqual(route[-1], field.destination_node)

    def test_a_doorway_offset_from_tile_row_centres_is_found(self):
        # Live-caught regression, re-derived 2026-08-04 (late). A wall
        # spanning x=8 blocks east-west crossing between tile columns ix=0
        # and ix=1, open only for a doorway at z:[2,13) whose centre (7.5)
        # falls BETWEEN two tile-row centres (z=4 and z=12, 8 units apart),
        # so a single centre-to-centre line test walks past it on both
        # sides. Node relocation (`_best_clearance_point`) must find it.
        #
        # The gap is 11 units because that is what the REAL M3_out doorway
        # this regression came from measures. The original fixture used 2
        # units, from a doc note reading "open at z=38-39, blocked at z=40
        # through 58" -- but that was integer sampling that never probed
        # below 38. Measured at 0.25-unit resolution the real opening runs
        # z=[30.00,41.00], i.e. 11.25 units. A radius-3.5 player needs 7.0
        # to fit at all, so the 2-unit version was asserting the router
        # should pass through a doorway the engine would not let the player
        # into -- see test_a_gap_narrower_than_the_player_is_refused.
        walk = walk_rect(-5, 5, -5, 5)
        wall = (
            wall_segment((8.0, -1000.0), (8.0, 2.0))
            + wall_segment((8.0, 13.0), (8.0, 1000.0))
        )
        geometry = build_room_geometry(walk, wall)
        destination = Position(20.0, 0.0, 0.0)
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        player_tile, layers, _ = resolve_node(geometry, Position(-20.0, 0.0, 0.0))
        route = reconstruct_route(field, (player_tile, layers))
        self.assertIsNotNone(
            route, "failed to route through a real doorway offset from the "
                   "tile-row centres")

    def test_a_gap_narrower_than_the_player_is_refused(self):
        # The complement, and the reason the permissive five-line test had
        # to go: a 2-unit gap cannot admit a player whose collision ball has
        # radius 3.5 (they need 7.0). Routing through it is not a near miss,
        # it is guidance into a wall.
        walk = walk_rect(-5, 5, -5, 5)
        wall = (
            wall_segment((8.0, -1000.0), (8.0, 6.0))
            + wall_segment((8.0, 8.0), (8.0, 1000.0))
        )
        geometry = build_room_geometry(walk, wall)
        field = flow_field_from(geometry, Position(20.0, 0.0, 0.0))
        self.assertIsNotNone(field)
        player_tile, layers, _ = resolve_node(geometry, Position(-20.0, 0.0, 0.0))
        self.assertIsNone(
            reconstruct_route(field, (player_tile, layers)),
            "routed through a gap the player physically cannot fit through")

    def test_fully_solid_wall_with_no_gap_still_blocks(self):
        walk = walk_rect(-5, 5, -5, 5)
        wall = wall_segment((8.0, -1000.0), (8.0, 1000.0))
        geometry = build_room_geometry(walk, wall)
        destination = Position(20.0, 0.0, 0.0)
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        player_tile, layers, _ = resolve_node(geometry, Position(-20.0, 0.0, 0.0))
        route = reconstruct_route(field, (player_tile, layers))
        self.assertIsNone(route)

    def test_wall_forces_a_detour_around_a_gap(self):
        walk = walk_rect(-10, 10, -10, 10)
        wall = wall_segment((-300.0, 0.0), (0.0, 0.0))
        geometry = build_room_geometry(walk, wall)
        destination = Position(-70.0, 0.0, 70.0)
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        player_tile, layers, _ = resolve_node(geometry, Position(-70.0, 0.0, -70.0))
        route = reconstruct_route(field, (player_tile, layers))
        self.assertIsNotNone(route)
        self.assertTrue(
            any(tile[0] >= 0 for tile, _ in route),
            "route never crosses to the open (x>=0) side of the wall -- "
            "a straight-line-blind router would never need to",
        )

    def test_fully_enclosed_destination_has_no_route(self):
        walk = walk_rect(-30, 30, -30, 30)
        box = wall_box(100.0, 124.0, 100.0, 124.0)
        geometry = build_room_geometry(walk, box)
        destination = Position(112.0, 0.0, 112.0)  # box center
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        player_tile, layers, _ = resolve_node(geometry, Position(0.0, 0.0, 0.0))
        route = reconstruct_route(field, (player_tile, layers))
        self.assertIsNone(route)

    def test_narrow_corridor_connects_two_rooms(self):
        room_a = walk_rect(0, 5, 0, 5)
        room_b = walk_rect(0, 5, 10, 15)
        corridor = walk_rect(2, 3, 5, 10)
        geometry = build_room_geometry(room_a + room_b + corridor, ())
        destination = Position(20.0, 0.0, 100.0)
        field = flow_field_from(geometry, destination)
        self.assertIsNotNone(field)
        player_tile, layers, _ = resolve_node(geometry, Position(20.0, 0.0, 20.0))
        route = reconstruct_route(field, (player_tile, layers))
        self.assertIsNotNone(route)
        self.assertTrue(
            all(tile[0] == 2 for tile, _ in route if 5 <= tile[1] < 10),
            "route did not thread through the single-tile-wide corridor",
        )

    def test_max_tiles_bound_aborts_oversized_search(self):
        geometry = build_room_geometry(walk_rect(-10, 10, -10, 10), ())
        destination = Position(0.0, 0.0, 0.0)
        field = flow_field_from(geometry, destination, max_tiles=5)
        self.assertIsNone(field)

    def test_destination_with_no_walk_model_coverage_fails_to_build(self):
        # No walk model at all (e.g. one of the 10 rooms confirmed to have
        # none) -- must fail honestly, not silently invent a floor.
        geometry = build_room_geometry((), wall_box(-10.0, 10.0, -10.0, 10.0))
        destination = Position(0.0, 0.0, 0.0)
        field = flow_field_from(geometry, destination)
        self.assertIsNone(field)

    def test_malformed_walk_model_pointer_raises_during_parsing(self):
        # Not a pathfinding-layer test per se, but confirms the parser
        # itself fails loudly on a corrupt slot rather than silently
        # returning partial/wrong geometry -- see collision_probe.py.
        from battle_narrator.collision_probe import parse_walk_model_triangles
        # One entry (0x40 bytes) whose +0x24 slot points at an offset well
        # past the end of the (tiny) file -- must raise, not silently
        # return an empty/partial triangle list.
        header = (0x08).to_bytes(4, "big") + (1).to_bytes(4, "big")
        entry = bytearray(0x40)
        entry[0x24:0x28] = (0xFFFF).to_bytes(4, "big")
        with self.assertRaises(ValueError):
            parse_walk_model_triangles(header + bytes(entry))


class SimplifyRouteTests(unittest.TestCase):
    """Route simplification, added 2026-08-02 after the project owner
    reported "a lot of waypoints cramped in one location, so a lot, if not
    most, seem redundant." """

    def _node(self, ix, iz, layer=0):
        return ((ix, iz), frozenset({layer}))

    def test_a_straight_run_collapses_to_its_endpoints(self):
        nodes = [self._node(i, 0) for i in range(4)]
        self.assertEqual(
            simplify_route(nodes, max_span=None),
            [self._node(0, 0), self._node(3, 0)])

    def test_a_turn_is_always_kept(self):
        nodes = [self._node(0, 0), self._node(1, 0), self._node(2, 0),
                 self._node(2, 1), self._node(2, 2)]
        simplified = simplify_route(nodes, max_span=None)
        self.assertIn(self._node(2, 0), simplified,
                      "the corner node was dropped")
        self.assertEqual(simplified[0], nodes[0])
        self.assertEqual(simplified[-1], nodes[-1])

    def test_a_layer_change_is_kept_even_when_geometrically_collinear(self):
        nodes = [self._node(0, 0), self._node(1, 0),
                 ((2, 0), frozenset({0, 1})),   # transition, straight through
                 self._node(3, 0, layer=1), self._node(4, 0, layer=1)]
        simplified = simplify_route(nodes, max_span=None)
        self.assertIn(((2, 0), frozenset({0, 1})), simplified,
                      "a layer transition was collapsed away")

    def test_diagonal_runs_also_collapse(self):
        nodes = [self._node(i, i) for i in range(5)]
        self.assertEqual(
            simplify_route(nodes, max_span=None),
            [self._node(0, 0), self._node(4, 4)])

    def test_short_routes_pass_through_untouched(self):
        for nodes in ([], [self._node(0, 0)],
                      [self._node(0, 0), self._node(1, 0)]):
            self.assertEqual(simplify_route(nodes), nodes)
        self.assertIsNone(simplify_route(None))

    def test_max_span_emits_periodic_checkpoints_on_a_long_straight_run(self):
        # Without a cap a long straight route collapses to a single distant
        # waypoint, which would silence the waypoint-reached cue and leave
        # stall detection measuring against a very far target.
        nodes = [self._node(i, 0) for i in range(40)]
        uncapped = simplify_route(nodes, max_span=None)
        capped = simplify_route(nodes, max_span=MAX_WAYPOINT_SPAN)
        self.assertEqual(len(uncapped), 2)
        self.assertGreater(len(capped), 2)
        # No gap between consecutive kept nodes may exceed the cap.
        for (ax, az), (bx, bz) in zip(
                [n[0] for n in capped], [n[0] for n in capped[1:]]):
            span = math.dist((ax, az), (bx, bz)) * TILE_SIZE
            self.assertLessEqual(span, MAX_WAYPOINT_SPAN + TILE_SIZE)

    def test_waypoint_span_scales_with_route_length(self):
        from battle_narrator.pathfinding import (
            WAYPOINT_SPAN_MAX, WAYPOINT_SPAN_MIN, WAYPOINT_SPAN_TARGET_COUNT,
            waypoint_span_for_route,
        )
        # A fixed span gave wildly different waypoint density across rooms
        # (measured: room diagonals 84 -> 2621 units, a 31x spread).
        short = waypoint_span_for_route(40.0)
        medium = waypoint_span_for_route(260.0)
        huge = waypoint_span_for_route(2600.0)
        self.assertEqual(short, WAYPOINT_SPAN_MIN, "short routes must clamp")
        self.assertEqual(huge, WAYPOINT_SPAN_MAX, "long routes must clamp")
        self.assertAlmostEqual(medium, 260.0 / WAYPOINT_SPAN_TARGET_COUNT)
        self.assertLess(short, medium)
        self.assertLess(medium, huge)

        # Degenerate inputs must not produce a zero/negative span, which
        # would make simplify_route emit a waypoint at every single node.
        for bad in (0.0, -5.0, None):
            self.assertEqual(waypoint_span_for_route(bad), WAYPOINT_SPAN_MIN)

    def test_scaled_span_keeps_waypoint_count_roughly_constant(self):
        from battle_narrator.pathfinding import waypoint_span_for_route
        for tiles in (10, 40, 120):
            nodes = [self._node(i, 0) for i in range(tiles)]
            length = (tiles - 1) * TILE_SIZE
            simplified = simplify_route(
                nodes, max_span=waypoint_span_for_route(length))
            # Straight run, so count is driven purely by the span. Should
            # stay in a narrow band rather than growing with route length.
            self.assertGreaterEqual(len(simplified), 2)
            self.assertLessEqual(
                len(simplified), 14,
                f"a {tiles}-tile straight route produced {len(simplified)} "
                f"waypoints -- spacing is not scaling with length")

    def test_simplification_only_ever_drops_nodes_never_invents_them(self):
        nodes = [self._node(0, 0), self._node(1, 0), self._node(2, 0),
                 self._node(2, 1), self._node(3, 1)]
        simplified = simplify_route(nodes)
        self.assertTrue(set(simplified).issubset(set(nodes)))
        self.assertEqual(simplified[0], nodes[0])
        self.assertEqual(simplified[-1], nodes[-1])


class RealM3OutFixtureTests(unittest.TestCase):
    """Captured live 2026-07-31/2026-08-01: exact positions and CCD data
    from the terraced-cliff route that originally exposed this project's
    floor-parsing bug. Verifies the walk-model companion queries against
    real recorded live values, and reproduces the actual failure as an
    automated regression."""

    @classmethod
    def setUpClass(cls):
        if not REAL_M3_OUT_CCD.is_file():
            raise unittest.SkipTest(f"real fixture not found: {REAL_M3_OUT_CCD}")
        data = REAL_M3_OUT_CCD.read_bytes()
        cls.walk_triangles = parse_walk_model_triangles(data)
        cls.wall_triangles = parse_environment_triangles(data)
        cls.geometry = build_room_geometry(cls.walk_triangles, cls.wall_triangles)

    # (label, x, y, z) -- verbatim from the live watcher logs.
    LIVE_POSITIONS = [
        ("guide start (ground)", -127.73, -0.02, 171.41),
        ("climb start (0->1 transition)", -107.34, -0.03, 116.40),
        ("mid-climb", -107.47, 16.36, 95.51),
        ("plateau top", -101.89, 40.00, 61.67),
        ("stuck-at-wall spot", -50.95, 40.00, 49.03),
    ]

    def test_walk_model_has_far_more_floor_than_the_old_wall_slot(self):
        upward = [t for t in self.walk_triangles if t.normal[1] >= 0.5]
        self.assertGreater(len(upward), 500)

    def test_resolved_height_matches_live_recorded_position_within_tolerance(self):
        for label, x, y, z in self.LIVE_POSITIONS:
            with self.subTest(label=label):
                result = resolve_node(self.geometry, Position(x, y, z))
                self.assertIsNotNone(result, f"{label}: no walk coverage resolved")
                _, _, height = result
                self.assertAlmostEqual(
                    height, y, delta=0.02,
                    msg=f"{label}: resolved height {height} vs real Y {y}")

    def test_climb_start_resolves_to_the_0_to_1_transition(self):
        _, layers, _ = resolve_node(
            self.geometry, Position(-107.34, -0.03, 116.40))
        self.assertEqual(layers, frozenset({0, 1}))

    def test_ground_and_plateau_resolve_to_different_layers(self):
        _, ground_layers, _ = resolve_node(
            self.geometry, Position(-127.73, -0.02, 171.41))
        _, plateau_layers, _ = resolve_node(
            self.geometry, Position(-101.89, 40.00, 61.67))
        self.assertNotEqual(ground_layers, plateau_layers)

    def test_simplification_removes_the_measured_real_world_redundancy(self):
        """The project owner reported (2026-08-02) that waypoints were
        cramped and mostly redundant. Measured on this exact real route
        before simplification: 5 nodes, path length 32.0 against a
        straight-line 32.0 (1.00x), with 3 of 3 interior waypoints exactly
        collinear. This pins that simplification actually removes that
        redundancy on the real data, not just on synthetic fixtures."""
        destination = Position(-127.94, 16.12, 202.18)   # worldmap exit
        field = flow_field_from(self.geometry, destination)
        self.assertIsNotNone(field)
        start = resolve_node(self.geometry, Position(-127.73, -0.02, 171.41))
        self.assertIsNotNone(start)
        chain = reconstruct_route(field, (start[0], start[1]))
        self.assertIsNotNone(chain)

        simplified = simplify_route(chain)
        self.assertLess(
            len(simplified), len(chain),
            f"simplification removed nothing from a real route of "
            f"{len(chain)} nodes")

        # Every retained node must be one of the originals -- simplification
        # may only ever DROP nodes, never invent a position.
        self.assertTrue(set(simplified).issubset(set(chain)))
        self.assertEqual(simplified[0], chain[0])
        self.assertEqual(simplified[-1], chain[-1])

        # Every dropped node must be exactly collinear with the retained
        # pair that now spans it, so the straight line between consecutive
        # waypoints still passes through nothing but verified hops.
        indices = [chain.index(node) for node in simplified]
        for start_i, end_i in zip(indices, indices[1:]):
            (ax, az), _ = chain[start_i]
            (cx, cz), _ = chain[end_i]
            for (bx, bz), _ in chain[start_i + 1:end_i]:
                cross = (bx - ax) * (cz - az) - (bz - az) * (cx - ax)
                self.assertEqual(
                    cross, 0,
                    f"dropped node ({bx},{bz}) is not collinear with the "
                    f"waypoints now spanning it")

    def test_regression_routes_up_the_real_terrace_instead_of_failing(self):
        """The most important regression case (project owner's own framing):
        recreate the exact M3_out failure. The router must resolve floor
        beneath every captured position, preserve the ramp's 0->1
        transition, and route from ground level up onto the plateau instead
        of failing or stalling at a false wall waypoint."""
        destination = Position(-101.89, 40.00, 61.67)  # plateau top
        field = flow_field_from(self.geometry, destination)
        self.assertIsNotNone(
            field, "flow field failed to build against the real walk model")

        player_result = resolve_node(self.geometry, Position(-127.73, -0.02, 171.41))
        self.assertIsNotNone(player_result)
        player_tile, player_layers, _ = player_result
        route = reconstruct_route(field, (player_tile, player_layers))
        self.assertIsNotNone(
            route,
            "no route found from real ground level to the real plateau -- "
            "this is the exact live failure this rewrite must fix",
        )
        self.assertTrue(
            any(len(layers) > 1 for _, layers in route),
            "route never crossed a real layer transition (the ramp)",
        )
        # Every node height along the route must come from a real
        # walk-model surface -- reconstruct_route only ever returns nodes
        # the flood-fill actually resolved, so this also confirms nothing
        # in the route silently fell back to an invented/default height.
        for tile, layers in route:
            self.assertIn((tile, layers), field.node_height)


REAL_M6_OUT_CCD = (
    Path(__file__).resolve().parent.parent
    / "_dialogue_extraction" / "collision" / "M6_out.ccd"
)


class RealM6OutSearchBoundTests(unittest.TestCase):
    """Gateon Port is the largest room in the game: a full-game survey
    measured its flood at 24555 reachable nodes, against a second-largest of
    14900 (D3_out). MAX_TILES was 20000, so every route request in this one
    room aborted and fell back to direct guidance -- the live "No walkable
    path found" the project owner hit. Guards the bound against being
    lowered back under what the real geometry needs."""

    @classmethod
    def setUpClass(cls):
        if not REAL_M6_OUT_CCD.exists():
            raise unittest.SkipTest(f"missing fixture {REAL_M6_OUT_CCD}")
        raw = REAL_M6_OUT_CCD.read_bytes()
        cls.geometry = build_room_geometry(
            parse_walk_model_triangles(raw), parse_environment_triangles(raw))

    def test_the_largest_room_routes_under_the_shipped_bound(self):
        # A real position sampled live in Gateon Port this session.
        field = flow_field_from(self.geometry, Position(43.8, 0.0, -304.7))
        self.assertIsNotNone(
            field,
            "the game's largest room must route with the shipped MAX_TILES; "
            "if this fails the bound is under the real geometry again",
        )
        self.assertGreater(
            len(field.node_height), 20000,
            "this room really does exceed the old 20000 bound -- if it no "
            "longer does, this test has stopped covering the regression",
        )

    def test_bound_still_aborts_a_search_that_exceeds_it(self):
        """The cap must still do its job; raising it must not disable it."""
        self.assertIsNone(
            flow_field_from(self.geometry, Position(43.8, 0.0, -304.7),
                            max_tiles=100))


if __name__ == "__main__":
    unittest.main()
