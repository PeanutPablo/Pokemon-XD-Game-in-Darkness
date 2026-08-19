import json
import logging
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

from battle_narrator import npc_beacons
from battle_narrator.entity_nav import EntityNavigator
from battle_narrator.key_capture import (
    KeyEvent, LowLevelKeyCapture, MenuKeyPolicy, VK_DOWN, VK_END, VK_ESCAPE,
    VK_F1, VK_H, VK_HOME, VK_LEFT, VK_RETURN, VK_RIGHT, VK_SPACE, VK_UP,
    WM_KEYDOWN, WM_KEYUP,
)
from battle_narrator.phase1b_lifecycle import LifecycleController
from battle_narrator.settings import (
    Category, Info, Number, SettingsStore, Toggle, build_categories,
    spoken_chord,
)
from battle_narrator.settings_menu import SettingsMenu
from battle_narrator.speech import SpeechEventClass


class Speech:
    def __init__(self):
        self.calls = []

    def emit(self, event, text, deduplicate=False, interrupt=None):
        self.calls.append((event, text, interrupt))

    @property
    def spoken(self):
        return [text for _, text, _ in self.calls]

    @property
    def last(self):
        return self.calls[-1][1] if self.calls else None


class Capture:
    """Stands in for LowLevelKeyCapture: the menu only ever drains it and
    tells it whether it is open."""

    def __init__(self):
        self.queued = []
        self.menu_open = False
        self.discarded = 0

    def press(self, vk, shift=False):
        self.queued.append(KeyEvent(vk, shift=shift))

    def poll(self):
        drained, self.queued = self.queued, []
        return drained

    def discard(self):
        self.discarded += 1
        self.queued = []


class Controller:
    """A stand-in for the lifecycle: appliers only ever getattr readers off
    it, and every one of them tolerates a missing reader."""

    def __init__(self, **readers):
        for name, reader in readers.items():
            setattr(self, name, reader)


def simple_categories():
    return (
        Category("Sounds", (
            Toggle("sounds.beacons", "Entity beacons", True),
            Number("sounds.volume", "Beacon volume", 0.5, 0.0, 1.0, 0.25,
                   unit="percent"),
        )),
        Category("Speech", (
            Toggle("speech.rooms", "Room announcements", True),
        )),
        Category("Hotkeys", (
            Info("hotkeys.0", "Money check", "control plus M"),
        )),
    )


def menu(categories=None, path=None, speech=None, controller=None):
    store = SettingsStore(
        categories or simple_categories(), path=path,
        logger=logging.getLogger("settings-test"))
    capture = Capture()
    return SettingsMenu(
        store, capture, speech or Speech(),
        logging.getLogger("settings-test"), controller), store, capture


class SettingsValueTests(unittest.TestCase):
    def test_toggle_speaks_on_and_off(self):
        toggle = Toggle("k", "Label", True)
        self.assertEqual(toggle.speak_value(True), "on")
        self.assertEqual(toggle.speak_value(False), "off")

    def test_percent_number_is_spoken_as_whole_percent(self):
        number = Number("k", "Label", 0.85, 0.0, 1.0, 0.05, unit="percent")
        self.assertEqual(number.speak_value(0.85), "85 percent")

    def test_seconds_are_singular_at_one(self):
        number = Number("k", "L", 1.0, 0.5, 5.0, 0.5, unit="seconds")
        self.assertEqual(number.speak_value(1.0), "1 second")
        self.assertEqual(number.speak_value(1.5), "1.5 seconds")

    def test_plain_numbers_drop_a_trailing_zero(self):
        number = Number("k", "L", 120.0, 40.0, 240.0, 10.0)
        self.assertEqual(number.speak_value(120.0), "120")

    def test_stepping_stays_inside_the_range(self):
        number = Number("k", "L", 1.0, 0.0, 1.0, 0.25)
        self.assertEqual(number.adjust(1.0, 1), 1.0)
        self.assertEqual(number.adjust(0.0, -1), 0.0)

    def test_repeated_steps_do_not_accumulate_float_dust(self):
        number = Number("k", "L", 0.0, 0.0, 1.0, 0.05)
        value = 0.0
        for _ in range(6):
            value = number.adjust(value, 1)
        self.assertEqual(value, 0.3)

    def test_coerce_clamps_a_stored_value_from_outside_the_range(self):
        number = Number("k", "L", 0.5, 0.0, 1.0, 0.05)
        self.assertEqual(number.coerce(9.0), 1.0)
        self.assertEqual(number.coerce("nonsense"), 0.5)

    def test_spoken_chord_expands_modifier_names(self):
        self.assertEqual(
            spoken_chord("ctrl+shift+period"),
            "control plus shift plus period")
        self.assertEqual(spoken_chord("ctrl+h"), "control plus H")


class SettingsStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "companion_settings.json"
        self.addCleanup(self.directory.cleanup)

    def store(self):
        return SettingsStore(
            simple_categories(), path=self.path,
            logger=logging.getLogger("settings-test"))

    def test_defaults_before_anything_is_stored(self):
        self.assertTrue(self.store().load().get("sounds.beacons"))

    def test_saved_values_survive_a_reload(self):
        store = self.store()
        store.set("sounds.volume", 0.25)
        self.assertEqual(self.store().load().get("sounds.volume"), 0.25)

    def test_setup_written_keys_are_preserved(self):
        self.path.write_text(
            json.dumps({"dolphin_exe": "D:/Dolphin.exe"}), encoding="utf-8")
        self.store().set("sounds.beacons", False)
        document = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(document["dolphin_exe"], "D:/Dolphin.exe")
        self.assertFalse(document["accessibility"]["sounds.beacons"])

    def test_unknown_stored_keys_are_ignored(self):
        self.path.write_text(
            json.dumps({"accessibility": {"sounds.retired": 1}}),
            encoding="utf-8")
        store = self.store().load()
        self.assertNotIn("sounds.retired", store.values)

    def test_a_corrupt_file_falls_back_to_defaults(self):
        self.path.write_text("{ not json", encoding="utf-8")
        self.assertTrue(self.store().load().get("sounds.beacons"))

    def test_an_unwritable_path_reports_once_and_keeps_the_value(self):
        failures = []
        store = SettingsStore(
            simple_categories(),
            path=Path(self.directory.name) / "missing" / "dir" / "s.json",
            logger=logging.getLogger("settings-test"),
            on_save_error=failures.append)
        store.set("sounds.beacons", False)
        store.set("sounds.volume", 0.25)
        self.assertEqual(len(failures), 1)
        self.assertFalse(store.get("sounds.beacons"))

    def test_enabled_defaults_to_true_for_an_unknown_feature(self):
        self.assertTrue(self.store().enabled("sounds.from_the_future"))


class SettingsApplicationTests(unittest.TestCase):
    """The appliers, against the real reader attributes they target."""

    def setUp(self):
        self.original_gain = npc_beacons.PASSIVE_BEACON_GAIN_SCALE
        self.original_category = dict(npc_beacons.PASSIVE_BEACON_CATEGORY_GAIN)

        def restore():
            npc_beacons.PASSIVE_BEACON_GAIN_SCALE = self.original_gain
            npc_beacons.PASSIVE_BEACON_CATEGORY_GAIN.clear()
            npc_beacons.PASSIVE_BEACON_CATEGORY_GAIN.update(
                self.original_category)

        self.addCleanup(restore)
        self.store = SettingsStore(
            build_categories(), logger=logging.getLogger("settings-test"))

    def test_beacon_volume_reaches_the_gain_the_beacons_actually_read(self):
        self.store.set("sounds.beacon_volume", 0.25, Controller())
        self.assertEqual(npc_beacons.PASSIVE_BEACON_GAIN_SCALE, 0.25)

    def test_warp_trim_is_per_category(self):
        self.store.set("sounds.warp_beacon_volume", 0.1, Controller())
        self.assertEqual(
            npc_beacons.PASSIVE_BEACON_CATEGORY_GAIN["warp"], 0.1)

    def test_footstep_volume_reaches_the_shared_tone_player(self):
        class TonePlayer:
            STEP_GAIN = 0.9

        class Reader:
            def __init__(self, player):
                self.tone_player = player

        player = TonePlayer()
        controller = Controller(
            terrain_footstep_reader=Reader(player),
            blocked_movement_reader=Reader(player))
        self.store.set("sounds.footstep_volume", 0.5, controller)
        self.assertEqual(player.STEP_GAIN, 0.5)

    def test_guide_settings_reach_both_guide_modes(self):
        class Guide:
            max_distance = 120.0
            arrival_distance = 4.0

        class Modes:
            def __init__(self):
                self.beacon = Guide()
                self.navigation = Guide()

        modes = Modes()
        controller = Controller(audio_guide_reader=modes)
        self.store.set("navigation.guide_range", 80.0, controller)
        self.store.set("navigation.arrival_distance", 6.0, controller)
        self.assertEqual(modes.beacon.max_distance, 80.0)
        self.assertEqual(modes.navigation.max_distance, 80.0)
        self.assertEqual(modes.beacon.arrival_distance, 6.0)
        self.assertEqual(modes.navigation.arrival_distance, 6.0)

    def test_applying_with_no_readers_yet_is_harmless(self):
        self.store.apply_all(Controller())

    def test_applying_with_no_controller_at_all_is_harmless(self):
        self.store.apply_all(None)

    def test_a_failing_applier_does_not_escape(self):
        class Exploding:
            @property
            def max_distance(self):
                raise RuntimeError("boom")

            @max_distance.setter
            def max_distance(self, value):
                raise RuntimeError("boom")

        self.store.set(
            "sounds.beacon_range", 60.0,
            Controller(npc_sound_reader=Exploding()))
        self.assertEqual(self.store.get("sounds.beacon_range"), 60.0)


class SettingsMenuNavigationTests(unittest.TestCase):
    def setUp(self):
        self.speech = Speech()
        self.menu, self.store, self.capture = menu(speech=self.speech)

    def press(self, vk, shift=False):
        self.capture.press(vk, shift=shift)
        self.menu.poll_once()

    def test_f1_opens_and_announces_the_first_item_with_its_heading(self):
        self.press(VK_F1)
        self.assertTrue(self.menu.open)
        self.assertTrue(self.capture.menu_open)
        self.assertIn("Sounds. Entity beacons, on.", self.speech.last)

    def test_the_instructions_are_spoken_only_on_the_first_open(self):
        self.press(VK_F1)
        self.assertIn("left and right to change", self.speech.last)
        self.press(VK_F1)
        self.press(VK_F1)
        self.assertNotIn("left and right to change", self.speech.last)

    def test_f1_again_closes_and_releases_the_keys(self):
        self.press(VK_F1)
        self.press(VK_F1)
        self.assertFalse(self.menu.open)
        self.assertFalse(self.capture.menu_open)
        self.assertEqual(self.speech.last, "Settings closed.")

    def test_escape_closes(self):
        self.press(VK_F1)
        self.press(VK_ESCAPE)
        self.assertFalse(self.menu.open)

    def test_keys_do_nothing_while_the_menu_is_closed(self):
        self.press(VK_DOWN)
        self.assertEqual(self.speech.calls, [])

    def test_down_moves_one_item_without_repeating_the_heading(self):
        self.press(VK_F1)
        self.press(VK_DOWN)
        self.assertEqual(self.speech.last, "Beacon volume, 50 percent.")

    def test_crossing_into_a_new_category_announces_its_heading(self):
        self.press(VK_F1)
        self.press(VK_DOWN)
        self.press(VK_DOWN)
        self.assertEqual(
            self.speech.last, "Speech. Room announcements, on.")

    def test_the_list_stops_at_the_top_instead_of_wrapping(self):
        self.press(VK_F1)
        self.press(VK_UP)
        self.assertEqual(
            self.speech.last, "Top of list. Entity beacons, on.")

    def test_the_list_stops_at_the_end(self):
        self.press(VK_F1)
        self.press(VK_END)
        self.press(VK_DOWN)
        self.assertTrue(self.speech.last.startswith("End of list."))

    def test_home_and_end_jump_to_the_ends(self):
        self.press(VK_F1)
        self.press(VK_END)
        self.assertEqual(
            self.speech.last, "Hotkeys. Money check, control plus M.")
        self.press(VK_HOME)
        self.assertEqual(self.speech.last, "Sounds. Entity beacons, on.")

    def test_h_jumps_to_the_next_heading(self):
        self.press(VK_F1)
        self.press(VK_H)
        self.assertEqual(
            self.speech.last, "Speech. Room announcements, on.")

    def test_h_wraps_from_the_last_heading_to_the_first(self):
        self.press(VK_F1)
        self.press(VK_H)
        self.press(VK_H)
        self.press(VK_H)
        self.assertEqual(self.speech.last, "Sounds. Entity beacons, on.")

    def test_shift_h_returns_to_the_top_of_the_current_category_first(self):
        self.press(VK_F1)
        self.press(VK_DOWN)
        self.press(VK_H, shift=True)
        self.assertEqual(self.speech.last, "Sounds. Entity beacons, on.")

    def test_shift_h_from_a_heading_goes_to_the_previous_one(self):
        self.press(VK_F1)
        self.press(VK_H)
        self.press(VK_H, shift=True)
        self.assertEqual(self.speech.last, "Sounds. Entity beacons, on.")

    def test_an_empty_category_is_never_landed_on(self):
        categories = (
            Category("Sounds", (Toggle("a", "A", True),)),
            Category("Hotkeys", ()),
            Category("Speech", (Toggle("b", "B", True),)),
        )
        self.menu, self.store, self.capture = menu(
            categories=categories, speech=self.speech)
        self.press(VK_F1)
        self.press(VK_H)
        self.assertEqual(self.speech.last, "Speech. B, on.")

    def test_an_entirely_empty_menu_says_so_and_stays_closed(self):
        self.menu, self.store, self.capture = menu(
            categories=(Category("Hotkeys", ()),), speech=self.speech)
        self.press(VK_F1)
        self.assertFalse(self.menu.open)
        self.assertIn("No settings", self.speech.last)


class SettingsMenuChangeTests(unittest.TestCase):
    def setUp(self):
        self.speech = Speech()
        self.menu, self.store, self.capture = menu(speech=self.speech)

    def press(self, vk, shift=False):
        self.capture.press(vk, shift=shift)
        self.menu.poll_once()

    def test_right_turns_a_toggle_off_and_says_the_new_state(self):
        self.press(VK_F1)
        self.press(VK_RIGHT)
        self.assertFalse(self.store.get("sounds.beacons"))
        self.assertEqual(self.speech.last, "Entity beacons, off.")

    def test_space_activates_a_toggle(self):
        self.press(VK_F1)
        self.press(VK_SPACE)
        self.assertFalse(self.store.get("sounds.beacons"))

    def test_enter_activates_a_toggle(self):
        self.press(VK_F1)
        self.press(VK_RETURN)
        self.assertFalse(self.store.get("sounds.beacons"))

    def test_right_steps_a_number_up(self):
        self.press(VK_F1)
        self.press(VK_DOWN)
        self.press(VK_RIGHT)
        self.assertEqual(self.store.get("sounds.volume"), 0.75)
        self.assertEqual(self.speech.last, "Beacon volume, 75 percent.")

    def test_left_steps_a_number_down(self):
        self.press(VK_F1)
        self.press(VK_DOWN)
        self.press(VK_LEFT)
        self.assertEqual(self.store.get("sounds.volume"), 0.25)

    def test_the_end_of_a_range_is_announced(self):
        self.press(VK_F1)
        self.press(VK_DOWN)
        self.press(VK_RIGHT)
        self.press(VK_RIGHT)
        self.press(VK_RIGHT)
        self.assertEqual(
            self.speech.last, "Beacon volume, 100 percent. Maximum.")

    def test_a_read_only_entry_cannot_be_changed(self):
        self.press(VK_F1)
        self.press(VK_END)
        self.press(VK_RIGHT)
        self.assertEqual(self.speech.last, "Money check, control plus M.")

    def test_changes_are_spoken_as_menu_focus(self):
        self.press(VK_F1)
        self.press(VK_RIGHT)
        self.assertEqual(self.speech.calls[-1][0], SpeechEventClass.MENU_FOCUS)


class SettingsMenuLifecycleResetTests(unittest.TestCase):
    """`clear()` is what a disconnect calls. It must release the keys
    silently: Dolphin has gone, so there is nobody in front of the game to
    hear a close announcement, and an open menu left holding the arrows
    would be holding them for a window that no longer exists."""

    def setUp(self):
        self.speech = Speech()
        self.menu, self.store, self.capture = menu(speech=self.speech)
        self.capture.press(VK_F1)
        self.menu.poll_once()
        self.speech.calls.clear()

    def test_clear_closes_the_menu(self):
        self.menu.clear("Dolphin went away")
        self.assertFalse(self.menu.open)

    def test_clear_releases_the_captured_keys(self):
        self.menu.clear("Dolphin went away")
        self.assertFalse(self.capture.menu_open)

    def test_clear_drops_keys_queued_before_it(self):
        self.capture.press(VK_DOWN)
        self.menu.clear("Dolphin went away")
        self.menu.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_clear_says_nothing(self):
        self.menu.clear("Dolphin went away")
        self.assertEqual(self.speech.calls, [])

    def test_clearing_an_already_closed_menu_is_harmless(self):
        self.menu.clear("first")
        self.menu.clear("second")
        self.assertFalse(self.menu.open)

    def test_it_reopens_afterwards(self):
        self.menu.clear("Dolphin went away")
        self.capture.press(VK_F1)
        self.menu.poll_once()
        self.assertTrue(self.menu.open)
        self.assertIn("Entity beacons, on.", self.speech.last)

    def test_the_controller_adopts_the_menu_on_construction(self):
        # The appliers need it, and it is reassigned on every reattach.
        controller = LifecycleController(
            connection=None, tasks_factory=None, narrator_factory=None,
            speaker=None, logger=logging.getLogger("settings-test"),
            settings_menu=self.menu)
        self.assertIs(self.menu.controller, controller)


class SettingsMenuPersistenceTests(unittest.TestCase):
    def test_a_change_is_written_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "companion_settings.json"
            menu_, store, capture = menu(path=path)
            capture.press(VK_F1)
            capture.press(VK_RIGHT)
            menu_.poll_once()
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(stored["accessibility"]["sounds.beacons"])


class KeyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = MenuKeyPolicy()

    def test_only_the_open_key_is_owned_while_the_menu_is_closed(self):
        self.assertTrue(self.policy.owns(VK_F1, menu_open=False))
        for key in (VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT, VK_H, VK_RETURN):
            self.assertFalse(self.policy.owns(key, menu_open=False), hex(key))

    def test_menu_keys_are_owned_while_it_is_open(self):
        for key in (VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT, VK_H, VK_RETURN,
                    VK_SPACE, VK_ESCAPE, VK_HOME, VK_END):
            self.assertTrue(self.policy.owns(key, menu_open=True), hex(key))

    def test_game_keys_are_never_owned(self):
        for key in (0x58, 0x5A, 0x43, 0x53, 0x44, 0x51, 0x57, 0x54, 0x47,
                    0x46):  # X Z C S D Q W T G F
            self.assertFalse(self.policy.owns(key, menu_open=True), hex(key))
        self.assertFalse(self.policy.owns(0x71, menu_open=True))  # F2


class FakeUser32:
    def __init__(self, held=()):
        self.held = set(held)

    def GetAsyncKeyState(self, vk):
        return 0x8000 if vk in self.held else 0


class KeyCaptureTests(unittest.TestCase):
    def capture(self, foreground=True, held=()):
        return LowLevelKeyCapture(
            MenuKeyPolicy(), lambda: foreground,
            logging.getLogger("settings-test"),
            user32=FakeUser32(held), kernel32=object())

    def test_the_open_key_is_swallowed_and_queued(self):
        capture = self.capture()
        self.assertTrue(capture._handle(VK_F1, WM_KEYDOWN))
        self.assertEqual(capture.poll(), [KeyEvent(VK_F1)])

    def test_the_key_up_is_swallowed_but_not_queued(self):
        capture = self.capture()
        capture._handle(VK_F1, WM_KEYDOWN)
        capture.poll()
        self.assertTrue(capture._handle(VK_F1, WM_KEYUP))
        self.assertEqual(capture.poll(), [])

    def test_nothing_is_taken_while_dolphin_is_not_focused(self):
        capture = self.capture(foreground=False)
        self.assertFalse(capture._handle(VK_F1, WM_KEYDOWN))
        self.assertEqual(capture.poll(), [])

    def test_arrows_reach_the_game_while_the_menu_is_closed(self):
        capture = self.capture()
        for key in (VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT, VK_H, VK_RETURN):
            self.assertFalse(capture._handle(key, WM_KEYDOWN), hex(key))
        self.assertEqual(capture.poll(), [])

    def test_arrows_are_taken_while_the_menu_is_open(self):
        capture = self.capture()
        capture.menu_open = True
        self.assertTrue(capture._handle(VK_DOWN, WM_KEYDOWN))
        self.assertEqual(capture.poll(), [KeyEvent(VK_DOWN)])

    def test_game_keys_are_never_taken_even_with_the_menu_open(self):
        capture = self.capture()
        capture.menu_open = True
        for key in (0x58, 0x5A, 0x54, 0x47, 0x46):  # X Z T G F
            self.assertFalse(capture._handle(key, WM_KEYDOWN), hex(key))

    def test_shift_is_reported_for_a_heading_jump_backwards(self):
        capture = self.capture(held=(0x10,))
        capture.menu_open = True
        capture._handle(VK_H, WM_KEYDOWN)
        self.assertEqual(capture.poll(), [KeyEvent(VK_H, shift=True)])

    def test_poll_drains(self):
        capture = self.capture()
        capture._handle(VK_F1, WM_KEYDOWN)
        self.assertEqual(len(capture.poll()), 1)
        self.assertEqual(capture.poll(), [])


class Reader:
    def __init__(self):
        self.polls = 0
        self.cleared = []

    def poll_once(self, *args):
        self.polls += 1

    def clear(self, reason):
        self.cleared.append(reason)

    def suppress_for_dialogue(self):
        self.cleared.append("suppressed")


class LifecycleGatingTests(unittest.TestCase):
    """The toggles that are honoured at poll time rather than applied."""

    def controller(self, **kwargs):
        store = SettingsStore(
            build_categories(), logger=logging.getLogger("settings-test"))
        controller = LifecycleController(
            connection=None, tasks_factory=None, narrator_factory=None,
            speaker=None, logger=logging.getLogger("settings-test"),
            settings=store, **kwargs)
        return controller, store

    def test_room_announcements_stop_when_switched_off(self):
        controller, store = self.controller()
        controller.room_change_reader = Reader()
        controller.poll_room_change()
        store.values["speech.room_changes"] = False
        controller.poll_room_change()
        controller.poll_room_change()
        self.assertEqual(controller.room_change_reader.polls, 1)

    def test_the_reader_is_cleared_once_on_the_falling_edge(self):
        controller, store = self.controller()
        controller.room_change_reader = Reader()
        controller.poll_room_change()
        store.values["speech.room_changes"] = False
        controller.poll_room_change()
        controller.poll_room_change()
        self.assertEqual(
            controller.room_change_reader.cleared, ["disabled in settings"])

    def test_switching_back_on_resumes_polling(self):
        controller, store = self.controller()
        controller.room_change_reader = Reader()
        store.values["speech.room_changes"] = False
        controller.poll_room_change()
        store.values["speech.room_changes"] = True
        controller.poll_room_change()
        self.assertEqual(controller.room_change_reader.polls, 1)

    def test_beacons_are_stopped_as_well_as_cleared(self):
        controller, store = self.controller()
        controller.npc_sound_reader = Reader()
        controller.poll_npc_sounds()
        store.values["sounds.beacons"] = False
        controller.poll_npc_sounds()
        self.assertIn("suppressed", controller.npc_sound_reader.cleared)

    def test_footsteps_and_the_blocked_cue_are_gated_independently(self):
        controller, store = self.controller()
        controller.terrain_footstep_reader = Reader()
        controller.blocked_movement_reader = Reader()
        store.values["sounds.footsteps"] = False
        store.values["sounds.blocked_cue"] = True
        controller.poll_terrain_footsteps()
        controller.poll_blocked_movement()
        self.assertEqual(controller.terrain_footstep_reader.polls, 0)
        self.assertEqual(controller.blocked_movement_reader.polls, 1)

    def test_everything_runs_when_there_are_no_settings_at_all(self):
        controller = LifecycleController(
            connection=None, tasks_factory=None, narrator_factory=None,
            speaker=None, logger=logging.getLogger("settings-test"))
        controller.room_change_reader = Reader()
        controller.poll_room_change()
        self.assertEqual(controller.room_change_reader.polls, 1)

    def test_an_open_menu_polls_at_the_active_rate_in_a_waiting_state(self):
        controller, _ = self.controller()
        menu_, _, _ = menu()
        controller.settings_menu = menu_
        self.assertEqual(controller.interval, controller.waiting_interval)
        menu_.open = True
        self.assertEqual(controller.interval, controller.active_interval)

    def test_the_menu_is_polled_and_isolated_from_the_loop(self):
        class Exploding:
            def poll_once(self):
                raise RuntimeError("boom")

        controller, _ = self.controller()
        controller.settings_menu = Exploding()
        controller.poll_settings_menu()  # must not raise


class AutoRepeatSettingTests(unittest.TestCase):
    """The two entity-nav overrides the Speech category writes."""

    def navigator(self):
        return EntityNavigator(
            memory=None, profile=None, sources={}, hotkeys={},
            speech=None, logger=logging.getLogger("settings-test"))

    def test_auto_repeat_is_on_by_default(self):
        self.assertTrue(self.navigator().auto_repeat_enabled)

    def test_the_delay_defers_to_the_profile_until_overridden(self):
        self.assertIsNone(self.navigator().auto_repeat_seconds)

    def test_the_settings_write_both(self):
        store = SettingsStore(
            build_categories(), logger=logging.getLogger("settings-test"))
        navigator = self.navigator()
        controller = Controller(entity_nav_reader=navigator)
        store.set("speech.auto_repeat", False, controller)
        store.set("speech.auto_repeat_delay", 2.5, controller)
        self.assertFalse(navigator.auto_repeat_enabled)
        self.assertEqual(navigator.auto_repeat_seconds, 2.5)


class EntityLocationSettingTests(unittest.TestCase):
    """ctrl+L and the Speech category are one setting, not two.

    The hotkey flips `location_enabled` on the reader directly -- it has
    to, the menu may never have been opened. If the store never hears
    about that, it keeps the stale value, writes it on the next unrelated
    change, and silently undoes the player's choice at the next launch."""

    def navigator(self):
        return EntityNavigator(
            memory=None, profile=None, sources={}, hotkeys={},
            speech=None, logger=logging.getLogger("settings-test"))

    def store(self):
        return SettingsStore(
            build_categories(), logger=logging.getLogger("settings-test"))

    def test_it_is_on_by_default(self):
        self.assertTrue(self.navigator().location_enabled)

    def test_the_menu_writes_the_reader(self):
        store, navigator = self.store(), self.navigator()
        controller = Controller(entity_nav_reader=navigator)
        store.set("speech.entity_location", False, controller)
        self.assertFalse(navigator.location_enabled)

    def test_the_applier_wires_the_reader_back_to_the_store(self):
        store, navigator = self.store(), self.navigator()
        controller = Controller(entity_nav_reader=navigator, settings=store)
        store.apply_all(controller)
        self.assertIsNotNone(navigator.on_location_change)
        navigator.on_location_change(False)
        self.assertFalse(store.values["speech.entity_location"])

    def test_a_controller_with_no_store_still_applies_the_value(self):
        """Callback wiring is a bonus; the setting itself must still land."""
        store, navigator = self.store(), self.navigator()
        controller = Controller(entity_nav_reader=navigator)
        store.set("speech.entity_location", False, controller)
        self.assertFalse(navigator.location_enabled)
        self.assertIsNone(navigator.on_location_change)

    def test_the_applier_tolerates_a_missing_reader(self):
        store = self.store()
        store.set("speech.entity_location", False, Controller())


class BuiltCategoryTests(unittest.TestCase):
    def test_every_category_the_owner_asked_for_is_present(self):
        titles = [category.title for category in build_categories()]
        self.assertEqual(titles, ["Sounds", "Speech", "Navigation", "Hotkeys"])

    def test_the_sound_library_heading_appears_only_with_sounds(self):
        # Omitted entirely when nothing is playable, rather than added
        # empty -- see settings._sound_library_categories.
        library = SimpleNamespace(
            cues=(SimpleNamespace(
                key="beacon.item", label="Item beacon",
                description="An item is lying on the ground nearby."),),
            play=lambda key: None)
        titles = [
            category.title
            for category in build_categories(sound_library=library)]
        self.assertEqual(
            titles,
            ["Sounds", "Speech", "Navigation", "Hotkeys", "Sound library"])
        empty = SimpleNamespace(cues=(), play=lambda key: None)
        self.assertEqual(
            [category.title for category in build_categories(sound_library=empty)],
            ["Sounds", "Speech", "Navigation", "Hotkeys"])

    def test_hotkeys_are_listed_as_read_only_entries(self):
        categories = build_categories(
            hotkeys=(("Money check", "ctrl+m"),))
        item = categories[-1].items[0]
        self.assertEqual(item.kind, "info")
        self.assertEqual(item.speak_value(None), "control plus M")

    def test_defaults_come_from_the_constants_the_features_use(self):
        items = {
            item.key: item
            for category in build_categories() for item in category.items
        }
        self.assertEqual(
            items["sounds.beacon_volume"].default,
            npc_beacons.PASSIVE_BEACON_GAIN_SCALE)
        self.assertEqual(
            items["sounds.warp_beacon_volume"].default,
            npc_beacons.PASSIVE_BEACON_CATEGORY_GAIN["warp"])

    def test_every_key_is_unique(self):
        keys = [
            item.key
            for category in build_categories() for item in category.items
        ]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
