"""One passability test, every room (2026-08-04, late).

Replaces the two-authority slice of the same day. That version gave a room
the swept-circle test only when its walk model had <= 8 triangles, and left
everything else on a permissive five-sample line test. Both halves were
wrong: the classifier misfired on real rooms (`D1_labo_B2` cleared it by six
triangles and got the permissive test over a bare floor plane with 416
structural triangles in the hit model), and the measurement that justified
sparing outdoor rooms measured tile-centre clearance rather than player
positions. See NAVIGATION_AUDIT_2026-08-04.md 2.

The regression bar that replaces "rich rooms are untouched by construction"
is stronger and is asserted below: `M3_out`'s live-proven terrace route must
still build and link WITH the swept test applied to it.
"""
import math
import unittest
from pathlib import Path
from types import SimpleNamespace

from battle_narrator import pathfinding as pf
from battle_narrator.collision_probe import (
    CollisionTriangle, WalkTriangle, parse_environment_triangles,
    parse_walk_model_triangles,
)
from battle_narrator.npc_beacons import Position
from battle_narrator.pathfinding import (
    DEFAULT_COLLISION_RADIUS,
    build_room_geometry,
    diagnose_unreachable,
    flow_field_from,
    flow_field_toward,
    reconstruct_route,
    resolve_node,
)

COLLISION = (Path(__file__).resolve().parents[1]
             / "_dialogue_extraction" / "collision")


def walk_quad(x0, x1, z0, z1, y=0.0, layer=0):
    """One flat floor as two triangles -- exactly what 38 of the game's
    rooms actually ship."""
    return [
        WalkTriangle(((x0, y, z0), (x1, y, z0), (x1, y, z1)),
                     (0.0, 1.0, 0.0), layer, layer, 0xFF, 0),
        WalkTriangle(((x0, y, z0), (x1, y, z1), (x0, y, z1)),
                     (0.0, 1.0, 0.0), layer, layer, 0xFF, 0),
    ]


def wall(p0, p1, y0=-2.0, y1=10.0):
    (x0, z0), (x1, z1) = p0, p1
    return [
        CollisionTriangle(((x0, y0, z0), (x1, y0, z1), (x1, y1, z1)),
                          (0.0, 0.0, 1.0), 0, 0),
        CollisionTriangle(((x0, y0, z0), (x1, y1, z1), (x0, y1, z0)),
                          (0.0, 0.0, 1.0), 0, 0),
    ]


class GeometryTests(unittest.TestCase):
    def test_geometry_records_radius_and_room(self):
        geometry = build_room_geometry(walk_quad(0, 100, 0, 100), (), floor_id=7)
        self.assertEqual(geometry.collision_radius, DEFAULT_COLLISION_RADIUS)
        self.assertEqual(geometry.floor_id, 7)

    def test_there_is_no_per_room_passability_choice_left(self):
        """The classifier and its override map are gone on purpose. A room
        that needs different treatment is evidence the single test is wrong,
        and should be fixed there rather than exempted here."""
        for name in ("PassabilityAuthority", "classify_authority",
                     "DEGENERATE_WALK_MODEL_MAX_TRIANGLES",
                     "ROOM_AUTHORITY_OVERRIDES", "_segment_blocked",
                     "GAP_SAMPLE_OFFSETS"):
            self.assertFalse(hasattr(pf, name), f"{name} is still present")


class DegenerateRoomRoutingTests(unittest.TestCase):
    def _room(self, walls, radius=DEFAULT_COLLISION_RADIUS):
        return build_room_geometry(
            walk_quad(-8, 120, -8, 120), walls, floor_id=1,
            collision_radius=radius)

    def test_furniture_is_not_walked_through(self):
        """A counter spanning the room must split it. Under the old
        permissive rule one clear sample line opened the edge; a swept
        circle at the player's own width cannot squeeze past."""
        barrier = wall((-8.0, 56.0), (120.0, 56.0))
        geometry = self._room(barrier)
        field = flow_field_from(geometry, Position(56.0, 0.0, 100.0))
        self.assertIsNotNone(field)
        south = resolve_node(geometry, Position(56.0, 0.0, 16.0))
        self.assertIsNotNone(south)
        self.assertNotIn(
            (south[0], south[1]), field.node_height,
            "the flood fill crossed a solid barrier that is wider than the "
            "player -- the swept test is not gating this room")

    def test_a_gap_wider_than_the_player_stays_open(self):
        """The same barrier with a genuine doorway must remain passable --
        the test has to reject furniture without sealing real openings."""
        left = wall((-8.0, 56.0), (40.0, 56.0))
        right = wall((72.0, 56.0), (120.0, 56.0))
        geometry = self._room(left + right)
        field = flow_field_from(geometry, Position(56.0, 0.0, 100.0))
        self.assertIsNotNone(field)
        south = resolve_node(geometry, Position(56.0, 0.0, 16.0))
        self.assertIn(
            (south[0], south[1]), field.node_height,
            "a 32-unit doorway was sealed for a player of radius 4")

    def test_radius_is_configurable(self):
        """A narrow gap passable by a small mover must be impassable for a
        wide one -- the radius genuinely drives the decision.

        The gap is centred on a TILE CENTRE (x=52) on purpose. A first
        version put it on a tile BOUNDARY, where both neighbouring centres
        land exactly on a wall endpoint and the gap is unusable at any
        radius. That is a real property of testing an 8-unit grid with a
        4-unit radius, not a fixture quirk -- it is the `grid_alignment`
        cause `diagnose_unreachable` exists to report, and the reason
        resolution is flagged as unfinished business in this slice."""
        left = wall((-8.0, 56.0), (49.0, 56.0))
        right = wall((55.0, 56.0), (120.0, 56.0))
        start, destination = Position(56.0, 0.0, 16.0), Position(56.0, 0.0, 100.0)
        for radius, expected in ((1.0, True), (DEFAULT_COLLISION_RADIUS, False)):
            geometry = self._room(left + right, radius=radius)
            field = flow_field_from(geometry, destination)
            seed = resolve_node(geometry, start)
            linked = field is not None and (seed[0], seed[1]) in field.node_height
            self.assertEqual(
                linked, expected,
                f"an 8-unit gap with collision radius {radius} should "
                f"{'pass' if expected else 'block'}")

    def test_height_layers_are_not_flattened(self):
        """An obstacle far above the floor must not block the floor. The
        rich-model path deliberately ignores height; the swept path must
        not inherit that."""
        overhead = wall((-8.0, 56.0), (120.0, 56.0), y0=200.0, y1=220.0)
        geometry = self._room(overhead)
        field = flow_field_from(geometry, Position(56.0, 0.0, 100.0))
        seed = resolve_node(geometry, Position(56.0, 0.0, 16.0))
        self.assertIn(
            (seed[0], seed[1]), field.node_height,
            "geometry 200 units overhead blocked a ground-level route -- "
            "another height layer is contaminating this obstacle set")

    def test_floor_support_is_still_required(self):
        """The hit model gains authority over obstacles, never over whether
        there is ground."""
        geometry = self._room(())
        self.assertIsNone(
            flow_field_from(geometry, Position(5000.0, 0.0, 5000.0)),
            "routed to a destination with no floor under it")

    def test_build_stats_are_reported(self):
        geometry = self._room(wall((-8.0, 56.0), (60.0, 56.0)))
        field = flow_field_from(geometry, Position(56.0, 0.0, 100.0))
        stats = field.stats
        for key in ("passability", "collision_radius", "walk_triangles",
                    "wall_triangles", "rejected_edges", "nodes",
                    "target_projected"):
            self.assertIn(key, stats)
        # Doubles as the build's version stamp in the log -- see
        # NAVIGATION_AUDIT_2026-08-04.md 0.
        self.assertEqual(stats["passability"], "swept")
        self.assertGreater(stats["rejected_edges"], 0)


class UnreachableDiagnosisTests(unittest.TestCase):
    def test_target_projection_failure_is_named(self):
        geometry = build_room_geometry(walk_quad(0, 100, 0, 100), (), floor_id=1)
        cause, _ = diagnose_unreachable(
            geometry, Position(50.0, 0.0, 50.0), Position(9000.0, 0.0, 9000.0))
        self.assertEqual(cause, "target_projection")

    def test_radius_clearance_failure_is_named(self):
        """A destination in a nook too tight for the player's own width.

        Sized so no point in the tile clears the radius -- a wider box would
        be an enclosure the player could stand inside, which is a
        connectivity failure, not a clearance one, and must not be reported
        as clearance."""
        box = (wall((49.0, 49.0), (55.0, 49.0)) + wall((49.0, 55.0), (55.0, 55.0))
               + wall((49.0, 49.0), (49.0, 55.0)) + wall((55.0, 49.0), (55.0, 55.0)))
        geometry = build_room_geometry(
            walk_quad(0, 100, 0, 100), box, floor_id=1)
        cause, _ = diagnose_unreachable(
            geometry, Position(10.0, 0.0, 10.0), Position(50.0, 0.0, 50.0))
        self.assertIn(cause, ("radius_clearance", "grid_alignment"))

    def test_cross_level_is_reported_as_height_not_silently_absorbed(self):
        walk = walk_quad(0, 100, 0, 100, y=0.0, layer=0)
        walk += walk_quad(0, 100, 0, 100, y=200.0, layer=0)
        geometry = build_room_geometry(walk, (), floor_id=1)
        cause, _ = diagnose_unreachable(
            geometry, Position(10.0, 0.0, 10.0), Position(50.0, 200.0, 50.0))
        self.assertEqual(cause, "height_layer")


@unittest.skipUnless((COLLISION / "M3_out.ccd").is_file(),
                     "extracted .ccd data not present")
class RealRoomTests(unittest.TestCase):
    """Against the project owner's own extracted room data."""

    def _geometry(self, room):
        data = (COLLISION / f"{room}.ccd").read_bytes()
        return build_room_geometry(
            parse_walk_model_triangles(data),
            parse_environment_triangles(data),
            floor_id=None)

    def test_m3_out_terrace_route_survives_the_swept_test(self):
        """**The regression bar for this whole change.** The live-proven
        outdoor route (AUDIO GUIDE Arrived., 2026-08-02) must still build and
        still link now that the swept test applies to it too.

        This replaces `test_swept_test_is_never_used_in_a_rich_room`, which
        asserted the defect: it required the swept predicate to be
        unreachable here, which is precisely what let the flood fill route
        through walls in every room the classifier misjudged."""
        geometry = self._geometry("M3_out")
        # The REAL endpoints of the live-proven journey, from the watcher log
        # of 2026-08-04 00:10 -- plateau top down to the ground below. The
        # previous fixture used invented coordinates, and one of them
        # (-3.00, -0.02, 8.00) sits 3.385 units from a wall: closer than the
        # hero's own 3.5 collision radius, so it is not a place the engine
        # would ever have let the player stand. Measured live positions are
        # strictly better evidence than coordinates chosen to make a test go
        # green.
        start = Position(83.09, 40.00, 91.65)
        field = flow_field_toward(
            geometry, Position(19.23, -5.04, 98.97), start)
        self.assertIsNotNone(field)
        seed = resolve_node(geometry, start)
        node = (seed[0], seed[1])
        self.assertIn(node, field.node_height)
        route = reconstruct_route(field, node)
        self.assertIsNotNone(route)
        self.assertGreater(len(route), 10)

    def test_the_swept_test_really_is_used_outdoors(self):
        """The complement of the bar above: confirm the route survives
        BECAUSE the test passes it, not because the test is skipped."""
        geometry = self._geometry("M3_out")
        calls = []
        original = pf._swept_circle_blocked

        def spy(*args, **kwargs):
            calls.append(args)
            return original(*args, **kwargs)

        pf._swept_circle_blocked = spy
        try:
            flow_field_from(geometry, Position(-60.0, 40.0, 120.0))
        finally:
            pf._swept_circle_blocked = original
        self.assertTrue(
            calls, "the swept-circle test was never invoked outdoors")

    def test_every_logged_m3_out_position_clears_the_radius(self):
        """Player-position evidence from the outdoor room, which is what
        WORLD_NAVIGATION_ARCHITECTURE.md 6g never had. Eight real logged
        positions from the U-turn session; the closest sits 3.498 units from
        a wall. If "hugging geometry is normal outdoors" were true, some of
        these would be well inside the radius. None is."""
        geometry = self._geometry("M3_out")
        logged = (
            (-46.87, 120.0, -120.80), (-59.00, 120.0, -121.78),
            (-66.11, 120.0, -119.95), (-48.91, 120.0, -121.02),
            (-56.09, 120.0, -121.78), (-70.92, 120.0, -119.08),
            (-46.66, 120.0, -120.78), (-58.11, 120.0, -121.81),
        )
        for x, y, z in logged:
            with self.subTest(position=(x, z)):
                closest = min(
                    pf._point_segment_distance(
                        x, z, *pf._triangle_longest_edge_xz(triangle))
                    for triangle in geometry.wall_triangles
                    if pf._wall_spans_height(triangle, y)
                )
                self.assertGreaterEqual(closest, 3.49)


if __name__ == "__main__":
    unittest.main()


class DestinationProjectionTests(unittest.TestCase):
    """Live-caught 2026-08-04: every route in `D1_garage_1F` failed with
    `cause=target_projection` before passability was ever consulted. Two of
    that room's three interactable regions sit at z=-100.5 and z=-119.1
    against a floor quad ending at z=-67.7, and 47-48 units below it -- the
    stairwell to the basement, which the flat walk model does not cover."""

    def test_a_destination_off_the_floor_on_THIS_level_still_projects(self):
        """Lateral projection is for a destination placed off the walkable
        surface of the level it belongs to -- a warp in a wall recess, a PC
        on a ledge. That case must keep working."""
        from battle_narrator.pathfinding import resolve_destination_node
        geometry = build_room_geometry(
            walk_quad(0.0, 100.0, 0.0, 100.0), (), floor_id=1)
        # 30 units beyond the floor's edge, but on this floor's own level.
        off_floor = Position(50.0, 0.0, 130.0)
        self.assertIsNone(resolve_node(geometry, off_floor))
        projected = resolve_destination_node(geometry, off_floor)
        self.assertIsNotNone(projected, "no floor found near the destination")
        self.assertGreater(projected[3], 0.0, "offset should be non-zero")
        field = flow_field_from(geometry, off_floor)
        self.assertIsNotNone(field, "route still failed to build")
        seed = resolve_node(geometry, Position(50.0, 0.0, 20.0))
        self.assertIn((seed[0], seed[1]), field.node_height)

    def test_a_destination_on_ANOTHER_LEVEL_is_never_projected_onto_this_one(self):
        """The correction to the above, 2026-08-04 (late). Lateral
        projection ignored height entirely, so `D1_garage_1F`'s basement
        warp (y=-48.24) was projected 59 units sideways onto the ground
        floor at y=0.0 and the route seeded in a connected component the
        player could not reach -- a six-node route pointing into the south
        wall while the real target was down a stairwell. A destination on
        another storey is the cross-level case, not an off-surface
        placement, and must be refused rather than flattened onto this
        level."""
        from battle_narrator.pathfinding import (
            resolve_destination_node, DESTINATION_PROJECTION_MAX_VERTICAL_GAP)
        geometry = build_room_geometry(
            walk_quad(0.0, 100.0, 0.0, 100.0), (), floor_id=1)
        # The real shape of the garage warp: beyond the floor's edge AND far
        # below it.
        another_level = Position(50.0, -45.0, 130.0)
        self.assertIsNone(resolve_node(geometry, another_level))
        self.assertIsNone(
            resolve_destination_node(geometry, another_level),
            "projected a destination that is on a different storey")
        # ...and the guard is about the VERTICAL gap specifically: the same
        # XZ at a compatible height still projects.
        gap = DESTINATION_PROJECTION_MAX_VERTICAL_GAP
        self.assertIsNotNone(
            resolve_destination_node(
                geometry, Position(50.0, -gap + 0.5, 130.0)),
            "refused a destination within the same level's height band")

    def test_a_cross_level_target_off_this_room_s_floor_is_refused(self):
        """**Inverted 2026-08-12.** This used to require guidance to the
        reachable point nearest a stairwell 45 units below the floor, on the
        grounds that it is "what a sighted player walks toward".

        Measured across every interaction pair in the game, that rule
        accepted 2024 routes of which only 265 were locally useful. A
        destination with no walkable floor beneath it anywhere in this room
        cannot be reached in this room, and saying otherwise is the
        false-routing defect. The guide now refuses and hands to the beacon.

        The destination here sits 45 units below a floor that does not
        extend under it, so no arrival tile exists -- see
        `pathfinding.destination_target_tiles`."""
        from battle_narrator.pathfinding import flow_field_toward
        geometry = build_room_geometry(
            walk_quad(0.0, 100.0, 0.0, 100.0), (), floor_id=1)
        player = Position(50.0, 0.0, 20.0)
        field = flow_field_toward(
            geometry, Position(50.0, -45.0, 130.0), player)
        # **Revised 2026-08-13.** Refusing outright took away guidance the
        # player was relying on. What must never happen is claiming to have
        # ARRIVED; being walked to the closest reachable ground, told how far
        # short it stops, is useful and honest.
        self.assertIsNotNone(field, "no guidance at all for a cross-level target")
        self.assertTrue(
            (field.stats or {}).get("partial_guidance"),
            "a destination with no floor under it was routed to as if it "
            "were reachable")

    def test_partial_guidance_never_chooses_a_floor_above_the_target(self):
        """Relic cave regression: X/Z proximity must not beat elevation.

        The player stands on a disconnected upper floor directly over the
        lower destination. The old partial fallback selected that upper
        floor and announced arrival despite a 120-unit vertical error.
        """
        geometry = build_room_geometry(
            walk_quad(0, 100, 0, 100, y=120.0, layer=3)
            + walk_quad(0, 20, 0, 20, y=0.0, layer=0),
            (), floor_id=1,
        )
        field = flow_field_toward(
            geometry, Position(10.0, 0.0, 10.0),
            Position(80.0, 120.0, 80.0),
        )
        self.assertIsNone(
            field,
            "partial guidance routed to the upper floor above the target",
        )

    def test_partial_guidance_obeys_a_region_band_at_an_upper_only_edge(self):
        """The live exit anchor can sit just beyond the lower cave floor.

        Its raw X/Z column therefore contains only the clifftop, while the
        wider trigger region establishes that the exit belongs downstairs.
        The partial fallback must retain that region evidence.
        """
        geometry = build_room_geometry(
            walk_quad(0, 100, 0, 100, y=120.0, layer=3)
            + walk_quad(0, 20, 0, 20, y=0.0, layer=0),
            (), floor_id=1,
        )
        lower_region = SimpleNamespace(triangles=(
            # A tall vertical curtain like M3_out's exit. Its broad region
            # band includes y=40 after tolerance, but its resolved floor is
            # y=0 and partial routing must stay with that floor.
            ((10.0, -10.0, 10.0), (80.0, -10.0, 10.0),
             (10.0, 36.0, 10.0)),
        ))
        field = flow_field_toward(
            geometry, Position(10.0, -10.0, 10.0),
            Position(80.0, 120.0, 80.0),
            destination_region=lower_region,
        )
        self.assertIsNone(
            field,
            "partial guidance discarded the exit region's lower-floor band",
        )

    def test_an_unseedable_destination_outside_the_room_gets_no_route(self):
        """The bound on the above. Guiding toward the reachable point
        "nearest" a destination this room does not contain would repeat the
        lateral projection's mistake at a larger scale."""
        from battle_narrator.pathfinding import flow_field_toward
        geometry = build_room_geometry(
            walk_quad(0.0, 100.0, 0.0, 100.0), (), floor_id=1)
        self.assertIsNone(
            flow_field_toward(geometry, Position(9000.0, 0.0, 9000.0),
                              Position(50.0, 0.0, 20.0)),
            "routed toward a destination nowhere near this room")

    def test_projection_never_seeds_inside_an_obstacle(self):
        from battle_narrator.pathfinding import resolve_destination_node
        blockade = wall((0.0, 96.0), (100.0, 96.0))
        geometry = build_room_geometry(
            walk_quad(0.0, 100.0, 0.0, 100.0), blockade, floor_id=1)
        projected = resolve_destination_node(
            geometry, Position(50.0, -45.0, 130.0))
        if projected is not None:
            tile, _layers, height, _offset = projected
            from battle_narrator.pathfinding import _swept_circle_node_blocked
            self.assertFalse(
                _swept_circle_node_blocked(geometry, tile, height),
                "route was seeded on a tile the player cannot stand on")

    def test_a_destination_that_already_projects_is_untouched(self):
        """The fallback must only ever turn a failure into a route -- it
        must never move a destination that already resolves."""
        from battle_narrator.pathfinding import resolve_destination_node
        geometry = build_room_geometry(
            walk_quad(0.0, 100.0, 0.0, 100.0), (), floor_id=1)
        on_floor = Position(50.0, 0.0, 50.0)
        direct = resolve_node(geometry, on_floor)
        projected = resolve_destination_node(geometry, on_floor)
        self.assertEqual(projected[:3], direct)
        self.assertEqual(projected[3], 0.0)

    def test_a_destination_nowhere_near_the_room_still_fails(self):
        from battle_narrator.pathfinding import resolve_destination_node
        geometry = build_room_geometry(
            walk_quad(0.0, 100.0, 0.0, 100.0), (), floor_id=1)
        self.assertIsNone(
            resolve_destination_node(geometry, Position(9000.0, 0.0, 9000.0)),
            "projected a destination that is nowhere near this room")


class ExemptTileTests(unittest.TestCase):
    """The tile the player stands in is exempt from the OCCUPANCY test only.

    Live-caught 2026-08-04 (late). Exempting it from the wall-crossing test
    too let the flood enter that tile straight through a wall, which is how
    `D1_garage_1F`'s six-tile pocket acquired the player as a member: every
    edge into their tile was genuinely swept-blocked, yet `origin_node in
    field.node_height` reported True, so `flow_field_toward`'s reachability
    fallback never fired and the guide confidently routed 8 units into a
    wall."""

    def _walled_off_geometry(self):
        # A full-height wall across the middle of an open floor. The player
        # stands just south of it; the seed is just north.
        geometry = build_room_geometry(
            walk_quad(0.0, 100.0, 0.0, 100.0),
            wall((0.0, 50.0), (100.0, 50.0), y0=-2.0, y1=30.0),
            floor_id=1)
        return geometry

    def test_an_exempt_tile_is_not_entered_through_a_wall(self):
        geometry = self._walled_off_geometry()
        south = Position(50.0, 0.0, 44.0)     # player, hard against the wall
        north = Position(50.0, 0.0, 56.0)     # destination, other side
        seed = resolve_node(geometry, south)
        field = pf.flow_field_toward(geometry, north, south)
        if field is not None:
            route = reconstruct_route(field, (seed[0], seed[1]))
            if route is not None:
                # If the player is linked at all, the link must not cross the
                # wall: every consecutive pair has to pass the real edge test.
                for before, after in zip(route, route[1:]):
                    self.assertFalse(
                        pf._swept_circle_blocked(
                            geometry, before[0], after[0], 0.0,
                            field.node_points),
                        f"route crossed a wall between {before[0]} and "
                        f"{after[0]}")

    def test_exemption_still_admits_the_tile_the_player_occupies(self):
        """The exemption must keep doing its real job -- a player standing
        in a tile whose centre is too close to a wall is still IN the graph,
        which is the 2026-08-04 fix this must not regress."""
        geometry = self._walled_off_geometry()
        # 4.5 units from the wall: standable at radius 3.5, and the tile
        # centre (44.0) is comfortably clear too, so the player links.
        player = Position(50.0, 0.0, 45.5)
        field = pf.flow_field_toward(
            geometry, Position(20.0, 0.0, 20.0), player)
        self.assertIsNotNone(field)
        seed = resolve_node(geometry, player)
        self.assertIn((seed[0], seed[1]), field.node_height)


class NodeRelocationTests(unittest.TestCase):
    """A tile's node sits at the roomiest point inside it, not mandatorily
    at its centre -- the resolution fix (2026-08-04, late)."""

    def test_a_corridor_that_misses_tile_centres_is_still_routable(self):
        """The exact failure mode. A gap wide enough for the player, placed
        so that no tile centre falls inside it, is invisible to a
        centre-only graph and obvious to a relocated one."""
        # Two walls leaving a 9-unit gap centred on z=40 -- wider than the
        # 7.0-unit diameter, so the player fits. Tile rows sit at z=36 and
        # z=44, both outside the gap's clear band.
        walls = (wall((0.0, 35.5), (100.0, 35.5), y0=-2.0, y1=30.0)
                 + wall((0.0, 44.5), (100.0, 44.5), y0=-2.0, y1=30.0))
        geometry = build_room_geometry(
            walk_quad(0.0, 100.0, 0.0, 100.0), walls, floor_id=1)
        point, clearance = pf._best_clearance_point(geometry, (6, 4), 0.0)
        centre = pf._tile_center((6, 4), geometry.tile_size)
        self.assertNotEqual(
            point, centre,
            "the node did not move even though the centre is not the "
            "roomiest point in the tile")
        self.assertGreaterEqual(
            clearance, geometry.collision_radius,
            "the corridor is wide enough for the player but was rejected")

    def test_relocation_now_applies_outdoors_too(self):
        """**Inverted 2026-08-04 (late).** This previously asserted that
        `M3_out` relocated ZERO nodes, as a structural guarantee that the
        outdoor room could not shift under its live-proven route.

        That guarantee was the bug. Pinning outdoor nodes to tile centres is
        what put 22 of 38 route tiles within 4.0 units of a wall, and that
        measurement was then cited as proof a swept test could not work
        outdoors -- circular. With relocation on, those same tiles resolve to
        points 6.2-10.3 units clear, and the route survives the swept test
        (see `RealRoomTests`). So relocation is now expected here, not
        forbidden."""
        ccd = COLLISION / "M3_out.ccd"
        if not ccd.is_file():
            self.skipTest(f"real fixture not found: {ccd}")
        data = ccd.read_bytes()
        geometry = build_room_geometry(
            parse_walk_model_triangles(data), parse_environment_triangles(data))
        field = flow_field_from(geometry, Position(-127.94, 16.12, 202.18))
        self.assertIsNotNone(field)
        self.assertGreater(
            field.stats["relocated_nodes"], 0,
            "no node relocated outdoors -- relocation is not reaching this "
            "room, which is the state that made the swept test look unusable")


class RelicStoneCaveRegressionTests(unittest.TestCase):
    """Live report 2026-08-12: "something is wrong with the relic stone cave
    navigation".

    `M3_cave_1F_1`'s walk model is a single flat quad, so all of its
    structure lives in 198 wall triangles, and its passage genuinely splits
    into pockets the flood cannot join. Asking for a route from the cave
    entrance to the shrine exit produced a confident `VERIFIED` 14-hop route
    whose final waypoint sat **180.4 units** from the exit, because
    `flow_field_toward`'s reachability fallback settled for the nearest
    reachable tile with no ceiling on how far "nearest" could be. Nothing was
    spoken to say the route did not reach the target: the player walks the
    cave and arrives nowhere near the way out.

    Positions are the room's own interactable region centres."""

    ENTRANCE = Position(62.1, 0.0, -134.8)
    SHRINE_EXIT = Position(-18.8, 0.0, 150.0)
    SAME_POCKET = Position(26.5, 0.0, -26.0)

    @classmethod
    def setUpClass(cls):
        ccd = COLLISION / "M3_cave_1F_1.ccd"
        if not ccd.is_file():
            raise unittest.SkipTest(f"missing fixture {ccd}")
        data = ccd.read_bytes()
        cls.geometry = build_room_geometry(
            parse_walk_model_triangles(data),
            parse_environment_triangles(data))

    def test_an_unreachable_exit_yields_no_route_rather_than_a_wrong_one(self):
        field = flow_field_toward(
            self.geometry, self.SHRINE_EXIT, self.ENTRANCE)
        self.assertTrue(
            field is None or (field.stats or {}).get("partial_guidance"),
            "the guide presented a route to a destination it cannot reach "
            "as if it arrived -- it will walk the player confidently to the "
            "wrong place")

    def test_the_failure_names_itself(self):
        cause, sentence = diagnose_unreachable(
            self.geometry, self.ENTRANCE, self.SHRINE_EXIT)
        self.assertEqual(
            cause, "disconnected",
            f"reported '{cause}' instead of naming the real problem: {sentence}")

    def test_a_destination_in_the_same_pocket_still_routes(self):
        """The refusal must be specific to unreachable targets. Guidance
        inside the reachable part of the cave has to keep working, or the
        fix has simply turned the cave off."""
        field = flow_field_toward(
            self.geometry, self.SAME_POCKET, self.ENTRANCE)
        self.assertIsNotNone(field)
        end = field.node_position(field.destination_node)
        self.assertLess(
            ((end.x - self.SAME_POCKET.x) ** 2
             + (end.z - self.SAME_POCKET.z) ** 2) ** 0.5, 8.0,
            "the route ended far from a destination that is reachable")


class ReachabilityFallbackBoundTests(unittest.TestCase):
    """The bound that separates "guide to the nearest reachable point" from
    "walk the player somewhere else and call it success".

    Each case below is one of the outcomes the 2026-08-12 split audit had to
    tell apart, pinned so the classification cannot drift."""

    def _room(self, name):
        ccd = COLLISION / f"{name}.ccd"
        if not ccd.is_file():
            self.skipTest(f"missing fixture {ccd}")
        data = ccd.read_bytes()
        return build_room_geometry(
            parse_walk_model_triangles(data), parse_environment_triangles(data))

    def test_cave_old_false_route_versus_new_refusal(self):
        """The headline case, asserted from both sides: the old rule DID
        produce a route, and it ended nowhere near the destination."""
        geometry = self._room("M3_cave_1F_1")
        entrance = Position(62.1, 0.0, -134.8)
        shrine = Position(-18.8, 0.0, 150.0)

        # Old behaviour, reproduced here only: nearest reachable node to the
        # RAW destination, no ceiling.
        reachable = flow_field_from(geometry, entrance)
        self.assertIsNotNone(reachable)
        best = min(
            (math.dist(pf.node_point(geometry, node[0], None, height),
                       (shrine.x, shrine.z)), node)
            for node, height in reachable.node_height.items())
        self.assertGreater(
            best[0], 128.0,
            "the old rule's terminal point should be far from the shrine -- "
            "this fixture no longer reproduces the reported failure")

        # Current behaviour still guides -- the player was relying on being
        # taken to the cave's doorstep -- but never as a route that arrives.
        field = flow_field_toward(geometry, shrine, entrance)
        self.assertTrue(
            field is None or (field.stats or {}).get("partial_guidance"),
            f"a route ending {best[0]:.0f} units from the destination was "
            f"presented as if it arrived")

    def test_the_garage_basement_warp_is_refused_after_investigation(self):
        """**Inverted 2026-08-12.** This required the basement stairwell to
        keep routing, on the reasoning that its distance is mostly vertical.

        Investigated rather than exempted, as the brief required: this room's
        walk model has no surface beneath either basement region, and no
        reachable node shares a tile with them. They are the stairs to
        another floor. The old rule "worked" by guiding 70 units to a spot by
        the south wall and reporting VERIFIED. Refusing is the correct
        model of a cross-level destination."""
        geometry = self._room("D1_garage_1F")
        player = Position(77.57, 0.0, -48.76)
        field = flow_field_toward(
            geometry, Position(72.99, -48.24, -119.07), player)
        self.assertTrue(
            field is None or (field.stats or {}).get("partial_guidance"),
            "the basement warp was routed to as if it were reachable")
        cause, sentence = diagnose_unreachable(
            geometry, player, Position(72.99, -48.24, -119.07))
        self.assertNotEqual(cause, "unknown", sentence)

    def test_an_ordinary_reachable_destination_is_untouched(self):
        geometry = self._room("D1_garage_1F")
        field = flow_field_toward(
            geometry, Position(20.0, 0.0, -20.0), Position(77.57, 0.0, -48.76))
        self.assertIsNotNone(field)
        self.assertFalse(
            (field.stats or {}).get("reseeded_for_reachability", False),
            "an ordinary in-room destination should not need the fallback")

    def test_a_structurally_disconnected_destination_is_named(self):
        geometry = self._room("M3_cave_1F_1")
        cause, sentence = diagnose_unreachable(
            geometry, Position(62.1, 0.0, -134.8),
            Position(-18.8, 0.0, 150.0))
        self.assertEqual(cause, "disconnected", sentence)
        self.assertIn("separate pockets", sentence)

    def test_a_destination_below_the_floor_still_projects(self):
        """Vertical separation must not by itself trip the bound: the
        garage warp is 48 units down and still earns guidance."""
        geometry = self._room("D1_garage_1F")
        target = Position(72.99, -48.24, -119.07)
        self.assertIsNone(
            resolve_node(geometry, target),
            "fixture no longer sits off the walkable surface")
        self.assertIsNotNone(
            pf.resolve_destination_node(geometry, target,
                                        max_vertical_gap=math.inf),
            "the destination should still project with the guard lifted")

    def test_acceptance_is_connectivity_not_distance(self):
        """**Replaced the projected-floor bound test, 2026-08-12.**

        There is no distance ceiling left to pin. What must hold is that
        acceptance follows local connectivity into the destination's arrival
        tiles: the garage's in-room region routes, and its basement warp --
        which no reachable node touches -- does not, regardless of how the
        two compare on distance."""
        garage = self._room("D1_garage_1F")
        player = Position(77.57, 0.0, -48.76)
        unreachable = flow_field_toward(
            garage, Position(72.99, -48.24, -119.07), player)
        self.assertTrue(
            unreachable is None
            or (unreachable.stats or {}).get("partial_guidance"),
            "an unreachable destination was routed to as if reachable")
        self.assertIsNotNone(
            flow_field_toward(garage, Position(20.0, 0.0, -20.0), player),
            "an ordinary reachable destination stopped routing")
        self.assertFalse(
            hasattr(pf, "REACHABILITY_FALLBACK_MAX_OFFSET"),
            "the distance ceiling is still present")


class RealGarageRegressionTests(unittest.TestCase):
    """The live failure of 2026-08-04 12:40:52, as an automated regression.

    The player selected the basement stairwell warp. The destination sits
    48.2 units BELOW the garage floor and 51 units beyond its southern edge,
    was projected laterally onto the ground floor, and seeded a six-node
    pocket the player could not walk out of. Positions are verbatim from
    `logs/battle_narrator_phase1b.log`."""

    PLAYER = Position(70.16, 0.00, -48.75)
    BASEMENT_WARP = Position(72.99, -48.24, -119.07)

    @classmethod
    def setUpClass(cls):
        ccd = COLLISION / "D1_garage_1F.ccd"
        if not ccd.is_file():
            raise unittest.SkipTest(f"real fixture not found: {ccd}")
        data = ccd.read_bytes()
        cls.geometry = build_room_geometry(
            parse_walk_model_triangles(data), parse_environment_triangles(data),
            floor_id=0x1)

    def test_the_basement_warp_is_diagnosed_as_cross_level(self):
        cause, sentence = diagnose_unreachable(
            self.geometry, self.PLAYER, self.BASEMENT_WARP)
        self.assertEqual(cause, "height_layer", sentence)

    def test_the_collision_radius_matches_where_the_player_really_stood(self):
        """The behavioural pin for `DEFAULT_COLLISION_RADIUS`.

        The engine let the player stand here, so their clearance is an upper
        bound on the radius the engine sweeps. Measured across all 311
        logged positions in this room the floor is 3.495, hit repeatedly at
        two independent walls -- consistent with 3.5 (a real value in the
        `peopleInfo` table) and flatly inconsistent with 4.0, which
        classified 67.8% of their real recorded positions as inside an
        obstacle."""
        seed = resolve_node(self.geometry, self.PLAYER)
        self.assertIsNotNone(seed)
        clearance = pf._point_clearance(
            self.geometry, seed[0], (self.PLAYER.x, self.PLAYER.z), seed[2])
        self.assertLess(
            clearance, 4.0,
            "this position would not disprove a 4.0 radius -- the fixture "
            "has drifted from the live capture it encodes")
        self.assertAlmostEqual(
            clearance, self.geometry.collision_radius, delta=0.02,
            msg=f"the player stood {clearance:.3f} from a wall while the "
                f"configured radius is {self.geometry.collision_radius}")

    def test_the_player_tile_links_despite_hugging_the_wall(self):
        """They were pressed against the south wall, in a 0.25-unit sliver at
        their tile's northern edge -- so the tile itself does not pass the
        sampled occupancy test, and only the standing-there exemption plus
        its self-calibrating radius put them in the graph. That is the whole
        point of the exemption, and this pins it against the real data."""
        field = pf.flow_field_toward(
            self.geometry, Position(-80.0, 0.0, 40.0), self.PLAYER)
        self.assertIsNotNone(field)
        seed = resolve_node(self.geometry, self.PLAYER)
        self.assertIn((seed[0], seed[1]), field.node_height)

    def test_the_basement_warp_is_refused_because_it_has_no_floor_here(self):
        """**Inverted 2026-08-12, after investigating rather than exempting.**

        This used to require guidance to the basement warp. It was only ever
        satisfied by the permissive fallback, which guided 70 units to a spot
        by the south wall and called it VERIFIED.

        Measured: this room's walk model has NO surface beneath either
        basement region (`walk_height_candidates` at both region centres is
        empty), and no reachable node shares a tile with either. They are
        cross-level destinations -- the stairs down -- and this room's graph
        genuinely cannot reach them. Refusing is correct."""
        field = pf.flow_field_toward(
            self.geometry, self.BASEMENT_WARP, self.PLAYER)
        self.assertTrue(
            field is None or (field.stats or {}).get("partial_guidance"),
            "the basement warp was presented as a reachable destination "
            "despite having no walkable floor beneath it in this room")

    def test_an_in_room_destination_still_routes(self):
        """The refusal must be specific to the unreachable warps -- ordinary
        guidance inside the garage has to keep working."""
        field = pf.flow_field_toward(
            self.geometry, Position(20.0, 0.0, -20.0), self.PLAYER)
        self.assertIsNotNone(field, "ordinary in-room guidance was lost")


class PlayerPositionAtActivationTests(unittest.TestCase):
    """Live-caught 2026-08-04, second pass. The off-floor-destination
    fallback needs the player's position to seed somewhere reachable, but
    the route is built inside `begin()` -- before any `next_waypoint` has
    supplied one. Without threading it through activation, the garage seeded
    a five-node pocket by the stairwell (`flow_field_nodes=5`) and reported
    the player unlinked on every poll."""

    def test_begin_uses_the_player_position_for_an_off_floor_destination(self):
        import logging
        from battle_narrator.navigation_service import NavigationService

        service = NavigationService(
            collision_dir="unused", room_codes={}, logger=logging.getLogger("t"))
        # A room whose floor is one quad, with the destination well beyond
        # its edge -- the shape of a stairwell warp.
        service._geometry_cache[1] = build_room_geometry(
            walk_quad(0.0, 200.0, 0.0, 200.0), (), floor_id=1)
        player = Position(20.0, 0.0, 20.0)
        # An in-room destination, so this tests what it says it tests: that
        # `begin` uses the player position. It used to use a destination 45
        # units below the floor and beyond its edge, which since 2026-08-12
        # is refused outright -- that made this a test of the removed
        # fallback rather than of activation-time seeding.
        service.begin(1, Position(180.0, 0.0, 180.0), player)
        result = service.next_waypoint(player)
        self.assertTrue(
            result.path_available,
            "an ordinary destination produced no route even though the "
            "player position was available at activation")
        self.assertEqual(service._last_player_position, player)

    def test_begin_without_a_player_position_still_works(self):
        """Backward compatible: the parameter is optional, and omitting it
        must not break an ordinary on-floor destination."""
        import logging
        from battle_narrator.navigation_service import NavigationService

        service = NavigationService(
            collision_dir="unused", room_codes={}, logger=logging.getLogger("t"))
        service._geometry_cache[1] = build_room_geometry(
            walk_quad(0.0, 200.0, 0.0, 200.0), (), floor_id=1)
        service.begin(1, Position(150.0, 0.0, 150.0))
        self.assertTrue(
            service.next_waypoint(Position(20.0, 0.0, 20.0)).path_available)
