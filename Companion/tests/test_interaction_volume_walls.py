"""Interaction trigger volumes are not walls (2026-08-14).

Live report: "the relic cave is facing the same issues as before", followed by
the project owner confirming they **can physically walk into the cave** while
the engine reports the doorway object ENABLED.

Both facts are true at once because `M3_out` entry 33 is not a wall. Its two
hit-model (+0x28) triangles are geometrically identical to its own
interaction region's (region 9), and it is the only entry in that room which
both owns a region and carries hit geometry. The companion was rebuilding a
trigger volume as rock across the cave mouth.

An interaction region is by definition a volume the player must be able to
stand inside for the trigger to fire, so it cannot also be a barrier.

Measured over all 177 rooms: **346 of 1118** hit-model objects have obstacle
geometry that is entirely interaction geometry, across **117 rooms**. This
was systemic, not one room's quirk -- which is why the fix is a general rule
and names no room and no entry index.
"""
import unittest
from pathlib import Path

from battle_narrator.collision_probe import (
    parse_environment_triangles, parse_walk_model_triangles)
from battle_narrator.npc_beacons import Position
from battle_narrator.pathfinding import build_room_geometry, flow_field_from
from battle_narrator.region_geometry import (
    interaction_volume_keys, parse_regions, triangle_key)

COLLISION = (Path(__file__).resolve().parents[1]
             / "_dialogue_extraction" / "collision")


def _m3_out():
    ccd = COLLISION / "M3_out.ccd"
    if not ccd.is_file():
        raise unittest.SkipTest(f"missing fixture {ccd}")
    return ccd.read_bytes()


class DoorwayObjectIsATriggerTests(unittest.TestCase):
    """The evidence, pinned so the claim cannot rot."""

    def test_the_doorway_objects_hit_geometry_is_its_interaction_region(self):
        data = _m3_out()
        wall = [t for t in parse_environment_triangles(data)
                if t.entry_index == 33]
        region = parse_regions(data)[9]
        self.assertEqual(
            {triangle_key(t.vertices) for t in wall},
            {triangle_key(t) for t in region.triangles},
            "entry 33's obstacle geometry is no longer its own interaction "
            "region -- the premise of this fix has changed")

    def test_it_is_the_only_entry_that_both_owns_a_region_and_has_walls(self):
        """Entry 33 is unique in owning an interaction region AND carrying
        hit-model geometry -- which is what made it the cave's false wall."""
        from battle_narrator.region_geometry import (
            INTERACTABLE_SLOTS, _u32)

        data = _m3_out()
        walls = {t.entry_index for t in parse_environment_triangles(data)}
        list_start, count = _u32(data, 0), _u32(data, 4)
        owners = {
            entry for entry in range(count)
            if any(_u32(data, list_start + entry * 0x40 + slot)
                   for slot in INTERACTABLE_SLOTS)
        }
        self.assertEqual(owners & walls, {33})

    def test_other_entries_duplicate_region_geometry_in_the_hit_slot(self):
        """Separately from ownership, several entries' hit geometry simply
        IS some region's volume, duplicated into the obstacle slot. Those are
        trigger volumes too, and the rule drops them for the same reason --
        recorded here because it makes the fix broader than one doorway."""
        data = _m3_out()
        volumes = interaction_volume_keys(data)
        by_entry = {}
        for triangle in parse_environment_triangles(data):
            if triangle_key(triangle.vertices) in volumes:
                by_entry.setdefault(triangle.entry_index, 0)
                by_entry[triangle.entry_index] += 1
        self.assertEqual(sorted(by_entry), [0, 1, 2, 3, 4, 5, 33])


class TriggerVolumesAreNotObstaclesTests(unittest.TestCase):
    """The behaviour that matters: the cave opens with the doorway object
    ENABLED, which is what the engine actually reports."""

    POCKET = Position(-20.0, -5.0, -24.0)

    class _LiveState:
        """The live enable state read from the running game on 2026-08-14:
        objects 0,1,2 disabled, 33 ENABLED."""

        def is_enabled(self, floor_id, entry_index):
            return entry_index not in {0, 1, 2}

    def _geometry(self, volumes):
        data = _m3_out()
        return build_room_geometry(
            parse_walk_model_triangles(data),
            parse_environment_triangles(data),
            enable_state=self._LiveState(),
            interaction_volumes=volumes)

    def test_without_the_fix_the_cave_is_sealed(self):
        """Guards the test itself: if this stopped reproducing, the one below
        would pass for the wrong reason."""
        geometry = self._geometry(None)
        field = flow_field_from(geometry, self.POCKET)
        self.assertEqual(len(field.node_height), 26)

    def test_the_cave_opens_with_the_doorway_object_still_enabled(self):
        geometry = self._geometry(interaction_volume_keys(_m3_out()))
        field = flow_field_from(geometry, self.POCKET)
        self.assertGreater(
            len(field.node_height), 1000,
            "the cave mouth is still sealed once trigger volumes stop being "
            "treated as walls")

    def test_only_interaction_geometry_is_dropped(self):
        data = _m3_out()
        volumes = interaction_volume_keys(data)
        without = self._geometry(None)
        with_fix = self._geometry(volumes)
        dropped = set(without.wall_triangles) - set(with_fix.wall_triangles)
        self.assertTrue(dropped)
        for triangle in dropped:
            self.assertIn(
                triangle_key(triangle.vertices), volumes,
                "a triangle that is not interaction geometry was dropped")

    def test_default_is_unchanged_behaviour(self):
        """Offline tools and every synthetic fixture pass no volumes, and
        must be completely unaffected."""
        data = _m3_out()
        walls = parse_environment_triangles(data)
        walk = parse_walk_model_triangles(data)
        self.assertEqual(
            len(build_room_geometry(walk, walls).wall_triangles),
            len(build_room_geometry(
                walk, walls, interaction_volumes=frozenset()).wall_triangles))


class RuleIsGeneralTests(unittest.TestCase):
    """No room and no entry index appears in the production rule."""

    def test_the_rule_applies_across_many_rooms(self):
        affected = 0
        checked = 0
        for path in sorted(COLLISION.glob("*.ccd"))[:60]:
            data = path.read_bytes()
            try:
                volumes = interaction_volume_keys(data)
                walls = parse_environment_triangles(data)
            except (OSError, ValueError):
                continue
            checked += 1
            if any(triangle_key(t.vertices) in volumes for t in walls):
                affected += 1
        self.assertGreater(checked, 30)
        self.assertGreater(
            affected, 10,
            "the trigger-volume overlap should be widespread, not unique to "
            "one room")


if __name__ == "__main__":
    unittest.main()
