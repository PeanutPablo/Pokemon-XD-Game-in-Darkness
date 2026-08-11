from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskEvent:
    kind: str
    snapshot: object
    previous_packed: int | None = None


@dataclass
class Slot:
    state: int = 0
    packed: int | None = None


class EventTracker:
    def __init__(self, capacity):
        self.slots = [Slot() for _ in range(capacity)]

    def update(self, snapshots):
        events = []
        for snapshot in snapshots:
            slot = self.slots[snapshot.index]
            allocated = snapshot.state in (1, 2)
            if allocated and slot.state == 0:
                events.append(TaskEvent("open", snapshot))
            elif allocated and slot.state in (1, 2) and snapshot.packed_id != slot.packed:
                events.append(TaskEvent("id_change", snapshot, slot.packed))
            elif snapshot.state == 0 and slot.state in (1, 2):
                events.append(TaskEvent("close", snapshot, slot.packed))
            slot.state = snapshot.state
            slot.packed = snapshot.packed_id if allocated else None
        return events


@dataclass
class StabilityGate:
    pending: object = None
    seen: set = field(default_factory=set)

    def observe(self, sample):
        if sample != self.pending:
            self.pending = sample
            return None
        if sample in self.seen:
            return None
        self.seen.add(sample)
        return sample

    def reset(self):
        self.pending = None
        self.seen.clear()
