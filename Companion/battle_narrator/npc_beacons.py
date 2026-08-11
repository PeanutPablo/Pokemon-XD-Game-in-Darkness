"""Repeating stereo, distance, and height-aware overworld NPC beacons."""
from dataclasses import dataclass
import math
from pathlib import Path
import struct
import time
import wave

from .memory import MemoryError, require_range
from .player_facing_names import LOCATION_NAMES


NAVIGATION_GAIN_FLOOR = 0.25
NAVIGATION_GAIN_RANGE = 0.55
"""The navigation beacon's own gain curve (`audio_guide.guide_values`):
0.25 when a target is at maximum range, 0.80 when standing on it. Defined
here rather than in audio_guide.py because that module already depends on
this one, and both the guide and the passive beacons need it."""


def navigation_gain(proximity):
    """Gain the NAVIGATION beacon would use at this proximity (0.0 far,
    1.0 arrived)."""
    return NAVIGATION_GAIN_FLOOR + NAVIGATION_GAIN_RANGE * proximity


PASSIVE_BEACON_GAIN_SCALE = 1.0
"""Global volume for passive beacons, as a scale of `navigation_gain`.

1.0 means they play at the same volume as the navigation beacon. Set to a
quarter when the beacons were first wired up, then raised to full at the
project owner's request after hearing them in game (2026-08-05).

Kept as a SCALE rather than folded into the curve on purpose: it is one of
the two knobs the planned user-settings UI needs (this and
`PASSIVE_BEACON_CATEGORY_GAIN` below), and expressing it as a relationship
means retuning the navigation curve moves both together instead of silently
changing the ratio between them."""

PASSIVE_BEACON_CATEGORY_GAIN = {
    "warp": 0.20,
}
"""Per-category volume trims, multiplied on top of the global scale.
Anything absent plays at 1.0.

Warps sit at a fifth, set by ear by the project owner (first 0.5, still too
loud, then 0.20). They are by far the densest category -- a room can hold a
great many, and unlike an NPC or an item they are rarely the thing being
looked for -- so at parity they crowd out the categories that matter. This
is a per-sound mix trim, not a statement about importance."""

PASSIVE_BEACON_SOUND_FILES = {
    "npc": "npcs.wav",
    "pokemart": "pokemarts.wav",
    "item": "items.wav",
    "door": "doors.wav",
    "warp": "warps.wav",
    "elevator": "elevators.wav",
}
"""Passive ambient beacons, one distinct sound per category, from the
project's own `sounds/` directory. Any category reaching the reader
without an entry here (e.g. "healing") has no sound of its own and is
deliberately NOT beaconed rather than being given a borrowed one -- a
wrong cue is worse than no cue, because the player would act on it.

Elevators joined the original five at the project owner's request
(2026-08-10), now that `sounds/elevators.wav` exists. They were the
worked example in the paragraph above for as long as they had no file:
the source has always published them (AuthoritativeElevatorEntitySource),
and they were held silent rather than borrowed the warp or NPC tone."""

ENTITY_SOUND_FILES = {
    "npc": "npc_sound.wav",
    "item": "263129__mossy4__sine-up-flutter-beep.wav",
    "door": "263123__mossy4__sine-tri-tone-down-negative-beep-amb-verb.wav",
    "warp": "263655__mossy4__upward-beep-chromatic-fifths.wav",
    "healing": "263132__mossy4__tri-tone-up-beep.wav",
    "store_clerk": "263125__mossy4__sine-fifths-up-beep.wav",
    "pokebox": "263128__mossy4__tone-beep-amb-verb.wav",
    "elevator": "263131__mossy4__tone-beep-slower-lower-amb-verb.wav",
}


def resolve_sound_dir(companion_dir):
    """Locate the project's own `sounds/` directory from `Companion/`.

    Two layouts have to work and they nest differently. A built release
    is self-contained, so `sounds/` sits beside `Companion/` inside the
    extracted folder. The development checkout keeps it one level higher
    still, a sibling of `PokemonXGAccessibility/` -- which is outside the
    part of the tree the release builder stages, and is exactly why an
    unpacked release used to start and then die on the first beacon that
    came into range.

    The release layout is checked FIRST, deliberately: a recipient who
    extracts into a folder that already contains an unrelated `sounds/`
    must still get the packaged one, not that.

    Falls back to the release path when neither exists, so the missing
    files are reported against the location a recipient should be
    looking at rather than one two directories above their release."""
    companion_dir = Path(companion_dir)
    release_layout = companion_dir.parent / "sounds"
    checkout_layout = companion_dir.parent.parent / "sounds"
    for candidate in (release_layout, checkout_layout):
        if candidate.is_dir():
            return candidate
    return release_layout


@dataclass(frozen=True)
class Position:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class LiveActor:
    """A currently-spawned NPC actor: whether it is displayed, and where it
    actually is. `position` is None when the actor has no usable model, in
    which case callers fall back to floor_character's scripted position."""
    visible: bool
    position: object = None


@dataclass(frozen=True)
class PlayerPose:
    position: Position
    yaw: float
    """The active CAMERA's world yaw -- the frame every spoken direction is
    expressed in (pan, pitch, o'clock bearings). Not the player's own
    orientation."""
    facing: float = None
    """The HERO MODEL's own rotation about Y -- which way the character is
    physically turned, which is simply whichever way they last walked (this
    game has no turn-in-place). Distinct from `yaw`, and needed because the
    game gates talking on it; see entity_nav.facing_error. None when the
    read was unavailable, in which case facing-dependent reporting is
    suppressed rather than guessed."""


MAP_NAMES = dict(LOCATION_NAMES, T1="Title Screen")
"""Was a SECOND, hand-maintained copy of the location table -- and the two
disagreed on S2, S3, D5 and D7, with the labels the player actually heard
coming from the wrong one. Derived from the single table now, so a
correction to one is a correction to both. `T1` is a title-screen pseudo
location that has no player-facing room of its own."""

ITEMS = {
}

HEALING = {
    0x8A: Position(-89.0, 0.0, -42.9),
}


@dataclass
class NPCInteractionContext:
    name: str | None = None
    # Set by NPCSoundReader alongside `name` (see the two assignments below).
    # Declared here so it exists before that reader has ever resolved an NPC --
    # dialogue from a non-NPC source (a sign, a scripted event) reaches
    # dialogue_speaker_name() without either writer having run.
    identity: tuple | None = None


@dataclass(frozen=True)
class NPC:
    floor_id: int
    index: int
    visible: bool
    talk_id: int
    position: Position
    name_id: int = 0
    interaction_radius: float = 10.0
    category: str = "npc"
    label: str | None = None
    people_info_id: int = 0
    """The NPC's TYPE id (floor_character + 0x06), the index into the
    people-info table that supplies its model and talk distance.

    Read but discarded until now. Exposed because role NPCs -- Pokemon
    Center nurses, Mart clerks, Mt. Battle receptionists -- are ordinary
    NPCs with no distinguishing interaction record: a full enumeration of
    common.rel's 832 interaction records found no "healing machine" or
    "reception desk" type, and the 241 non-common records are per-room
    script indices with no global meaning. A shared type id is the only
    authoritative signal that could identify such roles across every room,
    replacing phase1b_app's current room-id guess (0x85/0x86), which both
    mislabels every other NPC in those two rooms and misses every other
    Pokemon Center. Whether it actually clusters that way is UNCONFIRMED --
    that is what this field exists to measure.

    Appended last so existing positional NPC(...) construction is
    unaffected."""

    @property
    def identity(self):
        return self.floor_id, self.index


class NPCMemorySource:
    def __init__(self, memory, profile):
        self.memory, self.profile = memory, profile

    def _position(self, address, label):
        values = Position(*struct.unpack(
            ">fff", self.memory.bytes(address, 12, label, 4)))
        if not all(math.isfinite(value) for value in vars(values).values()):
            raise MemoryError(f"{label} contains a non-finite coordinate")
        return values

    def hero_model_address(self):
        """Resolve the live hero model's node address. Shared by
        player_pose() (read) and teleport.py's writer (write) so both use
        the identical resolution chain -- extracted here rather than
        duplicated, since this walk is delicate (linked-list search keyed
        on hero_leader/hero_model_resource_ids)."""
        p = self.profile
        leader = self.memory.u32(p.hero_leader, "hero leader")
        if leader >= len(p.hero_model_resource_ids):
            raise MemoryError(f"invalid hero leader {leader}")
        resource_id = p.hero_model_resource_ids[leader]
        node = self.memory.pointer(
            p.resource_list_head, p.resource_node_size,
            "resource-list head", 4)
        seen = set()
        for _ in range(p.resource_max_nodes):
            if node in seen:
                raise MemoryError("resource-list cycle")
            seen.add(node)
            group_id = self.memory.u32(
                node + p.resource_group_offset, "resource group")
            candidate_id = self.memory.u32(
                node + p.resource_id_offset, "resource ID")
            state = self.memory.u8(
                node + p.resource_state_offset, "resource state")
            if group_id == 0 and candidate_id == resource_id and state == 0:
                return self.memory.pointer(
                    node + p.resource_data_offset,
                    p.model_rotation_offset + 12,
                    "hero model",
                    4,
                )
            next_node = self.memory.u32(
                node + p.resource_next_offset, "next resource")
            if not next_node:
                break
            require_range(
                next_node, p.resource_node_size, "next resource",
                self.memory.profile, 4)
            node = next_node
        raise MemoryError(f"hero model resource {resource_id} not found")

    def player_pose(self):
        p = self.profile
        model = self.hero_model_address()
        position = self._position(
            model + p.model_position_offset, "hero position")
        # Camera yaw, read the way cameraGetRotY() does. This is not a
        # constant per room: every floor loads a field-camera list, and when
        # it holds more than one entry the engine blends their yaws by
        # inverse square distance to the player every frame, so the value
        # changes continuously as the player walks. Gateon Port has eight,
        # spanning 67 degrees. Re-read every poll; never cached.
        work = self.memory.pointer(
            p.camera_work_pointer,
            p.camera_work_rot_y_offset + 4,
            "camera work",
            4,
        )
        yaw = struct.unpack(
            ">f",
            self.memory.bytes(
                work + p.camera_work_rot_y_offset,
                4,
                "camera yaw",
                4,
            ),
        )[0]
        if not math.isfinite(yaw):
            raise MemoryError("camera yaw is non-finite")
        # The hero model's own Y rotation -- see PlayerPose.facing. Failing
        # to read it must not break position/yaw reporting, which is what
        # every other consumer depends on, so it degrades to None.
        try:
            facing = struct.unpack(
                ">f",
                self.memory.bytes(
                    model + p.model_rotation_offset + 4,
                    4,
                    "hero facing",
                    4,
                ),
            )[0]
            if not math.isfinite(facing):
                facing = None
        except MemoryError:
            facing = None
        return PlayerPose(position, yaw, facing)

    def npcs(self):
        p = self.profile
        floor_id = self.memory.u16(p.current_floor_id, "current floor ID")
        count_root = self.memory.pointer(
            p.floor_data_count_root, 4, "floor-data count root", 4)
        count = self.memory.u32(count_root, "floor-data count")
        if count > p.floor_data_max_records:
            raise MemoryError(f"invalid floor-data count {count}")
        table = self.memory.pointer(
            p.floor_data_root,
            max(1, count) * p.floor_data_stride,
            "floor-data table",
            4,
        )
        floor = None
        for index in range(count):
            candidate = table + index * p.floor_data_stride
            if self.memory.u16(
                    candidate + p.floor_id_offset, "floor record ID") == floor_id:
                floor = candidate
                break
        if floor is None:
            raise MemoryError(f"floor record {floor_id} not found")
        slot = self.memory.pointer(
            floor + p.floor_character_slot_offset, 4,
            "floor character slot", 4)
        header = self.memory.pointer(slot, 8, "floor character header", 4)
        count_pointer = self.memory.pointer(
            header, 4, "floor character count pointer", 4)
        npc_count = self.memory.u32(count_pointer, "floor character count")
        if npc_count > p.floor_character_max_records:
            raise MemoryError(f"invalid floor character count {npc_count}")
        base = self.memory.pointer(
            header + 4,
            max(1, npc_count) * p.floor_character_stride,
            "floor character records",
            4,
        )
        live_visibility = self._live_visibility_by_index()
        result = []
        for index in range(npc_count):
            record = base + index * p.floor_character_stride
            people_info_id = self.memory.u16(
                record + p.floor_character_people_info_offset,
                "NPC people-info ID",
            )
            people_count_root = self.memory.pointer(
                p.people_info_count_root, 4, "people-info count root", 4)
            people_count = self.memory.u32(
                people_count_root, "people-info count")
            if people_info_id >= people_count:
                raise MemoryError(f"invalid people-info ID {people_info_id}")
            people_table = self.memory.pointer(
                p.people_info_root,
                max(1, people_count) * p.people_info_stride,
                "people-info table",
                4,
            )
            talk_distance = struct.unpack(
                ">f",
                self.memory.bytes(
                    people_table
                    + people_info_id * p.people_info_stride
                    + p.people_info_talk_distance_offset,
                    4,
                    "NPC talk distance",
                    4,
                ),
            )[0]
            if not math.isfinite(talk_distance) or talk_distance <= 0:
                talk_distance = p.default_interaction_radius
            static_visible = bool(
                self.memory.u8(record, "NPC flags")
                & p.floor_character_visible_mask
            )
            actor = live_visibility.get(index)
            # The live actor's own position wins whenever it exists:
            # floor_character only ever holds the SCRIPTED spawn point, so
            # anything the game has moved since (a cutscene walking a group
            # out of a building, a wandering NPC, a follower) would
            # otherwise be reported at where it started. Falls back to the
            # static position when no actor is spawned.
            static_position = self._position(
                record + p.floor_character_position_offset, "NPC position")
            result.append(NPC(
                floor_id,
                index,
                static_visible if actor is None else actor.visible,
                self.memory.u32(
                    record + p.floor_character_talk_offset, "NPC talk ID"),
                (actor.position
                 if actor is not None and actor.position is not None
                 else static_position),
                self.memory.u16(
                    record + p.floor_character_name_offset, "NPC name ID"),
                talk_distance,
                people_info_id=people_info_id,
            ))
        item = ITEMS.get(floor_id)
        if item is not None:
            position, label = item
            result.append(NPC(
                floor_id, 0x7FFE, True, 1, position,
                interaction_radius=10.0, category="item", label=label,
            ))
        healing = HEALING.get(floor_id)
        if healing is not None:
            result.append(NPC(
                floor_id, 0x7FFD, True, 1, healing,
                interaction_radius=4.0, category="healing", label="Healing",
            ))
        return result

    def _live_visibility_by_index(self):
        """Cross-reference the live 'people' runtime-actor table against
        floor_character's per-room index, since floor_character's own
        visible bit is confirmed stale for story-hidden characters (see
        profile.py's people_work_* field comments). identity_a==0 is the
        game's reserved sentinel for special/global follower slots, not a
        real room -- excluded so their identity_b values (100+) can never
        be mistaken for a real room's small per-index identity_b values."""
        p = self.profile
        count = self.memory.u32(
            p.people_work_count_address, "people-work count")
        if count > p.people_work_max_records:
            raise MemoryError(f"invalid people-work count {count}")
        if count == 0:
            return {}
        base = self.memory.pointer(
            p.people_work_root_address,
            count * p.people_work_stride,
            "people-work records",
            4,
        )
        live_visibility = {}
        for slot in range(count):
            record = base + slot * p.people_work_stride
            if not self.memory.u8(record + p.people_work_occupied_offset,
                                   "people-work occupied"):
                continue
            identity_a = self.memory.u32(
                record + p.people_work_identity_a_offset,
                "people-work identity A")
            if identity_a == 0:
                continue
            identity_b = self.memory.u32(
                record + p.people_work_identity_b_offset,
                "people-work identity B")
            disp = self.memory.u8(
                record + p.people_work_disp_offset, "people-work disp")
            live_visibility[identity_b] = LiveActor(
                bool(disp), self._live_position(record))
        return live_visibility

    def _live_position(self, record):
        """Where the actor actually IS, or None if it has no live model.

        floor_character only holds a SCRIPTED/spawn position. Any NPC the
        game has since moved -- a cutscene walking a group out of a
        building, a wandering NPC, a follower -- stays at its spawn point
        there forever, so every bearing spoken for it points at where it
        started. The project owner hit this with the Hexagon Brothers after
        a cutscene moved them.

        The chain is the engine's own, from peopleBiosGetPosPtr
        (0x80297724): `lwz r3, 0x8(r3)` takes the actor's model pointer
        from people_work + 0x08, then GSmodelGetPositionPtr (0x800F7B30) is
        just `addi r3, r3, 0x18` -- the same model_position_offset this
        file already uses for the hero model."""
        p = self.profile
        try:
            model = self.memory.u32(
                record + p.people_work_model_offset, "people-work model")
            if not (p.mem1_start <= model < p.mem1_end):
                return None
            return self._position(
                model + p.model_position_offset, "live NPC position")
        except MemoryError:
            # A missing or half-initialised model must not break the whole
            # NPC list; the static position is still a usable fallback.
            return None

    def current_floor_id(self):
        return self.memory.u16(
            self.profile.current_floor_id, "current floor ID")


def wave_duration(path):
    with wave.open(str(path), "rb") as source:
        return source.getnframes() / source.getframerate()


SUPPORTED_SAMPLE_WIDTHS = (1, 2, 3, 4)
"""Byte widths of uncompressed PCM this player can read.

Originally 16-bit only, which was a trap rather than a constraint: the
project's own `sounds/` directory is 24-bit, so wiring those files in
crashed the narrator outright the first time a beacon tried to play (live,
2026-08-05). Nothing downstream actually needs 16-bit input -- everything
after decoding works on plain integers -- so the width is now normalised on
load instead of rejected. Anyone dropping a new sound in should not have to
know the project's internal sample format."""


def _decode_pcm(frames, width):
    """Decode uncompressed PCM to signed integers on the 16-bit scale.

    Scaling to a common range rather than preserving the source depth keeps
    the pan/gain/clamp maths downstream in one fixed range, so a 24-bit clip
    and a 16-bit clip at the same requested gain come out equally loud."""
    if width == 2:
        return list(struct.unpack("<" + "h" * (len(frames) // 2), frames))
    if width == 1:
        # WAV stores 8-bit as UNSIGNED with 128 as silence, unlike every
        # wider depth, which is signed.
        return [(sample - 128) * 256 for sample in frames]
    if width == 3:
        return [
            int.from_bytes(frames[offset:offset + 3], "little", signed=True) >> 8
            for offset in range(0, len(frames) - 2, 3)
        ]
    if width == 4:
        return [
            sample >> 16
            for sample in struct.unpack("<" + "i" * (len(frames) // 4), frames)
        ]
    raise ValueError(
        f"unsupported WAV sample width {width} bytes; "
        f"supported: {SUPPORTED_SAMPLE_WIDTHS}")


def check_playable(path):
    """Raise if `path` is not a WAV this player can render.

    Used as a startup pre-flight so an unusable sound file reports itself
    clearly before the narrator runs, rather than throwing from inside the
    poll loop the first time that particular category happens to come into
    range -- which is how it actually failed: minutes into play, in a
    category-dependent and therefore hard-to-reproduce way."""
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        frames = source.getnframes()
    if channels not in (1, 2):
        raise ValueError(
            f"{Path(path).name}: {channels}-channel WAV; need mono or stereo")
    if width not in SUPPORTED_SAMPLE_WIDTHS:
        raise ValueError(
            f"{Path(path).name}: {width * 8}-bit WAV; "
            f"supported: {', '.join(str(w * 8) for w in SUPPORTED_SAMPLE_WIDTHS)}-bit")
    if not frames:
        raise ValueError(f"{Path(path).name}: contains no audio")


MIN_WSOLA_SAMPLES = 64
"""Below this many input samples, WSOLA can't even form two analysis frames
out of the pitch-resampled signal -- _pitch_shift_wsola returns None and the
caller falls back to the FFT method instead (a short synthetic click is the
main real-world case this guards)."""


def _resample_linear(values, new_length):
    """Linearly resample `values` (a 1-D numpy array) to 
ew_length`
    samples -- this alone IS the actual pitch change (playing content back
    faster/slower changes both its pitch and its duration); WSOLA time
    stretching afterward restores the original duration without touching
    the pitch this step already set."""
    import numpy as np
    old_length = values.shape[0]
    if new_length <= 0:
        return np.zeros(0, dtype=np.float64)
    if old_length == 1:
        return np.full(new_length, values[0], dtype=np.float64)
    old_x = np.linspace(0.0, 1.0, old_length)
    new_x = np.linspace(0.0, 1.0, new_length)
    return np.interp(new_x, old_x, values)


def _hann_window(n):
    import numpy as np
    if n <= 1:
        return np.ones(max(n, 0), dtype=np.float64)
    return 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / (n - 1))


def _wsola_time_stretch(source, output_length, frame_size):
    """Waveform Similarity Overlap-Add: stretches/compresses `source` to
    exactly `output_length` samples by overlap-adding windowed frames whose
    actual read position is nudged (within a small search radius around the
    ideal, unstretched position) to whichever offset best cross-correlates
    with the tail of the previously placed frame. That "waveform
    similarity" search is what makes the splice inaudible -- unlike the
    previous FFT bin-interpolation approach, nothing here touches phase
    relationships between frequency bins directly, which is what caused the
    old method's smeared/robotic artifacts."""
    import numpy as np
    m = source.shape[0]
    if output_length <= 0 or m == 0:
        return np.zeros(max(output_length, 0), dtype=np.float64)
    synthesis_hop = max(1, frame_size // 2)
    stretch_factor = output_length / m
    analysis_hop = synthesis_hop / stretch_factor
    search_radius = max(1, synthesis_hop // 4)
    window = _hann_window(frame_size)
    overlap = frame_size - synthesis_hop

    padded_length = output_length + frame_size
    output = np.zeros(padded_length, dtype=np.float64)
    weight = np.zeros(padded_length, dtype=np.float64)

    read_pos = 0.0
    write_pos = 0
    previous_frame = None
    max_start = max(0, m - frame_size)
    while write_pos < output_length:
        ideal_start = int(round(read_pos))
        if previous_frame is None or overlap <= 0:
            chosen_start = max(0, min(ideal_start, max_start))
        else:
            lo = max(0, ideal_start - search_radius)
            hi = min(max_start, ideal_start + search_radius)
            tail = previous_frame[-overlap:]
            if hi < lo:
                chosen_start = max(0, min(ideal_start, max_start))
            else:
                candidates = np.arange(lo, hi + 1)
                # Vectorized cross-correlation of `tail` against every
                # candidate overlap window at once, rather than a per-
                # candidate Python loop.
                windows = np.stack([
                    source[start:start + overlap] for start in candidates
                ])
                scores = windows @ tail
                chosen_start = int(candidates[np.argmax(scores)])
        frame = source[chosen_start:chosen_start + frame_size]
        if frame.shape[0] < frame_size:
            frame = np.pad(frame, (0, frame_size - frame.shape[0]))
        windowed = frame * window
        output[write_pos:write_pos + frame_size] += windowed
        weight[write_pos:write_pos + frame_size] += window
        previous_frame = frame
        read_pos += analysis_hop
        write_pos += synthesis_hop

    nonzero = weight > 1e-9
    output[nonzero] /= weight[nonzero]
    return output[:output_length]


def _pitch_shift_wsola(samples, pitch):
    """Real pitch change (linear resample) + WSOLA time-stretch back to the
    original sample count. Returns None (signaling "unsupported, use the
    fallback") when the input is too short to form even a couple of
    analysis frames after resampling -- never raises for that case."""
    import numpy as np
    values = np.asarray(samples, dtype=np.float64)
    original_length = values.shape[0]
    if original_length < MIN_WSOLA_SAMPLES:
        return None
    resampled_length = max(1, round(original_length / pitch))
    frame_size = max(16, min(256, resampled_length // 4))
    if resampled_length < frame_size * 2:
        return None
    resampled = _resample_linear(values, resampled_length)
    stretched = _wsola_time_stretch(resampled, original_length, frame_size)
    if stretched.shape[0] != original_length:
        if stretched.shape[0] < original_length:
            stretched = np.pad(
                stretched, (0, original_length - stretched.shape[0]))
        else:
            stretched = stretched[:original_length]
    if not np.all(np.isfinite(stretched)):
        return None
    original_peak = float(np.max(np.abs(values))) if values.size else 0.0
    stretched_peak = float(np.max(np.abs(stretched))) if stretched.size else 0.0
    if original_peak and stretched_peak:
        stretched *= original_peak / stretched_peak
    return stretched.tolist()


def _pitch_shift_fft_fallback(samples, pitch):
    """The original FFT bin-interpolation pitch shift -- kept only as a
    guarded fallback for inputs `_pitch_shift_wsola` can't handle (too
    short for even one analysis frame after resampling). Known to sound
    smeared/"phasey" at anything but a very short, simple clip, which is
    exactly the case this is still used for: interpolating the real and
    imaginary parts of the spectrum independently does not preserve phase
    relationships between frequency bins."""
    import numpy as np
    values = np.asarray(samples, dtype=np.float64)
    spectrum = np.fft.rfft(values)
    bins = np.arange(spectrum.size, dtype=np.float64)
    source_bins = bins / pitch
    real = np.interp(source_bins, bins, spectrum.real, left=0.0, right=0.0)
    imaginary = np.interp(
        source_bins, bins, spectrum.imag, left=0.0, right=0.0
    )
    shifted = np.fft.irfft(real + 1j * imaginary, n=values.size)
    if not np.all(np.isfinite(shifted)):
        # Never hand back corrupted audio -- the untouched input is a safe,
        # audible-if-unshifted last resort.
        return samples
    original_peak = float(np.max(np.abs(values))) if values.size else 0.0
    shifted_peak = float(np.max(np.abs(shifted))) if shifted.size else 0.0
    if original_peak and shifted_peak:
        shifted *= original_peak / shifted_peak
    return shifted.tolist()


def _resample_to_rate(samples, source_rate, target_rate):
    """Resample a plain list of samples from `source_rate` to `target_rate`,
    reusing `_resample_linear`'s numpy interpolation (by sample COUNT, not
    rate directly) rather than a second resampling implementation."""
    if source_rate == target_rate or not samples:
        return samples
    import numpy as np
    values = np.asarray(samples, dtype=np.float64)
    new_length = max(1, round(len(samples) * target_rate / source_rate))
    return _resample_linear(values, new_length).tolist()


MIXER_FREQUENCY = 44100
"""Fixed output rate for every SpatialWavePlayer instance's shared
pygame.mixer channel pool. Source WAV assets in this project are NOT all
the same rate (e.g. terrain_footsteps.py's synthesized clicks are 22050 Hz;
other assets differ) -- pygame.mixer.Sound built from a raw buffer does NOT
resample it to the mixer's configured rate, it just plays the buffer's
samples at that rate, so every rendered buffer is resampled to this one
fixed rate in `play()` before handing it to pygame (a cheap linear
resample, reusing the same `_resample_linear` used by the WSOLA pitch
shift above -- no second resampling implementation)."""

MIXER_CHANNEL_COUNT = 16
"""However many of this project's simultaneous cues (footsteps, blocked-
movement, NPC beacons, the audio guide tone) might genuinely overlap --
comfortably more than the actual handful of concurrent sources that exist
today, so channel exhaustion should never be the reason two sounds cut
each other off."""


class SpatialWavePlayer:
    """Render a short 16-bit stereo buffer and play it via pygame.mixer.

    Switched from `winsound.PlaySound` (2026-07-30): PlaySound is a single
    GLOBAL Windows audio channel -- every SpatialWavePlayer instance in this
    project (terrain footsteps, NPC beacons, the audio guide) ultimately
    called the same one-sound-at-a-time OS API, so whichever fired second
    silently cut off whatever was already playing, project-wide, regardless
    of which reader owned which sound. The project owner caught this live
    ("footsteps trying to silence the beacon and vice versa"). pygame.mixer
    gives genuine concurrent channels; each SpatialWavePlayer instance
    tracks only the channels IT started, so its own `stop()` never affects
    a different instance's currently-playing sound.

    Plays directly from the in-memory rendered buffer rather than writing a
    temp WAV file first and shelling out to play it by path -- the old
    cache-directory/slot-alternation dance existed only to work around
    `PlaySound`'s file-based API and is no longer needed."""

    def __init__(self, mixer_module=None):
        if mixer_module is None:
            import pygame.mixer as mixer_module
        self.mixer = mixer_module
        if not self.mixer.get_init():
            self.mixer.init(frequency=MIXER_FREQUENCY, size=-16, channels=2)
            self.mixer.set_num_channels(MIXER_CHANNEL_COUNT)
        self._channels = []

    @staticmethod
    def _pitch_shift_constant_duration(samples, pitch):
        """Shift pitch while preserving sample count and duration. Tries
        WSOLA first (see _pitch_shift_wsola) -- real, time-domain pitch
        shifting well suited to this project's short tonal/percussive
        clips -- and falls back to the older FFT method only when WSOLA
        can't run at all (a clip too short for even one analysis frame) or
        produces a non-finite result. Never returns empty or corrupted
        audio: the absolute last resort is the untouched input."""
        if abs(pitch - 1.0) < 1e-6 or not samples:
            return samples
        result = None
        try:
            result = _pitch_shift_wsola(samples, pitch)
        except Exception:
            result = None
        if result is None:
            try:
                result = _pitch_shift_fft_fallback(samples, pitch)
            except Exception:
                result = None
        if not result:
            return samples
        return result

    def play(self, path, pan, pitch, gain):
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames = source.readframes(source.getnframes())
        if channels not in (1, 2):
            raise ValueError(
                f"NPC beacon sources must be mono or stereo WAV; "
                f"{Path(path).name} has {channels} channels")
        left_gain = gain * math.cos((pan + 1) * math.pi / 4)
        right_gain = gain * math.sin((pan + 1) * math.pi / 4)
        samples = _decode_pcm(frames, width)
        step = channels
        mono_samples = [
            samples[offset] if channels == 1 else (
                samples[offset] + samples[offset + 1]
            ) / 2
            for offset in range(0, len(samples), step)
        ]
        mono_samples = self._pitch_shift_constant_duration(
            mono_samples, pitch
        )
        mono_samples = _resample_to_rate(mono_samples, rate, MIXER_FREQUENCY)
        rendered = bytearray()
        for mono in mono_samples:
            left = max(-32768, min(32767, round(mono * left_gain)))
            right = max(-32768, min(32767, round(mono * right_gain)))
            rendered.extend(struct.pack("<hh", left, right))
        sound = self.mixer.Sound(buffer=bytes(rendered))
        channel = sound.play()
        self._channels = [c for c in self._channels if c.get_busy()]
        if channel is not None:
            self._channels.append(channel)

    def stop(self):
        for channel in self._channels:
            channel.stop()
        self._channels = []


class NPCSoundReader:
    def __init__(
        self,
        source,
        sound_paths,
        player,
        logger,
        max_distance=120.0,
        repeat_pause=1.0,
        clock=time.monotonic,
        speech=None,
        entity_names=None,
        interaction_allowance=1.5,
        interaction_context=None,
        foreground_active=None,
        category_sound_paths=None,
        room_names=None,
        beacon_categories=None,
    ):
        self.source = source
        self.paths = tuple(Path(path) for path in sound_paths)
        if not self.paths:
            raise ValueError("at least one NPC sound is required")
        self.durations = tuple(wave_duration(path) for path in self.paths)
        self.player = player
        self.logger = logger
        self.max_distance = max_distance
        self.repeat_pause = repeat_pause
        self.clock = clock
        self.speech = speech
        self.entity_names = entity_names or {}
        self.interaction_inside = set()
        self.interaction_focus = None
        self.interaction_allowance = interaction_allowance
        self.interaction_context = interaction_context
        self.foreground_active = foreground_active or (lambda: True)
        self.foreground_was_active = True
        self.category_paths = {
            key: Path(path)
            for key, path in (category_sound_paths or {}).items()
        }
        self.category_durations = {
            key: wave_duration(path)
            for key, path in self.category_paths.items()
        }
        # Categories allowed to sound. None means "no restriction" (the
        # original behaviour). When set, a category with no sound of its
        # own is skipped rather than falling back to `self.paths`, which
        # would give e.g. an elevator the plain NPC tone and actively
        # mislead -- a wrong cue is worse than no cue, because the player
        # acts on it.
        self.beacon_categories = (
            frozenset(beacon_categories) if beacon_categories is not None
            else None
        )
        self.room_names = room_names or {}
        self.announced_floor_id = None
        self.next_due = {}
        self.busy_until = 0.0
        self.floor_id = None

    def clear(self, reason):
        self.next_due.clear()
        self.busy_until = 0.0
        self.floor_id = None
        self.interaction_inside.clear()
        if self.interaction_context is not None:
            self.interaction_context.name = None
            self.interaction_context.identity = None
        self.logger.debug("NPC beacons cleared: %s", reason)

    def suppress_for_dialogue(self):
        self.player.stop()

    def sound_index(self, npc):
        return (npc.floor_id * 31 + npc.index) % len(self.paths)

    def sound_for(self, npc):
        if npc.category in self.category_paths:
            return (
                self.category_paths[npc.category],
                self.category_durations[npc.category],
            )
        index = self.sound_index(npc)
        return self.paths[index], self.durations[index]

    def room_description(self, floor_id):
        code = self.room_names.get(floor_id)
        if not code:
            return f"Map {floor_id}"
        parts = code.split("_")
        area = MAP_NAMES.get(parts[0], parts[0])
        detail = " ".join(parts[1:]).replace("labo", "Lab")
        detail = detail.replace("1F", "1 F").replace("2F", "2 F")
        detail = detail.replace("B1", "Basement 1")
        return f"{area}, {detail}" if detail else area

    def announce_current_map(self):
        if not hasattr(self.source, "current_floor_id"):
            return
        floor_id = self.source.current_floor_id()
        if floor_id == self.announced_floor_id:
            return
        self.announced_floor_id = floor_id
        if self.speech is not None:
            from .speech import SpeechEventClass
            description = self.room_description(floor_id)
            self.speech.emit(
                SpeechEventClass.ENTITY_NAV,
                f"Map: {description}.",
                deduplicate=False,
            )
            self.logger.info(
                "MAP ANNOUNCEMENT floor=%d description=%r",
                floor_id, description,
            )

    @staticmethod
    def spatial_values(pose, npc, max_distance):
        dx = npc.position.x - pose.position.x
        dz = npc.position.z - pose.position.z
        horizontal = math.hypot(dx, dz)
        if horizontal:
            right_x = math.cos(pose.yaw)
            right_z = -math.sin(pose.yaw)
            pan = max(-1.0, min(1.0, (dx * right_x + dz * right_z)
                                / horizontal))
        else:
            pan = 0.0
        forward_x = -math.sin(pose.yaw)
        forward_z = -math.cos(pose.yaw)
        joystick_up_distance = dx * forward_x + dz * forward_z
        # The navigation beacon's own curve, scaled globally and then
        # trimmed per category -- see PASSIVE_BEACON_GAIN_SCALE and
        # PASSIVE_BEACON_CATEGORY_GAIN. The 0.18 floor keeps a far-off
        # entity just audible rather than fading to nothing, which is the
        # whole point of an ambient beacon.
        proximity = max(0.18, min(1.0, 1.0 - horizontal / max_distance))
        gain = (
            PASSIVE_BEACON_GAIN_SCALE
            * PASSIVE_BEACON_CATEGORY_GAIN.get(npc.category, 1.0)
            * navigation_gain(proximity)
        )
        semitones = max(-6.0, min(6.0, joystick_up_distance / 8.0))
        pitch = 2 ** (semitones / 12.0)
        return horizontal, pan, pitch, gain

    def poll_once(self):
        focused = bool(self.foreground_active())
        if not focused:
            if self.foreground_was_active:
                self.player.stop()
                self.clear("Dolphin is not foreground")
            self.foreground_was_active = False
            return
        if not self.foreground_was_active:
            self.next_due.clear()
            self.busy_until = 0.0
            self.logger.debug("NPC beacons resumed: Dolphin foreground")
        self.foreground_was_active = True
        self.announce_current_map()
        now = self.clock()
        pose = self.source.player_pose()
        available = {}
        for npc in self.source.npcs():
            if not npc.visible or not npc.talk_id:
                continue
            if (self.beacon_categories is not None
                    and npc.category not in self.beacon_categories):
                continue
            spatial = self.spatial_values(pose, npc, self.max_distance)
            if spatial[0] <= self.max_distance:
                available[npc.identity] = (npc, spatial)
        interaction = {
            identity for identity, (npc, spatial) in available.items()
            if spatial[0] <= (
                npc.interaction_radius
                + self.interaction_allowance
            )
        }
        nearest = (
            min(interaction, key=lambda item: available[item][1][0])
            if interaction else None
        )
        if nearest is not None:
            npc = available[nearest][0]
            name = npc.label or self.entity_names.get(npc.name_id, "NPC")
        else:
            npc = None
            name = None
        if self.interaction_context is not None:
            self.interaction_context.name = name
            self.interaction_context.identity = (npc.floor_id, npc.index) if npc else None
        if (
            nearest is not None
            and nearest != self.interaction_focus
            and self.speech is not None
        ):
            from .speech import SpeechEventClass
            self.speech.emit(
                SpeechEventClass.NPC_INTERACTION,
                f"{name}, interaction available.",
                deduplicate=False,
            )
            self.logger.info(
                "NPC INTERACTION floor=%d npc=%d name_id=%d name=%r distance=%.2f",
                npc.floor_id, npc.index, npc.name_id, name,
                available[nearest][1][0],
            )
        self.interaction_focus = nearest
        self.interaction_inside = interaction
        current_floor = next(
            (npc.floor_id for npc, _ in available.values()), None)
        if current_floor != self.floor_id:
            self.floor_id = current_floor
            self.next_due.clear()
        self.next_due = {
            identity: due for identity, due in self.next_due.items()
            if identity in available
        }
        for identity in available:
            self.next_due.setdefault(identity, now)
        if now < self.busy_until:
            return
        ready = [
            identity for identity, due in self.next_due.items()
            if due <= now
        ]
        if not ready:
            return
        identity = min(
            ready,
            key=lambda item: (
                0 if item in interaction else 1,
                self.next_due[item],
                available[item][1][0],
            ),
        )
        npc, (distance, pan, pitch, gain) = available[identity]
        sound_path, duration = self.sound_for(npc)
        self.player.play(sound_path, pan, pitch, gain)
        self.busy_until = (
            now + 0.12 if identity in interaction
            else now + duration + 0.10
        )
        distance_ratio = min(1.0, distance / self.max_distance)
        interval = (
            0.18 if identity in interaction
            else 0.30 + 5.70 * (distance_ratio ** 1.25)
        )
        self.next_due[identity] = now + interval
        self.logger.info(
            "NPC BEACON floor=%d npc=%d distance=%.2f pan=%.2f "
            "camera_pitch=%.3f gain=%.2f sound=%s",
            npc.floor_id,
            npc.index,
            distance,
            pan,
            pitch,
            gain,
            sound_path.name,
        )







