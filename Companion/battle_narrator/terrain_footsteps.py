"""Accessibility-only footstep and terrain feedback, independent of the
game's own native footstep sound (which live investigation this session
found is not exposed through any discoverable memory field or symbol-named
function -- see Documentation/ACCESSIBILITY_COVERAGE_MATRIX.md's "Footstep
sound / terrain feedback" entry).

Answers "am I moving, and what am I walking on?" using only data already
available to the companion: live player position (already read for entity
navigation and beacons) and locally-parsed room `.ccd` collision geometry
(already used for warps/doors/elevators and `collision_probe.py`'s forward
collision prediction). No native footstep-SFX trigger, animation-state
field, or velocity field is required or assumed.

Movement is derived purely from position deltas between polls -- distance
travelled paces synthetic steps, not the game's own animation timing.
Terrain is identified by the `collision_type` field of whichever
environment triangle the player is standing on/over -- the same raw field
`COLLISION_DETECTION_INVESTIGATION.md` already flagged as present but
unclassified. No semantic meaning (e.g. "type 3 = grass") is assumed or
hardcoded for any value; a distinguishable tone is guaranteed per distinct
raw value instead, so the player can tell terrain changed even before any
value is independently confirmed to mean anything specific.

Collision-blocked feedback (`BlockedMovementReader`, kept in a fully
separate class with its own opt-in flag) reuses
`collision_probe.predict_forward_collision` (a geometric forward-ray
prediction against the same local `.ccd` data) rather than the game's own
ephemeral, unreadable collision result. It is gated on a `MovementInputSource`
verifying a movement direction is actively held, not on stillness alone --
stillness alone cannot distinguish "the player is pushing into a wall" from
"the player let go of the stick near a wall," which was flagged as an
unacceptable false positive for anything framed as collision feedback. See
`movement_input.py` for the input source and its current (unverified)
status.
"""
import math
import random
import struct
import wave
from pathlib import Path

from .collision_probe import (
    parse_environment_triangles,
    parse_walk_model_triangles,
    predict_forward_collision,
)


def load_room_triangles(collision_dir, room_codes, cache, room_id, logger):
    """Public (not module-private) because `navigation_service.py` reuses
    this exact room-code-to-`.ccd` loading logic rather than a second
    definition of how to find/parse a room's collision file. Parses CCD
    slot +0x28 (`CCD_HITMDL_HEAD`, obstacles/walls) -- see
    `load_walk_model_triangles` for the separate slot +0x24 walkable-ground
    model."""
    if room_id in cache:
        return cache[room_id]
    code = room_codes.get(room_id)
    path = Path(collision_dir) / f"{code}.ccd" if code else None
    if path is None or not path.is_file():
        triangles = ()
    else:
        try:
            triangles = parse_environment_triangles(path.read_bytes())
        except (OSError, ValueError) as exc:
            if logger:
                logger.debug(
                    "TERRAIN collision load failed room=0x%X: %s", room_id, exc)
            triangles = ()
    cache[room_id] = triangles
    return triangles


def load_walk_model_triangles(collision_dir, room_codes, cache, room_id, logger):
    """Same room-code-to-`.ccd` resolution as `load_room_triangles`, but
    for CCD slot +0x24 (`CCD_WALKMDL_HEAD`) -- the engine's own walkable-
    ground model (see `collision_probe.parse_walk_model_triangles` and
    `WORLD_NAVIGATION_ARCHITECTURE.md`). Kept as a distinct cache/function
    rather than reusing `load_room_triangles`'s cache, since a room's wall
    and walk triangles are different objects read from the same file --
    conflating the two caches would require re-parsing one every time the
    other's cache is queried first."""
    if room_id in cache:
        return cache[room_id]
    code = room_codes.get(room_id)
    path = Path(collision_dir) / f"{code}.ccd" if code else None
    if path is None or not path.is_file():
        triangles = ()
    else:
        try:
            triangles = parse_walk_model_triangles(path.read_bytes())
        except (OSError, ValueError) as exc:
            if logger:
                logger.debug(
                    "TERRAIN walk-model load failed room=0x%X: %s", room_id, exc)
            triangles = ()
    cache[room_id] = triangles
    return triangles


def _angle_delta(a, b):
    """Smallest absolute difference between two angles in radians,
    wrap-around-safe."""
    return abs(math.atan2(math.sin(a - b), math.cos(a - b)))


def _point_in_triangle_xz(x, z, triangle):
    (ax, _, az), (bx, _, bz), (cx, _, cz) = triangle.vertices
    d1 = (x - bx) * (az - bz) - (ax - bx) * (z - bz)
    d2 = (x - cx) * (bz - cz) - (bx - cx) * (z - cz)
    d3 = (x - ax) * (cz - az) - (cx - ax) * (z - az)
    has_negative = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_positive = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_negative and has_positive)


def find_ground_triangle(triangles, position, height_tolerance=1.5):
    """Return the environment triangle the player is standing on/over, or
    None. Only considers roughly-horizontal (walkable) triangles whose XZ
    footprint contains the player and whose average height is within
    `height_tolerance` of the player's own Y -- the closest such triangle
    wins when floors overlap (e.g. a room above another)."""
    best, best_gap = None, None
    for triangle in triangles:
        if abs(triangle.normal[1]) < 0.5:
            continue
        if not _point_in_triangle_xz(position.x, position.z, triangle):
            continue
        average_y = sum(vertex[1] for vertex in triangle.vertices) / 3
        gap = abs(position.y - average_y)
        if gap > height_tolerance:
            continue
        if best is None or gap < best_gap:
            best, best_gap = triangle, gap
    return best


def _write_click_wav(path, duration, frequency, sample_rate=22050, harsh=False):
    """Synthesize a short percussive click as a 16-bit mono WAV, entirely
    independent of any game asset. `harsh` uses a square-ish waveform for a
    buzzier, more attention-grabbing cue (used for the blocked warning)."""
    frame_count = int(sample_rate * duration)
    frames = bytearray()
    for index in range(frame_count):
        t = index / sample_rate
        envelope = math.exp(-t / (duration / 4))
        raw = math.sin(2 * math.pi * frequency * t)
        if harsh:
            raw = math.copysign(1.0, raw)
        sample = int(max(-1.0, min(1.0, raw * envelope)) * 32767)
        frames += struct.pack("<h", sample)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))


def _convert_frames_to_16bit(frames, width):
    """Downconvert 24-bit (or 32-bit) little-endian signed PCM frames to
    16-bit by keeping the most-significant 2 bytes of each sample --
    `SpatialWavePlayer.play()` (npc_beacons.py) only accepts 16-bit WAV,
    but real recorded footstep sounds are commonly 24-bit."""
    if width == 2:
        return frames
    if width not in (3, 4):
        raise ValueError(f"unsupported WAV sample width {width} bytes")
    out = bytearray()
    span = 1 << (width * 8)
    half = span // 2
    for offset in range(0, len(frames) - width + 1, width):
        value = int.from_bytes(frames[offset:offset + width], "little")
        if value >= half:
            value -= span
        sample16 = max(-32768, min(32767, value >> ((width - 2) * 8)))
        out += struct.pack("<h", sample16)
    return bytes(out)


def _ensure_16bit_wav(source_path, cache_path):
    """Write a 16-bit copy of `source_path` to `cache_path`, once, if not
    already cached (mirrors `_write_click_wav`'s own lazy-generation
    pattern) -- or return `source_path` unchanged if it's already 16-bit,
    no copy needed."""
    with wave.open(str(source_path), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    if width == 2:
        return source_path
    if not cache_path.exists():
        converted = _convert_frames_to_16bit(frames, width)
        with wave.open(str(cache_path), "wb") as handle:
            handle.setnchannels(channels)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(converted)
    return cache_path


BLOCKED_CUE_FREQUENCY = 200.0
"""Fundamental of the blocked-movement cue, in Hz.

**Raised from 90.0 on 2026-08-18**, after the project owner reported the
cue as inaudible from the Sound library. The file was never silent -- it
peaks at full scale and measures -9 dBFS RMS -- but it is a square wave,
and a square's energy is concentrated in its fundamental: at 90 Hz, 84% of
it sat below 150 Hz, which laptop speakers and most earbuds simply do not
reproduce. What reached the ear was the 270 Hz third harmonic at a third
of the amplitude, and nothing else.

200 Hz puts the fundamental itself in range on any speaker while keeping
this the lowest, dullest cue in the set -- a thud rather than a beep, so it
stays distinguishable from the beacons, which is why a low tone was chosen
in the first place."""

BLOCKED_CUE_FILENAME = "_terrain_blocked_200hz.wav"
"""Renamed alongside the frequency change, deliberately.

`resolve_blocked_path` generates the file only `if not path.exists()`, so
every existing install already has the old 90 Hz one cached and would have
kept it forever under the old name. A new name is the cache key: the
retuned cue is generated on next launch, and the stale file is simply
ignored."""


def resolve_blocked_path(asset_dir):
    """The blocked-movement cue's file, generating it if it is not cached.

    A module function rather than a private step inside `TerrainTonePlayer.
    __init__` because the sound library needs the same file to offer as a
    listenable example, and it is built before any tone player exists.
    Re-deriving the filename there would be a second place for it to be
    written down, and the two would eventually disagree."""
    asset_dir = Path(asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)
    path = asset_dir / BLOCKED_CUE_FILENAME
    if not path.exists():
        _write_click_wav(path, duration=0.16,
                         frequency=BLOCKED_CUE_FREQUENCY, harsh=True)
    return path


def resolve_step_paths(asset_dir, footstep_sounds_dir=None, logger=None):
    """Every footstep clip, 16-bit and cached, or the synthesized fallback.

    Same reasoning as `resolve_blocked_path`, and idempotent for the same
    reason: `_ensure_16bit_wav` and `_write_click_wav` both skip work that
    is already done, so calling this from two places costs one conversion
    in total, not two.

    **The fallback is reported.** It used to be taken in silence, and that
    silence is the whole reason "the beacons activate but not the
    footsteps" was a mystery rather than a log line. The asymmetry is
    real and deliberate -- a missing beacon raises `LocalDataError` and
    stops the narrator, while a missing footstep recording degrades to a
    synthesized click so the player keeps SOMETHING underfoot -- but
    degrading quietly is not the same as degrading invisibly. Every route
    to the fallback now says which one it took, at warning level."""
    asset_dir = Path(asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)
    paths = ()
    reason = "no footstep directory was configured"
    if footstep_sounds_dir is not None:
        sounds_dir = Path(footstep_sounds_dir)
        if not sounds_dir.is_dir():
            reason = f"{sounds_dir} does not exist"
        else:
            sources = sorted(sounds_dir.glob("*.wav"))
            if not sources:
                reason = f"{sounds_dir} contains no .wav files"
            else:
                # `SpatialWavePlayer.play()` (npc_beacons.py) only accepts
                # 16-bit WAV; the project owner's real footstep recordings
                # are 24-bit, so each gets a cached 16-bit copy written
                # once, not converted on every step.
                try:
                    paths = tuple(
                        _ensure_16bit_wav(
                            source,
                            asset_dir / f"_footstep_16bit_{source.stem}.wav",
                        )
                        for source in sources
                    )
                except (OSError, wave.Error, ValueError) as problem:
                    # Caught rather than raised: this runs from the
                    # narrator's constructor, and a footstep cache that
                    # cannot be written -- a read-only folder, a full disk,
                    # security software refusing the write -- must not take
                    # the whole companion down with it.
                    paths = ()
                    reason = (f"converting the recordings in {sounds_dir} "
                              f"failed: {problem}")
    if paths:
        return paths
    if logger is not None:
        logger.warning(
            "TERRAIN FOOTSTEPS falling back to the synthesized click: %s. "
            "Beacons are unaffected, which is why this is easy to miss.",
            reason)
    fallback_path = asset_dir / "_terrain_step_base.wav"
    if not fallback_path.exists():
        _write_click_wav(fallback_path, duration=0.09, frequency=260.0)
    return (fallback_path,)


class TerrainTonePlayer:
    """Plays accessibility-only footstep and blocked-movement tones.
    Reuses the existing `SpatialWavePlayer` pan/pitch/gain rendering
    rather than a separate playback path -- pan is always centered
    (footsteps are the player's own feet, not a directional beacon), and
    pitch varies deterministically by the raw `collision_type` value so
    distinct terrain reads as distinct sound without asserting what any
    specific value means.

    Footstep sounds are real recordings (project owner's own `.wav`
    files, `sounds/footsteps/`), one picked at random per step via
    `random.choice` -- not the same clip every time -- rather than the
    single synthesized click this used before. Falls back to a
    synthesized click only if no real footstep sounds are found (that
    directory missing/empty), so the reader never goes silent. The
    blocked-movement tone is unaffected -- still the original synthesized
    harsh click, since the project owner asked specifically about
    footsteps."""

    def __init__(self, wave_player, asset_dir, footstep_sounds_dir=None,
                 logger=None):
        self.wave_player = wave_player
        self.asset_dir = Path(asset_dir)
        self._blocked_path = resolve_blocked_path(self.asset_dir)
        self._step_paths = resolve_step_paths(
            self.asset_dir, footstep_sounds_dir, logger)

    @property
    def using_real_footsteps(self):
        """False when play_step is firing the synthesized click.

        Exposed so the state is inspectable rather than only audible --
        `phase1b_app` reports it once at startup, and a test can assert on
        it without listening to anything."""
        return not any(path.name == "_terrain_step_base.wav"
                       for path in self._step_paths)

    STEP_GAIN = 0.9
    """Raised 50% from 0.6 at the project owner's request (2026-08-10)
    after live listening: the footsteps sat under the beacons rather than
    alongside them. Named rather than inlined because it is the knob the
    planned user-settings UI needs, and because the blocked-movement cue
    below has its own separate level that this must not silently move."""

    @staticmethod
    def _pitch_for_type(collision_type):
        if collision_type is None:
            return 1.0
        return 1.0 + 0.12 * (collision_type % 6)

    def play_step(self, collision_type):
        self.wave_player.play(
            random.choice(self._step_paths), pan=0.0,
            pitch=self._pitch_for_type(collision_type), gain=self.STEP_GAIN,
        )

    def play_blocked(self):
        self.wave_player.play(self._blocked_path, pan=0.0, pitch=1.0, gain=0.8)


class TerrainFootstepReader:
    """Continuous, room-agnostic synthetic footstep and terrain reader.

    Paces synthetic step cues by real distance travelled -- entirely
    independent of the game's own footstep internals. Does NOT include any
    collision/blocked-movement logic; see `BlockedMovementReader` for that,
    kept deliberately separate so each can be enabled and live-tested
    independently.
    """

    STEP_DISTANCE = 12.0
    """Live-tuned 2026-07-29 (was 1.6, a first-guess that turned out far too
    small): real per-poll walking deltas observed in the field log clustered
    around 16-23 units, meaning the original value would fire many steps per
    single poll tick -- a rapid buzz, not discrete footsteps. Still a rough
    calibration (world-units-per-visual-footstep isn't independently known),
    pending further live listening."""
    STILLNESS_EPSILON = 0.02
    MAX_PLAUSIBLE_DELTA = 60.0
    """A single poll-to-poll displacement above this is treated as a
    teleport, warp, room transition, or other non-walking jump rather than
    real movement -- resets cadence instead of producing a burst of steps.
    Live-tuned 2026-07-29 (was 8.0, which turned out to reject essentially
    ALL real walking -- the narrator's own log showed genuine walking
    deltas of 16-23 units being discarded as "large jumps" every poll,
    producing zero footsteps across 200+ units of real movement). Set from
    real observed data: walking-scale deltas topped out around 23, while
    genuine room-transition/teleport-scale deltas started at 143 and up --
    60.0 sits with a comfortable margin in the gap between the two."""

    def __init__(self, memory, profile, pose_source, collision_dir,
                 room_codes, tone_player, logger):
        self.memory, self.profile, self.pose_source = memory, profile, pose_source
        self.collision_dir = Path(collision_dir)
        self.room_codes = dict(room_codes)
        self.tone_player = tone_player
        self.logger = logger
        self._triangles_by_room = {}
        self._last_position = None
        self._accumulated_distance = 0.0
        self._known_types = set()

    def _triangles_for_room(self, room_id):
        return load_room_triangles(
            self.collision_dir, self.room_codes, self._triangles_by_room,
            room_id, self.logger)

    def clear(self, reason):
        if self._last_position is not None and self.logger:
            self.logger.debug("TERRAIN FOOTSTEPS CLEAR reason=%s", reason)
        self._last_position = None
        self._accumulated_distance = 0.0

    def poll_once(self):
        room_id = self.memory.u16(
            self.profile.current_floor_id, "terrain footsteps floor id")
        pose = self.pose_source.player_pose()
        position = pose.position
        if self._last_position is None:
            self._last_position = position
            return
        delta = math.dist(
            (position.x, position.z),
            (self._last_position.x, self._last_position.z),
        )
        self._last_position = position
        if delta >= self.MAX_PLAUSIBLE_DELTA:
            if self.logger:
                self.logger.debug(
                    "TERRAIN FOOTSTEPS large jump ignored delta=%.2f", delta)
            self._accumulated_distance = 0.0
            return
        if delta < self.STILLNESS_EPSILON:
            return
        self._accumulated_distance += delta
        if self._accumulated_distance < self.STEP_DISTANCE:
            return
        self._accumulated_distance -= self.STEP_DISTANCE
        triangle = find_ground_triangle(self._triangles_for_room(room_id), position)
        collision_type = triangle.collision_type if triangle is not None else None
        self._play_step(collision_type)

    def _play_step(self, collision_type):
        if collision_type is not None and collision_type not in self._known_types:
            self._known_types.add(collision_type)
            if self.logger:
                self.logger.info(
                    "TERRAIN FOOTSTEPS new terrain type observed: %s",
                    collision_type)
        self.tone_player.play_step(collision_type)


class BlockedMovementReader:
    """Blocked-forward-movement cue, kept fully separate from
    TerrainFootstepReader with its own opt-in flag.

    Requires ALL of: a movement direction actively held (per
    `movement_input_source`), displacement below the stillness threshold,
    forward collision geometry in the player's current facing direction
    (used as a proxy for "intended movement direction" -- the game already
    turns the character to face the held stick direction, and no verified
    stick-to-world transform exists yet to do better), sustained for a
    short debounce window, and not already fired during the same
    continuous blocked-input episode. The episode resets on movement,
    input release, a material facing change, or the obstacle clearing --
    never on stillness alone, which cannot distinguish a genuine blocked
    push from simply standing still near a wall.
    """

    STILLNESS_EPSILON = 0.02
    DEBOUNCE_TICKS = 4
    PROBE_DISTANCE = 2.2
    YAW_CHANGE_RESET = 0.35  # radians; a deliberate turn resets the episode

    def __init__(self, memory, profile, pose_source, movement_input_source,
                 collision_dir, room_codes, tone_player, logger):
        self.memory, self.profile, self.pose_source = memory, profile, pose_source
        self.movement_input_source = movement_input_source
        self.collision_dir = Path(collision_dir)
        self.room_codes = dict(room_codes)
        self.tone_player = tone_player
        self.logger = logger
        self._triangles_by_room = {}
        self._last_position = None
        self._last_yaw = None
        self._qualifying_ticks = 0
        self._episode_fired = False

    def _triangles_for_room(self, room_id):
        return load_room_triangles(
            self.collision_dir, self.room_codes, self._triangles_by_room,
            room_id, self.logger)

    def clear(self, reason):
        if self._last_position is not None and self.logger:
            self.logger.debug("BLOCKED MOVEMENT CLEAR reason=%s", reason)
        self._last_position = None
        self._last_yaw = None
        self._qualifying_ticks = 0
        self._episode_fired = False

    def _reset_episode(self):
        self._qualifying_ticks = 0
        self._episode_fired = False

    def poll_once(self):
        room_id = self.memory.u16(
            self.profile.current_floor_id, "blocked movement floor id")
        pose = self.pose_source.player_pose()
        position = pose.position
        input_held = self.movement_input_source.is_direction_held()

        if self._last_position is None:
            self._last_position, self._last_yaw = position, pose.yaw
            return

        displacement = math.dist(
            (position.x, position.z),
            (self._last_position.x, self._last_position.z),
        )
        yaw_changed = (
            self._last_yaw is not None
            and _angle_delta(pose.yaw, self._last_yaw) > self.YAW_CHANGE_RESET
        )
        self._last_position, self._last_yaw = position, pose.yaw

        if not input_held or displacement >= self.STILLNESS_EPSILON or yaw_changed:
            self._reset_episode()
            return

        hit = predict_forward_collision(
            self._triangles_for_room(room_id), pose, self.PROBE_DISTANCE)
        if hit is None:
            self._reset_episode()
            return

        self._qualifying_ticks += 1
        if self._qualifying_ticks < self.DEBOUNCE_TICKS or self._episode_fired:
            return
        self._episode_fired = True
        self.tone_player.play_blocked()
        if self.logger:
            self.logger.info(
                "BLOCKED MOVEMENT room=0x%X distance=%.2f", room_id, hit.distance)
