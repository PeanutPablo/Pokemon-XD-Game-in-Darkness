"""Read-only, continuous "hot/cold" audio guidance toward whatever entity
is currently selected in entity navigation.

Never sends input, never touches the emulated controller, never moves the
player -- exactly like the rest of entity_nav.py, this only reads memory
and plays sound. The player walks themselves; this just reports direction
and distance as a repeating spatial tone instead of speech, so it doesn't
compete with dialogue/narration for the speech channel.

Reuses proven building blocks rather than inventing new ones:
- `entity_nav.relative_geometry` for the exact same camera-relative
  forward/right decomposition entity-nav's own spoken descriptions use.
- The same "closer = faster repeat" beacon cadence formula already proven
  in npc_beacons.py's NPCSoundReader, so the guide tone feels consistent
  with the passive proximity beacons the player already knows.
- `npc_beacons.SpatialWavePlayer` for pan/pitch/gain rendering.

Obstacle-aware routing is delegated entirely to a `navigation_service.
NavigationService` (constructor-injected) -- this class owns none of the
pathfinding/room-geometry/hysteresis details itself, only asking the
service each poll "what should I aim at right now" and feeding that into
`guide_values()`'s pan/pitch/gain math. Arrival stays keyed to the REAL
entity position and the existing `arrival_distance`, never to a tile or
waypoint, regardless of what the navigation service is doing internally --
see the two separate distance computations in `poll_once` below.

**Two modes, one class (2026-08-04, project owner's request).** Passing
`navigation=None` gives the DIRECT mode: a single beacon that sits on the
selected entity itself, with pan/pitch/gain describing the straight line to
it and no routing, waypoints, or route announcements of any kind. Passing a
real `NavigationService` gives the ROUTED mode described above. Production
runs one of each -- ctrl+shift+g for the direct beacon, ctrl+shift+n for
routed navigation -- and turning either on turns the other off (see
`peer`), because two spatial cues describing different aim points at once
is exactly the ambiguity this interface exists to avoid. They are one class
rather than two because everything except the aim point is identical:
selection tracking, arrival, cadence, and the pan/pitch/gain math.

Pan (left/right), pitch (forward/backward facing), and gain+repeat-rate
(proximity/"hot-cold") each carry one distinct signal -- see
`guide_values()`'s own docstring for the project owner's live-caught
correction (2026-07-30) that pitch and repeat-rate originally "double
dipped" on the same proximity job.

Cross-room guidance is intentionally NOT automatic routing through a room
graph -- NavigationService itself is intra-room only (a floor/room change
invalidates its route). Doors and warps are already their own entity-nav
categories with real, authoritative positions (see authoritative_warps.py)
-- guiding to a door, walking through it, then selecting the real target in
the new room composes naturally with the category system already in place.
Automatic multi-room path selection is a reasonable follow-up, not
implemented here.
"""
import time

from .entity_nav import relative_geometry
from .npc_beacons import navigation_gain
from .speech import SpeechEventClass

WAYPOINT_REACHED_GAIN = 0.7
"""Fixed gain for the one-shot "waypoint reached" confirmation cue --
unrelated to proximity, so it doesn't need the hot/cold gain math."""

ARRIVAL_HEIGHT_TOLERANCE = 10.0
"""How far, in world units, the target may sit above or below the player
and still count as arrived at.

Arrival compared `relative_geometry`'s HORIZONTAL component only -- it
already computes a `vertical` component, which was simply discarded. So
standing directly beneath a target on an upper terrace announced
"Arrived." while the player was nowhere near able to reach it. Same
discarded-Y mistake as `navigation_service.WAYPOINT_CAPTURE_HEIGHT_
TOLERANCE`, which was caught live on 2026-08-04 in `M3_out`; this one was
found by reading the code alongside it rather than from a log, so it is
fixed on the same reasoning rather than its own live evidence.

Shares that constant's 10.0 for the same reason it does: it is the measured
bound on how much height one continuous walkable surface changes across a
tile in real `M3_out` terrain (steepest genuine slope step: 7.40). A target
standing on a slope or a step near the player stays comfortably inside it;
one on a different deck does not."""


def guide_values(pose, position, max_distance, proximity_distance=None):
    """Pan/pitch/gain for the guide tone.

    **This game has no turn-to-face action** (project owner, 2026-08-03:
    "this game does not support turning to orient, it's just moving in any
    direction"), and the camera cannot be rotated. So pan and pitch are not
    "which way to turn" -- together they say *which way to push the stick*,
    in fixed camera space. That is why the pair is sufficient on its own:
    left/right and forward/back fully determine a stick direction here.

    Pan reflects the left/right component using the same camera-relative
    right-component entity-nav's spoken clock positions already use, so a
    centred tone means the same thing entity-nav calls "12 o'clock."

    Pitch carries the forward/back component, not proximity (project owner's
    explicit correction, 2026-07-30: pitch and the repeat-rate/gain
    "hot/cold" intensity were both signaling distance -- redundant, "double
    dipping" on the same job). Pitch rises when the target lies ahead in
    camera space (push "up" on the stick) and falls when it lies behind
    (push "down"), via the cosine of the angle from straight-ahead --
    continuously, not
    the discrete clock-position bins the project owner first described
    (10-2 o'clock high / 4-8 o'clock low): a hard-binned version would
    audibly "step" right at the 3/9 o'clock boundary, where continuous
    interpolation instead passes smoothly through a neutral pitch. This
    reuses the same `forward`/`horizontal` values `relative_geometry`
    already computes for `pan`, referencing whatever `position` the caller
    passed in (the routed waypoint during obstacle-aware guidance, so pan
    and pitch always describe the same immediate direction) -- no new
    geometry, no second position argument.

    Gain remains the sole proximity ("hot/cold") signal, paired with the
    caller's own repeat-cadence calculation. `proximity_distance`, when
    given, drives gain instead of the raw distance to `position` -- needed
    because routed guidance computes pan/pitch from the next walkable
    waypoint (so steering follows the correct immediate direction around an
    obstacle) but wants gain to reflect the REMAINING distance along the
    whole route, not the distance to that one nearby waypoint. Without
    this, gain would cycle cold->hot every single tile hop instead of
    smoothly warming up across the whole trip. `horizontal` (the first
    return value) is always the true distance to `position`, unaffected by
    this override -- callers needing a plain distance (e.g. arrival checks)
    should pass the real target position with no override."""
    horizontal, forward, right, vertical = relative_geometry(pose, position)
    pan = max(-1.0, min(1.0, right / horizontal)) if horizontal else 0.0
    facing = (forward / horizontal) if horizontal else 1.0
    pitch = 2.0 ** facing
    reference_distance = horizontal if proximity_distance is None else proximity_distance
    proximity = max(0.0, min(1.0, 1.0 - reference_distance / max_distance))
    # Shared with the passive beacons, which play at a fixed fraction of
    # this (npc_beacons.PASSIVE_BEACON_GAIN_SCALE). Retuning the curve here
    # moves both together and keeps that ratio intact.
    gain = navigation_gain(proximity)
    return horizontal, pan, pitch, gain


class AudioGuideReader:
    def __init__(self, entity_nav, player, sound_path, hotkey, speech, logger,
                 navigation, pose_source,
                 max_distance=120.0, arrival_distance=4.0, clock=time.monotonic,
                 waypoint_sound_path=None, name="Guide"):
        self.entity_nav = entity_nav
        self.player = player
        self.sound_path = sound_path
        self.hotkey = hotkey
        self.speech = speech
        self.logger = logger
        self.navigation = navigation
        """`None` puts this reader in direct mode -- a beacon on the entity
        itself, no routing. See this module's own docstring."""
        self.pose_source = pose_source
        self.max_distance = max_distance
        self.arrival_distance = arrival_distance
        self.clock = clock
        self.waypoint_sound_path = waypoint_sound_path
        self.name = name
        """What this reader calls itself when it speaks ("Beacon on.",
        "Navigation on."), so the player can tell which of the two is
        running from the announcement alone."""
        self.peer = None
        """Optionally the other mode's reader. Set after construction (they
        reference each other, so neither can take the other in its
        constructor). Turning this one on turns the peer off."""
        self.active = False
        self.category_key = None
        self.identity = None
        self.next_due = 0.0

    def clear(self, reason):
        if self.active:
            self.player.stop()
            if self.navigation is not None:
                self.navigation.clear()
            self.logger.debug("AUDIO GUIDE %s CLEAR reason=%s", self.name, reason)
        self.active = False
        self.category_key = None
        self.identity = None

    def _say(self, text):
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, deduplicate=False, interrupt=True)
        self.logger.info("AUDIO GUIDE %s", text)

    def _current_target(self):
        state = self.entity_nav.state
        if state.category_key is None or state.selected_identity is None:
            return None, None
        source = self.entity_nav.sources.get(state.category_key)
        if source is None:
            return None, None
        entities = {entity.identity: entity for entity in source.entities()}
        return source, entities.get(state.selected_identity)

    def poll_once(self):
        triggered = self.hotkey.poll()
        if triggered:
            if self.active:
                self.clear("toggled off")
                self._say(f"{self.name} off.")
                return
            source, entity = self._current_target()
            if entity is None:
                self._say("No entity selected to guide to.")
                return
            # Only one spatial aim point at a time: two beacons describing
            # different directions at once is the ambiguity this interface
            # exists to remove.
            if self.peer is not None and self.peer.active:
                self.peer.clear("superseded by the other guide mode")
            self.active = True
            self.category_key = self.entity_nav.state.category_key
            self.identity = self.entity_nav.state.selected_identity
            self.next_due = 0.0
            if self.navigation is not None:
                # The player's position is passed at ACTIVATION, not left to
                # be picked up on the first poll. The route is built right
                # here, and an off-floor destination needs to know where the
                # player is in order to seed somewhere they can actually
                # reach (see `pathfinding.flow_field_toward`). Live
                # 2026-08-04: without it the garage seeded a five-node pocket
                # by the stairwell and reported the player unlinked forever.
                self.navigation.begin(
                    self.pose_source.current_floor_id(), entity.position,
                    source.player_pose().position)
            self._say(f"{self.name} on.")
            return
        if not self.active:
            return
        state = self.entity_nav.state
        if state.category_key != self.category_key or state.selected_identity != self.identity:
            self.clear("selection changed")
            self._say(f"{self.name} stopped: selection changed.")
            return
        source, entity = self._current_target()
        if entity is None:
            self.clear("target no longer available")
            self._say(f"{self.name} stopped: target no longer available.")
            return
        pose = source.player_pose()
        # Arrival is always judged against the real, un-snapped entity
        # position and the existing arrival_distance -- never against a
        # tile or waypoint -- regardless of what the navigation service
        # does internally for the tone's aim below.
        real_distance, _, _, _ = guide_values(pose, entity.position, self.max_distance)
        # ...and against the vertical separation too: being directly below
        # something on an upper deck is not being at it. See
        # ARRIVAL_HEIGHT_TOLERANCE.
        _, _, _, vertical = relative_geometry(pose, entity.position)
        if (real_distance <= self.arrival_distance
                and abs(vertical) <= ARRIVAL_HEIGHT_TOLERANCE):
            self._say("Arrived.")
            self.clear("arrived")
            return
        if self.navigation is None:
            # Direct mode: the beacon simply sits on the entity. No routing,
            # no waypoints, no route announcements -- pan/pitch describe the
            # straight line to it and gain its raw distance.
            self._emit_tone(pose, entity.position, real_distance,
                            self.max_distance)
            return
        self.navigation.update(
            self.pose_source.current_floor_id(), entity.position, pose.position)
        result = self.navigation.next_waypoint(pose.position)
        if result.fallback_started:
            self._say("No walkable path found; guiding directly.")
        if result.progress_invalidated:
            self._say("Walkable route could not be verified; guiding directly.")
        if result.waypoint_advanced and self.waypoint_sound_path is not None:
            self.player.play(self.waypoint_sound_path, 0.0, 1.0, WAYPOINT_REACHED_GAIN)
        # The "hot/cold" gain/pitch/repeat-cadence gradient is normalized
        # against `effective_max_distance`, not always `self.max_distance`
        # directly -- see NavigationResult.route_initial_distance's own
        # docstring. A genuinely long routed trip can exceed
        # `self.max_distance` for most of its length; without this, the
        # tone stayed clamped near "cold" until the last stretch (caught
        # live: "doesn't change... unless I'm really close"). Widening the
        # denominator to at least the trip's own starting distance spans
        # the gradient across the whole walk, while a short trip (already
        # under `self.max_distance`) keeps behaving exactly as before.
        effective_max_distance = self.max_distance
        if result.path_available:
            target_position = result.target_position
            proximity_distance = (
                result.remaining_distance
                if result.remaining_distance is not None else real_distance
            )
            if result.route_initial_distance is not None:
                effective_max_distance = max(
                    self.max_distance, result.route_initial_distance)
        else:
            target_position = entity.position
            proximity_distance = real_distance
        self._emit_tone(pose, target_position, proximity_distance,
                        effective_max_distance)

    def _emit_tone(self, pose, target_position, proximity_distance,
                   effective_max_distance):
        """Render one beacon pulse aimed at `target_position`, subject to
        the proximity-scaled repeat cadence. Shared by both modes -- the
        only thing that differs between them is which position gets passed
        in here and what distance drives the gradient."""
        _, pan, pitch, gain = guide_values(
            pose, target_position, effective_max_distance,
            proximity_distance=proximity_distance,
        )
        now = self.clock()
        if now < self.next_due:
            return
        self.player.play(self.sound_path, pan, pitch, gain)
        distance_ratio = min(1.0, proximity_distance / effective_max_distance)
        interval = 0.15 + 0.85 * (distance_ratio ** 1.25)
        self.next_due = now + interval


class GuideModes:
    """The two guide readers (direct beacon, routed navigation) presented to
    the lifecycle as one pollable reader, since it owns a single guide slot.

    Nothing more than a pair: it polls both and clears both. The mutual
    exclusion between them lives in `AudioGuideReader.peer`, not here, so it
    holds however the two are driven -- including from separate hotkey polls
    in a future arrangement that doesn't route through this class."""

    def __init__(self, beacon, navigation):
        self.beacon = beacon
        self.navigation = navigation
        beacon.peer = navigation
        navigation.peer = beacon

    def poll_once(self):
        self.beacon.poll_once()
        self.navigation.poll_once()

    def clear(self, reason):
        self.beacon.clear(reason)
        self.navigation.clear(reason)
