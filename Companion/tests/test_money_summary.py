import logging
import unittest

from battle_narrator.hotkeys import MoneySummary
from battle_narrator.memory import MemoryReader
from battle_narrator.phase1b_lifecycle import LifecycleController
from battle_narrator.profile import XD_US_REV0

FAKE_SAVEDATA = 0x80700000


def be32(value):
    return value.to_bytes(4, "big")


class WindowBackend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + offset, 0) for offset in range(size))


class Hotkey:
    def __init__(self):
        self.fire = False

    def poll(self):
        result = self.fire
        self.fire = False
        return result


class Speech:
    def __init__(self):
        self.calls = []

    def emit(self, event, text, interrupt=None):
        self.calls.append((event, text, interrupt))


class MoneySummaryTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowBackend()
        self.profile = XD_US_REV0
        self.memory = MemoryReader(self.backend, self.profile)
        self.hotkey = Hotkey()
        self.speech = Speech()
        self.logger = logging.getLogger("money-summary-test")
        p = self.profile
        self.backend.put(p.savedata_pointer_address, be32(FAKE_SAVEDATA))
        self.hero_base = FAKE_SAVEDATA + p.hero_offset

    def _summary(self):
        return MoneySummary(
            self.memory, self.profile, self.hotkey, self.speech, self.logger)

    def _set_money(self, value):
        self.backend.put(
            self.hero_base + self.profile.hero_pokedoru_offset, be32(value))

    def _set_coupons(self, value):
        self.backend.put(
            self.hero_base + self.profile.hero_poke_coupon_offset,
            be32(value))

    def press(self, summary):
        self.hotkey.fire = True
        summary.poll_once()

    def test_speaks_the_real_balance(self):
        self._set_money(300)
        self._set_coupons(42)
        summary = self._summary()
        self.press(summary)
        self.assertEqual(
            self.speech.calls[-1][1],
            "Pokédollars: 300. Poké Coupons: 42.")

    def test_zero_balance_is_spoken_not_suppressed(self):
        self._set_money(0)
        summary = self._summary()
        self.press(summary)
        self.assertEqual(
            self.speech.calls[-1][1],
            "Pokédollars: 0. Poké Coupons: 0.")

    def test_no_press_is_silent(self):
        self._set_money(300)
        summary = self._summary()
        summary.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_passive_increase_announces_reward_delta(self):
        self._set_money(300)
        summary = MoneySummary(self.memory, self.profile, self.hotkey, self.speech, self.logger, announce_increases=True)
        summary.poll_once()
        self._set_money(550); summary.poll_once()
        self.assertEqual(self.speech.calls[-1][1], "Received 250 Pok\u00e9dollars. Total: 550.")

    def test_passive_decrease_is_silent(self):
        self._set_money(300)
        summary = MoneySummary(self.memory, self.profile, self.hotkey, self.speech, self.logger, announce_increases=True)
        summary.poll_once(); self._set_money(100); summary.poll_once()
        self.assertEqual(self.speech.calls, [])

    def test_read_failure_is_silent(self):
        # No savedata pointer configured -- MemoryReader.pointer will
        # reject the resulting bounds, matching a real transient/unready
        # save state rather than crashing the poll loop.
        backend = WindowBackend()
        memory = MemoryReader(backend, self.profile)
        summary = MoneySummary(
            memory, self.profile, self.hotkey, self.speech, self.logger)
        self.press(summary)
        self.assertEqual(self.speech.calls, [])

    def test_lifecycle_accepts_money_summary_factory(self):
        summary = self._summary()
        factory = lambda: summary
        controller = LifecycleController(
            object(), lambda: None, lambda tasks: None, object(),
            logging.getLogger("lifecycle-money-test"),
            money_summary_factory=factory,
        )
        self.assertIs(controller.money_summary_factory, factory)
        self.assertIsNone(controller.money_summary_reader)


if __name__ == "__main__":
    unittest.main()
