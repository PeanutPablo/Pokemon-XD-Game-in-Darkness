from .memory import MemoryError, PointerError, require_range
from .tasks import TaskSnapshot


class GSmsgUnavailable(MemoryError):
    """A verified game is readable, but GSmsg is not initialized."""


class MalformedGSmsg(MemoryError):
    """A nonzero GSmsg value violates the verified GXXE01 layout."""


class PersistentGSmsgTasks:
    def __init__(self, memory, profile):
        self.memory = memory
        self.profile = profile
        self.structure = None

    def _checked(self, address, size, label, alignment=4):
        try:
            return require_range(
                address, size, label, self.profile, alignment
            )
        except PointerError as exc:
            raise MalformedGSmsg(str(exc)) from exc

    def resolve(self):
        p = self.profile
        manager = self.memory.u32(p.manager_root, "GSmsg manager pointer")
        if manager == 0:
            raise GSmsgUnavailable("GSmsg manager is null")
        self._checked(
            manager, p.manager_tasks_offset + 4, "GSmsg manager", 4
        )

        capacity = self.memory.u16(manager, "GSmsg capacity")
        if capacity == 0:
            raise GSmsgUnavailable("GSmsg capacity is zero")
        if capacity != p.task_capacity:
            raise MalformedGSmsg(
                f"GSmsg capacity {capacity} is invalid; "
                f"expected {p.task_capacity}"
            )

        task_array = self.memory.u32(
            manager + p.manager_tasks_offset,
            "GSmsg task array pointer",
        )
        if task_array == 0:
            raise GSmsgUnavailable("GSmsg task array is null")
        self._checked(
            task_array,
            capacity * p.task_stride,
            "GSmsg task array",
            4,
        )

        again = (
            self.memory.u32(p.manager_root, "GSmsg manager pointer"),
            self.memory.u16(manager, "GSmsg capacity"),
            self.memory.u32(
                manager + p.manager_tasks_offset,
                "GSmsg task array pointer",
            ),
        )
        structure = manager, capacity, task_array
        if again != structure:
            raise MalformedGSmsg("GSmsg structure changed while resolving")
        if self.structure is not None and self.structure != structure:
            raise MalformedGSmsg(
                "GSmsg structure changed without an unavailable transition"
            )
        self.structure = structure
        return structure

    def snapshots(self):
        _, capacity, task_array = self.resolve()
        p = self.profile
        snapshots = []
        for index in range(capacity):
            address = task_array + index * p.task_stride
            self._checked(address, p.task_stride, "GSmsg task", 4)
            state = self.memory.u8(
                address + p.task_state_offset, "GSmsg task state"
            )
            if state not in (0, 1, 2):
                raise MalformedGSmsg(
                    f"GSmsg task {index} has invalid state {state}"
                )
            packed = (
                self.memory.u32(
                    address + p.task_id_offset, "packed message ID"
                )
                if state in (1, 2)
                else None
            )
            snapshots.append(
                TaskSnapshot(index, address, state, packed)
            )
        return snapshots
