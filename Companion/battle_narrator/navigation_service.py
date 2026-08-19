"""Reusable per-room navigation service.

Owns everything `pathfinding.py` itself deliberately does not: room geometry
caching, route lifecycle (build / rebuild-on-drift / debounce /
preserve-old-route-until-a-replacement-succeeds), player-node resolution,
and waypoint hysteresis. Built as a standalone, consumer-agnostic layer --
today's only consumer is `audio_guide.AudioGuideReader`, but nothing here
depends on it, so future features (autowalk, breadcrumb guidance, objective
routing, spoken turn directions -- none implemented yet) can request
navigation information without depending on the audio guide.

Cross-room routing is explicitly out of scope: a `Route` is only ever valid
within the one `floor_id` it was built for. A room/floor change always
invalidates the active route and requires a fresh build against that room's
own `.ccd` data -- no routing through doors, warps, or elevators is
attempted here.

**2026-08-01: routes are now built from the game's own CCD walk model**
(`pathfinding.py`'s rewrite -- see `WORLD_NAVIGATION_ARCHITECTURE.md`), not
an inferred default-walkable floor. This module's route-progress
validation, failure detection, confidence states, and waypoint adjacency
(all added 2026-07-31, before the walk-model investigation) are KEPT as
independent safety nets against genuine routing bugs or geometry gaps (e.g.
one of the 10 rooms with no walk model at all) -- but the specific
UNCERTAIN confidence state and its supporting machinery
(`nearest_supported_floor_distance`, `_tiles_have_unsupported_region`,
per-route floor-support-distance bookkeeping) existed ONLY to compensate
for the old parser not reading real floor data, and have been removed now
that real floor data is always what routing is built from. A successfully
built route is either VERIFIED (the normal case now) or has already failed
outright (FAILED/DIRECT_FALLBACK) -- there is no longer a "successful but
built on inference" middle state.
"""
import math
import time
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

from .pathfinding import (
    HEIGHT_CONTINUITY_TOLERANCE,
    destination_target_tiles,
    TILE_SIZE,
    _tile_center,
    build_room_geometry,
    diagnose_unreachable,
    flow_field_from,
    flow_field_toward,
    reconstruct_route,
    region_crossing_segments,
    resolve_destination_node,
    resolve_node,
    simplify_route,
    waypoint_span_for_route,
)
from .collision_object_enable import (
    EnableStateUnavailable,
    StaticObjectEnableState,
)
from .region_geometry import interaction_volume_keys, parse_regions
from .terrain_footsteps import load_room_triangles, load_walk_model_triangles

MOVING_TARGET_REBUILD_DISTANCE = TILE_SIZE
"""A route is only rebuilt for a moving destination once it has drifted
this far from the position the active route was built against -- avoids
rebuilding on minor per-poll animation jitter."""
MIN_REBUILD_INTERVAL = 1.0
"""Cooldown, in seconds, between rebuild attempts once
MOVING_TARGET_REBUILD_DISTANCE is exceeded, so a target oscillating right at
the threshold can't trigger a rebuild attempt on every single poll."""
WAYPOINT_STABLE_RADIUS_RATIO = 0.9
"""The active waypoint only advances to a fresh candidate once the player
comes within this fraction of a tile's size of the CURRENT waypoint --
prevents audible flicker between two neighboring next-hop tiles when the
player is straddling a cell boundary.

**Recalibrated 2026-08-02 from live measurement (was 0.5 -> a 4.0-unit
capture window).** A controlled live run, already carrying the
SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS recalibration, still failed: across
four waypoint attempts the project owner's closest approach was 4.72, 4.30,
6.36 and 8.57 units -- never inside the 4.0 window -- so the active waypoint
never advanced, best_distance stopped improving, and the 4-second stall
timeout abandoned the route every time. All four of those waypoint tile
centres were verified to be genuinely standable real walk-model surfaces
(y=40.00/36.60, layers 1 and 1-2), so the routing was correct; the capture
window was simply too small to hit while walking past a tile centre.

0.9 tiles (7.2 units) covers those observed near-misses while remaining
strictly BELOW the 8.0-unit orthogonal spacing between consecutive
waypoints (11.3 diagonal), so a player standing on waypoint N is still
outside waypoint N+1's window and cannot skip a hop. Semantically this
matches what a waypoint means -- "reach this tile", a tile being 8 units
across -- rather than "hit its exact centre"."""
WAYPOINT_CAPTURE_HEIGHT_TOLERANCE = HEIGHT_CONTINUITY_TOLERANCE
"""How far, in world units, the player's own resolved walk surface may sit
above or below the active waypoint's surface and still count as having
reached it.

**Added 2026-08-04 (live-caught).** Capture was previously XZ-only
(`_distance_xz` discards Y), which meant falling off a terrace onto the
ground DIRECTLY BENEATH a waypoint counted as reaching it. Live, floor 0x84
(`M3_out`), 00:10:00-00:10:21:

    00:10:00.849 player=(83.09, 40.00, 91.65) node=((10,11),{1}) -> wp=((2,11),{1})
    00:10:06.622 player=(19.23, -5.04, 98.97) node=((2,12),{0})  -> wp=((2,15),{1})

The player dropped from layer 1 (y=40.00) to layer 0 (y=-5.04). Tile (2,11)
genuinely carries both surfaces -- verified against the room's own walk
model: height -4.41 layers [0] and height 39.66 layers [1]. Their XZ
distance to the waypoint centre was 7.01 against a 7.20 capture radius, so
the cursor advanced and the committed sequence marched on along the upper
terrace while they stood on the ground below. Route length then GREW
(chain 54 -> 61 -> 65 -> 66), six polls reported the player unlinked, and
the guide only admitted anything was wrong 160.5 units of walking later,
when the displacement backstop fired. Its most misleading moment, logged at
00:10:13.407, aimed the beacon at `((0,16),{1})` while the player stood at
`((0,16),{0})` -- the very tile they were already in, one layer up,
centred and hot and unreachable.

Deliberately reuses `HEIGHT_CONTINUITY_TOLERANCE` rather than introducing a
second number for the same physical question ("are these two points on one
continuous walkable surface"), matching how `traversal_log.py` reuses
`TerrainFootstepReader.MAX_PLAUSIBLE_DELTA`. Its 10.0 was measured against
real `M3_out` terrain: the steepest genuine same-layer slope step is 7.40
units per tile, and within the 7.2-unit capture window a real ramp can
therefore account for a little under 7 units of legitimate height
difference -- comfortably passed here, while the 44.7-unit drop above is
comfortably rejected."""
HELD_WAYPOINT_TIMEOUT = 3.0
"""How long, in seconds, `next_waypoint` will keep repeating the last known
waypoint while the player's current node can't be freshly linked into the
active route before giving up and dropping to direct guidance instead. A
short grace period absorbs a momentary bad read without holding forever
once the player has genuinely diverged from what this route covers -- see
`_held_waypoint_result`."""

WAYPOINT_PROGRESS_TIMEOUT = None
"""**Retired 2026-08-03. Elapsed time is no longer a failure trigger at
all** -- `SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS` is now the sole detector.
Kept as an explicit `None` rather than deleted so this reasoning stays
attached to the thing it replaced.

Was 4.0 seconds without a meaningful improvement in distance-to-waypoint.
Two project-owner corrections killed it:

1. It fired while the player was standing perfectly still (live: cumulative
   displacements of 0.00 and 0.65 units), abandoning routes during a pause.
2. **This game has no turn-to-face action.** Movement is direct -- you push
   a direction and the character goes that way. So there is no orientation
   delay for a timer to be measuring, and "time spent not getting closer"
   carries no information about whether a waypoint is reachable. Standing
   still means the player is thinking; it is not evidence of a bad route.

What IS evidence is covering real ground and still not closing distance --
which is exactly `SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS`, and which remains
in force. The project owner's own assessment after live use: "the 4 second
timer i don't think helps much."

Removing a safety net is only safe because the defects it was compensating
for have since been fixed at the source (walk-model parsing, node identity,
capture radius, rebuild budget) -- it was firing spuriously far more often
than it was catching anything real."""
STALL_MOVEMENT_EPSILON = 0.5
"""Per-poll displacement, in world units, below which the player counts as
STATIONARY and the stall timer does not advance at all.

**Added 2026-08-03 (live-caught).** The stall timer previously ran on
wall-clock, so standing still for `WAYPOINT_PROGRESS_TIMEOUT` abandoned the
route outright. Two failures in one live session fired at cumulative
displacements of 0.00 and 0.65 units -- the project owner was simply
standing still. That is precisely what this interface asks a blind player to
do: stop, listen to the beacon, turn, get their bearings. Punishing it made
the guide, in their words, "kinda clumsy."

Standing still is also not evidence of a bad route -- it carries no
information about whether the waypoint is reachable, which is the only thing
this check exists to detect. So the timer now accrues only while the player
is genuinely moving and failing to close distance, which is the real
pathological signal. The thrashing check
(SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS) is unaffected and still catches
movement that goes nowhere."""
WAYPOINT_PROGRESS_EPSILON = 1.0
"""Minimum real improvement in distance-to-waypoint, in world units, to
count as "meaningful" progress -- guards against float/GPS-style jitter
resetting the stall timer without the player actually having gotten
closer."""
SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS = TILE_SIZE * 20
"""If the player's cumulative displacement since the waypoint's
best-distance-so-far last improved reaches this many world units, the
waypoint fails immediately, even before WAYPOINT_PROGRESS_TIMEOUT elapses --
covers "moved substantially without getting closer" and "repeatedly crosses
around the waypoint without reaching it" (thrashing back and forth covers a
lot of ground without ever improving the best distance, same signal as
moving away and not coming back).

**Recalibrated 2026-08-01 from live measurement (was TILE_SIZE * 3 = 24, an
uncalibrated guess).** A controlled live run had the guide abandon its route
2.18 seconds after activation, both failures firing on this check at
displacements of 24.07 and 26.01 -- barely over the old 24.0 threshold.
Measuring the project owner's real movement between polls in that same run
gave ~17 world units/second walking and ~32-38 running (peak sample: 22.3
units in 0.7s). At those speeds the old threshold allowed only ~0.7-1.4
seconds of movement before declaring failure -- less than human reaction
time to a newly-started audio cue, so simply being mid-stride in any
direction other than straight at the first waypoint failed the route almost
immediately. The new value (160 units) exceeds the ~150 units a running
player covers during the full WAYPOINT_PROGRESS_TIMEOUT window, which makes
that timeout the primary no-progress detector (as intended) and leaves this
check as what it was always meant to be: a backstop for genuine sustained
circling, not a trigger during ordinary travel."""
MAX_ROUTE_REBUILDS_PER_ACTIVATION = 1
"""How many consecutive rebuild attempts a route gets -- WITHOUT the player
reaching a waypoint in between -- before this activation gives up on
collision-based routing and drops to direct guidance. Detect and reject a
bad route rather than confidently repeating it, but don't rebuild forever
either.

**Budget semantics corrected 2026-08-02 (live-caught).** This was a
never-resetting per-activation LIFETIME count, so an entire multi-hundred-
unit journey got exactly one recovery no matter how well it was otherwise
going: two brief detours anywhere along the way killed routing permanently.
Observed live on a successful-until-then run -- rebuild #1 at t=5.0s, route
permanently abandoned at t=9.7s, ~10 seconds into a journey of well over a
minute, while the player was still in a perfectly routable area and had in
fact reached a waypoint at t=5.7s in between the two failures.

The counter now resets to 0 whenever the player actually REACHES a waypoint
(see `next_waypoint`'s advance branch), because that is concrete evidence
the route is working. So the protection still fires exactly where it was
aimed -- repeated failures with no progress between them, the genuinely
stuck case -- while normal navigation friction spread across a long trip no
longer accumulates toward a permanent give-up. Nodes that already failed
validation stay excluded regardless; only the attempt counter replenishes."""


_NO_OPINION = 0.0
"""Returned by `region_component_cost` when it cannot answer cheaply.
Distinct from `None`, which means "the graph cannot reach this" --
conflating the two would let "I do not know" masquerade as
"unreachable" and silently drop valid components."""


class RouteConfidence(Enum):
    """How much a currently active route should be trusted.

    **VERIFIED means the navigation graph provides a continuous ordinary
    walkable route to the destination's interaction region.** It has never
    been allowed to mean "the graph got reasonably close", and as of
    2026-08-12 it no longer can: the reachability fallback used to accept a
    reseed within 64 units of the destination and report the result
    VERIFIED, which measured across the whole game misled the player in
    86.9% of the routes it accepted -- including one that ended 1678 units
    away. Acceptance is now local connectivity into the destination's own
    arrival tiles (see `pathfinding.destination_target_tiles`), so a route
    that exists is a route that arrives.

    The direct fallback is never VERIFIED; it is DIRECT_FALLBACK, and the
    guide says "No walkable path found; guiding directly" exactly once.

    VERIFIED -- the normal case: a route was successfully built from the
    game's own CCD walk model, with real height and layer data throughout.
    FAILED -- the current waypoint just failed real-progress validation;
    transient, resolved by a rebuild attempt on the very same poll.
    DIRECT_FALLBACK -- collision-based routing has been abandoned for this
    guide activation (either the geometry itself couldn't be linked at all,
    or a rebuild already failed to fix real lack of progress); using
    straight-line direct guidance instead.

    There is no UNCERTAIN state anymore: an earlier version of this enum
    (2026-07-31) had one, to flag routes built partly on inferred rather
    than confirmed floor data. That inference no longer exists (routing is
    always built from the game's own walk model now -- see this module's
    own top docstring), so a route that builds successfully is always
    VERIFIED."""
    VERIFIED = "verified"
    PARTIAL = "partial"
    """A real walkable route, but to the closest point the graph can
    reach rather than to the destination itself. Announced as such --
    see `NavigationResult.partial_shortfall`. Never silent, and never
    VERIFIED."""
    FAILED = "failed"
    DIRECT_FALLBACK = "direct_fallback"


def _distance_xz(a, b):
    return math.hypot(a.x - b.x, a.z - b.z)


def _region_component_key(region, position):
    """Which VOLUME of a region-backed destination a point belongs to.

    Separates the three things a region destination conflates:

    1. **identity** -- the trigger volume, which is what this returns;
    2. **the spoken point** -- `Region.nearest_point`, which slides
       continuously along the volume's edge as the player walks and is what
       the beacon should keep announcing;
    3. **the route's arrival set** -- `pathfinding.destination_target_tiles`,
       already derived from the region's own triangles.

    Only (2) moves when the player walks. Treating it as the destination's
    identity is what made `NavigationService` rebuild a route that had not
    changed; see the call site in `update`.

    Returns the selected component's triangles (hashable, and the same value
    `region_target._same` compares), or `None` for a point destination -- and
    `None` never compares equal to anything here, so a genuinely moving
    target keeps the ordinary drift rule."""
    if region is None or position is None:
        return None
    components = getattr(region, "components", None)
    if components is None:
        return None
    best = None
    best_distance = None
    for component in components():
        distance = component.distance(position.x, position.z)
        if distance is None:
            continue
        if best_distance is None or distance < best_distance:
            best_distance, best = distance, component
    return None if best is None else best.triangles


@dataclass
class NavigationResult:
    """What `NavigationService.next_waypoint()` hands back each poll.

    `target_position` is what the caller should aim its guidance at --
    either a route waypoint or (once the player's node IS the destination
    node, or no route is available at all) the real, un-snapped destination
    position, so arrival/fine-approach logic downstream never has to know
    about tiles or layers.
    `path_available` is False exactly when the caller should use direct
    (straight-line) guidance instead of route-following.
    `fallback_started` is True on the single poll where `path_available`
    transitions from True to False -- callers should speak the one-shot
    "No walkable path found; guiding directly." warning only then, not on
    every subsequent poll while still unavailable.
    `remaining_distance` is the approximate walking distance left along the
    WHOLE route (not the distance to `target_position` alone), in world
    units, or None when unknown (no route, or the player couldn't be
    freshly resolved this poll). Callers should prefer this over the raw
    distance to `target_position` for "hot/cold" intensity feedback --
    using the immediate waypoint's own distance there would make the tone
    swing cold->hot on every single tile hop instead of warming up smoothly
    across the whole trip, since a waypoint is always only ~1 tile away.
    `route_initial_distance` is `remaining_distance` as it stood the FIRST
    time this route successfully resolved a player position -- captured
    once and held fixed for the route's lifetime (not recomputed every
    poll: progress should be judged against where the trip STARTED, not a
    moving target). Callers should normalize their own "hot/cold" gradient
    against `max(their_own_fixed_max_distance, route_initial_distance)`
    instead of a fixed constant alone -- long trips then get a gradient
    spanning their whole length, while short trips keep behaving as before.

    `confidence` is a `RouteConfidence` describing how much this poll's
    guidance should be trusted.
    `progress_invalidated` is True on the single poll where real-progress
    validation gave up on collision-based routing entirely for this
    activation (as opposed to `fallback_started`, which fires when the
    geometry itself couldn't be linked at all) -- callers should speak the
    distinct one-shot "Walkable route could not be verified; guiding
    directly." warning only then.
    `waypoint_advanced` is True on the single poll where the active waypoint
    changed because the player got close enough to the previous one --
    callers can use this to play a distinct "waypoint reached" cue.
    """
    target_position: object
    path_available: bool
    fallback_started: bool
    remaining_distance: object = None
    route_initial_distance: object = None
    confidence: object = RouteConfidence.VERIFIED
    progress_invalidated: bool = False
    waypoint_advanced: bool = False
    partial_started: bool = False
    """True on the single poll where a PARTIAL route begins, so the
    caller speaks its one-shot warning once rather than every poll."""
    partial_shortfall: object = None
    partial_vertical: object = None


@dataclass
class _WaypointProgress:
    """Tracks real player progress toward ONE specific waypoint node, reset
    whenever the active waypoint changes. See WAYPOINT_PROGRESS_TIMEOUT and
    SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS for the two failure conditions
    this backs."""
    node: tuple
    best_distance: float
    best_distance_at: float
    cumulative_displacement: float = 0.0
    last_player_position: object = None
    stalled_moving_time: float = 0.0
    """Seconds spent WITHOUT improving `best_distance`, counted only across
    polls where the player actually moved -- see
    `STALL_MOVEMENT_EPSILON`."""
    last_seen_at: object = None


@dataclass
class _Route:
    floor_id: int
    geometry: object
    flow_field: object
    destination_position: object
    built_at: float
    current_waypoint_node: object = None
    initial_remaining_distance: object = None
    held_since: object = None
    confidence: object = RouteConfidence.VERIFIED
    progress: object = None
    failed_nodes: set = field(default_factory=set)
    rebuild_attempts: int = 0
    abandoned: bool = False
    abandonment_announced: bool = False
    destination_component: object = None
    """Which VOLUME of a region-backed destination this route targets --
    `region_geometry.Region` component triangles, or `None` for a point
    destination. This, not `destination_position`, is the destination's
    identity for rebuild purposes; see `_region_component_key`."""
    partial_shortfall: object = None
    partial_vertical: object = None
    partial_announced: bool = False
    reached_destination_node: bool = False
    """Trace-only latch so `route_success` is emitted once per route rather
    than on every poll of the fine approach. Carries no routing meaning."""
    nodes_by_tile: object = None
    waypoint_sequence: object = None
    """The simplified waypoint chain COMMITTED when this route was first
    followed. Advanced through by `waypoint_cursor` rather than recomputed
    from the player's live node -- see next_waypoint for the U-turn failure
    that made re-derivation unusable. Rebuilt only when the route is."""
    waypoint_cursor: int = 1
    """Lazily-built index {tile: [node, ...]} over this route's flow field,
    used by `NavigationService._field_node_at` to map a real player position
    onto the graph robustly -- see that method's own docstring."""
    destination_region: object = None
    """The destination's `region_geometry.Region`, when it has one.
    Held so a rebuild seeds against the same arrival tiles the original
    build accepted -- see `pathfinding.destination_target_tiles`."""
    waypoint_span: object = None
    """Waypoint spacing for THIS route, from `waypoint_span_for_route`.
    Captured once, from the route's initial length, and held fixed for its
    lifetime -- recomputing it per poll against the shrinking remaining
    distance would keep moving the waypoints out from under the player as
    they walk."""


class NavigationService:
    def __init__(self, collision_dir, room_codes, logger, clock=time.monotonic,
                 enable_state=None, room_change_regions=None):
        self.collision_dir = collision_dir
        self.room_codes = dict(room_codes)
        self.logger = logger
        self.clock = clock
        self.room_change_regions = room_change_regions
        """`(floor_id) -> {region index}` for the regions in that room that
        MOVE THE PLAYER TO ANOTHER ROOM -- warps, doors, elevators.

        Optional, and `None` (the default) restores the pre-2026-08-17
        behaviour of routing straight through every one of them. The live
        app supplies it from the same authoritative `common.rel` records the
        "Exits" entity category is built from, so the set routing avoids and
        the set the player can select are the same set by construction.

        **Why routing has to know (live 2026-08-17, `M6_out`).** The project
        owner autowalked to the world-map exit at Gateon Port and arrived in
        the parts shop instead. The route was not wrong about geometry: its
        second leg ran from (92, 196) to (89, 223), and warp region 7 -- the
        parts-shop door, `common.rel` record 727, target room 0x97 -- is a
        trigger curtain 25 units wide at z=214.0, which that leg crosses
        0.69 units from its centre. Both attempts ended the same way.

        Nothing in the router had any concept of this. Worse, the one place
        that knew these regions existed made it more likely, not less:
        `interaction_volume_keys` deliberately REMOVES their triangles from
        the wall set so a doorway is never rebuilt as a barrier (needed for
        Agate's Relic Stone cave, which is a trigger you must walk into and
        which does not change rooms). Correct for that case, and exactly
        wrong for a door you are only walking past.

        The distinction that matters is not "is this an interaction region"
        but "does crossing it move me somewhere else", which is a question
        only the warp records can answer -- so this is where the answer comes
        in. The destination's own region is always exempt: routing to a door
        obviously has to be allowed to reach it."""
        self.enable_state = (
            StaticObjectEnableState() if enable_state is None else enable_state)
        """Which CCD collision objects the running game currently considers.

        Defaults to `StaticObjectEnableState` so offline tools and the many
        tests that build geometry from a bare `.ccd` keep working unchanged;
        the live app passes a `LiveObjectEnableState`. See
        `collision_object_enable.py` for why "everything enabled" is not a
        safe default against a running game."""
        self._enable_signature = None
        """Signature of the enable state the cached geometry was built from.
        `None` means "not tracking" (the static state, which never changes)."""
        self._geometry_cache = {}
        self._geometry_signature = {}
        self._interaction_volume_cache = {}
        self._region_cache = {}
        self._avoid_segment_cache = {}
        self._wall_triangle_cache = {}
        self._walk_triangle_cache = {}
        self._route = None
        self._last_rebuild_attempt = 0.0
        self._path_was_available = True
        self._last_player_position = None
        """Most recent resolved player position, kept only so a failed build
        can be diagnosed from where the player actually is rather than from
        the destination. Never used for routing."""

    def refresh_enable_state(self, floor_id):
        """Re-read the engine's collision-object enable bits and report
        whether they changed since the cached geometry was built.

        Called once per poll from `begin`/`update`, never from a route build:
        `build_room_geometry` asks `is_enabled` once per triangle, so the read
        has to be amortised into a single snapshot or a `M6_out` build would
        issue tens of thousands of memory reads.

        Returns True when the caller should treat existing routing state as
        stale. A state with no `refresh` (the static one) never changes and so
        never reports a change."""
        refresh = getattr(self.enable_state, "refresh", None)
        if refresh is None:
            return False
        signature = refresh(floor_id)
        if signature == self._enable_signature:
            return False
        previous = self._enable_signature
        self._enable_signature = signature
        if previous is None and signature is None:
            return False
        if previous is None:
            # First snapshot of the session, not a toggle. Logging this as
            # "changed" made the very first line of every session read as if
            # the engine had just altered the world.
            self.logger.info(
                "COLLISION enable-state initialised floor=0x%X disabled=%s",
                floor_id, self._disabled_summary())
            return False
        # Only geometry built under the OLD signature is stale. Dropping the
        # whole cache would re-parse and re-index every room the session has
        # visited, which for M6_out alone is seconds of work.
        stale = [
            key for key, built in self._geometry_signature.items()
            if built != signature
        ]
        for key in stale:
            self._geometry_cache.pop(key, None)
            self._geometry_signature.pop(key, None)
        self.logger.info(
            "COLLISION enable-state changed floor=0x%X rooms_invalidated=%d "
            "disabled=%s", floor_id, len(stale), self._disabled_summary())
        return bool(stale) or previous is not None

    def _disabled_summary(self):
        snapshot = getattr(self.enable_state, "snapshot", None)
        if snapshot is None:
            return "?"
        return ",".join(str(index) for index in snapshot.disabled_entries()) or "none"

    def _interaction_volumes(self, floor_id):
        """Triangle keys of this room's interaction regions, so a trigger
        volume is never rebuilt as a wall. Cached per room -- the `.ccd`
        never changes. Returns an empty set when the file is unavailable,
        which restores the previous behaviour rather than failing the room."""
        if floor_id in self._interaction_volume_cache:
            return self._interaction_volume_cache[floor_id]
        code = self.room_codes.get(floor_id)
        path = Path(self.collision_dir) / f"{code}.ccd" if code else None
        volumes = frozenset()
        if path is not None and path.is_file():
            try:
                volumes = interaction_volume_keys(path.read_bytes())
            except (OSError, ValueError) as exc:
                self.logger.debug(
                    "NAVIGATION interaction volumes unavailable floor=0x%X: %s",
                    floor_id, exc)
        self._interaction_volume_cache[floor_id] = volumes
        return volumes

    def _regions(self, floor_id):
        """This room's interaction regions, `{index: Region}`. Cached: the
        `.ccd` never changes. Empty when unavailable, which degrades to the
        old route-through-anything behaviour rather than failing the room."""
        if floor_id in self._region_cache:
            return self._region_cache[floor_id]
        code = self.room_codes.get(floor_id)
        path = Path(self.collision_dir) / f"{code}.ccd" if code else None
        regions = {}
        if path is not None and path.is_file():
            try:
                regions = parse_regions(path.read_bytes())
            except (OSError, ValueError) as exc:
                self.logger.debug(
                    "NAVIGATION regions unavailable floor=0x%X: %s",
                    floor_id, exc)
        self._region_cache[floor_id] = regions
        return regions

    def _avoid_segments(self, floor_id, destination_region):
        """Trigger curtains the route must not cross, because crossing one
        would move the player to another room they did not ask for.

        Returns XZ segments no route leg may cross. One exemption: **the
        destination's own region**. Routing to a door has to be allowed to
        reach it, and `destination_target_tiles` derives the arrival tiles
        from those very triangles -- refusing them would turn every warp
        destination into an instant refusal.
        Someone who has just stepped out of a shop is standing ON that
        shop's trigger, and that needs no special case here: crossing is
        what is refused, not standing, so their own node stays routable and
        the first leg simply has to lead away from the curtain rather than
        back through it.

        Only the per-region segment lists are cached; the exemptions depend
        on the route, not the room."""
        if self.room_change_regions is None:
            return ()
        try:
            indices = self.room_change_regions(floor_id)
        except Exception as exc:
            self.logger.debug(
                "NAVIGATION room-change regions unavailable floor=0x%X: %s",
                floor_id, exc)
            return ()
        if not indices:
            return ()
        regions = self._regions(floor_id)
        exempt_index = getattr(destination_region, "index", None)
        segments = []
        for index in indices:
            if index == exempt_index:
                continue
            region = regions.get(index)
            if region is None:
                continue
            key = (floor_id, index)
            cached = self._avoid_segment_cache.get(key)
            if cached is None:
                cached = region_crossing_segments(region)
                self._avoid_segment_cache[key] = cached
            segments.extend(cached)
        return tuple(segments)

    def _geometry_for(self, floor_id):
        signature = self._enable_signature
        cached = self._geometry_cache.get(floor_id)
        if cached is not None and self._geometry_signature.get(floor_id) != signature:
            cached = None
            self._geometry_cache.pop(floor_id, None)
        if cached is None:
            wall_triangles = load_room_triangles(
                self.collision_dir, self.room_codes, self._wall_triangle_cache,
                floor_id, self.logger)
            walk_triangles = load_walk_model_triangles(
                self.collision_dir, self.room_codes, self._walk_triangle_cache,
                floor_id, self.logger)
            try:
                geometry = build_room_geometry(
                    walk_triangles, wall_triangles, floor_id=floor_id,
                    enable_state=self.enable_state,
                    interaction_volumes=self._interaction_volumes(floor_id))
            except EnableStateUnavailable as exc:
                # No safe guess exists -- see EnableStateUnavailable. Refusing
                # here drops this room to direct guidance through the caller's
                # existing `geometry is None` path, which is the same honest
                # failure a room with no walk model already takes.
                self.logger.warning(
                    "NAVIGATION room load floor=0x%X room=%s refused: %s",
                    floor_id, self.room_codes.get(floor_id, "?"), exc)
                return None
            # Room-load diagnostic: which model is governing passability
            # here, and on what evidence. Logged once per room per enable
            # signature, so it is cheap and makes every later route line in
            # the log interpretable -- and a re-log now also marks the moment
            # an object toggle rebuilt the room.
            self.logger.info(
                "NAVIGATION room load floor=0x%X room=%s walk_triangles=%d "
                "wall_triangles=%d passability=swept collision_radius=%.2f "
                "tile_size=%.1f disabled_objects=%s",
                floor_id, self.room_codes.get(floor_id, "?"),
                len(geometry.walk_triangles), len(geometry.wall_triangles),
                geometry.collision_radius, geometry.tile_size,
                self._disabled_summary())
            self._geometry_cache[floor_id] = geometry
            self._geometry_signature[floor_id] = signature
        return self._geometry_cache[floor_id]

    def _trace(self, event, **fields):
        """One structured `NAVTRACE` line per lifecycle event.

        Added 2026-08-04 (late) for the live-validation pass on the
        relocation/radius work. Deliberately key=value rather than prose so
        a whole session can be parsed mechanically, and deliberately fired
        only on RARE events -- route build, waypoint commit, waypoint
        advance, progress failure, rebuild, abandonment, arrival. Nothing
        here runs per poll: the existing per-poll "player node not linked"
        line is already why this log reached 275 MB.

        This is instrumentation only. It reads state and formats it; it
        makes no routing decision and changes no behaviour."""
        parts = []
        for key, value in fields.items():
            if isinstance(value, float):
                parts.append(f"{key}={value:.3f}")
            else:
                parts.append(f"{key}={value}")
        self.logger.info("NAVTRACE %s %s", event, " ".join(parts))

    @staticmethod
    def _fmt_point(position):
        if position is None:
            return "none"
        return f"({position.x:.2f},{position.y:.2f},{position.z:.2f})"

    def _trace_node(self, route, node, label):
        """Items 7-9 for one waypoint: tile, resolved node point, and the
        offset between them -- the whole question relocation raises."""
        if node is None:
            return {label: "none"}
        tile, layers = node
        point = route.flow_field.node_position(node)
        centre_x, centre_z = _tile_center(tile, route.flow_field.tile_size)
        return {
            f"{label}_tile": f"{tile[0]},{tile[1]}",
            f"{label}_layers": "|".join(str(v) for v in sorted(layers)),
            f"{label}_point": f"({point.x:.2f},{point.y:.2f},{point.z:.2f})",
            f"{label}_centre": f"({centre_x:.2f},{centre_z:.2f})",
            f"{label}_offset": round(
                math.hypot(point.x - centre_x, point.z - centre_z), 3),
        }

    def _trace_projections(self, geometry, destination_position):
        """Items 3 and 4: what the DIRECT resolve said versus what the route
        actually used, for both endpoints. These differing silently is what
        hid the cross-level projection bug."""
        fields = {}
        player = self._last_player_position
        direct_start = resolve_node(geometry, player) if player else None
        fields["start_pos"] = self._fmt_point(player)
        fields["start_direct"] = (
            "none" if direct_start is None
            else f"tile={direct_start[0][0]},{direct_start[0][1]}"
                 f";h={direct_start[2]:.2f}")
        fields["target_pos"] = self._fmt_point(destination_position)
        direct_target = resolve_node(geometry, destination_position)
        fields["target_direct"] = (
            "none" if direct_target is None
            else f"tile={direct_target[0][0]},{direct_target[0][1]}"
                 f";h={direct_target[2]:.2f}")
        projected = resolve_destination_node(geometry, destination_position)
        fields["target_final"] = (
            "refused" if projected is None
            else f"tile={projected[0][0]},{projected[0][1]}"
                 f";h={projected[2]:.2f};offset={projected[3]:.2f}")
        if direct_target is None and projected is None:
            # Item 5's other half: say WHY, in the same line.
            cause, _sentence = diagnose_unreachable(
                geometry, player or destination_position, destination_position)
            fields["target_refused_cause"] = cause
        return fields

    def _try_build(self, floor_id, destination_position, keep_on_failure,
                    blocked_nodes=frozenset(), rebuild_attempts=0,
                    destination_region=None):
        geometry = self._geometry_for(floor_id)
        avoid_segments = self._avoid_segments(floor_id, destination_region)
        start = self.clock()
        field = (
            flow_field_toward(
                geometry, destination_position, self._last_player_position,
                blocked_nodes=blocked_nodes,
                destination_region=destination_region,
                blocked_segments=avoid_segments)
            if geometry.walk_triangles else None
        )
        duration = self.clock() - start
        if field is None:
            cause, explanation = diagnose_unreachable(
                geometry, self._last_player_position or destination_position,
                destination_position)
            self.logger.debug(
                "NAVIGATION route build FAILED floor=0x%X room=%s duration=%.4fs "
                "walk_triangles=%d wall_triangles=%d passability=swept radius=%.2f "
                "cause=%s (%s)",
                floor_id, self.room_codes.get(floor_id, "?"), duration,
                len(geometry.walk_triangles), len(geometry.wall_triangles),
                geometry.collision_radius, cause, explanation)
            self._trace(
                "build_failed", floor=f"0x{floor_id:X}",
                room=self.room_codes.get(floor_id, "?"),
                passability="swept",
                radius=geometry.collision_radius, cause=cause,
                rebuild_attempts=rebuild_attempts,
                keep_on_failure=keep_on_failure,
                duration_s=duration,
                **self._trace_projections(geometry, destination_position))
            if not keep_on_failure:
                self._route = None
            return
        stats = field.stats or {}
        self.logger.debug(
            "NAVIGATION route build floor=0x%X room=%s passability=%s radius=%.2f "
            "nodes=%d rejected_edges=%d rejected_nodes=%d target_projected=%s "
            "target_projection_offset=%.1f reseeded=%s relocated=%d "
            "duration=%.4fs",
            floor_id, self.room_codes.get(floor_id, "?"),
            stats.get("passability"), stats.get("collision_radius", -1.0),
            len(field.node_height), stats.get("rejected_edges", -1),
            stats.get("rejected_nodes", -1), stats.get("target_projected"),
            stats.get("target_projection_offset", 0.0),
            # Whether the reachability fallback fired. Absent from the log
            # until 2026-08-04 (late), which is exactly why the garage's
            # six-node pocket could not be diagnosed from the log alone --
            # "did the fallback run and fail, or never run?" was unanswerable.
            stats.get("reseeded_for_reachability", False),
            stats.get("relocated_nodes", 0), duration)
        dest_node = field.destination_node
        dest_point = field.node_position(dest_node)
        self._trace(
            "build_ok", floor=f"0x{floor_id:X}",
            room=self.room_codes.get(floor_id, "?"),
            passability=stats.get("passability"),
            radius=stats.get("collision_radius", -1.0),
            tile_size=field.tile_size,
            nodes=len(field.node_height),
            rejected_edges=stats.get("rejected_edges", -1),
            reseeded=stats.get("reseeded_for_reachability", False),
            relocated=stats.get("relocated_nodes", 0),
            seed_node=f"{dest_node[0][0]},{dest_node[0][1]}",
            seed_point=f"({dest_point.x:.2f},{dest_point.y:.2f},{dest_point.z:.2f})",
            seed_layers="|".join(str(v) for v in sorted(dest_node[1])),
            rebuild_attempts=rebuild_attempts,
            duration_s=duration,
            # How many trigger curtains this route was forbidden to cross.
            # Logged because the failure it prevents is invisible otherwise:
            # the 2026-08-17 parts-shop route looked completely healthy in
            # the log right up to the room change.
            avoided_triggers=len(avoid_segments),
            **self._trace_projections(geometry, destination_position))
        self._route = _Route(
            floor_id=floor_id, geometry=geometry, flow_field=field,
            destination_position=destination_position, built_at=start,
            failed_nodes=set(blocked_nodes), rebuild_attempts=rebuild_attempts,
            destination_region=destination_region,
            destination_component=_region_component_key(
                destination_region, destination_position),
            partial_shortfall=stats.get("partial_shortfall"),
            partial_vertical=stats.get("partial_vertical"),
            confidence=(RouteConfidence.PARTIAL
                        if stats.get("partial_guidance")
                        else RouteConfidence.VERIFIED))

    def begin(self, floor_id, destination_position, player_position=None,
              destination_region=None):
        """Start guiding toward `destination_position` in `floor_id`,
        discarding any previous route/hysteresis state. Call on guide
        activation (and treat a fresh activation as the only time a failed
        build should immediately mean "use direct guidance").

        `player_position` matters on the very first build: an off-floor
        destination is seeded at the nearest floor the PLAYER can reach, and
        without it that fallback cannot run at all -- the route is built here,
        before any `next_waypoint` has supplied a position."""
        # Set to the real current time, not a hardcoded 0.0: `update()`'s
        # cooldown check is `now - self._last_rebuild_attempt`, and with a
        # monotonic clock `now` is never near zero, so a hardcoded 0.0 here
        # would make that very first post-failure cooldown check always
        # pass trivially, defeating the cooldown on the next poll.
        self._last_rebuild_attempt = self.clock()
        self._path_was_available = True
        self._route = None
        self.refresh_enable_state(floor_id)
        if player_position is not None:
            self._last_player_position = player_position
        self._try_build(floor_id, destination_position, keep_on_failure=False,
                        destination_region=destination_region)

    def update(self, floor_id, destination_position, player_position=None,
               destination_region=None):
        """Call every active poll with the current floor and the target's
        current real position. Rebuilds when there's no active route yet,
        the room changed, the collision-object enable state changed, the
        destination moved to a different trigger VOLUME, or a point
        destination has drifted past `MOVING_TARGET_REBUILD_DISTANCE` (gated
        by `MIN_REBUILD_INTERVAL`).

        **Drift does not apply within one region component.** A region
        destination's point slides along the volume's edge as the player
        walks, and that is not the destination changing -- see
        `_region_component_key`.
        A rebuild attempt that fails leaves an existing same-room route and
        its waypoint exactly as-is rather than dropping to direct
        guidance -- only a room change whose rebuild also fails, or never
        having had a route at all, triggers the fallback signal."""
        if player_position is not None:
            self._last_player_position = player_position
        if self.refresh_enable_state(floor_id) and self._route is not None:
            # The engine toggled a collision object: a pier rotated, a
            # doorway opened. Every claim the active route makes was computed
            # against geometry that no longer exists, so it is discarded
            # outright rather than allowed to keep steering -- and the rebuild
            # is NOT cooldown-gated, because this is a discrete world event
            # like a room change, not per-poll target drift.
            self._trace("enable_state_changed", floor=floor_id,
                        disabled=self._disabled_summary())
            self._route = None
            self._last_rebuild_attempt = self.clock()
            self._try_build(floor_id, destination_position,
                            keep_on_failure=False,
                            destination_region=destination_region)
            return
        if self._route is not None and self._route.abandoned:
            # Collision-based routing was already abandoned for this
            # activation after real-progress validation failed twice (see
            # `_handle_waypoint_failure`) -- a moving/drifting target
            # shouldn't resurrect it; direct guidance continues until the
            # next `begin()`.
            return
        if self._route is None:
            now = self.clock()
            if now - self._last_rebuild_attempt < MIN_REBUILD_INTERVAL:
                return
            self._last_rebuild_attempt = now
            self._try_build(floor_id, destination_position, keep_on_failure=False,
                            destination_region=destination_region)
            return
        if floor_id != self._route.floor_id:
            # A room change is a discrete, meaningful event -- always
            # rebuild immediately (no cooldown gate), and don't preserve the
            # old room's route if the new room's build fails.
            self._last_rebuild_attempt = self.clock()
            self._try_build(floor_id, destination_position, keep_on_failure=False,
                            destination_region=destination_region)
            return
        component = _region_component_key(
            destination_region, destination_position)
        if component is not None and component == self._route.destination_component:
            # Same trigger VOLUME as the active route: the point moved, the
            # destination did not. Nothing a rebuild would produce differs --
            # `destination_target_tiles` derives the arrival set from the
            # region's own triangles and ignores this point entirely, and the
            # flow field is seeded AT the destination and floods outward, so
            # it already covers wherever the player has walked to.
            #
            # Live 2026-08-13 05:49:31-38, M3_out, "to Relic Stone cave":
            # five full rebuilds of a 1861-node room in seven seconds, one
            # every poll that cleared MIN_REBUILD_INTERVAL. The cave's trigger
            # has a long edge at z=-23.86 and the player was walking parallel
            # to it along the clifftop, so `Region.nearest_point` returned
            # (player.x, -23.86) every poll -- `target_pos.x` tracked
            # `start_pos.x` 1:1 and drift crossed the 8.0 threshold on every
            # 8 units walked.
            #
            # It was not merely wasteful. Reprojecting that sliding point
            # picked a different SURFACE at different x: at x=-38.04 the
            # nearest floor under (x, -23.86) is the clifftop itself
            # (y=120.00, 1637 nodes, "8 units away, 2 waypoints"), while at
            # x=-27.97 it is the cave floor below (y=-5.04, 1861 nodes, "686
            # units away, 30 waypoints"). The guide alternated between those
            # two answers for one unchanged destination.
            return
        drift = _distance_xz(
            destination_position, self._route.destination_position)
        if drift <= MOVING_TARGET_REBUILD_DISTANCE:
            return
        now = self.clock()
        if now - self._last_rebuild_attempt < MIN_REBUILD_INTERVAL:
            return
        self._last_rebuild_attempt = now
        self._try_build(floor_id, destination_position, keep_on_failure=True,
                        destination_region=destination_region)

    def region_component_cost(self, floor_id, player_position, component):
        """Ordering value for one component of an interaction region, or
        `None` when the navigation graph cannot reach it.

        This is the hook that keeps entity speech and routing agreeing:
        `region_target.RegionTargetSelector` asks it which volumes of a
        multi-volume region are walkable, so the beacon cannot name a volume
        the route would refuse.

        **It must never flood.** This is called per entity per poll. An
        earlier version answered from a precomputed component map, which
        measured at 29.10 s for the first request in `M6_out` against 2.28 s
        without it -- the map floods the whole 21000-node room before it can
        answer anything. A per-call flood is worse still.

        So it answers only from work already done: the ACTIVE ROUTE's own
        flow field. If the player is in that field and the component's
        arrival tiles are too, they are in one connected component by
        construction -- the field is the graph's own reachability answer.
        With no active route there is no cheap sound answer, so it returns
        `None` for "no opinion", and the selector falls back to nearest
        point. That is the honest trade: the invariant is enforced exactly
        when the guide is actually running, and speech is never blocked
        waiting on a flood."""
        route = self._route
        if route is None or route.abandoned or route.floor_id != floor_id:
            return _NO_OPINION
        field = route.flow_field
        geometry = route.geometry
        seed = resolve_node(geometry, player_position)
        if seed is None:
            return _NO_OPINION
        if not any(node[0] == seed[0] for node in field.node_height):
            return _NO_OPINION
        tiles = destination_target_tiles(geometry, player_position, component)
        reached = [node for node in field.node_height if node[0] in tiles]
        if not reached:
            return None
        return min(field.cost_so_far.get(node, math.inf) for node in reached)

    def clear(self):
        self._route = None
        self._path_was_available = True

    def _fallback_result(self):
        fallback_started = self._path_was_available
        self._path_was_available = False
        return NavigationResult(
            None, False, fallback_started, confidence=RouteConfidence.DIRECT_FALLBACK)

    def _held_waypoint_result(self, route):
        """Player couldn't be freshly resolved/linked this poll -- keep
        using the last known waypoint rather than failing immediately, so a
        momentary bad read never causes flicker or a spurious fallback.
        BUT only for up to HELD_WAYPOINT_TIMEOUT: past that, the player has
        genuinely left the region this route covers, and continuing to
        point at a now-stale waypoint is actively misleading -- drop to
        direct guidance instead."""
        if route.current_waypoint_node is None:
            return self._fallback_result()
        now = self.clock()
        if route.held_since is None:
            route.held_since = now
        elif now - route.held_since >= HELD_WAYPOINT_TIMEOUT:
            return self._fallback_result()
        self._path_was_available = True
        return NavigationResult(
            route.flow_field.node_position(route.current_waypoint_node),
            True, False, confidence=route.confidence)

    def _abandoned_result(self, route):
        """Collision-based routing was already given up on for this
        activation (see `_handle_waypoint_failure`) -- keep reporting direct
        fallback without re-announcing the one-shot warning."""
        announce = not route.abandonment_announced
        route.abandonment_announced = True
        self._path_was_available = False
        return NavigationResult(
            None, False, False, confidence=RouteConfidence.DIRECT_FALLBACK,
            progress_invalidated=announce)

    def _field_node_at(self, route, tile, height):
        """The flow-field node that corresponds to a real player position at
        `tile`/`height`, or None if the field holds no node for that tile.

        Needed because a node's `(tile, layer_set)` key is NOT well-defined
        from position alone: a single tile can contain walk-model triangles
        carrying DIFFERENT layer nibbles, so which layer set you get depends
        on exactly which XZ point inside the tile you sample. `flow_field_from`
        samples tile centers; `resolve_node` samples wherever the player
        actually stands. When those land on different triangles, the player's
        node key legitimately does not exist in the field even though the
        player is standing squarely on a routed tile.

        Confirmed live 2026-08-01 in `M3_out` at tile (15,-21): the tile
        center resolves to layers {3} (height 120.005) while the project
        owner's real position 3.6 units away resolves to layers {3,4} at the
        SAME height 120.005 -- so the field contained ((15,-21),{3}) while
        the player resolved to ((15,-21),{3,4}), producing a spurious
        "player node not linked to destination" and a held-waypoint episode
        mid-route.

        Resolution is by nearest real height among that tile's nodes, which
        is stable regardless of layer tagging (the heights genuinely differ
        between stacked surfaces; the layer nibbles are what vary within one
        surface). Layer identity still governs graph CONNECTIVITY in
        `pathfinding._connected_walk_candidate` -- unchanged -- it simply
        stops being used as a brittle lookup key here."""
        if route.nodes_by_tile is None:
            index = {}
            for node in route.flow_field.node_height:
                index.setdefault(node[0], []).append(node)
            route.nodes_by_tile = index
        candidates = route.nodes_by_tile.get(tile)
        if not candidates:
            return None
        best = min(
            candidates,
            key=lambda node: abs(route.flow_field.node_height[node] - height))
        # "Nearest height" is only a legitimate identification when there is
        # a genuinely near height to match. Unbounded, this claims the
        # player is standing on whatever surface the field happens to hold
        # at that tile -- including one on a terrace far above their head,
        # which is the same discarded-Y mistake WAYPOINT_CAPTURE_HEIGHT_
        # TOLERANCE documents on the capture side. Beyond the tolerance the
        # honest answer is "the field holds no node for where you are",
        # which the caller already handles (held waypoint, then direct
        # guidance).
        if abs(route.flow_field.node_height[best] - height) > (
                WAYPOINT_CAPTURE_HEIGHT_TOLERANCE):
            return None
        return best

    def _update_waypoint_progress(self, route, waypoint_node, player_position, now):
        """Returns True if the CURRENT waypoint attempt has failed real
        progress validation (see WAYPOINT_PROGRESS_TIMEOUT and
        SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS). A fresh waypoint (or the
        first one ever) always starts as not-failed, regardless of how it
        compares to a previous attempt's numbers."""
        waypoint_position = route.flow_field.node_position(waypoint_node)
        distance = _distance_xz(player_position, waypoint_position)
        progress = route.progress
        if progress is None or progress.node != waypoint_node:
            route.progress = _WaypointProgress(
                node=waypoint_node, best_distance=distance, best_distance_at=now,
                last_player_position=player_position, last_seen_at=now)
            return False
        step = 0.0
        if progress.last_player_position is not None:
            step = _distance_xz(player_position, progress.last_player_position)
            progress.cumulative_displacement += step
        elapsed = 0.0 if progress.last_seen_at is None else max(
            0.0, now - progress.last_seen_at)
        progress.last_player_position = player_position
        progress.last_seen_at = now
        if distance <= progress.best_distance - WAYPOINT_PROGRESS_EPSILON:
            progress.best_distance = distance
            progress.best_distance_at = now
            progress.cumulative_displacement = 0.0
            progress.stalled_moving_time = 0.0
        elif step >= STALL_MOVEMENT_EPSILON:
            # Retained purely as an observable diagnostic -- it is NOT a
            # failure trigger any more (see WAYPOINT_PROGRESS_TIMEOUT).
            progress.stalled_moving_time += elapsed
        # Distance covered without closing on the waypoint is the ONLY
        # failure signal now. This game has no turn-to-face action --
        # movement is direct -- so elapsed time carries no information about
        # reachability, while real ground covered does.
        return progress.cumulative_displacement >= SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS

    def _handle_waypoint_failure(self, route, player_position):
        """A waypoint failed real-progress validation: mark it suspect,
        rebuild once avoiding it, and if the rebuilt route ALSO fails to
        make progress, abandon collision-based routing for the rest of this
        activation rather than rebuilding forever."""
        failed_node = route.current_waypoint_node
        route.failed_nodes.add(failed_node)
        route.confidence = RouteConfidence.FAILED
        self.logger.debug(
            "NAVIGATION waypoint failed progress validation: node=%s "
            "rebuild_attempts=%d best_distance=%.2f cumulative_displacement=%.2f",
            failed_node, route.rebuild_attempts,
            route.progress.best_distance if route.progress else -1.0,
            route.progress.cumulative_displacement if route.progress else -1.0)
        # Item 11: the player moved a long way without closing on the
        # waypoint. `cumulative_displacement` versus `best_distance` is the
        # oscillation signature -- large travel, no approach.
        self._trace(
            "progress_failed",
            room=self.room_codes.get(route.floor_id, "?"),
            player=self._fmt_point(player_position),
            best_distance=route.progress.best_distance if route.progress else -1.0,
            cumulative_displacement=(
                route.progress.cumulative_displacement if route.progress else -1.0),
            threshold=SUBSTANTIAL_MOVEMENT_WITHOUT_PROGRESS,
            stalled_moving_time=(
                route.progress.stalled_moving_time if route.progress else -1.0),
            rebuild_attempts=route.rebuild_attempts,
            max_rebuilds=MAX_ROUTE_REBUILDS_PER_ACTIVATION,
            **self._trace_node(route, failed_node, "failed"))
        if route.rebuild_attempts < MAX_ROUTE_REBUILDS_PER_ACTIVATION:
            self._trace(
                "rebuild_started",
                room=self.room_codes.get(route.floor_id, "?"),
                attempt=route.rebuild_attempts + 1,
                max_rebuilds=MAX_ROUTE_REBUILDS_PER_ACTIVATION,
                # Movement without closing on an aim point proves only that
                # this waypoint attempt did not work for the player.  It does
                # NOT prove the underlying walk-model node is impassable.
                # Removing such a node can sever the only real ramp into a
                # destination: live in M3_out it turned a valid route to the
                # Relic Stone cave into a 598-unit partial route ending on the
                # clifftop above it.  Rebuild from the player's new position,
                # but preserve the authoritative graph intact.
                blocked_nodes=0)
            self._try_build(
                route.floor_id, route.destination_position, keep_on_failure=False,
                blocked_nodes=frozenset(),
                rebuild_attempts=route.rebuild_attempts + 1,
                destination_region=route.destination_region)
            if self._route is not None:
                # Retain the attempts as diagnostics only.  They must never
                # become graph exclusions without collision evidence.
                self._route.failed_nodes = set(route.failed_nodes)
            if self._route is not None:
                # Re-resolve immediately against the freshly rebuilt field so
                # this same poll returns usable guidance instead of wasting a
                # cycle -- the fresh route's progress state starts clean, so
                # this cannot recurse again on the very same poll.
                return self.next_waypoint(player_position)
            # The rebuild itself failed outright -- restore the old route
            # object purely to carry the abandonment state forward;
            # `abandoned=True` below
            # short-circuits `next_waypoint` before its now-stale
            # geometry/flow_field would ever be read again.
            self._route = route
        route.abandoned = True
        # Item 12, failure side. `rebuild_failed` distinguishes "no route at
        # all from the new position" from "rebuilt and still made no
        # progress" -- different problems with the same visible outcome.
        self._trace(
            "route_abandoned",
            room=self.room_codes.get(route.floor_id, "?"),
            player=self._fmt_point(player_position),
            destination=self._fmt_point(route.destination_position),
            rebuild_attempts=route.rebuild_attempts,
            rebuild_failed=self._route is route,
            failed_nodes=len(route.failed_nodes))
        return self._abandoned_result(route)

    def _simplify(self, route, chain):
        """Collapse this route's chain into the waypoints worth announcing.

        A thin wrapper rather than two call sites, kept from the reverted
        string-pull slice because both places that build a waypoint sequence
        must stay identical -- they diverged once already."""
        return simplify_route(chain, max_span=route.waypoint_span)

    def _advance_past_reached_waypoints(self, route, player_node):
        """Skip any committed waypoint the player is already past.

        The cursor could previously only step forward one place at a time,
        and only on coming within the capture radius of the CURRENT waypoint.
        Walk wide of one and it never advanced: the beacon kept pointing at a
        waypoint behind the player until they walked back to satisfy it, then
        sent them forward again. Measured over the whole live log, 25 such
        backward-aim events across 15 of the 33 substantial journeys.

        The test used here is exact rather than geometric. `cost_so_far` is
        the flow field's own optimal cost from a node to the destination, so
        a waypoint whose cost is no lower than the player's own is, by
        definition, not progress -- they are already at least as close. Any
        such waypoint is skipped. This cannot oscillate, because the field is
        fixed for the route's lifetime and the cursor only ever increases.

        Deliberately NOT a re-derivation of the sequence from the player's
        live node: that is the U-turn failure committing the sequence exists
        to prevent (see `next_waypoint`). This only ever moves the cursor
        FORWARD along the sequence already committed."""
        sequence = route.waypoint_sequence
        if not sequence:
            return False
        cost_so_far = route.flow_field.cost_so_far
        player_cost = cost_so_far.get(player_node)
        if player_cost is None:
            return False
        moved = False
        while route.waypoint_cursor < len(sequence) - 1:
            waypoint_cost = cost_so_far.get(sequence[route.waypoint_cursor])
            if waypoint_cost is None or waypoint_cost < player_cost:
                break
            route.waypoint_cursor += 1
            moved = True
        return moved

    def _recommit_waypoint_sequence(self, route, chain):
        """Rebuild the committed waypoint sequence from `chain` (the
        player's own current route to the destination) and return the first
        waypoint of it, or None if there is no usable chain.

        Only called where re-deriving is provably not the U-turn case the
        commitment exists to prevent -- see the caller in `next_waypoint`.
        The flow field itself is untouched: this re-picks which waypoints
        along the already-built route are handed out, it does not re-route."""
        if not chain or len(chain) < 2:
            route.waypoint_sequence = None
            route.waypoint_cursor = 1
            return None
        route.waypoint_sequence = self._simplify(route, chain)
        route.waypoint_cursor = 1
        sequence = route.waypoint_sequence
        if sequence and len(sequence) > 1:
            return sequence[1]
        return route.flow_field.next_hop.get(chain[0])

    def next_waypoint(self, player_position):
        """The core per-poll query: where should guidance currently aim?
        See `NavigationResult` for the return contract."""
        self._last_player_position = player_position
        route = self._route
        if route is None:
            return self._fallback_result()
        if route.abandoned:
            return self._abandoned_result(route)
        seed = resolve_node(route.geometry, player_position)
        if seed is None:
            self.logger.debug(
                "NAVIGATION player position failed to resolve to any walk-"
                "model surface at all: x=%.2f y=%.2f z=%.2f",
                player_position.x, player_position.y, player_position.z)
            return self._held_waypoint_result(route)
        player_tile, player_layers, player_height = seed
        player_node = (player_tile, player_layers)
        if player_node not in route.flow_field.node_height:
            # The exact layer-set key missed -- resolve by tile + nearest
            # real height instead, which is stable regardless of which
            # triangle inside the tile happened to be sampled. See
            # `_field_node_at` for the live-confirmed case this fixes.
            player_node = self._field_node_at(route, player_tile, player_height)
        if player_node is None or player_node not in route.flow_field.node_height:
            self.logger.debug(
                "NAVIGATION player node not linked to destination: "
                "player=(%.2f,%.2f,%.2f) tile=%s layers=%s height=%.2f "
                "destination=(%.2f,%.2f,%.2f) dest_node=%s "
                "flow_field_nodes=%d bounds=%s",
                player_position.x, player_position.y, player_position.z,
                player_tile, sorted(player_layers), player_height,
                route.destination_position.x, route.destination_position.y,
                route.destination_position.z, route.flow_field.destination_node,
                len(route.flow_field.node_height), route.geometry.bounds)
            return self._held_waypoint_result(route)
        route.held_since = None
        remaining_distance = (
            route.flow_field.cost_so_far[player_node] * route.flow_field.tile_size
        )
        # Captured once per route, the first time it resolves a real
        # player position, and held fixed for that route's lifetime -- see
        # NavigationResult.route_initial_distance's own docstring. Not
        # recomputed every poll: progress should be judged against where
        # the trip STARTED, not a moving target.
        if route.initial_remaining_distance is None:
            route.initial_remaining_distance = remaining_distance
            # Waypoint spacing scales with how long this journey actually is,
            # so a cramped indoor hop and a long outdoor crossing both yield
            # a comparable number of waypoints -- see
            # `waypoint_span_for_route`. Fixed here, once, for the same
            # reason `initial_remaining_distance` is.
            route.waypoint_span = waypoint_span_for_route(remaining_distance)
        initial_distance = route.initial_remaining_distance
        if player_node == route.flow_field.destination_node:
            self._path_was_available = True
            route.progress = None
            if not route.reached_destination_node:
                # Item 12, success side: the player stood on the route's own
                # seed node. Fired once per route so a long fine-approach
                # cannot spam it.
                route.reached_destination_node = True
                self._trace(
                    "route_success",
                    room=self.room_codes.get(route.floor_id, "?"),
                    player=self._fmt_point(player_position),
                    player_height=player_height,
                    destination=self._fmt_point(route.destination_position),
                    residual_to_real_target=_distance_xz(
                        player_position, route.destination_position),
                    initial_distance=initial_distance,
                    rebuild_attempts=route.rebuild_attempts,
                    **self._trace_node(route, player_node, "seed"))
            return NavigationResult(
                route.destination_position, True, False,
                remaining_distance, initial_distance, confidence=route.confidence)
        # The aim point is the next place the route actually TURNS, not the
        # adjacent tile -- runs of exactly-collinear hops in between are
        # collapsed by `simplify_route` (provably safe: see its docstring).
        #
        # The waypoint SEQUENCE is committed when the route is built and then
        # advanced through by index. It is deliberately NOT recomputed from
        # whatever node the player currently occupies.
        #
        # Recomputing was a live failure. On a U-shaped route -- west along
        # one tile row, up, then back east along the next -- the two arms are
        # adjacent, and their flow-field hops point in OPPOSITE directions.
        # The project owner walked the boundary between rows -16 and -15
        # (z = -120.0) at z ~= -120.5, so sub-tile drift flipped which row
        # they resolved to, and each flip handed back the opposite arm:
        # "go west", "go east", "go west" -- eight reversals in seventy
        # seconds, over 160 units of movement with no progress, until they
        # gave up and walked it manually. Committing to the sequence means
        # reaching waypoint N always yields waypoint N+1 of the path already
        # being followed, whichever adjacent tile the player happens to be
        # standing in.
        #
        # Genuinely leaving the route is still handled: progress validation
        # (see `_progress_failed`) detects real movement without progress and
        # triggers a rebuild, which recommits a fresh sequence.
        if route.waypoint_sequence is None:
            chain = reconstruct_route(route.flow_field, player_node)
            route.waypoint_sequence = (
                self._simplify(route, chain) if chain else None
            )
            route.waypoint_cursor = 1
            # The committed sequence, dumped once, with every waypoint's
            # tile, resolved point and offset from centre (items 7-9). This
            # is the record needed to answer "is the calculated route
            # physically valid" without replaying the session.
            self._trace(
                "sequence_committed",
                room=self.room_codes.get(route.floor_id, "?"),
                chain_len=len(chain) if chain else -1,
                simplified_len=(len(route.waypoint_sequence)
                                if route.waypoint_sequence else -1),
                waypoint_span=route.waypoint_span,
                remaining_distance=remaining_distance,
                **self._trace_node(route, player_node, "player_node"))
            for index, node in enumerate(route.waypoint_sequence or ()):
                self._trace(
                    "sequence_node", i=index,
                    **self._trace_node(route, node, "wp"))
        chain = reconstruct_route(route.flow_field, player_node)
        # Skip forward past any waypoint the player has already got past --
        # walking wide of one must not send them back for it. See
        # `_advance_past_reached_waypoints`.
        skipped_ahead = self._advance_past_reached_waypoints(route, player_node)
        simplified = route.waypoint_sequence
        if simplified and route.waypoint_cursor < len(simplified):
            candidate = simplified[route.waypoint_cursor]
        else:
            candidate = route.flow_field.next_hop.get(player_node)
        if candidate is None:
            # Reachable but no further hop recorded -- treat as arrived;
            # shouldn't normally happen since destination_node is handled
            # above, but degrade to fine guidance rather than failing.
            self._path_was_available = True
            route.progress = None
            return NavigationResult(
                route.destination_position, True, False,
                remaining_distance, initial_distance, confidence=route.confidence)
        self._path_was_available = True
        waypoint_advanced = False
        if skipped_ahead:
            # The cursor moving is not enough on its own: `current_waypoint_
            # node` is otherwise only ever reassigned inside the capture
            # branch below, so without this the guide kept aiming at the
            # waypoint it had just decided the player was past -- the aim
            # stayed pinned at x=17.0 while the player walked to x=148.0
            # (`WaypointOvershootTests`).
            #
            # Getting PAST a waypoint is the same evidence as reaching one:
            # the route is working. So it fires the same confirmation cue and
            # replenishes the same rebuild budget (see
            # MAX_ROUTE_REBUILDS_PER_ACTIVATION). Without this the look-ahead
            # would silently swallow both, which is how it first broke
            # `test_reaching_a_waypoint_replenishes_the_rebuild_budget`.
            route.current_waypoint_node = candidate
            waypoint_advanced = True
            route.rebuild_attempts = 0
        elif (route.current_waypoint_node is None
                or route.current_waypoint_node not in route.flow_field.node_height):
            route.current_waypoint_node = candidate
        else:
            current_position = route.flow_field.node_position(
                route.current_waypoint_node)
            stable_radius = route.flow_field.tile_size * WAYPOINT_STABLE_RADIUS_RATIO
            within_xz = (
                _distance_xz(player_position, current_position) <= stable_radius)
            height_gap = abs(player_height - current_position.y)
            off_surface = height_gap > WAYPOINT_CAPTURE_HEIGHT_TOLERANCE
            if within_xz and off_surface:
                # Standing directly above or below the waypoint rather than
                # on it -- the player has left the surface this route was
                # following (see WAYPOINT_CAPTURE_HEIGHT_TOLERANCE for the
                # live terrace fall this detects). Do NOT advance the
                # cursor, and recommit the sequence from where the player
                # actually is, so the guide stops steering along a surface
                # they are no longer on.
                #
                # Recommitting is safe HERE specifically, where the U-turn
                # failure that motivated committing the sequence at all
                # cannot apply: that failure was sub-tile drift flipping
                # between two same-height adjacent tile ROWS, whereas this
                # branch requires a large height difference at essentially
                # the same XZ, which no amount of horizontal drift produces.
                self.logger.debug(
                    "NAVIGATION waypoint refused: player is %.2f units "
                    "%s it (tolerance %.2f) -- player=(%.2f,%.2f,%.2f) "
                    "surface=%.2f node=%s waypoint=%s at y=%.2f; "
                    "recommitting from the player's own route",
                    height_gap, "below" if player_height < current_position.y
                    else "above", WAYPOINT_CAPTURE_HEIGHT_TOLERANCE,
                    player_position.x, player_position.y, player_position.z,
                    player_height, player_node, route.current_waypoint_node,
                    current_position.y)
                candidate = self._recommit_waypoint_sequence(route, chain)
                if candidate is None:
                    self._path_was_available = True
                    route.progress = None
                    return NavigationResult(
                        route.destination_position, True, False,
                        remaining_distance, initial_distance,
                        confidence=route.confidence)
                route.current_waypoint_node = candidate
            elif within_xz:
                # The player reached the current waypoint (a turn), so step
                # the COMMITTED sequence forward -- the next waypoint of the
                # route already being followed, not one re-derived from
                # whichever tile they happen to be standing in (see the
                # U-turn failure documented above).
                #
                # Every hop collapsed between consecutive waypoints was
                # individually validated during the flood fill (layer
                # connectivity, wall-crossing, height continuity, corner-cut
                # prevention), and collapsing only ever removes EXACTLY-
                # collinear nodes, so the straight line between them still
                # passes through nothing but those verified hops. The
                # "consecutive waypoints are joined by a straight line of
                # walkable tiles" guarantee holds by construction.
                sequence = route.waypoint_sequence
                if sequence and route.waypoint_cursor + 1 < len(sequence):
                    route.waypoint_cursor += 1
                    following = sequence[route.waypoint_cursor]
                else:
                    # Past the end of the committed chain (or none was
                    # built): fall back to the field's own next hop so the
                    # final approach still works.
                    following = route.flow_field.next_hop.get(player_node)
                if (following is not None
                        and following != route.current_waypoint_node):
                    # Captured before the overwrite so the trace can report
                    # the real capture distance to the waypoint just
                    # satisfied (item 10).
                    previous_node = route.current_waypoint_node
                    route.current_waypoint_node = following
                    candidate = following
                    waypoint_advanced = True
                    # Position logging for the still-unexplained live report
                    # that the FIRST waypoint sometimes differs between guide
                    # re-toggles from one spot. Determinism and jitter were
                    # both ruled out under investigation, leaving equal-cost
                    # branch points as the leading (unconfirmed) hypothesis --
                    # this records exactly what would be needed to confirm or
                    # kill it: the real position, the node it resolved to, and
                    # how much simplification collapsed. See
                    # ACCESSIBILITY_BACKLOG.md.
                    self.logger.debug(
                        "NAVIGATION waypoint selected: player=(%.2f,%.2f,%.2f) "
                        "player_node=%s -> waypoint=%s chain=%d simplified=%d",
                        player_position.x, player_position.y, player_position.z,
                        player_node, candidate,
                        len(chain) if chain else -1,
                        len(simplified) if simplified else -1)
                    # Item 10: how far the player actually was from the
                    # waypoint at the moment it advanced. `previous` is the
                    # one just satisfied, so this is the real capture
                    # distance, not the distance to the new target.
                    previous_point = route.flow_field.node_position(previous_node)
                    self._trace(
                        "waypoint_advanced",
                        room=self.room_codes.get(route.floor_id, "?"),
                        cursor=route.waypoint_cursor,
                        of=len(sequence) if sequence else -1,
                        player=self._fmt_point(player_position),
                        player_height=player_height,
                        capture_distance=_distance_xz(
                            player_position, previous_point),
                        stable_radius=stable_radius,
                        height_gap=abs(player_height - previous_point.y),
                        remaining_distance=remaining_distance,
                        **{**self._trace_node(route, previous_node, "from"),
                           **self._trace_node(route, candidate, "to")})
                    # Reaching a waypoint is concrete proof the route is
                    # working, so it REPLENISHES the rebuild budget -- see
                    # MAX_ROUTE_REBUILDS_PER_ACTIVATION's own docstring for
                    # the live case where a whole journey was permanently
                    # abandoned 9.7 seconds in because that budget was a
                    # never-resetting per-activation lifetime count.
                    # `failed_nodes` is deliberately NOT cleared: a node
                    # that already failed real-progress validation stays
                    # excluded for the rest of the activation.
                    route.rebuild_attempts = 0

        now = self.clock()
        failed = self._update_waypoint_progress(
            route, route.current_waypoint_node, player_position, now)
        if failed:
            return self._handle_waypoint_failure(route, player_position)

        partial_started = (
            route.confidence is RouteConfidence.PARTIAL
            and not route.partial_announced)
        if partial_started:
            route.partial_announced = True
        return NavigationResult(
            route.flow_field.node_position(route.current_waypoint_node),
            True, False, remaining_distance, initial_distance,
            confidence=route.confidence, waypoint_advanced=waypoint_advanced,
            partial_started=partial_started,
            partial_shortfall=route.partial_shortfall,
            partial_vertical=route.partial_vertical)

    def remaining_route(self, player_position):
        """Ordered list of world positions from the player's current node to
        the destination node, or None if unavailable. Not consumed by
        AudioGuideReader today -- exposed for future breadcrumb/spoken-turn
        consumers per this module's own reusability goal."""
        route = self._route
        if route is None or route.abandoned:
            return None
        seed = resolve_node(route.geometry, player_position)
        if seed is None:
            return None
        player_tile, player_layers, player_height = seed
        player_node = (player_tile, player_layers)
        if player_node not in route.flow_field.node_height:
            # Same tile+nearest-height resolution `next_waypoint` uses -- see
            # `_field_node_at`. Without it this would spuriously report "no
            # remaining route" whenever the player stood on a triangle whose
            # layer tagging differs from the one the flood fill sampled.
            player_node = self._field_node_at(route, player_tile, player_height)
        if player_node is None:
            return None
        nodes = reconstruct_route(route.flow_field, player_node)
        if nodes is None:
            return None
        return [route.flow_field.node_position(node) for node in nodes]

    def reachable(self):
        """Whether a route currently exists AND hasn't been abandoned after
        repeated real-progress failure (coarse; does not itself confirm the
        player's current position specifically links into it -- see
        `next_waypoint`/`remaining_route` for that)."""
        return self._route is not None and not self._route.abandoned
