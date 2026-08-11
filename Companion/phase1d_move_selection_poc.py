"""Phase 1D: read-only battle move-selection narrator for vanilla GXXE01."""

import os
import re
import sys
import time

import dolphin_memory_engine as dme
from cytolk import tolk

from phase0g_nvda_resolved_move_poc import LocalMoveResolver, presentation_case


MEM1_START = 0x80000000
MEM1_END = 0x81800000
WINDOW_MANAGER = 0x80445A68
MOVE_MENU_IDS = {57, 144, 158, 161}
WORK_SIZE = 0xBC
STATUS_SIZE = 0x48
MAX_WINDOWS = 64
POLL_SECONDS = 0.05
IDLE_REPORT_SECONDS = 2.0
MAX_MOVE_ID = 374
MAX_MOVE_NAME_CHARS = 32
LOG_PATH = os.path.join(
    os.path.dirname(__file__), "logs", "phase1d_move_selection.log"
)


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
            f"{label}: invalid range 0x{address:08X}+0x{size:X}, "
            f"alignment={alignment}"
        )
    data = dme.read_bytes(address, size)
    if data is None or len(data) != size:
        raise ValidationError(f"{label}: short read")
    return bytes(data)


def u32(address, label):
    return int.from_bytes(read_bytes(address, 4, label, 4), "big")


def s16(address, label):
    value = int.from_bytes(read_bytes(address, 2, label), "big")
    return value - 0x10000 if value & 0x8000 else value


def decode_gschar(address, maximum, label):
    # Message-table strings may start at odd byte addresses.
    raw = read_bytes(address, (maximum + 1) * 2, label)
    chars = []
    for offset in range(0, len(raw), 2):
        value = (raw[offset] << 8) | raw[offset + 1]
        if value == 0:
            return "".join(chars)
        if value < 0x20 or value == 0xFFFF:
            raise ValidationError(f"{label}: control value 0x{value:04X}")
        chars.append(chr(value))
    raise ValidationError(f"{label}: no terminator within {maximum} characters")


def normalize(value):
    return re.sub(r"\s+", " ", value).strip().casefold()


def find_move_menu():
    pointer = u32(WINDOW_MANAGER + 0x10, "window-list head")
    seen = set()
    for _ in range(MAX_WINDOWS):
        if pointer == 0:
            return None
        if pointer in seen:
            raise ValidationError("window list contains a cycle")
        if not valid_range(pointer, WORK_SIZE, 4):
            raise ValidationError(f"invalid window-work pointer 0x{pointer:08X}")
        seen.add(pointer)
        menu_id = u32(pointer + 0x04, "window menu ID")
        if menu_id in MOVE_MENU_IDS:
            return pointer, menu_id
        pointer = u32(pointer + 0x10, "next window-work")
    raise ValidationError("window list exceeds static traversal bound")


def sample_selection(work, expected_menu_id, resolver):
    menu_before = u32(work + 0x04, "menu ID before sample")
    status = u32(work + 0xB8, "MENU_WAZA_STATUS pointer")
    if not valid_range(status, STATUS_SIZE, 4):
        raise ValidationError(f"invalid MENU_WAZA_STATUS pointer 0x{status:08X}")

    base = s16(work + 0x9C, "cursor base")
    cursor = s16(work + 0x9E, "cursor offset")
    slot = base + cursor
    if slot < 0 or slot >= 4:
        raise ValidationError(f"invalid move slot base={base} cursor={cursor}")

    record = status + 0x04 + slot * 0x0C
    name_pointer = u32(record + 0x00, "move-name pointer")
    type_pointer = u32(record + 0x04, "move-type pointer")
    move_type_id = int.from_bytes(
        read_bytes(record + 0x08, 2, "move type ID"), "big"
    )
    maximum_pp = read_bytes(record + 0x0A, 1, "maximum PP")[0]
    current_pp = read_bytes(record + 0x0B, 1, "current PP")[0]

    if (
        name_pointer == 0
        and type_pointer == 0
        and move_type_id == 0
        and maximum_pp == 0
        and current_pp == 0
    ):
        raise ValidationError(f"selected slot {slot} is statically empty")
    if name_pointer == 0 or type_pointer == 0:
        raise ValidationError("partially populated move record")
    if maximum_pp == 0 or current_pp > maximum_pp:
        raise ValidationError(
            f"invalid PP current={current_pp} maximum={maximum_pp}"
        )

    acting = u32(status + 0x40, "FightOutPokemon pointer")
    if not valid_range(acting, 8, 4):
        raise ValidationError(f"invalid FightOutPokemon pointer 0x{acting:08X}")
    fight_pokemon = u32(acting + 0x04, "FightPokemon pointer")
    if not valid_range(fight_pokemon, 0x94, 4):
        raise ValidationError(f"invalid FightPokemon pointer 0x{fight_pokemon:08X}")
    # fightPokemonGetPokemonPtr returns the embedded Pokemon at FightPokemon+4.
    # Pokemon::wazas begins at +0x80 and each PokemonWaza is four bytes.
    pokemon = fight_pokemon + 0x04
    pokemon_waza = pokemon + 0x80 + slot * 4
    move_id = int.from_bytes(read_bytes(pokemon_waza, 2, "move ID"), "big")
    pokemon_current_pp = read_bytes(
        pokemon_waza + 0x02, 1, "PokemonWaza current PP"
    )[0]
    if not 1 <= move_id <= MAX_MOVE_ID:
        raise ValidationError(f"move ID {move_id} outside verified range")
    if pokemon_current_pp != current_pp:
        raise ValidationError(
            f"current PP disagreement menu={current_pp} "
            f"PokemonWaza={pokemon_current_pp}"
        )

    live_name = decode_gschar(name_pointer, MAX_MOVE_NAME_CHARS, "live move name")
    try:
        name_id, local_name, _suffix_id, _suffix = resolver.resolve(move_id)
    except Exception as exc:
        raise ValidationError(f"local move lookup failed: {exc}") from exc
    if normalize(live_name) != normalize(local_name):
        raise ValidationError(
            f"name disagreement live={live_name!r} local={local_name!r}"
        )

    menu_after = u32(work + 0x04, "menu ID after sample")
    status_after = u32(work + 0xB8, "status pointer after sample")
    if (
        menu_before != menu_after
        or menu_after != expected_menu_id
        or status_after != status
    ):
        raise ValidationError("menu structure changed during sample")

    return {
        "menu_id": menu_after,
        "status": status,
        "base": base,
        "cursor": cursor,
        "slot": slot,
        "record": record,
        "acting": acting,
        "fight_pokemon": fight_pokemon,
        "pokemon": pokemon,
        "pokemon_waza": pokemon_waza,
        "move_id": move_id,
        "move_type_id": move_type_id,
        "name_pointer": name_pointer,
        "live_name": live_name,
        "name_id": name_id,
        "local_name": local_name,
        "current_pp": current_pp,
        "maximum_pp": maximum_pp,
    }


def log_line(handle, text):
    stamp = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{stamp}] {text}"
    print(line, flush=True)
    handle.write(line + "\n")
    handle.flush()


def describe(sample):
    return (
        f"menu={sample['menu_id']} status=0x{sample['status']:08X} "
        f"base={sample['base']} cursor={sample['cursor']} slot={sample['slot']} "
        f"record=0x{sample['record']:08X} acting=0x{sample['acting']:08X} "
        f"fight_pokemon=0x{sample['fight_pokemon']:08X} "
        f"pokemon=0x{sample['pokemon']:08X} "
        f"pokemon_waza=0x{sample['pokemon_waza']:08X} "
        f"move_id={sample['move_id']} type_id={sample['move_type_id']} "
        f"name_ptr=0x{sample['name_pointer']:08X} "
        f"live_name={sample['live_name']!r} name_msg_id={sample['name_id']} "
        f"local_name={sample['local_name']!r} "
        f"pp={sample['current_pp']}/{sample['maximum_pp']}"
    )


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    resolver = LocalMoveResolver()
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
        last_slot = None
        idle_since = None
        idle_reported = False
        with open(LOG_PATH, "a", encoding="utf-8") as log:
            log_line(log, "Phase 1D read-only diagnostic started")
            while True:
                if not dme.is_hooked():
                    log_line(log, "Dolphin disconnected; stopping")
                    break
                try:
                    found = find_move_menu()
                    if found is None:
                        if last_identity is not None:
                            log_line(log, "move menu closed; speech re-armed")
                        last_identity = None
                        last_slot = None
                        idle_since = None
                        idle_reported = False
                    else:
                        work, menu_id = found
                        sample = sample_selection(work, menu_id, resolver)
                        identity = (work, menu_id, sample["status"])
                        now = time.monotonic()
                        if identity != last_identity or sample["slot"] != last_slot:
                            event = (
                                "menu opened"
                                if identity != last_identity
                                else "selection changed"
                            )
                            log_line(log, f"{event}: work=0x{work:08X} {describe(sample)}")
                            speech = (
                                f"{presentation_case(sample['local_name'])}, "
                                f"{sample['current_pp']} of "
                                f"{sample['maximum_pp']} P P"
                            )
                            spoke = tolk.speak(speech, interrupt=True)
                            log_line(log, f"spoken={speech!r} result={spoke}")
                            last_identity = identity
                            last_slot = sample["slot"]
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
                                f"work=0x{work:08X} {describe(sample)}",
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

