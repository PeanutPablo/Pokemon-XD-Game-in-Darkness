"""
Phase 0F: bounded, read-only validation of the central GSmsg task array.

This is intentionally separate from the confirmed Phase 0D effectiveness
field PoC.  It dynamically resolves the GSmsg manager and its task array,
but accepts only the exact retail-GXXE01 shape established statically:

    *(u32)0x804E8348       -> manager
    manager+0x00           -> task capacity (must be exactly 2)
    manager+0x1C           -> task array
    task stride            -> 0x6C
    task+0x00              -> active byte
    task+0x1C              -> packed message ID

Read-only by construction.  The only dolphin_memory_engine operations used
are hook, is_hooked, get_status, read_byte, read_bytes, read_word, and
un_hook.  No debugger connection or memory-write API is used.
"""

import json
import os
import re
import sys
import time

import dolphin_memory_engine as dme
from cytolk import tolk


MANAGER_ROOT_ADDR = 0x804E8348
STATIC_TASK_CAPACITY = 2  # sole retail call: GSmsgInit(2, 5) at 0x8005C4B0
TASK_STRIDE = 0x6C
TASK_ACTIVE_OFFSET = 0x00
TASK_ID_OFFSET = 0x1C
POLL_INTERVAL_SEC = 0.05

MEM1_START = 0x80000000
MEM1_END = 0x81800000  # exclusive; 24 MiB GameCube MEM1

BASE_DIR = os.path.dirname(__file__)
STRINGS_PATH = os.path.join(
    BASE_DIR, "_dialogue_extraction", "fight_common_strings.json"
)
LOG_PATH = os.path.join(BASE_DIR, "logs", "phase0f_nvda_gsmsg_task_poc.log")
PLACEHOLDER_RE = re.compile(r"\[[^\]]+\]")


class StructureError(RuntimeError):
    pass


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


def valid_mem1_pointer(address, required_size=1):
    return (
        isinstance(address, int)
        and address != 0
        and address % 4 == 0
        and MEM1_START <= address
        and required_size >= 0
        and address + required_size <= MEM1_END
    )


def read_u16_be(address):
    raw = dme.read_bytes(address, 2)
    if raw is None or len(raw) != 2:
        raise StructureError(f"short u16 read at 0x{address:08X}")
    return int.from_bytes(raw, "big")


def resolve_structure():
    manager_before = dme.read_word(MANAGER_ROOT_ADDR)
    if not valid_mem1_pointer(manager_before, 0x24):
        raise StructureError(
            f"invalid manager pointer 0x{manager_before:08X} "
            f"read from 0x{MANAGER_ROOT_ADDR:08X}"
        )

    capacity = read_u16_be(manager_before)
    if capacity != STATIC_TASK_CAPACITY:
        raise StructureError(
            f"task capacity {capacity} is not the statically verified "
            f"retail capacity {STATIC_TASK_CAPACITY}"
        )

    task_array = dme.read_word(manager_before + 0x1C)
    array_size = capacity * TASK_STRIDE
    if not valid_mem1_pointer(task_array, array_size):
        raise StructureError(
            f"invalid task-array pointer/range: pointer=0x{task_array:08X}, "
            f"size=0x{array_size:X}"
        )

    manager_after = dme.read_word(MANAGER_ROOT_ADDR)
    capacity_after = read_u16_be(manager_before)
    task_array_after = dme.read_word(manager_before + 0x1C)
    if (
        manager_after != manager_before
        or capacity_after != capacity
        or task_array_after != task_array
    ):
        raise StructureError("GSmsg structural values changed while resolving")

    return manager_before, capacity, task_array


def split_packed_id(packed_id):
    return packed_id >> 20, packed_id & 0x000FFFFF


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(STRINGS_PATH, encoding="utf-8") as strings_file:
        fight_strings = json.load(strings_file)

    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        log(handle, "=== Phase 0F GSmsg task-array diagnostic starting ===")
        log(
            handle,
            f"Loaded {len(fight_strings)} demonstrable fight_common IDs from "
            f"{STRINGS_PATH}",
        )
        log(
            handle,
            "Safety: read-only DME operations; capacity must equal 2; "
            "all pointers and the complete task-array range must lie in MEM1.",
        )

        dme.hook()
        if not dme.is_hooked():
            log(handle, f"ABORT: failed to hook Dolphin: {dme.get_status()}")
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
                {"active": False, "task_state": 0, "packed": None, "opened_at": None}
                for _ in range(capacity)
            ]

            log(handle, f"Polling all {capacity} tasks every 50ms.")
            while True:
                current_manager, current_capacity, current_array = resolve_structure()
                if (
                    current_manager != manager
                    or current_capacity != capacity
                    or current_array != task_array
                ):
                    raise StructureError(
                        "GSmsg structure changed after polling began: "
                        f"manager 0x{manager:08X}->0x{current_manager:08X}, "
                        f"capacity {capacity}->{current_capacity}, "
                        f"array 0x{task_array:08X}->0x{current_array:08X}"
                    )

                now = time.monotonic()
                for index in range(capacity):
                    task_addr = task_array + index * TASK_STRIDE
                    active_raw = dme.read_byte(task_addr + TASK_ACTIVE_OFFSET)
                    if active_raw not in (0, 1, 2):
                        raise StructureError(
                            f"task {index} at 0x{task_addr:08X} has "
                            f"unproven state byte {active_raw}"
                        )
                    active = active_raw in (1, 2)
                    packed = dme.read_word(task_addr + TASK_ID_OFFSET) if active else None
                    state = states[index]

                    if active_raw != state["task_state"]:
                        transition_packed = packed if active else state["packed"]
                        if transition_packed is None:
                            transition_details = "packed=None"
                        else:
                            transition_table, transition_id = split_packed_id(transition_packed)
                            transition_details = (
                                f"packed=0x{transition_packed:08X} "
                                f"table={transition_table} message_id={transition_id}"
                            )
                        log(
                            handle,
                            f"STATE index={index} task=0x{task_addr:08X} "
                            f"transition={state['task_state']}->{active_raw} "
                            f"{transition_details}",
                        )

                    if active and not state["active"]:
                        table, message_id = split_packed_id(packed)
                        text = fight_strings.get(str(message_id)) if table == 0 else None
                        source = "fight_common" if text is not None else "ignored/unproven"
                        log(
                            handle,
                            f"OPEN index={index} task=0x{task_addr:08X} "
                            f"packed=0x{packed:08X} table={table} "
                            f"message_id={message_id} source={source} "
                            f"raw_template={text!r}",
                        )
                        state.update(
                            active=True, packed=packed, opened_at=now
                        )
                        if text is not None:
                            unresolved = bool(PLACEHOLDER_RE.search(text))
                            spoke = tolk.speak(text, interrupt=True)
                            log(
                                handle,
                                f"SPOKEN index={index} message_id={message_id} "
                                f"unresolved_template={unresolved} "
                                f"text={text!r} result={spoke}",
                            )

                    elif active and state["active"] and packed != state["packed"]:
                        old_packed = state["packed"]
                        table, message_id = split_packed_id(packed)
                        text = fight_strings.get(str(message_id)) if table == 0 else None
                        source = "fight_common" if text is not None else "ignored/unproven"
                        log(
                            handle,
                            f"ID_CHANGE index={index} task=0x{task_addr:08X} "
                            f"old_packed=0x{old_packed:08X} "
                            f"packed=0x{packed:08X} table={table} "
                            f"message_id={message_id} source={source} "
                            f"raw_template={text!r}",
                        )
                        state["packed"] = packed
                        if text is not None:
                            unresolved = bool(PLACEHOLDER_RE.search(text))
                            spoke = tolk.speak(text, interrupt=True)
                            log(
                                handle,
                                f"SPOKEN index={index} message_id={message_id} "
                                f"unresolved_template={unresolved} "
                                f"text={text!r} result={spoke}",
                            )

                    elif not active and state["active"]:
                        lifetime_ms = (now - state["opened_at"]) * 1000.0
                        old_packed = state["packed"]
                        table, message_id = split_packed_id(old_packed)
                        log(
                            handle,
                            f"CLOSE index={index} task=0x{task_addr:08X} "
                            f"packed=0x{old_packed:08X} table={table} "
                            f"message_id={message_id} lifetime_ms={lifetime_ms:.1f}",
                        )
                        state.update(
                            active=False, packed=None, opened_at=None
                        )

                    state["task_state"] = active_raw

                time.sleep(POLL_INTERVAL_SEC)

        except KeyboardInterrupt:
            log(handle, "Stopped by operator.")
        except (StructureError, Exception) as exc:
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
