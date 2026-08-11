"""Foreground-scoped manual battle HP summaries for Windows."""
from dataclasses import dataclass
import ctypes
import os

from .health import round_percent, speech_name
from .speech import SpeechEventClass

STATUS_NAMES = {
    0: None,
    3: "poisoned",
    4: "badly poisoned",
    5: "paralyzed",
    6: "burned",
    7: "frozen",
    8: "asleep",
}

KEY_CODES = {
    **{chr(value).casefold(): value for value in range(ord("A"), ord("Z") + 1)},
    **{str(value): ord(str(value)) for value in range(10)},
    **{f"f{value}": 0x6F + value for value in range(1, 13)},
    # VK_OEM_* punctuation keys, needed for entity-navigation hotkeys.
    "period": 0xBE,
    "comma": 0xBC,
    "slash": 0xBF,
}
MODIFIER_CODES = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12}

class HotkeyError(ValueError):
    pass

def parse_hotkey(value):
    parts = [part.strip().casefold() for part in value.split("+") if part.strip()]
    keys = [part for part in parts if part not in MODIFIER_CODES]
    modifiers = [part for part in parts if part in MODIFIER_CODES]
    if len(keys) != 1 or keys[0] not in KEY_CODES or len(set(parts)) != len(parts):
        raise HotkeyError(f"invalid HP summary hotkey: {value!r}")
    if not modifiers:
        raise HotkeyError("HP summary hotkey must include a modifier")
    return tuple(MODIFIER_CODES[item] for item in modifiers) + (KEY_CODES[keys[0]],)

class WindowsForegroundProcess:
    """Reports whether the configured process owns foreground focus."""

    def __init__(self, process_name="Dolphin.exe", user32=None, kernel32=None):
        self.process_name = process_name.casefold()
        self.user32 = user32 or ctypes.windll.user32
        self.kernel32 = kernel32 or ctypes.windll.kernel32

    def process_name_for_foreground(self):
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.c_ulong()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        handle = self.kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(size)):
                return ""
            return os.path.basename(buffer.value).casefold()
        finally:
            self.kernel32.CloseHandle(handle)

    def is_active(self):
        return self.process_name_for_foreground() == self.process_name


class WindowsForegroundHotkey:
    """Edge-triggered chord accepted only while Dolphin owns foreground focus."""
    def __init__(self, chord, process_name="Dolphin.exe", user32=None, kernel32=None):
        self.codes = parse_hotkey(chord)
        self.process_name = process_name.casefold()
        self.user32 = user32 or ctypes.windll.user32
        self.kernel32 = kernel32 or ctypes.windll.kernel32
        self.held = False

    def _pressed(self):
        return all(self.user32.GetAsyncKeyState(code) & 0x8000 for code in self.codes)

    def _foreground_process(self):
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.c_ulong()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        handle = self.kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(size)):
                return ""
            return os.path.basename(buffer.value).casefold()
        finally:
            self.kernel32.CloseHandle(handle)

    def poll(self):
        pressed = self._pressed()
        fire = pressed and not self.held and self._foreground_process() == self.process_name
        self.held = pressed
        return fire

@dataclass
class PendingSummary:
    signature: tuple
    samples: tuple

class BattleHPSummary:
    def __init__(self, source, profile, hotkey, speech, logger):
        self.source = source
        self.profile = profile
        self.hotkey = hotkey
        self.speech = speech
        self.logger = logger
        self.pending = None

    def clear(self, reason):
        self.pending = None
        self.logger.debug("HP SUMMARY CLEAR reason=%s", reason)

    @staticmethod
    def _signature(samples):
        return tuple((sample.identity, sample.raw_nickname, sample.hp,
                      sample.max_hp, sample.condition, sample.level)
                     for sample in samples)

    def _ordered(self, samples):
        by_slot = {sample.identity.slot: sample for sample in samples}
        return [(ownership, by_slot[slot])
                for slot, ownership in zip(
                    self.profile.summary_slot_order,
                    self.profile.summary_slot_ownership)
                if slot in by_slot]

    @staticmethod
    def _line(ownership, sample):
        name = speech_name(sample.raw_nickname)
        _, percentage = round_percent(sample.hp, sample.max_hp)
        percent = "zero percent" if percentage == 0 else f"{percentage} percent"
        pieces = [f"{ownership} {name}", f"level {sample.level}",
                  f"{sample.hp} of {sample.max_hp} HP", percent]
        if sample.hp == 0:
            pieces.append("fainted")
        status = STATUS_NAMES[sample.condition]
        if status is not None:
            pieces.append(status)
        return ", ".join(pieces) + "."

    def poll_once(self):
        triggered = self.hotkey.poll()
        if triggered:
            samples = tuple(self.source.battlers())
            ordered = tuple(sample for _, sample in self._ordered(samples))
            if not ordered:
                self.logger.debug("HP SUMMARY ignored: no occupied active slots")
                self.pending = None
                return
            self.pending = PendingSummary(self._signature(ordered), ordered)
            self.logger.debug("HP SUMMARY sample1 count=%d", len(ordered))
            return
        if self.pending is None:
            return
        samples = tuple(self.source.battlers())
        ordered_pairs = self._ordered(samples)
        ordered = tuple(sample for _, sample in ordered_pairs)
        signature = self._signature(ordered)
        pending = self.pending
        self.pending = None
        if signature != pending.signature:
            self.logger.warning("HP SUMMARY suppressed: live battlers changed between samples")
            return
        text = " ".join(self._line(owner, sample)
                        for owner, sample in ordered_pairs)
        self.speech.emit(SpeechEventClass.BATTLE_EVENT, text, interrupt=True)
        self.logger.info("HP SUMMARY %s", text)


class HeartGaugeSummary:
    """On-demand Shadow Pokemon Heart Gauge check, usable anywhere in the
    overworld (not battle-only like BattleHPSummary) -- the project owner
    explicitly requested this alongside the party summary screen's own
    passive Heart Gauge narration ("both"), for checking progress while
    just walking around. No settling/two-sample logic is needed here (unlike
    BattleHPSummary) since the overworld party struct doesn't animate the
    way an in-battle HP bar does -- a single fresh read on hotkey press is
    already correct."""

    def __init__(self, source, hotkey, speech, logger):
        self.source = source
        self.hotkey = hotkey
        self.speech = speech
        self.logger = logger

    def clear(self, reason):
        self.logger.debug("HEART GAUGE CLEAR reason=%s", reason)

    @staticmethod
    def _line(slot):
        name = speech_name(slot.raw_nickname)
        if slot.heart_gauge_percent >= 100:
            return f"{name}: fully open, ready to purify."
        return f"{name}: {slot.heart_gauge_percent} percent open."

    def poll_once(self):
        if not self.hotkey.poll():
            return
        try:
            slots = self.source.slots()
        except Exception as exc:
            self.logger.debug("HEART GAUGE read failed: %s", exc)
            return
        shadow = [slot for slot in slots if slot.heart_gauge_percent is not None]
        text = (
            " ".join(self._line(slot) for slot in shadow)
            if shadow else "No Shadow Pokemon in your party."
        )
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
        self.logger.info("HEART GAUGE %s", text)


class MoneySummary:
    """On-demand Pokédollar balance check, usable anywhere in the
    overworld -- project owner's explicit request, 2026-07-30. Reads
    `hero_pokedoru_offset` off the same "hero" struct base bag_menu.py's
    own `_hero_base()` already resolves (`savedata_pointer_address` ->
    `+hero_offset`), matching xd-decomp's `heroBiosGetPokedoru`
    (game/pxdvs/app/hero/heroBios.cpp) -- see profile.py's own comment for
    the derivation chain."""

    def __init__(self, memory, profile, hotkey, speech, logger, announce_increases=False):
        self.memory = memory
        self.profile = profile
        self.hotkey = hotkey
        self.speech = speech
        self.logger = logger
        self.announce_increases = announce_increases
        self.previous_money = None

    def clear(self, reason):
        self.previous_money = None
        self.logger.debug("MONEY CLEAR reason=%s", reason)


    def _hero_base(self):
        p = self.profile
        savedata = self.memory.pointer(
            p.savedata_pointer_address,
            p.hero_offset + p.hero_party_offset
            + p.hero_party_slots * p.hero_party_stride,
            "money hero savedata pointer",
            4,
        )
        return savedata + p.hero_offset

    def poll_once(self):
        triggered = self.hotkey.poll()
        if not triggered and not self.announce_increases:
            return
        try:
            hero = self._hero_base()
            money = self.memory.u32(
                hero + self.profile.hero_pokedoru_offset, "hero money")
            coupons = self.memory.u32(
                hero + self.profile.hero_poke_coupon_offset,
                "hero Poke Coupons")
        except Exception as exc:
            self.logger.debug("MONEY read failed: %s", exc)
            return
        previous = self.previous_money
        self.previous_money = money
        if triggered:
            text = (
                f"Pok\u00e9dollars: {money}. "
                f"Pok\u00e9 Coupons: {coupons}."
            )
            self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
            self.logger.info("MONEY %s", text)
        elif previous is not None and money > previous:
            amount = money - previous
            text = f"Received {amount} Pok\u00e9dollars. Total: {money}."
            self.speech.emit(SpeechEventClass.BATTLE_EVENT, text, interrupt=False)
            self.logger.info("MONEY GAIN %s", text)
