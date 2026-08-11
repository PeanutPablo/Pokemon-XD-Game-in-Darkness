"""Proximity sound cues for every visible overworld NPC."""
from dataclasses import dataclass
import math
from pathlib import Path
import time
import wave

from .memory import MemoryError, require_range


@dataclass(frozen=True)
class Position:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class NPC:
    floor_id: int
    index: int
    visible: bool
    talk_id: int
    position: Position

    @property
    def identity(self):
        return self.floor_id, self.index


class NPCMemorySource:
    """Read the game's generic floor-character table and leader model."""

    def __init__(self, memory, profile):
        self.memory, self.profile = memory, profile

    def _position(self, address, label):
        values = self.memory.bytes(address, 12, label, 4)
        import struct
        position = Position(*struct.unpack(">fff", values))
        if not all(math.isfinite(value) for value in position.__dict__.values()):
            raise MemoryError(f"{label} contains a non-finite coordinate")
        return position

    def player_position(self):
        p = self.profile
        leader = self.memory.u32(p.hero_leader, "hero leader")
        if leader >= len(p.hero_model_resource_ids):
            raise MemoryError(f"invalid hero leader {leader}")
        resource_id = p.hero_model_resource_ids[leader]
        node = self.memory.pointer(
            p.resource_list_head, p.resource_node_size, "resource-list head", 4)
        seen = set()
        for _ in range(p.resource_max_nodes):
            if node in seen:
                raise MemoryError("resource-list cycle")
            seen.add(node)
            group_id = self.memory.u32(
                node + p.resource_group_offset, "resource group")
            candidate_id = self.memory.u32(
                node + p.resource_id_offset, "resource ID")
            state = self.memory.u8(node + p.resource_state_offset, "resource state")
            if group_id == 0 and candidate_id == resource_id and state == 0:
                model = self.memory.pointer(
                    node + p.resource_data_offset,
                    p.model_position_offset + 12,
                    "hero model",
                    4,
                )
                return self._position(
                    model + p.model_position_offset, "hero position")
            next_node = self.memory.u32(
                node + p.resource_next_offset, "next resource")
            if next_node == 0:
                break
            require_range(
                next_node,
                p.resource_node_size,
                "next resource",
                self.memory.profile,
                4,
            )
            node = next_node
        raise MemoryError(f"hero model resource {resource_id} not found")

    def npcs(self):
        p = self.profile
        floor_id = self.memory.u16(p.current_floor_id, "current floor ID")
        count_root = self.memory.pointer(
            p.floor_data_count_root, 4, "floor-data count root", 4)
        count = self.memory.u32(count_root, "floor-data count")
        if count > p.floor_data_max_records:
            raise MemoryError(f"invalid floor-data count {count}")
        table = self.memory.pointer(
            p.floor_data_root,
            max(1, count) * p.floor_data_stride,
            "floor-data table",
            4,
        )
        floor = None
        for index in range(count):
            candidate = table + index * p.floor_data_stride
            if self.memory.u16(
                    candidate + p.floor_id_offset, "floor record ID") == floor_id:
                floor = candidate
                break
        if floor is None:
            raise MemoryError(f"floor record {floor_id} not found")
        slot = self.memory.pointer(
            floor + p.floor_character_slot_offset, 4,
            "floor character slot", 4)
        header = self.memory.pointer(slot, 8, "floor character header", 4)
        count_pointer = self.memory.pointer(
            header, 4, "floor character count pointer", 4)
        npc_count = self.memory.u32(count_pointer, "floor character count")
        if npc_count > p.floor_character_max_records:
            raise MemoryError(f"invalid floor character count {npc_count}")
        base = self.memory.pointer(
            header + 4,
            max(1, npc_count) * p.floor_character_stride,
            "floor character records",
            4,
        )
        result = []
        for index in range(npc_count):
            record = base + index * p.floor_character_stride
            flags = self.memory.u8(record, "NPC flags")
            result.append(NPC(
                floor_id,
                index,
                bool(flags & p.floor_character_visible_mask),
                self.memory.u32(
                    record + p.floor_character_talk_offset, "NPC talk ID"),
                self._position(
                    record + p.floor_character_position_offset, "NPC position"),
            ))
        return result


class WindowsWavePlayer:
    def __init__(self, winsound_module=None):
        if winsound_module is None:
            import winsound as winsound_module
        self.winsound = winsound_module

    def play(self, path):
        flags = (
            self.winsound.SND_FILENAME
            | self.winsound.SND_ASYNC
            | self.winsound.SND_NODEFAULT
        )
        self.winsound.PlaySound(str(path), flags)


def wave_duration(path):
    with wave.open(str(path), "rb") as source:
        return source.getnframes() / source.getframerate()


class NPCSoundReader:
    def __init__(
        self,
        source,
        sound_paths,
        player,
        logger,
        radius=22.0,
        clock=time.monotonic,
    ):
        paths = tuple(Path(path) for path in sound_paths)
        if not paths:
            raise ValueError("at least one NPC sound is required")
        self.source = source
        self.paths = paths
        self.durations = tuple(wave_duration(path) for path in paths)
        self.player = player
        self.logger = logger
        self.radius = radius
        self.clock = clock
        self.inside = set()
        self.pending = []
        self.busy_until = 0.0

    def sound_index(self, npc):
        return (npc.floor_id * 31 + npc.index) % len(self.paths)

    @staticmethod
    def distance(left, right):
        return math.hypot(left.x - right.x, left.z - right.z)

    def clear(self, reason):
        self.inside.clear()
        self.pending.clear()
        self.busy_until = 0.0
        self.logger.debug("NPC sounds cleared: %s", reason)

    def poll_once(self):
        player_position = self.source.player_position()
        nearby = []
        for npc in self.source.npcs():
            if not npc.visible or not npc.talk_id:
                continue
            distance = self.distance(player_position, npc.position)
            if distance <= self.radius:
                nearby.append((distance, npc))
        current = {npc.identity for _, npc in nearby}
        queued = {npc.identity for _, npc in self.pending}
        for distance, npc in sorted(nearby, key=lambda item: item[0]):
            if npc.identity not in self.inside and npc.identity not in queued:
                self.pending.append((distance, npc))
        self.inside = current
        self.pending = [
            item for item in self.pending if item[1].identity in current]
        now = self.clock()
        if self.pending and now >= self.busy_until:
            distance, npc = self.pending.pop(0)
            index = self.sound_index(npc)
            self.player.play(self.paths[index])
            self.busy_until = now + self.durations[index]
            self.logger.info(
                "NPC SOUND floor=%d npc=%d distance=%.2f sound=%s",
                npc.floor_id, npc.index, distance, self.paths[index].name,
            )



