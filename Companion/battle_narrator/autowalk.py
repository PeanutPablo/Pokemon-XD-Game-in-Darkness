"""Walks the player to the current entity-nav selection.

Autowalk was rejected once (see ACCESSIBILITY_BACKLOG.md's "Deferred ideas")
on the grounds that it means sending input, which the audio guide
deliberately avoids. The project owner reversed that on 2026-08-16 -- "you
may void the read only philosophy for this time" -- after an investigation
found the game already contains a scripted-stick override the engine uses on
itself, so this does not synthesise controller input, does not require
Dolphin to hold focus, and does not move the player's model directly the way
`teleport.py` does. It pushes the stick and lets the engine walk. See
`hero_stick.py` for that mechanism and its derivation.

**This module owns steering and stopping. Nothing else.** Routing is
`NavigationService`'s job, exactly as it is for the routed audio guide, and
this asks it the same question that guide asks -- "what should I aim at
right now" -- then converts that aim into a stick deflection instead of into
a tone. The two are deliberately close relatives: if the routed guide would
lead the player somewhere, autowalk walks the same line, so a player can
verify one against the other by ear.

It gets its OWN `NavigationService` instance rather than sharing the guide's.
A service holds one active route; sharing would mean turning on autowalk
silently retargeted the guide's route, and stopping either one cleared the
other's. The geometry cache inside each instance is per-room and rebuilt on
demand, so the duplication costs a second cached room, not a second parse of
every room in the game.

**Stopping is the part that matters.** A blind player cannot see that
autowalk has gone wrong, so every condition that could mean "this is no
longer walking me somewhere I want to go" ends the walk and says so, rather
than continuing on a stale assumption:

- the player touches any movement input (stick or D-pad) -- the primary,
  deliberate abort, and the one the project owner asked for;
- free-roam context is lost (a menu, dialogue, a battle, a cutscene);
- the room or floor changes -- including by walking through the very door
  being autowalked to, which is a SUCCESS, but still an unconditional stop:
  the route was built against the old room's geometry and means nothing in
  the new one;
- the entity-nav selection changes, or the target stops existing;
- routing stops being trustworthy -- anything but a real walkable route
  (see `_ROUTABLE_CONFIDENCE`);
- the player stops making progress for `BLOCKED_TIMEOUT`, which is what
  walking into unmodelled geometry looks like from here;
- `MAX_WALK_SECONDS` elapse regardless of cause, as a backstop against a
  failure mode nobody predicted.

Arrival itself is judged the same way `audio_guide.AudioGuideReader` judges
it -- real distance to the real entity position, plus a vertical tolerance
so standing underneath a target on an upper deck is not "arrived" -- because
the two must not disagree about what reaching something means.
"""
import math
import time

from .audio_guide import ARRIVAL_HEIGHT_TOLERANCE
from .entity_nav import relative_geometry
from .hero_stick import UNVERIFIED_MESSAGE
from .navigation_service import RouteConfidence
from .speech import SpeechEventClass

_ROUTABLE_CONFIDENCE = frozenset({
    RouteConfidence.VERIFIED, RouteConfidence.PARTIAL,
})
"""The only two states autowalk will move on.

VERIFIED is an ordinary walkable route into the destination's own arrival
tiles. PARTIAL is a real walkable route that provably stops short, and is
accepted because the shortfall is a measured number this module speaks
before it starts moving -- the player agrees to a walk that ends near the
target, rather than being told it arrived.

FAILED and DIRECT_FALLBACK are both refusals here, and DIRECT_FALLBACK is
the important one: it means routing has given up and the guide would switch
to pointing in a straight line. A straight line is useful advice to a person
who can feel their way around a wall. Handed to a stick, it is an
instruction to walk into that wall."""

BLOCKED_TIMEOUT = 2.5
"""Seconds of pushing the stick without getting meaningfully closer before
the walk is abandoned as blocked.

Longer than it sounds necessary on purpose. `NavigationService` legitimately
holds a waypoint through short stalls of its own (its own progress
validation runs on a 4-second timeout), and real terrain produces brief
non-progress while rounding a corner, where distance-to-target flattens for
a moment even though the walk is going fine. This is the backstop for
geometry the walk model does not describe -- a real wall the router does not
know about -- not a replacement for the router's own stall handling."""
BLOCKED_PROGRESS_EPSILON = 1.0
"""World units of improvement that count as progress. One unit is well
under a tile (8.0) and well under a single poll's travel at walking speed,
so genuine movement clears it easily while a character pinned against
collision cannot."""
MAX_WALK_SECONDS = 90.0
"""Hard ceiling on one activation. Nothing in the game should need this --
the longest measured intra-room routes are far shorter -- so reaching it
means something is wrong in a way none of the specific stops caught."""
SETTLE_GRACE = 0.5
"""How long after activation the input-abort is suppressed.

The player has just pressed a chord, and may still be holding the movement
key they were walking with when they decided to hand over. Arming the abort
immediately would make autowalk stop on the same input that started it,
which reads as "the hotkey does nothing". The abort arms as soon as no input
is seen, or when this expires -- whichever comes first, so continuing to
hold a direction past the grace period still stops the walk."""
APPROACH_DISTANCE = 14.0
"""Remaining distance at which the stick is eased off toward
`APPROACH_DEFLECTION`.

Full deflection all the way in overshoots: the engine keeps moving for a
frame or two after the last write, and arrival is a 4-unit radius. Easing
off costs a fraction of a second on a trip and makes the stop land inside
the radius instead of sailing through it."""
APPROACH_DEFLECTION = 0.55
"""Fraction of full deflection used at the closest approach. Not lower: the
engine has its own input deadzone and a stick this side of it produces no
movement at all, which would stall the walk just short of the target and
trip the blocked timeout instead of arriving."""


def stick_for_target(pose, target_position, remaining_distance=None,
                     full_deflection=0x38):
    """The stick deflection that walks from `pose` toward `target_position`.

    Camera space, not character space, and that is not an approximation:
    this game has no turn-to-face action and the camera cannot be rotated,
    so the stick IS a direction in the camera's frame (the same reasoning
    `audio_guide.guide_values` documents for pan and pitch). The decomposi-
    tion is `relative_geometry`'s, unchanged, so autowalk pushes in exactly
    the direction entity-nav describes in words and the guide describes in
    tone.

    Sign convention, live-verified 2026-08-03 in `movement_input.py` and
    independently confirmed by `_getStickData`'s D-pad branch: stick Y is
    NEGATIVE for "up"/forward, positive X is the camera's right.

    Returns (0, 0) for a target the player is already standing on, which the
    caller may write safely -- a centred stick under the override is a
    deliberate "stand still", not a release."""
    horizontal, forward, right, _ = relative_geometry(pose, target_position)
    if horizontal <= 0.0:
        return 0, 0
    scale = 1.0
    if remaining_distance is not None and remaining_distance < APPROACH_DISTANCE:
        near = max(0.0, remaining_distance) / APPROACH_DISTANCE
        scale = APPROACH_DEFLECTION + (1.0 - APPROACH_DEFLECTION) * near
    magnitude = full_deflection * scale
    return (
        int(round(right / horizontal * magnitude)),
        int(round(-forward / horizontal * magnitude)),
    )


class AutowalkReader:
    def __init__(self, entity_nav, stick, hotkey, speech, logger, navigation,
                 pose_source, movement_input, arrival_distance=4.0,
                 full_deflection=0x38, clock=time.monotonic):
        self.entity_nav = entity_nav
        self.stick = stick
        self.hotkey = hotkey
        self.speech = speech
        self.logger = logger
        self.navigation = navigation
        self.pose_source = pose_source
        self.movement_input = movement_input
        self.arrival_distance = arrival_distance
        self.full_deflection = full_deflection
        self.clock = clock
        self.active = False
        self.category_key = None
        self.identity = None
        self.floor_id = None
        self.started_at = None
        self.abort_armed = False
        self.best_distance = None
        self.best_distance_at = None

    def _say(self, text):
        self.speech.emit(
            SpeechEventClass.ENTITY_NAV, text, deduplicate=False,
            interrupt=True)
        self.logger.info("AUTOWALK %s", text)

    def clear(self, reason):
        """Stop walking. Always releases the override, even when this
        reader does not believe it is active -- see `hero_stick.py` on why
        the release path is the one that must never be conditional."""
        self.stick.release()
        if self.active:
            self.navigation.clear()
            self.logger.debug("AUTOWALK CLEAR reason=%s", reason)
        self.active = False
        self.category_key = None
        self.identity = None
        self.floor_id = None
        self.started_at = None
        self.abort_armed = False
        self.best_distance = None
        self.best_distance_at = None

    def _stop(self, reason, message):
        self.clear(reason)
        self._say(message)

    def _current_target(self):
        state = self.entity_nav.state
        if state.category_key is None or state.selected_identity is None:
            return None, None
        source = self.entity_nav.sources.get(state.category_key)
        if source is None:
            return None, None
        entities = {entity.identity: entity for entity in source.entities()}
        return source, entities.get(state.selected_identity)

    def _context_valid(self):
        """Free-roam gate, borrowed from entity navigation rather than
        re-derived: `EntityNavigator.context_valid` is already false while a
        window is open or dialogue is up, which covers menus, shops,
        battles and scripted scenes in one already-live-proven test."""
        return bool(getattr(self.entity_nav, "context_valid", False))

    def poll_once(self):
        if self.hotkey.poll():
            self._toggle()
            return
        if not self.active:
            return
        self._advance()

    def _toggle(self):
        if self.active:
            self._stop("toggled off", "Autowalk off.")
            return
        if not self._context_valid():
            self._say("Autowalk needs free movement.")
            return
        if not self.stick.verify():
            self._say(UNVERIFIED_MESSAGE)
            return
        source, entity = self._current_target()
        if entity is None:
            self._say("No entity selected to walk to.")
            return
        floor_id = self.pose_source.current_floor_id()
        pose = source.player_pose()
        self.navigation.begin(
            floor_id, entity.position, pose.position,
            destination_region=(entity.metadata or {}).get("region"))
        self.active = True
        self.category_key = self.entity_nav.state.category_key
        self.identity = self.entity_nav.state.selected_identity
        self.floor_id = floor_id
        self.started_at = self.clock()
        # Not armed yet: the player may still be holding the direction they
        # were walking in. See SETTLE_GRACE.
        self.abort_armed = False
        self.best_distance = None
        self.best_distance_at = self.started_at
        self._say(f"Autowalk on, {entity.label or 'target'}.")

    def _advance(self):
        now = self.clock()
        if self._aborting(now):
            return
        source, entity = self._current_target()
        state = self.entity_nav.state
        if (state.category_key != self.category_key
                or state.selected_identity != self.identity):
            self._stop("selection changed", "Autowalk stopped: selection changed.")
            return
        if entity is None:
            self._stop("target gone", "Autowalk stopped: target no longer available.")
            return
        floor_id = self.pose_source.current_floor_id()
        if floor_id != self.floor_id:
            # Reached by walking through a door as well as by any other room
            # change, and stopping is right either way: the route belongs to
            # the room it was built in.
            self._stop("floor changed", "Autowalk stopped: new area.")
            return
        pose = source.player_pose()
        real_distance, _, _, vertical = relative_geometry(pose, entity.position)
        if (real_distance <= self.arrival_distance
                and abs(vertical) <= ARRIVAL_HEIGHT_TOLERANCE):
            self._stop("arrived", "Arrived.")
            return
        self.navigation.update(
            floor_id, entity.position, pose.position,
            destination_region=(entity.metadata or {}).get("region"))
        result = self.navigation.next_waypoint(pose.position)
        if not result.path_available or result.confidence not in _ROUTABLE_CONFIDENCE:
            self._stop(
                f"unroutable confidence={result.confidence}",
                "Autowalk stopped: no walkable route.")
            return
        if result.partial_started:
            # Spoken before the walk continues, not after it ends, so the
            # player knows what they are getting while it is still theirs to
            # cancel. Mirrors the routed guide's own PARTIAL announcement.
            pieces = ["Cannot reach it; walking to the closest point I can reach"]
            if result.partial_shortfall is not None:
                pieces.append(f"{round(result.partial_shortfall)} short")
            self._say(", ".join(pieces) + ".")
        remaining = (
            result.remaining_distance
            if result.remaining_distance is not None else real_distance
        )
        if self._blocked(remaining, now):
            self._stop("blocked", "Autowalk stopped: blocked.")
            return
        x, y = stick_for_target(
            pose, result.target_position, remaining,
            full_deflection=self.full_deflection)
        self.stick.hold(x, y)

    def _aborting(self, now):
        """The stop conditions that do not need a route, a pose or a target
        -- checked first precisely because they must still work when
        reading any of those would fail."""
        if not self._context_valid():
            self._stop("context lost", "Autowalk stopped.")
            return True
        requested = self.movement_input.is_movement_requested()
        if not self.abort_armed:
            if not requested:
                # First moment of no input: the player has let go of
                # whatever they were holding, so their next press is a real
                # request rather than the tail of the one before.
                self.abort_armed = True
            elif (self.started_at is not None
                    and now - self.started_at >= SETTLE_GRACE):
                # Still held this long after activation: no longer plausibly
                # leftover, so honour it. Arming and acting on the same poll
                # matters -- deferring to the next one would keep walking
                # against input the player is actively holding.
                self.abort_armed = True
        if requested and self.abort_armed:
            self._stop("player input", "Autowalk off.")
            return True
        if self.started_at is not None and now - self.started_at >= MAX_WALK_SECONDS:
            self._stop("time limit", "Autowalk stopped: taking too long.")
            return True
        return False

    def _blocked(self, remaining, now):
        """True once `BLOCKED_TIMEOUT` has passed with no real improvement.

        Measured against the best distance ever achieved on this walk rather
        than the previous poll's, so oscillating back and forth across the
        same spot -- which is what being stuck against geometry actually
        looks like -- cannot keep resetting the timer."""
        if remaining is None or not math.isfinite(remaining):
            return False
        if self.best_distance is None or remaining < self.best_distance - BLOCKED_PROGRESS_EPSILON:
            self.best_distance = remaining
            self.best_distance_at = now
            return False
        if self.best_distance_at is None:
            self.best_distance_at = now
            return False
        return now - self.best_distance_at >= BLOCKED_TIMEOUT
