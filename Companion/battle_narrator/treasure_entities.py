"""Live, state-aware item boxes and loose/story pickups.

Ownership chain, traced end to end in the verified vanilla US XD build
(`xd-decomp/build/GXXE01/asm/game/pxdvs/app/floor/`) on 2026-08-09. Every
field below has a named owner, a read site and a write site.

    floor_tresure_list  (count 0x804E88F0, base 0x804E88F4, stride 0x1C)
      +0x00 bits 5-7  placement kind   (byte >> 5) & 7
      +0x00 bits 2-4  pickup category  (byte >> 2) & 7  -> floorEventGetTresure
      +0x01           script-writable  <- floorEventChangeTresure
      +0x02  s16      facing           -> peopleSetRot
      +0x04  u16      owning room id
      +0x06  u16      COLLECTED general flag
      +0x08  u16      SPAWN general flag
      +0x0C  u32      item id          <- floorEventChangeTresure
      +0x10..0x18     spawn position   -> peopleSetPos
        |
        v
    _floorInitTresure (0x8011F838), at room load, for each record in room:
        peopleOpen(group, 0x7FFF0000 | ordinal, model)   ordinal counts
                                                          THIS ROOM's records
        peopleSetPos / peopleSetRot / peopleAddCollision
        peopleSetFlagOn(actor, 4)      <- marks it a treasure actor
        peopleSetDisp(actor, 1)
        peopleBiosSetTresureID(actor, global table index)
        if +0x06 and GSflagTest(+0x06):  floorEventCtrlTresure(.., 0)  "taken"
        else:                            floorEventCtrlTresure(.., 1)  "available"
             if +0x08 and !GSflagTest(+0x08): peopleSetDisp(actor, 0)  "unspawned"

    floorEventCtrlTresure (0x80121934) is the whole state machine:
        mode 0  "taken"      kind 1 -> motion 2 (open pose) + peopleSetFlagOn(1)
                             kinds 2/3 -> peopleSetDisp(0)
        mode 1  "available"  motion 0
        mode 2  "pick it up" early-returns if GSflagTest(+0x06);
                             kind 1 plays the opening motion and sound 0x461;
                             then mode 0, then **GSflagOn(+0x06)**, then
                             floorEventGetTresure(category, item id, +0x01)

    heroMove (0x8014FE14): A press -> peopleCheckTresure -> CtrlTresure mode 2

What kinds 1, 2 and 3 actually are
----------------------------------
Not inferred from appearance -- read off mode 0, the "this has been taken"
branch:

- **kind 1 keeps its actor and changes pose.** `peopleSetMotion(.., 2, ..)`
  plus `peopleSetFlagOn(actor, 1)`, and bit 0 of `people_work +0x10` is
  exactly what makes `peopleTalkCheck` skip an actor. So a collected kind 1
  is still standing there, in an opened pose, and can no longer be
  interacted with. That is an **item box**, and it is why "Opened item box"
  can remain a landmark: the object genuinely remains.
- **kinds 2 and 3 disappear.** `peopleSetDisp(actor, 0)`. Nothing is left
  to navigate to. Those are **loose pickups** -- ground items, sparkles,
  dropped and story items.

Kind 0 and kinds 4-7 select no model in `_floorInitTresure` and are not
placeable; they are ignored here rather than guessed at.

The state model is readable WITHOUT a live actor
------------------------------------------------
Both state flags are ordinary general flags, so collected and spawned are
answerable from the record plus `GeneralFlagReader` even before the room's
actors exist. The live actor corroborates and supplies the true position;
it is not the only source of truth. This is what lets a script-driven
spawn or collection appear immediately, with no room reload.
"""
from dataclasses import dataclass
import math
import struct

from .entities import Entity
from .memory import MemoryError
from .npc_beacons import NPCMemorySource, Position
from .talk_predicate import TalkInputs, evaluate

TABLE_COUNT_PTR = 0x804E88F0
TABLE_BASE_PTR = 0x804E88F4
STRIDE = 0x1C
MAX_PLAUSIBLE_RECORDS = 4096

KIND_SHIFT = 5
KIND_MASK = 0x7
CATEGORY_SHIFT = 2
"""`extrwi r0, r0, 3, 24` = `(byte >> 5) & 7` for the placement kind, and
`extrwi r3, r0, 3, 27` = `(byte >> 2) & 7` for the category handed to
`floorEventGetTresure`. Two independent call sites agree on the first."""

KIND_BOX = 1
KINDS_LOOSE = (2, 3)
PLACEABLE_KINDS = (KIND_BOX,) + KINDS_LOOSE

TREASURE_RESID_MARKER = 0x7FFF0000
TREASURE_ORDINAL_MASK = 0x1FF
"""`floorEventGetTresureList` validates the marker and then takes the low
**9** bits as the room ordinal (`clrlwi r27, r3, 23`)."""

BOX_LABEL = "Item box"
OPENED_BOX_LABEL = "Opened item box"
LOOSE_LABEL = "Item"
"""Accessibility-owned object-class labels, which the audit brief permits.
Deliberately NOT the resolved item name: the game does not reveal what a
box or a ground sparkle contains until it is taken, so naming it would be
inventing information the player could not otherwise have -- and would
spoil it. The item id is read and carried in metadata for diagnostics and
for any later feature that has a reason to use it."""


@dataclass(frozen=True)
class TreasureRecord:
    """One `floor_tresure_list` entry. Static per room visit."""

    table_index: int
    """The global index. `peopleBiosSetTresureID` puts this on the actor,
    and it is stable across rooms -- the better of the two engine keys."""
    ordinal: int
    """Position among THIS room's records, which is what the actor's resID
    carries."""
    address: int
    kind: int
    category: int
    room_id: int
    collected_flag: int
    spawn_flag: int
    item_id: int
    facing: int
    position: object
    """The spawn point `peopleSetPos` writes at room load. NOT where the
    object is now -- see `TreasureState.position`."""

    @property
    def res_id(self):
        return TREASURE_RESID_MARKER | (self.ordinal & TREASURE_ORDINAL_MASK)

    @property
    def is_box(self):
        return self.kind == KIND_BOX

    @property
    def identity(self):
        return ("item", self.table_index)


@dataclass(frozen=True)
class TreasureState:
    """A record resolved against live flags and the live actor pool."""

    record: object
    collected: bool
    spawned: bool
    actor: object
    displayed: object
    position: object
    unresolved: object = None
    """Set when a flag could not be read. An unresolved pickup is published
    nowhere -- see the class docstring in ENTITY_STATE_AND_BEACON_POLICY.md."""

    @property
    def exists(self):
        return self.unresolved is None

    @property
    def interactable(self):
        """A collected box keeps its actor but the engine sets
        `people_work +0x10` bit 0 on it, so the game itself will not talk
        to it any more."""
        return self.exists and self.spawned and not self.collected

    @property
    def landmark(self):
        """A collected box is still a physical object in the room. A
        collected loose pickup is not: `floorEventCtrlTresure` mode 0 hides
        it outright."""
        if not self.exists:
            return False
        if self.record.is_box:
            return self.spawned
        return self.spawned and not self.collected

    @property
    def beacon(self):
        """Narrower than navigation, deliberately: a beacon claims that
        going there is useful NOW, which an opened box is not."""
        return self.interactable

    @property
    def label(self):
        if not self.record.is_box:
            return LOOSE_LABEL
        return OPENED_BOX_LABEL if self.collected else BOX_LABEL


def parse_records(memory, room_id=None):
    """Every placeable record, with per-room ordinals assigned exactly as
    `_floorInitTresure` assigns them.

    The ordinal counter advances for every record belonging to the room,
    including kinds the engine gives no model -- the increment sits on the
    common path, before the kind is used. Filtering by kind first would
    shift every later ordinal and mis-key every actor in the room."""
    count = memory.u32(
        memory.pointer(TABLE_COUNT_PTR, 4, "treasure table count ptr", 4),
        "treasure table count")
    if count > MAX_PLAUSIBLE_RECORDS:
        raise MemoryError(f"implausible treasure table count {count}")
    base = memory.pointer(
        TABLE_BASE_PTR, max(1, count) * STRIDE, "treasure table base", 4)
    ordinals = {}
    records = []
    for index in range(count):
        address = base + index * STRIDE
        flags = memory.u8(address, f"treasure flags {index}")
        room = memory.u16(address + 0x04, f"treasure room {index}")
        ordinal = ordinals.get(room, 0)
        ordinals[room] = ordinal + 1
        if room_id is not None and room != room_id:
            continue
        kind = (flags >> KIND_SHIFT) & KIND_MASK
        if kind not in PLACEABLE_KINDS:
            continue
        values = struct.unpack(">fff", memory.bytes(
            address + 0x10, 12, f"treasure position {index}", 4))
        if not all(math.isfinite(value) for value in values):
            continue
        records.append(TreasureRecord(
            table_index=index,
            ordinal=ordinal,
            address=address,
            kind=kind,
            category=(flags >> CATEGORY_SHIFT) & KIND_MASK,
            room_id=room,
            collected_flag=memory.u16(address + 0x06, "treasure collected flag"),
            spawn_flag=memory.u16(address + 0x08, "treasure spawn flag"),
            item_id=memory.u32(address + 0x0C, "treasure item id"),
            facing=struct.unpack(
                ">h", memory.bytes(address + 0x02, 2, "treasure facing", 2))[0],
            position=Position(*values),
        ))
    return tuple(records)


class LiveTreasureEntitySource:
    """Item boxes and loose pickups, gated by the game's own state.

    Static record definitions are cached per room; collected, spawned,
    displayed and position are re-read every query and never cached, so a
    script that spawns or removes a pickup is reflected without a room
    reload."""

    def __init__(self, memory, profile, flag_reader=None, runtime=None,
                 logger=None):
        self.memory, self.profile = memory, profile
        self.flag_reader = flag_reader
        self.runtime = runtime
        self.logger = logger
        self.pose_source = NPCMemorySource(memory, profile)
        self._room_id = None
        self._records = ()
        self._surveyed = False

    def player_pose(self):
        return self.pose_source.player_pose()

    def _flag(self, number):
        """None when it cannot be answered -- never a guessed default."""
        if not number:
            return None
        if self.flag_reader is None:
            return None
        try:
            return bool(self.flag_reader.value(number))
        except Exception:
            return None

    def records(self, room_id):
        if room_id != self._room_id:
            self._records = parse_records(self.memory, room_id)
            self._room_id = room_id
            self._surveyed = False
        return self._records

    def survey(self, states, room_id):
        """Log every treasure record in the room and why it is or is not
        published -- ONCE per room entry, not per tick.

        A pickup that never appears is invisible by definition: the player
        cannot tell "no item here" from "the item is being filtered". This
        makes the difference readable. Added 2026-08-13 for the
        beginning-of-game PDA, which does not appear in Items and whose
        record cannot be inspected offline -- `floor_tresure_list` is
        built at room load and exists only in live memory."""
        if self.logger is None or self._surveyed:
            return
        self._surveyed = True
        self.logger.info(
            "TREASURE SURVEY room=0x%02X: %d placeable record(s)",
            room_id, len(states))
        for state in states:
            record = state.record
            if not state.exists:
                verdict = f"UNRESOLVED ({state.unresolved})"
            elif state.landmark:
                verdict = f"published as {state.label!r}"
            elif not state.spawned:
                verdict = "hidden: spawn flag clear"
            elif state.collected:
                verdict = "hidden: collected"
            else:
                verdict = "hidden"
            self.logger.info(
                "  TREASURE idx=%d ordinal=%d kind=%d cat=%d item=0x%X "
                "collected_flag=%d(%s) spawn_flag=%d(%s) actor=%s disp=%s "
                "pos=(%.1f,%.1f,%.1f) -> %s",
                record.table_index, record.ordinal, record.kind,
                record.category, record.item_id,
                record.collected_flag, self._flag(record.collected_flag),
                record.spawn_flag, self._flag(record.spawn_flag),
                state.actor is not None, state.displayed,
                state.position.x, state.position.y, state.position.z,
                verdict)

    def _actors_by_res_id(self):
        if self.runtime is None:
            return {}
        try:
            return {
                actor.res_id: actor
                for actor in self.runtime.actors()
                if actor.is_treasure
            }
        except Exception:
            return {}

    def states(self, room_id=None):
        """Every placeable record in the room, resolved against live state.
        Exposed for the diagnostic and the tests, not just for entities()."""
        if room_id is None:
            room_id = self.memory.u16(
                self.profile.current_floor_id, "treasure room id")
        actors = self._actors_by_res_id()
        result = []
        for record in self.records(room_id):
            collected = self._flag(record.collected_flag)
            spawned = self._flag(record.spawn_flag)
            unresolved = None
            if record.collected_flag and collected is None:
                unresolved = f"collected flag {record.collected_flag} unreadable"
            if record.spawn_flag and spawned is None:
                unresolved = f"spawn flag {record.spawn_flag} unreadable"
            actor = actors.get(record.res_id)
            result.append(TreasureState(
                record=record,
                # A record with no collected flag can never be collected,
                # and one with no spawn flag is present from room load --
                # both are the engine's own behaviour in _floorInitTresure,
                # not a default chosen here.
                collected=bool(collected) if record.collected_flag else False,
                spawned=bool(spawned) if record.spawn_flag else True,
                actor=actor,
                displayed=None if actor is None else actor.displayed,
                position=(
                    actor.position if actor is not None
                    and actor.position is not None else record.position),
                unresolved=unresolved,
            ))
        return tuple(result)

    def _verdict(self, state, pose):
        """The treasure slice of `peopleTalkCheck`, which is NOT the NPC
        slice. Established from the branch at 0x802A3684, reached exactly
        when `floorCharacterBiosFindByResID` returns NULL:

        - the wall check is **skipped entirely** for treasure (the branch
          forces the wall flag to 0), so `wall_through=True` here;
        - there is no static record, so the talk-start-type gate does not
          apply;
        - kind 1 additionally requires the player to be within a cone of
          the BOX's own rotation. Its argument order is not established, so
          it is reported UNKNOWN rather than evaluated -- which downgrades
          the wording to "In range" instead of promising a press will land.
        """
        actor = state.actor
        if actor is None or self.runtime is None:
            return None
        try:
            info = self.runtime.people_info(actor.people_info_id)
            hero = self.runtime.hero_actor(self.pose_source.hero_model_address())
            hero_info = (self.runtime.people_info(hero.people_info_id)
                         if hero is not None else None)
        except Exception:
            return None
        if info is None:
            return None
        verdict = evaluate(TalkInputs(
            displayed=actor.displayed,
            talk_flag_blocked=actor.talk_flag_blocked,
            talk_start_type=0,
            hero_position=pose.position,
            neck_position=state.position,
            hero_facing=hero.facing if hero is not None else pose.facing,
            hero_col_ball_size=(
                hero_info.col_ball_size if hero_info is not None else 0.0),
            npc_col_ball_size=info.col_ball_size,
            talk_distance=actor.talk_distance,
            wall_through=True,
            wall_blocked=None,
        ))
        if state.record.is_box and verdict.eligible:
            from dataclasses import replace as _replace
            return _replace(
                verdict, eligible=False,
                unknown_gates=verdict.unknown_gates + ("box approach angle",))
        return verdict

    def entities(self):
        room_id = self.memory.u16(
            self.profile.current_floor_id, "treasure room id")
        pose = None
        result = []
        states = self.states(room_id)
        self.survey(states, room_id)
        for state in states:
            if not state.exists:
                if self.logger is not None:
                    self.logger.debug(
                        "TREASURE unresolved index=%d: %s",
                        state.record.table_index, state.unresolved)
                continue
            if not state.landmark:
                continue
            if pose is None:
                pose = self.player_pose()
            verdict = self._verdict(state, pose) if state.interactable else None
            result.append(Entity(
                category="item",
                identity=state.record.identity,
                label=state.label,
                position=state.position,
                interaction_distance=(
                    verdict.threshold if verdict is not None else None),
                subtype="box" if state.record.is_box else "loose",
                metadata={
                    "beacon": state.beacon,
                    "collected": state.collected,
                    "spawned": state.spawned,
                    "interactable": state.interactable,
                    "kind": state.record.kind,
                    "category": state.record.category,
                    "item_id": state.record.item_id,
                    "ordinal": state.record.ordinal,
                    "table_index": state.record.table_index,
                    "has_actor": state.actor is not None,
                    "displayed": state.displayed,
                    "spawn_position": state.record.position,
                    "verdict": verdict,
                },
            ))
        return result
