"""The Relic Stone cave, both ways round (2026-08-13).

Live report 2026-08-12 was "something is wrong with the relic stone cave
navigation". The cause was not the passability predicate: measured against
the real `M3_out` pocket, all 22 boundary edges refused as wall-blocked are
blocked by genuine geometry (an exact segment-to-triangle test agrees with
the swept test's longest-edge approximation on 22 of 22, so none of them is
an approximation artifact). The walls are real -- the running game has simply
switched them off, and the companion was rebuilding them.

    M3_out          object 33   one 2-triangle quad at z=-1.5 spanning
                                x -46..-1.2, walling the cave mouth
    M3_cave_1F_1    objects 4,5 the interior doorways; the room's other 194
                                wall triangles are all one object

Both rooms' own scripts call `UnknownClass46::16` (the script-level
`GScolsys2SetObjEnable`) with enable=0 on exactly those indices.

**Both states are pinned here.** The doorway objects are flag-gated, so
"enabled" is a legitimately reachable state and must still block -- making
"cave always open" the regression would just invert the bug. Which state is
live is the engine's business, read through `ObjectEnableState`; these tests
supply each state explicitly as a fixture and assert the geometry that
follows from it.
"""
import math
import unittest
from pathlib import Path

from battle_narrator.collision_probe import (
    parse_environment_triangles, parse_walk_model_triangles)
from battle_narrator.npc_beacons import Position
from battle_narrator.pathfinding import (
    build_room_geometry,
    diagnose_unreachable,
    flow_field_from,
    flow_field_toward,
    resolve_node,
)

COLLISION = (Path(__file__).resolve().parents[1]
             / "_dialogue_extraction" / "collision")


class FixtureEnableState:
    """A known enable state, standing in for the live one.

    Naming object indices is exactly what a FIXTURE is for -- it pins the
    state the engine reports. Production code never does this; see
    `NoRoomSpecialCasingTests`."""

    def __init__(self, disabled=()):
        self.disabled = frozenset(disabled)

    def is_enabled(self, floor_id, entry_index):
        return entry_index not in self.disabled


def geometry_for(room, disabled=()):
    ccd = COLLISION / f"{room}.ccd"
    if not ccd.is_file():
        raise unittest.SkipTest(f"missing fixture {ccd}")
    data = ccd.read_bytes()
    return build_room_geometry(
        parse_walk_model_triangles(data), parse_environment_triangles(data),
        enable_state=FixtureEnableState(disabled))


def reachable_from(geometry, position):
    field = flow_field_from(geometry, position)
    return set() if field is None else {node[0] for node in field.node_height}


class RelicCaveExteriorTests(unittest.TestCase):
    """`M3_out`. The cave mouth sits in a hollow at y=-5, layer 0, whose
    nearest same-level reachable ground is 7.3 units away horizontally -- the
    doorstep. Its 60 boundary edges classify as 28 layer mismatch (the
    neighbour's only surface is the clifftop, y=120 layer 3), 10 with no walk
    surface, and 22 blocked by wall."""

    POCKET = Position(-20.0, -5.0, -24.0)
    DOORWAY_OBJECT = 33

    def test_route_is_available_back_up_after_leaving_the_cave(self):
        """The live return trip must work, not only the downhill journey.

        Relocated slope nodes used to make the graph directional: the route
        into the cave worked, then every target above the village floor
        reported ``height_layer`` after the player came back outside.
        """
        geometry = geometry_for("M3_out", disabled={1, 5, 33})
        cave_floor = Position(-18.75, -5.04, -1.36)
        upper_village = Position(-143.03, 80.0, -28.50)
        field = flow_field_toward(geometry, upper_village, cave_floor)
        self.assertIsNotNone(field)
        seed = resolve_node(geometry, cave_floor)
        self.assertIn((seed[0], seed[1]), field.node_height)

    def test_with_the_doorway_object_enabled_the_mouth_is_a_sealed_pocket(self):
        """The legitimately-reachable closed state. It must still block --
        the fix is to mirror the engine, not to open the cave permanently."""
        geometry = geometry_for("M3_out")
        self.assertEqual(
            len(reachable_from(geometry, self.POCKET)), 26,
            "the closed state no longer produces the 26-tile pocket the live "
            "report and the edge classification were both measured against")

    def test_with_the_doorway_object_disabled_the_mouth_rejoins_the_village(self):
        geometry = geometry_for("M3_out", disabled={self.DOORWAY_OBJECT})
        reachable = reachable_from(geometry, self.POCKET)
        self.assertGreater(
            len(reachable), 1000,
            "disabling the doorway object did not reconnect the cave mouth to "
            "Agate Village")

    def test_only_two_triangles_separate_the_two_states(self):
        """The whole defect is two triangles. Pinned so a future change to
        the wall-normal filter or the parser cannot quietly widen it."""
        closed = geometry_for("M3_out")
        open_ = geometry_for("M3_out", disabled={self.DOORWAY_OBJECT})
        self.assertEqual(
            len(closed.wall_triangles) - len(open_.wall_triangles), 2)
        self.assertEqual(
            len(closed.walk_triangles), len(open_.walk_triangles),
            "the doorway object carries no walkable ground; if that changes, "
            "the walk-model side of the filter needs its own regression")

    def test_the_reconnected_pocket_spans_multiple_layers(self):
        """Reaching the village means reaching its terraces, not just more of
        the hollow -- a same-layer-only expansion would suggest the pocket
        merely grew rather than joined the room."""
        geometry = geometry_for("M3_out", disabled={self.DOORWAY_OBJECT})
        field = flow_field_from(geometry, self.POCKET)
        self.assertIsNotNone(field)
        layers = {layer for _, layers in field.node_height for layer in layers}
        self.assertGreater(len(layers), 1, f"only reached layers {layers}")


class RelicCaveInteriorTests(unittest.TestCase):
    """`M3_cave_1F_1`. Its walk model is a single flat quad, so all of the
    room's structure lives in its 198 wall triangles -- 194 in one object and
    two each in objects 4 and 5, the doorways.

    Positions are the room's own interactable region centres, as used by the
    original regression."""

    ENTRANCE = Position(62.1, 0.0, -134.8)
    SHRINE_EXIT = Position(-18.8, 0.0, 150.0)
    SAME_POCKET = Position(26.5, 0.0, -26.0)
    DOORWAY_OBJECTS = {4, 5}

    def test_with_the_doorways_enabled_the_exit_is_unreachable(self):
        """The closed state, and the original 2026-08-12 regression: the
        refusal must survive, because the guide presenting a route it cannot
        walk is the worse failure."""
        geometry = geometry_for("M3_cave_1F_1")
        field = flow_field_toward(geometry, self.SHRINE_EXIT, self.ENTRANCE)
        self.assertTrue(
            field is None or (field.stats or {}).get("partial_guidance"),
            "a destination the graph cannot reach was presented as reached")

    def test_the_closed_state_still_names_its_own_failure(self):
        geometry = geometry_for("M3_cave_1F_1")
        cause, sentence = diagnose_unreachable(
            geometry, self.ENTRANCE, self.SHRINE_EXIT)
        self.assertEqual(cause, "disconnected", sentence)

    def test_with_the_doorways_disabled_the_exit_is_reachable(self):
        geometry = geometry_for("M3_cave_1F_1", disabled=self.DOORWAY_OBJECTS)
        seed = resolve_node(geometry, self.SHRINE_EXIT)
        self.assertIsNotNone(seed)
        self.assertIn(
            seed[0], reachable_from(geometry, self.ENTRANCE),
            "the shrine exit is still unreachable from the cave entrance with "
            "the doorway objects disabled")

    def test_the_open_state_routes_all_the_way_rather_than_stopping_short(self):
        """The closed state produced a confident 14-hop route ending 180.4
        units from the exit. Open, the route must actually arrive."""
        geometry = geometry_for("M3_cave_1F_1", disabled=self.DOORWAY_OBJECTS)
        field = flow_field_toward(geometry, self.SHRINE_EXIT, self.ENTRANCE)
        self.assertIsNotNone(field)
        self.assertFalse(
            (field.stats or {}).get("partial_guidance"),
            "still only partial guidance with the doorways open")
        end = field.node_position(field.destination_node)
        gap = math.dist(
            (end.x, end.z), (self.SHRINE_EXIT.x, self.SHRINE_EXIT.z))
        self.assertLess(
            gap, 8.0,
            f"route ends {gap:.1f} units from the shrine exit")

    def test_opening_the_doorways_more_than_doubles_the_reachable_area(self):
        closed = len(reachable_from(geometry_for("M3_cave_1F_1"), self.ENTRANCE))
        open_ = len(reachable_from(
            geometry_for("M3_cave_1F_1", disabled=self.DOORWAY_OBJECTS),
            self.ENTRANCE))
        self.assertEqual(closed, 85)
        self.assertGreater(open_, 2 * closed)

    def test_guidance_inside_the_reachable_part_works_in_both_states(self):
        """The refusal must stay specific to unreachable targets, or the fix
        has simply turned the cave off."""
        for disabled in ((), self.DOORWAY_OBJECTS):
            with self.subTest(disabled=sorted(disabled)):
                geometry = geometry_for("M3_cave_1F_1", disabled=disabled)
                field = flow_field_toward(
                    geometry, self.SAME_POCKET, self.ENTRANCE)
                self.assertIsNotNone(field)
                end = field.node_position(field.destination_node)
                self.assertLess(
                    math.dist((end.x, end.z),
                              (self.SAME_POCKET.x, self.SAME_POCKET.z)), 8.0)


class NoRoomSpecialCasingTests(unittest.TestCase):
    """The safety invariant: the companion must never decide "object 33
    should be disabled because this is the Relic cave". It decides "CCD entry
    33 is disabled because the engine's collision-object state says so."

    Asserted behaviourally rather than by scanning source, so it holds
    against what the code DOES rather than how it is written."""

    def _state(self, flags):
        from test_collision_object_enable import live_state
        state, _, _ = live_state(flags)
        return state

    def test_the_same_flags_decode_identically_in_every_room(self):
        flags = [0x0000] * 40
        flags[33] = 0x0001
        answers = []
        for floor_id in (0x84, 0x7D, 0x01, 0xFF):
            state = self._state(flags)
            state.refresh(floor_id)
            answers.append(tuple(
                state.is_enabled(floor_id, index) for index in range(40)))
        self.assertEqual(
            len(set(answers)), 1,
            "the enable decision varies by room -- something is special-casing")

    def test_an_all_clear_table_disables_nothing_anywhere(self):
        """If any room-specific rule had been baked in, some room would
        report a disabled object the engine never disabled."""
        for floor_id in (0x84, 0x7D, 0x01, 0xFF):
            state = self._state([0x0000] * 40)
            state.refresh(floor_id)
            self.assertEqual(state.snapshot.disabled_entries(), ())

    def test_the_cave_objects_are_not_privileged(self):
        """33, 4 and 5 must behave exactly like any other index."""
        for index in (4, 5, 33, 7, 19):
            flags = [0x0000] * 40
            flags[index] = 0x0001
            state = self._state(flags)
            state.refresh(0x84)
            self.assertEqual(state.snapshot.disabled_entries(), (index,))


if __name__ == "__main__":
    unittest.main()
