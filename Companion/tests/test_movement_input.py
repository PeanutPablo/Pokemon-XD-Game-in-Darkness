import unittest

from battle_narrator.memory import MemoryError as MemErr
from battle_narrator.movement_input import (
    CONTROLLER_STRIDE,
    CONTROLLER_TABLE_BASE,
    GSinputMovementSource,
    NeverHeldMovementSource,
    STICK_X_OFFSET,
    STICK_Y_OFFSET,
)


class FakeMemory:
    def __init__(self):
        self.values = {}

    def set_stick(self, x, y):
        base = CONTROLLER_TABLE_BASE
        self.values[base + STICK_X_OFFSET] = x & 0xFF
        self.values[base + STICK_Y_OFFSET] = y & 0xFF

    def u8(self, address, label):
        if address not in self.values:
            raise MemErr(f"unmapped {address:#x}")
        return self.values[address]


class GSinputMovementSourceTests(unittest.TestCase):
    def test_neutral_stick_is_not_held(self):
        memory = FakeMemory()
        memory.set_stick(0, 0)
        source = GSinputMovementSource(memory)
        self.assertFalse(source.is_direction_held())

    def test_small_jitter_within_deadzone_is_not_held(self):
        memory = FakeMemory()
        memory.set_stick(5, -5)
        source = GSinputMovementSource(memory)
        self.assertFalse(source.is_direction_held())

    def test_stick_pushed_past_deadzone_on_x_is_held(self):
        memory = FakeMemory()
        memory.set_stick(100, 0)
        source = GSinputMovementSource(memory)
        self.assertTrue(source.is_direction_held())

    def test_stick_pushed_past_deadzone_negative_y_is_held(self):
        memory = FakeMemory()
        memory.set_stick(0, -100)
        source = GSinputMovementSource(memory)
        self.assertTrue(source.is_direction_held())

    def test_unreadable_memory_fails_safe_to_not_held(self):
        memory = FakeMemory()  # nothing mapped
        source = GSinputMovementSource(memory)
        self.assertFalse(source.is_direction_held())


class NeverHeldMovementSourceTests(unittest.TestCase):
    def test_always_reports_not_held(self):
        self.assertFalse(NeverHeldMovementSource().is_direction_held())


if __name__ == "__main__":
    unittest.main()
