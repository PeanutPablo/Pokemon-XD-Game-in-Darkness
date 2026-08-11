"""Canonical live-actor pool: the game's own `tagPeopleWork` array.

This is the single authority on which NPCs currently exist, where they
actually are, and whether the game will let the player talk to them.
Everything else -- static `floor_character` placement records, the
people-info table -- is *metadata* that gets correlated onto a live actor,
never a source of entities in its own right.

Why this module exists (the defect it replaces)
-----------------------------------------------
`npc_beacons.NPCMemorySource.npcs()` iterates the STATIC
`floor_character` array and then decorates each record with live state
looked up by index. That publishes an entity for every static record
whether or not an actor is spawned, keys live state on `identity_b` alone
without checking the actor belongs to this floor's group, and reads the
people-info table by array index when the engine looks records up by an ID
field. See ENTITY_NAVIGATION_AUDIT.md causes A/B and defect N7.

Ownership chain, all traced by disassembly of the verified vanilla US XD
build (GXXE01 rev 0):

    peopleBiosGetWorkPtr(i)      -> _pPeopleWorkTop + i * 0x1B0,
                                    bounds-checked against _people_num
    floorCharacterBiosFindByResID(groupID, resID)
                                 -> rejects unless groupID equals the
                                    CURRENT floor's group id, then
                                    floorDataBiosGetCharInfo does
                                    charBase + resID * 0x24
    peopleInfoBiosGetPtr(id)     -> LINEAR SEARCH of peopleInfoData for a
                                    record whose +0x04 equals `id`.
                                    NOT an array index.
    peopleBiosGetPosPtr(actor)   -> actor +0x08 (model) -> model +0x18

Read-only. Never writes, never calls into the game.
"""
from dataclasses import dataclass
import math
import struct

from .memory import MemoryError as GameMemoryError
from .npc_beacons import Position


TREASURE_RESID_MARKER = 0x7FFF0000
"""`_floorInitTresure` allocates one people actor per treasure record in
the room with `resID = 0x7FFF0000 | ordinal`, and
`floorEventGetTresureList` validates exactly that marker before accepting
a resID. Actors carrying it are ground pickups, not characters -- Phase 3
owns them. Recognised here only so this module can classify them out
rather than mistake one for a character with an absurd index."""


def _finite(*values):
    return all(math.isfinite(value) for value in values)


@dataclass(frozen=True)
class PeopleInfo:
    """A `peopleInfoData` record -- the actor's TYPE: which model it uses,
    how big its collision ball is, which joint counts as its neck."""

    info_id: int
    """ALSO the model resource id. `peopleInfoBiosGetModelResID` is
    `lwz r3, 0x4(r3)` -- the same `+0x04` field `peopleInfoBiosGetPtr`
    linear-searches on. That is why these are large resource-shaped values
    (`0x15FA0400`, `0x11A40400`) rather than small indices, and it is the
    most promising place for the human-versus-overworld-Pokemon
    distinction to live: a Pokemon actor necessarily uses a Pokemon model.
    Logged by the shadow reader so the split can be found from ordinary
    play rather than guessed from handler names."""
    address: int
    neck_index: int
    """`peopleInfoBiosGetNeckIndex` = signed byte at +0x01. Negative means
    the actor has no neck joint, and `peopleGetPartsPos` falls back to the
    actor's own base position."""
    col_ball_size: float
    """`peopleInfoBiosGetColBallSize` = float at +0x10. One of the three
    terms in the game's talk-distance threshold."""
    static_talk_distance: float
    """Float at +0x24. Retained for comparison ONLY -- the value the talk
    check actually uses is the live `people_work +0x178`. Whether this
    initialises that field is unverified; the diagnostic logs both so the
    question can be settled from evidence."""


@dataclass(frozen=True)
class StaticCharacter:
    """A `floor_character` record: scripted placement plus the talk
    metadata that has no live equivalent."""

    index: int
    address: int
    visible: bool
    load_init: bool
    talk_wall_through: bool
    talk_start_type: int
    talk_end_type: int
    people_info_id: int
    name_id: int
    talk_script_id: int
    position: Position
    """The SPAWN point. Never published as an entity position -- the live
    actor's model position is. Kept so the diagnostic can show how far a
    moved NPC has drifted from it."""


@dataclass(frozen=True)
class LiveActor:
    """One occupied `tagPeopleWork` slot."""

    slot: int
    address: int
    group_id: int
    res_id: int
    displayed: bool
    flags: int
    people_info_id: int
    model: int
    position: object
    facing: object
    talk_distance: float

    @property
    def talk_flag_blocked(self):
        """`peopleBiosCheckFlag(actor, 1)` -- bit 0 of +0x10. When set,
        `peopleTalkCheck` skips the actor outright."""
        return bool(self.flags & 1)

    @property
    def is_treasure(self):
        return (self.res_id & 0xFFFF0000) == TREASURE_RESID_MARKER

    @property
    def identity(self):
        """`(groupID, resID)` -- the engine's own key, the pair
        `floorCharacterBiosFindByResID` takes. Survives the actor moving,
        being hidden, or changing slot; changes when the runtime entity is
        genuinely replaced."""
        return (self.group_id, self.res_id)


@dataclass(frozen=True)
class Character:
    """A live actor successfully correlated with its static record and
    type record. This -- and only this -- is what may become an NPC
    entity."""

    actor: LiveActor
    static: StaticCharacter
    info: PeopleInfo
    generation: int

    @property
    def identity(self):
        return self.actor.identity

    @property
    def position(self):
        return self.actor.position


@dataclass(frozen=True)
class RejectedActor:
    """An actor that could not be published, and why. Surfaced to the
    diagnostic log so a wrong exclusion is investigable, never to speech."""

    slot: int
    group_id: int
    res_id: int
    reason: str


class PeopleRuntimeSource:
    def __init__(self, memory, profile):
        self.memory, self.profile = memory, profile
        self._info_cache = None
        self._info_cache_token = None
        self._floor_cache = {}
        self._floor_cache_id = None
        self._generations = {}
        self._slot_bindings = {}
        self.rejected = ()

    # ---- static metadata, cached per room -----------------------------

    def current_floor_id(self):
        return self.memory.u16(
            self.profile.current_floor_id, "current floor ID")

    def _floor_record(self, floor_id):
        p = self.profile
        count_root = self.memory.pointer(
            p.floor_data_count_root, 4, "floor-data count root", 4)
        count = self.memory.u32(count_root, "floor-data count")
        if count > p.floor_data_max_records:
            raise GameMemoryError(f"invalid floor-data count {count}")
        table = self.memory.pointer(
            p.floor_data_root, max(1, count) * p.floor_data_stride,
            "floor-data table", 4)
        for index in range(count):
            candidate = table + index * p.floor_data_stride
            if self.memory.u16(
                    candidate + p.floor_id_offset, "floor record ID") == floor_id:
                return candidate
        raise GameMemoryError(f"floor record {floor_id} not found")

    def floor_group_ids(self, floor_id):
        """The current floor's group id candidates.

        `floorDataBiosGetGroupID` reads `floorData + 0x2C + 4 * L`, where L
        is a language index derived from `pokecoloGetLanguage()`. That
        language global has not been located, so rather than GUESS an index
        this reads the whole slot range and treats membership in it as the
        test. That is weaker than the engine's exact-slot comparison but
        strictly stronger than the current code's "identity_a != 0", and it
        cannot silently pick the wrong language's id. The diagnostic logs
        which slot actually matched, so the index can be pinned from
        evidence and this widened to an exact check later."""
        p = self.profile
        record = self._floor_record(floor_id)
        return tuple(
            self.memory.u32(
                record + p.floor_data_group_id_offset + 4 * slot,
                f"floor group id {slot}")
            for slot in range(p.floor_data_group_id_slots)
        )

    def static_characters(self, floor_id):
        """`floor_character` records for a room, cached until the room
        changes. Static geometry/metadata may be cached; live state may
        not -- see ENTITY_NAVIGATION_ARCHITECTURE.md."""
        if self._floor_cache_id == floor_id:
            return self._floor_cache
        p = self.profile
        record = self._floor_record(floor_id)
        slot = self.memory.pointer(
            record + p.floor_character_slot_offset, 4,
            "floor character slot", 4)
        header = self.memory.pointer(slot, 8, "floor character header", 4)
        count_pointer = self.memory.pointer(
            header, 4, "floor character count pointer", 4)
        count = self.memory.u32(count_pointer, "floor character count")
        if count > p.floor_character_max_records:
            raise GameMemoryError(f"invalid floor character count {count}")
        base = self.memory.pointer(
            header + 4, max(1, count) * p.floor_character_stride,
            "floor character records", 4)
        characters = {}
        for index in range(count):
            address = base + index * p.floor_character_stride
            flags0 = self.memory.u8(address, "floor character flags 0")
            flags1 = self.memory.u8(address + 0x01, "floor character flags 1")
            values = struct.unpack(">fff", self.memory.bytes(
                address + p.floor_character_position_offset, 12,
                "floor character position", 4))
            if not _finite(*values):
                raise GameMemoryError("floor character position is non-finite")
            characters[index] = StaticCharacter(
                index=index,
                address=address,
                visible=bool(flags0 & p.floor_character_visible_mask),
                load_init=bool((flags0 >> 6) & 1),
                talk_wall_through=bool((flags0 >> 3) & 1),
                talk_start_type=(flags1 >> 3) & 0x3,
                talk_end_type=(flags1 >> 1) & 0x3,
                people_info_id=self.memory.u16(
                    address + p.floor_character_people_info_offset,
                    "floor character people-info id"),
                name_id=self.memory.u16(
                    address + p.floor_character_name_offset,
                    "floor character name id"),
                talk_script_id=self.memory.u32(
                    address + p.floor_character_talk_offset,
                    "floor character talk script id"),
                position=Position(*values),
            )
        self._floor_cache = characters
        self._floor_cache_id = floor_id
        return characters

    def _people_info_table(self):
        p = self.profile
        count_root = self.memory.pointer(
            p.people_info_count_root, 4, "people-info count root", 4)
        count = self.memory.u32(count_root, "people-info count")
        if count > p.people_info_max_records:
            raise GameMemoryError(f"invalid people-info count {count}")
        base = self.memory.pointer(
            p.people_info_root, max(1, count) * p.people_info_stride,
            "people-info table", 4)
        if self._info_cache_token != (base, count):
            self._info_cache = {}
            self._info_cache_token = (base, count)
        return base, count

    def _read_people_info(self, address, info_id):
        p = self.profile
        col_ball = struct.unpack(">f", self.memory.bytes(
            address + p.people_info_col_ball_offset, 4,
            "people-info collision ball", 4))[0]
        talk = struct.unpack(">f", self.memory.bytes(
            address + p.people_info_talk_distance_offset, 4,
            "people-info talk distance", 4))[0]
        return PeopleInfo(
            info_id=info_id,
            address=address,
            neck_index=struct.unpack(">b", self.memory.bytes(
                address + p.people_info_neck_index_offset, 1,
                "people-info neck index", 1))[0],
            col_ball_size=col_ball if math.isfinite(col_ball) else 0.0,
            static_talk_distance=talk if math.isfinite(talk) else 0.0,
        )

    def people_info(self, info_id):
        """`peopleInfoBiosGetPtr` -- a LINEAR SEARCH keyed on the record's
        own `+0x04` id field, not an array index.

        These ids are large, resource-shaped values, NOT small table
        indices. Confirmed two ways: `gimmickBox.s` calls this with the
        literal `0x11A40400`, and live actors in the Agate Mart carry
        `0x15FA0400` / `0x17220400` / `0x1A700400` at `people_work +0x1C`.
        That namespace distinction is the whole of defect R6 -- see
        `people_info_by_index` below."""
        p = self.profile
        base, count = self._people_info_table()
        if info_id in self._info_cache:
            return self._info_cache[info_id]
        for index in range(count):
            address = base + index * p.people_info_stride
            if self.memory.u32(
                    address + p.people_info_id_offset,
                    "people-info id") != info_id:
                continue
            info = self._read_people_info(address, info_id)
            self._info_cache[info_id] = info
            return info
        self._info_cache[info_id] = None
        return None

    def people_info_by_index(self, index):
        """The people-info record at an ARRAY INDEX.

        `floor_character +0x06` is an index into this table -- small
        (81, 116, 145 in the Agate Mart) -- while `people_work +0x1C` is
        the record's own large id. They are different namespaces for the
        same record, and comparing one against the other directly is
        meaningless. This resolves the static side into the id namespace so
        the two CAN be compared.

        Returns None when the index is outside the table, which is
        reported as "cannot check" rather than as a mismatch."""
        p = self.profile
        base, count = self._people_info_table()
        if not 0 <= index < count:
            return None
        address = base + index * p.people_info_stride
        info_id = self.memory.u32(
            address + p.people_info_id_offset, "people-info id by index")
        return self._read_people_info(address, info_id)

    # ---- live pool ----------------------------------------------------

    def _actor_position(self, model):
        p = self.profile
        if not (p.mem1_start <= model < p.mem1_end):
            return None
        try:
            values = struct.unpack(">fff", self.memory.bytes(
                model + p.model_position_offset, 12, "live actor position", 4))
        except GameMemoryError:
            return None
        return Position(*values) if _finite(*values) else None

    def actors(self):
        """Every occupied `tagPeopleWork` slot, unfiltered."""
        p = self.profile
        count = self.memory.u32(
            p.people_work_count_address, "people-work count")
        if count > p.people_work_max_records:
            raise GameMemoryError(f"invalid people-work count {count}")
        if count == 0:
            return ()
        base = self.memory.pointer(
            p.people_work_root_address, count * p.people_work_stride,
            "people-work records", 4)
        result = []
        for slot in range(count):
            address = base + slot * p.people_work_stride
            if not self.memory.u8(
                    address + p.people_work_occupied_offset,
                    "people-work occupied"):
                continue
            model = self.memory.u32(
                address + p.people_work_model_offset, "people-work model")
            facing = None
            try:
                value = struct.unpack(">f", self.memory.bytes(
                    address + p.people_work_rot_y_offset, 4,
                    "people-work rotation", 4))[0]
                facing = value if math.isfinite(value) else None
            except GameMemoryError:
                facing = None
            try:
                talk_distance = struct.unpack(">f", self.memory.bytes(
                    address + p.people_work_talk_distance_offset, 4,
                    "people-work talk distance", 4))[0]
            except GameMemoryError:
                talk_distance = float("nan")
            result.append(LiveActor(
                slot=slot,
                address=address,
                group_id=self.memory.u32(
                    address + p.people_work_identity_a_offset,
                    "people-work group id"),
                res_id=self.memory.u32(
                    address + p.people_work_identity_b_offset,
                    "people-work res id"),
                displayed=bool(self.memory.u8(
                    address + p.people_work_disp_offset, "people-work disp")),
                flags=self.memory.u32(
                    address + p.people_work_flags_offset, "people-work flags"),
                people_info_id=self.memory.u32(
                    address + p.people_work_people_info_offset,
                    "people-work people-info id"),
                model=model,
                position=self._actor_position(model),
                facing=facing,
                talk_distance=(
                    talk_distance if math.isfinite(talk_distance) else 0.0),
            ))
        return tuple(result)

    def hero_actor(self, hero_model_address, actors=None):
        """The hero's own `tagPeopleWork` record, found by matching the
        model pointer this project already resolves for the player pose.

        `peopleTalkCheck` reads two things off it that have no other
        source: the hero's `colBallSize` (via its people-info) and the
        hero's rot.y at +0x40, which is the facing the talk cone is
        measured against. Matching on the model pointer is exact -- one
        model, one actor -- and avoids needing `heroMoveGetResID`."""
        if not hero_model_address:
            return None
        for actor in (self.actors() if actors is None else actors):
            if actor.model == hero_model_address:
                return actor
        return None

    def _generation(self, actor):
        """A monotonically increasing epoch per identity, bumped whenever
        the runtime entity behind that identity is REPLACED -- a different
        slot, or a different model allocation. Ordinary polling, walking,
        and being hidden all leave it untouched, which is exactly the
        "survives ordinary polling but changes when the runtime entity is
        replaced" property the identity strategy requires."""
        identity = actor.identity
        binding = (actor.slot, actor.model)
        previous = self._slot_bindings.get(identity)
        if previous != binding:
            self._slot_bindings[identity] = binding
            if previous is not None:
                self._generations[identity] = (
                    self._generations.get(identity, 0) + 1)
            else:
                self._generations.setdefault(identity, 0)
        return self._generations[identity]

    def characters(self):
        """Live character actors that belong to the current floor and
        correlate cleanly with their static record.

        A static record with no live actor produces nothing. An actor whose
        metadata disagrees with its static record produces nothing and a
        `RejectedActor` diagnostic instead -- publishing an entity the
        engine would not recognise is worse than publishing none."""
        floor_id = self.current_floor_id()
        group_ids = set(self.floor_group_ids(floor_id))
        statics = self.static_characters(floor_id)
        published = {}
        rejected = []
        for actor in self.actors():
            if actor.group_id == 0:
                # The engine's reserved sentinel for the global
                # partner/follower slots -- `floorCharacterBiosFindByResID`
                # redirects those to `_globalCharacter` rather than the
                # per-floor array, so their resIDs are not room indices.
                rejected.append(RejectedActor(
                    actor.slot, actor.group_id, actor.res_id,
                    "global/follower slot (groupID 0)"))
                continue
            if actor.is_treasure:
                rejected.append(RejectedActor(
                    actor.slot, actor.group_id, actor.res_id,
                    "treasure actor (Phase 3 owns these)"))
                continue
            if actor.group_id not in group_ids:
                rejected.append(RejectedActor(
                    actor.slot, actor.group_id, actor.res_id,
                    "groupID does not belong to the current floor"))
                continue
            static = statics.get(actor.res_id)
            if static is None:
                rejected.append(RejectedActor(
                    actor.slot, actor.group_id, actor.res_id,
                    "resID outside this floor's character array"))
                continue
            # Independent cross-check of the pairing: the live actor and
            # the static record must agree on the TYPE. They are written
            # from different places, so a genuine disagreement means the
            # CORRELATION is wrong, and publishing an entity the engine
            # would not recognise is worse than publishing none.
            #
            # Defect R6, found by the shadow reader within minutes of it
            # first running (2026-08-09): this used to compare
            # `static.people_info_id` against `actor.people_info_id`
            # directly. Those are DIFFERENT NAMESPACES -- the static field
            # is an array index (81, 116, 145) and the live field is the
            # record's own id (0x15FA0400, 0x17220400, 0x1A700400) -- so it
            # could never match, and it rejected every NPC in every room.
            # That is exactly the "empties the category" failure that
            # forced the 2026-08-06 revert.
            #
            # An index that does not resolve is reported as "cannot check"
            # and does NOT reject: an unverifiable gate must never count as
            # a failed one.
            static_info = self.people_info_by_index(static.people_info_id)
            if (static_info is not None
                    and static_info.info_id != actor.people_info_id):
                rejected.append(RejectedActor(
                    actor.slot, actor.group_id, actor.res_id,
                    f"people-info mismatch: actor 0x{actor.people_info_id:08X} "
                    f"vs static index {static.people_info_id} "
                    f"-> 0x{static_info.info_id:08X}"))
                continue
            info = self.people_info(actor.people_info_id)
            if info is None:
                rejected.append(RejectedActor(
                    actor.slot, actor.group_id, actor.res_id,
                    f"people-info {actor.people_info_id} not in the table"))
                continue
            if actor.position is None:
                rejected.append(RejectedActor(
                    actor.slot, actor.group_id, actor.res_id,
                    "no readable live model position"))
                continue
            identity = actor.identity
            if identity in published:
                # One authoritative published NPC per live actor. Two
                # occupied slots claiming the same (groupID, resID) is a
                # genuine engine-level ambiguity, not something to average
                # or to publish twice.
                rejected.append(RejectedActor(
                    actor.slot, actor.group_id, actor.res_id,
                    "duplicate identity already published from another slot"))
                continue
            published[identity] = Character(
                actor=actor, static=static, info=info,
                generation=self._generation(actor),
            )
        self.rejected = tuple(rejected)
        return tuple(published.values())
