"""Foreground-scoped manual battle HP summaries for Windows."""
from dataclasses import dataclass
import ctypes
import os

from .health import (
    STATUS_NAMES, owner_for_battler, round_percent, speech_name,
)
from .speech import SpeechEventClass

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
        if not all(self.user32.GetAsyncKeyState(code) & 0x8000
                   for code in self.codes):
            return False
        # A chord means exactly itself: a modifier the chord does not name
        # must be UP. Without this, `ctrl+slash` is also pressed every time
        # `ctrl+shift+slash` is -- ctrl and slash are both down -- so the
        # two chords were never distinguishable, and the shorter one won
        # wherever a caller tested it first. That is exactly what happened
        # to entity-nav's refresh: `poll_once` checks `repeat` (ctrl+slash)
        # before `refresh` (ctrl+shift+slash), so from the day refresh was
        # added, pressing it re-announced the selection and never rebuilt
        # the list. Found 2026-08-16 while re-binding autowalk onto that
        # same chord.
        return not any(
            self.user32.GetAsyncKeyState(code) & 0x8000
            for code in MODIFIER_CODES.values() if code not in self.codes
        )

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
        """(ownership word, sample) for every occupied slot, player side first.

        Ownership is DERIVED, via `health.owner_for_battler`, from which
        trainer's party array the battler's own FightPokemon record sits in
        -- not from its index in the active array. The positional
        `profile.summary_slot_ownership` tuple this used to index is
        documented in profile.py as unreliable for exactly this purpose: the
        2026-07-25 handoff recorded the opposite interleaving, and a fixed
        tuple cannot be right for both. It also cannot survive the active
        array compacting after a faint, which is when the summary matters
        most -- ctrl+h would confidently attribute the foe's Pokemon to the
        player. `owner_for_battler` still falls back to the tuple when the
        pointer lands outside every party range, which does not happen for a
        real battler.

        Speaking order is now derived too, rather than read from
        `summary_slot_order`: the player's battlers first, then the
        opponent's, each in active-slot order. That is the same order the
        old tuple produced for an uncompacted field, and unlike the tuple it
        stays grouped by side after a replacement lands in a different
        slot."""
        ordered = []
        for sample in samples:
            ownership = owner_for_battler(self.profile, sample)
            ordered.append((ownership, sample))
        ordered.sort(
            key=lambda item: (item[0] != "Player", item[1].identity.slot))
        return ordered

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
    overworld (not battle-only like BattleHPSummary), covering both the
    current party and every PC box -- the project owner
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
            slots = self.source.shadow_gauge_slots()
        except Exception as exc:
            self.logger.debug("HEART GAUGE read failed: %s", exc)
            return
        shadow = [slot for slot in slots if slot.heart_gauge_percent is not None]
        text = (
            " ".join(self._line(slot) for slot in shadow)
            if shadow else "No Shadow Pokemon have a Shadow Gauge."
        )
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
        self.logger.info("HEART GAUGE %s", text)


class PartySlotSummary:
    """Ctrl+1 through Ctrl+6: everything about one party member, anywhere.

    The party summary SCREEN (party_summary_screen.py) already narrates all
    of this, but only while that screen is open, and getting there costs
    several menus. The project owner asked for the same facts on a single
    key press, from the overworld or from inside a battle, which is what
    this is: one chord per party slot, no navigation.

    Reads the overworld roster (`PartyMemorySource.slots()`, i.e.
    Hero.partyPokemon[6]) rather than the battle field. That is deliberate
    and is the right source for both cases -- the field only ever holds the
    one or two Pokemon currently out, whereas "what is in slot 4" is a
    question about the roster, and the roster struct is the same one the
    game itself writes HP and status back into during a battle.

    `item_names` is optional and duck-typed on `resolve_name(item_id)`
    (production passes `item_database.ItemNameResolver`). Without it, or
    for an ID it cannot resolve, the raw ID is spoken rather than a guessed
    name -- the same policy party_summary_screen.py already follows.

    **The ability is deliberately NOT spoken here (removed 2026-08-18).**
    It was in the first version of this readout; the project owner reported
    it as wrong -- "it's not accurate anyways" -- so it is gone rather than
    left in with a caveat. A stated fact a player cannot trust is worse
    than an absent one: they either act on it and are misled, or they learn
    to discount the whole utterance, which costs the fields that ARE
    correct.

    This is a removal, not a fix. `PartySlot.ability_name` still carries
    the same value, `party_summary_screen.py`'s Status page still speaks
    it, and the resolution chain in `resolver.LocalAbilityData` is
    untouched -- so whatever is wrong there is still wrong, and still
    reaches the player by that route. Diagnosing it needs a live sample of
    a Pokemon whose real ability is known; see the coverage matrix entry.
    """

    def __init__(self, source, hotkeys, speech, logger, item_names=None):
        self.source = source
        self.hotkeys = dict(hotkeys)
        self.speech = speech
        self.logger = logger
        self.item_names = item_names

    def clear(self, reason):
        self.logger.debug("PARTY SLOT CLEAR reason=%s", reason)

    def _item_text(self, item_id):
        if not item_id:
            return "No item held."
        if self.item_names is not None:
            try:
                name = self.item_names.resolve_name(item_id)
            except Exception:
                name = None
            if name:
                return f"Holding {speech_name(name)}."
        return f"Holding item {item_id}."

    def line(self, index, slot):
        """Everything one press should say. `slot` is None for an empty
        party position."""
        position = f"Slot {index + 1}"
        if slot is None:
            return f"{position} is empty."
        _, percentage = round_percent(slot.hp, slot.max_hp)
        percent = "zero percent" if percentage == 0 else f"{percentage} percent"
        pieces = [
            f"{position}. {speech_name(slot.raw_nickname)}",
            f"level {slot.level}",
            f"{slot.hp} of {slot.max_hp} HP",
            percent,
        ]
        if slot.hp == 0:
            pieces.append("fainted")
        status = STATUS_NAMES.get(slot.condition)
        if status is not None:
            pieces.append(status)
        text = ", ".join(pieces) + "."
        if slot.heart_gauge_percent is not None:
            text += (
                " Heart Gauge: fully open, ready to purify."
                if slot.heart_gauge_percent >= 100
                else f" Heart Gauge: {slot.heart_gauge_percent} percent open."
            )
        text += f" {self._item_text(slot.item_id)}"
        return text

    def poll_once(self):
        pressed = [index for index, hotkey in sorted(self.hotkeys.items())
                   if hotkey.poll()]
        if not pressed:
            return
        if len(pressed) > 1:
            # Two party chords in one tick is not a thing a player does on
            # purpose; answering the first keeps the reply deterministic
            # instead of speaking two summaries over each other.
            self.logger.debug("PARTY SLOT multiple chords %r", pressed)
        index = pressed[0]
        try:
            slots = {slot.index: slot for slot in self.source.slots()}
        except Exception as exc:
            # Spoken, not silent. The player pressed a key: silence reads
            # as "the companion is broken" and is indistinguishable from a
            # dead hotkey, which is precisely the failure this feature is
            # meant to remove.
            self.logger.debug("PARTY SLOT read failed: %s", exc)
            self.speech.emit(
                SpeechEventClass.ENTITY_NAV,
                "Party is not available right now.", interrupt=True)
            return
        text = self.line(index, slots.get(index))
        self.speech.emit(SpeechEventClass.ENTITY_NAV, text, interrupt=True)
        self.logger.info("PARTY SLOT %d %s", index + 1, text)


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
