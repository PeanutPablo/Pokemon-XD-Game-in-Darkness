"""A synthetic but structurally faithful game memory image for NPC tests.

Lays out the real chain -- floor_data -> floor_character array,
peopleInfoData, tagPeopleWork, and per-actor models -- at the real offsets
and strides from `profile.XD_US_REV0`, so a test that passes here is
exercising the same field arithmetic production does. Values are invented;
the STRUCTURE is not.
"""
import struct

from battle_narrator.memory import MemoryReader
from battle_narrator.profile import XD_US_REV0


P = XD_US_REV0

BASE = 0x80500000
FLOOR_COUNT_ROOT = BASE + 0x0000
FLOOR_TABLE = BASE + 0x0100
CHAR_SLOT = BASE + 0x1000
CHAR_HEADER = BASE + 0x1100
CHAR_COUNT = BASE + 0x1200
CHAR_RECORDS = BASE + 0x1300
INFO_COUNT = BASE + 0x2000
INFO_TABLE = BASE + 0x2100
WORK_RECORDS = BASE + 0x3000
MODELS = BASE + 0x8000
MODEL_STRIDE = 0x100

DEFAULT_GROUP = 7


class Backend:
    """Sparse byte-addressed store. Unwritten addresses read as zero, which
    is what an untouched game structure looks like."""

    def __init__(self):
        self.data = {}

    def write(self, address, payload):
        for offset, value in enumerate(payload):
            self.data[address + offset] = value

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + i, 0) for i in range(size))


def u32(value):
    return struct.pack(">I", value & 0xFFFFFFFF)


def u16(value):
    return struct.pack(">H", value & 0xFFFF)


def f32(value):
    return struct.pack(">f", value)


PEOPLE_INFO_ID_BASE = 0x11A40400
"""People-info records are keyed by a large, resource-shaped id in their
own `+0x04` field -- `gimmickBox.s` calls `peopleInfoBiosGetPtr` with the
literal `0x11A40400`, and live Agate Mart actors carry `0x15FA0400` /
`0x17220400` / `0x1A700400` at `people_work +0x1C`.

`floor_character +0x06` is something else entirely: a small INDEX into the
same table (81, 116, 145 in that room). The fixture models both namespaces
because conflating them is a real defect this suite has to be able to
catch -- it shipped once (R6, 2026-08-09) and rejected every NPC in the
game."""


def info_id_for_index(index, count):
    """Deliberately NOT `base + index`: ids descend as indices ascend, so a
    reader that quietly swaps one namespace for the other lands on the
    wrong record instead of accidentally working."""
    return PEOPLE_INFO_ID_BASE + (count - index) * 0x100


class Character:
    """One NPC to place into the image.

    `info_id` is the value written to `floor_character +0x06` -- an INDEX
    into the people-info table, matching the game. The actor's own
    `people_work +0x1C` gets that record's large id unless `actor_info_id`
    overrides it."""

    def __init__(self, res_id, info_id=10, name_id=0, talk_script_id=0,
                 position=(0.0, 0.0, 0.0), live_position=None,
                 group_id=DEFAULT_GROUP, spawned=True, displayed=True,
                 flags=0, talk_start_type=0, wall_through=True,
                 static_visible=True, load_init=True, talk_distance=3.0,
                 actor_info_id=None, slot=None, model=None):
        self.res_id = res_id
        self.info_id = info_id
        self.actor_info_id = actor_info_id
        self.name_id = name_id
        self.talk_script_id = talk_script_id
        self.position = position
        self.live_position = live_position or position
        self.group_id = group_id
        self.spawned = spawned
        self.displayed = displayed
        self.flags = flags
        self.talk_start_type = talk_start_type
        self.wall_through = wall_through
        self.static_visible = static_visible
        self.load_init = load_init
        self.talk_distance = talk_distance
        self.slot = slot
        self.model = model


def build(characters, floor_id=0x86, group_id=DEFAULT_GROUP,
          infos=None, hero_model=None, extra_actors=()):
    """Returns (MemoryReader, backend). `infos` maps people-info table
    INDEX -> (neck index, collision ball, static talk distance)."""
    backend = Backend()
    infos = dict(infos or {})
    for character in characters:
        infos.setdefault(character.info_id, (-1, 3.5, 3.0))
    for character in extra_actors:
        infos.setdefault(character.info_id, (-1, 3.5, 3.0))
    if hero_model is not None:
        infos.setdefault(99, (-1, 3.5, 3.0))

    # floor_data: one record, holding the character-slot pointer and the
    # language-indexed group id table.
    backend.write(P.floor_data_count_root, u32(FLOOR_COUNT_ROOT))
    backend.write(FLOOR_COUNT_ROOT, u32(1))
    backend.write(P.floor_data_root, u32(FLOOR_TABLE))
    backend.write(FLOOR_TABLE + P.floor_id_offset, u16(floor_id))
    backend.write(FLOOR_TABLE + P.floor_character_slot_offset, u32(CHAR_SLOT))
    for slot in range(P.floor_data_group_id_slots):
        backend.write(
            FLOOR_TABLE + P.floor_data_group_id_offset + 4 * slot,
            u32(group_id))
    backend.write(P.current_floor_id, u16(floor_id))

    # floor_character array.
    backend.write(CHAR_SLOT, u32(CHAR_HEADER))
    backend.write(CHAR_HEADER, u32(CHAR_COUNT))
    backend.write(CHAR_HEADER + 4, u32(CHAR_RECORDS))
    count = (max((c.res_id for c in characters), default=-1) + 1)
    backend.write(CHAR_COUNT, u32(count))
    for character in characters:
        record = CHAR_RECORDS + character.res_id * P.floor_character_stride
        flags0 = 0
        if character.static_visible:
            flags0 |= P.floor_character_visible_mask
        if character.load_init:
            flags0 |= 1 << 6
        if character.wall_through:
            flags0 |= 1 << 3
        backend.write(record, bytes([flags0]))
        backend.write(record + 0x01,
                      bytes([(character.talk_start_type & 0x3) << 3]))
        backend.write(record + P.floor_character_people_info_offset,
                      u16(character.info_id))
        backend.write(record + P.floor_character_name_offset,
                      u16(character.name_id))
        backend.write(record + P.floor_character_talk_offset,
                      u32(character.talk_script_id))
        backend.write(record + P.floor_character_position_offset,
                      b"".join(f32(v) for v in character.position))

    # peopleInfoData is a real ARRAY -- `floor_character +0x06` indexes it
    # directly -- but each record also carries its own large id at +0x04,
    # and `peopleInfoBiosGetPtr` LINEAR SEARCHES for that id rather than
    # indexing. Both access paths are therefore modelled, with the ids
    # descending as the indices ascend so neither can stand in for the
    # other by accident.
    info_count = max(infos) + 1 if infos else 0
    backend.write(P.people_info_count_root, u32(INFO_COUNT))
    backend.write(INFO_COUNT, u32(info_count))
    backend.write(P.people_info_root, u32(INFO_TABLE))
    info_ids = {}
    for index in range(info_count):
        neck, ball, talk = infos.get(index, (-1, 3.5, 3.0))
        info_ids[index] = info_id_for_index(index, info_count)
        record = INFO_TABLE + index * P.people_info_stride
        backend.write(record + P.people_info_id_offset, u32(info_ids[index]))
        backend.write(record + P.people_info_neck_index_offset,
                      struct.pack(">b", neck))
        backend.write(record + P.people_info_col_ball_offset, f32(ball))
        backend.write(record + P.people_info_talk_distance_offset, f32(talk))

    # tagPeopleWork. Slots are assigned first so `_people_num` can cover
    # every explicitly-placed slot -- a count that stopped short would make
    # the source simply not see the actor, and a test asserting a rejection
    # would pass for the wrong reason.
    actors = [c for c in characters if c.spawned] + list(extra_actors)
    assignments = []
    cursor = 0
    for character in actors:
        assigned = character.slot if character.slot is not None else cursor
        assignments.append((assigned, character))
        cursor = max(cursor, assigned) + 1
    hero_slot = cursor if hero_model is not None else None
    total = cursor + (1 if hero_model is not None else 0)
    backend.write(P.people_work_count_address, u32(total))
    backend.write(P.people_work_root_address, u32(WORK_RECORDS))

    def place(slot, group, res, info_id, displayed, flags, model, position,
              talk_distance, facing=0.0):
        record = WORK_RECORDS + slot * P.people_work_stride
        backend.write(record + P.people_work_occupied_offset, bytes([1]))
        backend.write(record + P.people_work_disp_offset,
                      bytes([1 if displayed else 0]))
        backend.write(record + P.people_work_identity_a_offset, u32(group))
        backend.write(record + P.people_work_identity_b_offset, u32(res))
        backend.write(record + P.people_work_flags_offset, u32(flags))
        backend.write(record + P.people_work_people_info_offset, u32(info_id))
        backend.write(record + P.people_work_model_offset, u32(model))
        backend.write(record + P.people_work_rot_y_offset, f32(facing))
        backend.write(record + P.people_work_talk_distance_offset,
                      f32(talk_distance))
        if position is not None:
            backend.write(model + P.model_position_offset,
                          b"".join(f32(v) for v in position))

    for assigned, character in assignments:
        model = (character.model if character.model is not None
                 else MODELS + assigned * MODEL_STRIDE)
        # The actor carries the record's ID; the static record carries its
        # INDEX. `actor_info_id`, when given explicitly, is used verbatim so
        # a test can force a genuine disagreement.
        actor_info = (
            character.actor_info_id
            if character.actor_info_id is not None
            else info_ids.get(character.info_id, 0)
        )
        place(assigned, character.group_id, character.res_id,
              actor_info, character.displayed, character.flags,
              model, character.live_position, character.talk_distance)
    if hero_slot is not None:
        place(hero_slot, group_id, 0xFF, info_ids.get(99, 0), True, 0,
              hero_model, (0.0, 0.0, 0.0), 0.0)

    return MemoryReader(backend, P), backend
