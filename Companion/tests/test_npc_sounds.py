import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.npc_sounds import NPC, NPCSoundReader, Position


class Source:
    def __init__(self, npcs):
        self.items = npcs

    def player_position(self):
        return Position(0, 0, 0)

    def npcs(self):
        return self.items


class Player:
    def __init__(self):
        self.played = []

    def play(self, path):
        self.played.append(Path(path).name)


class Logger:
    def debug(self, *args):
        pass

    def info(self, *args):
        pass


def make_wave(path):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(1000)
        output.writeframes(b"\0\0" * 10)


class NPCSoundTests(unittest.TestCase):
    def test_visible_talking_npcs_receive_stable_sounds(self):
        with tempfile.TemporaryDirectory() as directory:
            sounds = [Path(directory) / f"{value}.wav" for value in range(3)]
            for sound in sounds:
                make_wave(sound)
            npcs = [
                NPC(141, 0, True, 1, Position(2, 0, 0)),
                NPC(141, 1, True, 2, Position(3, 0, 0)),
            ]
            player = Player()
            now = [0.0]
            reader = NPCSoundReader(
                Source(npcs), sounds, player, Logger(), clock=lambda: now[0])
            reader.poll_once()
            now[0] = 1
            reader.poll_once()
            self.assertEqual(len(player.played), 2)
            self.assertNotEqual(
                reader.sound_index(npcs[0]), reader.sound_index(npcs[1]))

    def test_hidden_silent_and_out_of_range_characters_do_not_play(self):
        with tempfile.TemporaryDirectory() as directory:
            sound = Path(directory) / "cue.wav"
            make_wave(sound)
            source = Source([
                NPC(1, 0, False, 1, Position(1, 0, 0)),
                NPC(1, 1, True, 0, Position(1, 0, 0)),
                NPC(1, 2, True, 1, Position(50, 0, 0)),
            ])
            player = Player()
            NPCSoundReader(source, [sound], player, Logger()).poll_once()
            self.assertEqual(player.played, [])

    def test_leaving_range_rearms_the_same_npc(self):
        with tempfile.TemporaryDirectory() as directory:
            sound = Path(directory) / "cue.wav"
            make_wave(sound)
            npc = NPC(1, 0, True, 1, Position(1, 0, 0))
            source, player = Source([npc]), Player()
            now = [0.0]
            reader = NPCSoundReader(
                source, [sound], player, Logger(), clock=lambda: now[0])
            reader.poll_once()
            source.items = []
            now[0] = 1
            reader.poll_once()
            source.items = [npc]
            now[0] = 2
            reader.poll_once()
            self.assertEqual(player.played, ["cue.wav", "cue.wav"])


if __name__ == "__main__":
    unittest.main()
