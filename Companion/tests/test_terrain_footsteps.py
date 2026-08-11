import logging
import math
import unittest
from pathlib import Path

from battle_narrator.collision_probe import CollisionTriangle
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.terrain_footsteps import (
    BlockedMovementReader,
    TerrainFootstepReader,
    TerrainTonePlayer,
    find_ground_triangle,
    load_walk_model_triangles,
)

REAL_COLLISION_DIR = (
    Path(__file__).resolve().parent.parent / "_dialogue_extraction" / "collision"
)


def floor_triangle(vertices, collision_type, entry_index=0):
    return CollisionTriangle(
        tuple(vertices), (0.0, 1.0, 0.0), collision_type, entry_index)


def wall_triangle(vertices, collision_type=9, entry_index=0):
    return CollisionTriangle(
        tuple(vertices), (0.0, 0.0, 1.0), collision_type, entry_index)


class FindGroundTriangleTests(unittest.TestCase):
    def test_finds_triangle_containing_point_at_matching_height(self):
        ground = floor_triangle((
            (-5.0, 0.0, -5.0), (5.0, 0.0, -5.0), (0.0, 0.0, 5.0),
        ), collision_type=2)
        result = find_ground_triangle((ground,), Position(0.0, 0.05, 0.0))
        self.assertIs(result, ground)

    def test_returns_none_outside_every_triangle(self):
        ground = floor_triangle((
            (-5.0, 0.0, -5.0), (5.0, 0.0, -5.0), (0.0, 0.0, 5.0),
        ), collision_type=2)
        result = find_ground_triangle((ground,), Position(50.0, 0.0, 50.0))
        self.assertIsNone(result)

    def test_returns_none_when_height_gap_exceeds_tolerance(self):
        ground = floor_triangle((
            (-5.0, 0.0, -5.0), (5.0, 0.0, -5.0), (0.0, 0.0, 5.0),
        ), collision_type=2)
        result = find_ground_triangle(
            (ground,), Position(0.0, 10.0, 0.0), height_tolerance=1.5)
        self.assertIsNone(result)

    def test_ignores_vertical_wall_triangles(self):
        wall = wall_triangle((
            (-5.0, 0.0, 0.0), (5.0, 0.0, 0.0), (0.0, 10.0, 0.0),
        ))
        result = find_ground_triangle((wall,), Position(0.0, 1.0, 0.0))
        self.assertIsNone(result)

    def test_picks_closer_floor_when_two_overlap_in_xz(self):
        lower = floor_triangle((
            (-5.0, 0.0, -5.0), (5.0, 0.0, -5.0), (0.0, 0.0, 5.0),
        ), collision_type=1)
        upper = floor_triangle((
            (-5.0, 10.0, -5.0), (5.0, 10.0, -5.0), (0.0, 10.0, 5.0),
        ), collision_type=7)
        result = find_ground_triangle(
            (lower, upper), Position(0.0, 9.6, 0.0), height_tolerance=5.0)
        self.assertIs(result, upper)


class RecordingTonePlayer:
    def __init__(self):
        self.steps = []
        self.blocked_calls = 0

    def play_step(self, collision_type):
        self.steps.append(collision_type)

    def play_blocked(self):
        self.blocked_calls += 1


class FakeMemory:
    def __init__(self, floor_id):
        self.floor_id = floor_id

    def u16(self, address, label):
        return self.floor_id


class FakeProfile:
    current_floor_id = 0x1234


class FakePoseSource:
    def __init__(self, poses):
        self._poses = list(poses)

    def player_pose(self):
        return self._poses.pop(0)


def make_reader(poses, ground_type=2, wall_hit=None):
    reader = TerrainFootstepReader(
        FakeMemory(0x8A), FakeProfile(), FakePoseSource(poses),
        collision_dir="unused", room_codes={}, tone_player=RecordingTonePlayer(),
        logger=None,
    )
    ground = floor_triangle((
        (-50.0, 0.0, -50.0), (50.0, 0.0, -50.0), (0.0, 0.0, 50.0),
    ), collision_type=ground_type)
    triangles = [ground]
    if wall_hit is not None:
        triangles.append(wall_hit)
    reader._triangles_by_room[0x8A] = tuple(triangles)
    return reader


class TerrainFootstepReaderTests(unittest.TestCase):
    def test_first_poll_only_records_position(self):
        reader = make_reader([PlayerPose(Position(0.0, 0.0, 0.0), 0.0)])
        reader.poll_once()
        self.assertEqual(reader.tone_player.steps, [])
        self.assertEqual(reader.tone_player.blocked_calls, 0)

    def test_small_movement_does_not_trigger_a_step(self):
        reader = make_reader([
            PlayerPose(Position(0.0, 0.0, 0.0), 0.0),
            PlayerPose(Position(0.1, 0.0, 0.0), 0.0),
        ])
        reader.poll_once()
        reader.poll_once()
        self.assertEqual(reader.tone_player.steps, [])

    def test_crossing_step_distance_triggers_exactly_one_step_with_ground_type(self):
        step = TerrainFootstepReader.STEP_DISTANCE
        reader = make_reader([
            PlayerPose(Position(0.0, 0.0, 0.0), 0.0),
            PlayerPose(Position(step + 1.0, 0.0, 0.0), 0.0),
        ], ground_type=5)
        reader.poll_once()
        reader.poll_once()
        self.assertEqual(reader.tone_player.steps, [5])

    def test_multiple_steps_accumulate_across_polls(self):
        # Each individual delta stays below STEP_DISTANCE on its own, but
        # crosses it on the 2nd and 4th poll once accumulated -- mirrors a
        # real per-poll walking delta smaller than one full step.
        delta = TerrainFootstepReader.STEP_DISTANCE * (2.0 / 3.0)
        reader = make_reader([
            PlayerPose(Position(0.0, 0.0, 0.0), 0.0),
            PlayerPose(Position(delta, 0.0, 0.0), 0.0),
            PlayerPose(Position(delta * 2, 0.0, 0.0), 0.0),
            PlayerPose(Position(delta * 3, 0.0, 0.0), 0.0),
        ], ground_type=2)
        for _ in range(4):
            reader.poll_once()
        self.assertEqual(reader.tone_player.steps, [2, 2])

    def test_step_reports_none_type_when_off_any_known_ground(self):
        step = TerrainFootstepReader.STEP_DISTANCE
        reader = make_reader([
            PlayerPose(Position(1000.0, 0.0, 1000.0), 0.0),
            PlayerPose(Position(1000.0 + step + 1.0, 0.0, 1000.0), 0.0),
        ])
        reader.poll_once()
        reader.poll_once()
        self.assertEqual(reader.tone_player.steps, [None])

    def test_realistic_walking_scale_delta_is_not_mistaken_for_a_jump(self):
        # Regression test for the live-tuning bug found 2026-07-29: a real
        # per-poll walking delta (~20 units, per the narrator's own field
        # log) must accumulate normally, not be discarded as a "large jump"
        # the way MAX_PLAUSIBLE_DELTA=8.0 previously did to ALL real
        # walking.
        reader = make_reader([
            PlayerPose(Position(0.0, 0.0, 0.0), 0.0),
            PlayerPose(Position(20.0, 0.0, 0.0), 0.0),
        ], ground_type=3)
        reader.poll_once()
        reader.poll_once()
        self.assertEqual(reader.tone_player.steps, [3])

    def test_large_one_frame_jump_resets_cadence_instead_of_bursting(self):
        # Simulates a teleport/warp/room transition: a huge displacement in
        # one poll must not produce a burst of steps once real movement
        # resumes afterward.
        reader = make_reader([
            PlayerPose(Position(0.0, 0.0, 0.0), 0.0),
            PlayerPose(Position(500.0, 0.0, 0.0), 0.0),  # large jump
            PlayerPose(Position(500.5, 0.0, 0.0), 0.0),  # tiny real move after
        ], ground_type=2)
        reader.poll_once()
        reader.poll_once()
        reader.poll_once()
        self.assertEqual(reader.tone_player.steps, [])

    def test_clear_resets_internal_state(self):
        reader = make_reader([PlayerPose(Position(0.0, 0.0, 0.0), 0.0)])
        reader.poll_once()
        reader._accumulated_distance = 1.0
        reader.clear("test")
        self.assertIsNone(reader._last_position)
        self.assertEqual(reader._accumulated_distance, 0.0)


class FakeMovementInput:
    def __init__(self, held=True):
        self.held = held

    def is_direction_held(self):
        return self.held


def make_blocked_reader(poses, wall_hit=None, input_held=True):
    reader = BlockedMovementReader(
        FakeMemory(0x8A), FakeProfile(), FakePoseSource(poses),
        FakeMovementInput(input_held),
        collision_dir="unused", room_codes={}, tone_player=RecordingTonePlayer(),
        logger=None,
    )
    triangles = [wall_hit] if wall_hit is not None else []
    reader._triangles_by_room[0x8A] = tuple(triangles)
    return reader


DEFAULT_WALL = wall_triangle((
    (-5.0, 0.0, -1.0), (5.0, 0.0, -1.0), (0.0, 10.0, -1.0),
))


class BlockedMovementReaderTests(unittest.TestCase):
    def test_stillness_without_input_held_never_fires(self):
        poses = [PlayerPose(Position(0.0, 0.0, 0.0), 0.0)] * 10
        reader = make_blocked_reader(poses, wall_hit=DEFAULT_WALL, input_held=False)
        for _ in range(10):
            reader.poll_once()
        self.assertEqual(reader.tone_player.blocked_calls, 0)

    def test_input_held_but_no_geometry_never_fires(self):
        poses = [PlayerPose(Position(0.0, 0.0, 0.0), 0.0)] * 10
        reader = make_blocked_reader(poses, wall_hit=None, input_held=True)
        for _ in range(10):
            reader.poll_once()
        self.assertEqual(reader.tone_player.blocked_calls, 0)

    def test_input_held_below_debounce_ticks_does_not_fire_yet(self):
        poses = [PlayerPose(Position(0.0, 0.0, 0.0), 0.0)] * 4
        reader = make_blocked_reader(poses, wall_hit=DEFAULT_WALL, input_held=True)
        for _ in range(4):
            reader.poll_once()
        self.assertEqual(reader.tone_player.blocked_calls, 0)

    def test_all_five_conditions_together_fire_exactly_once(self):
        poses = [PlayerPose(Position(0.0, 0.0, 0.0), 0.0)] * 10
        reader = make_blocked_reader(poses, wall_hit=DEFAULT_WALL, input_held=True)
        for _ in range(10):
            reader.poll_once()
        self.assertEqual(reader.tone_player.blocked_calls, 1)

    def test_releasing_input_resets_the_episode(self):
        reader = make_blocked_reader(
            [PlayerPose(Position(0.0, 0.0, 0.0), 0.0)] * 14,
            wall_hit=DEFAULT_WALL, input_held=True,
        )
        for _ in range(6):
            reader.poll_once()
        self.assertEqual(reader.tone_player.blocked_calls, 1)
        reader.movement_input_source.held = False
        for _ in range(2):
            reader.poll_once()
        reader.movement_input_source.held = True
        for _ in range(6):
            reader.poll_once()
        self.assertEqual(reader.tone_player.blocked_calls, 2)

    def test_material_direction_change_resets_the_episode(self):
        poses = (
            [PlayerPose(Position(0.0, 0.0, 0.0), 0.0)] * 6
            + [PlayerPose(Position(0.0, 0.0, 0.0), math.pi)] * 6
        )
        reader = make_blocked_reader(list(poses), wall_hit=DEFAULT_WALL, input_held=True)
        for _ in range(len(poses)):
            reader.poll_once()
        # facing pi (away from the wall at z=-1) should no longer detect the
        # wall at all -- confirms the reset also stops a stale re-fire.
        self.assertEqual(reader.tone_player.blocked_calls, 1)

    def test_movement_resuming_resets_the_episode(self):
        poses = (
            [PlayerPose(Position(0.0, 0.0, 0.0), 0.0)] * 6
            + [PlayerPose(Position(0.0, 0.0, 0.5), 0.0)]
            + [PlayerPose(Position(0.0, 0.0, 0.5), 0.0)] * 6
        )
        reader = make_blocked_reader(list(poses), wall_hit=DEFAULT_WALL, input_held=True)
        for _ in range(len(poses)):
            reader.poll_once()
        self.assertEqual(reader.tone_player.blocked_calls, 2)

    def test_clear_resets_internal_state(self):
        reader = make_blocked_reader(
            [PlayerPose(Position(0.0, 0.0, 0.0), 0.0)], wall_hit=DEFAULT_WALL)
        reader.poll_once()
        reader._qualifying_ticks = 3
        reader._episode_fired = True
        reader.clear("test")
        self.assertIsNone(reader._last_position)
        self.assertEqual(reader._qualifying_ticks, 0)
        self.assertFalse(reader._episode_fired)


class FakeWavePlayer:
    def __init__(self):
        self.calls = []

    def play(self, path, pan, pitch, gain):
        self.calls.append((path, pan, pitch, gain))


class TerrainTonePlayerTests(unittest.TestCase):
    def test_generates_step_and_blocked_wav_files_once(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            player = TerrainTonePlayer(FakeWavePlayer(), Path(tmp))
            self.assertTrue((Path(tmp) / "_terrain_step_base.wav").is_file())
            self.assertTrue((Path(tmp) / "_terrain_blocked_base.wav").is_file())

    def test_play_step_uses_centered_pan_and_type_dependent_pitch(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            wave_player = FakeWavePlayer()
            player = TerrainTonePlayer(wave_player, Path(tmp))
            player.play_step(3)
            [(path, pan, pitch, gain)] = wave_player.calls
            self.assertEqual(pan, 0.0)
            self.assertAlmostEqual(pitch, 1.0 + 0.12 * 3)

    def test_play_step_with_unknown_type_uses_neutral_pitch(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            wave_player = FakeWavePlayer()
            player = TerrainTonePlayer(wave_player, Path(tmp))
            player.play_step(None)
            [(path, pan, pitch, gain)] = wave_player.calls
            self.assertEqual(pitch, 1.0)

    def test_play_step_uses_the_named_step_gain(self):
        # Raised 50% (0.6 -> 0.9) at the project owner's request
        # 2026-08-10. Asserted against the constant, not the number, so
        # retuning stays a one-line change -- but the blocked cue keeps
        # its own separate, LOUDER level, which this must not have moved.
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            wave_player = FakeWavePlayer()
            player = TerrainTonePlayer(wave_player, Path(tmp))
            player.play_step(0)
            player.play_blocked()
            step_gain, blocked_gain = (call[3] for call in wave_player.calls)
            self.assertAlmostEqual(step_gain, TerrainTonePlayer.STEP_GAIN)
            self.assertGreater(step_gain, 0.6)
            self.assertNotAlmostEqual(blocked_gain, step_gain)

    def test_play_blocked_uses_the_blocked_wav(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            wave_player = FakeWavePlayer()
            player = TerrainTonePlayer(wave_player, Path(tmp))
            player.play_blocked()
            [(path, pan, pitch, gain)] = wave_player.calls
            self.assertEqual(path.name, "_terrain_blocked_base.wav")

    def test_real_footstep_sounds_are_used_when_available(self):
        import tempfile
        import wave as wave_module
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            asset_dir = Path(tmp) / "assets"
            sounds_dir = Path(tmp) / "footsteps"
            sounds_dir.mkdir()
            for name in ("a.wav", "b.wav"):
                with wave_module.open(str(sounds_dir / name), "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(22050)
                    handle.writeframes(b"\x00\x00" * 10)

            wave_player = FakeWavePlayer()
            player = TerrainTonePlayer(
                wave_player, asset_dir, footstep_sounds_dir=sounds_dir)
            names = set()
            for _ in range(30):
                player.play_step(0)
                names.add(wave_player.calls[-1][0].name)
            # Real sounds used (not the synthesized fallback), and random
            # selection actually varies across calls, not always the same
            # file -- 30 draws from 2 files makes both showing up
            # overwhelmingly likely if selection is real.
            self.assertEqual(names, {"a.wav", "b.wav"})

    def test_24bit_footstep_recordings_are_converted_and_playable(self):
        import struct
        import tempfile
        import wave as wave_module
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            asset_dir = Path(tmp) / "assets"
            sounds_dir = Path(tmp) / "footsteps"
            sounds_dir.mkdir()
            source_path = sounds_dir / "real.wav"
            # A real 24-bit recording, matching the project owner's actual
            # footstep files (stereo, 24-bit, 44.1kHz).
            frames = struct.pack("<3B", 0x00, 0x10, 0x02) * 4  # 4 stereo samples' worth of bytes, arbitrary
            with wave_module.open(str(source_path), "wb") as handle:
                handle.setnchannels(2)
                handle.setsampwidth(3)
                handle.setframerate(44100)
                handle.writeframesraw(frames)

            wave_player = FakeWavePlayer()
            player = TerrainTonePlayer(
                wave_player, asset_dir, footstep_sounds_dir=sounds_dir)
            [path] = player._step_paths
            self.assertNotEqual(path, source_path)
            with wave_module.open(str(path), "rb") as handle:
                self.assertEqual(handle.getsampwidth(), 2)
                self.assertEqual(handle.getnchannels(), 2)
                self.assertEqual(handle.getframerate(), 44100)

    def test_missing_footstep_sounds_dir_falls_back_to_synthesized_click(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            wave_player = FakeWavePlayer()
            player = TerrainTonePlayer(
                wave_player, Path(tmp),
                footstep_sounds_dir=Path(tmp) / "does_not_exist")
            player.play_step(0)
            [(path, pan, pitch, gain)] = wave_player.calls
            self.assertEqual(path.name, "_terrain_step_base.wav")


class LoadWalkModelTrianglesTests(unittest.TestCase):
    """Real fixture data. A full 177-room scan (2026-08-01) found 10 rooms
    with a genuinely empty CCD +0x24 slot -- 6 of which (`TEST000`-`TEST004`,
    `peopleViewer001`) are not real rooms at all -- and 3 more whose walk
    models contain a NaN normal on one or two individual triangles.

    Those 3 originally failed to parse entirely; investigation (2026-08-02)
    showed the vertices were valid and only the normal was NaN -- a
    degenerate triangle -- so the parser now skips the individual triangle
    instead of discarding the whole room. See
    `collision_probe.parse_walk_model_triangles`. Genuinely empty rooms must
    still load as an honest empty result rather than crashing the caller."""

    def _skip_if_missing(self, name):
        if not (REAL_COLLISION_DIR / f"{name}.ccd").is_file():
            raise unittest.SkipTest(f"real fixture not found: {name}.ccd")

    def test_room_with_a_genuinely_empty_walk_model_loads_as_empty(self):
        self._skip_if_missing("B1_6")
        cache = {}
        triangles = load_walk_model_triangles(
            REAL_COLLISION_DIR, {1: "B1_6"}, cache, 1,
            logging.getLogger("load-walk-model-test"))
        self.assertEqual(triangles, ())
        self.assertIn(1, cache)

    def test_degenerate_triangle_is_skipped_without_losing_the_whole_room(self):
        # M6_pc_1F holds 179 walk triangles, exactly one of which has a NaN
        # normal. Raising on it previously cost this room all routing; it
        # must now load the other 178 -- and it is a real 2-layer room, so
        # the layer machinery genuinely depends on this data.
        self._skip_if_missing("M6_pc_1F")
        cache = {}
        triangles = load_walk_model_triangles(
            REAL_COLLISION_DIR, {1: "M6_pc_1F"}, cache, 1,
            logging.getLogger("load-walk-model-test"))
        self.assertGreater(len(triangles), 100)
        self.assertTrue(
            all(math.isfinite(v) for t in triangles for vertex in t.vertices
                for v in vertex),
            "a non-finite vertex survived the skip")
        self.assertTrue(
            all(math.isfinite(v) for t in triangles for v in t.normal),
            "a non-finite normal survived the skip")
        layers = {t.layer_a for t in triangles} | {t.layer_b for t in triangles}
        self.assertEqual(layers, {0, 1})

    def test_every_real_room_parses_without_raising(self):
        # Whole-corpus guard: after the degenerate-triangle fix, no `.ccd`
        # file in the project should fail walk-model parsing outright.
        if not REAL_COLLISION_DIR.is_dir():
            raise unittest.SkipTest("real collision directory not present")
        from battle_narrator.collision_probe import parse_walk_model_triangles
        failures = []
        for path in sorted(REAL_COLLISION_DIR.glob("*.ccd")):
            try:
                parse_walk_model_triangles(path.read_bytes())
            except Exception as exc:
                failures.append(f"{path.name}: {exc}")
        self.assertEqual(failures, [], f"walk-model parse failures: {failures}")

    def test_room_with_no_matching_code_loads_as_empty(self):
        cache = {}
        triangles = load_walk_model_triangles(
            REAL_COLLISION_DIR, {}, cache, 999,
            logging.getLogger("load-walk-model-test"))
        self.assertEqual(triangles, ())


if __name__ == "__main__":
    unittest.main()
