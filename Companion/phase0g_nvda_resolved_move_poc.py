"""
Phase 0G: read-only GSmsg move-announcement substitution validation.

Separate from Phase 0D and Phase 0F. Polls the confirmed GSmsg task array,
resolves template 20333 through live msgctrl values and independently
through the locally extracted common.rel data, and speaks only when both
paths agree.

The only dolphin_memory_engine operations used are hook, is_hooked,
get_status, read_byte, read_bytes, read_word, and un_hook.
"""

import json
import os
import re
import struct
import sys
import time
from dataclasses import dataclass

import dolphin_memory_engine as dme
from cytolk import tolk

import _dialogue_extraction_tool as extraction


MANAGER_ROOT_ADDR = 0x804E8348
ATTACK_MONS_ADDR = 0x804EB1FC
WAZA_NAME_ADDR = 0x804EB260
EV_STR_BUF1_ADDR = 0x804EB1F4

STATIC_TASK_CAPACITY = 2
TASK_STRIDE = 0x6C
TASK_STATE_OFFSET = 0x00
TASK_ID_OFFSET = 0x1C
MOVE_TEMPLATE_ID = 20333
POLL_INTERVAL_SEC = 0.05

MEM1_START = 0x80000000
MEM1_END = 0x81800000
NICKNAME_MAX_CHARS = 11
RESOLVED_TEXT_MAX_CHARS = 64

BASE_DIR = os.path.dirname(__file__)
EXTRACTION_DIR = os.path.join(BASE_DIR, "_dialogue_extraction")
FIGHT_STRINGS_PATH = os.path.join(EXTRACTION_DIR, "fight_common_strings.json")
COMMON_FSYS_PATH = os.path.join(EXTRACTION_DIR, "raw", "files", "common.fsys")
LOG_PATH = os.path.join(BASE_DIR, "logs", "phase0g_nvda_resolved_move_poc.log")


class StructureError(RuntimeError):
    pass


class MessageValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SubstitutionSample:
    attacker: int
    fight_pokemon: int
    nickname_address: int
    move_name_pointer: int
    suffix_pointer: int
    move_id: int
    nickname: str
    live_move_name: str
    live_suffix: str


def timestamp():
    now = time.time()
    return (
        time.strftime("%H:%M:%S", time.localtime(now))
        + f".{int(now * 1000) % 1000:03d}"
    )


def log(handle, message):
    line = f"[{timestamp()}] {message}"
    print(line, flush=True)
    handle.write(line + "\n")
    handle.flush()


def valid_mem1_range(address, size=1, alignment=1):
    return (
        isinstance(address, int)
        and address != 0
        and alignment > 0
        and address % alignment == 0
        and size >= 0
        and MEM1_START <= address
        and address + size <= MEM1_END
    )


def require_pointer(address, size, label, alignment=4):
    if not valid_mem1_range(address, size, alignment=alignment):
        raise MessageValidationError(
            f"{label} invalid: pointer=0x{address:08X}, size=0x{size:X}"
        )
    return address


def read_u16_be(address):
    raw = dme.read_bytes(address, 2)
    if raw is None or len(raw) != 2:
        raise StructureError(f"short u16 read at 0x{address:08X}")
    return int.from_bytes(raw, "big")


def resolve_structure():
    manager_before = dme.read_word(MANAGER_ROOT_ADDR)
    if not valid_mem1_range(manager_before, 0x24, alignment=4):
        raise StructureError(
            f"invalid manager pointer 0x{manager_before:08X}"
        )

    capacity = read_u16_be(manager_before)
    if capacity != STATIC_TASK_CAPACITY:
        raise StructureError(
            f"capacity {capacity} != static capacity {STATIC_TASK_CAPACITY}"
        )

    task_array = dme.read_word(manager_before + 0x1C)
    array_size = capacity * TASK_STRIDE
    if not valid_mem1_range(task_array, array_size, alignment=4):
        raise StructureError(
            f"invalid task array 0x{task_array:08X}, size=0x{array_size:X}"
        )

    manager_after = dme.read_word(MANAGER_ROOT_ADDR)
    capacity_after = read_u16_be(manager_before)
    task_array_after = dme.read_word(manager_before + 0x1C)
    if (
        manager_after != manager_before
        or capacity_after != capacity
        or task_array_after != task_array
    ):
        raise StructureError("GSmsg structure changed while resolving")

    return manager_before, capacity, task_array


def split_packed_id(packed_id):
    return packed_id >> 20, packed_id & 0x000FFFFF


def decode_live_gschar(address, maximum_chars, label, alignment):
    require_pointer(address, (maximum_chars + 1) * 2, label, alignment=alignment)
    raw = dme.read_bytes(address, (maximum_chars + 1) * 2)
    if raw is None or len(raw) != (maximum_chars + 1) * 2:
        raise MessageValidationError(f"{label}: short GSchar read")

    chars = []
    terminated = False
    for offset in range(0, len(raw), 2):
        value = int.from_bytes(raw[offset : offset + 2], "big")
        if value == 0:
            terminated = True
            break
        if value == 0xFFFF:
            raise MessageValidationError(
                f"{label}: unexpected unresolved control sentinel"
            )
        chars.append(chr(value))
        if len(chars) > maximum_chars:
            raise MessageValidationError(f"{label}: exceeds character bound")

    if not terminated:
        raise MessageValidationError(
            f"{label}: no terminator within {maximum_chars} characters"
        )
    return "".join(chars)


def take_substitution_sample():
    attacker = dme.read_word(ATTACK_MONS_ADDR)
    require_pointer(attacker, 0x64E, "_ATTACK_MONS")

    fight_pokemon = dme.read_word(attacker + 0x04)
    require_pointer(
        fight_pokemon,
        0x52 + (NICKNAME_MAX_CHARS + 1) * 2,
        "FightPokemon",
    )
    nickname_address = fight_pokemon + 0x52

    move_name_pointer = dme.read_word(WAZA_NAME_ADDR)
    require_pointer(
        move_name_pointer,
        (RESOLVED_TEXT_MAX_CHARS + 1) * 2,
        "_WAZA_NAME",
        alignment=1,
    )
    suffix_pointer = dme.read_word(EV_STR_BUF1_ADDR)
    require_pointer(
        suffix_pointer,
        (RESOLVED_TEXT_MAX_CHARS + 1) * 2,
        "_EV_STR_BUF1",
        alignment=1,
    )

    move_id = read_u16_be(attacker + 0x64C)
    nickname = decode_live_gschar(
        nickname_address, NICKNAME_MAX_CHARS, "nickname", alignment=2
    )
    live_move_name = decode_live_gschar(
        move_name_pointer, RESOLVED_TEXT_MAX_CHARS, "live move name", alignment=1
    )
    live_suffix = decode_live_gschar(
        suffix_pointer, RESOLVED_TEXT_MAX_CHARS, "live suffix", alignment=1
    )

    return SubstitutionSample(
        attacker=attacker,
        fight_pokemon=fight_pokemon,
        nickname_address=nickname_address,
        move_name_pointer=move_name_pointer,
        suffix_pointer=suffix_pointer,
        move_id=move_id,
        nickname=nickname,
        live_move_name=live_move_name,
        live_suffix=live_suffix,
    )


def normalize_for_comparison(value):
    return re.sub(r"\s+", " ", value).strip().casefold()


class LocalMoveResolver:
    MOVE_STRIDE = 0x38
    NAME_ID_OFFSET = 0x20
    SUFFIX_ID_OFFSET = 0x28

    def __init__(self):
        with open(COMMON_FSYS_PATH, "rb") as handle:
            files = extraction.parse_fsys(handle.read())
        common_rel = next(entry for entry in files if entry["name"] == "common_rel")
        self.data = common_rel["data"]
        relocation = extraction.RelFile(self.data)
        self.moves_base = relocation.get_pointer(124)
        names_base = relocation.get_pointer(136)
        if self.moves_base < 0 or names_base < 0:
            raise RuntimeError("required common.rel pointers 124/136 missing")
        self.names = extraction.decode_string_table(self.data[names_base:])

        with open(FIGHT_STRINGS_PATH, encoding="utf-8") as handle:
            self.fight_strings = json.load(handle)

    def resolve(self, move_id):
        entry = self.moves_base + move_id * self.MOVE_STRIDE
        if move_id <= 0 or entry < 0 or entry + self.MOVE_STRIDE > len(self.data):
            raise MessageValidationError(f"move ID {move_id} outside local table")

        name_id = struct.unpack_from(
            ">I", self.data, entry + self.NAME_ID_OFFSET
        )[0]
        suffix_id = struct.unpack_from(
            ">I", self.data, entry + self.SUFFIX_ID_OFFSET
        )[0]
        name_tokens = self.names.get(name_id)
        suffix = self.fight_strings.get(str(suffix_id))
        if name_tokens is None or suffix is None:
            raise MessageValidationError(
                f"local lookup missing: move={move_id}, "
                f"name_id={name_id}, suffix_id={suffix_id}"
            )
        name = extraction.render_tokens(name_tokens)
        if "[" in name or "[" in suffix:
            raise MessageValidationError("local move text contains controls")
        return name_id, name, suffix_id, suffix


def presentation_case(value):
    if value and value == value.upper() and any(ch.isalpha() for ch in value):
        return value.title()
    return value


def speak_direct_message(handle, index, task_addr, message_id, text):
    if text is None or "[" in text:
        log(
            handle,
            f"NOT_SPOKEN index={index} task=0x{task_addr:08X} "
            f"message_id={message_id} reason=not_fully_decoded text={text!r}",
        )
        return
    spoke = tolk.speak(text, interrupt=True)
    log(
        handle,
        f"SPOKEN index={index} task=0x{task_addr:08X} "
        f"message_id={message_id} text={text!r} result={spoke}",
    )


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    resolver = LocalMoveResolver()

    with open(FIGHT_STRINGS_PATH, encoding="utf-8") as handle:
        fight_strings = json.load(handle)

    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        log(handle, "=== Phase 0G resolved-move diagnostic starting ===")
        log(
            handle,
            "Safety: read-only DME; capacity=2; states restricted to 0/1/2; "
            "all pointers and ranges validated inside MEM1.",
        )

        dme.hook()
        if not dme.is_hooked():
            log(handle, f"ABORT: DME hook failed: {dme.get_status()}")
            return 1

        speech_loaded = False
        try:
            manager, capacity, task_array = resolve_structure()
            log(
                handle,
                f"STRUCTURE manager=0x{manager:08X} capacity={capacity} "
                f"task_array=0x{task_array:08X} stride=0x{TASK_STRIDE:X}",
            )

            tolk.load()
            speech_loaded = bool(tolk.is_loaded())
            if not speech_loaded:
                raise StructureError("Tolk did not report loaded")
            reader = tolk.detect_screen_reader()
            if reader is None:
                raise StructureError("no active screen reader detected")
            log(handle, f"Screen reader detected: {reader}")

            states = [
                {
                    "task_state": 0,
                    "packed": None,
                    "pending": None,
                    "handled": False,
                    "opened_at": None,
                }
                for _ in range(capacity)
            ]

            while True:
                current = resolve_structure()
                if current != (manager, capacity, task_array):
                    raise StructureError(
                        f"GSmsg structure changed: initial="
                        f"{(manager, capacity, task_array)!r}, current={current!r}"
                    )

                now = time.monotonic()
                for index in range(capacity):
                    task_addr = task_array + index * TASK_STRIDE
                    task_state = dme.read_byte(task_addr + TASK_STATE_OFFSET)
                    if task_state not in (0, 1, 2):
                        raise StructureError(
                            f"task {index} at 0x{task_addr:08X} "
                            f"has unproven state {task_state}"
                        )
                    allocated = task_state in (1, 2)
                    packed = (
                        dme.read_word(task_addr + TASK_ID_OFFSET)
                        if allocated
                        else None
                    )
                    state = states[index]

                    if task_state != state["task_state"]:
                        transition_packed = packed if allocated else state["packed"]
                        details = "packed=None"
                        if transition_packed is not None:
                            table, message_id = split_packed_id(transition_packed)
                            details = (
                                f"packed=0x{transition_packed:08X} "
                                f"table={table} message_id={message_id}"
                            )
                        log(
                            handle,
                            f"STATE index={index} task=0x{task_addr:08X} "
                            f"transition={state['task_state']}->{task_state} "
                            f"{details}",
                        )

                    newly_allocated = allocated and state["task_state"] == 0
                    id_changed = (
                        allocated
                        and state["task_state"] in (1, 2)
                        and packed != state["packed"]
                    )

                    if newly_allocated or id_changed:
                        table, message_id = split_packed_id(packed)
                        state.update(
                            packed=packed,
                            pending=None,
                            handled=False,
                            opened_at=now,
                        )
                        text = (
                            fight_strings.get(str(message_id))
                            if table == 0
                            else None
                        )
                        event = "OPEN" if newly_allocated else "ID_CHANGE"
                        log(
                            handle,
                            f"{event} index={index} task=0x{task_addr:08X} "
                            f"state={task_state} packed=0x{packed:08X} "
                            f"table={table} message_id={message_id} "
                            f"raw_template={text!r}",
                        )
                        if table == 0 and message_id == MOVE_TEMPLATE_ID:
                            try:
                                state["pending"] = take_substitution_sample()
                                log(
                                    handle,
                                    f"SAMPLE1 index={index} "
                                    f"task=0x{task_addr:08X} "
                                    f"value={state['pending']!r}",
                                )
                            except MessageValidationError as exc:
                                state["handled"] = True
                                log(
                                    handle,
                                    f"MOVE_ABORT index={index} "
                                    f"task=0x{task_addr:08X} reason={exc}",
                                )
                        elif table == 0:
                            speak_direct_message(
                                handle, index, task_addr, message_id, text
                            )
                            state["handled"] = True

                    elif (
                        allocated
                        and not state["handled"]
                        and state["pending"] is not None
                    ):
                        table, message_id = split_packed_id(packed)
                        if table == 0 and message_id == MOVE_TEMPLATE_ID:
                            first = state["pending"]
                            state["handled"] = True
                            try:
                                second = take_substitution_sample()
                                log(
                                    handle,
                                    f"SAMPLE2 index={index} "
                                    f"task=0x{task_addr:08X} value={second!r}",
                                )
                                if second != first:
                                    raise MessageValidationError(
                                        f"two 50ms samples differ: "
                                        f"first={first!r}, second={second!r}"
                                    )

                                (
                                    name_id,
                                    local_name,
                                    suffix_id,
                                    local_suffix,
                                ) = resolver.resolve(second.move_id)
                                name_match = (
                                    normalize_for_comparison(second.live_move_name)
                                    == normalize_for_comparison(local_name)
                                )
                                suffix_match = (
                                    normalize_for_comparison(second.live_suffix)
                                    == normalize_for_comparison(local_suffix)
                                )
                                normalized_live_name = normalize_for_comparison(second.live_move_name)
                                normalized_local_name = normalize_for_comparison(local_name)
                                normalized_live_suffix = normalize_for_comparison(second.live_suffix)
                                normalized_local_suffix = normalize_for_comparison(local_suffix)
                                passed = name_match and suffix_match
                                final_sentence = (
                                    f"{presentation_case(second.nickname)} used "
                                    f"{presentation_case(local_name)}"
                                    f"{local_suffix}"
                                )
                                log(
                                    handle,
                                    f"RESOLUTION index={index} "
                                    f"task=0x{task_addr:08X} state={task_state} "
                                    f"packed=0x{packed:08X} "
                                    f"attacker=0x{second.attacker:08X} "
                                    f"fight_pokemon=0x{second.fight_pokemon:08X} "
                                    f"nickname_addr=0x{second.nickname_address:08X} "
                                    f"raw_nickname={second.nickname!r} "
                                    f"move_id={second.move_id} "
                                    f"live_name={second.live_move_name!r} "
                                    f"live_suffix={second.live_suffix!r} "
                                    f"local_name_id={name_id} "
                                    f"local_name={local_name!r} "
                                    f"local_suffix_id={suffix_id} "
                                    f"local_suffix={local_suffix!r} "
                                    f"normalized_live_name={normalized_live_name!r} "
                                    f"normalized_local_name={normalized_local_name!r} "
                                    f"normalized_live_suffix={normalized_live_suffix!r} "
                                    f"normalized_local_suffix={normalized_local_suffix!r} "
                                    f"final={final_sentence!r} "
                                    f"cross_validation_passed={passed}",
                                )
                                if not passed:
                                    raise MessageValidationError(
                                        "live/local move text disagreement"
                                    )
                                spoke = tolk.speak(final_sentence, interrupt=True)
                                log(
                                    handle,
                                    f"SPOKEN index={index} "
                                    f"task=0x{task_addr:08X} "
                                    f"message_id={message_id} "
                                    f"text={final_sentence!r} result={spoke}",
                                )
                            except MessageValidationError as exc:
                                log(
                                    handle,
                                    f"MOVE_ABORT index={index} "
                                    f"task=0x{task_addr:08X} reason={exc}",
                                )

                    if task_state == 0 and state["task_state"] in (1, 2):
                        lifetime_ms = (now - state["opened_at"]) * 1000.0
                        old_packed = state["packed"]
                        table, message_id = split_packed_id(old_packed)
                        log(
                            handle,
                            f"CLOSE index={index} task=0x{task_addr:08X} "
                            f"packed=0x{old_packed:08X} table={table} "
                            f"message_id={message_id} "
                            f"lifetime_ms={lifetime_ms:.1f}",
                        )
                        state.update(
                            packed=None,
                            pending=None,
                            handled=False,
                            opened_at=None,
                        )

                    state["task_state"] = task_state

                time.sleep(POLL_INTERVAL_SEC)

        except KeyboardInterrupt:
            log(handle, "Stopped by operator.")
        except Exception as exc:
            log(handle, f"ABORT: {type(exc).__name__}: {exc}")
            return 1
        finally:
            if speech_loaded:
                try:
                    tolk.unload()
                    log(handle, "Tolk unloaded.")
                except Exception as exc:
                    log(handle, f"WARNING: Tolk unload failed: {exc}")
            try:
                dme.un_hook()
                log(handle, "Un-hooked from Dolphin.")
            except Exception as exc:
                log(handle, f"WARNING: DME unhook failed: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
