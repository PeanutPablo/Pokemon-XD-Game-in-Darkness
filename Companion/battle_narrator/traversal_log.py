"""Conservative, secondary walked-position edge recorder.

**STATUS: SHELVED (2026-08-01), not consumed by anything.** Built
2026-07-31 on the working assumption that the game's `.ccd` data was
missing real floor/ground geometry (a bulk scan had found CCD slot +0x28
sparse-to-absent for floor triangles in most rooms). A follow-up
architecture investigation ("is this genuinely missing data, or an
incomplete understanding of the game's world representation") traced every
CCD model slot via decomp disassembly and found the latter: CCD slot +0x24
(`CCD_WALKMDL_HEAD`) is the engine's own walkable-ground model, with real
height and explicit layer/transition data, that this project simply hadn't
parsed yet (see `WORLD_NAVIGATION_ARCHITECTURE.md`, `pathfinding.py`).
Routing is now built directly from that authoritative source. The premise
this module was investigating a workaround FOR no longer holds, so building
it out further is not justified -- inferring walkability from player trails
would be strictly worse than reading the surface the engine itself walks
on. Kept rather than deleted (it is documented and independently tested,
and the underlying idea -- a breadcrumb trail back the way the player came
-- may still have standalone value someday, unrelated to floor inference)
but explicitly not part of the navigation story going forward. Do not wire
this into `NavigationService` without a fresh, separate justification.

Investigated per the project owner's explicit spec (2026-07-31) as a
possible SECONDARY source for navigation, specifically because this
project's own `.ccd` collision data had been (mistakenly, per the above)
believed to be sparse-to-absent for real floor/ground geometry. The
player's own real, successfully-walked positions are ground truth this
project already reads reliably everywhere else.

But per the project owner's own explicit caution, this module does
DELIBERATELY LITTLE with that idea in this pass:

- It does NOT feed into `NavigationService`'s routing decisions at all.
  Nothing in this module is wired into the live app yet -- it exists as a
  standalone, independently-tested building block, per the instruction not
  to build broad learned-map routing until progress validation (see
  `navigation_service.RouteConfidence`/waypoint-failure handling) and this
  conservative recording have been separately proven.
- It records ONLY verified point-to-point EDGES ("the player successfully
  moved from tile A to tile B"), never a filled walkable area. Recording
  edge (A, B) proves nothing about any tile other than A and B themselves --
  not a neighbor, not a different elevation at the same XZ, not a tile the
  player merely passed near.
- It never persists anything to disk -- purely in-memory, scoped to one
  `TraversalRecorder` instance's lifetime. Per the project owner: "Do not
  persist learned routes across sessions until their identity and safety
  model are established" -- that identity/safety work hasn't happened, so
  this deliberately can't outlive one process.

`TraversalContext` intentionally has no defaults on its exclusion fields --
a caller must explicitly state what's currently true (battle, menu, dialogue,
teleport, cutscene, real player input, collision-stuck) rather than a typo'd
omission silently defaulting to "safe to record."
"""
import math
from dataclasses import dataclass

from .pathfinding import TILE_SIZE
from .terrain_footsteps import TerrainFootstepReader

MAX_PLAUSIBLE_STEP_DISTANCE = TerrainFootstepReader.MAX_PLAUSIBLE_DELTA
"""Reuses the exact same live-tuned "how big a single poll-to-poll
displacement can plausibly be before it's a teleport/warp/jump rather than
real walking" threshold TerrainFootstepReader already relies on -- no
second magic number invented for the same underlying question."""


@dataclass(frozen=True)
class TraversalContext:
    """Per-sample context a caller must supply alongside a position for
    `TraversalRecorder.record()` to judge whether the step ending at that
    position is a valid, recordable traversal. No field has a default --
    every exclusion the project owner specified must be an explicit,
    positively-stated fact from the caller, not an assumed default."""
    floor_id: int
    in_battle: bool
    in_menu: bool
    dialogue_active: bool
    cutscene_active: bool
    teleported: bool
    collision_stuck: bool
    player_input_active: bool


def _sample_excluded(context):
    """True if this sample's own state disqualifies it from ever being part
    of a recorded edge -- battles, menus, dialogue, cutscenes, a just-fired
    teleport/warp, a collision-stuck episode, or movement without real
    player input (scripted movement)."""
    return (
        context.in_battle or context.in_menu or context.dialogue_active
        or context.cutscene_active or context.teleported
        or context.collision_stuck or not context.player_input_active
    )


def _finite_position(position):
    return (
        math.isfinite(position.x)
        and math.isfinite(position.y)
        and math.isfinite(position.z)
    )


class TraversalRecorder:
    """Records verified A->B tile edges from consecutive valid samples.
    Call `record()` every poll with the player's current real position and
    context; internally decides whether THIS step (from the previous valid
    sample to this one) qualifies."""

    def __init__(self, tile_size=TILE_SIZE,
                 max_step_distance=MAX_PLAUSIBLE_STEP_DISTANCE,
                 max_trail_length=2000):
        self.tile_size = tile_size
        self.max_step_distance = max_step_distance
        self.max_trail_length = max_trail_length
        self._edges = {}
        self._tile_heights = {}
        self._trails = {}
        self._last_position = None
        self._last_context = None

    def _tile_key(self, position):
        return (
            math.floor(position.x / self.tile_size),
            math.floor(position.z / self.tile_size),
        )

    def record(self, position, context):
        """Call every poll. Records an edge from the PREVIOUS call's
        position to this one only if both samples are valid, both are on
        the same floor (a floor/room change is never a valid edge, even if
        the coordinate delta happens to look small), the displacement is
        under `max_step_distance`, and the two positions resolve to
        different tiles (no self-edge for standing still)."""
        if not _finite_position(position):
            # Ignored entirely, not stored -- a bad momentary read shouldn't
            # poison the chain OR silently become "the previous position"
            # for the next comparison. The last known-good sample stays in
            # place so the next valid sample can still connect to it.
            return
        previous_position = self._last_position
        previous_context = self._last_context
        self._last_position = position
        self._last_context = context
        if previous_position is None or previous_context is None:
            return
        if _sample_excluded(context) or _sample_excluded(previous_context):
            return
        if context.floor_id != previous_context.floor_id:
            return
        distance = math.dist(
            (position.x, position.y, position.z),
            (previous_position.x, previous_position.y, previous_position.z))
        if distance > self.max_step_distance:
            return
        from_tile = self._tile_key(previous_position)
        to_tile = self._tile_key(position)
        if from_tile == to_tile:
            return
        floor_id = context.floor_id
        self._edges.setdefault(floor_id, set()).add((from_tile, to_tile))
        self._tile_heights[(floor_id, from_tile)] = previous_position.y
        self._tile_heights[(floor_id, to_tile)] = position.y
        trail = self._trails.setdefault(floor_id, [])
        if not trail:
            # Seed with the starting tile too -- otherwise the very first
            # recorded edge would silently drop its own origin from the
            # breadcrumb trail.
            trail.append(from_tile)
        if trail[-1] != to_tile:
            trail.append(to_tile)
        if len(trail) > self.max_trail_length:
            del trail[0]

    def has_edge(self, floor_id, from_tile, to_tile):
        """"The player successfully moved from `from_tile` to `to_tile`" --
        and nothing more. Does NOT imply any other tile, including
        geometric neighbors of either tile, is walkable."""
        return (from_tile, to_tile) in self._edges.get(floor_id, ())

    def supported_height(self, floor_id, tile):
        """Real observed height for `tile`, ONLY if it was actually an
        endpoint of a verified traversed edge -- never inferred for a tile
        the player merely passed near. Returns None if unsupported."""
        return self._tile_heights.get((floor_id, tile))

    def breadcrumb_route(self, floor_id, from_tile):
        """Ordered list of tiles retracing the player's own already-walked
        trail on this floor, from `from_tile`'s most recent occurrence back
        to the earliest tile still remembered -- i.e. "the way you came."
        Returns None if `from_tile` was never recorded on this floor. This
        is deliberately NOT a general route to an arbitrary destination:
        per this module's own docstring, a breadcrumb only ever retraces an
        already-verified path, never a synthesized one, and never
        extrapolates beyond the tiles actually walked."""
        trail = self._trails.get(floor_id)
        if not trail or from_tile not in trail:
            return None
        index = len(trail) - 1 - trail[::-1].index(from_tile)
        return list(reversed(trail[:index + 1]))
