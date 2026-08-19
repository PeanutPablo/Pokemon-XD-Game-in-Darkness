"""Interaction-region geometry: keep the whole region, not a centroid.

The Phase 1 audit measured every one of the 843 interaction regions in the
177 extracted rooms and found the centroid is not an interaction point:

| Measurement | Median | p90 | Max |
|---|---:|---:|---:|
| centroid -> nearest point of its own region | 0.00 u | 3.54 u | 168.9 u |
| centroid -> farthest point of its own region | 18.40 u | 30.68 u | 340.9 u |

842 of 843 are large enough that a player standing legitimately inside can
be more than a full interaction radius from the announced point, and 210
have a centroid lying outside their own region.

So a region is retained as its triangles, and the point announced is the
**nearest point of the region to the player**, recomputed per query. The
centroid survives only as a stable anchor for ordering and metadata, where
its inaccuracy costs nothing.

Shared deliberately: warps, doors, elevators, PCs, signs and the Phase 4
room-script objects all sit on the same geometry, so this exists once
rather than five times.
"""
from dataclasses import dataclass
import math
import struct

MAX_CCD_ENTRIES = 4096
MAX_CCD_TRIANGLES = 100000
INTERACTABLE_SLOTS = (0x2C, 0x30)
"""The two top-level CCD slots carrying interactable triangle lists. No
interaction index appears in both slots in any of the 177 rooms, so
merging them into one namespace never collides -- measured, not assumed."""


def _u16(data, offset):
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data, offset):
    return struct.unpack_from(">I", data, offset)[0]


@dataclass(frozen=True)
class Region:
    """One interaction region, as its own triangles."""

    index: int
    triangles: tuple
    anchor: tuple
    """(x, y, z): centroid X/Z with the region's FLOOR Y. Ordering and
    metadata only -- never announced as the place to walk to. Y is the
    minimum because these are tall trigger volumes standing on the walkable
    surface, and the player's own Y is their feet."""

    def nearest_point(self, x, z):
        """Nearest point of this region to (x, z), in the XZ plane.

        Returns the point itself when the player is inside a triangle, and
        the nearest point on an edge otherwise -- which is what "walk to
        the edge of the trigger" means."""
        best = None
        best_distance = None
        for triangle in self.triangles:
            if _contains_xz(triangle, x, z):
                return (x, z)
            for start in range(3):
                ax, _, az = triangle[start]
                bx, _, bz = triangle[(start + 1) % 3]
                point = _nearest_on_segment(ax, az, bx, bz, x, z)
                distance = math.hypot(point[0] - x, point[1] - z)
                if best_distance is None or distance < best_distance:
                    best_distance, best = distance, point
        return best

    def distance(self, x, z):
        point = self.nearest_point(x, z)
        if point is None:
            return None
        return math.hypot(point[0] - x, point[1] - z)

    def components(self):
        """This region split into its spatially separate VOLUMES.

        One interaction index can own several disjoint trigger volumes --
        the two ends of a corridor, both sides of a doorway, a pair of cave
        mouths. Measured over all 843 regions, that is why 210 have a
        centroid outside their own geometry: the centroid lands in the empty
        space between two volumes. `D1_out` index 2 is 161.9 units from any
        of its own triangles, `D3_out` index 1 is 168.9.

        Treating such a region as one blob is what lets navigation announce
        and route toward different volumes, or pick a nearer volume the
        player cannot reach while a farther one is walkable. Splitting it
        makes "which part of this thing am I going to" answerable.

        Triangles join a component when they share a vertex in XZ. That is
        the conservative direction: touching volumes merge (harmless -- they
        are mutually reachable by definition), while genuinely separate ones
        stay separate, which is the case that matters.

        Returns a tuple of `Region`s sharing this one's index and anchor.
        A single-volume region returns itself, so callers need no special
        case."""
        if len(self.triangles) <= 1:
            return (self,)
        parent = list(range(len(self.triangles)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

        keyed = []
        for triangle in self.triangles:
            keyed.append({(round(v[0], 3), round(v[2], 3)) for v in triangle})
        for i in range(len(keyed)):
            for j in range(i + 1, len(keyed)):
                if keyed[i] & keyed[j]:
                    union(i, j)
        groups = {}
        for index, triangle in enumerate(self.triangles):
            groups.setdefault(find(index), []).append(triangle)
        if len(groups) == 1:
            return (self,)
        return tuple(
            Region(index=self.index, triangles=tuple(members),
                   anchor=self.anchor)
            for members in groups.values())


def _nearest_on_segment(ax, az, bx, bz, x, z):
    dx, dz = bx - ax, bz - az
    length = dx * dx + dz * dz
    if length == 0.0:
        return (ax, az)
    t = ((x - ax) * dx + (z - az) * dz) / length
    t = max(0.0, min(1.0, t))
    return (ax + t * dx, az + t * dz)


def _contains_xz(triangle, x, z):
    """Point-in-triangle in the XZ plane.

    A triangle with **zero area in XZ contains nothing**, and that case is
    not hypothetical: every vertical face of a trigger volume projects to a
    line. Without this guard the sign test degenerates -- all three cross
    products are zero, neither `negative` nor `positive` is set, and the
    function claims to contain the entire plane. A single vertical face
    would then report distance 0 to the player wherever they stood.
    Callers fall through to the edge test, which is the right answer for a
    line."""
    (ax, _, az), (bx, _, bz), (cx, _, cz) = triangle
    area = (bx - ax) * (cz - az) - (cx - ax) * (bz - az)
    if area == 0.0:
        return False
    d1 = (x - bx) * (az - bz) - (ax - bx) * (z - bz)
    d2 = (x - cx) * (bz - cz) - (bx - cx) * (z - cz)
    d3 = (x - ax) * (cz - az) - (cx - ax) * (z - az)
    negative = (d1 < 0) or (d2 < 0) or (d3 < 0)
    positive = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (negative and positive)


def triangle_key(vertices):
    """Order-independent identity for one triangle, rounded to the CCD's own
    two-decimal precision. Used to recognise the SAME triangle appearing in
    two different CCD slots."""
    return tuple(sorted(
        tuple(round(coordinate, 2) for coordinate in vertex)
        for vertex in vertices))


def interaction_volume_keys(ccd):
    """Every interaction-region triangle in this room, as `triangle_key`s.

    **Why routing needs this (live 2026-08-14).** A CCD object can carry
    geometry in the hit-model slot (+0x28) *and* own an interaction region
    (slots +0x2C/+0x30), and in that case the two are frequently the SAME
    triangles. `M3_out` entry 33 is exactly that: its two hit-model triangles
    are byte-identical to region 9's, and it is the only entry in that room
    which both owns a region and has hit geometry.

    Treating those triangles as obstacles builds a wall across a doorway the
    player walks straight through -- confirmed live by the project owner, who
    can enter the Relic Stone cave while the engine reports that object
    ENABLED and the companion was modelling its trigger volume as a barrier.

    An interaction region is by definition a volume the player must be able
    to stand inside for the trigger to fire, so it cannot also be something
    they are blocked by. Measured across all 177 rooms: 346 of 1118
    hit-model objects have obstacle geometry that is entirely interaction
    geometry, spanning 117 rooms -- so this is a systemic mismodelling, not
    one room's quirk.

    Returns a frozenset; `pathfinding.build_room_geometry` drops any wall
    triangle whose key is in it."""
    return frozenset(
        triangle_key(triangle)
        for region in parse_regions(ccd).values()
        for triangle in region.triangles)


def parse_regions(ccd):
    """`{interaction index: Region}` for one room's `.ccd`.

    All 2,259 top-level entries across all 177 rooms carry an identity
    transform, so these vertices are world coordinates -- an earlier
    hypothesis that they were object-space was measured and disproven."""
    list_start = _u32(ccd, 0)
    entry_count = _u32(ccd, 4)
    if (entry_count > MAX_CCD_ENTRIES
            or list_start + entry_count * 0x40 > len(ccd)):
        raise ValueError("invalid CCD top-level table")
    collected = {}
    for entry_index in range(entry_count):
        entry = list_start + entry_index * 0x40
        for slot in INTERACTABLE_SLOTS:
            pointer = _u32(ccd, entry + slot)
            if pointer == 0:
                continue
            triangle_start = _u32(ccd, pointer)
            triangle_count = _u32(ccd, pointer + 4)
            if (triangle_count > MAX_CCD_TRIANGLES
                    or triangle_start + triangle_count * 0x34 > len(ccd)):
                raise ValueError("invalid CCD interactable triangle list")
            index_offset = 0x32 if slot == 0x2C else 0x30
            for triangle_index in range(triangle_count):
                offset = triangle_start + triangle_index * 0x34
                values = struct.unpack_from(">9f", ccd, offset)
                if not all(math.isfinite(value) for value in values):
                    raise ValueError("non-finite CCD interactable vertex")
                index = _u16(ccd, offset + index_offset)
                collected.setdefault(index, []).append((
                    tuple(values[0:3]), tuple(values[3:6]), tuple(values[6:9]),
                ))
    regions = {}
    for index, triangles in collected.items():
        points = [vertex for triangle in triangles for vertex in triangle]
        regions[index] = Region(
            index=index,
            triangles=tuple(triangles),
            anchor=(
                sum(p[0] for p in points) / len(points),
                min(p[1] for p in points),
                sum(p[2] for p in points) / len(points),
            ),
        )
    return regions
