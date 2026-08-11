import unittest
from dataclasses import dataclass

from battle_narrator.memory import MemoryError as GameMemoryError, MemoryReader


@dataclass(frozen=True)
class FakeProfile:
    mem1_start: int = 0x80000000
    mem1_end: int = 0x81800000


class FakeBackend:
    def __init__(self):
        self.writes = []

    def write_bytes(self, address, data):
        self.writes.append((address, data))

    def read_bytes(self, address, size):
        return b"\0" * size


class RaisingBackend:
    def read_bytes(self, address, size):
        raise RuntimeError("Could not read memory at 12345")


class MemoryReadFailureTests(unittest.TestCase):
    """dolphin_memory_engine can raise a raw RuntimeError (not this
    project's own MemoryError) on a transient read failure even while
    Dolphin is still running -- every poll loop already handles
    MemoryError gracefully, so a raw RuntimeError escaping crashes the
    whole narrator process instead of just skipping that tick."""

    def test_backend_runtime_error_becomes_memory_error(self):
        memory = MemoryReader(RaisingBackend(), FakeProfile())
        with self.assertRaises(GameMemoryError):
            memory.bytes(0x80500000, 4, "test read")


class MemoryWriteTests(unittest.TestCase):
    """write_bytes is the only write path in this project (teleport.py's
    sole use); everything else stays read-only. Covers just the
    range-validation + backend-delegation contract."""

    def test_writes_valid_range_to_backend(self):
        backend = FakeBackend()
        memory = MemoryReader(backend, FakeProfile())
        memory.write_bytes(0x80500000, b"\x00\x00\x00\x00", "test write", 4)
        self.assertEqual(backend.writes, [(0x80500000, b"\x00\x00\x00\x00")])

    def test_rejects_out_of_range_address(self):
        backend = FakeBackend()
        memory = MemoryReader(backend, FakeProfile())
        with self.assertRaises(GameMemoryError):
            memory.write_bytes(0x70000000, b"\x00\x00\x00\x00", "test write", 4)
        self.assertEqual(backend.writes, [])

    def test_rejects_misaligned_address(self):
        backend = FakeBackend()
        memory = MemoryReader(backend, FakeProfile())
        with self.assertRaises(GameMemoryError):
            memory.write_bytes(0x80500001, b"\x00\x00\x00\x00", "test write", 4)
        self.assertEqual(backend.writes, [])


if __name__ == "__main__":
    unittest.main()
