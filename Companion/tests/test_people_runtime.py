"""Canonical live-actor ownership: which NPCs exist, and how they are keyed.

The rule under test throughout: a published NPC must correspond to a LIVE
actor that belongs to this floor and agrees with its static record. A
static placement record on its own is not an NPC.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import people_fixture as fx
from battle_narrator.people_runtime import (
    TREASURE_RESID_MARKER, PeopleRuntimeSource,
)
from battle_narrator.profile import XD_US_REV0


def source(characters, **kwargs):
    memory, backend = fx.build(characters, **kwargs)
    return PeopleRuntimeSource(memory, XD_US_REV0), backend


class OwnershipTests(unittest.TestCase):
    def test_live_actor_with_matching_static_metadata_publishes(self):
        runtime, _ = source([fx.Character(res_id=0, name_id=42)])
        characters = runtime.characters()
        self.assertEqual(len(characters), 1)
        self.assertEqual(characters[0].static.name_id, 42)

    def test_static_record_with_no_live_actor_publishes_nothing(self):
        runtime, _ = source([fx.Character(res_id=0, spawned=False)])
        self.assertEqual(runtime.characters(), ())

    def test_static_only_npc_does_not_leak_its_spawn_point(self):
        runtime, _ = source([
            fx.Character(res_id=0, spawned=True, live_position=(5.0, 0.0, 5.0)),
            fx.Character(res_id=1, spawned=False, position=(90.0, 0.0, 90.0)),
        ])
        positions = [c.position for c in runtime.characters()]
        self.assertEqual(len(positions), 1)
        self.assertNotIn(90.0, (positions[0].x, positions[0].z))

    def test_live_position_wins_over_the_scripted_spawn_point(self):
        runtime, _ = source([fx.Character(
            res_id=0, position=(0.0, 0.0, 0.0), live_position=(40.0, 1.0, -8.0))])
        position = runtime.characters()[0].position
        self.assertEqual((position.x, position.y, position.z), (40.0, 1.0, -8.0))

    def test_actor_from_another_floor_group_is_rejected(self):
        runtime, _ = source([
            fx.Character(res_id=0),
            fx.Character(res_id=1, group_id=fx.DEFAULT_GROUP + 5),
        ])
        self.assertEqual(len(runtime.characters()), 1)
        self.assertTrue(any("does not belong" in r.reason
                            for r in runtime.rejected))

    def test_global_follower_slot_is_rejected(self):
        runtime, _ = source([fx.Character(res_id=0),
                             fx.Character(res_id=1, group_id=0)])
        self.assertEqual(len(runtime.characters()), 1)
        self.assertTrue(any("groupID 0" in r.reason for r in runtime.rejected))

    def test_treasure_actor_is_classified_out(self):
        treasure = fx.Character(res_id=TREASURE_RESID_MARKER | 2, slot=5)
        runtime, _ = source([fx.Character(res_id=0)], extra_actors=[treasure])
        self.assertEqual(len(runtime.characters()), 1)
        self.assertTrue(any("treasure" in r.reason for r in runtime.rejected))

    def test_res_id_outside_the_character_array_is_rejected(self):
        stray = fx.Character(res_id=200, slot=4)
        runtime, _ = source([fx.Character(res_id=0)], extra_actors=[stray])
        self.assertEqual(len(runtime.characters()), 1)
        self.assertTrue(any("outside this floor" in r.reason
                            for r in runtime.rejected))

    def test_people_info_mismatch_rejects_the_pairing(self):
        runtime, _ = source([fx.Character(res_id=0, info_id=10,
                                          actor_info_id=0x0BADF00D)])
        self.assertEqual(runtime.characters(), ())
        self.assertTrue(any("people-info mismatch" in r.reason
                            for r in runtime.rejected))

    def test_the_static_index_is_resolved_before_it_is_compared(self):
        """Defect R6, found live 2026-08-09 and fixed the same day.

        `floor_character +0x06` is an INDEX (81, 116, 145 in the Agate
        Mart); `people_work +0x1C` is the record's own large ID
        (0x15FA0400, 0x17220400, 0x1A700400). Comparing them directly can
        never match, so the cross-check rejected every NPC in every room --
        the exact "empties the category" failure that forced the
        2026-08-06 revert. The two must be brought into one namespace
        first."""
        runtime, _ = source([fx.Character(res_id=0, info_id=10)])
        characters = runtime.characters()
        self.assertEqual(len(characters), 1, runtime.rejected)
        actor_id = characters[0].actor.people_info_id
        # The thing that made the bug invisible in tests: a fixture where
        # index and id happen to be equal.
        self.assertNotEqual(
            actor_id, 10,
            "the fixture must model index and id as different namespaces, "
            "or this suite cannot catch R6 at all")
        self.assertEqual(
            runtime.people_info_by_index(10).info_id, actor_id)

    def test_an_unresolvable_static_index_does_not_reject(self):
        """An unverifiable gate must never count as a failed one. If the
        index is outside the table there is nothing to compare, and
        silently dropping the NPC would repeat R6 in a quieter form."""
        runtime, backend = source([fx.Character(res_id=0, info_id=4)],
                                  infos={4: (-1, 3.5, 3.0)})
        backend.write(
            fx.CHAR_RECORDS + XD_US_REV0.floor_character_people_info_offset,
            fx.u16(9999))
        runtime._floor_cache_id = None
        self.assertEqual(len(runtime.characters()), 1, runtime.rejected)

    def test_people_info_by_index_is_bounds_checked(self):
        runtime, _ = source([fx.Character(res_id=0, info_id=4)],
                            infos={4: (-1, 3.5, 3.0)})
        self.assertIsNone(runtime.people_info_by_index(9999))
        self.assertIsNone(runtime.people_info_by_index(-1))

    def test_two_slots_claiming_one_identity_publish_once(self):
        duplicate = fx.Character(res_id=0, slot=6)
        runtime, _ = source([fx.Character(res_id=0)], extra_actors=[duplicate])
        self.assertEqual(len(runtime.characters()), 1)
        self.assertTrue(any("duplicate identity" in r.reason
                            for r in runtime.rejected))

    def test_separate_actors_stay_separate(self):
        runtime, _ = source([
            fx.Character(res_id=0, name_id=1, live_position=(0.0, 0.0, 0.0)),
            fx.Character(res_id=1, name_id=1, live_position=(0.1, 0.0, 0.1)),
        ])
        # Same name, near-identical coordinates -- still two NPCs, because
        # identity is (groupID, resID) and nothing else.
        self.assertEqual(len(runtime.characters()), 2)

    def test_hidden_actor_is_still_published_by_the_pool(self):
        # The POOL reports it; the talk predicate is what excludes it. Two
        # responsibilities, deliberately not merged.
        runtime, _ = source([fx.Character(res_id=0, displayed=False)])
        self.assertEqual(len(runtime.characters()), 1)
        self.assertFalse(runtime.characters()[0].actor.displayed)


class IdentityTests(unittest.TestCase):
    def test_identity_is_group_and_res(self):
        runtime, _ = source([fx.Character(res_id=3)])
        self.assertEqual(runtime.characters()[0].identity,
                         (fx.DEFAULT_GROUP, 3))

    def test_identity_survives_movement(self):
        runtime, backend = source([fx.Character(res_id=0)])
        first = runtime.characters()[0]
        backend.write(fx.MODELS + XD_US_REV0.model_position_offset,
                      b"".join(fx.f32(v) for v in (60.0, 0.0, 60.0)))
        second = runtime.characters()[0]
        self.assertEqual(first.identity, second.identity)
        self.assertEqual(first.generation, second.generation)
        self.assertNotEqual(first.position.x, second.position.x)

    def test_generation_advances_when_the_runtime_entity_is_replaced(self):
        runtime, backend = source([fx.Character(res_id=0)])
        before = runtime.characters()[0].generation
        record = fx.WORK_RECORDS + 0 * XD_US_REV0.people_work_stride
        backend.write(record + XD_US_REV0.people_work_model_offset,
                      fx.u32(fx.MODELS + 0x900))
        backend.write(fx.MODELS + 0x900 + XD_US_REV0.model_position_offset,
                      b"".join(fx.f32(v) for v in (1.0, 0.0, 1.0)))
        after = runtime.characters()[0].generation
        self.assertEqual(after, before + 1)


class PeopleInfoTests(unittest.TestCase):
    def test_lookup_is_by_id_field_not_array_index(self):
        # The fixture stores records in DESCENDING id order on purpose: an
        # index-based read (the pre-Phase-2 behaviour) picks the wrong
        # record and therefore the wrong collision ball.
        runtime, _ = source(
            [fx.Character(res_id=0, info_id=4)],
            infos={4: (-1, 9.0, 3.0), 9: (-1, 1.0, 3.0)})
        self.assertAlmostEqual(runtime.characters()[0].info.col_ball_size, 9.0)

    def test_missing_people_info_rejects(self):
        runtime, backend = source([fx.Character(res_id=0, info_id=4)],
                                  infos={4: (-1, 3.5, 3.0)})
        backend.write(fx.INFO_COUNT, fx.u32(0))
        runtime._info_cache_token = None
        self.assertEqual(runtime.characters(), ())

    def test_live_talk_distance_is_read_from_the_actor(self):
        runtime, _ = source(
            [fx.Character(res_id=0, info_id=4, talk_distance=12.0)],
            infos={4: (-1, 3.5, 3.0)})
        character = runtime.characters()[0]
        self.assertAlmostEqual(character.actor.talk_distance, 12.0)
        self.assertAlmostEqual(character.info.static_talk_distance, 3.0)


class HeroTests(unittest.TestCase):
    def test_hero_actor_is_found_by_model_pointer(self):
        hero_model = fx.MODELS + 0x4000
        runtime, _ = source([fx.Character(res_id=0)], hero_model=hero_model)
        hero = runtime.hero_actor(hero_model)
        self.assertIsNotNone(hero)
        self.assertEqual(hero.model, hero_model)

    def test_unknown_hero_model_returns_none(self):
        runtime, _ = source([fx.Character(res_id=0)])
        self.assertIsNone(runtime.hero_actor(fx.MODELS + 0x7000))


if __name__ == "__main__":
    unittest.main()
