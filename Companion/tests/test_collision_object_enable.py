"""Live collision-object enable state (2026-08-13).

Phase 5 (2026-08-01) shipped `StaticObjectEnableState` because the runtime
global's layout could not be confirmed. It was re-derived from `GScolsys2.s`
on 2026-08-13 and the always-enabled default turned out to be a real defect,
not a neutral placeholder: it reinstates collision objects the running game
has switched off. Agate's Relic Stone cave was sealed by exactly that -- one
2-triangle object outdoors, two more inside.

These tests pin the decoding against the structure the disassembly states,
the failure behaviour (which must never invent a state), and the
invalidation path that keeps a route from outliving a geometry change.
"""
import unittest

from battle_narrator.collision_object_enable import (
    CCD_ENTRY_COUNT_OFFSET,
    CUR_CCD_OFFSET,
    CUR_FLOOR_OFFSET,
    EnableStateUnavailable,
    FLOOR_OFFSET,
    GSCOLSYS2_ADDRESS,
    LiveObjectEnableState,
    MAX_OBJECTS,
    OBJ_FLAGS_OFFSET,
    OBJ_STRIDE,
    StaticObjectEnableState,
)
from battle_narrator.collision_probe import CollisionTriangle, WalkTriangle
from battle_narrator.memory import MemoryError as GameMemoryError
from battle_narrator.pathfinding import build_room_geometry


CCD_HEAD = 0x81000000


def _walk_triangle(entry_index, layer=0):
    return WalkTriangle(
        ((0.0, 0.0, 0.0), (8.0, 0.0, 0.0), (8.0, 0.0, 8.0)), (0.0, 1.0, 0.0),
        layer, layer, 0xFF, entry_index)


def _wall_triangle(entry_index):
    """Near-vertical, so it survives build_room_geometry's normal filter and
    its removal is attributable to the enable state alone."""
    return CollisionTriangle(
        ((0.0, 0.0, 0.0), (8.0, 0.0, 0.0), (8.0, 20.0, 0.0)),
        (0.0, 0.0, 1.0), 3, entry_index)


class FakeReader:
    """Serves a synthetic GScolsys2 image built to the layout the
    disassembly describes, so the decoding is tested against the structure
    rather than against itself."""

    def __init__(self, flags, cur_ccd=CCD_HEAD, cur_floor=0, count=None):
        self.flags = list(flags)
        self.cur_ccd = cur_ccd
        self.cur_floor = cur_floor
        self.count = len(flags) if count is None else count
        self.fail = None
        self.reads = 0

    def _check(self):
        self.reads += 1
        if self.fail is not None:
            raise self.fail

    def u32(self, address, label="u32"):
        self._check()
        if address == GSCOLSYS2_ADDRESS + CUR_FLOOR_OFFSET:
            return self.cur_floor
        if address == GSCOLSYS2_ADDRESS + CUR_CCD_OFFSET:
            return self.cur_ccd
        if address == self.cur_ccd + CCD_ENTRY_COUNT_OFFSET:
            return self.count
        raise GameMemoryError(f"{label}: unmapped address 0x{address:08X}")

    def bytes(self, address, size, label="memory", alignment=1):
        self._check()
        if address != GSCOLSYS2_ADDRESS + FLOOR_OFFSET:
            raise GameMemoryError(f"{label}: unmapped block 0x{address:08X}")
        block = bytearray(size)
        for index, word in enumerate(self.flags):
            offset = index * OBJ_STRIDE + OBJ_FLAGS_OFFSET
            if offset + 2 <= size:
                block[offset] = (word >> 8) & 0xFF
                block[offset + 1] = word & 0xFF
        return bytes(block)


class FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(("info", message % args if args else message))

    def warning(self, message, *args):
        self.records.append(("warning", message % args if args else message))

    def debug(self, message, *args):
        self.records.append(("debug", message % args if args else message))

    def messages(self, level=None):
        return [text for kind, text in self.records if level in (None, kind)]


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def live_state(flags, **kwargs):
    reader = FakeReader(flags, **kwargs)
    clock = FakeClock()
    state = LiveObjectEnableState(reader, FakeLogger(), clock)
    return state, reader, clock


class EnableFieldDecodingTests(unittest.TestCase):
    """`GScolsys2GetObjEnable` stores the INVERSE of bit 0 into its
    out-parameter: `clrlwi. r0, r0, 31` then `li r0, 0` on the set branch.
    The stored bit means DISABLED, and the reported byte means ENABLED."""

    def test_a_cleared_bit_is_enabled(self):
        state, _, _ = live_state([0x0000, 0x0000])
        state.refresh(0x84)
        self.assertTrue(state.is_enabled(0x84, 0))
        self.assertTrue(state.is_enabled(0x84, 1))

    def test_a_set_bit_is_disabled(self):
        state, _, _ = live_state([0x0000, 0x0001])
        state.refresh(0x84)
        self.assertTrue(state.is_enabled(0x84, 0))
        self.assertFalse(state.is_enabled(0x84, 1))

    def test_only_bit_zero_carries_the_enable_meaning(self):
        """Every other bit of the flags word must be ignored. The engine
        masks with bit 0 alone, and `SetObjEnable`'s enable branch clears
        only bit 0 (`rlwinm r0, r0, 0, 16, 30`) while preserving the rest --
        so treating the word as a boolean would misread any object carrying
        unrelated flags."""
        state, _, _ = live_state([0xFFFE, 0xFFFF, 0x0002, 0x8001])
        state.refresh(0x84)
        self.assertTrue(state.is_enabled(0x84, 0))    # 0xFFFE: bit0 clear
        self.assertFalse(state.is_enabled(0x84, 1))   # 0xFFFF: bit0 set
        self.assertTrue(state.is_enabled(0x84, 2))    # 0x0002: bit0 clear
        self.assertFalse(state.is_enabled(0x84, 3))   # 0x8001: bit0 set

    def test_records_are_read_at_the_documented_stride(self):
        """Record stride 0x28 with the flags word at +0x24, based at
        GScolsys2+0x04. A wrong stride still decodes object 0 correctly, so
        this pins a disabled object well down the array."""
        flags = [0x0000] * 10
        flags[7] = 0x0001
        state, _, _ = live_state(flags)
        state.refresh(0x84)
        for index in range(10):
            self.assertEqual(
                state.is_enabled(0x84, index), index != 7,
                f"object {index} decoded wrongly -- stride/offset is off")

    def test_the_snapshot_lists_disabled_entries(self):
        state, _, _ = live_state([0, 1, 0, 1, 1])
        state.refresh(0x84)
        self.assertEqual(state.snapshot.disabled_entries(), (1, 3, 4))


class EnableStateFailureTests(unittest.TestCase):
    """Nothing here may fall back to "everything is enabled" -- that is the
    defect being fixed, not a safe default."""

    def test_an_index_outside_the_object_table_raises(self):
        state, _, _ = live_state([0x0000, 0x0000])
        state.refresh(0x84)
        with self.assertRaises(EnableStateUnavailable):
            state.is_enabled(0x84, 2)
        with self.assertRaises(EnableStateUnavailable):
            state.is_enabled(0x84, -1)

    def test_no_loaded_ccd_yields_no_snapshot(self):
        state, _, _ = live_state([0x0000], cur_ccd=0)
        self.assertIsNone(state.refresh(0x84))
        with self.assertRaises(EnableStateUnavailable):
            state.is_enabled(0x84, 0)

    def test_a_nonzero_cur_floor_is_refused(self):
        """GScolsys2GetCurFloor returns NULL unless the field is exactly 0.
        A non-zero value means the structure is not what this code believes,
        and guessing past that is the whole failure mode being avoided."""
        state, _, _ = live_state([0x0000], cur_floor=1)
        self.assertIsNone(state.refresh(0x84))
        with self.assertRaises(EnableStateUnavailable):
            state.is_enabled(0x84, 0)

    def test_an_object_count_beyond_capacity_is_refused(self):
        state, _, _ = live_state([0x0000], count=MAX_OBJECTS + 1)
        self.assertIsNone(state.refresh(0x84))

    def test_a_zero_object_count_is_refused(self):
        state, _, _ = live_state([0x0000], count=0)
        self.assertIsNone(state.refresh(0x84))

    def test_an_unreadable_table_never_reports_enabled(self):
        state, reader, _ = live_state([0x0000, 0x0001])
        reader.fail = GameMemoryError("backend detached")
        self.assertIsNone(state.refresh(0x84))
        with self.assertRaises(EnableStateUnavailable):
            state.is_enabled(0x84, 0)

    def test_an_unreadable_table_logs_once_per_cause(self):
        """This runs in the per-poll path; this project has produced a 275 MB
        log by not gating a per-poll line."""
        state, reader, _ = live_state([0x0000])
        reader.fail = GameMemoryError("backend detached")
        for _ in range(20):
            state.refresh(0x84)
        warnings = [m for m in state.logger.messages("warning")
                    if "unreadable" in m]
        self.assertEqual(len(warnings), 1, state.logger.messages())

    def test_a_snapshot_survives_a_brief_read_failure(self):
        """Rebuilding M6_out's geometry costs seconds; dropping routing on
        every transient hiccup would be its own regression. The last
        VERIFIED snapshot is kept briefly -- which is not the same as
        inventing one."""
        state, reader, clock = live_state([0x0000, 0x0001])
        first = state.refresh(0x84)
        reader.fail = GameMemoryError("transient")
        clock.now += 1.0
        self.assertEqual(state.refresh(0x84), first)
        self.assertFalse(state.is_enabled(0x84, 1))

    def test_a_stale_snapshot_eventually_expires(self):
        state, reader, clock = live_state([0x0000, 0x0001])
        state.refresh(0x84)
        reader.fail = GameMemoryError("gone")
        clock.now += state.stale_after_s + 0.1
        self.assertIsNone(state.refresh(0x84))
        with self.assertRaises(EnableStateUnavailable):
            state.is_enabled(0x84, 1)

    def test_recovery_is_logged(self):
        state, reader, clock = live_state([0x0000])
        state.refresh(0x84)
        reader.fail = GameMemoryError("transient")
        state.refresh(0x84)
        reader.fail = None
        state.refresh(0x84)
        self.assertTrue(
            any("recovered" in m for m in state.logger.messages("info")),
            state.logger.messages())


class RoomTransitionTests(unittest.TestCase):
    """The engine holds exactly one loaded CCD, so a snapshot is only ever
    evidence about the room it was taken in."""

    def test_a_snapshot_is_not_answered_across_floors(self):
        state, _, _ = live_state([0x0000, 0x0001])
        state.refresh(0x84)
        with self.assertRaises(EnableStateUnavailable):
            state.is_enabled(0x7D, 1)

    def test_refreshing_in_the_new_room_rebinds_the_snapshot(self):
        state, _, _ = live_state([0x0000, 0x0001])
        state.refresh(0x84)
        state.refresh(0x7D)
        self.assertFalse(state.is_enabled(0x7D, 1))

    def test_the_signature_distinguishes_rooms(self):
        state, _, _ = live_state([0x0000, 0x0001])
        first = state.refresh(0x84)
        second = state.refresh(0x7D)
        self.assertNotEqual(first, second)


class SignatureTests(unittest.TestCase):
    def test_an_unchanged_table_keeps_its_signature(self):
        state, _, _ = live_state([0x0000, 0x0001])
        self.assertEqual(state.refresh(0x84), state.refresh(0x84))

    def test_toggling_an_object_changes_the_signature(self):
        state, reader, _ = live_state([0x0000, 0x0001])
        before = state.refresh(0x84)
        reader.flags[1] = 0x0000
        self.assertNotEqual(state.refresh(0x84), before)

    def test_a_reloaded_ccd_changes_the_signature(self):
        state, reader, _ = live_state([0x0000])
        before = state.refresh(0x84)
        reader.cur_ccd = CCD_HEAD + 0x2000
        self.assertNotEqual(state.refresh(0x84), before)


class GeometryFilteringTests(unittest.TestCase):
    """One record serves both model slots: `GScolsys2WalkGetHeight` (CCD
    +0x24) and the hit-model sweep (+0x28/+0x34) both consult the same
    `obj[i].flags` before looking at geometry. Filtering only one slot would
    mismodel the engine."""

    def test_a_disabled_object_loses_its_walk_triangles(self):
        state, _, _ = live_state([0x0000, 0x0001])
        state.refresh(0x84)
        geometry = build_room_geometry(
            (_walk_triangle(0), _walk_triangle(1)), (),
            floor_id=0x84, enable_state=state)
        self.assertEqual(
            {t.entry_index for t in geometry.walk_triangles}, {0})

    def test_a_disabled_object_loses_its_wall_triangles(self):
        state, _, _ = live_state([0x0000, 0x0001])
        state.refresh(0x84)
        geometry = build_room_geometry(
            (), (_wall_triangle(0), _wall_triangle(1)),
            floor_id=0x84, enable_state=state)
        self.assertEqual(
            {t.entry_index for t in geometry.wall_triangles}, {0})

    def test_both_slots_are_filtered_together(self):
        state, _, _ = live_state([0x0000, 0x0001])
        state.refresh(0x84)
        geometry = build_room_geometry(
            (_walk_triangle(0), _walk_triangle(1)),
            (_wall_triangle(0), _wall_triangle(1)),
            floor_id=0x84, enable_state=state)
        self.assertEqual({t.entry_index for t in geometry.walk_triangles}, {0})
        self.assertEqual({t.entry_index for t in geometry.wall_triangles}, {0})

    def test_an_unreadable_state_refuses_to_build_rather_than_pass_everything(self):
        state, reader, _ = live_state([0x0000, 0x0001])
        reader.fail = GameMemoryError("detached")
        state.refresh(0x84)
        with self.assertRaises(EnableStateUnavailable):
            build_room_geometry(
                (_walk_triangle(0),), (), floor_id=0x84, enable_state=state)


class StaticObjectEnableStateTests(unittest.TestCase):
    """Retained for offline tools and fixtures that analyse a `.ccd` on its
    own, where there is no running game to ask."""

    def test_every_object_is_always_enabled(self):
        state = StaticObjectEnableState()
        for entry_index in (0, 1, 34, 9999):
            self.assertTrue(state.is_enabled(floor_id=0x84, entry_index=entry_index))

    def test_default_enable_state_includes_every_triangle(self):
        triangles = (_walk_triangle(0), _walk_triangle(1), _walk_triangle(2))
        geometry = build_room_geometry(triangles, ())
        self.assertEqual(len(geometry.walk_triangles), 3)

    def test_a_custom_enable_state_can_exclude_specific_objects(self):
        class DisableEntryOne:
            def is_enabled(self, floor_id, entry_index):
                return entry_index != 1

        triangles = (_walk_triangle(0), _walk_triangle(1), _walk_triangle(2))
        geometry = build_room_geometry(triangles, (), enable_state=DisableEntryOne())
        remaining_entries = {t.entry_index for t in geometry.walk_triangles}
        self.assertEqual(remaining_entries, {0, 2})


def _walk_quad(x0, x1, z0, z1, entry_index, y=0.0, layer=0):
    return [
        WalkTriangle(((x0, y, z0), (x1, y, z0), (x1, y, z1)),
                     (0.0, 1.0, 0.0), layer, layer, 0xFF, entry_index),
        WalkTriangle(((x0, y, z0), (x1, y, z1), (x0, y, z1)),
                     (0.0, 1.0, 0.0), layer, layer, 0xFF, entry_index),
    ]


def _barrier(x, z0, z1, entry_index):
    """A vertical wall spanning z0..z1 at the given x, tall enough to reach a
    standing body."""
    return [
        CollisionTriangle(((x, -1.0, z0), (x, -1.0, z1), (x, 20.0, z1)),
                          (1.0, 0.0, 0.0), 3, entry_index),
        CollisionTriangle(((x, -1.0, z0), (x, 20.0, z1), (x, 20.0, z0)),
                          (1.0, 0.0, 0.0), 3, entry_index),
    ]


class NavigationInvalidationTests(unittest.TestCase):
    """Object state changes mid-room -- Gateon Port's piers are exactly that
    -- so the navigation graph and any route standing on it must not outlive
    the geometry they were computed against."""

    FLOOR = 0x84
    WALL_OBJECT = 1

    def _service(self, flags):
        from battle_narrator.navigation_service import NavigationService

        state, reader, clock = live_state(flags)
        service = NavigationService(
            collision_dir="unused", room_codes={}, logger=FakeLogger(),
            clock=clock, enable_state=state)
        service._walk_triangle_cache[self.FLOOR] = tuple(
            _walk_quad(0.0, 80.0, 0.0, 24.0, entry_index=0))
        service._wall_triangle_cache[self.FLOOR] = tuple(
            _barrier(40.0, 0.0, 24.0, entry_index=self.WALL_OBJECT))
        return service, reader, clock

    def test_a_toggle_reports_a_change_and_drops_cached_geometry(self):
        service, reader, _ = self._service([0x0000, 0x0000])
        service.refresh_enable_state(self.FLOOR)
        first = service._geometry_for(self.FLOOR)
        self.assertIsNotNone(first)
        self.assertEqual(len(first.wall_triangles), 2)

        reader.flags[self.WALL_OBJECT] = 0x0001
        self.assertTrue(service.refresh_enable_state(self.FLOOR))
        second = service._geometry_for(self.FLOOR)
        self.assertIsNot(second, first, "stale geometry was served")
        self.assertEqual(len(second.wall_triangles), 0)

    def test_an_unchanged_state_keeps_the_cached_geometry(self):
        """Rebuilding M6_out costs seconds -- an unchanged table must not
        trigger one."""
        service, _, _ = self._service([0x0000, 0x0000])
        service.refresh_enable_state(self.FLOOR)
        first = service._geometry_for(self.FLOOR)
        self.assertFalse(service.refresh_enable_state(self.FLOOR))
        self.assertIs(service._geometry_for(self.FLOOR), first)

    def test_an_active_route_is_discarded_when_the_barrier_opens(self):
        from battle_narrator.npc_beacons import Position

        service, reader, clock = self._service([0x0000, 0x0000])
        start = Position(8.0, 0.0, 12.0)
        destination = Position(72.0, 0.0, 12.0)
        service.begin(self.FLOOR, destination, player_position=start)
        blocked_route = service._route

        reader.flags[self.WALL_OBJECT] = 0x0001
        clock.now += 5.0
        service.update(self.FLOOR, destination, player_position=start)
        self.assertIsNot(
            service._route, blocked_route,
            "the route survived a geometry change it was computed against")

    def test_the_barrier_actually_separates_the_two_states(self):
        """Guards the fixture itself: if the wall never blocked, the
        invalidation tests above would pass vacuously."""
        from battle_narrator.npc_beacons import Position
        from battle_narrator.pathfinding import flow_field_from

        service, reader, _ = self._service([0x0000, 0x0000])
        service.refresh_enable_state(self.FLOOR)
        closed = flow_field_from(
            service._geometry_for(self.FLOOR), Position(8.0, 0.0, 12.0))
        reader.flags[self.WALL_OBJECT] = 0x0001
        service.refresh_enable_state(self.FLOOR)
        open_ = flow_field_from(
            service._geometry_for(self.FLOOR), Position(8.0, 0.0, 12.0))
        self.assertLess(len(closed.node_height), len(open_.node_height))

    def test_an_unreadable_state_refuses_the_room_instead_of_guessing(self):
        service, reader, _ = self._service([0x0000, 0x0000])
        reader.fail = GameMemoryError("detached")
        service.refresh_enable_state(self.FLOOR)
        self.assertIsNone(
            service._geometry_for(self.FLOOR),
            "an unreadable enable state produced geometry anyway")
        self.assertTrue(
            any("refused" in text
                for text in service.logger.messages("warning")),
            service.logger.messages())

    def test_a_static_state_never_reports_a_change(self):
        """Offline/test callers keep working unchanged."""
        from battle_narrator.navigation_service import NavigationService

        service = NavigationService(
            collision_dir="unused", room_codes={}, logger=FakeLogger(),
            clock=FakeClock())
        self.assertFalse(service.refresh_enable_state(self.FLOOR))


if __name__ == "__main__":
    unittest.main()
