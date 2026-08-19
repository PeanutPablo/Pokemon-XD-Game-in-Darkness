import logging
import unittest
from dataclasses import dataclass

from battle_narrator.audio_guide import (
    AudioGuideReader, GuideModes, guide_values,
)
from battle_narrator.collision_probe import CollisionTriangle, WalkTriangle
from battle_narrator.entities import Entity
from battle_narrator.entity_nav import NavState
from battle_narrator.navigation_service import NavigationResult, NavigationService, RouteConfidence
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.pathfinding import TILE_SIZE, build_room_geometry
from battle_narrator.phase1b_lifecycle import LifecycleController


class Hotkey:
    def __init__(self): self.fire = False
    def poll(self):
        result = self.fire; self.fire = False; return result


class Speech:
    def __init__(self): self.calls = []
    def emit(self, event, text, deduplicate=False, interrupt=False):
        self.calls.append(text)


class Player:
    def __init__(self):
        self.played = []
        self.stopped = 0
    def play(self, path, pan, pitch, gain):
        self.played.append((path, pan, gain, pitch))
    def stop(self):
        self.stopped += 1


class Source:
    def __init__(self, entities, pose=None):
        self.items = entities
        self.pose = pose or PlayerPose(Position(0, 0, 0), 0)
    def entities(self):
        return list(self.items)
    def player_pose(self):
        return self.pose


class FakeEntityNav:
    def __init__(self, sources, category_key=None, selected_identity=None):
        self.sources = sources
        self.state = NavState(category_key=category_key, selected_identity=selected_identity)


class FixedResultNavigation:
    """Test double returning a caller-supplied NavigationResult verbatim --
    used to test AudioGuideReader's own reaction to confidence/progress
    signals in isolation from NavigationService's real routing logic
    (already covered separately in test_navigation_service.py)."""
    def __init__(self, result):
        self.result = result
    # Signatures track `NavigationService` exactly, including the
    # `player_position` the route builder needs to seed an off-floor
    # destination somewhere the player can reach. A double that quietly
    # omits a real parameter is how the `PartySlot.nickname` crash reached
    # production with a green suite (see PLAYTHROUGH_BARRIER_LOG #10).
    def begin(self, floor_id, destination_position, player_position=None,
              destination_region=None):
        self.begun_with_player_position = player_position
        self.begun_with_region = destination_region

    def update(self, floor_id, destination_position, player_position=None,
               destination_region=None):
        self.updated_with_region = destination_region
    def next_waypoint(self, player_position):
        return self.result
    def clear(self):
        pass


class PoseSource:
    def __init__(self, floor_id=1):
        self.floor_id = floor_id
    def current_floor_id(self):
        return self.floor_id


def entity(identity="e1", x=10.0, y=0.0, z=0.0, label=None):
    return Entity(category="npc", identity=identity, label=label,
                 position=Position(x, y, z), interaction_distance=None)


def walk_tile(ix, iz, tile_size=TILE_SIZE, y=0.0, layer=0):
    x0, z0 = ix * tile_size, iz * tile_size
    x1, z1 = x0 + tile_size, z0 + tile_size
    return [
        WalkTriangle(
            ((x0, y, z0), (x1, y, z0), (x1, y, z1)), (0.0, 1.0, 0.0),
            layer, layer, 0xFF, 0),
        WalkTriangle(
            ((x0, y, z0), (x1, y, z1), (x0, y, z1)), (0.0, 1.0, 0.0),
            layer, layer, 0xFF, 0),
    ]


def walk_rect(ix0, ix1, iz0, iz1, tile_size=TILE_SIZE, y=0.0, layer=0):
    triangles = []
    for ix in range(ix0, ix1):
        for iz in range(iz0, iz1):
            triangles.extend(walk_tile(ix, iz, tile_size, y, layer))
    return triangles


def wall_segment(p0, p1, y0=-10.0, y1=10.0):
    (x0, z0), (x1, z1) = p0, p1
    return [
        CollisionTriangle(
            ((x0, y0, z0), (x1, y0, z1), (x1, y1, z1)), (0.0, 0.0, 1.0), 0, 0),
        CollisionTriangle(
            ((x0, y0, z0), (x1, y1, z1), (x0, y1, z0)), (0.0, 0.0, 1.0), 0, 0),
    ]


class GuideValuesTests(unittest.TestCase):
    def test_pitch_is_higher_when_target_is_ahead_than_behind(self):
        # Project owner's correction (2026-07-30): pitch signals
        # forward/backward facing, not proximity. Pose yaw=0 faces -Z.
        pose = PlayerPose(Position(0, 0, 0), 0)
        ahead = guide_values(pose, Position(0, 0, -10), 120.0)
        behind = guide_values(pose, Position(0, 0, 10), 120.0)
        self.assertGreater(ahead[2], 1.0)
        self.assertLess(behind[2], 1.0)
        self.assertGreater(ahead[2], behind[2])

    def test_pitch_does_not_depend_on_distance_when_facing_is_unchanged(self):
        # Same direction (dead ahead), very different distances -- pitch
        # (now a facing signal) must read identically; only gain/proximity
        # should differ with distance. This directly replaces the pre-
        # correction test that asserted the opposite.
        pose = PlayerPose(Position(0, 0, 0), 0)
        far = guide_values(pose, Position(0, 0, -100), 120.0)
        near = guide_values(pose, Position(0, 0, -10), 120.0)
        self.assertAlmostEqual(far[2], near[2])

    def test_pitch_is_neutral_when_target_is_directly_to_the_side(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        horizontal, pan, pitch, gain = guide_values(pose, Position(10, 0, 0), 120.0)
        self.assertAlmostEqual(pitch, 1.0)

    def test_pan_reflects_left_right(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        # right side relative to forward-facing yaw 0.
        right = guide_values(pose, Position(10, 0, 0), 120.0)
        left = guide_values(pose, Position(-10, 0, 0), 120.0)
        self.assertGreater(right[1], 0)
        self.assertLess(left[1], 0)

    def test_zero_distance_is_centered_pan(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        horizontal, pan, pitch, gain = guide_values(pose, Position(0, 0, 0), 120.0)
        self.assertEqual(pan, 0.0)

    def test_proximity_distance_overrides_gain_only_not_pitch(self):
        pose = PlayerPose(Position(0, 0, 0), 0)
        # Same target position (so pan/pitch/horizontal are identical), but
        # a much larger proximity_distance should read "cold" gain instead
        # of "hot" -- pitch (a facing signal now) must be untouched by it.
        near_hot = guide_values(pose, Position(0, 0, -10), 120.0)
        near_cold = guide_values(
            pose, Position(0, 0, -10), 120.0, proximity_distance=115.0)
        self.assertEqual(near_hot[1], near_cold[1])  # pan unaffected
        self.assertEqual(near_hot[0], near_cold[0])  # horizontal unaffected
        self.assertEqual(near_hot[2], near_cold[2])  # pitch unaffected
        self.assertLess(near_cold[3], near_hot[3])   # gain: colder


class AudioGuideReaderTests(unittest.TestCase):
    def setUp(self):
        self.speech = Speech()
        self.hotkey = Hotkey()
        self.player = Player()

    def _navigation(self, floor_id=1, extra_wall_triangles=()):
        navigation = NavigationService(
            collision_dir="unused", room_codes={},
            logger=logging.getLogger("audio-guide-test-navigation"))
        walk_triangles = walk_rect(-20, 20, -20, 20)
        navigation._geometry_cache[floor_id] = build_room_geometry(
            tuple(walk_triangles), tuple(extra_wall_triangles))
        return navigation

    def _reader(self, entity_nav, navigation=None, floor_id=1):
        return AudioGuideReader(
            entity_nav, self.player, "guide.wav", self.hotkey,
            self.speech, logging.getLogger("audio-guide-test"),
            navigation if navigation is not None else self._navigation(floor_id),
            PoseSource(floor_id),
            max_distance=120.0, arrival_distance=4.0,
        )

    def test_toggle_with_no_selection_announces_and_stays_off(self):
        nav = FakeEntityNav({"npc": Source([])})
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("No entity selected to guide to.", self.speech.calls)

    def test_toggle_on_with_selection_activates(self):
        source = Source([entity()])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        self.assertTrue(reader.active)
        self.assertIn("Guide on.", self.speech.calls)

    def test_toggle_off_stops_player_and_announces(self):
        source = Source([entity()])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        self.hotkey.fire = True
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertEqual(self.player.stopped, 1)
        self.assertIn("Guide off.", self.speech.calls)

    def test_active_guide_plays_tone_toward_target(self):
        source = Source([entity(x=10.0, z=0.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        self.assertEqual(len(self.player.played), 1)

    def test_repeat_interval_shrinks_when_closer(self):
        far_source = Source([entity(x=0.0, z=-100.0)])
        near_source = Source([entity(x=0.0, z=-10.0)])
        nav = FakeEntityNav({"npc": far_source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        far_interval = reader.next_due

        nav2 = FakeEntityNav({"npc": near_source}, category_key="npc", selected_identity="e1")
        reader2 = self._reader(nav2)
        self.hotkey.fire = True
        reader2.poll_once()
        reader2.poll_once()
        near_interval = reader2.next_due
        self.assertLess(near_interval, far_interval)

    def test_gain_warms_progressively_across_a_long_route_not_only_near_the_end(self):
        # Live-caught bug (2026-07-30): "the pitch/rate doesn't change...
        # unless I'm really close to the target." (Pitch has since been
        # repurposed to a facing signal -- see GuideValuesTests -- so gain
        # is now the sole proximity/"hot-cold" signal this test covers.) A
        # route longer than max_distance=120 (by actual walked distance)
        # must still show real progress partway through, not stay clamped
        # near "cold" until the last stretch.
        source = Source(
            [entity(x=140.0, z=0.0)],
            pose=PlayerPose(Position(-140.0, 0.0, 0.0), 0))
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()  # activation
        reader.poll_once()  # first active poll, route just built
        start_gain = self.player.played[-1][2]

        # Walk halfway to the destination across small, realistic steps --
        # not one large synthetic jump. Real-progress validation (see
        # test_navigation_service.py) now correctly treats a big jump with
        # no waypoint advance as a suspicious non-walking event, same as a
        # real teleport/warp would be; steps this small never overshoot a
        # waypoint's own capture radius, matching genuine continuous
        # walking rather than exercising that (separate, pre-existing)
        # overshoot edge case. NOT "really close" to the destination yet.
        x = -140.0
        while x < -0.5:
            x = min(x + 4.0, 0.0)
            source.pose = PlayerPose(Position(x, 0.0, 0.0), 0)
            reader.next_due = 0.0
            reader.poll_once()
        midway_gain = self.player.played[-1][2]

        self.assertGreater(
            midway_gain, start_gain + 0.05,
            "gain showed no meaningful progress at the route's halfway "
            "point, only presumably warming up near the very end",
        )

    def test_arrival_announces_and_stops(self):
        source = Source([entity(x=1.0, z=0.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Arrived.", self.speech.calls)
        self.assertEqual(self.player.stopped, 1)

    def test_standing_directly_beneath_a_target_is_not_arrival(self):
        """Arrival used `relative_geometry`'s HORIZONTAL component alone and
        discarded the `vertical` one it already returns, so being under a
        target on an upper deck announced "Arrived." -- the same discarded-Y
        mistake that let a fallen player capture a waypoint on the terrace
        above them (see test_navigation_service.TerraceFallCaptureTests)."""
        source = Source([entity(x=1.0, y=40.0, z=0.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        self.assertTrue(
            reader.active,
            "the guide stopped as though the player had arrived at a target "
            "40 units above their head")
        self.assertNotIn("Arrived.", self.speech.calls)

    def test_a_target_on_a_step_still_counts_as_arrival(self):
        """The height gate must not break arrival at ordinary targets that
        sit slightly above or below the player -- a step, a kerb, a slope."""
        source = Source([entity(x=1.0, y=3.0, z=0.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Arrived.", self.speech.calls)

    def test_selection_change_stops_guide(self):
        source = Source([entity(identity="e1"), entity(identity="e2", x=5.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        nav.state.selected_identity = "e2"
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Guide stopped: selection changed.", self.speech.calls)

    def test_target_gone_stops_guide(self):
        source = Source([entity()])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        source.items = []
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Guide stopped: target no longer available.", self.speech.calls)

    def test_inactive_guide_ignores_polls(self):
        source = Source([entity()])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        reader.poll_once()
        self.assertEqual(self.player.played, [])
        self.assertEqual(self.speech.calls, [])

    # -- dialogue suppression ------------------------------------------
    #
    # The guide goes SILENT while a conversation is open and resumes
    # afterwards. It is deliberately not turned off: entity-nav already
    # keeps its selection across a conversation on purpose, and throwing
    # the route away would make "find someone, talk to them, carry on"
    # cost a re-press and a route rebuild every time.

    def _active_reader(self):
        source = Source([entity(x=10.0, z=0.0)])
        nav = FakeEntityNav(
            {"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        self.player.played.clear()
        self.player.stopped = 0
        self.speech.calls.clear()
        return reader

    def test_dialogue_silences_an_active_guide_without_turning_it_off(self):
        reader = self._active_reader()
        reader.poll_once(silenced=True)
        self.assertEqual(self.player.played, [])
        self.assertEqual(self.speech.calls, [])
        self.assertTrue(reader.active)
        self.assertEqual(self.player.stopped, 1)

    def test_a_sound_already_playing_is_cut_off_once_not_every_poll(self):
        reader = self._active_reader()
        for _ in range(5):
            reader.poll_once(silenced=True)
        self.assertEqual(self.player.stopped, 1)

    def test_the_guide_resumes_by_itself_when_the_dialogue_closes(self):
        reader = self._active_reader()
        reader.poll_once(silenced=True)
        reader.poll_once()
        self.assertTrue(reader.active)
        self.assertEqual(len(self.player.played), 1)

    def test_arrival_during_dialogue_is_deferred_not_spoken_over_it(self):
        # Standing on the target while a conversation is up must not fire
        # "Arrived." into the middle of it. The fact is still true when the
        # box closes, and that is when it is said.
        source = Source([entity(x=0.0, z=0.0)])
        nav = FakeEntityNav(
            {"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        self.speech.calls.clear()
        reader.poll_once(silenced=True)
        self.assertEqual(self.speech.calls, [])
        self.assertTrue(reader.active)
        reader.poll_once()
        self.assertIn("Arrived.", self.speech.calls)
        self.assertFalse(reader.active)

    def test_a_press_during_dialogue_is_dropped_not_queued(self):
        # Acting on it would have to speak to be usable, which is the thing
        # being avoided. The chord is still POLLED so its edge state stays
        # honest -- see poll_once.
        reader = self._active_reader()
        self.hotkey.fire = True
        reader.poll_once(silenced=True)
        self.assertTrue(reader.active)
        self.assertEqual(self.speech.calls, [])
        reader.poll_once()
        self.assertTrue(reader.active)
        self.assertEqual(self.speech.calls, [])

    def test_dialogue_while_off_stays_off_and_touches_nothing(self):
        source = Source([entity()])
        nav = FakeEntityNav(
            {"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        reader.poll_once(silenced=True)
        self.assertFalse(reader.active)
        self.assertEqual(self.player.stopped, 0)
        self.assertEqual(self.speech.calls, [])

    def test_clear_drops_suppression_so_a_fresh_guide_is_not_born_silent(self):
        reader = self._active_reader()
        reader.poll_once(silenced=True)
        self.assertTrue(reader.suppressed)
        reader.clear("test")
        self.assertFalse(reader.suppressed)

    def test_lifecycle_accepts_audio_guide_factory(self):
        factory = lambda entity_nav_reader: self._reader(
            FakeEntityNav({"npc": Source([])}))
        controller = LifecycleController(
            object(), lambda: None, lambda tasks: None, object(),
            logging.getLogger("lifecycle-audio-guide-test"),
            audio_guide_factory=factory,
        )
        self.assertIs(controller.audio_guide_factory, factory)
        self.assertIsNone(controller.audio_guide_reader)

    def test_wall_forces_the_tone_to_aim_around_it_not_through(self):
        # The wall spans the full west edge of the -20..20 test floor
        # (world x -160..0) at z=0 -- the only opening is east of x=0.
        wall = wall_segment((-160.0, 0.0), (0.0, 0.0))
        navigation = self._navigation(extra_wall_triangles=wall)
        player_pose = PlayerPose(Position(-70.0, 0.0, -70.0), 0)
        source = Source([entity(x=-70.0, z=70.0)], pose=player_pose)
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav, navigation=navigation)
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        self.assertEqual(len(self.player.played), 1)
        # A straight-line-blind tone would read pan==0 (target is due
        # north, same x). The routed tone must instead point noticeably
        # rightward (east), toward the gap.
        self.assertGreater(self.player.played[0][1], 0.1)

    def test_fallback_message_spoken_once_when_unreachable(self):
        # A destination with no walk-model coverage anywhere near the
        # player is genuinely unreachable -- there's no default-open
        # fallback anymore (see pathfinding.py's own top docstring). This
        # isolated walk patch sits nowhere near the player.
        far = walk_rect(50, 55, 50, 55)
        navigation = NavigationService(
            collision_dir="unused", room_codes={},
            logger=logging.getLogger("audio-guide-test-navigation"))
        navigation._geometry_cache[1] = build_room_geometry(tuple(far), ())
        player_pose = PlayerPose(Position(20.0, 0.0, 20.0), 0)
        source = Source([entity(x=420.0, z=420.0)], pose=player_pose)
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav, navigation=navigation)
        self.hotkey.fire = True
        reader.poll_once()  # activation
        reader.poll_once()  # first active poll: fallback should engage
        self.assertIn(
            "No walkable path found; guiding directly.", self.speech.calls)
        self.assertEqual(len(self.player.played), 1)

        reader.poll_once()
        self.assertEqual(
            self.speech.calls.count("No walkable path found; guiding directly."),
            1,
        )

    def test_moving_target_continues_to_guide_without_spurious_fallback(self):
        source = Source([entity(identity="e1", x=10.0, z=0.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._reader(nav)
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        self.assertEqual(len(self.player.played), 1)

        source.items = [entity(identity="e1", x=90.0, z=40.0)]
        reader.next_due = 0.0
        reader.poll_once()
        self.assertEqual(len(self.player.played), 2)
        self.assertNotIn(
            "No walkable path found; guiding directly.", self.speech.calls)

    def test_verified_confidence_does_not_dampen_pitch(self):
        # RouteConfidence no longer has an UNCERTAIN state that dampens
        # pitch (routing is always built from real walk-model data now --
        # see navigation_service.py's own docstring) -- this pins that a
        # VERIFIED result still plays pitch at its full, undamped value.
        source = Source([entity(x=0.0, z=-10.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        fixed_result = NavigationResult(
            target_position=Position(0.0, 0.0, -10.0), path_available=True,
            fallback_started=False, confidence=RouteConfidence.VERIFIED)
        reader = self._reader(nav, navigation=FixedResultNavigation(fixed_result))
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        _, _, _, pitch = self.player.played[0]
        self.assertAlmostEqual(pitch, 2.0)

    def test_progress_invalidated_speaks_the_distinct_fallback_message(self):
        source = Source([entity(x=0.0, z=-10.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        fixed_result = NavigationResult(
            target_position=None, path_available=False, fallback_started=False,
            confidence=RouteConfidence.DIRECT_FALLBACK, progress_invalidated=True)
        reader = self._reader(nav, navigation=FixedResultNavigation(fixed_result))
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        self.assertIn(
            "Walkable route could not be verified; guiding directly.",
            self.speech.calls)

    def test_progress_invalidated_message_is_not_confused_with_the_geometry_fallback_message(self):
        source = Source([entity(x=0.0, z=-10.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        fixed_result = NavigationResult(
            target_position=None, path_available=False, fallback_started=True,
            confidence=RouteConfidence.DIRECT_FALLBACK, progress_invalidated=False)
        reader = self._reader(nav, navigation=FixedResultNavigation(fixed_result))
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        self.assertIn("No walkable path found; guiding directly.", self.speech.calls)
        self.assertNotIn(
            "Walkable route could not be verified; guiding directly.",
            self.speech.calls)

    def test_waypoint_advanced_plays_the_waypoint_reached_sound(self):
        source = Source([entity(x=0.0, z=-10.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        fixed_result = NavigationResult(
            target_position=Position(0.0, 0.0, -10.0), path_available=True,
            fallback_started=False, waypoint_advanced=True)
        reader = self._reader(nav, navigation=FixedResultNavigation(fixed_result))
        reader.waypoint_sound_path = "waypoint.wav"
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        waypoint_plays = [play for play in self.player.played if play[0] == "waypoint.wav"]
        self.assertEqual(len(waypoint_plays), 1)

    def test_no_waypoint_advance_does_not_play_the_waypoint_sound(self):
        source = Source([entity(x=0.0, z=-10.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        fixed_result = NavigationResult(
            target_position=Position(0.0, 0.0, -10.0), path_available=True,
            fallback_started=False, waypoint_advanced=False)
        reader = self._reader(nav, navigation=FixedResultNavigation(fixed_result))
        reader.waypoint_sound_path = "waypoint.wav"
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        waypoint_plays = [play for play in self.player.played if play[0] == "waypoint.wav"]
        self.assertEqual(len(waypoint_plays), 0)


class DirectBeaconModeTests(unittest.TestCase):
    """`navigation=None` -- the ctrl+g mode: one beacon sitting on the
    entity itself, no routing of any kind (project owner, 2026-08-04: "i
    want what's on g to be on n and i want g to be just one beacon that is
    on the entity")."""

    def setUp(self):
        self.speech = Speech()
        self.hotkey = Hotkey()
        self.player = Player()

    def _beacon(self, entity_nav, floor_id=1):
        return AudioGuideReader(
            entity_nav, self.player, "beacon.wav", self.hotkey, self.speech,
            logging.getLogger("audio-guide-beacon-test"), None,
            PoseSource(floor_id),
            max_distance=120.0, arrival_distance=4.0, name="Beacon")

    def test_beacon_aims_straight_at_the_entity_ignoring_obstacles(self):
        """The routed mode steers around a wall (see
        `test_wall_forces_the_tone_to_aim_around_it_not_through`). With the
        SAME wall in place the direct beacon must not: it reports where the
        entity is, which is the whole point of having it as a separate
        mode."""
        player_pose = PlayerPose(Position(-70.0, 0.0, -70.0), 0)
        source = Source([entity(x=-70.0, z=70.0)], pose=player_pose)
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._beacon(nav)
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        self.assertEqual(len(self.player.played), 1)
        # Target is due north, same x -- a straight-line beacon reads centred.
        self.assertAlmostEqual(self.player.played[0][1], 0.0, places=6)

    def test_beacon_speaks_its_own_name(self):
        source = Source([entity()])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._beacon(nav)
        self.hotkey.fire = True
        reader.poll_once()
        self.assertIn("Beacon on.", self.speech.calls)
        self.hotkey.fire = True
        reader.poll_once()
        self.assertIn("Beacon off.", self.speech.calls)

    def test_beacon_never_speaks_route_messages(self):
        """Direct mode has no route to fail, so none of the routed mode's
        route announcements may ever come out of it."""
        source = Source([entity(x=90.0, z=90.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._beacon(nav)
        self.hotkey.fire = True
        reader.poll_once()
        for _ in range(5):
            reader.next_due = 0.0
            reader.poll_once()
        for message in self.speech.calls:
            self.assertNotIn("walkable", message.lower())

    def test_beacon_still_announces_arrival(self):
        source = Source([entity(x=1.0, z=0.0)])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._beacon(nav)
        self.hotkey.fire = True
        reader.poll_once()
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Arrived.", self.speech.calls)

    def test_clear_is_safe_without_a_navigation_service(self):
        source = Source([entity()])
        nav = FakeEntityNav({"npc": source}, category_key="npc", selected_identity="e1")
        reader = self._beacon(nav)
        self.hotkey.fire = True
        reader.poll_once()
        reader.clear("test")
        self.assertFalse(reader.active)


class GuideModeExclusionTests(unittest.TestCase):
    """Only one aim point at a time: two spatial cues pointing different
    ways is exactly the ambiguity this interface exists to remove."""

    def setUp(self):
        self.speech = Speech()
        self.player = Player()
        self.beacon_hotkey = Hotkey()
        self.navigation_hotkey = Hotkey()
        source = Source([entity(x=40.0, z=0.0)])
        self.nav = FakeEntityNav(
            {"npc": source}, category_key="npc", selected_identity="e1")
        navigation_service = NavigationService(
            collision_dir="unused", room_codes={},
            logger=logging.getLogger("guide-modes-test-navigation"))
        navigation_service._geometry_cache[1] = build_room_geometry(
            tuple(walk_rect(-20, 20, -20, 20)), ())
        log = logging.getLogger("guide-modes-test")
        self.beacon = AudioGuideReader(
            self.nav, self.player, "beacon.wav", self.beacon_hotkey,
            self.speech, log, None, PoseSource(1), name="Beacon")
        self.routed = AudioGuideReader(
            self.nav, self.player, "routed.wav", self.navigation_hotkey,
            self.speech, log, navigation_service, PoseSource(1),
            name="Navigation")
        self.modes = GuideModes(self.beacon, self.routed)

    def test_starting_navigation_stops_the_beacon(self):
        self.beacon_hotkey.fire = True
        self.modes.poll_once()
        self.assertTrue(self.beacon.active)

        self.navigation_hotkey.fire = True
        self.modes.poll_once()
        self.assertTrue(self.routed.active)
        self.assertFalse(
            self.beacon.active,
            "both guide modes are running at once -- the player is hearing "
            "two beacons aimed at different things")

    def test_starting_the_beacon_stops_navigation(self):
        self.navigation_hotkey.fire = True
        self.modes.poll_once()
        self.assertTrue(self.routed.active)

        self.beacon_hotkey.fire = True
        self.modes.poll_once()
        self.assertTrue(self.beacon.active)
        self.assertFalse(self.routed.active)

    def test_dialogue_silences_both_modes_through_the_pair(self):
        self.navigation_hotkey.fire = True
        self.modes.poll_once()
        self.player.played.clear()
        self.modes.poll_once(silenced=True)
        self.assertEqual(self.player.played, [])
        self.assertTrue(self.routed.suppressed)
        self.assertTrue(self.routed.active)
        self.assertFalse(self.beacon.active)

    def test_clearing_the_pair_clears_both(self):
        self.beacon_hotkey.fire = True
        self.modes.poll_once()
        self.modes.clear("test")
        self.assertFalse(self.beacon.active)
        self.assertFalse(self.routed.active)


if __name__ == "__main__":
    unittest.main()
