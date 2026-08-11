import io
import logging
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from battle_narrator.dolphin import DolphinConnection, UnsupportedGameError
from battle_narrator.events import EventTracker
from battle_narrator.memory import MemoryError, MemoryReader, PointerError, valid_range
from battle_narrator.narrator import BattleNarrator
from battle_narrator.profile import XD_US_REV0
from battle_narrator.tasks import GSmsgTaskArray, TaskArrayError, TaskSnapshot, split_packed_id


class ByteBackend:
    def __init__(self):
        self.data = {}
        self.hooked = True

    def put(self, address, value):
        for index, byte in enumerate(value):
            self.data[address + index] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + index, 0) for index in range(size))

    def hook(self):
        self.hooked = True

    def is_hooked(self):
        return self.hooked

    def get_status(self):
        return "synthetic"

    def un_hook(self):
        self.hooked = False


def be16(value):
    return value.to_bytes(2, "big")


def be32(value):
    return value.to_bytes(4, "big")


def gschar(text):
    return b"".join(be16(ord(char)) for char in text) + b"\0\0"


class SequenceTasks:
    profile = XD_US_REV0

    def __init__(self, sequence):
        self.sequence = iter(sequence)

    def snapshots(self):
        return next(self.sequence)


class FakeConnection:
    def __init__(self, readable=True):
        self.readable = readable

    def is_readable(self):
        return self.readable


class FakeSpeaker:
    def __init__(self):
        self.spoken = []

    def speak(self, text, interrupt=False):
        self.spoken.append((text, interrupt))
        return True


class FakeCatalog:
    def __init__(self, messages):
        self.messages = {message.message_id: message for message in messages}

    def get(self, message_id):
        return self.messages.get(message_id)


def logger():
    value = logging.getLogger(f"test-{id(object())}")
    value.handlers.clear()
    value.addHandler(logging.StreamHandler(io.StringIO()))
    value.setLevel(logging.DEBUG)
    return value


class MemoryTests(unittest.TestCase):
    def test_packed_message_id(self):
        self.assertEqual(split_packed_id((3 << 20) | 20333), (3, 20333))

    def test_gschar_decodes_odd_address_and_unicode(self):
        backend = ByteBackend()
        address = 0x80001001
        backend.put(address, gschar("Pokémon"))
        memory = MemoryReader(backend, XD_US_REV0)
        self.assertEqual(memory.gschar(address, 7, "odd text"), "Pokémon")

    def test_unicode_utf8_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unicode.log"
            path.write_text("Pokémon", encoding="utf-8")
            self.assertEqual(path.read_bytes(), b"Pok\xc3\xa9mon")

    def test_invalid_pointer_and_complete_range(self):
        self.assertFalse(valid_range(0, 1))
        self.assertFalse(valid_range(0x817FFFFF, 4))
        with self.assertRaises(PointerError):
            MemoryReader(ByteBackend(), XD_US_REV0).gschar(
                0x817FFFFF, 1, "overflow"
            )

    def test_profile_rejects_a_build_whose_engine_does_not_match(self):
        # Correct disc label, no matching engine code -> refused. The label
        # alone is not evidence of compatibility; a hack can set any label,
        # and only the code layout decides whether our addresses are valid.
        backend = ByteBackend()
        backend.put(0x80000000, b"GXXE01\0\0")
        with self.assertRaises(UnsupportedGameError):
            DolphinConnection(backend, XD_US_REV0).attach()

    def test_profile_accepts_a_relabelled_build_with_a_matching_engine(self):
        backend = ByteBackend()
        backend.put(0x80000000, b"GXGE01\0\2")
        for _name, address, expected in XD_US_REV0.engine_signatures:
            backend.put(address, expected)
        connection = DolphinConnection(backend, XD_US_REV0)
        connection.attach()
        self.assertEqual(connection.verify_profile(), ("GXGE01", 2))


class TaskArrayTests(unittest.TestCase):
    def make_array(self, capacity=2, state=0):
        backend = ByteBackend()
        manager = 0x80002000
        tasks = 0x80003000
        backend.put(XD_US_REV0.manager_root, be32(manager))
        backend.put(manager, be16(capacity))
        backend.put(manager + XD_US_REV0.manager_tasks_offset, be32(tasks))
        backend.put(tasks, bytes([state]))
        return backend, GSmsgTaskArray(MemoryReader(backend, XD_US_REV0), XD_US_REV0)

    def test_states_zero_one_two_are_valid(self):
        for state in (0, 1, 2):
            _, tasks = self.make_array(state=state)
            self.assertEqual(tasks.snapshots()[0].state, state)

    def test_invalid_state_is_rejected(self):
        _, tasks = self.make_array(state=3)
        with self.assertRaises(TaskArrayError):
            tasks.snapshots()

    def test_invalid_capacity_is_rejected_before_iteration(self):
        _, tasks = self.make_array(capacity=99)
        with self.assertRaises(TaskArrayError):
            tasks.resolve()


class EventTests(unittest.TestCase):
    def snapshot(self, state, packed=None):
        return [TaskSnapshot(0, 0x80003000, state, packed)]

    def test_state_transition_does_not_repeat(self):
        tracker = EventTracker(1)
        packed = 20333
        self.assertEqual([e.kind for e in tracker.update(self.snapshot(1, packed))], ["open"])
        self.assertEqual(tracker.update(self.snapshot(2, packed)), [])

    def test_rearming_and_same_id_reuse(self):
        tracker = EventTracker(1)
        packed = 20333
        self.assertEqual([e.kind for e in tracker.update(self.snapshot(1, packed))], ["open"])
        self.assertEqual([e.kind for e in tracker.update(self.snapshot(0))], ["close"])
        self.assertEqual([e.kind for e in tracker.update(self.snapshot(2, packed))], ["open"])

    def test_id_change_while_allocated(self):
        tracker = EventTracker(1)
        tracker.update(self.snapshot(1, 20333))
        events = tracker.update(self.snapshot(1, 20256))
        self.assertEqual(events[0].kind, "id_change")
