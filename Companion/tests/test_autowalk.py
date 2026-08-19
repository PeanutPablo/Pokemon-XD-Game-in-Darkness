import logging
import math
import unittest

from battle_narrator import hero_stick
from battle_narrator.autowalk import (
    APPROACH_DEFLECTION,
    BLOCKED_TIMEOUT,
    MAX_WALK_SECONDS,
    SETTLE_GRACE,
    AutowalkReader,
    stick_for_target,
)
from battle_narrator.entities import Entity
from battle_narrator.entity_nav import NavState
from battle_narrator.hero_stick import HeroStickOverride
from battle_narrator.memory import MemoryError as NarratorMemoryError
from battle_narrator.movement_input import GSinputMovementSource
from battle_narrator.navigation_service import NavigationResult, RouteConfidence
from battle_narrator.npc_beacons import PlayerPose, Position

LOGGER = logging.getLogger("autowalk-test")
LOGGER.addHandler(logging.NullHandler())


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

    def emit(self, event, text, deduplicate=False, interrupt=False):
        self.calls.append(text)


class Source:
    def __init__(self, entities, pose=None):
        self.items = entities
        self.pose = pose or PlayerPose(Position(0.0, 0.0, 0.0), 0.0)

    def entities(self):
        return list(self.items)

    def player_pose(self):
        return self.pose


class FakeEntityNav:
    def __init__(self, sources, category_key=None, selected_identity=None,
                 context_valid=True):
        self.sources = sources
        self.state = NavState(category_key=category_key,
                              selected_identity=selected_identity)
        self.context_valid = context_valid


class FakePoseSource:
    def __init__(self, floor_id=0x8D):
        self.floor_id = floor_id

    def current_floor_id(self):
        return self.floor_id


class FakeNavigation:
    """Returns a caller-supplied NavigationResult verbatim, so autowalk's
    reaction to routing signals is tested apart from real routing (covered
    in test_navigation_service.py)."""

    def __init__(self, result):
        self.result = result
        self.begun = []
        self.cleared = 0

    def begin(self, floor_id, destination, player_position=None,
              destination_region=None):
        self.begun.append((floor_id, destination))

    def update(self, floor_id, destination, player_position=None,
               destination_region=None):
        pass

    def next_waypoint(self, player_position):
        return self.result

    def clear(self):
        self.cleared += 1


class FakeStick:
    def __init__(self, verified=True):
        self.verified = verified
        self.holds = []
        self.releases = 0

    def verify(self):
        return self.verified

    def hold(self, x, y):
        self.holds.append((x, y))

    def release(self):
        self.releases += 1


class FakeMovementInput:
    def __init__(self, requested=False):
        self.requested = requested

    def is_movement_requested(self):
        return self.requested


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeMemory:
    """Records writes and serves canned reads by address."""

    def __init__(self, reads=None):
        self.writes = []
        self.reads = reads or {}
        self.fail = False

    def bytes(self, address, size, label="memory", alignment=1):
        if self.fail:
            raise NarratorMemoryError(label)
        return self.reads.get(address, b"\x00" * size)

    def write_bytes(self, address, data, label="memory", alignment=1):
        if self.fail:
            raise NarratorMemoryError(label)
        self.writes.append((address, bytes(data)))


class Profile:
    hero_move_base = 0x804479F0
    hero_move_stick_override_offset = 0x3AE
    hero_move_stick_data_offset = 0x3AF
    hero_move_stick_full_deflection = 0x38


def result(target, **kwargs):
    defaults = dict(
        target_position=target,
        path_available=True,
        fallback_started=False,
        remaining_distance=100.0,
        confidence=RouteConfidence.VERIFIED,
    )
    defaults.update(kwargs)
    return NavigationResult(**defaults)


def entity(identity="e1", position=None, label="Nurse"):
    return Entity(
        category="npc",
        identity=identity,
        label=label,
        position=position or Position(0.0, 0.0, -100.0),
        interaction_distance=8.0,
        metadata={},
    )


def build(nav_result=None, entities=None, pose=None, context_valid=True,
          requested=False, verified=True, floor_id=0x8D):
    target = entities[0] if entities else entity()
    entities = entities or [target]
    source = Source(entities, pose=pose)
    nav = FakeEntityNav({"npc": source}, "npc", entities[0].identity,
                        context_valid=context_valid)
    navigation = FakeNavigation(
        nav_result or result(entities[0].position))
    stick = FakeStick(verified=verified)
    speech = Speech()
    hotkey = Hotkey()
    clock = FakeClock()
    reader = AutowalkReader(
        nav, stick, hotkey, speech, LOGGER, navigation,
        FakePoseSource(floor_id), FakeMovementInput(requested),
        arrival_distance=4.0, full_deflection=0x38, clock=clock,
    )
    return reader, stick, speech, hotkey, nav, navigation, clock


class StickGeometryTests(unittest.TestCase):
    """The direction the stick is pushed, in the camera's frame."""

    def test_target_straight_ahead_pushes_stick_up(self):
        # yaw 0 faces -Z, so a target at -Z is dead ahead. Up is NEGATIVE Y.
        pose = PlayerPose(Position(0.0, 0.0, 0.0), 0.0)
        x, y = stick_for_target(pose, Position(0.0, 0.0, -100.0))
        self.assertEqual(x, 0)
        self.assertEqual(y, -0x38)

    def test_target_behind_pushes_stick_down(self):
        pose = PlayerPose(Position(0.0, 0.0, 0.0), 0.0)
        x, y = stick_for_target(pose, Position(0.0, 0.0, 100.0))
        self.assertEqual(x, 0)
        self.assertEqual(y, 0x38)

    def test_target_to_camera_right_pushes_stick_right(self):
        pose = PlayerPose(Position(0.0, 0.0, 0.0), 0.0)
        x, y = stick_for_target(pose, Position(100.0, 0.0, 0.0))
        self.assertEqual(x, 0x38)
        self.assertEqual(y, 0)

    def test_direction_follows_camera_yaw(self):
        """The same world target under a rotated camera needs a different
        stick, which is the whole reason this works in camera space."""
        target = Position(0.0, 0.0, -100.0)
        turned = PlayerPose(Position(0.0, 0.0, 0.0), math.pi / 2)
        x, y = stick_for_target(turned, target)
        # Camera turned 90 degrees: what was ahead is now to one side.
        self.assertEqual(abs(x), 0x38)
        self.assertEqual(y, 0)

    def test_magnitude_is_full_deflection_at_distance(self):
        pose = PlayerPose(Position(0.0, 0.0, 0.0), 0.0)
        x, y = stick_for_target(pose, Position(50.0, 0.0, -50.0),
                                remaining_distance=200.0)
        self.assertAlmostEqual(math.hypot(x, y), 0x38, delta=1.0)

    def test_stick_eases_off_on_final_approach(self):
        pose = PlayerPose(Position(0.0, 0.0, 0.0), 0.0)
        _, near = stick_for_target(pose, Position(0.0, 0.0, -5.0),
                                   remaining_distance=5.0)
        self.assertLess(abs(near), 0x38)
        self.assertGreaterEqual(abs(near), 0x38 * APPROACH_DEFLECTION - 1)

    def test_zero_distance_target_is_a_centred_stick(self):
        pose = PlayerPose(Position(1.0, 0.0, 2.0), 0.0)
        self.assertEqual(stick_for_target(pose, Position(1.0, 0.0, 2.0)),
                         (0, 0))


class ActivationTests(unittest.TestCase):
    def test_toggle_on_holds_the_stick_and_announces(self):
        reader, stick, speech, hotkey, *_ = build()
        hotkey.fire = True
        reader.poll_once()
        self.assertTrue(reader.active)
        self.assertIn("Autowalk on, Nurse.", speech.calls)
        reader.poll_once()
        self.assertTrue(stick.holds)

    def test_toggle_off_releases_the_stick(self):
        reader, stick, speech, hotkey, *_ = build()
        hotkey.fire = True
        reader.poll_once()
        hotkey.fire = True
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Autowalk off.", speech.calls)
        self.assertGreaterEqual(stick.releases, 1)

    def test_refuses_without_a_selection(self):
        source = Source([])
        nav = FakeEntityNav({"npc": source}, "npc", None)
        stick = FakeStick()
        speech = Speech()
        hotkey = Hotkey()
        reader = AutowalkReader(
            nav, stick, hotkey, speech, LOGGER,
            FakeNavigation(result(Position(0, 0, 0))), FakePoseSource(),
            FakeMovementInput(), clock=FakeClock())
        hotkey.fire = True
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("No entity selected to walk to.", speech.calls)
        self.assertEqual(stick.holds, [])

    def test_refuses_when_not_free_roaming(self):
        reader, stick, speech, hotkey, *_ = build(context_valid=False)
        hotkey.fire = True
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Autowalk needs free movement.", speech.calls)
        self.assertEqual(stick.holds, [])

    def test_refuses_when_the_override_signature_does_not_match(self):
        """A build whose HeroMove accessors differ must lose autowalk, not
        get a write to an address that means something else there."""
        reader, stick, speech, hotkey, *_ = build(verified=False)
        hotkey.fire = True
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn(hero_stick.UNVERIFIED_MESSAGE, speech.calls)
        self.assertEqual(stick.holds, [])


class StopConditionTests(unittest.TestCase):
    def _running(self, **kwargs):
        reader, stick, speech, hotkey, nav, navigation, clock = build(**kwargs)
        hotkey.fire = True
        reader.poll_once()
        speech.calls.clear()
        return reader, stick, speech, hotkey, nav, navigation, clock

    def test_player_movement_stops_the_walk(self):
        reader, stick, speech, _, _, _, clock = self._running()
        reader.poll_once()          # no input yet: arms the abort
        reader.movement_input.requested = True
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Autowalk off.", speech.calls)
        self.assertGreaterEqual(stick.releases, 1)

    def test_input_held_from_before_activation_does_not_stop_it_immediately(self):
        """The player may still be holding the key they were walking with
        when they pressed the chord."""
        reader, stick, speech, _, _, _, clock = self._running(requested=True)
        reader.poll_once()
        self.assertTrue(reader.active)
        self.assertTrue(stick.holds)

    def test_input_still_held_past_the_grace_period_does_stop_it(self):
        reader, _, speech, _, _, _, clock = self._running(requested=True)
        reader.poll_once()
        clock.now += SETTLE_GRACE + 0.1
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Autowalk off.", speech.calls)

    def test_losing_free_roam_stops_the_walk(self):
        reader, stick, speech, _, nav, _, _ = self._running()
        nav.context_valid = False
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertGreaterEqual(stick.releases, 1)

    def test_room_change_stops_the_walk(self):
        reader, stick, speech, _, _, _, _ = self._running()
        reader.pose_source.floor_id = 0x84
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Autowalk stopped: new area.", speech.calls)

    def test_selection_change_stops_the_walk(self):
        reader, _, speech, _, nav, _, _ = self._running()
        nav.state.selected_identity = "someone-else"
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Autowalk stopped: selection changed.", speech.calls)

    def test_direct_fallback_never_steers(self):
        """The failure this exists to prevent: a straight line handed to a
        stick is an instruction to walk into a wall."""
        reader, stick, speech, _, _, navigation, _ = self._running()
        navigation.result = result(
            Position(0.0, 0.0, -100.0), path_available=False,
            confidence=RouteConfidence.DIRECT_FALLBACK)
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Autowalk stopped: no walkable route.", speech.calls)
        self.assertEqual(stick.holds, [])

    def test_failed_confidence_never_steers(self):
        reader, stick, speech, _, _, navigation, _ = self._running()
        navigation.result = result(
            Position(0.0, 0.0, -100.0), confidence=RouteConfidence.FAILED)
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertEqual(stick.holds, [])

    def test_partial_route_walks_but_says_so_first(self):
        reader, stick, speech, _, _, navigation, _ = self._running()
        navigation.result = result(
            Position(0.0, 0.0, -100.0), confidence=RouteConfidence.PARTIAL,
            partial_started=True, partial_shortfall=7.0)
        reader.poll_once()
        self.assertTrue(reader.active)
        self.assertTrue(stick.holds)
        self.assertTrue(any("7 short" in call for call in speech.calls))

    def test_no_progress_stops_the_walk_as_blocked(self):
        reader, stick, speech, _, _, navigation, clock = self._running()
        navigation.result = result(Position(0.0, 0.0, -100.0),
                                   remaining_distance=100.0)
        reader.poll_once()
        clock.now += BLOCKED_TIMEOUT + 0.1
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Autowalk stopped: blocked.", speech.calls)

    def test_real_progress_keeps_the_walk_alive(self):
        reader, stick, speech, _, _, navigation, clock = self._running()
        for step in range(6):
            navigation.result = result(Position(0.0, 0.0, -100.0),
                                       remaining_distance=100.0 - step * 10)
            clock.now += 1.0
            reader.poll_once()
        self.assertTrue(reader.active)

    def test_oscillating_without_improving_still_counts_as_blocked(self):
        """Being stuck against geometry looks like moving, so measuring
        against the previous poll rather than the best-ever distance would
        never time out."""
        reader, _, speech, _, _, navigation, clock = self._running()
        for step in range(8):
            distance = 100.0 if step % 2 else 104.0
            navigation.result = result(Position(0.0, 0.0, -100.0),
                                       remaining_distance=distance)
            clock.now += 0.5
            reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Autowalk stopped: blocked.", speech.calls)

    def test_hard_time_limit_stops_the_walk(self):
        reader, _, speech, _, _, navigation, clock = self._running()
        # Progress every poll, so only the ceiling can stop it.
        for step in range(5):
            navigation.result = result(
                Position(0.0, 0.0, -100.0),
                remaining_distance=1000.0 - step * 50)
            clock.now += MAX_WALK_SECONDS / 4
            reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Autowalk stopped: taking too long.", speech.calls)

    def test_arrival_stops_and_announces(self):
        pose = PlayerPose(Position(0.0, 0.0, -98.0), 0.0)
        reader, stick, speech, hotkey, *_ = build(pose=pose)
        hotkey.fire = True
        reader.poll_once()
        speech.calls.clear()
        reader.poll_once()
        self.assertFalse(reader.active)
        self.assertIn("Arrived.", speech.calls)
        self.assertGreaterEqual(stick.releases, 1)

    def test_standing_below_a_target_is_not_arrival(self):
        pose = PlayerPose(Position(0.0, -60.0, -98.0), 0.0)
        reader, _, speech, hotkey, *_ = build(pose=pose)
        hotkey.fire = True
        reader.poll_once()
        speech.calls.clear()
        reader.poll_once()
        self.assertNotIn("Arrived.", speech.calls)

    def test_clear_always_releases_even_when_inactive(self):
        reader, stick, *_ = build()
        reader.clear("never started")
        self.assertEqual(stick.releases, 1)


class HeroStickOverrideTests(unittest.TestCase):
    def _override(self, reads=None):
        memory = FakeMemory(reads)
        return memory, HeroStickOverride(memory, Profile(), LOGGER)

    def test_hold_writes_the_flag_and_both_stick_pairs_in_one_write(self):
        memory, stick = self._override()
        stick.hold(0x10, -0x10)
        self.assertEqual(len(memory.writes), 1)
        address, data = memory.writes[0]
        self.assertEqual(address, 0x804479F0 + 0x3AE)
        self.assertEqual(data, bytes((1, 0x10, 0xF0, 0x10, 0xF0)))

    def test_release_clears_only_the_flag(self):
        memory, stick = self._override()
        stick.hold(0x10, 0)
        stick.release()
        address, data = memory.writes[-1]
        self.assertEqual(address, 0x804479F0 + 0x3AE)
        self.assertEqual(data, b"\x00")
        self.assertFalse(stick.engaged)

    def test_release_never_raises(self):
        memory, stick = self._override()
        memory.fail = True
        stick.release()
        self.assertFalse(stick.engaged)

    def test_stick_values_are_clamped_to_full_deflection(self):
        """A bug producing 200 here would otherwise wrap into a hard shove
        in the opposite direction."""
        memory, stick = self._override()
        stick.hold(200, -200)
        _, data = memory.writes[0]
        self.assertEqual(data[1], 0x38)
        self.assertEqual(data[2], 256 - 0x38)

    def test_verify_matches_the_decomp_bytes(self):
        memory, stick = self._override({
            hero_stick.SET_STICK_ADDRESS: hero_stick.SET_STICK_BYTES,
            hero_stick.GET_STICK_ADDRESS: hero_stick.GET_STICK_BYTES,
        })
        self.assertTrue(stick.verify())

    def test_verify_rejects_a_different_build(self):
        memory, stick = self._override({
            hero_stick.SET_STICK_ADDRESS: hero_stick.SET_STICK_BYTES,
            hero_stick.GET_STICK_ADDRESS: b"\x00" * len(hero_stick.GET_STICK_BYTES),
        })
        self.assertFalse(stick.verify())

    def test_failed_verify_is_not_cached(self):
        """A game still booting must not lose autowalk for the session."""
        memory, stick = self._override()
        self.assertFalse(stick.verify())
        memory.reads = {
            hero_stick.SET_STICK_ADDRESS: hero_stick.SET_STICK_BYTES,
            hero_stick.GET_STICK_ADDRESS: hero_stick.GET_STICK_BYTES,
        }
        self.assertTrue(stick.verify())


class MovementInputAbortTests(unittest.TestCase):
    """The D-pad half of the abort signal, which the stick-only reader used
    by BlockedMovementReader deliberately does not cover."""

    class Memory:
        def __init__(self, stick=(0, 0), buttons=0):
            self.stick = stick
            self.buttons = buttons

        def u8(self, address, label="u8"):
            base = 0x80444AF8
            if address == base + 0x36:
                return self.stick[0] & 0xFF
            if address == base + 0x37:
                return self.stick[1] & 0xFF
            raise NarratorMemoryError(label)

        def u16(self, address, label="u16"):
            if address == 0x80444AF8 + 0x34:
                return self.buttons
            raise NarratorMemoryError(label)

    def test_dpad_counts_as_movement(self):
        source = GSinputMovementSource(self.Memory(buttons=0x0008))
        self.assertFalse(source.is_direction_held())
        self.assertTrue(source.is_movement_requested())

    def test_idle_controller_is_not_movement(self):
        source = GSinputMovementSource(self.Memory())
        self.assertFalse(source.is_movement_requested())

    def test_deflected_stick_counts_as_movement(self):
        source = GSinputMovementSource(self.Memory(stick=(56, 0)))
        self.assertTrue(source.is_movement_requested())

    def test_non_dpad_buttons_are_ignored(self):
        """Pressing A to talk to whatever you were walked to must not read
        as a request to stop walking."""
        source = GSinputMovementSource(self.Memory(buttons=0x0100))
        self.assertFalse(source.is_movement_requested())


if __name__ == "__main__":
    unittest.main()
