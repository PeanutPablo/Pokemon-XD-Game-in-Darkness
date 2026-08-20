"""Tests for read-only overworld entity navigation ("item navigation").

Numbered comments below map directly to the required test list from the
task spec. Requirements #26-28 (existing NPC beacon / dialogue / battle+VS
narration regression) are intentionally NOT duplicated here -- they are
covered by running the full suite (test_npc_beacons.py, test_dialogue.py,
test_battle_narrator.py, test_phase1e_menus.py already exist and pass).
"""
import logging
import math
import struct
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.entities import Entity
from battle_narrator.entity_nav import (
    ENTITY_GONE_MESSAGE,
    NO_ENTITIES_MESSAGE,
    EntityNavigator,
    clock_position,
    describe_entity,
    facing_error,
    relative_geometry,
)
from battle_narrator.entity_sources import NPCEntitySource
from battle_narrator.hotkeys import WindowsForegroundHotkey
from battle_narrator.npc_beacons import NPC, PlayerPose, Position
from battle_narrator.phase1b_lifecycle import LifecycleController, LifecycleState
from battle_narrator.profile import XD_US_REV0


@dataclass(frozen=True)
class MultiCategoryProfile:
    """A minimal stand-in profile exercising >1 category generically --
    the shipped profile only lists "npc" this slice, but the navigator's
    architecture must support more (per the explicit design requirement)."""
    entity_nav_category_keys: tuple = ("npc", "door", "treasure")
    entity_nav_category_singular_labels: tuple = ("NPC", "Door", "Item")
    entity_nav_category_plural_labels: tuple = ("NPCs", "Doors", "Items")
    entity_nav_same_position_threshold: float = XD_US_REV0.entity_nav_same_position_threshold
    entity_nav_vertical_threshold: float = XD_US_REV0.entity_nav_vertical_threshold
    entity_nav_auto_repeat_seconds: float = XD_US_REV0.entity_nav_auto_repeat_seconds
    entity_nav_auto_repeat_movement_epsilon: float = (
        XD_US_REV0.entity_nav_auto_repeat_movement_epsilon)
    interaction_collision_allowance: float = XD_US_REV0.interaction_collision_allowance
    current_floor_id: int = XD_US_REV0.current_floor_id
    window_manager: int = XD_US_REV0.window_manager
    window_list_offset: int = XD_US_REV0.window_list_offset


class Hotkey:
    def __init__(self):
        self.fire = False

    def poll(self):
        result = self.fire
        self.fire = False
        return result


class Speech:
    def __init__(self):
        self.calls = []

    def emit(self, event, text, deduplicate=False, interrupt=None):
        self.calls.append((event, text, deduplicate, interrupt))


def test_logger():
    log = logging.getLogger(f"entity-nav-test-{id(object())}")
    log.addHandler(logging.NullHandler())
    log.setLevel(logging.DEBUG)
    return log


class FakeMemory:
    """Entity-nav only ever reads two fixed addresses (floor id, window
    head); a stateful fake keyed on those two values is sufficient."""

    def __init__(self, floor_id=1, window_head=0):
        self.floor_id = floor_id
        self.window_head = window_head

    def u16(self, address, label=""):
        return self.floor_id

    def u32(self, address, label=""):
        return self.window_head


class FakeSource:
    def __init__(self, entities, pose):
        self._entities = entities
        self.pose = pose

    def entities(self):
        return list(self._entities)

    def player_pose(self):
        return self.pose


class BrokenSource(FakeSource):
    def entities(self):
        raise MemoryError("category runtime pointer is absent")


class FakeNPCUnderlying:
    def __init__(self, npcs, pose):
        self._npcs = npcs
        self._pose = pose

    def npcs(self):
        return self._npcs

    def player_pose(self):
        return self._pose


def entity(index, x, z, y=0, label=None, interaction=None, category="npc"):
    return Entity(
        category=category,
        identity=(category, index),
        label=label,
        position=Position(x, y, z),
        interaction_distance=interaction,
    )


def hotkey_map():
    return {
        "next": Hotkey(),
        "prev": Hotkey(),
        "next_category": Hotkey(),
        "prev_category": Hotkey(),
        "repeat": Hotkey(),
        "auto_repeat": Hotkey(),
    }


class MovableSource(FakeSource):
    """A FakeSource whose player can be walked around, for the stand-still
    auto-repeat. `player_pose` may also be made to fail, since a transient
    bad read is a real case the auto-repeat has to stay quiet through."""

    def __init__(self, entities, pose):
        super().__init__(entities, pose)
        self.fail = False

    def walk_to(self, x, z):
        self.pose = PlayerPose(Position(x, self.pose.position.y, z),
                               self.pose.yaw)

    def player_pose(self):
        if self.fail:
            raise MemoryError("player pose unreadable")
        return self.pose


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def advance(self, dt):
        self.t += dt

    def __call__(self):
        return self.t


def navigator(entities, pose=None, memory=None, hotkeys=None, profile=None,
              clock=None, source=None):
    pose = pose or PlayerPose(Position(0, 0, 0), 0)
    source = source or FakeSource(entities, pose)
    nav = EntityNavigator(
        memory or FakeMemory(),
        profile or XD_US_REV0,
        {"npc": source},
        hotkeys or hotkey_map(),
        Speech(),
        test_logger(),
        clock=clock or FakeClock(),
    )
    return nav, source


class GeometryTests(unittest.TestCase):
    """#7 direction at all major clock positions, #8 facing rotation,
    #9 distance formatting (neutral scale, not "meters")."""

    def test_twelve_three_six_nine_oclock(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        cases = [
            (Position(0, 0, -10), 12),  # straight ahead
            (Position(10, 0, 0), 3),    # directly right
            (Position(0, 0, 10), 6),    # directly behind
            (Position(-10, 0, 0), 9),   # directly left
        ]
        for position, expected in cases:
            horizontal, forward, right, _ = relative_geometry(pose, position)
            self.assertEqual(clock_position(horizontal, forward, right, 1.5), expected)

    def test_rotating_player_facing_changes_clock(self):
        position = Position(0, 0, -10)
        ahead = PlayerPose(Position(0, 0, 0), 0)
        turned = PlayerPose(Position(0, 0, 0), 3.14159265 / 2)
        h1, f1, r1, _ = relative_geometry(ahead, position)
        h2, f2, r2, _ = relative_geometry(turned, position)
        clock_ahead = clock_position(h1, f1, r1, 1.5)
        clock_turned = clock_position(h2, f2, r2, 1.5)
        self.assertEqual(clock_ahead, 12)
        self.assertNotEqual(clock_turned, clock_ahead)

    def test_same_position_when_extremely_close(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        horizontal, forward, right, _ = relative_geometry(pose, Position(0.1, 0, 0.1))
        self.assertIsNone(clock_position(horizontal, forward, right, 1.5))

    def test_distance_is_neutral_scale_not_meters(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        item = entity(0, 0, -6, label="Rui", interaction=2.0)
        text = describe_entity(XD_US_REV0, "npc", item, pose)
        self.assertIn("distance 6", text)
        self.assertNotIn("meter", text.casefold())

    def test_interaction_range_announced_both_ways(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        near = entity(0, 0, -1, label="Shopkeeper", interaction=2.0)
        far = entity(1, 0, -10, label="Rui", interaction=2.0)
        self.assertIn("Interaction available", describe_entity(XD_US_REV0, "npc", near, pose))
        self.assertIn("Out of interaction range", describe_entity(XD_US_REV0, "npc", far, pose))

    def test_unnamed_npc_fallback_omits_name(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        unnamed = entity(0, 0, -4, label=None, interaction=2.0)
        text = describe_entity(XD_US_REV0, "npc", unnamed, pose)
        self.assertTrue(text.startswith("NPC. "))
        self.assertNotIn("None", text)


class ActivationAndCyclingTests(unittest.TestCase):
    """#1 category activation, #2 closest-first, #3 next, #4 previous,
    #5 forward wraparound, #6 reverse wraparound, #14 stable identity
    preserved after minor player movement."""

    def setUp(self):
        self.entities = [
            entity(0, 0, -20, label="Far"),
            entity(1, 0, -5, label="Near"),
            entity(2, 0, -12, label="Mid"),
        ]
        self.nav, self.source = navigator(self.entities)

    def press(self, key):
        self.nav.hotkeys[key].fire = True
        self.nav.poll_once()

    def last(self):
        return self.nav.speech.calls[-1][1]

    def test_activation_announces_category_and_closest_first(self):
        self.press("next")
        self.assertTrue(self.last().startswith("NPCs. 3 available."))
        self.assertIn("Near", self.last())

    def test_next_moves_to_second_closest(self):
        self.press("next")  # Near
        self.press("next")  # Mid
        self.assertIn("Mid", self.last())

    def test_previous_moves_backward(self):
        self.press("next")  # Near
        self.press("next")  # Mid
        self.press("prev")  # back to Near
        self.assertIn("Near", self.last())

    def test_forward_wraparound(self):
        self.press("next")  # Near
        self.press("next")  # Mid
        self.press("next")  # Far
        self.press("next")  # wraps to Near
        self.assertIn("Near", self.last())

    def test_reverse_wraparound(self):
        self.press("next")  # Near (first)
        self.press("prev")  # wraps to Far (last)
        self.assertIn("Far", self.last())

    def test_selection_survives_minor_player_movement(self):
        self.press("next")  # Near
        self.press("next")  # Mid
        self.source.pose = PlayerPose(Position(0.3, 0, 0.2), 0)
        self.press("repeat")
        self.assertIn("Mid", self.last())


class RefreshRemovalTests(unittest.TestCase):
    """Refresh was removed on 2026-08-16 (see `EntityNavigator`'s
    docstring). What replaces it is asserted here rather than assumed: a
    category re-activation must pick up an entity that appeared after the
    category was first activated, since that -- not the deleted action -- is
    now the only way to reach one."""

    def setUp(self):
        self.entities = [
            entity(0, 0, -5, label="Near"),
            entity(1, 0, -20, label="Far"),
        ]
        self.nav, self.source = navigator(self.entities)

    def press(self, key):
        self.nav.hotkeys[key].fire = True
        self.nav.poll_once()

    def last(self):
        return self.nav.speech.calls[-1][1]

    def test_the_navigator_has_no_refresh_action_left(self):
        self.assertFalse(hasattr(self.nav, "_refresh"))

    def test_refresh_is_not_among_the_hotkeys(self):
        """Named for what it is actually pinning. It was
        `test_it_polls_only_the_five_remaining_hotkeys` and asserted the
        exact set, which made it fail when `location` was added on
        2026-08-19 -- a true statement about a new key, reported as a
        regression in the removal of an old one. The point of this test is
        that `refresh` is gone and stays gone; new actions are somebody
        else's business."""
        self.assertNotIn("refresh", self.nav.hotkeys)
        self.assertLessEqual(
            {"next", "prev", "next_category", "prev_category", "repeat"},
            set(self.nav.hotkeys))

    def test_reactivating_the_category_picks_up_a_new_entity(self):
        self.press("next")
        self.source._entities.append(entity(2, 0, -1, label="New"))
        self.press("next_category")
        self.assertIn("3 available.", self.last())


class CategoryTests(unittest.TestCase):
    """#22 category switching, #23 empty-category skipping,
    #24 all-categories-empty behavior."""

    def test_all_categories_empty_announces_no_entities(self):
        nav, _ = navigator([])
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        self.assertEqual(nav.speech.calls[-1][1], NO_ENTITIES_MESSAGE)

    def test_next_category_switches_and_skips_empty(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        nav = EntityNavigator(
            FakeMemory(), MultiCategoryProfile(),
            {
                "npc": FakeSource([entity(0, 0, -5, label="Rui")], pose),
                "door": FakeSource([], pose),
                "treasure": FakeSource(
                    [entity(0, 0, -3, label="Potion", category="treasure")], pose
                ),
            },
            hotkey_map(), Speech(), test_logger(),
        )
        nav.hotkeys["next_category"].fire = True
        nav.poll_once()
        self.assertIn("NPCs. 1 available.", nav.speech.calls[-1][1])
        nav.hotkeys["next_category"].fire = True
        nav.poll_once()
        self.assertIn("Items. 1 available.", nav.speech.calls[-1][1])
        self.assertIn("Potion", nav.speech.calls[-1][1])

    def test_prev_category_wraps_backward(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        nav = EntityNavigator(
            FakeMemory(), MultiCategoryProfile(),
            {
                "npc": FakeSource([entity(0, 0, -5, label="Rui")], pose),
                "door": FakeSource([], pose),
                "treasure": FakeSource(
                    [entity(0, 0, -3, label="Potion", category="treasure")], pose
                ),
            },
            hotkey_map(), Speech(), test_logger(),
        )
        nav.hotkeys["next_category"].fire = True
        nav.poll_once()  # lands on npc (first available)
        nav.hotkeys["prev_category"].fire = True
        nav.poll_once()  # wraps backward: npc -> treasure
        self.assertIn("Items. 1 available.", nav.speech.calls[-1][1])

    def test_broken_npc_source_does_not_hide_a_valid_item(self):
        """Tower 3F has treasure records but no floor-character array."""
        pose = PlayerPose(Position(0, 0, 0), 0)
        nav = EntityNavigator(
            FakeMemory(), MultiCategoryProfile(),
            {
                "npc": BrokenSource([], pose),
                "door": FakeSource([], pose),
                "treasure": FakeSource(
                    [entity(0, 0, -3, label="Item box", category="treasure")],
                    pose,
                ),
            },
            hotkey_map(), Speech(), test_logger(),
        )
        nav.hotkeys["next_category"].fire = True
        nav.poll_once()
        self.assertIn("Items. 1 available.", nav.speech.calls[-1][1])
        self.assertIn("Item box", nav.speech.calls[-1][1])


class InvalidationTests(unittest.TestCase):
    """#15 selection reset after map change, #16 selected-entity
    disappearance, #21 repeat-selection hotkey."""

    def test_map_change_clears_selection(self):
        memory = FakeMemory(floor_id=1)
        nav, _ = navigator([entity(0, 0, -5, label="Rui")], memory=memory)
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        self.assertIsNotNone(nav.state.selected_identity)
        memory.floor_id = 2
        nav.poll_once()
        self.assertIsNone(nav.state.selected_identity)
        self.assertIsNone(nav.state.category_key)

    def test_disappeared_entity_repeat_announces_gone(self):
        nav, source = navigator([entity(0, 0, -5, label="Rui")])
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        source._entities = []
        nav.hotkeys["repeat"].fire = True
        nav.poll_once()
        self.assertEqual(nav.speech.calls[-1][1], ENTITY_GONE_MESSAGE)

    def test_repeat_updates_direction_and_distance_after_movement(self):
        nav, source = navigator([entity(0, 0, -5, label="Rui")])
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        first = nav.speech.calls[-1][1]
        source.pose = PlayerPose(Position(0, 0, -2), 0)
        nav.hotkeys["repeat"].fire = True
        nav.poll_once()
        second = nav.speech.calls[-1][1]
        self.assertIn("distance 5", first)
        self.assertIn("distance 3", second)
        self.assertEqual(len(nav.speech.calls), 2)


class SelectionPersistenceTests(unittest.TestCase):
    """The highlight survives menus and dialogue.

    It used to be wiped whenever free-roaming control was lost, so the
    ordinary loop -- find someone in the list, talk to them, carry on down
    the list -- threw the list away every single time and dropped the
    player back at the nearest entity."""

    def two_entities(self, memory=None):
        return navigator(
            [entity(0, 0, -5, label="Rui"), entity(1, 0, -20, label="Jovi")],
            memory=memory or FakeMemory())

    def select_second(self, nav):
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        return nav.state.selected_identity

    def test_dialogue_does_not_reset_the_selection(self):
        nav, _ = self.two_entities()
        selected = self.select_second(nav)
        nav.poll_once(dialogue_active=True)
        self.assertEqual(nav.state.selected_identity, selected)
        self.assertEqual(nav.state.category_key, "npc")

    def test_selection_resumes_after_dialogue_ends(self):
        nav, _ = self.two_entities()
        selected = self.select_second(nav)
        nav.poll_once(dialogue_active=True)
        nav.poll_once()
        nav.hotkeys["repeat"].fire = True
        nav.poll_once()
        self.assertIn("Jovi", nav.speech.calls[-1][1])
        self.assertEqual(nav.state.selected_identity, selected)

    def test_opening_a_menu_does_not_reset_the_selection(self):
        memory = FakeMemory()
        nav, _ = self.two_entities(memory=memory)
        selected = self.select_second(nav)
        memory.window_head = 0x80001000
        nav.poll_once()
        memory.window_head = 0
        nav.poll_once()
        self.assertEqual(nav.state.selected_identity, selected)

    def test_hotkeys_still_do_nothing_while_a_menu_is_open(self):
        # Keeping the selection must not mean acting on it out of context.
        memory = FakeMemory()
        nav, _ = self.two_entities(memory=memory)
        self.select_second(nav)
        spoken = len(nav.speech.calls)
        memory.window_head = 0x80001000
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        self.assertEqual(len(nav.speech.calls), spoken)

    def test_map_change_still_clears(self):
        # Entities are per-room, so a remembered selection would name
        # something no longer present. This one MUST still reset.
        memory = FakeMemory(floor_id=1)
        nav, _ = self.two_entities(memory=memory)
        self.select_second(nav)
        memory.floor_id = 2
        nav.poll_once()
        self.assertIsNone(nav.state.selected_identity)
        self.assertIsNone(nav.state.category_key)

    def test_selection_survives_dialogue_even_if_entities_move(self):
        nav, source = self.two_entities()
        selected = self.select_second(nav)
        nav.poll_once(dialogue_active=True)
        source.pose = PlayerPose(Position(0, 0, -18), 0)
        nav.poll_once()
        nav.hotkeys["repeat"].fire = True
        nav.poll_once()
        self.assertEqual(nav.state.selected_identity, selected)
        self.assertIn("distance 2", nav.speech.calls[-1][1])


class CycleAnnouncementTests(unittest.TestCase):
    """Cycling within a category should not re-announce the category on
    every press -- it is padding in front of the thing the player wants, on
    the hotkey pressed most."""

    def test_cycling_omits_the_category_word(self):
        # The first press activates the category; the second is a real
        # cycle, and that is the utterance under test.
        nav, _ = navigator(
            [entity(0, 0, -5, label="Rui"), entity(1, 0, -20, label="Jovi")])
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        spoken = nav.speech.calls[-1][1]
        self.assertTrue(spoken.startswith("Jovi"), spoken)
        self.assertNotIn("NPC", spoken)

    def test_activation_does_not_say_the_category_twice(self):
        # It used to: "NPCs. 1 available. NPC. Rui. ...".
        nav, _ = navigator([entity(0, 0, -5, label="Rui")])
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        spoken = nav.speech.calls[-1][1]
        self.assertEqual(spoken.count("NPC"), 1, spoken)
        self.assertIn("NPCs. 1 available. Rui", spoken)

    def test_cycling_keeps_everything_else(self):
        nav, _ = navigator([entity(0, 0, -5, label="Rui")])
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        spoken = nav.speech.calls[-1][1]
        self.assertIn("Rui", spoken)
        self.assertIn("o'clock", spoken)
        self.assertIn("distance 5", spoken)

    def test_switching_category_still_announces_it(self):
        # The category is only informative when it CHANGES.
        nav, _ = navigator([entity(0, 0, -5, label="Rui")])
        nav.hotkeys["next_category"].fire = True
        nav.poll_once()
        self.assertIn("NPCs", nav.speech.calls[-1][1])

    def test_describe_entity_still_defaults_to_including_the_category(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        described = describe_entity(
            XD_US_REV0, "npc", entity(0, 0, -5, label="Rui"), pose)
        self.assertTrue(described.startswith("NPC."), described)


class ContextTests(unittest.TestCase):
    """#17 dialogue-context suppression, #19 menu-context suppression
    (via the conservative any-window-open signal)."""

    def test_dialogue_active_suppresses_hotkeys(self):
        nav, _ = navigator([entity(0, 0, -5, label="Rui")])
        nav.hotkeys["next"].fire = True
        nav.poll_once(dialogue_active=True)
        self.assertEqual(nav.speech.calls, [])

    def test_window_open_suppresses_hotkeys(self):
        memory = FakeMemory(window_head=0x80100000)
        nav, _ = navigator([entity(0, 0, -5, label="Rui")], memory=memory)
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        self.assertEqual(nav.speech.calls, [])

    def test_resumes_after_window_closes(self):
        memory = FakeMemory(window_head=0x80100000)
        nav, _ = navigator([entity(0, 0, -5, label="Rui")], memory=memory)
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        self.assertEqual(nav.speech.calls, [])
        memory.window_head = 0
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        self.assertEqual(len(nav.speech.calls), 1)


class ForegroundEnforcementTests(unittest.TestCase):
    """#20 Dolphin foreground enforcement."""

    def test_hotkey_ignored_when_dolphin_not_foreground(self):
        real_hotkey = object.__new__(WindowsForegroundHotkey)
        real_hotkey.process_name = "dolphin.exe"
        real_hotkey.held = False
        state = {"pressed": True, "process": "notepad.exe"}
        real_hotkey._pressed = lambda: state["pressed"]
        real_hotkey._foreground_process = lambda: state["process"]
        keys = hotkey_map()
        keys["next"] = real_hotkey
        nav, _ = navigator([entity(0, 0, -5, label="Rui")], hotkeys=keys)
        nav.poll_once()
        self.assertEqual(nav.speech.calls, [])
        state["process"] = "dolphin.exe"
        state["pressed"] = False
        nav.poll_once()  # key released while switching focus
        state["pressed"] = True
        nav.poll_once()  # fresh press while Dolphin is foreground
        self.assertEqual(len(nav.speech.calls), 1)


class SpeechBehaviorTests(unittest.TestCase):
    """#25 rapid cycling uses interrupting speech so obsolete selections
    do not queue."""

    def test_every_announcement_uses_interrupting_speech(self):
        nav, _ = navigator([
            entity(0, 0, -5, label="Rui"), entity(1, 0, -8, label="Ash"),
        ])
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        nav.hotkeys["next"].fire = True
        nav.poll_once()
        self.assertTrue(all(call[3] is True for call in nav.speech.calls))
        self.assertTrue(all(call[2] is False for call in nav.speech.calls))


class NPCEntitySourceTests(unittest.TestCase):
    """#11 unnamed NPC fallback (adapter passthrough), #12 duplicate NPC
    suppression, #13 invalid NPC rejection."""

    def make(self, npcs, entity_names=None):
        adapter = NPCEntitySource(memory=None, profile=None, entity_names=entity_names)
        adapter.source = FakeNPCUnderlying(npcs, PlayerPose(Position(0, 0, 0), 0))
        return adapter

    def test_invisible_and_untalkable_npcs_are_rejected(self):
        npcs = [
            NPC(1, 0, True, 0, Position(0, 0, -5)),   # talk_id 0: not interactable
            NPC(1, 1, False, 5, Position(0, 0, -5)),  # not visible
            NPC(1, 2, True, 7, Position(0, 0, -5)),   # valid
        ]
        entities = self.make(npcs).entities()
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].identity, ("npc", 1, 2))

    def test_duplicate_identity_suppressed(self):
        npcs = [
            NPC(1, 0, True, 5, Position(0, 0, -5)),
            NPC(1, 0, True, 5, Position(0, 0, -5)),
        ]
        self.assertEqual(len(self.make(npcs).entities()), 1)

    def test_unnamed_npc_gets_stable_letter_label(self):
        npcs = [
            NPC(1, 0, True, 5, Position(0, 0, -5), name_id=0),
            NPC(1, 1, True, 6, Position(10, 0, -5), name_id=0),
        ]
        adapter = self.make(npcs, entity_names={1: "Rui"})
        entities = {e.identity: e for e in adapter.entities()}
        self.assertEqual(entities[("npc", 1, 0)].label, "NPC A")
        self.assertEqual(entities[("npc", 1, 1)].label, "NPC B")
        # Stable across repeated calls, not re-derived from selection/order.
        self.assertEqual(adapter.entities()[0].label, "NPC A")

    def test_unnamed_letters_skip_named_npcs(self):
        npcs = [
            NPC(1, 0, True, 5, Position(0, 0, -5), name_id=1),
            NPC(1, 1, True, 6, Position(10, 0, -5), name_id=0),
        ]
        adapter = self.make(npcs, entity_names={1: "Rui"})
        entities = {e.identity: e for e in adapter.entities()}
        self.assertEqual(entities[("npc", 1, 0)].label, "Rui")
        self.assertEqual(entities[("npc", 1, 1)].label, "NPC A")

    def test_named_npc_resolves_label(self):
        npcs = [NPC(1, 0, True, 5, Position(0, 0, -5), name_id=1)]
        adapter = self.make(npcs, entity_names={1: "Rui"})
        self.assertEqual(adapter.entities()[0].label, "Rui")

    def test_synthetic_elevator_and_item_entries_are_excluded(self):
        npcs = [
            NPC(1, 0, True, 5, Position(0, 0, -5)),
            NPC(1, 0x7FFF, True, 1, Position(0, 15, 16), category="elevator", label="Elevator"),
            NPC(1, 0x7FFE, True, 1, Position(-30, 15, -104), category="item", label="PDA"),
        ]
        entities = self.make(npcs).entities()
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].category, "npc")


class GlobalCompanionEntitySourceTests(unittest.TestCase):
    @dataclass
    class Actor:
        slot: int
        group_id: int
        res_id: int
        displayed: bool
        position: object

    class Runtime:
        def __init__(self, actors): self._actors = actors
        def actors(self): return self._actors

    def source(self, actors):
        from battle_narrator.entity_sources import GlobalCompanionEntitySource
        pose = FakeNPCUnderlying([], PlayerPose(Position(0, 0, 0), 0))
        return GlobalCompanionEntitySource(pose, self.Runtime(actors))

    def test_visible_jovi_is_published_from_global_slot(self):
        jovi = self.Actor(1, 0, 101, True, Position(-78, 0, -110))
        entities = self.source([jovi]).entities()
        self.assertEqual([(e.label, e.position) for e in entities], [
            ("Jovi", Position(-78, 0, -110)),
        ])

    def test_player_and_hidden_reserved_slots_are_not_published(self):
        actors = [
            self.Actor(0, 0, 100, True, Position(0, 0, 0)),
            self.Actor(1, 0, 101, False, Position(-78, 0, -110)),
            self.Actor(2, 0, 104, True, Position(5, 0, 5)),
        ]
        self.assertEqual(self.source(actors).entities(), [])


class CategoryFilteredEntitySourceTests(unittest.TestCase):
    """Covers the reused per-floor elevator/item entries npc_beacons.py's
    NPCMemorySource.npcs() injects from its verified ELEVATORS/ITEMS
    lookups -- filtered and relabeled per category, not re-derived here."""

    def make(self, npcs, category):
        from battle_narrator.entity_sources import CategoryFilteredEntitySource
        adapter = CategoryFilteredEntitySource(memory=None, profile=None, category=category)
        adapter.source = FakeNPCUnderlying(npcs, PlayerPose(Position(0, 0, 0), 0))
        return adapter

    def test_filters_to_requested_category_and_uses_direct_label(self):
        npcs = [
            NPC(1, 0, True, 5, Position(0, 0, -5)),
            NPC(1, 0x7FFF, True, 1, Position(0, 15, 16), interaction_radius=4.0,
                category="elevator", label="Elevator"),
            NPC(1, 0x7FFE, True, 1, Position(-30, 15, -104), interaction_radius=10.0,
                category="item", label="PDA"),
        ]
        elevators = self.make(npcs, "elevator").entities()
        self.assertEqual(len(elevators), 1)
        self.assertEqual(elevators[0].label, "Elevator")
        self.assertEqual(elevators[0].category, "elevator")
        self.assertEqual(elevators[0].interaction_distance, 4.0)

        items = self.make(npcs, "item").entities()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].label, "PDA")
        self.assertEqual(items[0].interaction_distance, 10.0)

    def test_absent_category_on_current_floor_is_empty(self):
        npcs = [NPC(1, 0, True, 5, Position(0, 0, -5))]
        self.assertEqual(self.make(npcs, "item").entities(), [])


class ScriptedPdaEntitySourceTests(unittest.TestCase):
    class Memory:
        def __init__(self, room): self.room = room
        def u16(self, _address, _label): return self.room

    class Flags:
        def __init__(self, available=1, obtained=0):
            self.values = {1849: available, 1660: obtained}
        def value(self, flag_id): return self.values[flag_id]

    def source(self, room=0x8A, available=1, obtained=0):
        from battle_narrator.entity_sources import ScriptedPdaEntitySource
        return ScriptedPdaEntitySource(
            self.Memory(room), XD_US_REV0,
            self.Flags(available, obtained))

    def test_pda_uses_live_verified_xg_approach_point(self):
        entities = self.source().entities()
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].label, "PDA")
        self.assertEqual(entities[0].position, Position(-104.0, 0.5, -40.0))

    def test_pda_is_absent_outside_its_room(self):
        self.assertEqual(self.source(room=0x8B).entities(), [])

    def test_pda_is_hidden_before_story_availability(self):
        self.assertEqual(self.source(available=0).entities(), [])

    def test_pda_is_hidden_after_pickup(self):
        self.assertEqual(self.source(obtained=1).entities(), [])



class WarpEntitySourceTests(unittest.TestCase):
    """Covers the tentative/unverified generic warp table reader: the
    double-indirected count (matching the already-verified people_info
    pattern), stride-based record walk, empty-slot (marker==0) skipping,
    and non-finite-position skipping."""

    def make_backend(self):
        from battle_narrator.memory import MemoryReader

        class Backend:
            def __init__(self):
                self.data = {}

            def put(self, address, value):
                for offset, byte in enumerate(value):
                    self.data[address + offset] = byte

            def read_bytes(self, address, size):
                return bytes(
                    self.data.get(address + offset, 0) for offset in range(size)
                )

        return Backend(), MemoryReader

    def be32(self, value):
        return value.to_bytes(4, "big")

    def f32(self, value):
        return struct.pack(">f", value)

    def test_reads_count_via_double_indirection_and_skips_empty_slots(self):
        from battle_narrator.entity_sources import WarpEntitySource

        backend, MemoryReader = self.make_backend()
        p = XD_US_REV0
        count_root = 0x80700100
        table = 0x80700200
        backend.put(p.warp_count_root, self.be32(count_root))
        backend.put(count_root, self.be32(2))
        # slot 0 left all-zero by default (empty/inactive marker).
        backend.put(table + p.warp_record_stride, self.be32(0x24010000))
        backend.put(
            table + p.warp_record_stride + p.warp_position_offset,
            self.f32(10.0) + self.f32(0.0) + self.f32(-20.0),
        )
        backend.put(p.warp_data_root, self.be32(table))

        memory = MemoryReader(backend, p)
        source = WarpEntitySource(memory, p, pose_source=FakePoseSource())
        entities = source.entities()
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].identity, ("warp", 1))
        self.assertAlmostEqual(entities[0].position.x, 10.0)
        self.assertAlmostEqual(entities[0].position.z, -20.0)
        self.assertIsNone(entities[0].label)
        self.assertIsNone(entities[0].interaction_distance)

    def test_records_far_beyond_warp_max_distance_are_excluded(self):
        """The table has no floor-ID field (confirmed a single global
        table spanning the whole game), so records must be bounded by
        distance instead -- this reproduces the live "115 available"
        report and confirms the fix."""
        from battle_narrator.entity_sources import WarpEntitySource

        backend, MemoryReader = self.make_backend()
        p = XD_US_REV0
        count_root = 0x80700100
        table = 0x80700200
        backend.put(p.warp_count_root, self.be32(count_root))
        backend.put(count_root, self.be32(2))
        # Slot 0: nearby, should be included.
        backend.put(table, self.be32(0x24010000))
        backend.put(
            table + p.warp_position_offset,
            self.f32(10.0) + self.f32(0.0) + self.f32(-20.0),
        )
        # Slot 1: on some other floor entirely, far past warp_max_distance.
        backend.put(table + p.warp_record_stride, self.be32(0x24010000))
        backend.put(
            table + p.warp_record_stride + p.warp_position_offset,
            self.f32(5000.0) + self.f32(0.0) + self.f32(5000.0),
        )
        backend.put(p.warp_data_root, self.be32(table))

        memory = MemoryReader(backend, p)
        source = WarpEntitySource(memory, p, pose_source=FakePoseSource())
        entities = source.entities()
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].identity, ("warp", 0))


class FakePoseSource:
    def player_pose(self):
        return PlayerPose(Position(0, 0, 0), 0)


class LifecycleWiringTests(unittest.TestCase):
    """#18 battle-context suppression. The lifecycle's ACTIVE state is the
    GSmsg-manager-initialized steady state, which is live-confirmed to also
    cover ordinary overworld play (manager_root == dialogue_manager_root),
    not just battle -- so entity nav must be polled in BOTH GSMSG_WAITING
    and ACTIVE (matching poll_npc_sounds's placement exactly). Actual
    battle/menu suppression is the navigator's own window-open/dialogue
    context check (see ContextTests), not lifecycle-state gating."""

    def test_entity_nav_polled_in_both_waiting_and_active_states(self):
        class CountingEntityNav:
            def __init__(self):
                self.calls = 0

            def poll_once(self, dialogue_active=False):
                self.calls += 1

            def clear(self, reason):
                pass

        class Speaker:
            def speak(self, text, interrupt=False):
                return True

        class Connection:
            def hook(self):
                pass

            def is_readable(self):
                return True

            def verify_profile(self):
                pass

            def close(self):
                pass

        class Tasks:
            def resolve(self):
                return 1, 2, 3

        class Narrator:
            stop_requested = False

            def poll_once(self):
                pass

        entity_nav = CountingEntityNav()
        controller = LifecycleController(
            Connection(), lambda: Tasks(), lambda tasks: Narrator(),
            Speaker(), test_logger(), waiting_interval=0, active_interval=0,
            entity_nav_factory=lambda: entity_nav,
        )
        controller.step()  # cascades through GSMSG_WAITING (polls once)
        # then straight into ACTIVE since Tasks.resolve() never raises.
        self.assertEqual(controller.state, LifecycleState.ACTIVE)
        self.assertEqual(entity_nav.calls, 1)
        controller.step()  # an ACTIVE-state tick must ALSO poll entity nav
        self.assertEqual(entity_nav.calls, 2)


class FacingAwareInteractionTests(unittest.TestCase):
    """The game's peopleTalkCheck refuses to talk unless the player is
    turned toward the target, within profile.talk_cone_degrees (40, read out
    of updateChat's literal argument). Distance alone is not enough, and
    reporting it as though it were told the player to press A when the game
    would ignore them."""

    def test_facing_error_is_zero_when_pointed_straight_at_target(self):
        # facing 0 means -Z in this engine's convention.
        pose = PlayerPose(Position(0, 0, 0), 0.0, facing=0.0)
        self.assertAlmostEqual(facing_error(pose, Position(0, 0, -10)), 0.0, places=4)

    def test_facing_error_is_180_when_pointed_directly_away(self):
        pose = PlayerPose(Position(0, 0, 0), 0.0, facing=0.0)
        self.assertAlmostEqual(facing_error(pose, Position(0, 0, 10)), 180.0, places=4)

    def test_in_range_but_facing_away_is_reported_separately(self):
        pose = PlayerPose(Position(0, 0, 0), 0.0, facing=0.0)
        behind = entity(0, 0, 1, label="Shopkeeper", interaction=2.0)
        text = describe_entity(XD_US_REV0, "npc", behind, pose)
        self.assertIn("In range but facing away", text)
        self.assertNotIn("Interaction available", text)

    def test_in_range_and_facing_target_still_reports_available(self):
        pose = PlayerPose(Position(0, 0, 0), 0.0, facing=0.0)
        ahead = entity(0, 0, -1, label="Shopkeeper", interaction=2.0)
        self.assertIn(
            "Interaction available", describe_entity(XD_US_REV0, "npc", ahead, pose))

    def test_just_inside_and_just_outside_the_real_cone(self):
        cone = XD_US_REV0.talk_cone_degrees
        for offset, expected in ((cone - 5.0, "Interaction available"),
                                 (cone + 5.0, "In range but facing away")):
            angle = math.radians(offset)
            # Target one unit away, `offset` degrees off the facing axis.
            target = entity(0, math.sin(angle), -math.cos(angle),
                            label="Shopkeeper", interaction=2.0)
            pose = PlayerPose(Position(0, 0, 0), 0.0, facing=0.0)
            self.assertIn(
                expected, describe_entity(XD_US_REV0, "npc", target, pose),
                f"{offset:.0f} degrees off a {cone:.0f} degree cone")

    def test_missing_facing_falls_back_to_distance_only(self):
        """A failed facing read must not turn every in-range NPC into
        'facing away' -- it degrades to the previous distance-only wording."""
        pose = PlayerPose(Position(0, 0, 0), 0.0, facing=None)
        behind = entity(0, 0, 1, label="Shopkeeper", interaction=2.0)
        self.assertIn(
            "Interaction available", describe_entity(XD_US_REV0, "npc", behind, pose))

    def test_regression_the_live_npc_g_case(self):
        """Reproduces the exact live report: standing 1.72 units from an NPC
        with a 3.0 reach and a valid talk script, which would not talk. The
        player was facing 149.6 degrees away from it."""
        pose = PlayerPose(Position(129.41, 0.0, 139.33), 1.7233, facing=-0.7719)
        npc_g = entity(9, 129.0, 141.0, label="NPC G", interaction=3.0)
        self.assertAlmostEqual(facing_error(pose, npc_g.position), 149.6, delta=1.0)
        text = describe_entity(XD_US_REV0, "npc", npc_g, pose)
        self.assertIn("In range but facing away", text)


class StandStillAutoRepeatTests(unittest.TestCase):
    """Re-announce the current selection once the player has stood still for
    `entity_nav_auto_repeat_seconds` (project owner's request, 2026-08-04).

    Keyed to STOPPING, not to elapsed time: once per stop, re-armed only by
    moving again."""

    DELAY = XD_US_REV0.entity_nav_auto_repeat_seconds

    def _setup(self, entities=None):
        entities = entities or [entity(0, 0, 30, label="Jovi")]
        pose = PlayerPose(Position(0, 0, 0), 0.0)
        source = MovableSource(entities, pose)
        clock = FakeClock()
        hotkeys = hotkey_map()
        nav, _ = navigator(entities, pose=pose, hotkeys=hotkeys, clock=clock,
                           source=source)
        return nav, source, clock, hotkeys

    def _select(self, nav, hotkeys):
        hotkeys["next"].fire = True
        nav.poll_once()
        nav.speech.calls.clear()

    def _hold_still(self, nav, clock, seconds, step=0.25):
        elapsed = 0.0
        while elapsed < seconds:
            clock.advance(step)
            elapsed += step
            nav.poll_once()

    def test_standing_still_repeats_the_selection(self):
        nav, source, clock, hotkeys = self._setup()
        self._select(nav, hotkeys)
        source.walk_to(0.0, 10.0)          # move: re-arms the auto-repeat
        nav.poll_once()
        nav.speech.calls.clear()
        self._hold_still(nav, clock, self.DELAY + 0.5)
        self.assertEqual(
            len(nav.speech.calls), 1,
            f"expected exactly one automatic repeat, got "
            f"{[c[1] for c in nav.speech.calls]}")
        self.assertIn("o'clock", nav.speech.calls[0][1])
        self.assertIn("distance", nav.speech.calls[0][1])
        self.assertIn("Jovi", nav.speech.calls[0][1])

    def test_it_does_not_fire_before_the_delay(self):
        nav, source, clock, hotkeys = self._setup()
        self._select(nav, hotkeys)
        source.walk_to(0.0, 10.0)
        nav.poll_once()
        nav.speech.calls.clear()
        self._hold_still(nav, clock, self.DELAY - 0.5)
        self.assertEqual(nav.speech.calls, [])

    def test_it_fires_once_per_stop_not_repeatedly(self):
        nav, source, clock, hotkeys = self._setup()
        self._select(nav, hotkeys)
        source.walk_to(0.0, 10.0)
        nav.poll_once()
        nav.speech.calls.clear()
        self._hold_still(nav, clock, self.DELAY * 5)
        self.assertEqual(
            len(nav.speech.calls), 1,
            "standing still produced a repeating announcement")

    def test_moving_again_re_arms_it(self):
        nav, source, clock, hotkeys = self._setup()
        self._select(nav, hotkeys)
        source.walk_to(0.0, 10.0)
        nav.poll_once()
        nav.speech.calls.clear()
        self._hold_still(nav, clock, self.DELAY + 0.5)
        self.assertEqual(len(nav.speech.calls), 1)
        source.walk_to(0.0, 20.0)
        nav.poll_once()
        self._hold_still(nav, clock, self.DELAY + 0.5)
        self.assertEqual(
            len(nav.speech.calls), 2,
            "walking on and stopping again did not produce a second repeat")

    def test_a_deliberate_press_is_not_echoed_a_moment_later(self):
        """Pressing next/repeat while already standing still must satisfy
        the stop -- otherwise every press is followed by the same sentence
        again 1.5 seconds later."""
        nav, source, clock, hotkeys = self._setup()
        self._select(nav, hotkeys)
        self._hold_still(nav, clock, 0.5)
        hotkeys["repeat"].fire = True
        nav.poll_once()
        self.assertEqual(len(nav.speech.calls), 1, "the press itself spoke")
        self._hold_still(nav, clock, self.DELAY + 0.5)
        self.assertEqual(
            len(nav.speech.calls), 1,
            "the deliberate press was echoed by the auto-repeat")

    def test_nothing_is_said_with_no_selection(self):
        nav, source, clock, hotkeys = self._setup()
        self._hold_still(nav, clock, self.DELAY * 3)
        self.assertEqual(nav.speech.calls, [])

    def test_a_vanished_entity_is_silent_and_keeps_the_selection(self):
        """Unlike the manual repeat, which says so and clears. An unprompted
        announcement must not act on what could be a transient bad read."""
        nav, source, clock, hotkeys = self._setup()
        self._select(nav, hotkeys)
        source.walk_to(0.0, 10.0)
        nav.poll_once()
        nav.speech.calls.clear()
        selected = nav.state.selected_identity
        source._entities = []
        self._hold_still(nav, clock, self.DELAY + 0.5)
        self.assertEqual(nav.speech.calls, [])
        self.assertEqual(nav.state.selected_identity, selected)

    def test_an_unreadable_pose_stays_quiet(self):
        nav, source, clock, hotkeys = self._setup()
        self._select(nav, hotkeys)
        source.walk_to(0.0, 10.0)
        nav.poll_once()
        nav.speech.calls.clear()
        source.fail = True
        self._hold_still(nav, clock, self.DELAY * 3)
        self.assertEqual(nav.speech.calls, [])

    def test_a_menu_suppresses_it_and_closing_does_not_trigger_it(self):
        nav, source, clock, hotkeys = self._setup()
        self._select(nav, hotkeys)
        source.walk_to(0.0, 10.0)
        nav.poll_once()
        nav.speech.calls.clear()
        nav.memory.window_head = 0x80000000      # a menu opens
        self._hold_still(nav, clock, self.DELAY * 2)
        self.assertEqual(nav.speech.calls, [], "spoke while a menu was open")
        nav.memory.window_head = 0               # and closes
        nav.poll_once()
        self.assertEqual(
            nav.speech.calls, [],
            "closing the menu immediately triggered a repeat")


class AutoRepeatToggleTests(unittest.TestCase):
    """ctrl+L: stop re-announcing the selection when the player stands still.

    Added 2026-08-19 at the project owner's request. The setting already
    existed in the settings menu; what was missing was a way to reach it
    without opening a menu, which matters because the thing being switched
    off is an interruption that happens while you are trying to think."""

    def spoken(self, nav):
        return [text for _event, text, _dedupe, _interrupt in nav.speech.calls]

    def test_it_is_on_by_default(self):
        nav, _ = navigator([entity(0, 0, -10, label="Rui")])
        self.assertTrue(nav.auto_repeat_enabled)

    def test_the_hotkey_turns_it_off_and_says_so(self):
        """The player cannot see a checkbox, and the thing switched is
        something that happens when they do nothing -- without a spoken
        result the only way to learn the state is to stand still and wait
        to find out."""
        keys = hotkey_map()
        nav, _ = navigator([entity(0, 0, -10, label="Rui")], hotkeys=keys)
        keys["auto_repeat"].fire = True
        nav.poll_once()
        self.assertFalse(nav.auto_repeat_enabled)
        self.assertEqual(self.spoken(nav)[-1], "Repeat when you stop, off")

    def test_it_toggles_back_on(self):
        keys = hotkey_map()
        nav, _ = navigator([entity(0, 0, -10, label="Rui")], hotkeys=keys)
        for _ in range(2):
            keys["auto_repeat"].fire = True
            nav.poll_once()
        self.assertTrue(nav.auto_repeat_enabled)
        self.assertEqual(self.spoken(nav)[-1], "Repeat when you stop, on")

    def test_it_works_before_anything_is_selected(self):
        keys = hotkey_map()
        nav, _ = navigator([], hotkeys=keys)
        keys["auto_repeat"].fire = True
        nav.poll_once()
        self.assertFalse(nav.auto_repeat_enabled)

    def test_the_manual_repeat_key_still_works_when_it_is_off(self):
        """Deliberate: silencing something that speaks on its own is not
        the same as giving up the ability to ask for it."""
        keys = hotkey_map()
        nav, _ = navigator([entity(0, 0, -10, label="Rui")], hotkeys=keys)
        keys["next_category"].fire = True
        nav.poll_once()
        keys["auto_repeat"].fire = True
        nav.poll_once()
        keys["repeat"].fire = True
        nav.poll_once()
        self.assertIn("Rui", self.spoken(nav)[-1])

    def test_a_missing_hotkey_does_not_break_the_poll_loop(self):
        keys = hotkey_map()
        del keys["auto_repeat"]
        nav, _ = navigator([entity(0, 0, -10, label="Rui")], hotkeys=keys)
        keys["next_category"].fire = True
        nav.poll_once()
        self.assertIn("Rui", self.spoken(nav)[-1])

    def test_the_store_is_told_so_the_choice_survives_a_restart(self):
        keys = hotkey_map()
        nav, _ = navigator([entity(0, 0, -10, label="Rui")], hotkeys=keys)
        seen = []
        nav.on_auto_repeat_change = seen.append
        for _ in range(2):
            keys["auto_repeat"].fire = True
            nav.poll_once()
        self.assertEqual(seen, [False, True])


if __name__ == "__main__":
    unittest.main()

