"""Validation report for the two-authority passability slice.

Runs the four rooms the slice is required to be validated against and prints
the diagnostics requirement 6 asks for: room, triangle counts, selected
authority, collision radius, node count, rejected nodes/edges, projection
results, and whether a route was found.

Read-only. Uses the project owner's own extracted `.ccd` data.
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from battle_narrator.collision_probe import (
    parse_environment_triangles, parse_walk_model_triangles)
from battle_narrator.npc_beacons import Position
from battle_narrator.pathfinding import (
    PassabilityAuthority, _tile_center, build_room_geometry,
    diagnose_unreachable, flow_field_from, reconstruct_route, resolve_node)
from battle_narrator.player_facing_names import player_facing_room_name

COLLISION = BASE / "_dialogue_extraction" / "collision"

# (room, floor_id, start, destination, note)
CASES = [
    ("M3_out", 0x84, Position(-3.0, -0.02, 8.0), Position(-60.0, 40.0, 120.0),
     "live-proven terrace route (AUDIO GUIDE Arrived., 2026-08-02)"),
    ("D1_garage_1F", 0x1, Position(76.16, 0.0, -35.02), Position(33.49, 0.0, -24.45),
     "positions from the failing live log, 2026-08-04 11:45-11:47"),
    ("M3_pc_1F", 0x85, None, None, "Agate Pokemon Center"),
    ("M2_shop_1F", 0x79, None, None, "Pyrite Poke Mart"),
]


def geometry_for(room, floor_id):
    data = (COLLISION / f"{room}.ccd").read_bytes()
    return build_room_geometry(
        parse_walk_model_triangles(data),
        parse_environment_triangles(data),
        floor_id=floor_id)


def corners(geometry):
    """Two widely separated points inside the room's LARGEST connected
    walkable region.

    An earlier version used the walk quad's bounding-box corners inset by a
    fixed margin. That is not a fair test: an indoor room's corners are
    routinely behind a counter or inside the wall band, so it measured
    whether an arbitrary point happened to be reachable rather than whether
    the room routes. Picking the extremes of the dominant component asks the
    question actually worth asking -- can the player cross the room's open
    floor."""
    from battle_narrator.pathfinding import (
        _ORTHOGONAL, _DIAGONAL, _try_edge, walk_height_candidates)

    tile_size = geometry.tile_size
    xs = [v[0] for t in geometry.walk_triangles for v in t.vertices]
    zs = [v[2] for t in geometry.walk_triangles for v in t.vertices]
    y = geometry.walk_triangles[0].vertices[0][1]
    nodes = {}
    for ix in range(int(min(xs) // tile_size), int(max(xs) // tile_size) + 1):
        for iz in range(int(min(zs) // tile_size), int(max(zs) // tile_size) + 1):
            cx, cz = _tile_center((ix, iz), tile_size)
            found = walk_height_candidates(geometry, cx, cz)
            if found:
                nodes[(ix, iz)] = found[0]

    seen, best = set(), set()
    for tile in nodes:
        if tile in seen:
            continue
        stack, component = [tile], set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            surface = nodes[current]
            for dx, dz in _ORTHOGONAL + _DIAGONAL:
                neighbour = (current[0] + dx, current[1] + dz)
                if neighbour in component or neighbour not in nodes:
                    continue
                if _try_edge(geometry, current, surface.height,
                             surface.layers, neighbour) is not None:
                    stack.append(neighbour)
        seen |= component
        if len(component) > len(best):
            best = component

    ordered = sorted(best, key=lambda t: (t[0], t[1]))
    first, last = ordered[0], ordered[-1]
    ax, az = _tile_center(first, tile_size)
    bx, bz = _tile_center(last, tile_size)
    return Position(ax, y, az), Position(bx, y, bz)


def report(room, floor_id, start, destination, note):
    geometry = geometry_for(room, floor_id)
    if start is None:
        start, destination = corners(geometry)
    print(f"=== {room}  (floor 0x{floor_id:X} -- "
          f"{player_facing_room_name(room)})")
    print(f"    {note}")
    print(f"    walk_triangles={len(geometry.walk_triangles)}  "
          f"wall_triangles={len(geometry.wall_triangles)}")
    print(f"    authority={geometry.authority.value}  "
          f"collision_radius={geometry.collision_radius}  "
          f"tile_size={geometry.tile_size}")

    start_seed = resolve_node(geometry, start)
    dest_seed = resolve_node(geometry, destination)
    print(f"    start  ({start.x:.1f},{start.y:.1f},{start.z:.1f}) -> "
          f"{'tile ' + str(start_seed[0]) if start_seed else 'NO PROJECTION'}")
    print(f"    target ({destination.x:.1f},{destination.y:.1f},{destination.z:.1f}) -> "
          f"{'tile ' + str(dest_seed[0]) if dest_seed else 'NO PROJECTION'}")

    field = flow_field_from(geometry, destination)
    if field is None:
        cause, explanation = diagnose_unreachable(geometry, start, destination)
        print(f"    ROUTE: none. cause={cause}")
        print(f"           {explanation}")
        print()
        return
    stats = field.stats or {}
    print(f"    nodes={len(field.node_height)}  "
          f"rejected_edges={stats.get('rejected_edges')}  "
          f"rejected_nodes={stats.get('rejected_nodes')}")
    if start_seed is None:
        print("    ROUTE: start does not project\n")
        return
    node = (start_seed[0], start_seed[1])
    if node not in field.node_height:
        cause, explanation = diagnose_unreachable(
            geometry, start, destination, field)
        print(f"    ROUTE: start not linked. cause={cause}")
        print(f"           {explanation}")
        print()
        return
    route = reconstruct_route(field, node)
    print(f"    ROUTE: FOUND, {len(route)} hops")
    print()


def main():
    print("Two-authority passability validation")
    print(f"collision data: {COLLISION}")
    print()
    for room, floor_id, start, destination, note in CASES:
        if not (COLLISION / f"{room}.ccd").is_file():
            print(f"=== {room}: .ccd not extracted, skipped\n")
            continue
        report(room, floor_id, start, destination, note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
