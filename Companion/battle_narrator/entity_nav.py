"""Read-only, hotkey-driven overworld entity navigation ("item navigation").

Selects and describes nearby overworld entities (NPCs first, treasures
later) relative to the player. Never sends input, never touches the
emulated controller, never moves the player. Speech only.

Direction is computed relative to the player's *camera-relative facing*,
matching the convention already proven and shipped in npc_beacons.py's
NPCSoundReader.spatial_values -- that function derives "forward"/"right"
axes from the active camera's yaw (not the hero model's own rotation, and
not world north), and this module reuses the identical basis vectors so a
clock direction here means the same thing the existing spatial-audio pan
already means. See NAV_MATH.md-style notes below for the exact transform.

Coordinate system and angle transform (documented per project requirement):
  - Player pose position/yaw comes from NPCMemorySource.player_pose()
    (reused, not recomputed): position is (x, y, z) in game units, yaw is
    the active camera's yaw rotation component, in radians.
  - forward = (-sin(yaw), -cos(yaw)) in the (x, z) plane; right = (cos(yaw),
    -sin(yaw)) -- identical to npc_beacons.NPCSoundReader.spatial_values.
  - For an entity at relative offset (dx, dz) = (entity.x - player.x,
    entity.z - player.z): forward_component = dx*forward_x + dz*forward_z,
    right_component = dx*right_x + dz*right_z.
  - angle = degrees(atan2(right_component, forward_component)) mod 360.
    0 degrees = straight ahead = 12 o'clock; 90 = directly right = 3
    o'clock; 180 = directly behind = 6 o'clock; 270 = directly left = 9
    o'clock. clock = round(angle / 30) mod 12, with 0 displayed as 12.
  - Vertical relationship uses entity.y - player.y against a documented,
    uncalibrated threshold (profile.entity_nav_vertical_threshold).
  - Distance is the raw horizontal (x/z-plane) game-unit distance, rounded
    to the nearest integer. It is deliberately NOT labeled "meters" --
    no game-unit-to-real-world calibration has been verified in this
    project, so a neutral "distance N" scale is used instead.
"""
import math
import time
from dataclasses import dataclass

from .memory import MemoryError as GameMemoryError
from .speech import SpeechEventClass
from .talk_predicate import REJECT_FACING, REJECT_WALL


NO_ENTITIES_MESSAGE = "No navigable entities nearby."
ENTITY_GONE_MESSAGE = "Selected entity is no longer available."


def relative_geometry(pose, position):
    dx = position.x - pose.position.x
    dz = position.z - pose.position.z
    horizontal = math.hypot(dx, dz)
    forward_x, forward_z = -math.sin(pose.yaw), -math.cos(pose.yaw)
    right_x, right_z = math.cos(pose.yaw), -math.sin(pose.yaw)
    forward_component = dx * forward_x + dz * forward_z
    right_component = dx * right_x + dz * right_z
    vertical = position.y - pose.position.y
    return horizontal, forward_component, right_component, vertical


def facing_error(pose, position):
    """Absolute angle, in degrees, between the direction the player's
    character is physically turned and the direction to `position`.

    This is the quantity the game's own `peopleTalkCheck` gates on (see
    profile.talk_cone_degrees). It uses the HERO's rotation, not the
    camera's -- the two are unrelated, and the camera is what every spoken
    bearing is expressed in. Returns None when the hero facing could not be
    read, so callers suppress facing-dependent wording rather than guess."""
    if pose.facing is None:
        return None
    dx = position.x - pose.position.x
    dz = position.z - pose.position.z
    horizontal = math.hypot(dx, dz)
    if horizontal == 0.0:
        return 0.0
    # Same convention the engine uses for a heading: rot.y == 0 faces -Z.
    face_x, face_z = -math.sin(pose.facing), -math.cos(pose.facing)
    dot = (dx * face_x + dz * face_z) / horizontal
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


OCTANTS = (
    "ahead", "ahead-right", "right", "behind-right",
    "behind", "behind-left", "left", "ahead-left",
)


def relative_octant(forward_component, right_component):
    """Coarse camera-relative direction word ("behind-right").

    Deliberately the SAME frame as clock_position and as the audio guide's
    pan/pitch: the camera's, which is also what the joystick maps to. The
    character's own facing is never used for a direction word -- it is only
    ever reported as a state (see describe_entity), because mixing the two
    frames in one sentence would make neither actionable."""
    angle = math.degrees(math.atan2(right_component, forward_component))
    return OCTANTS[int((angle % 360 + 22.5) // 45) % 8]


def clock_position(horizontal, forward_component, right_component, same_position_threshold):
    if horizontal < same_position_threshold:
        return None
    angle = math.degrees(math.atan2(right_component, forward_component)) % 360
    clock = round(angle / 30) % 12
    return 12 if clock == 0 else clock


def describe_entity(profile, category_key, entity, pose, include_category=True):
    """`include_category=False` drops the leading category word.

    Cycling within a category repeats it on every single press -- "NPC.
    Jovi...", "NPC. Krane...", "NPC. Lily..." -- which is pure padding in
    front of the thing the player actually wants, on the hotkey they press
    most. The category is still announced when it CHANGES (switching
    categories), which is where it carries information."""
    horizontal, forward, right, vertical = relative_geometry(pose, entity.position)
    clock = clock_position(
        horizontal, forward, right, profile.entity_nav_same_position_threshold
    )
    singular = dict(zip(
        profile.entity_nav_category_keys, profile.entity_nav_category_singular_labels
    ))[category_key]
    # Warp labels are prepositional fragments ("to Pyrite Town police
    # station") written to follow the category word. Dropping the word left
    # them as sentence fragments -- "Warps. 2 available. to Pokemon HQ Lab."
    # -- so the noun is kept whenever the label cannot stand alone. Labels
    # that already lead with their own noun ("Elevator to ...", "Sign", a
    # character's name) are unaffected.
    label_needs_noun = bool(entity.label) and entity.label.startswith("to ")
    pieces = []
    if label_needs_noun and not include_category:
        # One phrase, not two: "Warp to X", never "Warp. to X".
        pieces.append(f"{singular} {entity.label}")
    else:
        if include_category:
            pieces.append(singular)
        if entity.label:
            pieces.append(entity.label)
    if clock is None:
        pieces.append("same position")
    else:
        clock_piece = f"{clock} o'clock, distance {round(horizontal)}"
        if abs(vertical) > profile.entity_nav_vertical_threshold:
            clock_piece += ", " + ("above" if vertical > 0 else "below")
        pieces.append(clock_piece)
    verdict = entity.metadata.get("verdict") if entity.metadata else None
    if verdict is not None:
        # The source already evaluated the game's OWN predicate against the
        # game's own reference point, so re-deriving range here from a
        # horizontal distance to the model origin would just reintroduce
        # the approximation the verdict exists to replace.
        if verdict.eligible:
            pieces.append("Interaction available")
        elif not verdict.in_range:
            pieces.append("Out of interaction range")
        elif verdict.reason == REJECT_FACING:
            # "walk toward it", not "turn around": this game has no
            # turn-in-place, so walking IS the only way to change facing,
            # and doing so keeps the player inside the interaction radius.
            pieces.append("In range but facing away, walk toward it")
        elif verdict.reason == REJECT_WALL:
            pieces.append("In range but something is in the way")
        elif verdict.unknown_gates:
            # In range, nothing known to reject it, but at least one gate
            # could not be checked. Say what is true -- close enough --
            # without promising the press will land.
            pieces.append("In range")
        else:
            pieces.append("Out of interaction range")
    elif entity.interaction_distance is not None:
        in_range = horizontal <= (
            entity.interaction_distance + profile.interaction_collision_allowance
        )
        if not in_range:
            pieces.append("Out of interaction range")
        else:
            error = facing_error(pose, entity.position)
            if error is not None and error > profile.talk_cone_degrees:
                pieces.append("In range but facing away, walk toward it")
            else:
                pieces.append("Interaction available")
    return ". ".join(pieces) + "."


@dataclass
class NavState:
    floor_id: object = None
    category_key: object = None
    frozen_order: tuple = ()
    selected_identity: object = None


class EntityNavigator:
    """Owns category/selection state and the five foreground-scoped hotkeys:
    next, prev, next_category, prev_category, repeat.

    There is no refresh action. It was removed on 2026-08-16 at the project
    owner's request, once it emerged that its chord had always been
    swallowed by `repeat`'s (see profile.default_autowalk_hotkey), so it had
    never run in production. Its purpose -- picking up entities that
    appeared after a category was activated, which next/prev cannot reach
    because they cycle the order frozen at activation -- is still served by
    switching category away and back, since `_activate_category` re-reads
    the live list every time.

    `sources` maps category key -> an object with `.entities()` (list of
    Entity, already filtered to valid/present/interactable by the source)
    and `.player_pose()`. `hotkeys` maps action name -> an object with
    `.poll()` (WindowsForegroundHotkey-compatible: edge-triggered, foreground
    scoped to Dolphin.exe).
    """

    def __init__(
        self, memory, profile, sources, hotkeys, speech, logger,
        clock=time.monotonic,
    ):
        self.memory = memory
        self.profile = profile
        self.sources = sources
        self.hotkeys = hotkeys
        self.speech = speech
        self.logger = logger
        self.clock = clock
        self.state = NavState()
        self.context_valid = False
        self._last_position = None
        """Player position at the previous poll, for the stand-still test."""
        self._stationary_since = None
        """When the player last stopped moving, or None while they are
        moving (or while their position could not be read)."""
        self._announced_this_stop = False
        """Whether the current stop has already produced an announcement --
        manual or automatic. Reset when the player moves again, which is
        what makes the auto-repeat fire once per stop rather than every
        `entity_nav_auto_repeat_seconds` for as long as they stand there."""
        self.auto_repeat_enabled = True
        """Settings-menu override for the stand-still re-announcement. The
        manual hotkeys are deliberately unaffected: this switches off the
        UNPROMPTED repeat, not the ability to ask for one."""
        self.auto_repeat_seconds = None
        """Settings-menu override for the stand-still delay, or None to use
        the profile's own `entity_nav_auto_repeat_seconds`. The profile is a
        frozen dataclass and is never mutated."""

    def clear(self, reason):
        self.state = NavState()
        self.context_valid = False
        self._reset_auto_repeat()
        self.logger.debug("ENTITY NAV cleared: %s", reason)

    def _reset_auto_repeat(self):
        self._last_position = None
        self._stationary_since = None
        self._announced_this_stop = False

    def _window_open(self):
        p = self.profile
        pointer = self.memory.u32(
            p.window_manager + p.window_list_offset, "entity-nav window head"
        )
        return pointer != 0

    def _refresh_context(self, dialogue_active):
        p = self.profile
        floor_id = self.memory.u16(p.current_floor_id, "entity-nav floor id")
        window_open = self._window_open()
        valid = not window_open and not dialogue_active
        if self.state.floor_id is not None and floor_id != self.state.floor_id:
            # Still cleared on a map change: the entities themselves are
            # per-room, so a remembered selection would name something that
            # is not in the room any more.
            self.clear("map changed")
        # Deliberately NOT cleared when free-roaming control is lost. It
        # used to be, which meant opening a menu or talking to anyone reset
        # the category to the first available and the highlight to the
        # nearest entity -- so the common loop of "find someone, talk to
        # them, carry on down the list" silently threw the list away every
        # time, and the player had to walk back down it from the top.
        #
        # Nothing goes stale by keeping it: `_cycle` and `_repeat` both
        # re-read the live entity list every press and re-resolve the
        # selection by identity, falling back when it has genuinely gone. `context_valid` still gates the ACTIONS, so
        # nothing responds to the hotkeys while a menu or dialogue is up.
        self.context_valid = valid
        self.state.floor_id = floor_id

    def _speak(self, text):
        # Any announcement satisfies the current stop, so a deliberate press
        # while standing still is not followed 1.5 seconds later by the same
        # sentence again. See `_poll_auto_repeat`.
        self._announced_this_stop = True
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, deduplicate=False, interrupt=True)
        self.logger.info("ENTITY NAV %s", text)

    def _available_categories(self):
        available = []
        for key in self.profile.entity_nav_category_keys:
            source = self.sources.get(key)
            if source is not None and self._source_entities(key):
                available.append(key)
        return available

    def _source_entities(self, key):
        """Read one category without letting it erase unrelated categories.

        Some rooms legitimately have no floor-character array. The NPC
        source reports that as an unreadable pointer, but static treasures,
        exits and interactables remain valid and useful. Treat a failed
        category as temporarily empty and continue surveying the others.
        """
        source = self.sources.get(key)
        if source is None:
            return []
        try:
            return source.entities()
        except (GameMemoryError, MemoryError) as exc:
            self.logger.debug(
                "ENTITY NAV source %s unavailable: %s", key, exc)
            return []

    def _activate_category(self, key):
        p = self.profile
        source = self.sources[key]
        entities = self._source_entities(key)
        pose = source.player_pose()
        ordered = sorted(
            entities, key=lambda entity: relative_geometry(pose, entity.position)[0]
        )
        self.state.category_key = key
        self.state.frozen_order = tuple(entity.identity for entity in ordered)
        self.state.selected_identity = ordered[0].identity if ordered else None
        plural = dict(zip(
            p.entity_nav_category_keys, p.entity_nav_category_plural_labels
        ))[key]
        header = f"{plural}. {len(ordered)} available."
        if ordered:
            # No category word on the entity: the header just said it, so
            # including it produced "NPCs. 1 available. NPC. Rui...".
            self._speak(header + " " + describe_entity(
                p, key, ordered[0], pose, include_category=False))
        else:
            self._speak(header)

    def _switch_category(self, direction):
        available = self._available_categories()
        if not available:
            self.state = NavState(floor_id=self.state.floor_id)
            self._speak(NO_ENTITIES_MESSAGE)
            return
        if self.state.category_key in available:
            index = available.index(self.state.category_key)
            new_index = (index + direction) % len(available)
        else:
            new_index = 0
        self._activate_category(available[new_index])

    def _cycle(self, direction):
        if self.state.category_key is None:
            self._switch_category(1)
            return
        source = self.sources[self.state.category_key]
        entities = {
            entity.identity: entity
            for entity in self._source_entities(self.state.category_key)
        }
        live_order = [
            identity for identity in self.state.frozen_order if identity in entities
        ]
        if not live_order:
            self._switch_category(1)
            return
        if self.state.selected_identity in live_order:
            index = live_order.index(self.state.selected_identity)
            new_index = (index + direction) % len(live_order)
        else:
            new_index = 0
        new_identity = live_order[new_index]
        self.state.selected_identity = new_identity
        pose = source.player_pose()
        self._speak(describe_entity(
            self.profile, self.state.category_key, entities[new_identity], pose,
            include_category=False,
        ))

    def _repeat(self):
        if self.state.category_key is None or self.state.selected_identity is None:
            return
        source = self.sources[self.state.category_key]
        entities = {
            entity.identity: entity
            for entity in self._source_entities(self.state.category_key)
        }
        entity = entities.get(self.state.selected_identity)
        if entity is None:
            self.state.selected_identity = None
            self._speak(ENTITY_GONE_MESSAGE)
            return
        pose = source.player_pose()
        self._speak(describe_entity(self.profile, self.state.category_key, entity, pose))

    def _poll_auto_repeat(self):
        """Re-announce the current selection once the player has stood still
        for `entity_nav_auto_repeat_seconds`.

        The case this serves: you walk toward something, stop, and want to
        know where it is now without taking a hand off the stick to press
        repeat. So it is keyed to STOPPING, not to elapsed time -- it fires
        once per stop and re-arms only when the player moves again.

        Deliberately quiet in every ambiguous case. It never speaks when
        there is no selection, when the selection has gone missing (unlike
        the manual repeat, which says so and clears -- an unprompted
        announcement should not act on what might be a transient bad read),
        or when the player's position cannot be read at all. Nothing here
        changes selection state; it only reads and speaks."""
        p = self.profile
        if not self.auto_repeat_enabled:
            # Tracking is dropped rather than merely muted, so switching it
            # back on starts from the player's next stop instead of firing
            # immediately off a stop that happened while it was off.
            self._reset_auto_repeat()
            return
        if self.state.category_key is None or self.state.selected_identity is None:
            self._reset_auto_repeat()
            return
        source = self.sources.get(self.state.category_key)
        if source is None:
            self._reset_auto_repeat()
            return
        try:
            pose = source.player_pose()
        except (GameMemoryError, MemoryError):
            # Same convention as the rest of this project: a transient bad
            # read resets local state rather than propagating. Treated as
            # "position unknown", so the next good read starts a fresh stop
            # instead of counting the gap as standing still.
            self._reset_auto_repeat()
            return
        position = pose.position
        previous, self._last_position = self._last_position, position
        if previous is None:
            return
        moved = math.hypot(position.x - previous.x, position.z - previous.z)
        if moved >= p.entity_nav_auto_repeat_movement_epsilon:
            self._stationary_since = None
            self._announced_this_stop = False
            return
        now = self.clock()
        if self._stationary_since is None:
            self._stationary_since = now
            return
        if self._announced_this_stop:
            return
        delay = (
            p.entity_nav_auto_repeat_seconds
            if self.auto_repeat_seconds is None else self.auto_repeat_seconds
        )
        if now - self._stationary_since < delay:
            return
        entities = {
            entity.identity: entity
            for entity in self._source_entities(self.state.category_key)
        }
        entity = entities.get(self.state.selected_identity)
        if entity is None:
            # Silent, and the selection is left alone -- see this method's
            # own docstring.
            self._announced_this_stop = True
            return
        self._speak(describe_entity(
            p, self.state.category_key, entity, pose))

    def poll_once(self, dialogue_active=False):
        self._refresh_context(dialogue_active)
        # Hotkeys are polled every tick regardless of context validity so
        # their edge-triggered held-state tracking stays correct; only the
        # resulting *actions* are gated on context_valid below.
        next_fired = self.hotkeys["next"].poll()
        prev_fired = self.hotkeys["prev"].poll()
        next_category_fired = self.hotkeys["next_category"].poll()
        prev_category_fired = self.hotkeys["prev_category"].poll()
        repeat_fired = self.hotkeys["repeat"].poll()
        if not self.context_valid:
            # A menu or dialogue is up. Drop the stand-still tracking rather
            # than let it accumulate: the player is not "standing still" in
            # any sense worth announcing, and closing the menu should not be
            # met with an immediate repeat.
            self._reset_auto_repeat()
            return
        if next_category_fired:
            self._switch_category(1)
        elif prev_category_fired:
            self._switch_category(-1)
        elif next_fired:
            self._cycle(1)
        elif prev_fired:
            self._cycle(-1)
        elif repeat_fired:
            self._repeat()
        # After the hotkey actions, so a press this tick has already marked
        # the stop as announced and cannot be echoed a moment later.
        self._poll_auto_repeat()
