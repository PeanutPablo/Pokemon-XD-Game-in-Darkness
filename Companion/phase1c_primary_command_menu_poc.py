"""Phase 1C: read-only primary battle-command highlight diagnostic.

Vanilla US Pokemon XD (GXXE01 Rev 0) only.  This deliberately remains
separate from the production battle narrator and all Phase 0 diagnostics.
"""

import os
import sys
import time

import dolphin_memory_engine as dme
from cytolk import tolk


MEM1_START = 0x80000000
MEM1_END = 0x81800000
WINDOW_MANAGER = 0x80445A68
LIST_HEAD_OFFSET = 0x10
WORK_MIN_SIZE = 0xBA
MAX_WINDOWS = 64
PRIMARY_MENU_IDS = {58, 142}
POLL_SECONDS = 0.05
IDLE_REPORT_SECONDS = 2.0
LOG_PATH = "Companion/logs/phase1c_primary_command_menu.log"

COMMANDS = {
    0: (300, "Fight"),
    1: (302, "Pokémon"),
    2: (304, "Item"),
    3: (306, "Call"),
}


class ValidationError(RuntimeError):
    pass


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
            f"{label}: invalid range 0x{address:08X}+0x{size:X}"
        )
    data = dme.read_bytes(address, size)
    if data is None or len(data) != size:
        raise ValidationError(f"{label}: short read")
    return bytes(data)


def u16(address, label):
    return int.from_bytes(read_bytes(address, 2, label), "big")


def s16(address, label):
    value = u16(address, label)
    return value - 0x10000 if value & 0x8000 else value


def u32(address, label):
    return int.from_bytes(read_bytes(address, 4, label, 4), "big")


def find_primary_menu():
    pointer = u32(WINDOW_MANAGER + LIST_HEAD_OFFSET, "window-list head")
    seen = set()
    for _ in range(MAX_WINDOWS):
        if pointer == 0:
            return None
        if pointer in seen:
            raise ValidationError("window list contains a cycle")
        if not valid_range(pointer, WORK_MIN_SIZE, 4):
            raise ValidationError(f"invalid window-work pointer 0x{pointer:08X}")
        seen.add(pointer)
        menu_id = u32(pointer + 0x04, "window menu ID")
        if menu_id in PRIMARY_MENU_IDS:
            return pointer, menu_id
        pointer = u32(pointer + 0x10, "next window-work")
    raise ValidationError("window list exceeds static safety bound")


def sample_selection(work):
    # Read twice to reject a node being closed/reused during this poll.
    menu_before = u32(work + 0x04, "menu ID before sample")
    base = s16(work + 0x9C, "cursor base")
    cursor = s16(work + 0x9E, "cursor index")
    menu_after = u32(work + 0x04, "menu ID after sample")
    if menu_before != menu_after or menu_after not in PRIMARY_MENU_IDS:
        raise ValidationError("menu changed during sample")
    logical = base + cursor
    if logical not in COMMANDS:
        raise ValidationError(
            f"invalid primary cursor base={base} cursor={cursor} total={logical}"
        )
    item_id, label = COMMANDS[logical]
    return menu_after, base, cursor, logical, item_id, label


def log_line(handle, text):
    stamp = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{stamp}] {text}"
    print(line, flush=True)
    handle.write(line + "\n")
    handle.flush()


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    dme.hook()
    if not dme.is_hooked():
        print("ERROR: Dolphin is not available.")
        return 1
    try:
        tolk.load()
        if not tolk.is_loaded() or tolk.detect_screen_reader() is None:
            print("ERROR: NVDA or another supported screen reader is not active.")
            return 1

        last_identity = None
        last_logical = None
        idle_since = None
        idle_reported = False
        with open(LOG_PATH, "a", encoding="utf-8") as log:
            log_line(log, "Phase 1C read-only diagnostic started")
            while True:
                if not dme.is_hooked():
                    log_line(log, "Dolphin disconnected; stopping")
                    break
                try:
                    found = find_primary_menu()
                    if found is None:
                        if last_identity is not None:
                            log_line(log, "primary command menu closed; speech re-armed")
                        last_identity = None
                        last_logical = None
                        idle_since = None
                        idle_reported = False
                    else:
                        work, _ = found
                        menu_id, base, cursor, logical, item_id, label = sample_selection(work)
                        identity = (work, menu_id)
                        now = time.monotonic()
                        if identity != last_identity:
                            log_line(
                                log,
                                f"menu opened work=0x{work:08X} menu={menu_id} "
                                f"base={base} cursor={cursor} logical={logical} "
                                f"item={item_id} label={label!r}",
                            )
                            tolk.speak(label, interrupt=True)
                            last_identity = identity
                            last_logical = logical
                            idle_since = now
                            idle_reported = False
                        elif logical != last_logical:
                            log_line(
                                log,
                                f"selection changed work=0x{work:08X} menu={menu_id} "
                                f"base={base} cursor={cursor} logical={logical} "
                                f"item={item_id} label={label!r}",
                            )
                            tolk.speak(label, interrupt=True)
                            last_logical = logical
                            idle_since = now
                            idle_reported = False
                        elif (
                            idle_since is not None
                            and not idle_reported
                            and now - idle_since >= IDLE_REPORT_SECONDS
                        ):
                            log_line(
                                log,
                                f"idle stable for {IDLE_REPORT_SECONDS:.1f}s: "
                                f"work=0x{work:08X} logical={logical} label={label!r}",
                            )
                            idle_reported = True
                except ValidationError as exc:
                    log_line(log, f"sample rejected safely: {exc}")
                time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            tolk.unload()
        except Exception:
            pass
        dme.un_hook()
    return 0


if __name__ == "__main__":
    sys.exit(main())
