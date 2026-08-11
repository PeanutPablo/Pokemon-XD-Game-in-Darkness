import unittest

from battle_narrator.collision_object_enable import StaticObjectEnableState
from battle_narrator.collision_probe import WalkTriangle
from battle_narrator.pathfinding import build_room_geometry


def _walk_triangle(entry_index, layer=0):
    return WalkTriangle(
        ((0.0, 0.0, 0.0), (8.0, 0.0, 0.0), (8.0, 0.0, 8.0)), (0.0, 1.0, 0.0),
        layer, layer, 0xFF, entry_index)


class StaticObjectEnableStateTests(unittest.TestCase):
    """Phase 5 (2026-08-01): the runtime enable-state global's exact layout
    could not be confirmed live (see collision_object_enable.py's own
    docstring) -- these tests cover the STATIC implementation actually
    shipped, and confirm build_room_geometry's own enable_state hook works
    correctly for whichever implementation is eventually plugged in."""

    def test_every_object_is_always_enabled(self):
        state = StaticObjectEnableState()
        for entry_index in (0, 1, 34, 9999):
            self.assertTrue(state.is_enabled(floor_id=0x84, entry_index=entry_index))

    def test_default_enable_state_includes_every_triangle(self):
        triangles = (_walk_triangle(0), _walk_triangle(1), _walk_triangle(2))
        geometry = build_room_geometry(triangles, ())
        self.assertEqual(len(geometry.walk_triangles), 3)

    def test_a_custom_enable_state_can_exclude_specific_objects(self):
        # Confirms the hook itself works correctly even though no
        # live-verified implementation exists yet -- a future
        # live-validated ObjectEnableState can be substituted with no
        # other code changes.
        class DisableEntryOne:
            def is_enabled(self, floor_id, entry_index):
                return entry_index != 1

        triangles = (_walk_triangle(0), _walk_triangle(1), _walk_triangle(2))
        geometry = build_room_geometry(triangles, (), enable_state=DisableEntryOne())
        remaining_entries = {t.entry_index for t in geometry.walk_triangles}
        self.assertEqual(remaining_entries, {0, 2})


if __name__ == "__main__":
    unittest.main()
