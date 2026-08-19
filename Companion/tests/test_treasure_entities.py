"""Item boxes and loose/story pickups, against the engine's own state model.

Every behaviour here traces to `_floorInitTresure` (0x8011F838) or
`floorEventCtrlTresure` (0x80121934). The distinction that shapes the whole
file: mode 0, the "this has been taken" branch, keeps a **kind 1** actor
and changes its pose, and **hides** a kind 2/3 actor outright. So a
collected box remains a landmark and a collected loose item does not.
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.memory import MemoryReader
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.profile import XD_US_REV0
from battle_narrator.treasure_entities import (
    BOX_LABEL, KIND_BOX, LOOSE_LABEL, LiveTreasureEntitySource,
    OPENED_BOX_LABEL, TREASURE_RESID_MARKER, parse_records,
)

COUNT_PTR_TARGET = 0x80700000
TABLE = 0x80710000
STRIDE = 0x1C
ROOM = 0x86


class Backend:
    def __init__(self):
        self.data = {}

    def write(self, address, payload):
        for offset, value in enumerate(payload):
            self.data[address + offset] = value

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + i, 0) for i in range(size))


def u32(v):
    return struct.pack(">I", v & 0xFFFFFFFF)


def u16(v):
    return struct.pack(">H", v & 0xFFFF)


def f32(v):
    return struct.pack(">f", v)


class Record:
    def __init__(self, kind=KIND_BOX, room=ROOM, collected_flag=0,
                 spawn_flag=0, item_id=0, position=(1.0, 0.0, 2.0),
                 category=0, facing=0):
        self.kind = kind
        self.room = room
        self.collected_flag = collected_flag
        self.spawn_flag = spawn_flag
        self.item_id = item_id
        self.position = position
        self.category = category
        self.facing = facing


def build(records, room=ROOM):
    backend = Backend()
    backend.write(0x804E88F0, u32(COUNT_PTR_TARGET))
    backend.write(COUNT_PTR_TARGET, u32(len(records)))
    backend.write(0x804E88F4, u32(TABLE))
    backend.write(XD_US_REV0.current_floor_id, u16(room))
    for index, record in enumerate(records):
        address = TABLE + index * STRIDE
        flags = ((record.kind & 0x7) << 5) | ((record.category & 0x7) << 2)
        backend.write(address, bytes([flags]))
        backend.write(address + 0x02, struct.pack(">h", record.facing))
        backend.write(address + 0x04, u16(record.room))
        backend.write(address + 0x06, u16(record.collected_flag))
        backend.write(address + 0x08, u16(record.spawn_flag))
        backend.write(address + 0x0C, u32(record.item_id))
        backend.write(address + 0x10,
                      b"".join(f32(v) for v in record.position))
    return MemoryReader(backend, XD_US_REV0), backend


class Flags:
    def __init__(self, values=None, broken=()):
        self.values = dict(values or {})
        self.broken = set(broken)

    def value(self, number):
        if number in self.broken:
            raise RuntimeError("flag unreadable")
        return self.values.get(number, 0)


class Actor:
    def __init__(self, res_id, position=None, displayed=True, blocked=False):
        self.res_id = res_id
        self.position = position
        self.displayed = displayed
        self.talk_flag_blocked = blocked
        self.people_info_id = 1
        self.talk_distance = 3.0
        self.facing = 0.0
        self.model = 0x80800000

    @property
    def is_treasure(self):
        return (self.res_id & 0xFFFF0000) == TREASURE_RESID_MARKER


class Runtime:
    def __init__(self, actors=()):
        self._actors = tuple(actors)

    def actors(self):
        return self._actors

    def people_info(self, info_id):
        return None

    def hero_actor(self, address, actors=None):
        return None


def source(records, flags=None, actors=(), room=ROOM):
    memory, backend = build(records, room=room)
    live = LiveTreasureEntitySource(
        memory, XD_US_REV0, Flags(flags), runtime=Runtime(actors))
    live.pose_source = FakePose()
    return live, backend


class FakePose:
    def player_pose(self):
        return PlayerPose(Position(0.0, 0.0, 0.0), 0.0, 0.0)

    def hero_model_address(self):
        return 0


def labels(entities):
    return sorted(e.label for e in entities)


class RecordDecodingTests(unittest.TestCase):
    def test_kind_comes_from_the_top_three_bits(self):
        memory, _ = build([Record(kind=3, category=5)])
        record = parse_records(memory, ROOM)[0]
        self.assertEqual(record.kind, 3)
        self.assertEqual(record.category, 5)

    def test_non_placeable_kinds_are_ignored(self):
        # _floorInitTresure selects a model only for 1, 2 and 3.
        for kind in (0, 4, 5, 6, 7):
            memory, _ = build([Record(kind=kind)])
            self.assertEqual(parse_records(memory, ROOM), ())

    def test_all_three_placeable_kinds_are_kept(self):
        memory, _ = build([Record(kind=1), Record(kind=2), Record(kind=3)])
        self.assertEqual(
            [r.kind for r in parse_records(memory, ROOM)], [1, 2, 3])

    def test_records_from_other_rooms_are_excluded(self):
        memory, _ = build([Record(room=0x99), Record(room=ROOM)])
        records = parse_records(memory, ROOM)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].table_index, 1)

    def test_ordinals_count_only_the_owning_room(self):
        memory, _ = build([
            Record(room=ROOM), Record(room=0x99), Record(room=ROOM)])
        records = parse_records(memory, ROOM)
        self.assertEqual([r.ordinal for r in records], [0, 1])
        self.assertEqual([r.table_index for r in records], [0, 2])

    def test_the_ordinal_counter_advances_past_unplaceable_kinds(self):
        # _floorInitTresure increments the resID counter before the kind
        # decides anything, so skipping kind 0 here would shift every later
        # ordinal and mis-key every actor in the room.
        memory, _ = build([
            Record(kind=0, room=ROOM), Record(kind=1, room=ROOM)])
        records = parse_records(memory, ROOM)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].ordinal, 1)

    def test_res_id_carries_the_marker_and_the_ordinal(self):
        memory, _ = build([Record(), Record()])
        records = parse_records(memory, ROOM)
        self.assertEqual(records[1].res_id, TREASURE_RESID_MARKER | 1)

    def test_a_non_finite_position_is_skipped_not_published(self):
        memory, backend = build([Record()])
        backend.write(TABLE + 0x10, struct.pack(">I", 0x7F800000))
        self.assertEqual(parse_records(memory, ROOM), ())

    def test_identity_is_the_global_table_index(self):
        memory, _ = build([Record(room=0x99), Record(room=ROOM)])
        self.assertEqual(parse_records(memory, ROOM)[0].identity, ("item", 1))


class ItemBoxTests(unittest.TestCase):
    def test_unopened_box_is_labelled_and_beacons(self):
        live, _ = source([Record(kind=1, collected_flag=100)])
        entity = live.entities()[0]
        self.assertEqual(entity.label, BOX_LABEL)
        self.assertTrue(entity.metadata["beacon"])

    def test_opened_box_is_relabelled(self):
        live, _ = source([Record(kind=1, collected_flag=100)],
                         flags={100: 1})
        self.assertEqual(live.entities()[0].label, OPENED_BOX_LABEL)

    def test_opened_box_stops_beaconing(self):
        live, _ = source([Record(kind=1, collected_flag=100)],
                         flags={100: 1})
        self.assertFalse(live.entities()[0].metadata["beacon"])

    def test_opened_box_remains_in_navigation_as_a_landmark(self):
        # floorEventCtrlTresure mode 0 keeps a kind 1 actor and only
        # changes its pose, so the box is physically still there.
        live, _ = source([Record(kind=1, collected_flag=100)],
                         flags={100: 1})
        self.assertEqual(len(live.entities()), 1)

    def test_opened_box_is_not_interactable(self):
        live, _ = source([Record(kind=1, collected_flag=100)],
                         flags={100: 1})
        entity = live.entities()[0]
        self.assertFalse(entity.metadata["interactable"])
        self.assertIsNone(entity.interaction_distance)

    def test_state_changes_without_a_room_reload(self):
        flags = Flags({100: 0})
        memory, _ = build([Record(kind=1, collected_flag=100)])
        live = LiveTreasureEntitySource(memory, XD_US_REV0, flags,
                                        runtime=Runtime())
        live.pose_source = FakePose()
        self.assertEqual(live.entities()[0].label, BOX_LABEL)
        flags.values[100] = 1
        self.assertEqual(live.entities()[0].label, OPENED_BOX_LABEL)
        self.assertFalse(live.entities()[0].metadata["beacon"])

    def test_two_boxes_holding_the_same_item_stay_distinct(self):
        live, _ = source([
            Record(kind=1, item_id=42, collected_flag=100,
                   position=(1.0, 0.0, 1.0)),
            Record(kind=1, item_id=42, collected_flag=101,
                   position=(9.0, 0.0, 9.0)),
        ], flags={100: 1})
        entities = live.entities()
        self.assertEqual(len({e.identity for e in entities}), 2)
        self.assertEqual(labels(entities), [BOX_LABEL, OPENED_BOX_LABEL])

    def test_an_unspawned_box_is_absent(self):
        live, _ = source([Record(kind=1, spawn_flag=200)], flags={200: 0})
        self.assertEqual(live.entities(), [])

    def test_a_box_with_no_live_actor_still_publishes_from_flags(self):
        # Both state flags are ordinary general flags, so the answer does
        # not depend on the actor pool having been read.
        live, _ = source([Record(kind=1, collected_flag=100)], actors=())
        self.assertEqual(live.entities()[0].label, BOX_LABEL)
        self.assertFalse(live.entities()[0].metadata["has_actor"])


class LooseItemTests(unittest.TestCase):
    def test_a_loose_item_uses_the_generic_label(self):
        live, _ = source([Record(kind=2)])
        self.assertEqual(live.entities()[0].label, LOOSE_LABEL)

    def test_a_script_hidden_live_item_is_absent(self):
        live, _ = source(
            [Record(kind=2)],
            actors=[Actor(TREASURE_RESID_MARKER | 0, displayed=False)])
        self.assertEqual(live.entities(), [])

    def test_live_visibility_overrides_a_set_spawn_flag(self):
        live, _ = source(
            [Record(kind=2, spawn_flag=200)], flags={200: 1},
            actors=[Actor(TREASURE_RESID_MARKER | 0, displayed=False)])
        self.assertEqual(live.entities(), [])

    def test_absent_before_its_spawn_flag_is_set(self):
        live, _ = source([Record(kind=2, spawn_flag=200)], flags={200: 0})
        self.assertEqual(live.entities(), [])

    def test_appears_as_soon_as_the_spawn_flag_is_set(self):
        flags = Flags({200: 0})
        memory, _ = build([Record(kind=2, spawn_flag=200)])
        live = LiveTreasureEntitySource(memory, XD_US_REV0, flags,
                                        runtime=Runtime())
        live.pose_source = FakePose()
        self.assertEqual(live.entities(), [])
        flags.values[200] = 1
        entities = live.entities()
        self.assertEqual(len(entities), 1)
        self.assertTrue(entities[0].metadata["beacon"])

    def test_a_pda_style_story_item_needs_no_special_case(self):
        # A one-time story pickup is an ordinary kind 2/3 record with both
        # flags set: gated on spawn, removed on collection.
        flags = Flags({200: 0, 100: 0})
        memory, _ = build([Record(kind=2, spawn_flag=200, collected_flag=100)])
        live = LiveTreasureEntitySource(memory, XD_US_REV0, flags,
                                        runtime=Runtime())
        live.pose_source = FakePose()
        self.assertEqual(live.entities(), [])          # before the story
        flags.values[200] = 1
        self.assertEqual(len(live.entities()), 1)      # spawned
        flags.values[100] = 1
        self.assertEqual(live.entities(), [])          # taken

    def test_a_collected_loose_item_disappears_and_is_silent(self):
        live, _ = source([Record(kind=2, collected_flag=100)], flags={100: 1})
        self.assertEqual(live.entities(), [])

    def test_a_script_removing_a_story_item_removes_the_entity(self):
        # The static record survives; the collected flag is what counts.
        live, _ = source([Record(kind=3, collected_flag=100)], flags={100: 1})
        self.assertEqual(live.entities(), [])

    def test_re_entering_the_room_after_collection_stays_empty(self):
        live, _ = source([Record(kind=2, collected_flag=100)], flags={100: 1})
        self.assertEqual(live.entities(), [])
        live.records(0x99)           # a room change, then back
        self.assertEqual(live.entities(), [])


class PositionTests(unittest.TestCase):
    def test_the_live_actor_position_wins_over_the_spawn_record(self):
        live, _ = source(
            [Record(kind=2, position=(1.0, 0.0, 2.0))],
            actors=[Actor(TREASURE_RESID_MARKER | 0,
                          position=Position(50.0, 0.0, 60.0))])
        entity = live.entities()[0]
        self.assertEqual(entity.position, Position(50.0, 0.0, 60.0))
        self.assertEqual(
            entity.metadata["spawn_position"], Position(1.0, 0.0, 2.0))

    def test_the_spawn_record_is_used_when_no_actor_exists(self):
        live, _ = source([Record(kind=2, position=(1.0, 0.0, 2.0))])
        self.assertEqual(live.entities()[0].position, Position(1.0, 0.0, 2.0))

    def test_an_actor_with_no_readable_position_falls_back(self):
        live, _ = source(
            [Record(kind=2, position=(1.0, 0.0, 2.0))],
            actors=[Actor(TREASURE_RESID_MARKER | 0, position=None)])
        self.assertEqual(live.entities()[0].position, Position(1.0, 0.0, 2.0))

    def test_actors_are_matched_by_res_id_not_by_order(self):
        live, _ = source(
            [Record(kind=2), Record(kind=2)],
            actors=[Actor(TREASURE_RESID_MARKER | 1,
                          position=Position(7.0, 0.0, 7.0))])
        by_ordinal = {
            e.metadata["ordinal"]: e.position for e in live.entities()}
        self.assertEqual(by_ordinal[1], Position(7.0, 0.0, 7.0))
        self.assertNotEqual(by_ordinal[0], Position(7.0, 0.0, 7.0))


class UnresolvedStateTests(unittest.TestCase):
    def test_an_unreadable_collected_flag_publishes_nothing(self):
        live, _ = source([Record(kind=1, collected_flag=100)],
                         flags=None)
        live.flag_reader = Flags(broken={100})
        self.assertEqual(live.entities(), [])

    def test_an_unreadable_spawn_flag_publishes_nothing(self):
        live, _ = source([Record(kind=2, spawn_flag=200)])
        live.flag_reader = Flags(broken={200})
        self.assertEqual(live.entities(), [])

    def test_no_flag_reader_leaves_flagged_records_unresolved(self):
        memory, _ = build([Record(kind=1, collected_flag=100)])
        live = LiveTreasureEntitySource(memory, XD_US_REV0, None,
                                        runtime=Runtime())
        live.pose_source = FakePose()
        self.assertEqual(live.entities(), [])

    def test_a_record_with_no_flags_is_always_present(self):
        # _floorInitTresure leaves such a record displayed and available.
        live, _ = source([Record(kind=1, collected_flag=0, spawn_flag=0)])
        entity = live.entities()[0]
        self.assertEqual(entity.label, BOX_LABEL)
        self.assertTrue(entity.metadata["spawned"])
        self.assertFalse(entity.metadata["collected"])


class MetadataTests(unittest.TestCase):
    def test_item_id_is_carried_but_never_spoken(self):
        live, _ = source([Record(kind=1, item_id=0x1234)])
        entity = live.entities()[0]
        self.assertEqual(entity.metadata["item_id"], 0x1234)
        self.assertEqual(entity.label, BOX_LABEL)

    def test_subtype_separates_boxes_from_loose_pickups(self):
        live, _ = source([Record(kind=1), Record(kind=2), Record(kind=3)])
        self.assertEqual(
            [e.subtype for e in live.entities()], ["box", "loose", "loose"])


class BeaconSplitTests(unittest.TestCase):
    """Beacon eligibility must be expressible separately from navigation
    eligibility -- audit cause F. An opened box is the case that needs it."""

    def test_navigation_and_beacon_disagree_for_an_opened_box(self):
        live, _ = source([Record(kind=1, collected_flag=100)], flags={100: 1})
        entity = live.entities()[0]
        self.assertEqual(len(live.entities()), 1)
        self.assertFalse(entity.metadata["beacon"])

    def test_the_beacon_bridge_drops_silenced_entities(self):
        from battle_narrator.entity_sources import WarpAugmentedNPCSource
        from battle_narrator.entities import Entity

        class Source:
            def entities(self):
                return [
                    Entity("item", ("item", 1), "Item box", Position(0, 0, 0),
                           metadata={"beacon": True}),
                    Entity("item", ("item", 2), "Opened item box",
                           Position(0, 0, 0), metadata={"beacon": False}),
                    Entity("item", ("item", 3), "No opinion",
                           Position(0, 0, 0)),
                ]

        class Npcs:
            def npcs(self):
                return []

            def current_floor_id(self):
                return ROOM

            def player_pose(self):
                return None

        published = WarpAugmentedNPCSource(
            Npcs(), Source(), category="item").npcs()
        self.assertEqual(
            sorted(n.label for n in published),
            ["Item box", "No opinion"])


if __name__ == "__main__":
    unittest.main()
