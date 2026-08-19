"""Reusable intra-room walkable-tile pathfinding.

Builds a destination-origin flow field over a room's own CCD walk model
(see `collision_probe.parse_walk_model_triangles`, CCD slot +0x24), so any
consumer can ask "what's the next walkable tile toward X" without
re-deriving walkability rules. Today's only consumer is
`navigation_service.NavigationService` (in turn consumed by
`audio_guide.AudioGuideReader`), but this module owns none of that
polling/hysteresis state -- it is pure geometry and search, deliberately
kept reusable for future consumers (autowalk, breadcrumb guidance, spoken
turn directions), none of which are implemented yet.

**Architecture rewrite (2026-08-01) -- read `WORLD_NAVIGATION_ARCHITECTURE.md`
first.** Every earlier version of this module (2026-07-30 through 2026-07-31)
inferred floor/height from CCD slot +0x28 (`CCD_HITMDL_HEAD`, obstacle/wall
geometry) because that was the only slot this project's `.ccd` parser read.
An explicit investigation (project owner's request, "is the missing floor
genuinely missing data, or an incomplete understanding of the game's world
representation") traced every CCD model slot via decomp disassembly and
found the answer is the latter: CCD slot +0x24 (`CCD_WALKMDL_HEAD`) is the
engine's own walkable-ground model, read by `GScolsys2WalkGetHeight` and
consumed by both real player locomotion (`heroMove.s`) and NPC locomotion
(`people.s`). It carries explicit per-triangle LAYER identity (byte +0x31,
two nibbles) and explicit TRANSITION triangles connecting adjacent layers
(e.g. a ramp) -- exactly the information needed to correctly route through
a terraced area, which height-proximity alone cannot disambiguate (measured
live: `M3_out`'s layers 1/2/3 have OVERLAPPING height bands).

So: **walkability, height, and layer all come from the walk model now.**
CCD slot +0x28 (`CollisionTriangle`, via `collision_probe.
parse_environment_triangles`) is used for exactly one thing here --
OBSTRUCTION, via a swept circle of the hero's own collision radius
(`_swept_points_blocked`), filtered to near-vertical triangles by
`WALL_NORMAL_THRESHOLD` exactly as `predict_forward_collision` already does
for the same data. That is now the single passability test for every room;
see the block comment above HEIGHT_CONTINUITY_TOLERANCE.

There is deliberately NO default-walkable/default-open fallback anymore. A
tile is walkable only if the walk model actually says so -- "no invented
walkable surfaces," per the project owner's explicit requirement. This is
now safe (it was not, before this rewrite): the earlier default-open pivot
existed specifically because +0x28 has almost no floor coverage in most
rooms, but +0x24 does (measured: 26,088 upward-facing triangles across 167
rooms in +0x24, vs. 289 in +0x28). Rooms with no walk model at all (10 of
177, not yet individually inspected) will now honestly fail to route,
falling back to direct guidance via the existing, already-tested mechanism
-- a real, disclosed limitation rather than a silently wrong inference.

First version optimizes tile-hop count (an unweighted-per-step search), NOT
necessarily the easiest route for a blind player to follow. A uniform-cost
(Dijkstra-shaped, not a plain BFS deque) search is used specifically so a
future version can supply a real `edge_cost` (turn penalties, narrow-passage
penalties, stairs/elevation, preferred corridors, terrain costs) without
restructuring the search itself -- only the cost function would change.

Route simplification IS implemented (2026-08-03, `simplify_route`), but in
its conservative COLLINEAR-COLLAPSE form, not the line-of-sight shortcutting
originally sketched -- see that function's own docstring for why, and
`waypoint_span_for_route` for how spacing scales with route length. Measured
against the real route from the 2026-08-04 live session: collapsing left 0
of 18 legs with a worse unsupported stretch than the individual hops it
replaced, so the "consecutive waypoints are joined by a straight line of
walkable tiles" guarantee is holding empirically as well as by construction.
True line-of-sight shortcutting between NON-collinear nodes remains
unimplemented and would need a real swept test against both models.

Cross-room routing is out of scope: this operates on one room's geometry at
a time. A room/floor change always means building a fresh
`RoomWalkableGeometry` from that room's own `.ccd` data.
"""
import functools
import heapq
import math
from dataclasses import dataclass
from enum import Enum

from . import region_geometry
from .collision_object_enable import StaticObjectEnableState
from .npc_beacons import Position

WALL_NORMAL_THRESHOLD = 0.35
"""Same magnitude threshold `predict_forward_collision` already uses to
decide a CCD hit-model triangle is "wall-like" (roughly vertical) -- reused
here, not redefined, to select which triangles the swept circle tests
against. This is the ONLY role CCD slot +0x28 plays in this module; see
this module's own top docstring."""
TILE_SIZE = 8.0
"""First-guess grid resolution (between terrain_footsteps.STEP_DISTANCE=12
and typical interaction radii ~10). Flagged for live tuning by ear, the same
way STEP_DISTANCE/MAX_PLAUSIBLE_DELTA were tuned twice already this project
from real field data -- this has not been live-tuned yet.

Deliberately UNCHANGED again by the single-passability-test slice
(2026-08-04, late), for the same reason it survived the two-authority slice
before it: resolution is a separate question from passability, and changing
both at once would make any behaviour change unattributable. `node_point`
relocation (see `_best_clearance_point`) addresses the placement half of
the resolution problem, which measurement showed was the half that mattered
-- halving this constant moved `M3_pc_1F` only from 23.7% to 28.7%
reachable. Whether the remaining half needs a finer lattice is the question
NAVIGATION_AUDIT_2026-08-04.md 2.4 leaves open, deliberately, until the
passability test underneath it has been live-validated."""

DEFAULT_COLLISION_RADIUS = 3.5
"""Radius, in world units, of the ball the engine sweeps when moving the
player: `heroMove.s:1186-1196` fetches the mover's `peopleInfo` record,
reads `peopleInfoBiosGetColBallSize`, and passes it to
`GScolsys2HitCollision`.

**Measured from live play, 2026-08-04 (late). Was 4.00, which was wrong.**

The `peopleInfo` table (279 records, live-read) holds 224 records at 4.00,
**14 at 3.50**, 23 at 0.00 and a handful of one-offs. 4.00 was adopted as
the table's dominant value because the hero's own record could not be
indexed -- the player's people-info ID comes from a runtime
`HEROMOVE_MEMBER` via `getObjID` in `heroMove.s`, not a constant.

It is pinned behaviourally instead, which needs no such index. Every
position the engine ever LET the player occupy is a position at least
`colBallSize` from any swept wall, so the closest observed approach is a
direct upper bound. **Corroborated across four independent rooms**
(NAVIGATION_AUDIT_2026-08-04.md 1), over every player position
`logs/battle_narrator_phase1b.log` holds:

    room            positions   min      <3.0    <3.5     <4.0
    D1_garage_1F          469   3.495    0.0%   23.9%    69.3%
    D1_labo_B1             38   3.496    0.0%   21.1%    63.2%
    D1_labo_B2             68   3.351    0.0%   27.9%    60.3%
    D1_labo_B3             41   2.684    2.4%   14.6%    51.2%

Four different geometries, and the distribution bottoms out at the same
value in each. In `D1_garage_1F` the floor is reached by two INDEPENDENT
contact points -- the south wall at z=-52.2 (player pressed against it, z
pinned at -48.76 while x slid along) and a separate obstacle near
(16.5, -22.1). The handful of sub-3.5 readings are measurement error, not
signal: logged positions are rounded to two decimals and `_swept_circle_*`
approximates each triangle by its longest XZ edge, which overstates its
extent near a corner. 3.50 is a real value in the table, so this
corroborates a record the hero plausibly has rather than fitting an
arbitrary number.

The consequence of the old value was not subtle: **51-69% of the positions
the player was actually standing in were classified as inside an
obstacle.** That is the true cause of the indoor fragmentation attributed
to grid resolution in WORLD_NAVIGATION_ARCHITECTURE.md 6h-6i -- the free
space was being eroded by 0.5 units everywhere, which is exactly enough to
sever marginal corridors no matter how finely they are sampled. It also
explains why halving the tile size did not help.

The same measurement settled a second question: **`collision_type` does not
gate passability.** Types 0-7 all occur, and in every room the closest
observed approach to EVERY type is the same ~3.5. No type is ever walked
through, so treating all near-vertical hit triangles as blocking is right.

Still configurable per geometry. A future direct read of the hero's
`peopleInfo` record would supersede this; it should agree."""

WALL_HEIGHT_BAND = 12.0
"""How far above a walkable surface a hit-model triangle must reach to be
treated as an obstacle for someone standing on it.

Requirement: do not flatten unrelated height layers into one obstacle set.
The predecessor test (`_segment_blocked`, removed 2026-08-04 late) projected
every wall triangle to XZ with no height test at all, so a railing far
overhead blocked a ground-level route. Now that the swept circle is the only
gate, this band applies everywhere, and that stray-railing behaviour is gone
with it.

First-guess value: large enough to cover a character's body, small enough to
exclude a storey above. Not live-tuned. Its remaining known gap is that
there is no MINIMUM obstacle height -- a 0.5-unit lip blocks exactly like a
wall. Not indicted by any measurement so far, still unverified."""


# ----------------------------------------------------------------------
# ONE passability test, everywhere. (2026-08-04, late -- see
# NAVIGATION_AUDIT_2026-08-04.md 2.)
#
# This module used to pick between two obstacle tests per room
# (`PassabilityAuthority`): a swept circle where the walk model was a bare
# quad, and a permissive five-sample line test (`_segment_blocked`)
# everywhere else. Both are gone. The walk model remains the sole authority
# on FLOOR SUPPORT and LAYER CONNECTIVITY -- which is all
# WORLD_NAVIGATION_ARCHITECTURE.md 1-4 ever established -- and the hit model
# is now the sole authority on OBSTRUCTION, tested by sweeping the hero's
# own collision ball exactly as `heroMove.s` does.
#
# Why the split was wrong on both sides:
#
# 1. The classifier ("<= 8 walk triangles means degenerate") misfired on
#    real rooms. `D1_labo_B2` cleared it by SIX triangles; its walk model is
#    a floor plane (4156 units^2 per triangle, one layer) and all 416 of its
#    structural triangles live in the hit model -- so it got the permissive
#    test. `D1_labo_B3` is the same story at 76 triangles. Measured there,
#    the flood admitted 2688 nodes where sweeping admits 61: the guide was
#    routing over a graph 44x larger than the space the player can occupy.
#    That is the "it leads me through walls" report, quantified.
#
# 2. The reason the split existed does not hold. WORLD_NAVIGATION_
#    ARCHITECTURE.md 6g rejected a global swept test because 22 of 38 TILE
#    CENTRES on the live-proven `M3_out` terrace route sit within 4.0 units
#    of a wall triangle. But that measures tile centres, not player
#    positions -- a centre 0.10 units from a cliff means the CENTRE is not
#    standable, which is exactly what node relocation exists to fix. No
#    player-position measurement anywhere in this project supports "hugging
#    geometry is normal"; every one that exists obeys 3.5 (see
#    DEFAULT_COLLISION_RADIUS). Re-run with the radius corrected to 3.5 and
#    relocation enabled, `M3_out`'s terrace journey still routes: 1837
#    nodes, 13 hops, 122.9 units, versus 10 hops / 82.4 before. It gets
#    LONGER because it now goes around what it used to cut through.
#
# A per-triangle alternative was tried first and FAILED: classifying each
# wall triangle as interior-obstacle (walkable floor on both sides at the
# same height) versus terrain-edge separates `M6_out` cleanly (30 interior
# of 900) but calls `M3_out`'s ramp flanks interior and would reject 10 of
# that route's 17 hops. Recorded so it is not re-attempted.
# ----------------------------------------------------------------------

HEIGHT_CONTINUITY_TOLERANCE = 10.0
"""**Demoted (2026-08-01) from primary connectivity gate to a defensive
numeric check, and re-measured against real data in that new role.**
Previously this alone decided whether two tiles' inferred heights were
"close enough" to link -- exactly the mechanism that silently bridged
unrelated overlapping terraces, since `M3_out`'s own layers 1/2/3 have
overlapping height bands (1: 0.87-41.00, 2: 43.19-92.16, 3: 81.68-121.19)
and height proximity alone cannot tell them apart. Layer identity (see
`_connected_walk_candidate`) is now the primary gate; this tolerance only
filters WITHIN an already layer-validated same-layer or transition
relationship, catching the case where a same-layer/transition candidate
technically shares a layer number but sits at an implausibly different
height (most likely two unrelated surfaces that happen to reuse the same
layer ID, not a modeling error).

The old value of 6.0 was tuned for the PREVIOUS (height-only, no layer
identity) model and turned out to be too strict once layer identity became
the real gate: measuring every genuinely same-layer, wall-unblocked,
adjacent tile pair across the real `M3_out` walk model found a real,
repeated climbable slope (`M3_out`'s own layer-1 hillside) with per-tile
height steps up to 7.40 -- 6.0 rejected part of that real, live-confirmed
walkable terrace (caught by `test_regression_routes_up_the_real_terrace_
instead_of_failing` failing at a measured delta of 6.80). The very next
cluster of same-layer deltas in that same measurement jumps straight to
22.04 and above -- almost certainly coincidental layer-number reuse between
genuinely unrelated surfaces, not real terrain. 10.0 sits with margin above
every real measured slope step and with a much larger margin below that
jump, so it still does real defensive work rather than passing everything
through."""
MAX_DROP_HEIGHT = None
"""**Do not add falling to the graph. The premise was wrong.**

Agate's Relic Stone cave sits in a hollow whose nearest same-level reachable
ground is 141 units away, while the tile above it carries walkable ground
125 units up. That looked like "you get in by walking off the ledge", and
one-way downward edges were implemented on that basis. They connected the
cave -- and also made falling beat walking on already-proven routes
(`M3_out`'s live-validated terrace route shortened from 11 hops to 10 by
leaping off the terrace instead of taking the ramp).

**Then the project owner corrected the premise (2026-08-13): this game has
no drops at all.** The character is glued to the ground while walking, with
one specific exception somewhere in the S.S. Libra. So falling is not how
that hollow is entered, and modelling it would be inventing a movement the
engine does not have -- the exact class of mistake the no-hardcoding rule
exists to prevent.

What the measurement therefore means instead: **the hollow must have a
walkable connection our model is refusing.** Classifying every one of the 60
boundary edges out of that 26-tile pocket, with the same predicate routing
uses:

    layer mismatch          28   neighbour's only surface is the clifftop
                                 (y=120, layer 3) -- correctly refused
    edge blocked by wall    22   <- the real suspects
    no walk surface at all  10   correctly refused

So the investigation has a target of 22 edges, not a room. That is the
deferred wall-semantics work, and it is now sharply scoped."""


MAX_TILES = 32000
"""Hard bound on search size, matching this project's standing convention of
bounding every unbounded-looking loop (floor_data_max_records,
people_work_max_records, etc.). Exceeding it aborts that build attempt --
the caller (navigation_service.py) falls back to direct guidance.

Derived from a full survey of every .ccd in the game (2026-08-03), measuring
the actual reachable node count of a flow field with the cap lifted:

    M6_out (Gateon Port)   24555 nodes   <- largest room in the game
    D3_out                 14900
    M2_cave_1F_1           11310
    M2_cave_2F_2           11130
    D5_out                 10315
    ...167 routable rooms total

The previous value of 20000 predates the walk-model rewrite and was set
before any of this could be measured. It clipped exactly one room -- and it
was M6_out, where the flood reaches 24555 nodes, so every route request in
Gateon Port failed outright and fell back to direct guidance ("No walkable
path found"). Nothing else in the game came close to the old bound.

32000 sits ~30% above the true maximum, so it still bounds a runaway search
while no real room can hit it. Worst measured build is M6_out at ~1.75s;
every other room is under 0.9s."""
WALK_MAX_CANDIDATES_PER_QUERY = 8
"""Matches `GScolsys2WalkGetHeight`'s own hard cap on distinct-height walk
surfaces accumulated for one XZ query (`cmpwi r24, 0x8` in the
disassembly) -- reproduced here as the engine's own source of truth, not
an independently chosen limit."""
WALK_HEIGHT_DEDUP_EPSILON = 1e-3
"""Two walk-model triangles whose plane height at the same query point
differ by less than this are treated as the same candidate surface --
mirrors `GScolsys2WalkGetHeight`'s own "reuse this height slot" merge
(adjacent triangles forming one flat quad share an exact height in
practice; this small tolerance absorbs float noise, not real height
differences)."""
NORMAL_VERTICAL_EPSILON = 1e-4
"""A walk-model triangle whose normal Y is closer to zero than this is
treated as vertical -- its plane equation cannot yield a meaningful height
(division by ~0). `GScolsys2WalkGetHeight` includes these triangles in its
point-in-polygon scan with no explicit filter visible in the disassembly,
but a near-zero denominator there would already produce a meaningless
height in the engine's own arithmetic; skipping them here reproduces that
outcome without risking a divide-by-zero, and was verified live: the
emulation using this exact rule matched all captured `M3_out` positions to
within 0.00-0.01 units."""

# Orthogonal neighbors are expanded before diagonals so corner-cut
# prevention can check "are both adjoining orthogonal steps open" using
# this same expansion pass.
_ORTHOGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
_DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))


def _tile_key(x, z, tile_size):
    return (math.floor(x / tile_size), math.floor(z / tile_size))


def _tile_center(key, tile_size):
    ix, iz = key
    return (ix * tile_size + tile_size / 2.0, iz * tile_size + tile_size / 2.0)


def _point_in_triangle_xz(x, z, triangle):
    (ax, _, az), (bx, _, bz), (cx, _, cz) = triangle.vertices
    d1 = (x - bx) * (az - bz) - (ax - bx) * (z - bz)
    d2 = (x - cx) * (bz - cz) - (bx - cx) * (z - cz)
    d3 = (x - ax) * (cz - az) - (cx - ax) * (z - az)
    has_negative = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_positive = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_negative and has_positive)


def _triangle_xz_bounds(triangle):
    xs = [vertex[0] for vertex in triangle.vertices]
    zs = [vertex[2] for vertex in triangle.vertices]
    return min(xs), max(xs), min(zs), max(zs)


@functools.lru_cache(maxsize=None)
def _triangle_longest_edge_xz(triangle):
    """Memoized: this is a fixed, deterministic property of `triangle` (a
    hashable frozen dataclass) that never changes, but the swept test hits
    the same handful of nearby wall triangles repeatedly across many
    tile-pair and sub-tile-sample combinations during one flood fill --
    profiling a real route build found this was ~15% of total time before
    caching, almost all of it pure recomputation of the same result."""
    projected = [(vertex[0], vertex[2]) for vertex in triangle.vertices]
    pairs = ((0, 1), (1, 2), (2, 0))
    a, b = max(
        pairs, key=lambda pair: math.dist(projected[pair[0]], projected[pair[1]]))
    return projected[a], projected[b]


def _cells_for_bounds(bounds, tile_size):
    min_x, max_x, min_z, max_z = bounds
    # The upper bound is nudged down by a tiny epsilon before flooring so a
    # triangle edge that lands EXACTLY on a cell boundary (e.g. a triangle
    # whose footprint is precisely one tile wide, touching but not
    # overlapping the next cell) registers only in the cell it actually
    # covers, not the neighboring one it merely touches.
    ix0, ix1 = math.floor(min_x / tile_size), math.floor((max_x - 1e-9) / tile_size)
    iz0, iz1 = math.floor(min_z / tile_size), math.floor((max_z - 1e-9) / tile_size)
    ix1, iz1 = max(ix0, ix1), max(iz0, iz1)
    return [
        (ix, iz)
        for ix in range(ix0, ix1 + 1)
        for iz in range(iz0, iz1 + 1)
    ]


BOUNDS_MARGIN = TILE_SIZE * 3
"""Kept as a defensive cap on how far the flood-fill can wander past the
room's own modeled extent (the XZ bounding box of every walk+wall triangle
combined, expanded by this margin) -- cheap insurance against pathological
geometry, not a walkability rule. Since walkability now REQUIRES real
walk-model coverage (no default-open fallback -- see this module's own top
docstring), this is far less load-bearing than it was under the old
default-open model, where it was the ONLY thing standing between an empty
region and an unbounded flood-fill."""


@dataclass(frozen=True)
class RoomWalkableGeometry:
    """Static per-room index: walk-model triangles (CCD +0x24, walkable
    ground -- see `WalkTriangle`) and wall triangles (CCD +0x28, obstacles
    only) held separately, each bucketed by tile cell (a triangle
    registered under every cell its XZ bounding box touches) so per-tile
    lookups only scan nearby triangles, not the whole room. Build once per
    room and cache indefinitely -- geometry never changes; only a
    destination or player position does."""
    walk_triangles: tuple
    wall_triangles: tuple
    walk_buckets: dict
    wall_buckets: dict
    tile_size: float = TILE_SIZE
    bounds: tuple = None
    collision_radius: float = DEFAULT_COLLISION_RADIUS
    floor_id: object = None
    relocation_cache: dict = None
    """Memo for `_best_clearance_point`, keyed by `(tile, height)`. A plain
    mutable dict on a frozen dataclass: geometry is cached per room for the
    app's lifetime and the sub-tile scan is pure, so this is computed once
    per tile per room and reused by every later route build in that room."""
    component_cache: dict = None
    """Memo for `connected_components` -- node -> component id over the
    ordinary edge predicate, computed once per room. A route request can
    then answer "can the player's component reach this destination at all"
    with two dictionary lookups instead of a full flood.

    Computed without the player-specific `exempt_tiles`/`node_points`
    relaxations, which is the only way it can differ from the real search.
    `flow_field_toward` closes that gap exactly rather than approximately --
    see the proof in its own comment."""
    ring_cache: dict = None
    """Memo for `wall_candidates_around`, keyed by `(tiles, ring)`. Same
    rationale as `relocation_cache` -- the wall buckets never change after
    build, so a neighbourhood gathered once is valid for the room's whole
    lifetime. See that method for the profile that motivated it."""

    def walk_candidates(self, key):
        return self.walk_buckets.get(key, ())

    def wall_candidates_near(self, key_a, key_b):
        seen = set()
        result = []
        for key in (key_a, key_b):
            for triangle in self.wall_buckets.get(key, ()):
                if id(triangle) not in seen:
                    seen.add(id(triangle))
                    result.append(triangle)
        return result

    def wall_candidates_around(self, keys, ring=1):
        """Every wall triangle bucketed within `ring` cells of any of
        `keys`.

        The swept test needs a wider net than exact bucket membership: a
        wall sitting just inside a neighbouring tile can still be within the
        collision radius of a node point in this one (a tile centre is only
        `tile_size / 2` = 4.0 units from the tile edge, against a radius of
        3.5), so the endpoint tiles' own buckets alone would miss obstacles
        that genuinely block the player."""
        # Memoized on the geometry, which is immutable after build and cached
        # per room for the app's lifetime. Profiling a real `M6_out` build
        # (21354 nodes) found this single method was the largest cost in the
        # whole flood fill -- 794,449 calls, 5.4 s of 18 s -- because the
        # swept test asks for the same tile's neighbourhood once per
        # clearance query, once per occupancy test and once per edge, and the
        # frontier revisits tiles many times over.
        cache = self.ring_cache
        cache_key = (keys if isinstance(keys, tuple) else tuple(keys), ring)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        seen = set()
        result = []
        for key in cache_key[0]:
            ix, iz = key
            for dx in range(-ring, ring + 1):
                for dz in range(-ring, ring + 1):
                    for triangle in self.wall_buckets.get((ix + dx, iz + dz), ()):
                        if id(triangle) not in seen:
                            seen.add(id(triangle))
                            result.append(triangle)
        result = tuple(result)
        cache[cache_key] = result
        return result

    def in_bounds(self, key):
        if self.bounds is None:
            return True
        min_x, max_x, min_z, max_z = self.bounds
        x, z = _tile_center(key, self.tile_size)
        return min_x <= x <= max_x and min_z <= z <= max_z


def _is_interaction_volume(triangle, interaction_volumes):
    """Whether this hit-model triangle IS an interaction region's own volume.

    A CCD object may carry geometry in both the hit-model slot (+0x28) and
    the interactable slots (+0x2C/+0x30), and when it does the triangles are
    frequently identical. Such a volume is something the player walks INTO to
    trigger, so it cannot also be something they are blocked by -- see
    `region_geometry.interaction_volume_keys` for the live case (`M3_out`
    entry 33, the Relic Stone cave doorway) and the game-wide measurement.

    `None` disables the test entirely, which is what every synthetic fixture
    and offline tool wants: they supply triangles with no CCD behind them."""
    if not interaction_volumes:
        return False
    return region_geometry.triangle_key(triangle.vertices) in interaction_volumes


def build_room_geometry(walk_triangles, wall_triangles, tile_size=TILE_SIZE,
                         floor_id=None, enable_state=None,
                         collision_radius=DEFAULT_COLLISION_RADIUS,
                         interaction_volumes=None):
    """Builds the per-room walkable/obstacle index from the engine's own
    two distinct CCD models: `walk_triangles` (CCD +0x24, `WalkTriangle` --
    real walkable ground, with layer identity) and `wall_triangles` (CCD
    +0x28, `CollisionTriangle` -- obstacles, filtered here to near-vertical
    ones exactly as `predict_forward_collision` already does for the same
    data). Neither is derived from the other by a normal-angle threshold
    anymore -- each comes from its own authoritative CCD slot, parsed by
    its own dedicated function in `collision_probe.py`.

    `enable_state`/`floor_id`: if given, walk/wall triangles whose
    `entry_index` is currently disabled (see `collision_object_enable.py`)
    are excluded at build time. Defaults to `StaticObjectEnableState`
    (everything enabled) -- see that module's own docstring for why this is
    not yet live-verified. Build-time filtering means a room whose enable
    state changes DURING a session (a script disabling an object after the
    room already loaded) would need a fresh geometry build to see the
    change; that's an accepted limitation of the current static-only
    implementation, not a design goal."""
    if enable_state is None:
        enable_state = StaticObjectEnableState()
    walk_triangles = tuple(
        t for t in walk_triangles if enable_state.is_enabled(floor_id, t.entry_index))
    # !! THE COMMENT BELOW DESCRIBES A FIX THAT WAS NEVER APPLIED. !!
    #
    # It says wall triangles are deliberately NOT gated by `enable_state`.
    # They are: the filter immediately below still calls `is_enabled`, and
    # so does the shipped 0.1.0 release. So the live failure it describes
    # is, as far as anything here shows, still reproducible. Left in place
    # rather than "fixed" in passing on 2026-08-18, because the change is a
    # routing change to a painfully live-tuned system and was not what was
    # being worked on; flagged instead. Whoever picks this up owns
    # re-measuring it live in `M6_out`.
    #
    # Its intent, unchanged: `enable_state` gates WALK triangles (a disabled
    # object withdraws its floor, which CLOSES routes) but should NOT gate
    # wall triangles (which would OPEN them).
    #
    # The engine itself skips a disabled object for both models, so that is
    # knowingly less faithful in one direction -- and it is the direction
    # that matters. Opening a route on an inference walks a blind player into
    # a gap; refusing one merely declines to help.
    #
    # **Live 2026-08-14, `M6_out` (Gateon Port).** Bridge segments 23-31 carry
    # ZERO walk triangles -- only hit geometry; the walk decks are entries
    # 44-62 and are never toggled. So gating walls by enable state did
    # nothing there but delete barriers from the segments the game had
    # switched OFF. It opened 216 nodes across open water and routed the
    # project owner over spans that do not exist; they had to ignore the
    # guide to get back.
    #
    # POLARITY CORRECTED 2026-08-18: this comment used to conclude
    # "`enable == 1` means that direction is CONNECTED". It means BLOCKED --
    # see GATEON_BRIDGE_ACCESSIBILITY.md §2.4, and note that the very first
    # sentence of this paragraph ("segments 23-31 carry ZERO walk
    # triangles") is one of the facts that settles it. The observation
    # itself is unaffected: removing a switched-OFF segment's barrier opens
    # water either way, because the ground mesh (entry 45) extends across
    # it and the hit geometry is what confines the player.
    #
    # Measured: with walls left alone, `M6_out` reachability returns to
    # exactly its all-enabled value (23488, from 23704), and the Relic cave
    # is unaffected because its false wall is an interaction volume, removed
    # by the rule below rather than by enable state.
    wall_triangles = tuple(
        t for t in wall_triangles
        if abs(t.normal[1]) <= WALL_NORMAL_THRESHOLD
        and enable_state.is_enabled(floor_id, t.entry_index)
        and not _is_interaction_volume(t, interaction_volumes)
    )
    walk_buckets = {}
    for triangle in walk_triangles:
        for key in _cells_for_bounds(_triangle_xz_bounds(triangle), tile_size):
            walk_buckets.setdefault(key, []).append(triangle)
    wall_buckets = {}
    for triangle in wall_triangles:
        for key in _cells_for_bounds(_triangle_xz_bounds(triangle), tile_size):
            wall_buckets.setdefault(key, []).append(triangle)
    all_triangles = walk_triangles + wall_triangles
    bounds = None
    if all_triangles:
        xs = [vertex[0] for triangle in all_triangles for vertex in triangle.vertices]
        zs = [vertex[2] for triangle in all_triangles for vertex in triangle.vertices]
        bounds = (
            min(xs) - BOUNDS_MARGIN, max(xs) + BOUNDS_MARGIN,
            min(zs) - BOUNDS_MARGIN, max(zs) + BOUNDS_MARGIN,
        )
    return RoomWalkableGeometry(
        walk_triangles, wall_triangles, walk_buckets, wall_buckets,
        tile_size, bounds, collision_radius, floor_id, {}, {}, {})


@dataclass(frozen=True)
class WalkSurfaceCandidate:
    """One de-duplicated-by-height candidate walkable surface at a query
    point -- mirrors `GScolsys2WalkGetHeight`'s own per-XZ candidate list.
    `layers` is a `frozenset` of one element for an ordinary same-layer
    surface (`{layer_a}` when `layer_a == layer_b`) or two elements for a
    transition triangle (`{layer_a, layer_b}`) -- this single representation
    is what makes connectivity a simple set-intersection test (see
    `_connected_walk_candidate`): a same-layer tile and a transition tile
    connect exactly when their layer sets overlap, which is true for
    same-to-same, same-to-transition (stepping onto a ramp), and
    transition-to-same-on-the-other-side (stepping off it), and false for
    two unrelated same-layer surfaces that merely overlap in height."""
    height: float
    layers: frozenset
    triangle: object


def walk_height_candidates(geometry, x, z, max_candidates=WALK_MAX_CANDIDATES_PER_QUERY):
    """Companion to the engine's own `GScolsys2WalkGetHeight`: every
    distinct walkable-surface height at XZ position `(x, z)`, each carrying
    the layer identity of whichever walk-model triangle produced it.
    Triangles whose normal is too close to vertical to yield a meaningful
    plane height are skipped (see `NORMAL_VERTICAL_EPSILON`); candidates
    within `WALK_HEIGHT_DEDUP_EPSILON` of an existing one are merged, and
    the list is capped at `max_candidates`, both matching the engine's own
    behavior. Returns a list of `WalkSurfaceCandidate`, possibly empty."""
    key = _tile_key(x, z, geometry.tile_size)
    candidates = []
    for triangle in geometry.walk_candidates(key):
        if not _point_in_triangle_xz(x, z, triangle):
            continue
        ny = triangle.normal[1]
        if abs(ny) < NORMAL_VERTICAL_EPSILON:
            continue
        ax, ay, az = triangle.vertices[0]
        nx, _, nz = triangle.normal
        height = ay - (nx * (x - ax) + nz * (z - az)) / ny
        merged = False
        for existing in candidates:
            if abs(existing.height - height) < WALK_HEIGHT_DEDUP_EPSILON:
                merged = True
                break
        if merged:
            continue
        if len(candidates) >= max_candidates:
            continue
        layers = frozenset({triangle.layer_a, triangle.layer_b})
        candidates.append(WalkSurfaceCandidate(height, layers, triangle))
    return candidates


def resolve_node(geometry, position, max_ring=2):
    """Resolves `position` (a genuine known real-world point -- the
    player's live position, or a destination) to a `(tile, layers, height)`
    node, using real nearest-height selection among the walk model's
    candidate surfaces at that XZ -- exactly `GScolsys2WalkGetLayer`'s own
    algorithm. This is correct here because we have a genuine known
    reference Y (`position.y`) to disambiguate against -- unlike during
    flow-field expansion between tiles (see `_connected_walk_candidate`),
    where no such known reference exists and layer identity must govern
    connectivity instead of height proximity.

    Falls back to an expanding ring search (nearest tile with ANY walk-model
    coverage within `max_ring` cells) only when the exact tile has none --
    a defensive path for standing exactly on a seam between triangles, NOT
    a default-walkable substitute: if nothing is found, this returns `None`,
    a genuine "unmapped/unwalkable here" result, matching the project
    owner's explicit "no invented walkable surfaces" requirement."""
    tile = _tile_key(position.x, position.z, geometry.tile_size)
    candidates = walk_height_candidates(geometry, position.x, position.z)
    if candidates:
        best = min(candidates, key=lambda c: abs(c.height - position.y))
        return tile, best.layers, best.height
    ox, oz = tile
    for ring in range(1, max_ring + 1):
        best_overall = None
        for dx in range(-ring, ring + 1):
            for dz in range(-ring, ring + 1):
                if max(abs(dx), abs(dz)) != ring:
                    continue
                key = (ox + dx, oz + dz)
                cx, cz = _tile_center(key, geometry.tile_size)
                candidates = walk_height_candidates(geometry, cx, cz)
                if not candidates:
                    continue
                best = min(candidates, key=lambda c: abs(c.height - position.y))
                distance = math.dist((cx, cz), (position.x, position.z))
                if best_overall is None or distance < best_overall[0]:
                    best_overall = (distance, key, best)
        if best_overall is not None:
            _, key, best = best_overall
            return key, best.layers, best.height
    return None


DESTINATION_PROJECTION_MAX_RING = 8
"""How far, in tiles, to search outward for real floor when a destination
does not sit over any walkable surface at all.

**Live-caught 2026-08-04, `D1_garage_1F`.** Every route request in that room
failed with `cause=target_projection` before passability was ever consulted.
The room's walk model is one flat quad spanning x -106.2..105.2,
z -67.7..77.5 at y=0.0, while two of its three interactable regions sit at
z=-100.5 and z=-119.1, 47-48 units BELOW the floor -- the stairwell down to
the basement, which the floor quad does not cover. `resolve_node`'s own ring
search reaches 2 tiles (16 units) and cannot bridge a 33-unit gap, so the
warp the player selected had no seed and the guide fell back to a
straight-line beacon through walls.

8 tiles (64 units) covers that gap with margin while staying bounded. This
is a genuinely different question from `resolve_node`'s ring search, which
exists to rescue a player standing on a seam between triangles -- hence a
separate, larger, separately-named limit rather than widening that one."""

ARRIVAL_RADIUS = 4.0
"""The real arrival radius, matching `audio_guide.AudioGuideReader`'s own
`arrival_distance`. Used to build the acceptance neighbourhood for a POINT
destination, the way a region's own triangles do for a region-backed one --
see `destination_target_tiles`. It is deliberately the distance the guide
already uses to say "Arrived", not a routing-specific ceiling."""


def destination_height_band(destination_position, region=None,
                             tolerance=HEIGHT_CONTINUITY_TOLERANCE):
    """The Y range a node must be in to count as ARRIVING at a destination.

    **Live-caught 2026-08-13, `M3_out`.** Arrival was matched on tile alone,
    which discards Y -- so a node on the clifftop counted as arriving at a
    trigger volume at the bottom of the cliff. Selecting the Relic Stone
    cave exit built a confident route, walked the player 341 units across
    Agate Village, reported `route_success` at a residual of 3.68 units, and
    left them standing 83 units ABOVE the entrance with no way down from
    there. The region spans y -10.00..36.67; the player finished at y=120.

    That is the same false-`VERIFIED` failure the whole region-acceptance
    change exists to remove, reintroduced through the one axis the tile
    lattice does not model. A route may only be accepted into a node whose
    height actually lies within the trigger volume, give or take the usual
    one-surface tolerance.

    Returns `(low, high)`, or `None` when the destination is a bare point --
    those already carry their own arrival radius in XZ and have no volume to
    test against."""
    if region is None or not getattr(region, "triangles", None):
        return None
    ys = [vertex[1] for triangle in region.triangles for vertex in triangle]
    return (min(ys) - tolerance, max(ys) + tolerance)


def destination_target_tiles(geometry, destination_position, region=None):
    """Which tiles count as ARRIVING at this destination.

    Region-backed destinations (warps, doors, elevators, PCs, signs -- see
    `region_geometry.Region`) are trigger VOLUMES the player walks into, so
    every tile the region's triangles touch counts. Point destinations get
    the tiles within the real arrival radius of the point.

    Tile intersection, not a distance test, and that distinction is
    load-bearing: the lattice is 8 units and a node sits up to ~5.7 units
    from any given point in its tile, so a 4-unit proximity test can miss
    the tile the player is literally standing in. Measured in
    `M3_cave_1F_1`: a 4-unit test reported zero reachable nodes touching the
    region the player was standing in, while tile intersection correctly
    reported the two regions that genuinely route."""
    tiles = set()
    if region is not None and getattr(region, "triangles", None):
        for triangle in region.triangles:
            xs = [vertex[0] for vertex in triangle]
            zs = [vertex[2] for vertex in triangle]
            tiles.update(_cells_for_bounds(
                (min(xs), max(xs), min(zs), max(zs)), geometry.tile_size))
        return frozenset(tiles)
    # (height filtering for region destinations lives in
    # `destination_height_band`, applied by the caller alongside these
    # tiles -- see that function for the live failure that required it.)
    centre = _tile_key(
        destination_position.x, destination_position.z, geometry.tile_size)
    tiles.add(centre)
    reach = int(math.ceil(ARRIVAL_RADIUS / geometry.tile_size))
    for dx in range(-reach, reach + 1):
        for dz in range(-reach, reach + 1):
            key = (centre[0] + dx, centre[1] + dz)
            cx, cz = _tile_center(key, geometry.tile_size)
            if math.dist((cx, cz), (destination_position.x,
                                    destination_position.z)) <= ARRIVAL_RADIUS + geometry.tile_size / 2.0:
                tiles.add(key)
    return frozenset(tiles)


_REMOVED_REACHABILITY_FALLBACK_MAX_OFFSET = """
**Removed 2026-08-12.** A reseed used to be accepted when its offset from
the destination's projected floor position was within 64 units. Measured
across every interaction-point pair in the game, that rule accepted 2024
routes of which only 265 were locally useful -- it misled the player 86.9%
of the time it fired.

Distance turned out to have essentially no predictive power. Measuring local
walkable connectivity from each accepted reseed to the destination's own
interaction region:

    distance to region   useful / total
    <= 4 units            103 / 103   100.0%
    4 - 8                  46 / 480     9.6%
    8 - 16                 54 / 478    11.3%
    16 - 32                22 / 440     5.0%
    > 32                   40 / 523     7.6%

Above the real 4-unit arrival radius the hit rate is 5-11% in EVERY band,
including the nearest -- and the >32 band scores better than 16-32. There is
no threshold to find because the signal is not there. 74.4% of reseeds
landing within 8 units of their destination were still on the far side of a
wall from it. Every candidate distance ceiling (16, 32, 64 units, measured
to the anchor or to the region) accepted a route that misled the player
79-87% of the time.

What DOES predict usefulness is whether an ordinary walkable path exists
from the reseed into the destination's interaction region -- the same walk
layers, wall tests, collision radius, corner rules and floor support the
flood fill itself uses, with no second projection or fallback underneath.
`flow_field_toward` now requires exactly that, so a reseed is accepted only
when the resulting field is a continuous ordinary route into the region.

Consequences, measured and accepted:

- `M3_cave_1F_1`: the shrine exit refuses (its region shares no reachable
  tile with the player), while regions 1 and 2 -- the pair that genuinely
  connects -- still route.
- `D1_garage_1F`: region 1 routes. Both basement warps refuse, because they
  are 48-60 units below a floor that does not extend under them: there is no
  walk surface beneath either region anywhere in this room. They only ever
  "worked" by guiding 70 units to a spot by the south wall. That is the
  cross-level case, and refusing it is the honest answer rather than a
  regression to be exempted.
"""
DESTINATION_PROJECTION_MAX_VERTICAL_GAP = HEIGHT_CONTINUITY_TOLERANCE
"""How far VERTICALLY a destination may be projected onto floor.

The ring search above is purely horizontal: it takes the nearest tile with
walk-model coverage and ignores how far below or above the destination
actually sits. Measured 2026-08-04 (late) against the live failure it was
built for -- `D1_garage_1F`'s basement warp at y=-48.24 -- it projected that
destination onto the ground-floor plane at y=0.0, a **48.2-unit** vertical
jump, and seeded the route in a connected component the player cannot reach.
The result was a six-node route pointing into the wall at the south end of
the garage while the real target was down a stairwell.

A destination on another storey is not "slightly off-surface"; it is the
cross-level case, which this module does not solve. Reusing
`HEIGHT_CONTINUITY_TOLERANCE` is deliberate: that constant is already this
module's measured answer to "are these two heights the same connected
surface", so projection and connectivity now agree about what one level is
rather than each having its own idea."""


def _resolve_at_own_column(geometry, position, own_tile, height_band=None):
    """The walk surface a destination sits on, at its OWN XZ only.

    Deliberately never ring-searches -- that is the caller's job, under the
    caller's vertical guard. `resolve_node` does have its own 2-ring
    fallback, and letting it fire here is precisely the defect this replaces:
    it returns a surface from some other column at any height, which the
    caller then trusted as an in-place seed.

    `height_band` is the destination region's own vertical extent (see
    `destination_height_band`). Where it admits at least one of this column's
    surfaces, selection is restricted to those; where it admits none, the
    band is ignored and the nearest-Y surface is used exactly as before.

    That asymmetry is deliberate and measured. Over all 843 interaction
    regions in the game, the surface beneath a region's anchor lies inside
    that region's own band in 835 cases, has no surface at all in 6, and
    falls outside in 2 (`D6_fort_4F` 9, `S3_labo_B1up` 1). Making the band a
    hard gate would refuse those 2 outright and gain nothing measurable, so
    it filters when it can and abstains when it cannot -- it may re-rank the
    candidates at a column, never empty it.

    (The tighter alternative, gating on `position.y` +-
    `DESTINATION_PROJECTION_MAX_VERTICAL_GAP`, was measured and rejected: 95
    of 843 regions sit further than that above their own floor, with no
    in-gap candidate anywhere at their XZ, so it would refuse all 95.)"""
    candidates = walk_height_candidates(geometry, position.x, position.z)
    if not candidates:
        return None
    if height_band is not None:
        low, high = height_band
        in_band = [c for c in candidates if low <= c.height <= high]
        if in_band:
            candidates = in_band
    best = min(candidates, key=lambda c: abs(c.height - position.y))
    return own_tile, best.layers, best.height


def resolve_destination_node(geometry, position, max_ring=DESTINATION_PROJECTION_MAX_RING,
                              max_vertical_gap=DESTINATION_PROJECTION_MAX_VERTICAL_GAP,
                              height_band=None):
    """Where should a route toward `position` actually END?

    Normally the destination's own tile. But a destination need not sit over
    walkable floor at all: warps, doors and PCs are frequently placed down a
    stairwell, on a ledge, or inside a wall recess that the room's walk
    model does not cover (see `DESTINATION_PROJECTION_MAX_RING`).

    Returns `(tile, layers, height, offset)` where `offset` is how far the
    seed had to move, in world units -- 0.0 when the destination projected
    directly. Returns `None` only if no real floor exists within `max_ring`.

    **This can only turn a failed route into a route; it never alters one
    that already builds.** It runs solely after `resolve_node` has already
    returned None, so rooms whose destinations project normally -- including
    every rich-walk-model room validated so far -- take the identical path
    they took before.

    Routing to the nearest reachable floor is also the honest answer rather
    than a fudge: the audio guide judges ARRIVAL against the real, un-snapped
    entity position and its own `arrival_distance`, never against a tile, so
    the player is guided across the room to the foot of the stairs and the
    final approach degrades to direct guidance automatically -- which is
    what a sighted player does too."""
    own_tile = _tile_key(position.x, position.z, geometry.tile_size)
    direct = _resolve_at_own_column(geometry, position, own_tile, height_band)
    if direct is not None:
        if not _swept_circle_node_blocked(geometry, direct[0], direct[2]):
            # No vertical guard needed on THIS branch: the destination moved
            # nowhere (offset 0.0), and `resolve_node` picked the nearest of
            # the walk surfaces genuinely present at the destination's own
            # XZ. That is the right answer for anything placed above its own
            # ground -- including `M3_out`'s worldmap exit, a live-proven
            # route whose warp sits well above the terrace it belongs to.
            return direct + (0.0,)
    # Reached when the destination's own column has no walk surface at all,
    # or has one the player could not stand on. Both fall to the lateral ring
    # search below, under its `max_vertical_gap` guard -- routing to the
    # counter's edge is useful, routing into the counter is not.
    #
    # This is where the surface-flip lived (live 2026-08-13, `M3_out` region
    # 6, the Relic Stone cave trigger): a 2-triangle vertical curtain at
    # z=-23.86 spanning x -39.58..5.18, y -10.00..36.67, standing on the cave
    # floor at y=-5.04 -- but that floor only exists beneath roughly
    # x -32..-1. The region's own nearest-point produces a destination out at
    # x=-38.04 whenever the player is that far west, where there is no
    # candidate at all. The old code called `resolve_node`, whose OWN 2-ring
    # fallback then returned the CLIFFTOP two tiles away at y=120.00 -- 130
    # units above the trigger -- and accepted it as an in-place seed with
    # offset 0.0 and no vertical test. The route targeted the clifftop (1637
    # nodes, "8 units away") instead of the cave (1861 nodes, "686 units
    # away"), flipping with the player's x.
    #
    # `_resolve_at_own_column` no longer ring-searches, so that case arrives
    # here instead, and this search refuses any surface further than
    # `max_vertical_gap` from the destination's own Y -- for a region-backed
    # destination, the region's floor (`Region.anchor[1]`, the minimum Y of
    # its own triangles). The clifftop is 130 units from it and correctly
    # refused; the cave floor is 4.96 and accepted. The destination's surface
    # is thereby a property of the region, not of where the player stands.
    origin = _tile_key(position.x, position.z, geometry.tile_size)
    ox, oz = origin
    for ring in range(1, max_ring + 1):
        best = None
        for dx in range(-ring, ring + 1):
            for dz in range(-ring, ring + 1):
                if max(abs(dx), abs(dz)) != ring:
                    continue
                key = (ox + dx, oz + dz)
                cx, cz = _tile_center(key, geometry.tile_size)
                candidates = walk_height_candidates(geometry, cx, cz)
                if not candidates:
                    continue
                surface = min(
                    candidates, key=lambda c: abs(c.height - position.y))
                if abs(surface.height - position.y) > max_vertical_gap:
                    # Another storey, not an off-surface placement on this
                    # one -- see DESTINATION_PROJECTION_MAX_VERTICAL_GAP.
                    continue
                if _swept_circle_node_blocked(geometry, key, surface.height):
                    # Never seed a route inside an obstacle: the player
                    # could not stand there to "arrive".
                    continue
                distance = math.dist((cx, cz), (position.x, position.z))
                if best is None or distance < best[0]:
                    best = (distance, key, surface)
        if best is not None:
            distance, key, surface = best
            return key, surface.layers, surface.height, distance
    return None


def _height_allowance(geometry, from_point, to_point, tolerance):
    """How much height two node points may differ by and still be one
    continuous surface.

    `HEIGHT_CONTINUITY_TOLERANCE` is a per-STEP limit, calibrated when every
    node sat at its tile centre and neighbours were therefore exactly
    `tile_size` apart. Node relocation (`_best_clearance_point`) broke that
    assumption: it picks each tile's roomiest point independently, so two
    adjacent tiles' nodes can move in opposite directions and end up much
    further apart than one tile.

    **Live 2026-08-14, `M3_out`.** The project owner walked down the hillside
    at z~82 -- measured from their own positions, a ~42 degree slope dropping
    7-8 units per 8 units travelled, comfortably inside the tolerance. But
    the graph refused every downhill edge off the terrace: tile (5,11)'s node
    had relocated to (41,95) and tile (5,10)'s to (47,81), **15.2 units
    apart** rather than 8, and the resulting 18.92-unit height difference was
    compared against a limit meant for a single 8-unit step. Every route down
    that hill was refused, so the flow field detoured east hunting for a
    shallower way in and walked the player in circles at the cliff edge.

    Treating the constant as a GRADIENT instead of a step restores what it
    was always measuring -- how steep a surface may be and still be walkable
    -- and makes it independent of where relocation happened to put the two
    nodes. At the nominal one-tile spacing the allowance is exactly the old
    value, so no edge that used to be open closes."""
    distance = math.dist(from_point, to_point)
    return max(tolerance, tolerance * distance / geometry.tile_size)


def _connected_walk_candidate(geometry, x, z, from_layers, from_height,
                               tolerance=HEIGHT_CONTINUITY_TOLERANCE,
                               from_point=None):
    """Find the walk-model surface at `(x, z)` that is actually reachable
    from a tile whose current layer set is `from_layers` -- the PRIMARY
    connectivity gate is layer-set intersection (a same-layer surface, or
    an explicit transition triangle sharing a layer with `from_layers`),
    NOT height proximity. `tolerance` is applied only AFTER that gate
    already passed -- a defensive check within an already layer-validated
    relationship (see `HEIGHT_CONTINUITY_TOLERANCE`'s own docstring), never
    a substitute for it. Returns `(height, layers)` for the best-matching
    connected candidate, or `None` if nothing at this point connects to
    `from_layers` at all."""
    candidates = walk_height_candidates(geometry, x, z)
    connected = [c for c in candidates if c.layers & from_layers]
    allowance = tolerance if from_point is None else _height_allowance(
        geometry, from_point, (x, z), tolerance)
    connected = [c for c in connected if abs(c.height - from_height) <= allowance]
    if not connected:
        return None
    best = min(connected, key=lambda c: abs(c.height - from_height))
    return best.height, best.layers


# `_segment_blocked` and its GAP_SAMPLE_OFFSETS lived here until
# 2026-08-04 (late). It opened a tile-to-tile edge whenever ANY ONE of five
# sampled lines was clear, which is why the flood fill walked through
# furniture -- see the block comment above HEIGHT_CONTINUITY_TOLERANCE.
#
# The real finding it encoded is kept, because it still constrains the
# design: a genuine ~2-unit-wide doorway in `M3_out.ccd` (open at z=38-39,
# blocked at z=40 through 58) falls entirely BETWEEN two tile-row centres,
# so a single centre-to-centre line walks straight past the one spot a
# player can actually fit through. That is a RESOLUTION problem, and
# `_best_clearance_point` answers it properly by moving the node to the
# roomiest point in its tile, rather than by weakening the obstacle test
# until the doorway happens to fall through it.


def _point_segment_distance(px, pz, start, end):
    ax, az = start
    bx, bz = end
    dx, dz = bx - ax, bz - az
    length_squared = dx * dx + dz * dz
    if length_squared < 1e-12:
        return math.dist((px, pz), start)
    t = max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / length_squared))
    return math.dist((px, pz), (ax + t * dx, az + t * dz))


def _segment_segment_distance(p0, p1, q0, q1):
    """Minimum distance between two 2D segments. Zero if they intersect."""
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = orient(q0, q1, p0), orient(q0, q1, p1)
    d3, d4 = orient(p0, p1, q0), orient(p0, p1, q1)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(
        _point_segment_distance(p0[0], p0[1], q0, q1),
        _point_segment_distance(p1[0], p1[1], q0, q1),
        _point_segment_distance(q0[0], q0[1], p0, p1),
        _point_segment_distance(q1[0], q1[1], p0, p1),
    )


def _wall_spans_height(triangle, height, band=WALL_HEIGHT_BAND):
    """Whether this hit-model triangle reaches the body of someone standing
    at `height` -- see `WALL_HEIGHT_BAND`. Keeps another floor's furniture
    out of this floor's obstacle set."""
    ys = [vertex[1] for vertex in triangle.vertices]
    return not (max(ys) < height - 0.5 or min(ys) > height + band)


NODE_RELOCATION_OFFSETS = (-0.375, -0.1875, 0.0, 0.1875, 0.375)
"""Sub-tile sampling positions, as fractions of `tile_size`, used to place a
tile's node at the roomiest point inside it instead of mandatorily at its
centre (see `_best_clearance_point`).

Includes 0.0 so a tile whose centre is already the best point keeps exactly
its old node, and stops at +-0.375 rather than +-0.5 so a relocated node
stays well inside its own tile and two neighbours' nodes cannot collapse
onto each other.

**Why relocation rather than a smaller `TILE_SIZE`.** Measured 2026-08-04
(late): halving the tile size moved `M3_pc_1F` from 23.7% to 28.7%
reachable, because the problem was never sampling density -- it is that the
graph may only ever place a node at one specific point per tile, and free
space is not aligned to the lattice. Relocation fixes the placement instead
of multiplying the samples, so node count, `MAX_TILES`, build time and every
existing per-tile diagnostic stay directly comparable to before."""


# A "skip the sub-tile scan when the centre is already wide open" fast path
# was tried here and REMOVED (2026-08-04, late). Once `wall_candidates_around`
# was memoized it saved nothing measurable (`M6_out` 6.02 s against 5.99 s),
# and it was not exactly equivalent -- `D1_labo_B2` came out with 176 nodes
# against 175. A shortcut that changes the answer has to earn it; this one
# did not.


def _best_clearance_point(geometry, key, height):
    """The point inside this tile with the most room around it, cached.

    This is the whole of the resolution fix: a corridor the player fits
    through can miss every tile centre while still passing cleanly through
    the tile, and today that tile is simply absent from the graph.
    `diagnose_unreachable` already sub-samples exactly this way to tell
    `grid_alignment` from `radius_clearance` -- this lets the graph USE the
    point that diagnostic finds instead of only reporting that it exists.

    Returns `(point, clearance)`. The caller decides whether `clearance` is
    enough, so this never applies the radius itself."""
    cache = geometry.relocation_cache
    cache_key = (key, round(height, 3))
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    size = geometry.tile_size
    cx, cz = _tile_center(key, size)
    if not geometry.wall_candidates_around((key,)):
        # No obstacle anywhere near this tile, so clearance is infinite at
        # every point in it and no sample can beat any other. Exactly what
        # the scan below now returns, and by far the common case outdoors --
        # `M6_out` is 21000+ nodes of mostly open ground.
        best = ((cx, cz), math.inf)
        cache[cache_key] = best
        return best
    # The centre is seeded FIRST and displaced only by a strictly better
    # sample, so a tile with uniform clearance keeps its centre.
    #
    # **Bug fixed here 2026-08-04 (late).** The loop used to start with
    # `best = None`, so the first sample it took -- offsets
    # (-0.375, -0.375), the tile's CORNER -- won every tie. On any tile where
    # clearance is uniform (all of open ground, where it is infinite
    # everywhere) the node was therefore placed at the corner, not the
    # centre, which is the exact opposite of what this function's own
    # comment claimed. It survived because `NODE_RELOCATION_OFFSETS` reads
    # centre-first and the comment asserted the loop did too. Caught by the
    # short-circuit above changing `M6_out`'s node count when it should have
    # been provably equivalent.
    best = ((cx, cz), _point_clearance(geometry, key, (cx, cz), height))
    for fraction_x in NODE_RELOCATION_OFFSETS:
        for fraction_z in NODE_RELOCATION_OFFSETS:
            if fraction_x == 0.0 and fraction_z == 0.0:
                continue
            point = (cx + fraction_x * size, cz + fraction_z * size)
            clearance = _point_clearance(geometry, key, point, height)
            if clearance > best[1]:
                best = (point, clearance)
    cache[cache_key] = best
    return best


def node_point(geometry, key, node_points=None, height=None):
    """Where this tile's graph node actually sits in XZ.

    In order: an explicit override, then the roomiest point inside the tile,
    then the tile centre.

    Overrides come from `node_points` and describe tiles where a better
    point is KNOWN rather than computed -- currently only the tile the
    player is demonstrably standing in, whose real live position beats any
    sampled estimate of that tile.

    Relocation applies whenever a `height` is supplied. It used to be
    restricted to hit-model-authority rooms, which is exactly what left
    `M3_out`'s route pinned to tile centres sitting 0.10 units from a cliff
    face -- and then had that pinning cited as proof a swept test could not
    work outdoors. See the block comment above HEIGHT_CONTINUITY_TOLERANCE.
    Callers with no height (plain tile geometry, diagnostics) still get the
    centre."""
    if node_points:
        override = node_points.get(key)
        if override is not None:
            return override
    if height is not None:
        return _best_clearance_point(geometry, key, height)[0]
    return _tile_center(key, geometry.tile_size)


def _point_clearance(geometry, key, point, height):
    """Distance from `point` to the nearest height-relevant obstacle."""
    best = math.inf
    for triangle in geometry.wall_candidates_around((key,)):
        if not _wall_spans_height(triangle, height):
            continue
        wall_start, wall_end = _triangle_longest_edge_xz(triangle)
        if math.dist(wall_start, wall_end) < 1e-5:
            continue
        distance = _point_segment_distance(
            point[0], point[1], wall_start, wall_end)
        if distance < best:
            best = distance
    return best


def _effective_radius(geometry, key_a, key_b, height, node_points,
                       exempt_tiles):
    """The radius an edge incident to an EXEMPT tile should actually be
    tested at.

    An exempt tile is one the player is demonstrably standing in, so its
    occupiability is a live fact rather than an inference. Testing edges out
    of it at the nominal radius contradicts that fact: measured live in
    `D1_garage_1F`, the player stood 3.495 units from the south wall while
    the nominal radius is 3.500, so EVERY edge leaving their tile was
    rejected on the clearance of the one endpoint already known to be
    occupied -- not because anything obstructed the path. The route field
    then could not contain the player, and `flow_field_toward` returned no
    route at all.

    So an exempt endpoint lowers the bar to its own observed clearance:
    "whatever the player currently fits through, they fit through." This is
    self-calibrating from live evidence rather than a tolerance tuned by
    ear, it can only ever relax edges touching the single tile the player
    occupies, and it collapses to the nominal radius the moment they are
    standing somewhere with normal clearance."""
    radius = geometry.collision_radius
    if not exempt_tiles:
        return radius
    for key in (key_a, key_b):
        if key not in exempt_tiles:
            continue
        observed = _point_clearance(
            geometry, key, node_point(geometry, key, node_points, height),
            height)
        if observed < radius:
            radius = observed
    return radius


def _swept_points_blocked(geometry, start, end, height, radius, tiles=None):
    """Can a circle of `radius` travel from XZ point `start` to `end`
    without touching a hit-model wall that reaches `height`?

    Takes raw points rather than tile keys so the same primitive serves both
    the flood fill's tile-to-tile edges and `simplify_route`'s arbitrary
    line-of-sight segments. `tiles` names which cells to gather wall
    candidates from; when omitted, every cell the segment passes through is
    used (plus a ring, since a wall just outside a cell can still be within
    the radius of a line through it).

    This mirrors what the engine itself does to move the player
    (`GScolsys2HitCollision` with `peopleInfoBiosGetColBallSize`), rather
    than approximating it with sampled lines."""
    if tiles is None:
        size = geometry.tile_size
        length = math.dist(start, end)
        steps = max(1, int(length / (size * 0.5)) + 1)
        tiles = {
            _tile_key(start[0] + (end[0] - start[0]) * i / steps,
                      start[1] + (end[1] - start[1]) * i / steps, size)
            for i in range(steps + 1)
        }
    for triangle in geometry.wall_candidates_around(tiles):
        if not _wall_spans_height(triangle, height):
            continue
        wall_start, wall_end = _triangle_longest_edge_xz(triangle)
        if math.dist(wall_start, wall_end) < 1e-5:
            continue
        if _segment_segment_distance(start, end, wall_start, wall_end) < radius:
            return True
    return False


def _swept_circle_blocked(geometry, key_a, key_b, height, node_points=None,
                           exempt_tiles=frozenset()):
    """`_swept_points_blocked` between two tiles' node points. The single
    passability gate for every room -- see the block comment above
    HEIGHT_CONTINUITY_TOLERANCE for why there is no longer a second one."""
    radius = _effective_radius(
        geometry, key_a, key_b, height, node_points, exempt_tiles)
    start = node_point(geometry, key_a, node_points, height)
    end = node_point(geometry, key_b, node_points, height)
    return _swept_points_blocked(
        geometry, start, end, height, radius, (key_a, key_b))


def _swept_circle_node_blocked(geometry, key, height, node_points=None):
    """Whether the player can even STAND at this tile's node point.

    Without this, the flood fill happily seeds and routes through tiles
    whose centres sit inside a counter: the edge test alone alone only asks
    about travel between centres, so a tile fully enclosed in furniture
    still enters the graph.

    With relocation the question sharpens from "is this tile's centre
    clear" to "is ANY point in this tile clear", which is the question that
    was always meant -- a tile is unusable only when the player genuinely
    cannot stand anywhere in it."""
    point = node_point(geometry, key, node_points, height)
    return _point_clearance(geometry, key, point, height) < geometry.collision_radius


def _try_edge(geometry, from_key, from_height, from_layers, to_key,
               exempt_tiles=frozenset(), node_points=None,
               blocked_segments=()):
    """Returns `(height, layers)` for `to_key` if it's walkably connected
    from `from_key`/`from_layers`/`from_height`: `to_key` is within the
    room's overall geometry bounds, the walk model has a surface there that
    shares a layer with `from_layers` (see `_connected_walk_candidate` --
    this is the real walkability gate now, not floor-triangle presence or
    height proximity alone), and the straight tile-to-tile segment doesn't
    cross a wall triangle. Returns `None` if any of those fail."""
    if not geometry.in_bounds(to_key):
        return None
    # Ask for floor support where the node will actually SIT, not at the
    # tile centre it may have moved away from. `from_height` picks the
    # relocation (rather than the height we are about to look up, which
    # would be circular); `_connected_walk_candidate` then validates the
    # real height and layer of whatever surface is found there.
    x, z = node_point(geometry, to_key, node_points, from_height)
    # Floor support is required regardless: the hit model has authority over
    # obstacles, never over whether there is ground here.
    connected = _connected_walk_candidate(
        geometry, x, z, from_layers, from_height,
        from_point=node_point(geometry, from_key, node_points, from_height))
    if connected is None:
        return None
    # A tile the player is DEMONSTRABLY standing in is occupiable, whatever
    # the tile-centre heuristic says. Live 2026-08-04, `D1_garage_1F`: the
    # player stood at (77.57, 0.00, -48.76) in tile (9,-7) with the route
    # seeded in the adjacent tile (9,-6), and was still reported unlinked
    # on every poll -- because that tile's CENTRE sits within the collision
    # radius of a wall, so the flood fill refused to enter the one tile it
    # had direct evidence was standable. Their real position was 4.4 units
    # from the centre; the tile is 8 units across, and only the centre is
    # tested. See `exempt_tiles`.
    #
    # The exemption covers the OCCUPANCY test only -- never the
    # wall-crossing test. Exempting both (as this did until 2026-08-04
    # late) lets the flood enter the player's tile straight THROUGH a
    # wall, which is exactly how the garage's six-tile pocket acquired
    # the player as a member: edges (9,-8)->(8,-7) and (8,-8)->(8,-7)
    # are both genuinely swept-blocked, so `origin_node in
    # field.node_height` reported True for a tile the player could not
    # actually reach from the seed, and `flow_field_toward`'s
    # reachability fallback never fired. "You are standing here" is
    # evidence about the tile, not about the route into it.
    height = connected[0]
    if (to_key not in exempt_tiles
            and _swept_circle_node_blocked(geometry, to_key, height,
                                            node_points)):
        return None
    if _swept_circle_blocked(geometry, from_key, to_key, height,
                              node_points, exempt_tiles):
        return None
    # Last, because it is the only test that asks about consequences rather
    # than geometry: this leg is walkable, but taking it would fire a
    # trigger the route was not asked to fire. See `blocked_segments` on
    # `flow_field_from`.
    if blocked_segments and _crosses_blocked_segment(
            node_point(geometry, from_key, node_points, from_height),
            (x, z), blocked_segments):
        return None
    return connected


TRIGGER_CROSSING_MARGIN = 1.0
"""How close, in world units, a route leg may pass to a trigger curtain it
is not allowed to fire.

Small deliberately. The first version of this test blocked whole TILES that
a trigger touched, which is 8 units of rounding in every direction, and
measured on `M6_out` that collapsed the player's reachable component from
23,488 tiles to 1,961: Gateon Port's doors sit in narrow gaps between
buildings, so swallowing the gap swallowed the route through it. Blocking
the CROSSING instead leaves the gap open and only refuses legs that
actually pass through the curtain, which is the thing that fires it.

Not zero, because a leg grazing the curtain's own plane is not meaningfully
different from crossing it, and float geometry should not decide which."""


def region_crossing_segments(region):
    """A region's triangles as XZ segments, for `blocked_segments`.

    Warp curtains are vertical planes -- every one measured in `M6_out` has
    zero depth in one axis and 25-75 units of height -- so their XZ shadow
    is a line, and each triangle contributes its own longest projected edge.
    Using the longest edge (rather than all three) is exact for a plane seen
    from above and conservative for anything else, since the longest edge
    spans the triangle's whole footprint."""
    segments = []
    for triangle in region.triangles:
        projected = [(vertex[0], vertex[2]) for vertex in triangle]
        pairs = ((0, 1), (1, 2), (2, 0))
        a, b = max(pairs, key=lambda pair: math.dist(
            projected[pair[0]], projected[pair[1]]))
        if math.dist(projected[a], projected[b]) < 1e-6:
            continue
        segments.append((projected[a], projected[b]))
    return tuple(segments)


def _crosses_blocked_segment(start, end, blocked_segments,
                              margin=TRIGGER_CROSSING_MARGIN):
    """Does the leg from `start` to `end` pass through a trigger curtain?

    Reuses `_segment_segment_distance`, the same primitive the swept wall
    test already uses, so a curtain is refused on exactly the geometry a
    wall would be."""
    if not blocked_segments:
        return False
    for segment_start, segment_end in blocked_segments:
        if _segment_segment_distance(
                start, end, segment_start, segment_end) <= margin:
            return True
    return False


def uniform_edge_cost(geometry, from_key, to_key):
    """Default edge cost: plain tile-hop distance (1.0 orthogonal, sqrt(2)
    diagonal) -- "lowest amount of walkable tiles," per the first-version
    spec. Takes `geometry` (unused here) so a future weighted cost function
    (turn penalties, narrow-passage penalties, terrain costs, etc.) can plug
    in with the same signature without restructuring the search below."""
    ix_a, iz_a = from_key
    ix_b, iz_b = to_key
    return math.hypot(ix_b - ix_a, iz_b - iz_a)


@dataclass(frozen=True)
class FlowField:
    """`next_hop`/`node_height`/`cost_so_far` are all keyed by NODE --
    `(tile, layers)`, not a bare tile -- since two different layers can
    occupy the same XZ tile with entirely different connectivity (the exact
    terraced-overlap case this rewrite fixes). `destination_node` is the
    seeded `(tile, layers)` the search flooded outward from."""
    next_hop: dict
    node_height: dict
    cost_so_far: dict
    destination_node: tuple
    tile_size: float
    stats: object = None
    """Build diagnostics -- see `flow_field_from`. A plain dict so callers
    can log it without this module knowing anything about logging."""
    node_points: object = None
    """Resolved per-tile XZ node positions, carried so `node_position`
    reports the same point the passability tests actually used -- otherwise
    the guide would steer toward a tile centre the route never validated.
    `None` means every node sits at its tile centre, which is every
    rich-walk-model room."""

    def node_position(self, node):
        tile, _ = node
        if self.node_points:
            point = self.node_points.get(tile)
            if point is not None:
                return Position(point[0], self.node_height[node], point[1])
        x, z = _tile_center(tile, self.tile_size)
        return Position(x, self.node_height[node], z)


def connected_components(geometry):
    """`{tile: component_id}` over the ordinary edge predicate.

    **Not used by routing. Kept for diagnostics only -- see the measurement
    below before wiring it into anything hot.**

    It was briefly used as a fast-refusal shortcut in `flow_field_toward`,
    on the reasoning that answering "can the player's component reach this
    destination" from a cached map beats a second flood of a 21000-node
    room. Measured on `M6_out`, the room that reasoning was aimed at, one
    route request took:

        with the shortcut     29.10 s
        without                2.28 s

    Building the map floods the WHOLE room through `_try_edge` before it can
    answer anything, which costs far more than the single flood it avoids --
    and the player pays it on their first activation in the room, which is
    exactly the moment that must not stall. It was removed the same day it
    was added.

    Recorded rather than deleted because the idea is sound in principle and
    will occur to the next person: it needs an incremental or lazily-bounded
    component structure, not a full-room flood, to be worth having."""
    raise NotImplementedError(
        "connected_components was removed from routing after measurement; "
        "see its docstring")


def flow_field_toward(geometry, destination_position, origin_position,
                       edge_cost=uniform_edge_cost, max_tiles=MAX_TILES,
                       blocked_nodes=frozenset(), destination_region=None,
                       blocked_segments=()):
    """`flow_field_from`, but guaranteed to be seeded somewhere the player
    can actually reach when the destination itself is off-floor.

    Needed because "nearest floor to the destination" and "floor the player
    can get to" are not the same tile. Live, `D1_garage_1F`: both basement
    warps recovered a seed 40.5 and 59.2 units away, the field built
    successfully -- and the player was still reported unlinked, because the
    recovered tiles sit in a pocket separate from the player's own region
    (that room's largest connected component is only 41% of its floored
    tiles).

    Strategy: try the direct seed first, since that is the common case and
    costs nothing extra. Only if the origin is missing from the resulting
    field -- or the destination could not be seeded at all -- do we flood
    outward from the ORIGIN instead, take the reachable tile closest to the
    true destination, and rebuild seeded there. The second flood is the
    price of an off-floor destination, not of ordinary routing.

    **The `field is None` case is the cross-level one** (2026-08-04, late).
    Since `resolve_destination_node` refuses to project across a storey (see
    `DESTINATION_PROJECTION_MAX_VERTICAL_GAP`), a basement warp seeded from
    the ground floor now yields no field at all. Falling through to the
    same reachability search turns that into the genuinely useful answer --
    guide to the reachable point nearest the stairwell, then hand off to the
    beacon -- instead of either a route into a wall (what projecting
    produced) or no guidance whatsoever (what refusing alone would).

    Returns the same `FlowField` as `flow_field_from`, or None."""
    origin_seed = (resolve_node(geometry, origin_position)
                   if origin_position is not None else None)
    # The player's own tile is exempt from the tile-centre OCCUPANCY test in
    # both floods: standing there is direct evidence it is occupiable. It is
    # never exempt from the wall-crossing test -- see `_try_edge`.
    exempt = frozenset({origin_seed[0]}) if origin_seed else frozenset()
    # ...and within that tile we know exactly where they are, which is a
    # strictly better sample of it than its centre. See `node_point`.
    points = ({origin_seed[0]: (origin_position.x, origin_position.z)}
              if origin_seed else None)
    # The destination region's own vertical extent, used to keep the seed on
    # the surface the region belongs to rather than whichever surface happens
    # to be nearest -- see `_resolve_at_own_column`. Computed once here; the
    # same band already governs ARRIVAL below, so seeding and arrival now
    # agree about which storey the destination is on instead of each deciding
    # separately.
    seed_band = destination_height_band(destination_position, destination_region)
    field = flow_field_from(
        geometry, destination_position, edge_cost, max_tiles, blocked_nodes,
        exempt, points, seed_band, blocked_segments)
    if origin_seed is None:
        return field
    origin_node = (origin_seed[0], origin_seed[1])
    if field is not None and origin_node in field.node_height:
        return field
    # The direct seed did not reach the player. Retry ONCE, seeded on the
    # destination's own arrival tiles, and accept only if that produces a
    # continuous ordinary route back to the player.
    #
    # Why this and not "nearest reachable point": see the block comment on
    # `ARRIVAL_RADIUS`/`destination_target_tiles` and the removal note above.
    # Distance-based acceptance misled the player in 86.9% of the routes it
    # accepted; local connectivity into the destination's own interaction
    # region is what actually predicts usefulness.
    #
    # There is no second fallback inside this. Every edge below is the
    # ordinary `_try_edge` predicate -- same walk layers, wall tests,
    # collision radius, corner rules, floor support and transitions the
    # flood fill uses everywhere else. If no arrival tile is reachable, the
    # answer is no route.
    targets = destination_target_tiles(
        geometry, destination_position, destination_region)
    # Fast refusal. Connected components are computed once per room, so
    # asking "is any arrival tile even in the player's component" is two
    # dictionary lookups against a second full flood -- which in `M6_out`
    # (21000 nodes) is most of a six-second build.
    #
    reachable = flow_field_from(
        geometry, origin_position, edge_cost, max_tiles, blocked_nodes, exempt,
        points, None, blocked_segments)
    if reachable is None:
        return None
    band = seed_band
    """Arrival uses the same band the seed did -- see `seed_band` above."""
    best = None
    for node, height in reachable.node_height.items():
        if node[0] not in targets:
            continue
        if band is not None and not (band[0] <= height <= band[1]):
            # Standing above or below the trigger is not arriving at it.
            # See `destination_height_band` for the clifftop route this
            # rejects.
            continue
        cost = reachable.cost_so_far.get(node, math.inf)
        if best is None or cost < best[0]:
            best = (cost, node, height)
    if best is None:
        # Nothing the player can walk to is inside the destination itself.
        #
        # **This is where refusing outright was wrong** (live, 2026-08-13).
        # Agate's Relic Stone cave sits in a 26-node pocket the graph never
        # joins, and the nearest reachable ground is 7.3 units from its mouth
        # horizontally -- the doorstep. The player had been using that: walk
        # to there, then step down. Refusing took a working journey away.
        #
        # The old rule delivered it by calling that point the route and
        # reporting VERIFIED, which is how the same mechanism also walked
        # people 1678 units to the wrong place in silence. Both problems come
        # from the CLAIM, not the guidance. So guidance is offered and the
        # claim is dropped: this returns a field flagged `partial`, carrying
        # how far short it stops, and the guide says so out loud.
        #
        # That is also why there is no distance ceiling here. A ceiling was
        # only ever a proxy for "is this claim safe to make", and measurement
        # showed no distance predicts that (see the removal note above).
        # Saying "seven units short" and saying "sixteen hundred units short"
        # are both honest; the player decides which is worth walking.
        # Resolve the walk surface once with the same region evidence used by
        # the real destination seed.  A region's full Y span is not itself a
        # floor band: M3_out's cave exit is a vertical trigger curtain from
        # y=-10 to y=36.67, which made the y=40 terrace look acceptable even
        # though the trigger's resolved walk floor is y=-5.04.
        intended_height = None
        if field is not None and field.destination_node in field.node_height:
            # The first field is already seeded on the resolved destination
            # floor. Reuse that answer instead of resolving the raw trigger
            # coordinate a second time with subtly different constraints.
            intended_height = field.node_height[field.destination_node]
        else:
            intended = resolve_destination_node(
                geometry, destination_position, height_band=seed_band)
            if intended is not None:
                intended_height = intended[2]
        if intended_height is None:
            # Not this room's business at all: no real floor within
            # `DESTINATION_PROJECTION_MAX_RING` of it on ANY level. Offering
            # to walk someone "toward" a destination the room does not
            # contain is noise, not partial help -- and reusing the
            # projection's own reach is what keeps that a principled line
            # rather than a second opinion about how far is too far.
            return None
        partial = None
        for node, height in reachable.node_height.items():
            # Nearest means nearest on the destination's actual walk
            # surface, not nearest in the XZ projection.  Without this, a
            # cliff or roof directly above an unreachable doorway beats the
            # real doorstep a few units sideways.  Live M3_out did exactly
            # that: destination floor ~= -5, chosen endpoint = 120, and the
            # guide declared arrival on top of the Relic Stone cave.
            if abs(height - intended_height) > HEIGHT_CONTINUITY_TOLERANCE:
                continue
            point = node_point(geometry, node[0], points, height)
            distance = math.dist(
                point, (destination_position.x, destination_position.z))
            if partial is None or distance < partial[0]:
                partial = (distance, node[0], height, point)
        if partial is None:
            return None
        shortfall, tile, height, point = partial
        rebuilt = flow_field_from(
            geometry, Position(point[0], height, point[1]), edge_cost,
            max_tiles, blocked_nodes, exempt, points, None, blocked_segments)
        if rebuilt is None or origin_node not in rebuilt.node_height:
            return None
        if rebuilt.stats is not None:
            rebuilt.stats["partial_guidance"] = True
            rebuilt.stats["partial_shortfall"] = shortfall
            rebuilt.stats["partial_vertical"] = height - destination_position.y
        return rebuilt
    _cost, arrival_node, height = best
    tile = arrival_node[0]

    # Preserve the full destination-seeded field whenever it can reach the
    # player.  That field lets the player deviate and rejoin anywhere in the
    # connected area.  The narrow player-origin chain below exists only for
    # genuinely direction-asymmetric slope data; preferring it globally made
    # ordinary routes report "player node not linked" on every small
    # deviation (live M5_out, 2026-08-13).
    cx, cz = node_point(geometry, tile, points, height)
    rebuilt = flow_field_from(
        geometry, Position(cx, height, cz), edge_cost, max_tiles,
        blocked_nodes, exempt, points, None, blocked_segments)
    if rebuilt is not None and origin_node in rebuilt.node_height:
        if rebuilt.stats is not None:
            rebuilt.stats["reseeded_for_reachability"] = True
            rebuilt.stats["seeded_on_arrival_tile"] = True
            rebuilt.stats["target_projection_offset"] = math.dist(
                (cx, cz),
                (destination_position.x, destination_position.z))
        return rebuilt

    # `reachable` was expanded FROM the player in the direction they will
    # actually walk.  Usually rebuilding from the arrival tile produces the
    # same graph in reverse.  Sloped relocated nodes exposed that this is not
    # guaranteed: in live M3_out the same layer-1 tile resolved to y=13.70
    # from above and y=8.14 from below, so downhill routing worked and the
    # identical uphill journey failed.  The player-origin flood already
    # contains a fully validated chain to the arrival tile; reverse that
    # chain into the `next_hop` representation instead of demanding that a
    # second, direction-dependent flood rediscover it backwards.
    outward = reconstruct_route(reachable, arrival_node)
    if outward:
        route_nodes = list(reversed(outward))
        next_hop = {
            route_nodes[i]: route_nodes[i + 1]
            for i in range(len(route_nodes) - 1)
        }
        costs = {arrival_node: 0.0}
        running = 0.0
        for i in range(len(route_nodes) - 2, -1, -1):
            running += edge_cost(
                geometry, route_nodes[i][0], route_nodes[i + 1][0])
            costs[route_nodes[i]] = running
        stats = dict(reachable.stats or {})
        stats["reseeded_for_reachability"] = True
        stats["seeded_on_arrival_tile"] = True
        stats["reversed_origin_chain"] = True
        cx, cz = node_point(geometry, tile, points, height)
        stats["target_projection_offset"] = math.dist(
            (cx, cz), (destination_position.x, destination_position.z))
        return FlowField(
            next_hop=next_hop,
            node_height={node: reachable.node_height[node]
                         for node in route_nodes},
            cost_so_far=costs,
            destination_node=arrival_node,
            tile_size=geometry.tile_size,
            stats=stats,
            node_points=reachable.node_points)

    return None


def flow_field_from(geometry, destination_position,
                     edge_cost=uniform_edge_cost, max_tiles=MAX_TILES,
                     blocked_nodes=frozenset(), exempt_tiles=frozenset(),
                     node_points=None, height_band=None,
                     blocked_segments=()):
    """Uniform-cost search outward from `destination_position`'s resolved
    node, recording `next_hop[node] = the neighbor node that discovered it`
    -- i.e. pointing back toward the destination. This is both "expand to
    walkable nodes around the destination" and "retroactively link back to
    the player" in a single pass: any node's shortest route to the
    destination is just "follow next_hop until reaching destination_node."

    `blocked_nodes` are treated as impassable regardless of what the walk
    model itself says -- used by `navigation_service.py` to rebuild a route
    that avoids a specific waypoint node that already failed real
    player-progress validation once, so a rebuild can't immediately hand
    back the exact same bad hop.

    `blocked_segments` are XZ line segments no route leg may cross -- the
    warp/door trigger curtains this route is not supposed to fire (see
    `region_crossing_segments`, and `navigation_service.NavigationService.
    room_change_regions` for the live failure that made this necessary).
    They are not tiles and not nodes: a trigger is a line in the world, and
    a route must be free to walk right up beside a shop door as long as it
    does not walk THROUGH it.

    Returns `None` if the destination can't be seeded onto any walk-model
    surface, or if the search exceeds `max_tiles` (the caller should fall
    back to direct guidance in either case)."""
    stats = {
        # Version stamp as much as a diagnostic: the log line carrying this
        # is the only way to tell which build a live session was actually
        # running (NAVIGATION_AUDIT_2026-08-04.md 0 -- a whole afternoon of
        # failure reports came from a companion process that had never been
        # restarted). "swept" means one universal passability test; the old
        # builds print "walk_model"/"hit_model" here instead.
        "passability": "swept",
        "collision_radius": geometry.collision_radius,
        "walk_triangles": len(geometry.walk_triangles),
        "wall_triangles": len(geometry.wall_triangles),
        "target_projected": False,
        "rejected_edges": 0,
        "rejected_nodes": 0,
        "nodes": 0,
    }
    seed = resolve_destination_node(
        geometry, destination_position, height_band=height_band)
    if seed is None:
        return None
    stats["target_projected"] = True
    dest_tile, dest_layers, dest_height, projection_offset = seed
    stats["target_projection_offset"] = projection_offset
    stats["target_node"] = (dest_tile, tuple(sorted(dest_layers)))
    dest_node = (dest_tile, dest_layers)
    node_height = {dest_node: dest_height}
    cost_so_far = {dest_node: 0.0}
    next_hop = {}
    frontier = [(0.0, dest_node)]
    finalized = set()
    while frontier:
        cost, node = heapq.heappop(frontier)
        if node in finalized:
            continue
        finalized.add(node)
        if len(finalized) > max_tiles:
            return None
        tile, layers = node
        height = node_height[node]
        ix, iz = tile
        open_ortho = set()
        for dx, dz in _ORTHOGONAL:
            neighbor_tile = (ix + dx, iz + dz)
            result = _try_edge(geometry, tile, height, layers, neighbor_tile,
                               exempt_tiles, node_points, blocked_segments)
            if result is None:
                stats["rejected_edges"] += 1
                continue
            neighbor_height, neighbor_layers = result
            neighbor_node = (neighbor_tile, neighbor_layers)
            if neighbor_node in blocked_nodes:
                stats["rejected_nodes"] += 1
                continue
            open_ortho.add((dx, dz))
            _relax(neighbor_node, node, neighbor_height, cost, dx, dz,
                   edge_cost, geometry, node_height, cost_so_far, next_hop, frontier)
        for dx, dz in _DIAGONAL:
            # Corner-cut prevention: a diagonal step is only allowed when
            # BOTH adjoining orthogonal steps are themselves open from this
            # same tile -- otherwise the "shortest" route would cut through
            # a wall corner or an inaccessible gap between two obstacles.
            if (dx, 0) not in open_ortho or (0, dz) not in open_ortho:
                continue
            neighbor_tile = (ix + dx, iz + dz)
            result = _try_edge(geometry, tile, height, layers, neighbor_tile,
                               exempt_tiles, node_points, blocked_segments)
            if result is None:
                stats["rejected_edges"] += 1
                continue
            neighbor_height, neighbor_layers = result
            neighbor_node = (neighbor_tile, neighbor_layers)
            if neighbor_node in blocked_nodes:
                stats["rejected_nodes"] += 1
                continue
            _relax(neighbor_node, node, neighbor_height, cost, dx, dz,
                   edge_cost, geometry, node_height, cost_so_far, next_hop, frontier)
    stats["nodes"] = len(node_height)
    # Freeze where each node actually ended up, so the guide steers to the
    # point the route validated rather than to a tile centre it may have
    # deliberately moved away from. Cheap: the relocation memo is warm by
    # now, so this is a dictionary walk, not a second geometry pass.
    resolved = {}
    for (tile, _layers), tile_height in node_height.items():
        resolved[tile] = node_point(geometry, tile, node_points, tile_height)
    stats["relocated_nodes"] = sum(
        1 for tile, point in resolved.items()
        if point != _tile_center(tile, geometry.tile_size))
    return FlowField(next_hop, node_height, cost_so_far, dest_node,
                     geometry.tile_size, stats, resolved)


def _relax(neighbor, key, neighbor_height, cost, dx, dz,
           edge_cost, geometry, node_height, cost_so_far, next_hop, frontier):
    new_cost = cost + edge_cost(geometry, key[0], neighbor[0])
    if new_cost < cost_so_far.get(neighbor, math.inf):
        cost_so_far[neighbor] = new_cost
        node_height[neighbor] = neighbor_height
        next_hop[neighbor] = key
        heapq.heappush(frontier, (new_cost, neighbor))


COLLINEAR_EPSILON = 1e-6
"""Cross-product magnitude below which three consecutive waypoint tiles are
treated as exactly collinear. Tile keys are integers, so a genuine turn
produces a cross product of at least 1 -- this only absorbs float noise, it
never merges a real direction change."""


WAYPOINT_SPAN_TARGET_COUNT = 8
"""Roughly how many waypoints a journey should produce, regardless of its
length -- see `waypoint_span_for_route`."""
WAYPOINT_SPAN_MIN = TILE_SIZE * 2
"""Waypoints never closer than 2 tiles: below this they read as "cramped in
one location," the project owner's original complaint.

Briefly raised to 4 tiles on 2026-08-04 (late) as part of the staircase
theory of the reported west-east-west waypoints, and **reverted with it** at
the project owner's instruction -- see `simplify_route`.

The observation that motivated the raise is separate from that theory and
still stands, unused: relocation places a node up to 3 units off its tile
centre, and consecutive waypoints can be displaced in opposite directions,
so over a 16-unit leg that is `atan(4/6)` = 34 degrees of bearing swing from
node placement alone. Recorded here rather than acted on, since it was never
shown to be what the project owner was hearing."""
WAYPOINT_SPAN_MAX = TILE_SIZE * 10
"""Waypoints never further apart than 10 tiles, so even a very long crossing
still gives periodic confirmation and keeps stuck-detection responsive."""


def waypoint_span_for_route(route_length):
    """Waypoint spacing for a route of `route_length` world units, so the
    number of waypoints stays roughly constant instead of scaling with
    distance.

    **Replaced a fixed 32-unit span, 2026-08-03.** Measuring the walk-model
    extent of all 167 rooms found diagonals from 84 units (`M6_crab_B1`) to
    2621 (`D5_out`) -- a 31x spread. A single fixed span therefore meant
    wildly inconsistent feedback density: 38% of the diagonal in the
    smallest rooms (far too coarse to be useful), against 1-2% in the
    largest (a crossing would emit ~80 separate waypoint cues).

    Note this specifically did NOT reproduce the project owner's "kinda
    clumsy" room: `M5_labo_2F` has a 259-unit diagonal, near the 272 median,
    where 32 units is a reasonable 12%. So this is not a fix for that
    report -- the stall-timer removal was -- it is a separate,
    independently-measured correction to spacing consistency.

    Clamped at both ends: `WAYPOINT_SPAN_MIN` stops short routes from
    regressing to the original cramped-waypoint complaint, and
    `WAYPOINT_SPAN_MAX` stops long ones from going so sparse that
    confirmation and stuck-detection suffer.

    Both bounds and the target count are first-guess values chosen from the
    room-size distribution above; they have NOT been live-tuned by ear."""
    if not route_length or route_length <= 0:
        return WAYPOINT_SPAN_MIN
    return max(WAYPOINT_SPAN_MIN,
               min(WAYPOINT_SPAN_MAX, route_length / WAYPOINT_SPAN_TARGET_COUNT))


MAX_WAYPOINT_SPAN = TILE_SIZE * 4
"""Default span used when a caller does not supply one (see
`waypoint_span_for_route` for the route-scaled value `navigation_service`
actually passes). Longest straight run, in world units, that
`simplify_route` will collapse into a single waypoint before emitting an
intermediate one anyway.

Without a cap, a perfectly straight route collapses all the way down to one
waypoint at the destination. That removes the cramping the project owner
reported, but overshoots: the "waypoint reached" cue would never fire during
a long straight walk, and `navigation_service`'s stall/thrashing detection
would be measuring against a target hundreds of units away, making it far
less sensitive to the player getting stuck on something local.

32 units (4 tiles) keeps periodic confirmation and responsive stuck
detection while still removing the reported redundancy -- the measured
`M3_out` case (5 waypoints across a 32-unit straight run) becomes 2, and a
250-unit journey goes from roughly 31 waypoints to roughly 8. First-guess
value, flagged for live tuning by ear like TILE_SIZE and STEP_DISTANCE
before it -- it has NOT been live-tuned."""


def simplify_route(nodes, max_span=MAX_WAYPOINT_SPAN):
    """Collapse runs of exactly-collinear waypoints, keeping only the nodes
    where the route actually turns (plus both endpoints, every layer change,
    and an intermediate node whenever a straight run exceeds `max_span` --
    see that constant's own docstring for why an uncapped collapse is wrong).

    **Why this specific, conservative form.** The route is a chain of hops
    that `flow_field_from` individually validated (layer connectivity,
    wall-crossing, height continuity, corner-cut prevention). If A, B and C
    are exactly collinear then the straight line A->C passes precisely
    through B, and A->B and B->C are both already-verified hops -- so
    dropping B is provably safe with no new geometry test. That keeps the
    project's existing "consecutive waypoints are joined by a straight line
    of nothing but walkable tiles" guarantee intact by construction, rather
    than trading it for a looser line-of-sight approximation.

    Motivated by a live report (2026-08-02): "there are a lot of waypoints
    cramped in one location, so a lot, if not most, seem redundant."

    A node whose layer set differs from either neighbour is ALWAYS kept even
    when geometrically collinear -- crossing between terrace layers is
    meaningful to a player following the guide even if the ground happens to
    run straight through it.

    **A line-of-sight "string pull" replaced this on 2026-08-04 (late) and
    was REVERTED the same day at the project owner's instruction.** The
    theory it rested on -- that the reported "waypoint at west, then east,
    then west again" was a grid staircase surviving the collinear-only
    collapse -- is wrong. It is worth recording precisely, so it is not
    re-derived and re-shipped by the next person who measures the same thing:

    - The staircase itself is real and measurable. An optimal path on a
      square grid whose bearing is not a multiple of 45 degrees must
      alternate between orthogonal and diagonal steps, every alternation has
      a non-zero cross product, and so every one survives this function.
      Measured swings on real routes: `D1_labo_B3` -55 +45 0 +45 -45 -45 on
      a path 1.08x straight-line; `D1_labo_B1` +13 -45 0 +45 -90 -45 at
      1.41x.
    - String pulling did remove it -- audible reversals went to zero on all
      four routes measured.
    - **It was still not what the project owner was hearing.** Removing the
      staircase did not remove the reported symptom, so the staircase is a
      real property of the waypoint sequence that is NOT the cause of the
      west-east-west report. Whatever is, remains unidentified.

    Deliberately NOT done here: shortcutting across open space between
    non-collinear nodes."""
    if nodes is None or len(nodes) <= 2:
        return nodes
    kept = [nodes[0]]
    for index in range(1, len(nodes) - 1):
        (prev_tile, prev_layers) = kept[-1]
        (current_tile, current_layers) = nodes[index]
        (next_tile, next_layers) = nodes[index + 1]
        if current_layers != prev_layers or current_layers != next_layers:
            kept.append(nodes[index])
            continue
        ax, az = prev_tile
        bx, bz = current_tile
        cx, cz = next_tile
        cross = (bx - ax) * (cz - az) - (bz - az) * (cx - ax)
        if abs(cross) > COLLINEAR_EPSILON:
            kept.append(nodes[index])
            continue
        if max_span is not None:
            span = math.hypot(bx - ax, bz - az) * TILE_SIZE
            if span >= max_span:
                kept.append(nodes[index])
    kept.append(nodes[-1])
    return kept


def diagnose_unreachable(geometry, start_position, destination_position,
                          flow_field=None):
    """Why is there no route? Returns a short machine-readable cause plus a
    human sentence, so an indoor failure is attributable instead of just
    silent.

    The causes are deliberately checked in the order that isolates them: a
    target that never projected cannot also be a clearance problem, and a
    target blocked at the player's own width is not a grid-resolution
    problem. See requirement 9 of the two-authority slice."""
    radius = geometry.collision_radius
    start_seed = resolve_node(geometry, start_position)
    dest_seed = resolve_node(geometry, destination_position)

    if dest_seed is None:
        projected = resolve_destination_node(geometry, destination_position)
        if projected is None:
            # Distinguish "nowhere near any floor" from "on another storey",
            # which look identical from the projection's return value but are
            # completely different problems. Checked with the vertical guard
            # lifted, so this reports why the guard fired rather than
            # re-reporting that it did.
            unguarded = resolve_destination_node(
                geometry, destination_position, max_vertical_gap=math.inf)
            if unguarded is not None:
                return ("height_layer",
                        f"the destination sits {abs(unguarded[2] - destination_position.y):.1f} "
                        f"units below/above this room's nearest floor -- it is "
                        f"on another level, the cross-level case, which "
                        f"intra-room routing does not solve; guiding to the "
                        f"reachable point closest to it instead")
            return ("target_projection",
                    f"the destination has no walkable floor within "
                    f"{DESTINATION_PROJECTION_MAX_RING} tiles of it -- it is "
                    f"not merely off-surface, it is nowhere near this room's "
                    f"floor")
        return ("target_projection_recovered",
                f"the destination does not sit over walkable floor, but real "
                f"floor was found {projected[3]:.1f} units away and the route "
                f"was seeded there")
    if start_seed is None:
        return ("start_projection",
                "the player does not sit over any walkable surface in this "
                "room's walk model")

    dest_tile, _dest_layers, dest_height = dest_seed
    start_tile, _start_layers, start_height = start_seed

    if _swept_circle_node_blocked(geometry, dest_tile, dest_height):
        # Distinguish "genuinely inside an obstacle" from "the TILE CENTRE
        # happens to be, while the tile holds real clearance elsewhere" --
        # the latter is grid alignment, not clearance, and is a live
        # possibility at TILE_SIZE 8.0 with radius 4.0.
        cx, cz = _tile_center(dest_tile, geometry.tile_size)
        step = geometry.tile_size / 4.0
        for dx in (-step, 0.0, step):
            for dz in (-step, 0.0, step):
                clear = True
                for triangle in geometry.wall_candidates_around((dest_tile,)):
                    if not _wall_spans_height(triangle, dest_height):
                        continue
                    a, b = _triangle_longest_edge_xz(triangle)
                    if _point_segment_distance(cx + dx, cz + dz, a, b) < radius:
                        clear = False
                        break
                if clear:
                    return ("grid_alignment",
                            f"the destination tile's centre is within "
                            f"{radius:.1f} units of an obstacle, but a point "
                            f"{math.hypot(dx, dz):.1f} units away inside the "
                            f"same tile is clear -- resolution/alignment, "
                            f"not clearance")
        return ("radius_clearance",
                f"the destination is inside an obstacle at the player's own "
                f"collision radius ({radius:.1f})")

    if abs(dest_height - start_height) > HEIGHT_CONTINUITY_TOLERANCE:
        return ("height_layer",
                f"start and destination sit {abs(dest_height - start_height):.1f} "
                f"units apart vertically -- beyond a single connected layer; "
                f"this is the cross-level case, out of scope for this slice")

    if flow_field is not None:
        start_node = (start_tile, _start_layers)
        if start_node not in flow_field.node_height:
            return ("floor_support",
                    "both endpoints project onto real floor, but no chain of "
                    "walkable tiles connects them")
    # Both endpoints are real, standable and on the same level, and neither
    # projection nor clearance explains anything -- so ask the question
    # directly rather than shrugging. Flooding from the start is the same
    # work a route build does, and this only runs on a failure.
    #
    # Added 2026-08-12: the Relic Stone cave reported `unknown`, which is the
    # least useful answer available at exactly the moment the log most needed
    # a real one. The room's passage genuinely splits into pockets, and
    # "disconnected" is both true and actionable.
    reachable = flow_field_from(geometry, start_position)
    if reachable is not None and not any(
            node[0] == dest_tile for node in reachable.node_height):
        return ("disconnected",
                f"both endpoints are standable and on the same level, but "
                f"they are in separate pockets of this room -- {len(reachable.node_height)} "
                f"tiles are reachable from the player and the destination is "
                f"not among them")
    return ("unknown",
            "no single cause isolated -- endpoints project, clearance is "
            "fine, and heights are compatible")


def reconstruct_route(flow_field, from_node):
    """Walks `next_hop` from `from_node` to the destination node, returning
    the full ordered node chain, or `None` if `from_node` was never reached
    by the flood-fill. Not used by AudioGuideReader in this pass -- this is
    what `NavigationService.remaining_route()` and a future line-of-sight
    simplification pass build on."""
    if from_node not in flow_field.node_height:
        return None
    route = [from_node]
    seen = {from_node}
    current = from_node
    while current != flow_field.destination_node:
        next_node = flow_field.next_hop.get(current)
        if next_node is None or next_node in seen:
            return None
        route.append(next_node)
        seen.add(next_node)
        current = next_node
    return route
