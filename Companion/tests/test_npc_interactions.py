import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator import npc_beacons
from battle_narrator.entity_sources import TalkHistory
from battle_narrator.npc_beacons import (
    NPC, NPCInteractionContext, NPCSoundReader, PlayerPose, Position,
)
from battle_narrator.speech import SpeechEventClass


class Source:
    def __init__(self, npc):
        self.npc = npc

    def player_pose(self):
        return PlayerPose(Position(0, 0, 0), 0)

    def npcs(self):
        return [self.npc]


class ListSource:
    """A source returning a fixed list of NPCs, for category-filter tests."""

    def __init__(self, npcs):
        self._npcs = npcs

    def player_pose(self):
        return PlayerPose(Position(0, 0, 0), 0)

    def npcs(self):
        return self._npcs


class Player:
    def play(self, *args):
        pass


class RecordingPlayer:
    def __init__(self):
        self.played = []

    def play(self, path, pan, pitch, gain):
        self.played.append((Path(path).name, pan, pitch, gain))

    def stop(self):
        pass


def write_silence_of(path, seconds, rate=8000):
    """A silent WAV of a specific duration, so scheduler tests can use the
    real clip lengths that caused the problem."""
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"\0\0" * int(rate * seconds))
    return path


def write_silence(path):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 10)
    return path


class Speech:
    def __init__(self):
        self.events = []

    def emit(self, event_class, text, deduplicate=False):
        self.events.append((event_class, text))


class Logger:
    def debug(self, *args): pass
    def info(self, *args): pass


def write_wav(path, width, channels=1, frames=200, rate=8000, amplitude=None):
    """Write a PCM WAV at an arbitrary bit depth.

    `wave` will not do this for us at 24-bit, so the sample bytes are packed
    by hand -- which is also what makes this an honest test of the decoder
    rather than a round-trip through the same helper it is verifying."""
    peak = (1 << (width * 8 - 1)) - 1
    amplitude = peak // 2 if amplitude is None else amplitude
    data = bytearray()
    for index in range(frames):
        value = amplitude if index % 2 else -amplitude
        for _ in range(channels):
            if width == 1:
                data.append(max(0, min(255, 128 + (value >> 8))))
            else:
                data.extend(int(value).to_bytes(width, "little", signed=True))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(bytes(data))
    return path


class FakeSound:
    def __init__(self, buffer):
        self.buffer = buffer

    def play(self):
        return None


class FakeMixer:
    """Stands in for pygame.mixer so rendering can be tested headlessly."""

    def __init__(self):
        self.sounds = []

    def get_init(self):
        return True

    def Sound(self, buffer):
        sound = FakeSound(buffer)
        self.sounds.append(sound)
        return sound


class WaveFormatTests(unittest.TestCase):
    """The passive beacon sounds are 24-bit, and the player originally read
    only 16-bit. That combination crashed the narrator outright the first
    time a beacon came into range (live, 2026-08-05) -- not at startup, but
    minutes into play, from inside the poll loop."""

    def test_every_supported_width_decodes_to_the_16_bit_scale(self):
        for width in npc_beacons.SUPPORTED_SAMPLE_WIDTHS:
            with tempfile.TemporaryDirectory() as directory:
                path = write_wav(Path(directory) / "s.wav", width)
                with wave.open(str(path), "rb") as source:
                    frames = source.readframes(source.getnframes())
                samples = npc_beacons._decode_pcm(frames, width)
                self.assertEqual(len(samples), 200, f"{width * 8}-bit count")
                self.assertTrue(
                    all(-32768 <= s <= 32767 for s in samples),
                    f"{width * 8}-bit out of 16-bit range")
                self.assertTrue(
                    any(s != 0 for s in samples),
                    f"{width * 8}-bit decoded to silence")

    def test_widths_agree_on_amplitude(self):
        """A 24-bit and a 16-bit clip of the same signal must come out
        equally loud -- otherwise swapping a sound file silently changes
        its volume."""
        decoded = {}
        for width in (2, 3, 4):
            with tempfile.TemporaryDirectory() as directory:
                peak = (1 << (width * 8 - 1)) - 1
                path = write_wav(
                    Path(directory) / "s.wav", width, amplitude=peak // 2)
                with wave.open(str(path), "rb") as source:
                    frames = source.readframes(source.getnframes())
                decoded[width] = npc_beacons._decode_pcm(frames, width)
        for width in (3, 4):
            self.assertAlmostEqual(
                max(decoded[width]), max(decoded[2]), delta=2,
                msg=f"{width * 8}-bit differs in level from 16-bit")

    def test_eight_bit_is_treated_as_unsigned(self):
        # 8-bit WAV is the one depth stored unsigned, with 128 as silence.
        self.assertEqual(npc_beacons._decode_pcm(bytes([128, 128]), 1), [0, 0])
        self.assertGreater(npc_beacons._decode_pcm(bytes([200]), 1)[0], 0)
        self.assertLess(npc_beacons._decode_pcm(bytes([50]), 1)[0], 0)

    def test_unsupported_width_is_rejected_clearly(self):
        with self.assertRaises(ValueError) as caught:
            npc_beacons._decode_pcm(b"\0" * 10, 5)
        self.assertIn("sample width", str(caught.exception))

    def test_check_playable_accepts_the_real_beacon_sounds(self):
        sounds = npc_beacons.resolve_sound_dir(
            Path(npc_beacons.__file__).parents[1])
        for category, filename in npc_beacons.PASSIVE_BEACON_SOUND_FILES.items():
            npc_beacons.check_playable(sounds / filename)

    def test_check_playable_rejects_an_empty_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_wav(Path(directory) / "s.wav", 2, frames=0)
            with self.assertRaises(ValueError):
                npc_beacons.check_playable(path)

    def test_check_playable_rejects_too_many_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_wav(Path(directory) / "s.wav", 2, channels=3)
            with self.assertRaises(ValueError):
                npc_beacons.check_playable(path)

    def test_player_renders_a_24_bit_source(self):
        # The exact case that crashed: render must succeed and produce
        # 16-bit stereo output.
        with tempfile.TemporaryDirectory() as directory:
            path = write_wav(Path(directory) / "s.wav", 3, channels=2)
            mixer = FakeMixer()
            npc_beacons.SpatialWavePlayer(mixer).play(path, 0.0, 1.0, 0.5)
            self.assertEqual(len(mixer.sounds), 1)
            buffer = mixer.sounds[0].buffer
            self.assertTrue(buffer)
            self.assertEqual(len(buffer) % 4, 0, "expected 16-bit stereo")

    def test_player_renders_every_supported_width(self):
        for width in npc_beacons.SUPPORTED_SAMPLE_WIDTHS:
            with tempfile.TemporaryDirectory() as directory:
                path = write_wav(Path(directory) / "s.wav", width, channels=2)
                mixer = FakeMixer()
                npc_beacons.SpatialWavePlayer(mixer).play(path, 0.5, 1.0, 0.5)
                self.assertTrue(
                    mixer.sounds and mixer.sounds[0].buffer,
                    f"{width * 8}-bit rendered nothing")


class NPCInteractionTests(unittest.TestCase):
    def test_static_story_record_without_live_actor_does_not_announce(self):
        with tempfile.TemporaryDirectory() as directory:
            sound = Path(directory) / "sound.wav"
            with wave.open(str(sound), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(b"\0\0" * 10)
            stale = NPC(
                0xA2, 3, True, 1, Position(0, 0, 0),
                name_id=100, interaction_radius=10,
                live_actor_present=False)
            speech = Speech()
            context = npc_beacons.NPCInteractionContext()
            reader = NPCSoundReader(
                Source(stale), [sound], Player(), Logger(), speech=speech,
                entity_names={100: "Mirror B."},
                interaction_context=context)

            reader.poll_once()

            self.assertEqual(speech.events, [])
            self.assertIsNone(context.name)
            self.assertIsNone(context.identity)

    def test_entering_exact_interaction_radius_announces_name_once(self):
        with tempfile.TemporaryDirectory() as directory:
            sound = Path(directory) / "sound.wav"
            with wave.open(str(sound), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(b"\0\0" * 10)
            npc = NPC(
                1, 2, True, 1, Position(4, 0, 0),
                name_id=3, interaction_radius=5)
            speech = Speech()
            reader = NPCSoundReader(
                Source(npc), [sound], Player(), Logger(),
                speech=speech, entity_names={3: "Krane"})
            reader.poll_once()
            reader.poll_once()
            self.assertEqual(speech.events, [
                (SpeechEventClass.NPC_INTERACTION,
                 "Krane, interaction available.")
            ])

    def test_nearest_in_range_entity_change_announces_new_name(self):
        with tempfile.TemporaryDirectory() as directory:
            sound = Path(directory) / "sound.wav"
            with wave.open(str(sound), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(b"\0\0" * 10)
            first = NPC(1, 1, True, 1, Position(1, 0, 0), 3, 5)
            second = NPC(1, 2, True, 1, Position(2, 0, 0), 4, 5)
            source = Source(first)
            source.npcs = lambda: [first, second]
            speech = Speech()
            reader = NPCSoundReader(
                source, [sound], Player(), Logger(), speech=speech,
                entity_names={3: "Krane", 4: "Lily"},
            )
            reader.poll_once()
            first_far = NPC(1, 1, True, 1, Position(2, 0, 0), 3, 5)
            second_near = NPC(1, 2, True, 1, Position(1, 0, 0), 4, 5)
            source.npcs = lambda: [first_far, second_near]
            reader.poll_once()
            self.assertEqual(
                [event[1] for event in speech.events],
                [
                    "Krane, interaction available.",
                    "Lily, interaction available.",
                ],
            )

    def test_passive_beacon_tracks_the_navigation_curve(self):
        """Assert the RELATIONSHIP, not a baked-in number -- retuning the
        navigation curve must carry the beacons with it rather than
        silently changing the ratio between them."""
        pose = PlayerPose(Position(0, 0, 0), 0)
        for distance, proximity in ((0, 1.0), (60, 0.5)):
            npc = NPC(1, 0, True, 1, Position(distance, 0, 0))
            gain = NPCSoundReader.spatial_values(pose, npc, 120)[3]
            self.assertAlmostEqual(
                gain,
                npc_beacons.PASSIVE_BEACON_GAIN_SCALE
                * npc_beacons.navigation_gain(proximity),
                msg=f"distance {distance}")

    def test_untrimmed_categories_play_at_full_volume(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        for category in ("npc", "item", "door", "pokemart"):
            npc = NPC(1, 0, True, 1, Position(0, 0, 0), category=category)
            self.assertAlmostEqual(
                NPCSoundReader.spatial_values(pose, npc, 120)[3],
                npc_beacons.navigation_gain(1.0),
                msg=category)

    def test_warps_are_trimmed(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        warp = NPC(1, 0, True, 1, Position(0, 0, 0), category="warp")
        other = NPC(1, 1, True, 1, Position(0, 0, 0), category="npc")
        warp_gain = NPCSoundReader.spatial_values(pose, warp, 120)[3]
        other_gain = NPCSoundReader.spatial_values(pose, other, 120)[3]
        self.assertAlmostEqual(
            warp_gain,
            other_gain * npc_beacons.PASSIVE_BEACON_CATEGORY_GAIN["warp"])
        self.assertLess(warp_gain, other_gain)

    def test_category_trim_applies_at_every_distance(self):
        # A trim is a mix level, so it must scale the whole curve rather
        # than only apply when standing on the entity.
        pose = PlayerPose(Position(0, 0, 0), 0)
        for distance in (0, 30, 60, 119):
            warp = NPC(1, 0, True, 1, Position(distance, 0, 0), category="warp")
            other = NPC(1, 1, True, 1, Position(distance, 0, 0), category="npc")
            self.assertAlmostEqual(
                NPCSoundReader.spatial_values(pose, warp, 120)[3],
                NPCSoundReader.spatial_values(pose, other, 120)[3]
                * npc_beacons.PASSIVE_BEACON_CATEGORY_GAIN["warp"],
                msg=f"distance {distance}")

    def test_passive_beacon_stays_audible_at_maximum_range(self):
        # The 0.18 proximity floor: an entity at the edge of range should
        # still be faintly audible, not silent. That is the point of an
        # ambient beacon -- it tells you something is out there.
        pose = PlayerPose(Position(0, 0, 0), 0)
        far = NPC(1, 0, True, 1, Position(120, 0, 0))
        gain = NPCSoundReader.spatial_values(pose, far, 120)[3]
        self.assertGreater(gain, 0.0)
        self.assertAlmostEqual(
            gain,
            npc_beacons.PASSIVE_BEACON_GAIN_SCALE
            * npc_beacons.navigation_gain(0.18))

    def test_every_category_trim_names_a_real_category(self):
        # A typo here would silently do nothing at all.
        self.assertTrue(
            set(npc_beacons.PASSIVE_BEACON_CATEGORY_GAIN)
            <= set(npc_beacons.PASSIVE_BEACON_SOUND_FILES))

    def test_no_beacon_exceeds_full_navigation_volume(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        for category in npc_beacons.PASSIVE_BEACON_SOUND_FILES:
            npc = NPC(1, 0, True, 1, Position(0, 0, 0), category=category)
            self.assertLessEqual(
                NPCSoundReader.spatial_values(pose, npc, 120)[3],
                npc_beacons.navigation_gain(1.0) + 1e-9, msg=category)

    def test_every_named_beacon_category_has_a_sound(self):
        # The categories the project owner asked for ("elevator" added
        # 2026-08-10 with sounds/elevators.wav). A category listed here
        # with no file would silently fall back to the generic NPC tone.
        #
        # "pokemart" REMOVED 2026-08-18 with the role labelling that was
        # the only thing producing it -- a room-id guess, so every NPC in a
        # Mart sounded like the clerk. `sounds/pokemarts.wav` is still in
        # the repo; restoring the category is one line in
        # PASSIVE_BEACON_SOUND_FILES once a clerk can actually be detected.
        self.assertEqual(
            set(npc_beacons.PASSIVE_BEACON_SOUND_FILES),
            {"npc", "item", "door", "warp", "elevator"})
        self.assertEqual(
            len(set(npc_beacons.PASSIVE_BEACON_SOUND_FILES.values())),
            len(npc_beacons.PASSIVE_BEACON_SOUND_FILES),
            "each category needs its OWN sound; duplicates make two "
            "different kinds of thing indistinguishable")

    def test_named_beacon_sound_files_exist_on_disk(self):
        sounds = npc_beacons.resolve_sound_dir(
            Path(npc_beacons.__file__).parents[1])
        for category, filename in npc_beacons.PASSIVE_BEACON_SOUND_FILES.items():
            self.assertTrue(
                (sounds / filename).is_file(),
                f"{category} beacon sound {filename} missing from {sounds}")

    def test_categories_without_a_sound_are_not_beaconed(self):
        """A healing spot reaching the reader has no sound of its own.
        Falling back to the NPC tone would cue the player toward the wrong
        kind of thing, which is worse than staying silent because they
        would act on it."""
        with tempfile.TemporaryDirectory() as directory:
            path = write_silence(Path(directory) / "beep.wav")
            player = RecordingPlayer()
            source = ListSource([
                NPC(1, 0, True, 1, Position(1, 0, 0), category="healing"),
                NPC(1, 1, True, 1, Position(2, 0, 0), category="pokebox"),
            ])
            NPCSoundReader(
                source, [path], player, Logger(),
                category_sound_paths={"npc": path, "door": path},
                beacon_categories=("npc", "door")).poll_once()
            self.assertEqual(player.played, [])

    def test_allowed_categories_are_still_beaconed(self):
        with tempfile.TemporaryDirectory() as directory:
            npc_sound = write_silence(Path(directory) / "npcs.wav")
            door_sound = write_silence(Path(directory) / "doors.wav")
            player = RecordingPlayer()
            source = ListSource([
                NPC(1, 0, True, 1, Position(1, 0, 0), category="door"),
            ])
            NPCSoundReader(
                source, [npc_sound], player, Logger(),
                category_sound_paths={"npc": npc_sound, "door": door_sound},
                beacon_categories=("npc", "door")).poll_once()
            self.assertEqual(len(player.played), 1)
            # ...and with ITS OWN sound, not the generic NPC one.
            self.assertEqual(player.played[0][0], "doors.wav")

    def test_elevators_beacon_with_their_own_sound(self):
        # 2026-08-10: elevators were the standing example of a category
        # held SILENT for want of a file. sounds/elevators.wav exists now,
        # so they sound -- and with their own clip, since an elevator that
        # sounded like a warp would be a wrong cue, not a missing one.
        with tempfile.TemporaryDirectory() as directory:
            npc_sound = write_silence(Path(directory) / "npcs.wav")
            elevator_sound = write_silence(Path(directory) / "elevators.wav")
            player = RecordingPlayer()
            source = ListSource([
                NPC(1, 0, True, 1, Position(1, 0, 0), category="elevator"),
            ])
            NPCSoundReader(
                source, [npc_sound], player, Logger(),
                category_sound_paths={
                    "npc": npc_sound, "elevator": elevator_sound},
                beacon_categories=("npc", "elevator")).poll_once()
            self.assertEqual(
                [entry[0] for entry in player.played], ["elevators.wav"])

    def test_no_category_restriction_keeps_the_original_behaviour(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_silence(Path(directory) / "beep.wav")
            player = RecordingPlayer()
            source = ListSource([
                NPC(1, 0, True, 1, Position(1, 0, 0), category="elevator"),
            ])
            NPCSoundReader(
                source, [path], player, Logger()).poll_once()
            self.assertEqual(len(player.played), 1)

    def test_interaction_context_identity_exists_before_any_npc_resolves(self):
        """Dialogue from a non-NPC source (a sign, a scripted event) reaches
        dialogue_speaker_name() without NPCSoundReader having ever resolved an
        NPC, so `identity` must already exist. It previously did not, and
        reading a sign crashed the narrator with AttributeError."""
        self.assertIsNone(NPCInteractionContext().identity)

    def test_talk_history_mark_accepts_the_unset_identity(self):
        """TalkHistory.mark() is the sole consumer of `identity`; the default
        has to be a value it already tolerates."""
        history = TalkHistory(flag_reader=None)
        history.mark(NPCInteractionContext().identity)
        self.assertEqual(history._talked, set())


if __name__ == "__main__":
    unittest.main()
