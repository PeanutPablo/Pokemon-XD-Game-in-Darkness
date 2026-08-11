import math
import shutil
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np

from battle_narrator.entity_sources import WarpAugmentedNPCSource
from battle_narrator.entities import Entity
from battle_narrator.memory import MemoryReader
from battle_narrator.npc_beacons import (
    MIN_WSOLA_SAMPLES, MIXER_FREQUENCY, NPC, NPCMemorySource, NPCSoundReader,
    PASSIVE_BEACON_SOUND_FILES, PlayerPose, Position, SpatialWavePlayer,
    _pitch_shift_wsola, check_playable, resolve_sound_dir,
)
from battle_narrator.profile import XD_US_REV0


def _sine(frequency, sample_rate, count, amplitude=10000.0):
    return [
        amplitude * math.sin(2 * math.pi * frequency * i / sample_rate)
        for i in range(count)
    ]


def _dominant_frequency(samples, sample_rate):
    values = np.asarray(samples, dtype=np.float64)
    spectrum = np.abs(np.fft.rfft(values))
    spectrum[0] = 0.0  # ignore DC
    freqs = np.fft.rfftfreq(len(values), d=1.0 / sample_rate)
    return float(freqs[int(np.argmax(spectrum))])


class Source:
    def __init__(self, npcs):
        self.items = npcs

    def player_pose(self):
        return PlayerPose(Position(0, 0, 0), 0)

    def npcs(self):
        return self.items


class Player:
    def __init__(self):
        self.played = []
        self.stopped = 0

    def play(self, path, pan, pitch, gain):
        self.played.append((Path(path).name, pan, pitch, gain))

    def stop(self):
        self.stopped += 1


class Logger:
    def debug(self, *args): pass
    def info(self, *args): pass


class Speech:
    def __init__(self):
        self.calls = []

    def emit(self, event_class, text, **kwargs):
        self.calls.append(text)


def make_wave(path):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 10)


class FakeChannel:
    def __init__(self):
        self._busy = True

    def get_busy(self):
        return self._busy

    def stop(self):
        self._busy = False


class FakeSound:
    def __init__(self, buffer):
        self.buffer = buffer
        self.channel = None

    def play(self):
        self.channel = FakeChannel()
        return self.channel


class FakeMixer:
    """Stand-in for pygame.mixer -- records every Sound() buffer and
    tracks channel busy/stopped state, without touching real audio."""

    def __init__(self):
        self.initialized = False
        self.init_args = None
        self.num_channels = None
        self.sounds = []

    def get_init(self):
        return self.initialized

    def init(self, frequency, size, channels):
        self.initialized = True
        self.init_args = (frequency, size, channels)

    def set_num_channels(self, count):
        self.num_channels = count

    def Sound(self, buffer):
        sound = FakeSound(buffer)
        self.sounds.append(sound)
        return sound


class NPCBeaconTests(unittest.TestCase):
    def test_map_change_is_announced_once_with_room_name(self):
        with tempfile.TemporaryDirectory() as directory:
            sound = Path(directory) / "npc.wav"
            make_wave(sound)
            source, speech = Source([]), Speech()
            floor = [0x8C]
            source.current_floor_id = lambda: floor[0]
            reader = NPCSoundReader(
                source, [sound], Player(), Logger(), speech=speech,
                room_names={0x8C: "M5_labo_1F", 0x8D: "M5_labo_2F"},
            )
            reader.poll_once()
            reader.poll_once()
            floor[0] = 0x8D
            reader.poll_once()
            self.assertEqual(speech.calls, [
                "Map: Pokemon HQ Lab, Lab 1 F.",
                "Map: Pokemon HQ Lab, Lab 2 F.",
            ])

    def test_elevator_uses_distinct_category_sound(self):
        with tempfile.TemporaryDirectory() as directory:
            npc_sound = Path(directory) / "npc.wav"
            elevator_sound = Path(directory) / "elevator.wav"
            make_wave(npc_sound)
            make_wave(elevator_sound)
            reader = NPCSoundReader(
                Source([]), [npc_sound], Player(), Logger(),
                category_sound_paths={"elevator": elevator_sound},
            )
            elevator = NPC(
                0x8C, 0x7FFF, True, 1, Position(0, 15, -140),
                category="elevator", label="Elevator",
            )
            self.assertEqual(reader.sound_for(elevator)[0], elevator_sound)


    def test_warp_uses_unique_sound_and_authoritative_position(self):
        with tempfile.TemporaryDirectory() as directory:
            npc_sound = Path(directory) / "npc.wav"
            warp_sound = Path(directory) / "warp.wav"
            make_wave(npc_sound); make_wave(warp_sound)
            base = Source([])
            base.current_floor_id = lambda: 0xAD
            warp_entity = Entity(
                "warp", ("warp", 790), "to World Map",
                Position(12, 3, -4),
            )
            warp_source = type("Warps", (), {
                "entities": lambda self: [warp_entity]
            })()
            source = WarpAugmentedNPCSource(base, warp_source)
            warp = source.npcs()[0]
            reader = NPCSoundReader(
                source, [npc_sound], Player(), Logger(),
                category_sound_paths={"warp": warp_sound},
            )
            self.assertEqual(warp.category, "warp")
            self.assertEqual(warp.position, Position(12, 3, -4))
            self.assertEqual(reader.sound_for(warp)[0], warp_sound)
            self.assertLess(warp.interaction_radius, 0)

    def test_beacons_require_dolphin_foreground_focus(self):
        with tempfile.TemporaryDirectory() as directory:
            sound = Path(directory) / "npc.wav"
            make_wave(sound)
            npc = NPC(141, 0, True, 1, Position(20, 0, 0))
            player, focused = Player(), [True]
            reader = NPCSoundReader(
                Source([npc]), [sound], player, Logger(),
                foreground_active=lambda: focused[0])
            reader.poll_once()
            focused[0] = False
            reader.poll_once()
            reader.poll_once()
            focused[0] = True
            reader.poll_once()
            self.assertEqual(len(player.played), 2)
            self.assertEqual(player.stopped, 1)

    def test_all_npcs_repeat_in_nearest_first_cycles(self):
        with tempfile.TemporaryDirectory() as directory:
            sounds = [Path(directory) / f"{i}.wav" for i in range(3)]
            for sound in sounds:
                make_wave(sound)
            npcs = [
                NPC(141, 0, True, 1, Position(20, 0, 0)),
                NPC(141, 1, True, 2, Position(5, 0, 0)),
            ]
            player, now = Player(), [0.0]
            reader = NPCSoundReader(
                Source(npcs), sounds, player, Logger(),
                repeat_pause=1, clock=lambda: now[0])
            reader.poll_once()
            now[0] = 1
            reader.poll_once()
            now[0] = 3
            reader.poll_once()
            self.assertEqual(len(player.played), 3)
            self.assertEqual(
                player.played[0][0], sounds[reader.sound_index(npcs[1])].name)

    def test_pan_and_pitch_follow_camera_joystick_axes(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        right = NPC(1, 0, True, 1, Position(10, 0, -6))
        _, pan, pitch, _ = NPCSoundReader.spatial_values(pose, right, 120)
        self.assertGreater(pan, 0.8)
        self.assertGreater(pitch, 1)
        turned = PlayerPose(Position(0, 0, 0), math.pi)
        self.assertLess(
            NPCSoundReader.spatial_values(turned, right, 120)[1], -0.8)
        below = NPC(1, 1, True, 1, Position(1, 0, 6))
        self.assertLess(
            NPCSoundReader.spatial_values(pose, below, 120)[2], 1)

    def test_renderer_resamples_to_mixer_rate_and_plays_via_a_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.wav"
            make_wave(source)
            mixer = FakeMixer()
            player = SpatialWavePlayer(mixer_module=mixer)
            player.play(source, pan=1, pitch=1.25, gain=0.5)
            self.assertTrue(mixer.initialized)
            self.assertEqual(mixer.init_args, (MIXER_FREQUENCY, -16, 2))
            self.assertEqual(len(mixer.sounds), 1)
            expected_frames = round(10 * MIXER_FREQUENCY / 8000)
            self.assertEqual(len(mixer.sounds[0].buffer), expected_frames * 4)
            self.assertTrue(mixer.sounds[0].channel.get_busy())

    def test_two_instances_only_stop_their_own_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.wav"
            make_wave(source)
            shared_mixer = FakeMixer()
            footsteps = SpatialWavePlayer(mixer_module=shared_mixer)
            guide = SpatialWavePlayer(mixer_module=shared_mixer)
            footsteps.play(source, pan=0, pitch=1.0, gain=1.0)
            guide.play(source, pan=0, pitch=1.0, gain=1.0)
            footsteps_channel = shared_mixer.sounds[0].channel
            guide_channel = shared_mixer.sounds[1].channel
            footsteps.stop()
            self.assertFalse(footsteps_channel.get_busy())
            self.assertTrue(guide_channel.get_busy())


class PitchShiftTests(unittest.TestCase):
    """Numerical regression coverage for the WSOLA pitch shift (npc_beacons.
    _pitch_shift_wsola / _pitch_shift_fft_fallback, dispatched by
    SpatialWavePlayer._pitch_shift_constant_duration). These can confirm
    length/finiteness/frequency-ratio correctness -- they cannot judge
    perceptual quality ("does it sound less phasey"), which requires a live
    listening comparison by the project owner."""

    def test_pitch_shift_preserves_length(self):
        samples = _sine(440.0, 8000, 2000)
        result = SpatialWavePlayer._pitch_shift_constant_duration(samples, 1.25)
        self.assertEqual(len(result), len(samples))

    def test_dominant_frequency_shifts_by_the_requested_ratio(self):
        sample_rate = 8000
        frequency = 440.0
        samples = _sine(frequency, sample_rate, 4000)
        for pitch in (1.25, 0.8):
            result = SpatialWavePlayer._pitch_shift_constant_duration(samples, pitch)
            self.assertEqual(len(result), len(samples))
            shifted_frequency = _dominant_frequency(result, sample_rate)
            expected = frequency * pitch
            self.assertLess(
                abs(shifted_frequency - expected), expected * 0.05 + 5.0,
                f"pitch={pitch}: expected ~{expected} Hz, got {shifted_frequency} Hz",
            )

    def test_unity_pitch_returns_input_unchanged(self):
        samples = _sine(440.0, 8000, 500)
        result = SpatialWavePlayer._pitch_shift_constant_duration(samples, 1.0)
        self.assertEqual(result, samples)

    def test_short_clip_falls_back_to_fft_method(self):
        samples = _sine(440.0, 8000, 10)
        self.assertLess(len(samples), MIN_WSOLA_SAMPLES)
        self.assertIsNone(_pitch_shift_wsola(samples, 1.25))
        result = SpatialWavePlayer._pitch_shift_constant_duration(samples, 1.25)
        self.assertEqual(len(result), len(samples))
        self.assertTrue(all(math.isfinite(value) for value in result))

    def test_silence_in_produces_silence_out(self):
        samples = [0.0] * 2000
        result = SpatialWavePlayer._pitch_shift_constant_duration(samples, 1.3)
        self.assertEqual(len(result), len(samples))
        self.assertTrue(all(math.isfinite(value) for value in result))
        self.assertLess(max(abs(value) for value in result), 1e-6)

    def test_no_nan_or_inf_across_a_range_of_pitches_and_lengths(self):
        for length in (80, 500, 3000):
            for pitch in (0.5, 0.8, 1.0, 1.25, 2.0):
                samples = _sine(220.0, 8000, length)
                result = SpatialWavePlayer._pitch_shift_constant_duration(
                    samples, pitch)
                self.assertEqual(len(result), length)
                self.assertTrue(
                    all(math.isfinite(value) for value in result),
                    f"non-finite output for length={length} pitch={pitch}",
                )


FLOOR_ID = 0x8D

FLOOR_DATA_COUNT_PTR = 0x80700000
FLOOR_DATA_TABLE = 0x80700100

# floor_character lookup is a 3-hop chain in the real code:
#   slot = *(floor + slot_offset)      -> FLOOR_CHAR_SLOT
#   header = *slot                     -> FLOOR_CHAR_HEADER
#   count_pointer = *header            -> FLOOR_CHAR_COUNT
#   npc_count = *count_pointer         -> plain integer
#   base = *(header + 4)               -> FLOOR_CHAR_RECORDS (single hop off header)
FLOOR_CHAR_SLOT = 0x80700200
FLOOR_CHAR_HEADER = 0x80700220
FLOOR_CHAR_COUNT = 0x80700230
FLOOR_CHAR_RECORDS = 0x80700300

PEOPLE_INFO_COUNT_PTR = 0x80700400
PEOPLE_INFO_TABLE = 0x80700500

PEOPLE_WORK_TABLE = 0x80700700


def be16(value):
    return value.to_bytes(2, "big")


def be32(value):
    return value.to_bytes(4, "big")


def bef(value):
    return struct.pack(">f", value)


class FakeBackend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + offset, 0) for offset in range(size))


class NPCMemorySourceTests(unittest.TestCase):
    """Covers the live people-work presence cross-reference added after a
    live-confirmed bug: floor_character's own visible bit stayed True for
    Krane on the Lab 2F after he was kidnapped (story-hidden), while the
    live people-actor table's disp byte correctly read 0. See
    profile.py's people_work_* fields and NPCMemorySource's
    _live_visibility_by_index() for the full mechanism."""

    def setUp(self):
        self.backend = FakeBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        p = self.profile

        self.backend.put(p.current_floor_id, be16(FLOOR_ID))

        self.backend.put(p.floor_data_count_root, be32(FLOOR_DATA_COUNT_PTR))
        self.backend.put(FLOOR_DATA_COUNT_PTR, be32(1))
        self.backend.put(p.floor_data_root, be32(FLOOR_DATA_TABLE))
        self.backend.put(FLOOR_DATA_TABLE + p.floor_id_offset, be16(FLOOR_ID))
        self.backend.put(
            FLOOR_DATA_TABLE + p.floor_character_slot_offset,
            be32(FLOOR_CHAR_SLOT),
        )
        self.backend.put(FLOOR_CHAR_SLOT, be32(FLOOR_CHAR_HEADER))
        self.backend.put(FLOOR_CHAR_HEADER, be32(FLOOR_CHAR_COUNT))
        self.backend.put(FLOOR_CHAR_COUNT, be32(2))
        self.backend.put(FLOOR_CHAR_HEADER + 4, be32(FLOOR_CHAR_RECORDS))

        self.backend.put(p.people_info_count_root, be32(PEOPLE_INFO_COUNT_PTR))
        self.backend.put(PEOPLE_INFO_COUNT_PTR, be32(1))
        self.backend.put(p.people_info_root, be32(PEOPLE_INFO_TABLE))
        self.backend.put(
            PEOPLE_INFO_TABLE + p.people_info_talk_distance_offset, bef(5.0)
        )

        self._set_floor_character(0, name_id=1, visible=True)
        self._set_floor_character(1, name_id=3, visible=True)

        # No live people-work records by default -- npcs() must fall back
        # to the static bit when nothing has been spawned yet.
        self.backend.put(p.people_work_count_address, be32(0))

    def _set_floor_character(self, index, name_id, visible):
        p = self.profile
        record = FLOOR_CHAR_RECORDS + index * p.floor_character_stride
        flags = p.floor_character_visible_mask if visible else 0
        self.backend.put(record, bytes([flags]))
        self.backend.put(record + p.floor_character_people_info_offset, be16(0))
        self.backend.put(record + p.floor_character_name_offset, be16(name_id))
        self.backend.put(
            record + p.floor_character_talk_offset, be32(0x0100000C + index)
        )
        self.backend.put(record + p.floor_character_position_offset, bef(0.0))
        self.backend.put(record + p.floor_character_position_offset + 4, bef(0.0))
        self.backend.put(record + p.floor_character_position_offset + 8, bef(0.0))

    def _set_people_work(self, records):
        """records: list of (identity_a, identity_b, disp) for occupied slots."""
        p = self.profile
        self.backend.put(p.people_work_count_address, be32(len(records)))
        self.backend.put(p.people_work_root_address, be32(PEOPLE_WORK_TABLE))
        for slot, (identity_a, identity_b, disp) in enumerate(records):
            record = PEOPLE_WORK_TABLE + slot * p.people_work_stride
            self.backend.put(record + p.people_work_occupied_offset, bytes([1]))
            self.backend.put(
                record + p.people_work_identity_a_offset, be32(identity_a)
            )
            self.backend.put(
                record + p.people_work_identity_b_offset, be32(identity_b)
            )
            self.backend.put(
                record + p.people_work_disp_offset, bytes([1 if disp else 0])
            )

    def test_falls_back_to_static_visible_bit_when_no_live_record(self):
        npcs = NPCMemorySource(self.memory, self.profile).npcs()
        self.assertEqual([npc.visible for npc in npcs], [True, True])

    def test_live_disp_bit_overrides_stale_static_visible_true(self):
        self._set_people_work([
            (0x7C0, 0, True),
            (0x7C0, 1, False),
        ])
        npcs = NPCMemorySource(self.memory, self.profile).npcs()
        self.assertEqual([npc.visible for npc in npcs], [True, False])

    def test_reserved_identity_a_zero_slots_are_ignored(self):
        self._set_people_work([
            (0, 1, False),
        ])
        npcs = NPCMemorySource(self.memory, self.profile).npcs()
        self.assertEqual([npc.visible for npc in npcs], [True, True])

    def test_live_disp_bit_can_also_confirm_static_false(self):
        self._set_floor_character(0, name_id=1, visible=False)
        self._set_people_work([
            (0x7C0, 0, False),
        ])
        npcs = NPCMemorySource(self.memory, self.profile).npcs()
        self.assertEqual([npc.visible for npc in npcs], [False, True])


class SparseBackend:
    """Backend serving explicitly-placed bytes; unmapped reads return zeros."""

    def __init__(self, regions):
        self.regions = dict(regions)

    def read_bytes(self, address, size):
        out = bytearray(size)
        for base, blob in self.regions.items():
            for offset in range(len(blob)):
                index = base + offset - address
                if 0 <= index < size:
                    out[index] = blob[offset]
        return bytes(out)


class LiveActorPositionTests(unittest.TestCase):
    """floor_character holds only a SCRIPTED spawn position. Any NPC the
    game has moved since -- the project owner hit this with the Hexagon
    Brothers, whom a cutscene walked out of a building -- would otherwise be
    reported at where it started, making every bearing for it wrong.

    The chain is the engine's own: peopleBiosGetPosPtr (0x80297724) reads
    the model pointer from people_work + 0x08, then GSmodelGetPositionPtr
    (0x800F7B30) adds 0x18."""

    RECORD = 0x80500000
    MODEL = 0x80600000

    def source(self, regions):
        p = XD_US_REV0
        return NPCMemorySource(MemoryReader(SparseBackend(regions), p), p)

    def test_reads_the_live_model_position(self):
        p = XD_US_REV0
        regions = {
            self.RECORD + p.people_work_model_offset: struct.pack(
                ">I", self.MODEL),
            self.MODEL + p.model_position_offset: struct.pack(
                ">fff", 12.5, 3.0, -47.25),
        }
        position = self.source(regions)._live_position(self.RECORD)
        self.assertIsNotNone(position)
        self.assertAlmostEqual(position.x, 12.5, places=4)
        self.assertAlmostEqual(position.y, 3.0, places=4)
        self.assertAlmostEqual(position.z, -47.25, places=4)

    def test_null_model_pointer_falls_back(self):
        """An actor with no model must not break the NPC list -- the static
        position stays usable."""
        p = XD_US_REV0
        regions = {
            self.RECORD + p.people_work_model_offset: struct.pack(">I", 0),
        }
        self.assertIsNone(self.source(regions)._live_position(self.RECORD))

    def test_out_of_range_model_pointer_falls_back(self):
        p = XD_US_REV0
        regions = {
            self.RECORD + p.people_work_model_offset: struct.pack(
                ">I", 0x0000BEEF),
        }
        self.assertIsNone(self.source(regions)._live_position(self.RECORD))

    def test_non_finite_live_position_is_rejected(self):
        """A half-initialised model can hold NaN; reporting that as a real
        position would poison every distance and bearing computed from it."""
        p = XD_US_REV0
        regions = {
            self.RECORD + p.people_work_model_offset: struct.pack(
                ">I", self.MODEL),
            self.MODEL + p.model_position_offset: struct.pack(
                ">fff", float("nan"), 0.0, 0.0),
        }
        self.assertIsNone(self.source(regions)._live_position(self.RECORD))


class CameraYawReadTests(unittest.TestCase):
    """The yaw must come from [pCamWork] + 0x14, the way cameraGetRotY() reads
    it -- not from the _activeCamera + 0x88 field used previously, which was
    verified live to sit at 0.0 while the real yaw swung through 67 degrees."""

    MODEL = 0x80400000
    CAMERA_WORK = 0x80475580
    ACTIVE_CAMERA_OBJECT = 0x80804AA0
    REAL_YAW = 1.5090

    def build(self):
        p = XD_US_REV0
        regions = {
            # hero model position
            self.MODEL + p.model_position_offset: struct.pack(
                ">fff", 1.0, 2.0, 3.0),
            # pCamWork -> _cameraWork, and the yaw the engine actually uses
            p.camera_work_pointer: struct.pack(">I", self.CAMERA_WORK),
            self.CAMERA_WORK + p.camera_work_rot_y_offset: struct.pack(
                ">f", self.REAL_YAW),
            # the old path: _activeCamera -> an object whose +0x88 is 0.0,
            # exactly as observed live. If the read regresses, yaw goes to 0.
            0x804EAEE0: struct.pack(">I", self.ACTIVE_CAMERA_OBJECT),
            self.ACTIVE_CAMERA_OBJECT + 0x88: struct.pack(">f", 0.0),
        }
        source = NPCMemorySource(MemoryReader(SparseBackend(regions), p), p)
        source.hero_model_address = lambda: self.MODEL
        return source

    def test_yaw_comes_from_camera_work_not_active_camera(self):
        pose = self.build().player_pose()
        self.assertAlmostEqual(pose.yaw, self.REAL_YAW, places=5)
        self.assertNotAlmostEqual(pose.yaw, 0.0, places=5)

    def test_yaw_follows_camera_work_when_it_changes(self):
        """A field-camera room blends yaw every frame, so a cached or
        one-shot read would be wrong -- the value must track."""
        source = self.build()
        self.assertAlmostEqual(source.player_pose().yaw, self.REAL_YAW, places=5)
        source.memory.backend.regions[
            self.CAMERA_WORK + XD_US_REV0.camera_work_rot_y_offset
        ] = struct.pack(">f", 0.6600)
        self.assertAlmostEqual(source.player_pose().yaw, 0.6600, places=5)


class ResolveSoundDirTests(unittest.TestCase):
    """The release used to ship without `sounds/` reachable at all: the
    path was hardcoded two levels above `Companion/`, which lands outside
    an extracted release, and the resulting LocalDataError killed the
    narrator on the first beacon. Both layouts are asserted here because
    the development checkout is the one the project owner runs and the
    release layout is the one nobody was testing."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def _companion(self, *, project="PokemonXGAccessibility"):
        companion = self.root / project / "Companion"
        companion.mkdir(parents=True)
        return companion

    def test_release_layout_sounds_beside_companion(self):
        companion = self._companion()
        packaged = companion.parent / "sounds"
        packaged.mkdir()
        self.assertEqual(resolve_sound_dir(companion), packaged)

    def test_checkout_layout_sounds_above_the_project(self):
        companion = self._companion()
        checkout = companion.parent.parent / "sounds"
        checkout.mkdir()
        self.assertEqual(resolve_sound_dir(companion), checkout)

    def test_packaged_sounds_win_over_an_unrelated_neighbour(self):
        """A recipient who extracts into a folder that already has a
        `sounds/` in it must still get the packaged one."""
        companion = self._companion()
        packaged = companion.parent / "sounds"
        packaged.mkdir()
        (companion.parent.parent / "sounds").mkdir()
        self.assertEqual(resolve_sound_dir(companion), packaged)

    def test_missing_everywhere_reports_the_release_location(self):
        """The error a recipient sees should name the folder they can
        actually go and look at, not one two levels above their release."""
        companion = self._companion()
        self.assertEqual(
            resolve_sound_dir(companion), companion.parent / "sounds")

    def test_a_file_named_sounds_is_not_a_sound_directory(self):
        companion = self._companion()
        (companion.parent / "sounds").write_text("not a directory")
        checkout = companion.parent.parent / "sounds"
        checkout.mkdir()
        self.assertEqual(resolve_sound_dir(companion), checkout)


class PassiveBeaconSoundFileTests(unittest.TestCase):
    """Every category the app beacons must have a real, playable file in
    the project's own `sounds/` directory -- these are the files the
    release now has to carry, and a missing one is a startup crash."""

    def test_every_passive_beacon_file_exists_and_is_playable(self):
        sounds = resolve_sound_dir(Path(__file__).parents[1])
        if not sounds.is_dir():
            self.skipTest(f"no sounds directory at {sounds}")
        for category, filename in PASSIVE_BEACON_SOUND_FILES.items():
            with self.subTest(category=category):
                check_playable(sounds / filename)


if __name__ == "__main__":
    unittest.main()




