import logging
import unittest
from pathlib import Path

from battle_narrator.settings import (
    Sound, SettingsStore, VALUELESS_KINDS, build_categories,
)
from battle_narrator.settings_menu import SettingsMenu
from battle_narrator.sound_library import (
    CUE_ORDER, SoundCue, SoundLibrary, build_cues,
)


class Player:
    def __init__(self):
        self.calls = []
        self.fail = False

    def play(self, path, pan, pitch, gain):
        if self.fail:
            raise RuntimeError("audio device gone")
        self.calls.append((Path(path).name, pan, pitch, gain))


class Capture:
    def __init__(self):
        self.menu_open = False
        self.events = []

    def poll(self):
        return list(self.events)

    def discard(self):
        self.events = []


class Speech:
    def __init__(self):
        self.calls = []

    def emit(self, event, text, deduplicate=False, interrupt=None):
        self.calls.append(text)


def cue(key="beacon.item", label="Item beacon", description="An item.",
        path="items.wav", gain=1.0):
    return SoundCue(key, label, description, Path(path), gain=gain)


class BuildCuesTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("sound-library-test")

    def test_entries_follow_the_catalogue_order_not_the_dict_order(self):
        paths = {"blocked": "b.wav", "beacon.item": "i.wav",
                 "beacon.npc": "n.wav"}
        cues = build_cues(paths, self.logger, check=lambda path: None)
        self.assertEqual(
            [entry.key for entry in cues],
            ["beacon.npc", "beacon.item", "blocked"])

    def test_every_catalogue_key_has_a_label_and_a_description(self):
        paths = {key: f"{key}.wav" for key in CUE_ORDER}
        cues = build_cues(paths, self.logger, check=lambda path: None)
        self.assertEqual(len(cues), len(CUE_ORDER))
        for entry in cues:
            self.assertTrue(entry.label)
            self.assertTrue(entry.description)

    def test_an_unusable_file_drops_only_its_own_entry(self):
        def check(path):
            if path.name == "broken.wav":
                raise ValueError("8-bit WAV")

        cues = build_cues(
            {"beacon.npc": "n.wav", "beacon.item": "broken.wav"},
            self.logger, check=check)
        self.assertEqual([entry.key for entry in cues], ["beacon.npc"])

    def test_a_missing_file_drops_only_its_own_entry(self):
        def check(path):
            if path.name == "gone.wav":
                raise FileNotFoundError(path)

        cues = build_cues(
            {"beacon.npc": "gone.wav", "beacon.item": "i.wav"},
            self.logger, check=check)
        self.assertEqual([entry.key for entry in cues], ["beacon.item"])

    def test_an_unknown_key_is_ignored(self):
        cues = build_cues(
            {"not.a.cue": "x.wav"}, self.logger, check=lambda path: None)
        self.assertEqual(cues, ())

    def test_a_per_cue_gain_is_carried_through(self):
        cues = build_cues(
            {"beacon.warp": "w.wav"}, self.logger,
            gains={"beacon.warp": 0.2}, check=lambda path: None)
        self.assertEqual(cues[0].gain, 0.2)


class SoundLibraryTests(unittest.TestCase):
    def setUp(self):
        self.player = Player()
        self.built = 0
        self.library = SoundLibrary(
            [cue(), cue(key="beacon.warp", path="warps.wav", gain=0.2)],
            self._make_player, logging.getLogger("sound-library-test"))

    def _make_player(self):
        self.built += 1
        return self.player

    def test_no_audio_device_is_touched_until_something_is_played(self):
        self.assertEqual(self.built, 0)
        self.library.play("beacon.item")
        self.assertEqual(self.built, 1)
        self.library.play("beacon.warp")
        self.assertEqual(self.built, 1)

    def test_playing_uses_the_cue_own_gain_centred_and_unpitched(self):
        self.assertTrue(self.library.play("beacon.warp"))
        self.assertEqual(self.player.calls, [("warps.wav", 0.0, 1.0, 0.2)])

    def test_an_unknown_key_plays_nothing(self):
        self.assertFalse(self.library.play("nope"))
        self.assertEqual(self.player.calls, [])

    def test_a_playback_failure_is_contained(self):
        self.player.fail = True
        self.assertFalse(self.library.play("beacon.item"))


class SoundLibraryMenuTests(unittest.TestCase):
    def setUp(self):
        self.player = Player()
        self.library = SoundLibrary(
            [cue(key="beacon.warp", label="Warp beacon",
                 description="A warp: stairs, or a doorway.",
                 path="warps.wav", gain=0.2)],
            lambda: self.player, logging.getLogger("sound-library-test"))
        self.store = SettingsStore(
            build_categories(sound_library=self.library))
        self.speech = Speech()
        self.menu = SettingsMenu(
            self.store, Capture(), self.speech,
            logging.getLogger("sound-library-test"))
        self.menu.open = True
        self.menu.index = len(self.menu.entries) - 1

    def test_the_library_is_the_last_category(self):
        category, item = self.menu.entries[-1]
        self.assertEqual(category.title, "Sound library")
        self.assertIsInstance(item, Sound)

    def test_an_empty_library_contributes_no_heading(self):
        store = SettingsStore(build_categories())
        menu = SettingsMenu(
            store, Capture(), Speech(),
            logging.getLogger("sound-library-test"))
        self.assertNotIn(
            "Sound library",
            [category.title for _index, category in menu._category_bounds()])

    def test_focus_speaks_the_label_and_what_the_cue_means(self):
        self.assertEqual(
            self.menu._entry_text(include_heading=True),
            "Sound library. Warp beacon, press enter to play. "
            "A warp: stairs, or a doorway.")

    def test_enter_plays_the_sound_and_says_nothing_over_it(self):
        self.menu._activate()
        self.assertEqual(self.player.calls, [("warps.wav", 0.0, 1.0, 0.2)])
        self.assertEqual(self.speech.calls, [])

    def test_arrows_do_not_play_and_do_not_store_a_value(self):
        self.menu._adjust(1)
        self.assertEqual(self.player.calls, [])
        self.assertEqual(len(self.speech.calls), 1)
        self.assertNotIn("library.beacon.warp", self.store.values)

    def test_every_entry_plays_its_own_sound_not_the_last_one(self):
        library = SoundLibrary(
            [cue(key="beacon.npc", path="npcs.wav"),
             cue(key="beacon.item", path="items.wav")],
            lambda: self.player, logging.getLogger("sound-library-test"))
        store = SettingsStore(build_categories(sound_library=library))
        menu = SettingsMenu(
            store, Capture(), Speech(),
            logging.getLogger("sound-library-test"))
        menu.open = True
        for offset, expected in ((2, "npcs.wav"), (1, "items.wav")):
            menu.index = len(menu.entries) - offset
            menu._activate()
        self.assertEqual(
            [name for name, *_rest in self.player.calls],
            ["npcs.wav", "items.wav"])

    def test_sound_entries_are_never_saved(self):
        self.assertIn("sound", VALUELESS_KINDS)
        self.store.load()
        self.assertNotIn("library.beacon.warp", self.store.values)


if __name__ == "__main__":
    unittest.main()
