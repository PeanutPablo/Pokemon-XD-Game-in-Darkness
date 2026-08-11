"""Authoritative, read-only XD warp extraction.

Warps are common.rel interaction points keyed to room collision regions.
"""
import math
import struct
from dataclasses import dataclass, replace
from pathlib import Path

import _dialogue_extraction_tool as extraction

from .entities import Entity
from .messages import LocalDataError
from .npc_beacons import Position
from .region_geometry import parse_regions

INTERACTION_STRIDE = 0x1C
COMMON_SCRIPT_MARKER = 0x0596
WARP_SCRIPT = 0x04
DOOR_SCRIPT = 0x05
ELEVATOR_SCRIPT = 0x06
TEXT_SCRIPT = 0x0C
CUTSCENE_WARP_SCRIPT = 0x0D
PC_SCRIPT = 0x0E
MAX_INTERACTIONS = 4096
MAX_CCD_ENTRIES = 4096
MAX_CCD_TRIANGLES = 100000


def _u16(data, offset):
    if offset < 0 or offset + 2 > len(data):
        raise ValueError(f"u16 outside data at 0x{offset:X}")
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data, offset):
    if offset < 0 or offset + 4 > len(data):
        raise ValueError(f"u32 outside data at 0x{offset:X}")
    return struct.unpack_from(">I", data, offset)[0]


@dataclass(frozen=True)
class WarpRecord:
    index: int
    room_id: int
    region_index: int
    interaction_method: int
    target_room_id: int
    target_entry_id: int
    kind: str


def parse_warp_records(common_rel, interaction_offset, count):
    """Parse only structurally verified Warp and CutsceneWarp records."""
    if not 0 <= count <= MAX_INTERACTIONS:
        raise ValueError(f"invalid interaction count {count}")
    end = interaction_offset + count * INTERACTION_STRIDE
    if interaction_offset < 0 or end > len(common_rel):
        raise ValueError("interaction table outside common.rel")
    records = []
    for index in range(count):
        offset = interaction_offset + index * INTERACTION_STRIDE
        marker = _u16(common_rel, offset + 0x08)
        script = _u16(common_rel, offset + 0x0A)
        if marker != COMMON_SCRIPT_MARKER:
            continue
        if script == WARP_SCRIPT:
            kind = "warp"
        elif script == CUTSCENE_WARP_SCRIPT:
            kind = "cutscene_warp"
        else:
            continue
        records.append(WarpRecord(
            index=index,
            room_id=_u16(common_rel, offset + 0x02),
            region_index=common_rel[offset + 0x07],
            interaction_method=common_rel[offset],
            target_room_id=_u16(common_rel, offset + 0x0E),
            target_entry_id=common_rel[offset + 0x13],
            kind=kind,
        ))
    return tuple(records)


@dataclass(frozen=True)
class DoorRecord:
    index: int
    room_id: int
    region_index: int
    interaction_method: int
    door_id: int


@dataclass(frozen=True)
class ElevatorRecord:
    index: int
    room_id: int
    region_index: int
    interaction_method: int
    elevator_id: int
    target_room_id: int
    target_elevator_id: int
    direction: int


def parse_door_records(common_rel, interaction_offset, count):
    """Parse only structurally verified Door records (XGInteractionPoint
    kIPDoorValue=0x5, same table/marker/stride as warps)."""
    if not 0 <= count <= MAX_INTERACTIONS:
        raise ValueError(f"invalid interaction count {count}")
    end = interaction_offset + count * INTERACTION_STRIDE
    if interaction_offset < 0 or end > len(common_rel):
        raise ValueError("interaction table outside common.rel")
    records = []
    for index in range(count):
        offset = interaction_offset + index * INTERACTION_STRIDE
        marker = _u16(common_rel, offset + 0x08)
        script = _u16(common_rel, offset + 0x0A)
        if marker != COMMON_SCRIPT_MARKER or script != DOOR_SCRIPT:
            continue
        records.append(DoorRecord(
            index=index,
            room_id=_u16(common_rel, offset + 0x02),
            region_index=common_rel[offset + 0x07],
            interaction_method=common_rel[offset],
            door_id=_u16(common_rel, offset + 0x0E),
        ))
    return tuple(records)


def parse_elevator_records(common_rel, interaction_offset, count):
    """Parse only structurally verified Elevator records (XGInteractionPoint
    kIPElevatorValue=0x6, same table/marker/stride as warps). Field offsets
    (elevator_id@+0xE, target_room_id@+0x12, target_elevator_id@+0x16,
    direction@+0x1B) are from Pokemon-XD-Code's XGInteractionPoint.swift,
    live-verified for room 0x8A (M5_apart_1F -> M5_apart_2F, elevator_id
    144 -> target_elevator_id 145)."""
    if not 0 <= count <= MAX_INTERACTIONS:
        raise ValueError(f"invalid interaction count {count}")
    end = interaction_offset + count * INTERACTION_STRIDE
    if interaction_offset < 0 or end > len(common_rel):
        raise ValueError("interaction table outside common.rel")
    records = []
    for index in range(count):
        offset = interaction_offset + index * INTERACTION_STRIDE
        marker = _u16(common_rel, offset + 0x08)
        script = _u16(common_rel, offset + 0x0A)
        if marker != COMMON_SCRIPT_MARKER or script != ELEVATOR_SCRIPT:
            continue
        records.append(ElevatorRecord(
            index=index,
            room_id=_u16(common_rel, offset + 0x02),
            region_index=common_rel[offset + 0x07],
            interaction_method=common_rel[offset],
            elevator_id=_u16(common_rel, offset + 0x0E),
            target_room_id=_u16(common_rel, offset + 0x12),
            target_elevator_id=_u16(common_rel, offset + 0x16),
            direction=common_rel[offset + 0x1B],
        ))
    return tuple(records)


@dataclass(frozen=True)
class TextRecord:
    index: int
    room_id: int
    region_index: int
    interaction_method: int
    message_field: int


def parse_text_records(common_rel, interaction_offset, count):
    """Parse only structurally verified Text/sign records (XGInteractionPoint
    kIPTextValue=0xC, same table/marker/stride as warps). `message_field`
    (same +0xE offset as Door/Elevator/PC's own identifying field) is
    captured as a candidate message/string ID but NOT yet confirmed to
    resolve through any specific string table -- treat it as an opaque
    number until independently verified, per this project's standing
    no-hardcoding rule."""
    if not 0 <= count <= MAX_INTERACTIONS:
        raise ValueError(f"invalid interaction count {count}")
    end = interaction_offset + count * INTERACTION_STRIDE
    if interaction_offset < 0 or end > len(common_rel):
        raise ValueError("interaction table outside common.rel")
    records = []
    for index in range(count):
        offset = interaction_offset + index * INTERACTION_STRIDE
        marker = _u16(common_rel, offset + 0x08)
        script = _u16(common_rel, offset + 0x0A)
        if marker != COMMON_SCRIPT_MARKER or script != TEXT_SCRIPT:
            continue
        records.append(TextRecord(
            index=index,
            room_id=_u16(common_rel, offset + 0x02),
            region_index=common_rel[offset + 0x07],
            interaction_method=common_rel[offset],
            message_field=_u16(common_rel, offset + 0x0E),
        ))
    return tuple(records)


@dataclass(frozen=True)
class PCRecord:
    index: int
    room_id: int
    region_index: int
    interaction_method: int
    secondary_field: int


def parse_pc_records(common_rel, interaction_offset, count):
    """Parse only structurally verified PC records (XGInteractionPoint
    kIPPCValue=0xE, same table/marker/stride as warps). `Pokemon-XD-Code`
    documents this type's own parameters as "unused in XD" specifically
    (as opposed to Colosseum) -- `secondary_field` (same +0xE offset as
    Door/Elevator's own identifying field) is captured for completeness
    but not assumed to carry any real meaning; only room_id/region_index
    (used for CCD centroid position resolution) are relied on."""
    if not 0 <= count <= MAX_INTERACTIONS:
        raise ValueError(f"invalid interaction count {count}")
    end = interaction_offset + count * INTERACTION_STRIDE
    if interaction_offset < 0 or end > len(common_rel):
        raise ValueError("interaction table outside common.rel")
    records = []
    for index in range(count):
        offset = interaction_offset + index * INTERACTION_STRIDE
        marker = _u16(common_rel, offset + 0x08)
        script = _u16(common_rel, offset + 0x0A)
        if marker != COMMON_SCRIPT_MARKER or script != PC_SCRIPT:
            continue
        records.append(PCRecord(
            index=index,
            room_id=_u16(common_rel, offset + 0x02),
            region_index=common_rel[offset + 0x07],
            interaction_method=common_rel[offset],
            secondary_field=_u16(common_rel, offset + 0x0E),
        ))
    return tuple(records)


def parse_interactable_region_centers(ccd):
    """Return interaction-index to position from CCD slots +0x2C/+0x30.

    X and Z are the region centroid -- the middle of the trigger volume is
    exactly what "which way is the door" wants.

    Y is the region's FLOOR (its minimum), not its centroid. These regions
    are tall trigger boxes standing on the walkable surface: measured across
    every extracted room, the median volume is 32.6 units tall and its
    centroid sits 16.3 units above its own floor, and 162 of 162 rooms
    exceeded `entity_nav_vertical_threshold` (3.0) on that offset alone. The
    player's own Y is their feet, so using the centroid made entity-nav
    announce "above" for essentially every warp, door, elevator, PC and sign
    in the game -- 200 of 422 announcements in one live log -- while NPCs,
    whose Y comes from their model, never did.

    Taking the floor makes this Y mean the same thing the player's Y means:
    a walkable surface. A genuine floor change still clears the threshold
    easily, because storeys are separated by far more than three units."""
    list_start = _u32(ccd, 0)
    entry_count = _u32(ccd, 4)
    if (entry_count > MAX_CCD_ENTRIES or
            list_start + entry_count * 0x40 > len(ccd)):
        raise ValueError("invalid CCD top-level table")
    points = {}
    for entry_index in range(entry_count):
        entry = list_start + entry_index * 0x40
        for slot in (0x2C, 0x30):
            pointer = _u32(ccd, entry + slot)
            if pointer == 0:
                continue
            triangle_start = _u32(ccd, pointer)
            triangle_count = _u32(ccd, pointer + 4)
            if (triangle_count > MAX_CCD_TRIANGLES or
                    triangle_start + triangle_count * 0x34 > len(ccd)):
                raise ValueError("invalid CCD interactable triangle list")
            index_offset = 0x32 if slot == 0x2C else 0x30
            for triangle_index in range(triangle_count):
                offset = triangle_start + triangle_index * 0x34
                values = struct.unpack_from(">9f", ccd, offset)
                if not all(math.isfinite(value) for value in values):
                    raise ValueError("non-finite CCD interactable vertex")
                interaction_index = _u16(ccd, offset + index_offset)
                points.setdefault(interaction_index, []).extend(
                    (values[base], values[base + 1], values[base + 2])
                    for base in (0, 3, 6)
                )
    return {
        index: (
            sum(point[0] for point in vertices) / len(vertices),
            min(point[1] for point in vertices),
            sum(point[2] for point in vertices) / len(vertices),
        )
        for index, vertices in points.items() if vertices
    }


def load_warp_records(common_fsys_path):
    """Load the verified interaction table from the user's extracted data."""
    path = Path(common_fsys_path)
    try:
        files = extraction.parse_fsys(path.read_bytes())
        data = next(item["data"] for item in files if item["name"] in {"common.rel", "common_rel"})
        rel = extraction.RelFile(data)
        return parse_warp_records(data, rel.get_pointer(62), _u32(data, rel.get_pointer(63)))
    except Exception as exc:
        raise LocalDataError(f"Could not load authoritative warp records: {exc}") from exc


def load_door_records(common_fsys_path):
    """Load the verified Door interaction records from the user's extracted data."""
    path = Path(common_fsys_path)
    try:
        files = extraction.parse_fsys(path.read_bytes())
        data = next(item["data"] for item in files if item["name"] in {"common.rel", "common_rel"})
        rel = extraction.RelFile(data)
        return parse_door_records(data, rel.get_pointer(62), _u32(data, rel.get_pointer(63)))
    except Exception as exc:
        raise LocalDataError(f"Could not load authoritative door records: {exc}") from exc


def load_elevator_records(common_fsys_path):
    """Load the verified Elevator interaction records from the user's extracted data."""
    path = Path(common_fsys_path)
    try:
        files = extraction.parse_fsys(path.read_bytes())
        data = next(item["data"] for item in files if item["name"] in {"common.rel", "common_rel"})
        rel = extraction.RelFile(data)
        return parse_elevator_records(data, rel.get_pointer(62), _u32(data, rel.get_pointer(63)))
    except Exception as exc:
        raise LocalDataError(f"Could not load authoritative elevator records: {exc}") from exc


def load_text_records(common_fsys_path):
    """Load the verified Text/sign interaction records from the user's extracted data."""
    path = Path(common_fsys_path)
    try:
        files = extraction.parse_fsys(path.read_bytes())
        data = next(item["data"] for item in files if item["name"] in {"common.rel", "common_rel"})
        rel = extraction.RelFile(data)
        return parse_text_records(data, rel.get_pointer(62), _u32(data, rel.get_pointer(63)))
    except Exception as exc:
        raise LocalDataError(f"Could not load authoritative text records: {exc}") from exc


def load_pc_records(common_fsys_path):
    """Load the verified PC interaction records from the user's extracted data."""
    path = Path(common_fsys_path)
    try:
        files = extraction.parse_fsys(path.read_bytes())
        data = next(item["data"] for item in files if item["name"] in {"common.rel", "common_rel"})
        rel = extraction.RelFile(data)
        return parse_pc_records(data, rel.get_pointer(62), _u32(data, rel.get_pointer(63)))
    except Exception as exc:
        raise LocalDataError(f"Could not load authoritative PC records: {exc}") from exc


def onward_destinations(records):
    """`{room: the single OTHER room it leads to}` from the warp graph.

    A pass-through room -- a cave corridor, a stairwell -- has exactly two
    kinds of exit: back the way you came, and onward. This finds the
    onward one, using nothing but the warp table.

    Agate is the case that motivated it. `M3_cave_1F_1` and
    `M3_cave_1F_2` both render as "Agate Village cave, 1st floor", so the
    duplicate disambiguator called them "A" and "B" -- letters assigned in
    table order, carrying no information. One of them is the passage to
    the Relic Stone and the other is a dead end, and a blind player had no
    way to tell which. Now they are told."""
    targets = {}
    for record in records:
        targets.setdefault(record.room_id, set()).add(record.target_room_id)
    onward = {}
    for room, reachable in targets.items():
        for source in reachable:
            others = reachable - {source}
            if len(others) == 1:
                onward.setdefault(room, {})[source] = next(iter(others))
    return onward


def _disambiguate_labels(entities, onward=None, room_names=None,
                         source_room=None):
    """Give duplicate labels a MEANINGFUL distinction where the warp graph
    provides one, and fall back to letters where it does not.

    A letter is the last resort, not the first: "cave, toward Relic Stone"
    is a thing a player can act on, "cave A" is not."""
    totals = {}
    for entity in entities:
        if entity.label:
            totals[entity.label] = totals.get(entity.label, 0) + 1
    result = []
    remaining = []
    for entity in entities:
        label = entity.label
        if not label or totals.get(label, 0) <= 1:
            result.append(entity)
            continue
        target = (entity.metadata or {}).get("target_room_id")
        next_room = (onward or {}).get(target, {}).get(source_room)
        name = (room_names or {}).get(next_room)
        # Another floor of the same building is not a destination worth
        # naming: "house in Agate Village, toward house in Agate Village,
        # 2nd floor" is longer than the label it disambiguates and says
        # nothing. Compare the part before the floor suffix.
        # Warp labels are prepositional ("to house in Agate Village"), so
        # the prefix has to come off before the buildings can be compared.
        same_building = bool(name) and (
            name.split(",")[0].strip()
            == label.split(",")[0].strip().removeprefix("to ").strip())
        if name and not same_building:
            result.append(replace(entity, label=f"{label}, toward {name}"))
        else:
            remaining.append(entity)
    # Anything the graph could not distinguish keeps the old lettering,
    # numbered among ITS OWN duplicates so the letters stay dense.
    return _lettered_duplicate_labels(remaining) + result if remaining else result


def _lettered_duplicate_labels(entities):
    totals = {}
    for entity in entities:
        if entity.label:
            totals[entity.label] = totals.get(entity.label, 0) + 1
    seen = {}
    result = []
    for entity in entities:
        label = entity.label
        if label and totals.get(label, 0) > 1:
            index = seen.get(label, 0)
            seen[label] = index + 1
            label = f"{label} {chr(ord("A") + index) if index < 26 else str(index + 1)}"
            entity = Entity(
                category=entity.category,
                identity=entity.identity,
                label=label,
                position=entity.position,
                interaction_distance=entity.interaction_distance,
                subtype=entity.subtype,
                metadata=entity.metadata,
            )
        result.append(entity)
    return result



def _region_position(regions, region_index, pose):
    """Nearest point of the interaction region to the player.

    Phase 3b (2026-08-10). These sources announced a region's CENTROID,
    which the Phase 1 audit measured across all 843 regions in 177 rooms:
    842 are large enough that a player standing legitimately inside can be
    more than a full interaction radius from the announced point, and 210
    have a centroid lying OUTSIDE their own region -- worst case 168.9
    units of empty space.

    The project owner hit the consequence directly: Agate's cave entrances
    announced at 184-287 units with an "above"/"below" qualifier, and no
    way to walk to one. The engine treats these as areas you enter
    anywhere, so the useful target is the nearest point of the area, not
    its middle.

    Y still comes from the region's floor, for the reason
    `region_geometry` records: the player's Y is their feet, and these are
    tall trigger volumes."""
    region = regions.get(region_index)
    if region is None:
        return None
    point = region.nearest_point(pose.position.x, pose.position.z)
    if point is None:
        return None
    return Position(point[0], region.anchor[1], point[1])


class AuthoritativeWarpEntitySource:
    """Room-scoped warp entities built only from common.rel and CCD data."""

    def __init__(self, memory, profile, pose_source, records, collision_dir, room_codes, room_names=None):
        self.memory, self.profile, self.pose_source = memory, profile, pose_source
        self.records, self.collision_dir = tuple(records), Path(collision_dir)
        self.room_codes, self.room_names, self._centers = dict(room_codes), dict(room_names or {}), {}
        self.onward = onward_destinations(self.records)

    def player_pose(self):
        return self.pose_source.player_pose()

    def _room_centers(self, room_id):
        if room_id in self._centers:
            return self._centers[room_id]
        code = self.room_codes.get(room_id)
        path = self.collision_dir / f"{code}.ccd" if code else None
        if path is None or not path.is_file():
            centers = {}
        else:
            try:
                centers = parse_regions(path.read_bytes())
            except (OSError, ValueError) as exc:
                raise LocalDataError(f"Could not load collision data for room 0x{room_id:X}: {exc}") from exc
        self._centers[room_id] = centers
        return centers

    def entities(self):
        room_id = self.memory.u16(self.profile.current_floor_id, "authoritative warp room id")
        centers, result = self._room_centers(room_id), []
        pose = self.player_pose()
        for record in self.records:
            if record.room_id != room_id or record.region_index not in centers:
                continue
            position = _region_position(centers, record.region_index, pose)
            if position is None:
                continue
            target = self.room_names.get(record.target_room_id, self.room_codes.get(record.target_room_id))
            result.append(Entity(category="warp", identity=("warp", record.index), label=f"to {target}" if target else None, position=position, subtype=record.kind, metadata={"target_room_id": record.target_room_id, "target_entry_id": record.target_entry_id, "interaction_method": record.interaction_method}))
        return _disambiguate_labels(
            result, self.onward, self.room_names, room_id)


class _RoomScopedInteractionSource:
    """Shared room-centroid lookup for Door/Elevator entity sources --
    identical mechanism to AuthoritativeWarpEntitySource (same interaction
    table, same CCD centroid resolution), factored out here since both new
    sources need it and this file's original warp class predates the need
    for a shared base."""

    def __init__(self, memory, profile, pose_source, records, collision_dir, room_codes, room_names=None):
        self.memory, self.profile, self.pose_source = memory, profile, pose_source
        self.records, self.collision_dir = tuple(records), Path(collision_dir)
        self.room_codes, self.room_names, self._centers = dict(room_codes), dict(room_names or {}), {}

    def player_pose(self):
        return self.pose_source.player_pose()

    def _room_centers(self, room_id):
        if room_id in self._centers:
            return self._centers[room_id]
        code = self.room_codes.get(room_id)
        path = self.collision_dir / f"{code}.ccd" if code else None
        if path is None or not path.is_file():
            centers = {}
        else:
            try:
                centers = parse_regions(path.read_bytes())
            except (OSError, ValueError) as exc:
                raise LocalDataError(f"Could not load collision data for room 0x{room_id:X}: {exc}") from exc
        self._centers[room_id] = centers
        return centers

    def _current_room_id(self, label):
        return self.memory.u16(self.profile.current_floor_id, label)


class AuthoritativeElevatorEntitySource(_RoomScopedInteractionSource):
    """Room-scoped elevator entities built only from common.rel and CCD
    data -- replaces the earlier hand-scanned ELEVATORS lookup in
    npc_beacons.py with CCD-resolved centroid positions per the same
    validated interaction table warps already use."""

    def entities(self):
        room_id = self._current_room_id("authoritative elevator room id")
        centers, result = self._room_centers(room_id), []
        pose = self.player_pose()
        for record in self.records:
            if record.room_id != room_id or record.region_index not in centers:
                continue
            position = _region_position(centers, record.region_index, pose)
            if position is None:
                continue
            target = self.room_names.get(record.target_room_id, self.room_codes.get(record.target_room_id))
            direction = "up" if record.direction == 0 else "down"
            label = f"Elevator to {target}" if target else "Elevator"
            result.append(Entity(
                category="elevator",
                identity=("elevator", record.index),
                label=label,
                position=position,
                metadata={
                    "elevator_id": record.elevator_id,
                    "target_room_id": record.target_room_id,
                    "target_elevator_id": record.target_elevator_id,
                    "direction": direction,
                },
            ))
        return result


class AuthoritativeDoorEntitySource(_RoomScopedInteractionSource):
    """Room-scoped door entities built only from common.rel and CCD data.

    A door whose collision region ALSO carries a Warp record is published
    with `metadata["beacon"] = False`, so it stays a known entity but makes
    no sound of its own (see `entity_sources.WarpAugmentedNPCSource` for
    that contract -- beacon eligibility is not navigation eligibility).

    Requested by the project owner 2026-08-10: standing at a building
    entrance played the door beacon and the warp beacon simultaneously
    from the identical point, because in this game's data such an entrance
    IS both -- the Door record animates the doorway, the Warp record moves
    you. Measured over the real table, 72 of 150 doors share a region with
    a warp, so this was not a rare edge case. The warp is the one that
    keeps sounding: it is what the player is actually navigating to, and it
    names its destination. The 78 doors that are not attached to a warp
    (interior doors, scenery) are untouched and still beacon."""

    def __init__(self, memory, profile, pose_source, records, collision_dir,
                 room_codes, room_names=None, warp_records=()):
        super().__init__(memory, profile, pose_source, records, collision_dir,
                         room_codes, room_names)
        self.warp_regions = frozenset(
            (record.room_id, record.region_index) for record in warp_records)
        """Region keys occupied by a warp. Empty when no warp records are
        supplied, which leaves every door beaconing -- the behaviour before
        this filter existed, and the right default for a caller that has no
        warp table to compare against."""

    def entities(self):
        room_id = self._current_room_id("authoritative door room id")
        centers, result = self._room_centers(room_id), []
        pose = self.player_pose()
        for record in self.records:
            if record.room_id != room_id or record.region_index not in centers:
                continue
            position = _region_position(centers, record.region_index, pose)
            if position is None:
                continue
            warp_attached = (
                record.room_id, record.region_index) in self.warp_regions
            metadata = {
                "door_id": record.door_id,
                "warp_attached": warp_attached,
            }
            if warp_attached:
                metadata["beacon"] = False
            result.append(Entity(
                category="door",
                identity=("door", record.index),
                label="Door",
                position=position,
                metadata=metadata,
            ))
        return result


class AuthoritativeTextEntitySource(_RoomScopedInteractionSource):
    """Room-scoped sign/plaque entities built only from common.rel and CCD
    data. Announces generically as "Sign" -- the record's own
    `message_field` is not yet confirmed to resolve to real text through
    any specific string table, so no attempt is made to speak sign
    contents until that's verified."""

    def entities(self):
        room_id = self._current_room_id("authoritative text room id")
        centers, result = self._room_centers(room_id), []
        pose = self.player_pose()
        for record in self.records:
            if record.room_id != room_id or record.region_index not in centers:
                continue
            position = _region_position(centers, record.region_index, pose)
            if position is None:
                continue
            result.append(Entity(
                category="sign",
                identity=("sign", record.index),
                label="Sign",
                position=position,
                metadata={"message_field": record.message_field},
            ))
        return result


class AuthoritativePCEntitySource(_RoomScopedInteractionSource):
    """Room-scoped PC entities built only from common.rel and CCD data.
    Reliability is a genuine open question for this specific type --
    `Pokemon-XD-Code` documents its parameters as "unused in XD" -- so
    this is deliberately labeled generically ("PC") rather than assuming
    the position/behavior matches Colosseum's PC objects exactly; needs
    live spot-checking against a known, real PC location."""

    def entities(self):
        room_id = self._current_room_id("authoritative pc room id")
        centers, result = self._room_centers(room_id), []
        pose = self.player_pose()
        for record in self.records:
            if record.room_id != room_id or record.region_index not in centers:
                continue
            position = _region_position(centers, record.region_index, pose)
            if position is None:
                continue
            result.append(Entity(
                category="pc",
                identity=("pc", record.index),
                label="PC",
                position=position,
                metadata={"secondary_field": record.secondary_field},
            ))
        return result