"""Labels, roles, deduplication and lifecycle for the canonical NPC source.

The regression that motivated Phase 2 is `AgatePokeMartTests`: room 0x86
(`M3_shop_1F`) has three NPCs and exactly one clerk, and the old code
called all three clerks because it keyed the role on the floor id.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import people_fixture as fx
from battle_narrator.entity_sources import LetterRegistry, LiveNPCEntitySource
from battle_narrator.model_parts import NeckResolution
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.npc_roles import (
    NPCRoleResolver, ROOM_SCRIPT_KIND, decode_talk_script_id, function_table,
    parse_room_script, room_roles,
)
from battle_narrator.people_runtime import PeopleRuntimeSource
from battle_narrator.profile import XD_US_REV0


class Pose:
    """Stands in for NPCMemorySource: supplies the player pose and the hero
    model address the runtime uses to find the hero's own actor."""

    def __init__(self, position=None, facing=0.0, model=None):
        self.position = position or Position(0.0, 0.0, 0.0)
        self.facing = facing
        self.model = model

    def player_pose(self):
        return PlayerPose(self.position, 0.0, self.facing)

    def hero_model_address(self):
        return self.model


class Logger:
    def __init__(self):
        self.debug_lines = []

    def debug(self, *args):
        self.debug_lines.append(args)

    def info(self, *args):
        pass

    def warning(self, *args):
        pass


def make_source(characters, names=None, roles=None, pose=None, floor_id=0x86,
                **kwargs):
    memory, backend = fx.build(characters, floor_id=floor_id, **kwargs)
    runtime = PeopleRuntimeSource(memory, XD_US_REV0)
    source = LiveNPCEntitySource(
        runtime, pose or Pose(), names or {},
        role_resolver=NPCRoleResolver(roles or {}), logger=Logger())
    return source, runtime, backend


class NeckPlausibilityTests(unittest.TestCase):
    """Live 2026-08-09: the JObj walk returned neck offsets of 40.92 and
    11.32 units against a 4.0 collision ball, and one NPC's offset moved
    0.50 -> 11.32 between two samples five seconds apart. An interaction
    point ten body-radii from the body is worse than no neck reference at
    all, so an implausible resolution falls back to the actor position."""

    class Resolver:
        """Stands in for NeckPositionResolver, returning a resolution the
        source has to judge rather than a bare position."""

        def __init__(self, offset):
            self.offset = offset
            self.calls = 0

        def resolve(self, model, neck_index, actor_position):
            self.calls += 1
            return NeckResolution(
                model=model, requested_index=neck_index, part_index=neck_index,
                jobj=0x80600000, source="matrix",
                base_position=actor_position,
                position=Position(
                    actor_position.x + self.offset, actor_position.y,
                    actor_position.z))

    def _source(self, offset, col_ball=4.0):
        memory, _ = fx.build([fx.Character(res_id=0, info_id=10)],
                             infos={10: (-1, col_ball, 3.0)})
        runtime = PeopleRuntimeSource(memory, XD_US_REV0)
        resolver = self.Resolver(offset)
        source = LiveNPCEntitySource(
            runtime, Pose(), {}, neck_resolver=resolver, logger=Logger())
        return source, resolver

    def test_a_neck_inside_the_collision_ball_is_used(self):
        source, resolver = self._source(0.2)
        entity = source.entities()[0]
        self.assertEqual(resolver.calls, 1)
        self.assertAlmostEqual(
            entity.metadata["interaction_position"].x,
            entity.position.x + 0.2, places=4)

    def test_a_neck_beyond_the_collision_ball_falls_back(self):
        source, _ = self._source(40.92)
        entity = source.entities()[0]
        self.assertAlmostEqual(
            entity.metadata["interaction_position"].x, entity.position.x,
            places=4)

    def test_the_bound_is_the_collision_ball_not_a_constant(self):
        # The same 6-unit offset is implausible for a small character and
        # fine for a large one, and the game supplies the size.
        small, _ = self._source(6.0, col_ball=4.0)
        large, _ = self._source(6.0, col_ball=10.0)
        self.assertAlmostEqual(
            small.entities()[0].metadata["interaction_position"].x,
            small.entities()[0].position.x, places=4)
        self.assertAlmostEqual(
            large.entities()[0].metadata["interaction_position"].x,
            large.entities()[0].position.x + 6.0, places=4)

    def test_a_rejected_neck_is_logged_not_silent(self):
        source, _ = self._source(40.92)
        source.entities()
        self.assertTrue(any(
            "neck rejected" in str(line) for line in source.logger.debug_lines))

    def test_an_unreadable_collision_ball_does_not_reject(self):
        # No size to compare against means the gate cannot be evaluated,
        # and an unverifiable gate never counts as a failed one.
        source, _ = self._source(40.92, col_ball=0.0)
        entity = source.entities()[0]
        self.assertAlmostEqual(
            entity.metadata["interaction_position"].x,
            entity.position.x + 40.92, places=4)


class LabelTests(unittest.TestCase):
    def test_named_npc_uses_its_authoritative_name(self):
        source, _, _ = make_source(
            [fx.Character(res_id=0, name_id=7)], names={7: "Eagun"})
        self.assertEqual(source.entities()[0].label, "Eagun")

    def test_unnamed_npcs_are_lettered_bare(self):
        source, _, _ = make_source(
            [fx.Character(res_id=0), fx.Character(res_id=1),
             fx.Character(res_id=2)])
        labels = [entity.label for entity in source.entities()]
        self.assertEqual(labels, ["A", "B", "C"])

    def test_no_npc_prefix_anywhere(self):
        source, _, _ = make_source([fx.Character(res_id=0)])
        for entity in source.entities():
            self.assertNotIn("NPC", entity.label)

    def test_letters_survive_an_npc_disappearing(self):
        source, runtime, backend = make_source(
            [fx.Character(res_id=0), fx.Character(res_id=1),
             fx.Character(res_id=2)])
        before = {e.identity: e.label for e in source.entities()}
        # Middle NPC despawns. Under the old recompute-every-call scheme the
        # third NPC silently inherited "B" -- the label the player was
        # already walking toward.
        record = fx.WORK_RECORDS + 1 * XD_US_REV0.people_work_stride
        backend.write(record + XD_US_REV0.people_work_occupied_offset,
                      bytes([0]))
        after = {e.identity: e.label for e in source.entities()}
        self.assertEqual(after[("npc", fx.DEFAULT_GROUP, 2)], "C")
        self.assertEqual(after[("npc", fx.DEFAULT_GROUP, 0)],
                         before[("npc", fx.DEFAULT_GROUP, 0)])

    def test_letters_are_unaffected_by_movement(self):
        source, _, backend = make_source(
            [fx.Character(res_id=0), fx.Character(res_id=1)])
        before = {e.identity: e.label for e in source.entities()}
        backend.write(fx.MODELS + XD_US_REV0.model_position_offset,
                      b"".join(fx.f32(v) for v in (900.0, 0.0, 900.0)))
        after = {e.identity: e.label for e in source.entities()}
        self.assertEqual(before, after)

    def test_letters_reset_on_a_room_change(self):
        registry = LetterRegistry()
        self.assertEqual(registry.letter(0x86, (7, 0)), "A")
        self.assertEqual(registry.letter(0x87, (7, 5)), "A")

    def test_a_name_appearing_later_does_not_relabel_the_others(self):
        source, _, backend = make_source(
            [fx.Character(res_id=0), fx.Character(res_id=1),
             fx.Character(res_id=2)], names={7: "Eagun"})
        first = {e.identity: e.label for e in source.entities()}
        self.assertEqual(first[("npc", fx.DEFAULT_GROUP, 1)], "B")
        record = fx.CHAR_RECORDS + 1 * XD_US_REV0.floor_character_stride
        backend.write(record + XD_US_REV0.floor_character_name_offset,
                      fx.u16(7))
        source.runtime._floor_cache_id = None
        second = {e.identity: e.label for e in source.entities()}
        self.assertEqual(second[("npc", fx.DEFAULT_GROUP, 1)], "Eagun")
        self.assertEqual(second[("npc", fx.DEFAULT_GROUP, 0)], "A")
        self.assertEqual(second[("npc", fx.DEFAULT_GROUP, 2)], "C")


class RoleResolutionTests(unittest.TestCase):
    def test_role_comes_from_the_talk_script_not_the_room(self):
        source, _, _ = make_source(
            [fx.Character(res_id=0, talk_script_id=0x01000007),
             fx.Character(res_id=1, talk_script_id=0x01000006),
             fx.Character(res_id=2, talk_script_id=0x01000008)],
            roles={0x86: {7: "Pokemon Mart clerk"}})
        labels = {e.identity[2]: e.label for e in source.entities()}
        self.assertEqual(labels[0], "Pokemon Mart clerk")
        self.assertNotEqual(labels[1], "Pokemon Mart clerk")
        self.assertNotEqual(labels[2], "Pokemon Mart clerk")

    def test_unknown_talk_script_resolves_to_no_role(self):
        resolver = NPCRoleResolver({0x86: {7: "Pokemon Mart clerk"}})
        self.assertIsNone(resolver.resolve(0x86, 0x01000999))
        self.assertIsNone(resolver.resolve(0x99, 0x01000007))

    def test_a_talk_id_of_an_unknown_kind_resolves_to_no_role(self):
        # Only the 0x01 kind is known to address the room script's function
        # table. Masking an unknown kind and looking the low bits up anyway
        # would manufacture a confident wrong label.
        resolver = NPCRoleResolver({0x86: {7: "Pokemon Mart clerk"}})
        self.assertIsNone(resolver.resolve(0x86, 0x02000007))
        self.assertIsNone(resolver.resolve(0x86, 7))
        self.assertEqual(
            resolver.resolve(0x86, 0x01000007), "Pokemon Mart clerk")

    def test_role_is_exposed_as_subtype_and_metadata(self):
        source, _, _ = make_source(
            [fx.Character(res_id=0, talk_script_id=0x01000007)],
            roles={0x86: {7: "Pokemon Mart clerk"}})
        entity = source.entities()[0]
        self.assertEqual(entity.subtype, "Pokemon Mart clerk")
        self.assertEqual(entity.metadata["role"], "Pokemon Mart clerk")


class AgatePokeMartTests(unittest.TestCase):
    """The reported defect, end to end, against the REAL derived table."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1] / "assets" / "npc_roles.json"
        cls.resolver = NPCRoleResolver(
            json.loads(path.read_text(encoding="utf-8")))

    def test_agate_mart_has_exactly_one_clerk_script(self):
        table = self.resolver.table[0x86]
        clerks = [talk for talk, role in table.items()
                  if role == "Pokemon Mart clerk"]
        self.assertEqual(len(clerks), 1)

    def test_agate_pokemon_centre_has_exactly_one_nurse_script(self):
        table = self.resolver.table[0x85]
        nurses = [talk for talk, role in table.items()
                  if role == "Pokemon Center nurse"]
        self.assertEqual(len(nurses), 1)

    def test_three_mart_npcs_yield_one_clerk_and_two_ordinary(self):
        clerk_index = next(iter(self.resolver.table[0x86]))
        encode = lambda index: (ROOM_SCRIPT_KIND << 24) | index
        memory, _ = fx.build([
            fx.Character(res_id=0, talk_script_id=encode(clerk_index)),
            fx.Character(res_id=1, talk_script_id=encode(clerk_index + 1)),
            fx.Character(res_id=2, talk_script_id=encode(clerk_index + 3)),
        ], floor_id=0x86)
        source = LiveNPCEntitySource(
            PeopleRuntimeSource(memory, XD_US_REV0), Pose(), {},
            role_resolver=self.resolver, logger=Logger())
        entities = source.entities()
        clerks = [e for e in entities if e.metadata.get("role")]
        self.assertEqual(len(clerks), 1)
        self.assertEqual(clerks[0].label, "Pokemon Mart clerk")
        # Revised 2026-08-10: the letter is the NPC's place in the WHOLE
        # roster, so the clerk (first in the room) occupies ordinal 0
        # without displaying it and the two shoppers are "B" and "C". The
        # point of the change is that a player can count to a letter.
        self.assertEqual(
            sorted(e.label for e in entities if not e.metadata.get("role")),
            ["B", "C"])

    def test_two_genuine_clerks_are_both_retained(self):
        clerk_script = (ROOM_SCRIPT_KIND << 24) | next(
            iter(self.resolver.table[0x86]))
        memory, _ = fx.build([
            fx.Character(res_id=0, talk_script_id=clerk_script,
                         live_position=(0.0, 0.0, 0.0)),
            fx.Character(res_id=1, talk_script_id=clerk_script,
                         live_position=(4.0, 0.0, 0.0)),
        ], floor_id=0x86)
        source = LiveNPCEntitySource(
            PeopleRuntimeSource(memory, XD_US_REV0), Pose(), {},
            role_resolver=self.resolver, logger=Logger())
        clerks = [e for e in source.entities() if e.metadata.get("role")]
        self.assertEqual(len(clerks), 2)
        self.assertEqual(len({c.identity for c in clerks}), 2)

    def test_the_role_table_generalises_beyond_agate(self):
        marts = [room for room, roles in self.resolver.table.items()
                 if "Pokemon Mart clerk" in roles.values()]
        self.assertGreater(len(marts), 5)
        self.assertIn(0x86, marts)


class EligibilityFilterTests(unittest.TestCase):
    def test_hidden_npc_is_not_offered(self):
        source, _, _ = make_source([fx.Character(res_id=0, displayed=False)])
        self.assertEqual(source.entities(), [])

    def test_talk_flag_blocked_npc_is_not_offered(self):
        source, _, _ = make_source([fx.Character(res_id=0, flags=1)])
        self.assertEqual(source.entities(), [])

    def test_talk_start_type_three_npc_is_not_offered(self):
        source, _, _ = make_source([fx.Character(res_id=0, talk_start_type=3)])
        self.assertEqual(source.entities(), [])

    def test_a_distant_npc_stays_navigable(self):
        source, _, _ = make_source(
            [fx.Character(res_id=0, live_position=(500.0, 0.0, 500.0))])
        entities = source.entities()
        self.assertEqual(len(entities), 1)
        self.assertFalse(entities[0].metadata["verdict"].eligible)
        self.assertFalse(entities[0].metadata["verdict"].in_range)

    def test_interaction_distance_is_the_engine_threshold(self):
        source, _, _ = make_source(
            [fx.Character(res_id=0, info_id=4, talk_distance=3.0)],
            infos={4: (-1, 3.5, 99.0)}, hero_model=fx.MODELS + 0x4000,
            pose=Pose(model=fx.MODELS + 0x4000))
        entity = source.entities()[0]
        # hero ball 3.5 + live talk 3.0 + npc ball 3.5, NOT the static 99.
        self.assertAlmostEqual(entity.interaction_distance, 10.0)

    def test_metadata_carries_generation_and_interaction_position(self):
        source, _, _ = make_source([fx.Character(res_id=0)])
        metadata = source.entities()[0].metadata
        self.assertIn("generation", metadata)
        self.assertIn("interaction_position", metadata)
        self.assertIn("verdict", metadata)


class LifecycleTests(unittest.TestCase):
    def test_npc_despawning_removes_it_immediately(self):
        source, _, backend = make_source(
            [fx.Character(res_id=0), fx.Character(res_id=1)])
        self.assertEqual(len(source.entities()), 2)
        record = fx.WORK_RECORDS + 1 * XD_US_REV0.people_work_stride
        backend.write(record + XD_US_REV0.people_work_occupied_offset,
                      bytes([0]))
        self.assertEqual(len(source.entities()), 1)

    def test_npc_appearing_dynamically_is_picked_up(self):
        source, _, backend = make_source(
            [fx.Character(res_id=0), fx.Character(res_id=1, spawned=False)])
        self.assertEqual(len(source.entities()), 1)
        # The pool grows: a script spawning an NPC mid-room raises
        # `_people_num` as well as filling the slot.
        backend.write(XD_US_REV0.people_work_count_address, fx.u32(2))
        record = fx.WORK_RECORDS + 1 * XD_US_REV0.people_work_stride
        backend.write(record + XD_US_REV0.people_work_occupied_offset,
                      bytes([1]))
        backend.write(record + XD_US_REV0.people_work_disp_offset, bytes([1]))
        backend.write(record + XD_US_REV0.people_work_identity_a_offset,
                      fx.u32(fx.DEFAULT_GROUP))
        backend.write(record + XD_US_REV0.people_work_identity_b_offset,
                      fx.u32(1))
        # The actor carries the people-info record's ID, not the static
        # record's index -- so copy it off the twin already spawned at the
        # same type rather than writing the index and calling it an id.
        # Writing `10` here is precisely defect R6, and it must not pass.
        backend.write(
            record + XD_US_REV0.people_work_people_info_offset,
            backend.read_bytes(
                fx.WORK_RECORDS + XD_US_REV0.people_work_people_info_offset, 4))
        model = fx.MODELS + 1 * fx.MODEL_STRIDE
        backend.write(record + XD_US_REV0.people_work_model_offset,
                      fx.u32(model))
        backend.write(record + XD_US_REV0.people_work_talk_distance_offset,
                      fx.f32(3.0))
        backend.write(model + XD_US_REV0.model_position_offset,
                      b"".join(fx.f32(v) for v in (2.0, 0.0, 2.0)))
        self.assertEqual(len(source.entities()), 2)

    def test_positions_are_never_cached_between_calls(self):
        source, _, backend = make_source([fx.Character(res_id=0)])
        first = source.entities()[0].position.x
        backend.write(fx.MODELS + XD_US_REV0.model_position_offset,
                      b"".join(fx.f32(v) for v in (33.0, 0.0, 0.0)))
        second = source.entities()[0].position.x
        self.assertNotEqual(first, second)
        self.assertEqual(second, 33.0)

    def test_static_metadata_is_cached_per_room_and_rebuilt_on_change(self):
        source, runtime, backend = make_source([fx.Character(res_id=0)])
        source.entities()
        self.assertEqual(runtime._floor_cache_id, 0x86)
        backend.write(XD_US_REV0.current_floor_id, fx.u16(0x87))
        backend.write(fx.FLOOR_TABLE + XD_US_REV0.floor_id_offset,
                      fx.u16(0x87))
        source.entities()
        self.assertEqual(runtime._floor_cache_id, 0x87)

    def test_unreadable_memory_raises_rather_than_publishing_a_guess(self):
        from battle_narrator.memory import MemoryError as GameMemoryError
        source, _, backend = make_source([fx.Character(res_id=0)])
        backend.write(XD_US_REV0.people_work_count_address, fx.u32(0xFFFFFFF))
        with self.assertRaises(GameMemoryError):
            source.entities()

    def test_rejections_are_recorded_for_diagnosis_not_spoken(self):
        source, _, _ = make_source([
            fx.Character(res_id=0),
            fx.Character(res_id=1, group_id=fx.DEFAULT_GROUP + 9),
        ])
        entities = source.entities()
        self.assertEqual(len(entities), 1)
        self.assertTrue(source.rejected)
        self.assertTrue(source.logger.debug_lines)


class RoleTableDerivationTests(unittest.TestCase):
    SCRIPT = """
.section "FTBL":
\t.function talk_122_shop_m, "talk_122_shop_m"
\t.function talk_121_ojisan1, "talk_121_ojisan1"
\t.function helper, "helper"
\t.function talk_130_via_helper, "talk_130_via_helper"

.section "CODE":
talk_122_shop_m:
\tcallstd       Dialogs::openPokemartMenu
talk_121_ojisan1:
\tcallstd       Character::talk
helper:
\tcallstd       Dialogs::openPokemartMenu
talk_130_via_helper:
\tcall          helper
"""

    def test_roles_are_keyed_on_the_declaration_index(self):
        """Settled live 2026-08-09: a live talk id's low bits are the
        function's INDEX (0x01000007 -> 7), not the number in its name
        (122). Keying on the name's number is defect R7 and matched
        nothing in the real game."""
        roles = room_roles(self.SCRIPT)
        self.assertEqual(roles[0], "Pokemon Mart clerk")   # talk_122_shop_m
        self.assertNotIn(122, roles)

    def test_ordinary_npc_gets_no_role(self):
        self.assertNotIn(1, room_roles(self.SCRIPT))       # talk_121_ojisan1

    def test_marker_reached_through_a_helper_resolves(self):
        self.assertEqual(
            room_roles(self.SCRIPT)[3], "Pokemon Mart clerk")

    def test_the_helper_itself_is_emitted_and_is_harmless(self):
        # A function no NPC's talk id points at is never looked up, and
        # filtering by a `talk_` name would silently miss every room whose
        # shop function is called something else.
        self.assertEqual(set(room_roles(self.SCRIPT)), {0, 2, 3})

    def test_the_function_table_stops_at_the_first_repeat(self):
        # The dumps declare every function twice (FTBL, then HEAD).
        self.assertEqual(
            function_table(self.SCRIPT),
            ["talk_122_shop_m", "talk_121_ojisan1", "helper",
             "talk_130_via_helper"])

    def test_parser_attributes_calls_to_the_declaring_function(self):
        graph = parse_room_script(self.SCRIPT)
        self.assertIn("Dialogs::openPokemartMenu", graph["talk_122_shop_m"][1])
        self.assertNotIn(
            "Dialogs::openPokemartMenu", graph["talk_121_ojisan1"][1])

    def test_resolver_round_trips_through_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roles.json"
            path.write_text(json.dumps({"0x86": {"7": "Pokemon Mart clerk"}}),
                            encoding="utf-8")
            resolver = NPCRoleResolver.from_json(path)
            self.assertEqual(
                resolver.resolve(0x86, 0x01000007), "Pokemon Mart clerk")


if __name__ == "__main__":
    unittest.main()
