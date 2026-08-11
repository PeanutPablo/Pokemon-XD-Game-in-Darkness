from dataclasses import dataclass

from .memory import MemoryError, require_range


def split_packed_id(packed):
    return packed >> 20, packed & 0x000FFFFF


@dataclass(frozen=True)
class TaskSnapshot:
    index: int
    address: int
    state: int
    packed_id: int | None


class TaskArrayError(MemoryError):
    pass


class GSmsgTaskArray:
    def __init__(self, memory, profile):
        self.memory = memory
        self.profile = profile
        self.structure = None

    def resolve(self):
        p = self.profile
        manager = self.memory.pointer(
            p.manager_root, p.manager_tasks_offset + 4, "GSmsg manager", 4
        )
        capacity = self.memory.u16(
            manager + p.manager_capacity_offset, "GSmsg capacity"
        )
        if capacity != p.task_capacity:
            raise TaskArrayError(
                f"GSmsg capacity {capacity} is unsupported; expected {p.task_capacity}"
            )
        total = capacity * p.task_stride
        tasks = self.memory.pointer(
            manager + p.manager_tasks_offset, total, "GSmsg task array", 4
        )
        again = (
            self.memory.u32(p.manager_root, "GSmsg manager pointer"),
            self.memory.u16(manager, "GSmsg capacity"),
            self.memory.u32(
                manager + p.manager_tasks_offset, "GSmsg task array pointer"
            ),
        )
        if again != (manager, capacity, tasks):
            raise TaskArrayError("GSmsg structure changed while resolving")
        structure = manager, capacity, tasks
        if self.structure is not None and structure != self.structure:
            raise TaskArrayError("GSmsg structure changed during polling")
        self.structure = structure
        return structure

    def snapshots(self):
        _, capacity, tasks = self.resolve()
        p = self.profile
        result = []
        for index in range(capacity):
            address = tasks + index * p.task_stride
            require_range(address, p.task_stride, "GSmsg task", p, 4)
            state = self.memory.u8(address + p.task_state_offset, "task state")
            if state not in (0, 1, 2):
                raise TaskArrayError(
                    f"GSmsg task {index} has unsupported state {state}"
                )
            packed = (
                self.memory.u32(address + p.task_id_offset, "packed message ID")
                if state in (1, 2)
                else None
            )
            result.append(TaskSnapshot(index, address, state, packed))
        return result
