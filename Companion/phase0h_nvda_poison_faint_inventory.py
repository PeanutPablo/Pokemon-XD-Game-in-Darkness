"""
Phase 0H: bounded, read-only poison/faint battle-message inventory.

Uses Phase 0G's confirmed GSmsg structure and substitution helpers without
modifying Phase 0D, Phase 0F, or Phase 0G.  Every observed fight_common
message is logged with its exact encoded bytes and control opcodes.
"""

import os
import sys
import time
from dataclasses import dataclass

import dolphin_memory_engine as dme
from cytolk import tolk

import _dialogue_extraction_tool as extraction
import phase0g_nvda_resolved_move_poc as phase0g


POLL_INTERVAL_SEC = 0.05
LOG_PATH = os.path.join(
    phase0g.BASE_DIR, "logs", "phase0h_nvda_poison_faint_inventory.log"
)
FIGHT_FSYS_PATH = os.path.join(
    phase0g.EXTRACTION_DIR, "raw", "files", "fight_common.fsys"
)

# Statically and live-verified substitution callbacks from Phase 0G.
VERIFIED_INLINE_CONTROLS = {0x00, 0x0E, 0x0F, 0x28}


class InventoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class MessageRecord:
    message_id: int
    raw: bytes
    tokens: tuple
    template: str
    opcodes: tuple


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


class FightMessageCatalog:
    def __init__(self):
        with open(FIGHT_FSYS_PATH, "rb") as handle:
            files = extraction.parse_fsys(handle.read())
        entry = next(
            item
            for item in files
            if item["type"] == 5 and item["name"] == "fight"
        )
        self.data = entry["data"]
        decoded = extraction.decode_string_table(self.data)
        count = int.from_bytes(self.data[4:6], "big")
        self.records = {}
        for index in range(count):
            table_offset = 0x10 + index * 8
            message_id = (
                int.from_bytes(
                    self.data[table_offset : table_offset + 4], "big"
                )
                & 0x000FFFFF
            )
            string_offset = int.from_bytes(
                self.data[table_offset + 4 : table_offset + 8], "big"
            )
            raw, opcodes = self._read_encoded(string_offset)
            tokens = tuple(decoded[message_id])
            self.records[message_id] = MessageRecord(
                message_id=message_id,
                raw=raw,
                tokens=tokens,
                template=extraction.render_tokens(tokens),
                opcodes=tuple(opcodes),
            )

    def _read_encoded(self, offset):
        if not 0 <= offset < len(self.data):
            raise InventoryError(f"string offset 0x{offset:X} outside table")
        start = offset
        opcodes = []
        while True:
            if offset + 2 > len(self.data):
                raise InventoryError("unterminated string leaves table")
            value = int.from_bytes(self.data[offset : offset + 2], "big")
            offset += 2
            if value == 0:
                break
            if value == 0xFFFF:
                if offset >= len(self.data):
                    raise InventoryError("control opcode leaves table")
                opcode = self.data[offset]
                opcodes.append(opcode)
                offset += 1
                extra = extraction.extra_bytes_for_opcode(opcode)
                if offset + extra > len(self.data):
                    raise InventoryError("control parameters leave table")
                offset += extra
        return self.data[start:offset], opcodes

    def get(self, message_id):
        return self.records.get(message_id)


def snapshot_known_globals():
    return {
        "_ATTACK_MONS": dme.read_word(phase0g.ATTACK_MONS_ADDR),
        "_WAZA_NAME": dme.read_word(phase0g.WAZA_NAME_ADDR),
        "_EV_STR_BUF1": dme.read_word(phase0g.EV_STR_BUF1_ADDR),
    }


def compose_verified(record, sample):
    pieces = []
    for token in record.tokens:
        if token[0] == "char":
            pieces.append(chr(token[1]))
            continue

        _, opcode, _extra = token
        if opcode == 0x00:
            pieces.append(" ")
        elif opcode == 0x0F:
            pieces.append(phase0g.presentation_case(sample.nickname))
        elif opcode == 0x28:
            pieces.append(phase0g.presentation_case(sample.live_move_name))
        elif opcode == 0x0E:
            pieces.append(sample.live_suffix)
        else:
            raise InventoryError(f"unverified opcode 0x{opcode:02X}")
    return " ".join("".join(pieces).split())


def validate_live_local_move(sample, resolver):
    (
        name_id,
        local_name,
        suffix_id,
        local_suffix,
    ) = resolver.resolve(sample.move_id)
    normalized_live_name = phase0g.normalize_for_comparison(
        sample.live_move_name
    )
    normalized_local_name = phase0g.normalize_for_comparison(local_name)
    normalized_live_suffix = phase0g.normalize_for_comparison(
        sample.live_suffix
    )
    normalized_local_suffix = phase0g.normalize_for_comparison(local_suffix)
    passed = (
        normalized_live_name == normalized_local_name
        and normalized_live_suffix == normalized_local_suffix
    )
    return {
        "name_id": name_id,
        "local_name": local_name,
        "suffix_id": suffix_id,
        "local_suffix": local_suffix,
        "normalized_live_name": normalized_live_name,
        "normalized_local_name": normalized_local_name,
        "normalized_live_suffix": normalized_live_suffix,
        "normalized_local_suffix": normalized_local_suffix,
        "passed": passed,
    }


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    catalog = FightMessageCatalog()
    resolver = phase0g.LocalMoveResolver()

    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        log(handle, "=== Phase 0H poison/faint inventory starting ===")
        log(
            handle,
            "Safety: GSmsg-only events; read-only DME; capacity=2; "
            "states limited to 0/1/2; 50ms polling.",
        )

        dme.hook()
        if not dme.is_hooked():
            log(handle, f"ABORT: DME hook failed: {dme.get_status()}")
            return 1

        speech_loaded = False
        try:
            manager, capacity, task_array = phase0g.resolve_structure()
            log(
                handle,
                f"STRUCTURE manager=0x{manager:08X} capacity={capacity} "
                f"task_array=0x{task_array:08X} "
                f"stride=0x{phase0g.TASK_STRIDE:X}",
            )

            tolk.load()
            speech_loaded = bool(tolk.is_loaded())
            if not speech_loaded:
                raise phase0g.StructureError("Tolk did not report loaded")
            reader = tolk.detect_screen_reader()
            if reader is None:
                raise phase0g.StructureError("no active screen reader")
            log(handle, f"Screen reader detected: {reader}")

            states = [
                {
                    "task_state": 0,
                    "packed": None,
                    "opened_at": None,
                    "pending": None,
                    "record": None,
                    "handled": False,
                    "resolution": None,
                }
                for _ in range(capacity)
            ]

            while True:
                current = phase0g.resolve_structure()
                if current != (manager, capacity, task_array):
                    raise phase0g.StructureError(
                        f"GSmsg structure changed: {current!r}"
                    )

                now = time.monotonic()
                for index in range(capacity):
                    task_addr = task_array + index * phase0g.TASK_STRIDE
                    task_state = dme.read_byte(
                        task_addr + phase0g.TASK_STATE_OFFSET
                    )
                    if task_state not in (0, 1, 2):
                        raise phase0g.StructureError(
                            f"task {index} at 0x{task_addr:08X} "
                            f"has unproven state {task_state}"
                        )
                    allocated = task_state in (1, 2)
                    packed = (
                        dme.read_word(task_addr + phase0g.TASK_ID_OFFSET)
                        if allocated
                        else None
                    )
                    state = states[index]

                    if task_state != state["task_state"]:
                        transition_packed = packed if allocated else state["packed"]
                        details = "packed=None"
                        if transition_packed is not None:
                            table, message_id = phase0g.split_packed_id(
                                transition_packed
                            )
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
                        table, message_id = phase0g.split_packed_id(packed)
                        record = catalog.get(message_id) if table == 0 else None
                        state.update(
                            packed=packed,
                            opened_at=now,
                            pending=None,
                            record=record,
                            handled=False,
                            resolution=None,
                        )
                        raw_hex = record.raw.hex(" ").upper() if record else None
                        opcodes = (
                            [f"0x{opcode:02X}" for opcode in record.opcodes]
                            if record
                            else []
                        )
                        template = record.template if record else None
                        event = "OPEN" if newly_allocated else "ID_CHANGE"
                        log(
                            handle,
                            f"{event} index={index} task=0x{task_addr:08X} "
                            f"state={task_state} packed=0x{packed:08X} "
                            f"table={table} message_id={message_id} "
                            f"template={template!r} raw_bytes={raw_hex!r} "
                            f"opcodes={opcodes!r}",
                        )

                        if record is None:
                            state["handled"] = True
                            log(
                                handle,
                                f"UNRESOLVED index={index} "
                                f"task=0x{task_addr:08X} "
                                "reason=not_demonstrably_fight_common",
                            )
                        elif not record.opcodes:
                            spoke = tolk.speak(record.template, interrupt=True)
                            state["handled"] = True
                            state["resolution"] = record.template
                            log(
                                handle,
                                f"SPOKEN index={index} "
                                f"task=0x{task_addr:08X} "
                                f"message_id={message_id} "
                                f"text={record.template!r} result={spoke}",
                            )
                        elif set(record.opcodes) <= VERIFIED_INLINE_CONTROLS:
                            try:
                                state["pending"] = (
                                    phase0g.take_substitution_sample()
                                )
                                log(
                                    handle,
                                    f"SAMPLE1 index={index} "
                                    f"task=0x{task_addr:08X} "
                                    f"value={state['pending']!r}",
                                )
                            except phase0g.MessageValidationError as exc:
                                state["handled"] = True
                                log(
                                    handle,
                                    f"UNRESOLVED index={index} "
                                    f"task=0x{task_addr:08X} "
                                    f"reason={exc} "
                                    f"globals={snapshot_known_globals()!r}",
                                )
                        else:
                            unknown = sorted(
                                set(record.opcodes) - VERIFIED_INLINE_CONTROLS
                            )
                            state["handled"] = True
                            log(
                                handle,
                                f"UNRESOLVED index={index} "
                                f"task=0x{task_addr:08X} "
                                f"unverified_opcodes="
                                f"{[f'0x{x:02X}' for x in unknown]!r} "
                                f"globals={snapshot_known_globals()!r}",
                            )

                    elif (
                        allocated
                        and not state["handled"]
                        and state["pending"] is not None
                    ):
                        first = state["pending"]
                        state["handled"] = True
                        record = state["record"]
                        try:
                            second = phase0g.take_substitution_sample()
                            log(
                                handle,
                                f"SAMPLE2 index={index} "
                                f"task=0x{task_addr:08X} value={second!r}",
                            )
                            if second != first:
                                raise phase0g.MessageValidationError(
                                    "two consecutive 50ms samples differ"
                                )

                            cross = None
                            if any(
                                opcode in (0x0E, 0x28)
                                for opcode in record.opcodes
                            ):
                                cross = validate_live_local_move(
                                    second, resolver
                                )
                                if not cross["passed"]:
                                    raise phase0g.MessageValidationError(
                                        "live/local move text disagreement"
                                    )
                            sentence = compose_verified(record, second)
                            state["resolution"] = sentence
                            log(
                                handle,
                                f"RESOLUTION index={index} "
                                f"task=0x{task_addr:08X} "
                                f"message_id={record.message_id} "
                                f"sample={second!r} cross={cross!r} "
                                f"final={sentence!r}",
                            )
                            spoke = tolk.speak(sentence, interrupt=True)
                            log(
                                handle,
                                f"SPOKEN index={index} "
                                f"task=0x{task_addr:08X} "
                                f"message_id={record.message_id} "
                                f"text={sentence!r} result={spoke}",
                            )
                        except (
                            phase0g.MessageValidationError,
                            InventoryError,
                        ) as exc:
                            log(
                                handle,
                                f"UNRESOLVED index={index} "
                                f"task=0x{task_addr:08X} reason={exc} "
                                f"globals={snapshot_known_globals()!r}",
                            )

                    if task_state == 0 and state["task_state"] in (1, 2):
                        lifetime_ms = (now - state["opened_at"]) * 1000.0
                        old_packed = state["packed"]
                        table, message_id = phase0g.split_packed_id(old_packed)
                        record = state["record"]
                        raw_hex = record.raw.hex(" ").upper() if record else None
                        opcodes = (
                            [f"0x{x:02X}" for x in record.opcodes]
                            if record
                            else []
                        )
                        log(
                            handle,
                            f"CLOSE index={index} task=0x{task_addr:08X} "
                            f"packed=0x{old_packed:08X} table={table} "
                            f"message_id={message_id} "
                            f"lifetime_ms={lifetime_ms:.1f} "
                            f"template="
                            f"{record.template if record else None!r} "
                            f"raw_bytes={raw_hex!r} opcodes={opcodes!r} "
                            f"final={state['resolution']!r}",
                        )
                        state.update(
                            packed=None,
                            opened_at=None,
                            pending=None,
                            record=None,
                            handled=False,
                            resolution=None,
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
