"""Phase 1F: bounded read-only HP damage and health-bar validation.

Vanilla US Pokemon XD (GXXE01 Rev 0) only.  This diagnostic is deliberately
separate from production and every earlier proof of concept.  It performs
only dolphin_memory_engine reads and cytolk speech.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import os
import sys
import time

import dolphin_memory_engine as dme
from cytolk import tolk


MEM1_START = 0x80000000
MEM1_END = 0x81800000
FIGHT_FLOOR = 0x804A1730
BATTLER_ARRAY = FIGHT_FLOOR + 0xDE44
BATTLER_SLOTS = 8
WINDOW_MANAGER = 0x80445A68
WINDOW_HEAD_OFFSET = 0x10
MAX_WINDOWS = 64
WINDOW_MIN_SIZE = 0xBC
STATUS_ALLOC_SIZE = 0x30
POLL_SECONDS = 0.05
STABLE_SAMPLES = 2
NICKNAME_MAX = 11
MAX_PLAUSIBLE_HP = 9999
GSMSG_MANAGER_ROOT = 0x804E8348
GSMSG_CAPACITY = 2
GSMSG_STRIDE = 0x6C
LOG_PATH = os.path.join(
    os.path.dirname(__file__), "logs", "phase1f_hp_damage_poc.log"
)


class ValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Battler:
    slot: int
    fight_out: int
    fight_pokemon: int
    pokemon: int
    nickname: str
    hp: int
    max_hp: int

    @property
    def identity(self):
        return (self.slot, self.fight_out, self.fight_pokemon, self.pokemon)


@dataclass(frozen=True)
class StatusWindow:
    address: int
    menu_id: int
    allocation: int
    max_hp: int
    target_hp: int
    old_hp: int
    duration: int
    progress: int
    nickname: str
    text_1_pointer: int
    text_1: str
    text_2_pointer: int
    text_2: str


def valid_range(address, size, alignment=1):
    return (
        isinstance(address, int)
        and address != 0
        and alignment > 0
        and address % alignment == 0
        and MEM1_START <= address
        and size >= 0
        and address + size <= MEM1_END
    )


def read_bytes(address, size, label, alignment=1):
    if not valid_range(address, size, alignment):
        raise ValidationError(
            f"{label}: invalid range 0x{address:08X}+0x{size:X} "
            f"alignment={alignment}"
        )
    data = dme.read_bytes(address, size)
    if data is None or len(data) != size:
        raise ValidationError(f"{label}: short read")
    return bytes(data)


def u16(address, label):
    return int.from_bytes(read_bytes(address, 2, label), "big")


def u8(address, label):
    return read_bytes(address, 1, label)[0]

def s16(address, label):
    value = u16(address, label)
    return value - 0x10000 if value & 0x8000 else value


def u32(address, label):
    return int.from_bytes(read_bytes(address, 4, label, 4), "big")


def decode_gschar(address, maximum, label, allow_null=False):
    if address == 0 and allow_null:
        return ""
    raw = read_bytes(address, (maximum + 1) * 2, label)
    chars = []
    for offset in range(0, len(raw), 2):
        value = (raw[offset] << 8) | raw[offset + 1]
        if value == 0:
            return "".join(chars)
        if value < 0x20 or value == 0xFFFF:
            raise ValidationError(f"{label}: control value 0x{value:04X}")
        chars.append(chr(value))
    raise ValidationError(f"{label}: unterminated string")


def normalize(text):
    return " ".join(text.split()).casefold()


def sample_battlers():
    result = []
    for slot in range(BATTLER_SLOTS):
        entry = BATTLER_ARRAY + slot * 4
        fight_out = u32(entry, f"battler[{slot}] FightOutPokemon")
        if fight_out == 0:
            continue
        if not valid_range(fight_out, 8, 4):
            raise ValidationError(
                f"battler[{slot}]: invalid FightOutPokemon 0x{fight_out:08X}"
            )
        fight_pokemon = u32(
            fight_out + 0x04, f"battler[{slot}] FightPokemon"
        )
        if not valid_range(fight_pokemon, 0x96, 4):
            raise ValidationError(
                f"battler[{slot}]: invalid FightPokemon 0x{fight_pokemon:08X}"
            )
        pokemon = fight_pokemon + 0x04
        nickname = decode_gschar(
            fight_pokemon + 0x52,
            NICKNAME_MAX,
            f"battler[{slot}] nickname",
        )
        hp = u16(pokemon + 0x04, f"battler[{slot}] HP")
        max_hp = u16(pokemon + 0x90, f"battler[{slot}] maximum HP")
        if not nickname.strip():
            raise ValidationError(f"battler[{slot}]: empty nickname")
        if not 1 <= max_hp <= MAX_PLAUSIBLE_HP or hp > max_hp:
            raise ValidationError(
                f"battler[{slot}]: impossible HP {hp}/{max_hp}"
            )
        result.append(
            Battler(
                slot, fight_out, fight_pokemon, pokemon, nickname, hp, max_hp
            )
        )
    # Reject structural changes during one sample.
    for battler in result:
        if u32(
            BATTLER_ARRAY + battler.slot * 4,
            f"battler[{battler.slot}] identity recheck",
        ) != battler.fight_out:
            raise ValidationError("battler array changed during sample")
    return result


def _optional_text(pointer, label):
    if pointer == 0 or not valid_range(pointer, 2):
        return ""
    try:
        return decode_gschar(pointer, 32, label)
    except ValidationError:
        return ""


def sample_windows():
    pointer = u32(WINDOW_MANAGER + WINDOW_HEAD_OFFSET, "window list head")
    seen = set()
    windows = []
    for _ in range(MAX_WINDOWS):
        if pointer == 0:
            return windows
        if pointer in seen:
            raise ValidationError("window list contains a cycle")
        if not valid_range(pointer, WINDOW_MIN_SIZE, 4):
            raise ValidationError(f"invalid window 0x{pointer:08X}")
        seen.add(pointer)
        menu_id = u32(pointer + 0x04, "window menu ID")
        allocation = u32(pointer + 0xB8, "window allocation")
        if valid_range(allocation, STATUS_ALLOC_SIZE, 4):
            status_nickname = decode_gschar(
                allocation, NICKNAME_MAX, "status copied nickname"
            )
            max_hp = s16(allocation + 0x18, "status maximum HP")
            target_hp = s16(allocation + 0x1A, "status target HP")
            old_hp = s16(pointer + 0xA8, "status animation old HP")
            duration = s16(pointer + 0xAA, "status animation duration")
            progress = s16(pointer + 0xAC, "status animation progress")
            text_1_pointer = u32(allocation + 0x1C, "status text pointer 1")
            text_2_pointer = u32(allocation + 0x20, "status text pointer 2")
            if (
                1 <= max_hp <= MAX_PLAUSIBLE_HP
                and 0 <= target_hp <= max_hp
                and 0 <= old_hp <= max_hp
                and duration >= 0
                and progress >= 0
            ):
                windows.append(
                    StatusWindow(
                        pointer,
                        menu_id,
                        allocation,
                        max_hp,
                        target_hp,
                        old_hp,
                        duration,
                        progress,
                        status_nickname,
                        text_1_pointer,
                        _optional_text(text_1_pointer, "status text 1"),
                        text_2_pointer,
                        _optional_text(text_2_pointer, "status text 2"),
                    )
                )
        next_pointer = u32(pointer + 0x10, "next window")
        pointer = next_pointer
    raise ValidationError("window list exceeds static traversal bound")


def correlation_candidates(battler, windows):
    nickname = normalize(battler.nickname)
    matches = []
    for window in windows:
        if (
            window.max_hp == battler.max_hp
            and window.target_hp == battler.hp
            and normalize(window.nickname) == nickname
        ):
            matches.append(window)
    return matches


def build_mapping(battlers, windows):
    candidates = {
        battler.identity: correlation_candidates(battler, windows)
        for battler in battlers
    }
    mapping = {}
    used = set()
    for battler in battlers:
        choices = candidates[battler.identity]
        if len(choices) == 1 and choices[0].address not in used:
            mapping[battler.identity] = choices[0]
            used.add(choices[0].address)
    return mapping, candidates


def sample_gsmsg_ids():
    manager = u32(GSMSG_MANAGER_ROOT, "GSmsg manager")
    if manager == 0:
        return ()
    if not valid_range(manager, 0x20, 4):
        raise ValidationError("invalid GSmsg manager")
    capacity = u16(manager, "GSmsg capacity")
    tasks = u32(manager + 0x1C, "GSmsg tasks")
    if capacity != GSMSG_CAPACITY or not valid_range(
        tasks, capacity * GSMSG_STRIDE, 4
    ):
        raise ValidationError("invalid GSmsg structure")
    result = []
    for index in range(capacity):
        task = tasks + index * GSMSG_STRIDE
        state = u8(task, f"GSmsg task {index} state")
        if state not in (0, 1, 2):
            raise ValidationError(f"invalid GSmsg state {state}")
        if state:
            packed = u32(task + 0x1C, f"GSmsg task {index} packed ID")
            result.append((index, state, packed, packed & 0xFFFFF))
    return tuple(result)


def round_half_up(numerator, denominator):
    value = Decimal(numerator * 100) / Decimal(denominator)
    return value, int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def percent_words(raw, rounded, remaining=False):
    if raw > 0 and rounded == 0:
        value = "less than one percent"
    else:
        value = f"{rounded} percent"
    return f"{value} remaining" if remaining else value


def describe_battler(b):
    return (
        f"slot={b.slot} FightOutPokemon=0x{b.fight_out:08X} "
        f"FightPokemon=0x{b.fight_pokemon:08X} Pokemon=0x{b.pokemon:08X} "
        f"nickname={b.nickname!r} HP={b.hp}/{b.max_hp}"
    )


def describe_window(w):
    return (
        f"window=0x{w.address:08X} menu={w.menu_id} "
        f"allocation=0x{w.allocation:08X} max={w.max_hp} target={w.target_hp} "
        f"old={w.old_hp} duration={w.duration} progress={w.progress} "
        f"copied_nickname={w.nickname!r} "
        f"text1_ptr=0x{w.text_1_pointer:08X} text1={w.text_1!r} "
        f"text2_ptr=0x{w.text_2_pointer:08X} text2={w.text_2!r}"
    )


def log_line(handle, text):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    line = f"[{stamp}.{int(time.time() * 1000) % 1000:03d}] {text}"
    print(line, flush=True)
    handle.write(line + "\n")
    handle.flush()


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    dme.hook()
    if not dme.is_hooked():
        print("ERROR: Dolphin is unavailable.")
        return 1
    try:
        tolk.load()
        if not tolk.is_loaded() or tolk.detect_screen_reader() is None:
            print("ERROR: NVDA or another supported screen reader is unavailable.")
            return 1

        baselines = {}
        pending = None
        last_snapshot = None
        stable_count = 0
        mappings_ready_since = None
        last_inventory = None
        last_gsmsg = ()
        with open(LOG_PATH, "a", encoding="utf-8") as log:
            log_line(log, "=== Phase 1F read-only HP diagnostic started ===")
            log_line(
                log,
                "audit: DME calls are hook/is_hooked/read_bytes/un_hook only; "
                "eight fixed battler slots; bounded window list; no writes/GDB",
            )
            while dme.is_hooked():
                started = time.monotonic()
                try:
                    battlers = sample_battlers()
                    windows = sample_windows()
                    mapping, candidates = build_mapping(battlers, windows)
                    gsmsg = sample_gsmsg_ids()
                    if gsmsg != last_gsmsg:
                        log_line(log, f"GSmsg active={gsmsg!r}")
                        last_gsmsg = gsmsg

                    inventory = (
                        tuple((b.identity, b.nickname, b.hp, b.max_hp) for b in battlers),
                        tuple(
                            (
                                w.address,
                                w.menu_id,
                                w.allocation,
                                w.max_hp,
                                w.target_hp,
                                w.old_hp,
                                w.duration,
                                w.progress,
                                w.text_1,
                                w.text_2,
                            )
                            for w in windows
                        ),
                    )
                    if inventory != last_inventory:
                        for battler in battlers:
                            log_line(log, "BATTLER " + describe_battler(battler))
                        for window in windows:
                            log_line(log, "STATUS_CANDIDATE " + describe_window(window))
                        for battler in battlers:
                            choices = candidates[battler.identity]
                            log_line(
                                log,
                                f"CORRELATION nickname={battler.nickname!r} "
                                f"identity={battler.identity!r} candidates="
                                f"{[f'0x{x.address:08X}' for x in choices]!r}",
                            )
                        last_inventory = inventory

                    identities = {b.identity for b in battlers}
                    for identity in list(baselines):
                        if identity not in identities:
                            del baselines[identity]
                    for battler in battlers:
                        if battler.identity not in baselines:
                            baselines[battler.identity] = battler.hp
                            log_line(
                                log,
                                "BASELINE established " + describe_battler(battler),
                            )

                    all_unambiguous = (
                        bool(battlers)
                        and len(mapping) == len(battlers)
                        and all(len(candidates[b.identity]) == 1 for b in battlers)
                    )
                    if all_unambiguous:
                        if mappings_ready_since is None:
                            mappings_ready_since = started
                            log_line(log, "READY: all battler/status mappings unambiguous")
                    else:
                        mappings_ready_since = None

                    if pending is None:
                        for battler in battlers:
                            old_hp = baselines[battler.identity]
                            if battler.hp == old_hp:
                                continue
                            choices = candidates[battler.identity]
                            if len(choices) != 1:
                                log_line(
                                    log,
                                    f"INCONCLUSIVE: HP changed for {battler.nickname!r} "
                                    f"but status mapping count={len(choices)}; no speech",
                                )
                                return 2
                            window = choices[0]
                            if window.target_hp != battler.hp:
                                log_line(
                                    log,
                                    "INCONCLUSIVE: status target disagrees with logical HP",
                                )
                                return 2
                            pending = {
                                "identity": battler.identity,
                                "nickname": battler.nickname,
                                "old": old_hp,
                                "new": battler.hp,
                                "max": battler.max_hp,
                                "window": window.address,
                                "started": started,
                                "gsmsg": gsmsg,
                            }
                            stable_count = 0
                            last_snapshot = None
                            log_line(
                                log,
                                f"EVENT begin nickname={battler.nickname!r} "
                                f"identity={battler.identity!r} old={old_hp} "
                                f"new={battler.hp} max={battler.max_hp} "
                                f"window=0x{window.address:08X} "
                                f"animation_old={window.old_hp} "
                                f"target={window.target_hp} duration={window.duration} "
                                f"progress={window.progress} GSmsg={gsmsg!r}",
                            )
                            break
                    else:
                        battler = next(
                            (b for b in battlers if b.identity == pending["identity"]),
                            None,
                        )
                        window = next(
                            (w for w in windows if w.address == pending["window"]),
                            None,
                        )
                        if battler is None or window is None:
                            log_line(log, "INCONCLUSIVE: pending identity/window vanished")
                            return 2
                        if battler.max_hp != pending["max"]:
                            log_line(log, "INCONCLUSIVE: maximum HP changed")
                            return 2
                        if battler.hp != pending["new"]:
                            if window.duration > 0:
                                pending["new"] = battler.hp
                                log_line(
                                    log,
                                    f"EVENT grouped logical update new={battler.hp} "
                                    f"target={window.target_hp}",
                                )
                            else:
                                log_line(log, "INCONCLUSIVE: unrelated second HP event")
                                return 2
                        snapshot = (
                            battler.identity,
                            battler.hp,
                            battler.max_hp,
                            window.target_hp,
                            window.duration,
                        )
                        log_line(
                            log,
                            f"ANIMATION window=0x{window.address:08X} "
                            f"old={window.old_hp} target={window.target_hp} "
                            f"duration={window.duration} progress={window.progress} "
                            f"logical={battler.hp}",
                        )
                        settled = (
                            window.duration == 0
                            and battler.hp == window.target_hp == pending["new"]
                        )
                        if settled and snapshot == last_snapshot:
                            stable_count += 1
                        elif settled:
                            stable_count = 1
                        else:
                            stable_count = 0
                        last_snapshot = snapshot
                        if stable_count >= STABLE_SAMPLES:
                            raw_change, rounded_change = round_half_up(
                                pending["old"] - pending["new"], pending["max"]
                            )
                            raw_remaining, rounded_remaining = round_half_up(
                                pending["new"], pending["max"]
                            )
                            if pending["new"] >= pending["old"]:
                                log_line(log, "INCONCLUSIVE: first validation is not damage")
                                return 2
                            speech = (
                                f"{pending['nickname']} lost "
                                f"{percent_words(raw_change, rounded_change)}. "
                                f"{percent_words(raw_remaining, rounded_remaining, True)}."
                            )
                            elapsed = started - pending["started"]
                            log_line(
                                log,
                                f"SETTLED old={pending['old']} new={pending['new']} "
                                f"max={pending['max']} raw_change_percent={raw_change} "
                                f"rounded_change={rounded_change} "
                                f"raw_remaining_percent={raw_remaining} "
                                f"rounded_remaining={rounded_remaining} "
                                f"settling_seconds={elapsed:.3f} speech={speech!r}",
                            )
                            spoke = tolk.speak(speech, interrupt=False)
                            log_line(log, f"NVDA spoke={spoke} sentence={speech!r}")
                            return 0
                except ValidationError as exc:
                    log_line(log, f"SAMPLE rejected safely: {exc}")
                elapsed = time.monotonic() - started
                time.sleep(max(0.0, POLL_SECONDS - elapsed))
            log_line(log, "Dolphin disconnected before validation completed")
            return 1
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            tolk.unload()
        except Exception:
            pass
        dme.un_hook()


if __name__ == "__main__":
    sys.exit(main())
