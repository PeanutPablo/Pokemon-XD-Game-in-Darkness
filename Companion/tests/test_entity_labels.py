"""Room labels derived from game data, and NPC roster ordinals.

Two defects this pins, both reported live 2026-08-10:

- "Agate Village Day-Care" sat on `M3_houseB_1F`, which makes no Daycare
  call at all. `M3_houseD_1F` is the only room in all 425 extracted
  scripts that calls `Daycare::depositPkm`.
- unnamed NPCs were lettered "the nth unnamed NPC", so a room of
  Eagun / Beluh / unnamed / unnamed spoke A and B instead of C and D.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import people_fixture as fx
from battle_narrator.entity_sources import LetterRegistry, LiveNPCEntitySource
from battle_narrator.npc_beacons import PlayerPose, Position
from battle_narrator.npc_roles import NPCRoleResolver, ROOM_SCRIPT_KIND
from battle_narrator.people_runtime import PeopleRuntimeSource
from battle_narrator.player_facing_names import (
    EXACT_ROOM_NAMES, build_room_names, player_facing_room_name,
)
from battle_narrator.profile import XD_US_REV0

COMPANION = Path(__file__).parents[1]
SERVICES = COMPANION / "assets" / "room_services.json"
ROOMS = COMPANION / "assets" / "room_ids.json"
HAVE_ASSETS = SERVICES.exists() and ROOMS.exists()


class Pose:
    def __init__(self):
        self.position = Position(0.0, 0.0, 0.0)
        self.facing = 0.0
        self.model = None

    def player_pose(self):
        return PlayerPose(self.position, 0.0, 0.0)

    def hero_model_address(self):
        return None


class Logger:
    def __init__(self):
        self.debug_lines = []

    def debug(self, *args):
        self.debug_lines.append(args)

    def info(self, *args):
        pass

    def warning(self, *args):
        pass


def labels_for(characters, names=None, roles=None, floor_id=0x86):
    memory, backend = fx.build(characters, floor_id=floor_id)
    source = LiveNPCEntitySource(
        PeopleRuntimeSource(memory, XD_US_REV0), Pose(), names or {},
        role_resolver=NPCRoleResolver(roles or {}), logger=Logger())
    return source, backend


def talk(index):
    return (ROOM_SCRIPT_KIND << 24) | index


class DayCareLabelTests(unittest.TestCase):
    def test_the_wrong_day_care_hardcode_is_gone(self):
        self.assertNotIn("M3_houseB_1F", EXACT_ROOM_NAMES)

    def test_an_unprovable_resident_name_is_not_asserted(self):
        self.assertNotIn("M3_houseA_1F", EXACT_ROOM_NAMES)

    def test_a_derived_service_names_an_otherwise_generic_house(self):
        self.assertEqual(
            player_facing_room_name(
                "M3_houseD_1F", {"M3_houseD_1F": "Day-Care"}),
            "Day-Care, 1st floor")

    def test_a_house_with_no_service_stays_generic(self):
        self.assertEqual(
            player_facing_room_name("M3_houseB_1F", {}),
            "house, 1st floor")

    def test_a_service_never_renames_a_room_the_code_already_names(self):
        # M2_out has a vending machine. It is not "Pyrite Town Pokemon Mart".
        self.assertEqual(
            player_facing_room_name("M2_out", {"M2_out": "Pokemon Mart"}),
            "Pyrite Town")
        self.assertEqual(
            player_facing_room_name("M3_pc_1F", {"M3_pc_1F": "Pokemon Center"}),
            "Pokemon Center, 1st floor")

    def test_build_room_names_threads_the_services_through(self):
        names = build_room_names(
            {0x83: "M3_houseD_1F", 0x80: "M3_houseB_1F"},
            {"M3_houseD_1F": "Day-Care"})
        self.assertEqual(names[0x83], "Day-Care, 1st floor")
        self.assertEqual(names[0x80], "house, 1st floor")

    @unittest.skipUnless(HAVE_ASSETS, "generated assets not present")
    def test_the_generated_table_puts_the_day_care_on_house_d(self):
        services = json.loads(SERVICES.read_text(encoding="utf-8"))
        self.assertEqual(services.get("M3_houseD_1F"), "Day-Care")
        self.assertNotIn("M3_houseB_1F", services)

    @unittest.skipUnless(HAVE_ASSETS, "generated assets not present")
    def test_agate_labels_end_to_end(self):
        codes = {int(k, 16): v for k, v in
                 json.loads(ROOMS.read_text(encoding="utf-8")).items()}
        names = build_room_names(
            codes, json.loads(SERVICES.read_text(encoding="utf-8")))
        self.assertEqual(names[0x83], "Day-Care, 1st floor")
        self.assertEqual(names[0x86], "Pokemon Mart, 1st floor")
        self.assertEqual(names[0x85],
                         "Pokemon Center, 1st floor")
        self.assertEqual(names[0x87], "Relic Stone")
        self.assertNotIn("Day-Care", names[0x80])
        for room in (0x7F, 0x80, 0x81):
            self.assertNotIn("Eagun", names[room] or "")


class RosterOrdinalTests(unittest.TestCase):
    """The letter is the NPC's place in the WHOLE roster, so the player can
    count to it. Named and role NPCs occupy a position without showing it."""

    def test_two_named_then_two_unnamed_gives_c_and_d(self):
        source, _ = labels_for([
            fx.Character(res_id=0, name_id=1),
            fx.Character(res_id=1, name_id=2),
            fx.Character(res_id=2),
            fx.Character(res_id=3),
        ], names={1: "Eagun", 2: "Beluh"})
        self.assertEqual([e.label for e in source.entities()],
                         ["Eagun", "Beluh", "C", "D"])

    def test_a_role_npc_consumes_its_ordinal_without_showing_it(self):
        source, _ = labels_for([
            fx.Character(res_id=0, name_id=1),
            fx.Character(res_id=1, name_id=2),
            fx.Character(res_id=2),
            fx.Character(res_id=3),
            fx.Character(res_id=4, talk_script_id=talk(7)),
        ], names={1: "Eagun", 2: "Beluh"},
            roles={0x86: {7: "Pokemon Mart clerk"}})
        self.assertEqual(
            [e.label for e in source.entities()],
            ["Eagun", "Beluh", "C", "D", "Pokemon Mart clerk"])

    def test_a_named_npc_in_the_middle_still_advances_the_letters(self):
        source, _ = labels_for([
            fx.Character(res_id=0),
            fx.Character(res_id=1, name_id=1),
            fx.Character(res_id=2),
            fx.Character(res_id=3, name_id=2),
        ], names={1: "Beluh", 2: "Logan"})
        self.assertEqual([e.label for e in source.entities()],
                         ["A", "Beluh", "C", "Logan"])

    def test_all_unnamed_is_a_dense_sequence(self):
        source, _ = labels_for([fx.Character(res_id=i) for i in range(4)])
        self.assertEqual([e.label for e in source.entities()],
                         ["A", "B", "C", "D"])

    def test_all_named_shows_no_letters(self):
        source, _ = labels_for([
            fx.Character(res_id=0, name_id=1),
            fx.Character(res_id=1, name_id=2),
        ], names={1: "Eagun", 2: "Beluh"})
        self.assertEqual([e.label for e in source.entities()],
                         ["Eagun", "Beluh"])

    def test_no_npc_prefix_is_ever_spoken(self):
        source, _ = labels_for([fx.Character(res_id=0)])
        self.assertEqual(source.entities()[0].label, "A")

    def test_movement_does_not_renumber(self):
        source, backend = labels_for(
            [fx.Character(res_id=0), fx.Character(res_id=1)])
        before = {e.identity: e.label for e in source.entities()}
        backend.write(fx.MODELS + XD_US_REV0.model_position_offset,
                      b"".join(fx.f32(v) for v in (800.0, 0.0, 800.0)))
        self.assertEqual({e.identity: e.label for e in source.entities()},
                         before)

    def test_a_despawn_does_not_renumber_the_survivors(self):
        source, backend = labels_for([fx.Character(res_id=i) for i in range(3)])
        before = {e.identity: e.label for e in source.entities()}
        record = fx.WORK_RECORDS + 1 * XD_US_REV0.people_work_stride
        backend.write(record + XD_US_REV0.people_work_occupied_offset,
                      bytes([0]))
        after = {e.identity: e.label for e in source.entities()}
        self.assertEqual(after[("npc", fx.DEFAULT_GROUP, 2)],
                         before[("npc", fx.DEFAULT_GROUP, 2)])
        self.assertEqual(after[("npc", fx.DEFAULT_GROUP, 0)], "A")

    def test_a_name_resolving_later_leaves_the_others_alone(self):
        registry = LetterRegistry()
        for index in range(4):
            registry.ordinal(0x86, ("npc", 7, index))
        self.assertEqual(registry.letter(0x86, ("npc", 7, 2)), "C")
        self.assertEqual(registry.letter(0x86, ("npc", 7, 3)), "D")

    def test_a_room_change_resets_the_roster(self):
        registry = LetterRegistry()
        self.assertEqual(registry.ordinal(0x86, ("npc", 7, 5)), 0)
        self.assertEqual(registry.ordinal(0x87, ("npc", 7, 9)), 0)

    def test_ordinals_are_unique_within_a_room(self):
        source, _ = labels_for([fx.Character(res_id=i) for i in range(5)])
        ordinals = [e.metadata["ordinal"] for e in source.entities()]
        self.assertEqual(sorted(ordinals), list(range(5)))

    def test_a_duplicate_slot_does_not_consume_an_ordinal(self):
        source, _ = labels_for([
            fx.Character(res_id=0), fx.Character(res_id=1),
        ])
        self.assertEqual(
            [e.metadata["ordinal"] for e in source.entities()], [0, 1])


class OnwardDestinationTests(unittest.TestCase):
    """Duplicate exit labels get a MEANINGFUL distinction from the warp
    graph before falling back to letters.

    Agate has two rooms that both render as "Agate Village cave, 1st
    floor". One leads onward to the Relic Stone and one is a dead end, and
    "cave A" / "cave B" -- letters in table order -- told the player
    nothing about which."""

    class Record:
        def __init__(self, room_id, target_room_id):
            self.room_id = room_id
            self.target_room_id = target_room_id

    def test_a_pass_through_room_reports_its_onward_room(self):
        from battle_narrator.authoritative_warps import onward_destinations
        onward = onward_destinations([
            self.Record(0x7D, 0x84), self.Record(0x7D, 0x87),
            self.Record(0x7E, 0x84),
        ])
        self.assertEqual(onward[0x7D][0x84], 0x87)

    def test_a_dead_end_has_no_onward_room(self):
        from battle_narrator.authoritative_warps import onward_destinations
        onward = onward_destinations([self.Record(0x7E, 0x84)])
        self.assertNotIn(0x7E, onward)

    def test_the_onward_room_disambiguates_instead_of_a_letter(self):
        from battle_narrator.authoritative_warps import _disambiguate_labels
        from battle_narrator.entities import Entity
        from battle_narrator.npc_beacons import Position
        entities = [
            Entity("warp", ("warp", 1), "to Agate Village cave, 1st floor",
                   Position(0, 0, 0), metadata={"target_room_id": 0x7D}),
            Entity("warp", ("warp", 2), "to Agate Village cave, 1st floor",
                   Position(0, 0, 0), metadata={"target_room_id": 0x7E}),
        ]
        labels = sorted(e.label for e in _disambiguate_labels(
            entities, {0x7D: {0x84: 0x87}}, {0x87: "Relic Stone"}, 0x84))
        self.assertEqual(labels, [
            "to Agate Village cave, 1st floor",
            "to Agate Village cave, 1st floor, toward Relic Stone",
        ])

    def test_another_floor_of_the_same_building_is_not_a_destination(self):
        from battle_narrator.authoritative_warps import _disambiguate_labels
        from battle_narrator.entities import Entity
        from battle_narrator.npc_beacons import Position
        entities = [
            Entity("warp", ("warp", 1), "to house in Agate Village, 1st floor",
                   Position(0, 0, 0), metadata={"target_room_id": 0x81}),
            Entity("warp", ("warp", 2), "to house in Agate Village, 1st floor",
                   Position(0, 0, 0), metadata={"target_room_id": 0x7F}),
        ]
        labels = sorted(e.label for e in _disambiguate_labels(
            entities, {0x81: {0x84: 0x82}},
            {0x82: "house in Agate Village, 2nd floor"}, 0x84))
        self.assertEqual(labels, [
            "to house in Agate Village, 1st floor A",
            "to house in Agate Village, 1st floor B",
        ])

    def test_a_unique_label_is_left_alone(self):
        from battle_narrator.authoritative_warps import _disambiguate_labels
        from battle_narrator.entities import Entity
        from battle_narrator.npc_beacons import Position
        entities = [Entity("warp", ("warp", 1), "to world map",
                           Position(0, 0, 0), metadata={})]
        self.assertEqual(
            [e.label for e in _disambiguate_labels(entities, {}, {}, 0x84)],
            ["to world map"])


class PurifyChamberLabelTests(unittest.TestCase):
    """The one PC that is a Purify Chamber terminal, and only that one."""

    def test_the_hq_lab_pc_is_named_the_purify_chamber(self):
        from battle_narrator.authoritative_warps import PC_LABEL_OVERRIDES
        self.assertEqual(PC_LABEL_OVERRIDES.get(695), "Purify Chamber")

    def test_every_other_pc_keeps_the_generic_label(self):
        from battle_narrator.authoritative_warps import PC_LABEL_OVERRIDES
        self.assertEqual(list(PC_LABEL_OVERRIDES), [695])

    @unittest.skipUnless(HAVE_ASSETS, "generated assets not present")
    def test_record_695_is_the_only_pc_in_the_hq_lab(self):
        """Pins the identity the override is keyed on. If a re-extraction
        renumbers the interaction table, this fails rather than silently
        renaming some unrelated PC."""
        import struct
        import _dialogue_extraction_tool as extraction
        common = COMPANION / "_dialogue_extraction" / "raw" / "files" / "common.fsys"
        if not common.exists():
            self.skipTest("extraction not present")
        files = extraction.parse_fsys(common.read_bytes())
        data = next(f["data"] for f in files
                    if f["name"] in {"common.rel", "common_rel"})
        rel = extraction.RelFile(data)
        table = rel.get_pointer(62)
        count = struct.unpack_from(">I", data, rel.get_pointer(63))[0]
        pcs = []
        for index in range(count):
            offset = table + index * 0x1C
            if struct.unpack_from(">H", data, offset + 0x08)[0] != 0x0596:
                continue
            if struct.unpack_from(">H", data, offset + 0x0A)[0] != 0x0E:
                continue
            if struct.unpack_from(">H", data, offset + 0x02)[0] != 0x8C:
                continue
            pcs.append((index, data[offset + 0x07]))
        self.assertEqual(pcs, [(695, 5)])


if __name__ == "__main__":
    unittest.main()
