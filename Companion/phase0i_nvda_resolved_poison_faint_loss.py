"""
Phase 0I: bounded, read-only live validation of observed Phase 0H controls.

Separate from and non-modifying of Phases 0D, 0F, 0G, and 0H. GSmsg tasks
are the only event source. Dolphin Memory Engine operations are read-only.
"""

import os
import sys
import time
from dataclasses import dataclass

import dolphin_memory_engine as dme
from cytolk import tolk

import phase0g_nvda_resolved_move_poc as phase0g
import phase0h_nvda_poison_faint_inventory as phase0h


POLL_INTERVAL_SEC = 0.05
LOG_PATH = os.path.join(
    phase0g.BASE_DIR, "logs", "phase0i_nvda_resolved_poison_faint_loss.log"
)

EV_STR_BUF0_ADDR = 0x804EB1F0
EV_STR_BUF2_ADDR = 0x804EB1F8
TSUIKA_MONS_ADDR = 0x804EB208
MY_NAME_ADDR = 0x804EB20C

STAT_MESSAGE_ID = 20243
POISONED_MESSAGE_ID = 20032
LOSS_MESSAGE_ID = 20024
CRITICAL_MESSAGE_ID = 20250

TEXT_MAX_CHARS = 64
PLAYER_NAME_MAX_CHARS = 11


class Phase0IError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActorSample:
    fight_out_pokemon: int
    fight_pokemon: int
    nickname_address: int
    nickname: str


@dataclass(frozen=True)
class StatSample:
    actor: ActorSample
    stat_pointer: int
    magnitude_pointer: int
    direction_pointer: int
    stat: str
    magnitude: str
    direction: str

    def signature(self, task_addr, packed):
        return (
            task_addr,
            packed,
            self.actor.fight_out_pokemon,
            self.actor.fight_pokemon,
            self.actor.nickname,
            self.stat_pointer,
            self.magnitude_pointer,
            self.direction_pointer,
            self.stat,
            self.magnitude,
            self.direction,
        )


@dataclass(frozen=True)
class PoisonSample:
    recipient: ActorSample


@dataclass(frozen=True)
class PlayerNameSample:
    pointer: int
    name: str


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


def read_actor(pointer_global, label):
    fight_out = dme.read_word(pointer_global)
    phase0g.require_pointer(fight_out, 0x08, label, alignment=4)
    fight_pokemon = dme.read_word(fight_out + 0x04)
    phase0g.require_pointer(
        fight_pokemon,
        0x52 + (phase0g.NICKNAME_MAX_CHARS + 1) * 2,
        f"{label}.FightPokemon",
        alignment=4,
    )
    nickname_address = fight_pokemon + 0x52
    nickname = phase0g.decode_live_gschar(
        nickname_address,
        phase0g.NICKNAME_MAX_CHARS,
        f"{label}.nickname",
        alignment=2,
    )
    if not nickname.strip():
        raise phase0g.MessageValidationError(f"{label}: empty nickname")
    return ActorSample(
        fight_out_pokemon=fight_out,
        fight_pokemon=fight_pokemon,
        nickname_address=nickname_address,
        nickname=nickname,
    )


def read_text_pointer(pointer_global, label, maximum=TEXT_MAX_CHARS, alignment=1):
    pointer = dme.read_word(pointer_global)
    value = phase0g.decode_live_gschar(
        pointer, maximum, label, alignment=alignment
    )
    return pointer, value


def take_stat_sample():
    actor = read_actor(phase0g.ATTACK_MONS_ADDR, "_ATTACK_MONS")
    stat_pointer, stat = read_text_pointer(EV_STR_BUF0_ADDR, "_EV_STR_BUF0")
    magnitude_pointer, magnitude = read_text_pointer(
        phase0g.EV_STR_BUF1_ADDR, "_EV_STR_BUF1"
    )
    direction_pointer, direction = read_text_pointer(
        EV_STR_BUF2_ADDR, "_EV_STR_BUF2"
    )
    return StatSample(
        actor=actor,
        stat_pointer=stat_pointer,
        magnitude_pointer=magnitude_pointer,
        direction_pointer=direction_pointer,
        stat=stat,
        magnitude=magnitude,
        direction=direction,
    )


def take_poison_sample():
    return PoisonSample(
        recipient=read_actor(TSUIKA_MONS_ADDR, "_TSUIKA_MONS")
    )


def take_player_name_sample():
    pointer, name = read_text_pointer(
        MY_NAME_ADDR,
        "_MY_NAME",
        maximum=PLAYER_NAME_MAX_CHARS,
        alignment=2,
    )
    if not name.strip():
        raise phase0g.MessageValidationError("_MY_NAME: empty player name")
    return PlayerNameSample(pointer=pointer, name=name)


def normalized(value):
    return phase0g.normalize_for_comparison(value)


def build_stat_crosscheck(sample, catalog):
    stat_ids = tuple(range(20339, 20347))
    magnitude_ids = (20239, 20241, 20380)
    direction_ids = (20240, 20242)

    def matches(value, ids):
        target = normalized(value)
        found = []
        for message_id in ids:
            record = catalog.get(message_id)
            if record is not None and normalized(record.template) == target:
                found.append((message_id, record.template))
        return found

    stat_matches = matches(sample.stat, stat_ids)
    magnitude_matches = matches(sample.magnitude, magnitude_ids)
    direction_matches = matches(sample.direction, direction_ids)
    passed = (
        len(stat_matches) == 1
        and len(magnitude_matches) == 1
        and len(direction_matches) == 1
    )
    return {
        "stat_matches": stat_matches,
        "magnitude_matches": magnitude_matches,
        "direction_matches": direction_matches,
        "normalized_stat": normalized(sample.stat),
        "normalized_magnitude": normalized(sample.magnitude),
        "normalized_direction": normalized(sample.direction),
        "passed": passed,
    }


def compose_stat(sample):
    nickname = phase0g.presentation_case(sample.actor.nickname)
    stat = phase0g.presentation_case(sample.stat)
    words = [f"{nickname}'s", stat]
    if sample.magnitude.strip():
        words.append(sample.magnitude.strip().lower())
    words.append(sample.direction.strip().lower())
    return " ".join(words) + "!"


def compose_poison(sample):
    nickname = phase0g.presentation_case(sample.recipient.nickname)
    return f"{nickname} was poisoned!"


def compose_loss(sample):
    name = phase0g.presentation_case(sample.name)
    return f"{name} is out of usable Pokémon!"


def speak_and_log(handle, index, task_addr, message_id, sentence):
    spoke = tolk.speak(sentence, interrupt=True)
    log(
        handle,
        f"SPOKEN index={index} task=0x{task_addr:08X} "
        f"message_id={message_id} text={sentence!r} result={spoke}",
    )
    return spoke


def snapshot_phase0i_globals():
    return {
        "_ATTACK_MONS": dme.read_word(phase0g.ATTACK_MONS_ADDR),
        "_EV_STR_BUF0": dme.read_word(EV_STR_BUF0_ADDR),
        "_EV_STR_BUF1": dme.read_word(phase0g.EV_STR_BUF1_ADDR),
        "_EV_STR_BUF2": dme.read_word(EV_STR_BUF2_ADDR),
        "_TSUIKA_MONS": dme.read_word(TSUIKA_MONS_ADDR),
        "_MY_NAME": dme.read_word(MY_NAME_ADDR),
    }


def reset_for_message(state, packed, record, now):
    state.update(
        packed=packed,
        opened_at=now,
        record=record,
        pending=None,
        handled=False,
        resolution=None,
        seen_signatures=set(),
    )


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    catalog = phase0h.FightMessageCatalog()
    resolver = phase0g.LocalMoveResolver()

    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        log(handle, "=== Phase 0I resolved poison/faint/loss validation ===")
        log(
            handle,
            "Safety: GSmsg-only events; read-only DME; capacity=2; "
            "states limited to 0/1/2; bounded GSchar; 50ms polling.",
        )

        dme.hook()
        if not dme.is_hooked():
            log(handle, f"ABORT: DME hook failed: {dme.get_status()}")
            return 1

        speech_loaded = False
        stop_requested = False
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
                    "record": None,
                    "pending": None,
                    "handled": False,
                    "resolution": None,
                    "seen_signatures": set(),
                }
                for _ in range(capacity)
            ]

            while not stop_requested:
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
                        reset_for_message(state, packed, record, now)
                        raw_hex = record.raw.hex(" ").upper() if record else None
                        opcodes = (
                            [f"0x{x:02X}" for x in record.opcodes]
                            if record
                            else []
                        )
                        log(
                            handle,
                            f"{'OPEN' if newly_allocated else 'ID_CHANGE'} "
                            f"index={index} task=0x{task_addr:08X} "
                            f"state={task_state} packed=0x{packed:08X} "
                            f"table={table} message_id={message_id} "
                            f"template={record.template if record else None!r} "
                            f"raw_bytes={raw_hex!r} opcodes={opcodes!r}",
                        )

                        if message_id == CRITICAL_MESSAGE_ID:
                            log(
                                handle,
                                f"PASSIVE_CRITICAL index={index} "
                                f"task=0x{task_addr:08X}",
                            )

                        if record is None:
                            state["handled"] = True
                            log(
                                handle,
                                f"UNRESOLVED index={index} "
                                f"task=0x{task_addr:08X} "
                                "reason=not_demonstrably_fight_common",
                            )
                        elif message_id == STAT_MESSAGE_ID:
                            # Continuously sampled below; one allocation can
                            # carry both Attack and Speed substitutions.
                            pass
                        elif message_id == POISONED_MESSAGE_ID:
                            try:
                                state["pending"] = take_poison_sample()
                                log(
                                    handle,
                                    f"SAMPLE1 kind=poison index={index} "
                                    f"task=0x{task_addr:08X} "
                                    f"value={state['pending']!r}",
                                )
                            except phase0g.MessageValidationError as exc:
                                state["handled"] = True
                                log(
                                    handle,
                                    f"UNRESOLVED index={index} "
                                    f"task=0x{task_addr:08X} reason={exc} "
                                    f"globals={snapshot_phase0i_globals()!r}",
                                )
                        elif message_id == LOSS_MESSAGE_ID:
                            try:
                                state["pending"] = take_player_name_sample()
                                log(
                                    handle,
                                    f"SAMPLE1 kind=loss index={index} "
                                    f"task=0x{task_addr:08X} "
                                    f"value={state['pending']!r}",
                                )
                            except phase0g.MessageValidationError as exc:
                                state["handled"] = True
                                log(
                                    handle,
                                    f"UNRESOLVED index={index} "
                                    f"task=0x{task_addr:08X} reason={exc} "
                                    f"globals={snapshot_phase0i_globals()!r}",
                                )
                        elif not record.opcodes:
                            state["resolution"] = record.template
                            state["handled"] = True
                            speak_and_log(
                                handle,
                                index,
                                task_addr,
                                message_id,
                                record.template,
                            )
                        elif set(record.opcodes) <= phase0h.VERIFIED_INLINE_CONTROLS:
                            try:
                                state["pending"] = (
                                    phase0g.take_substitution_sample()
                                )
                                log(
                                    handle,
                                    f"SAMPLE1 kind=verified index={index} "
                                    f"task=0x{task_addr:08X} "
                                    f"value={state['pending']!r}",
                                )
                            except phase0g.MessageValidationError as exc:
                                state["handled"] = True
                                log(
                                    handle,
                                    f"UNRESOLVED index={index} "
                                    f"task=0x{task_addr:08X} reason={exc}",
                                )
                        else:
                            state["handled"] = True
                            unknown = sorted(
                                set(record.opcodes)
                                - phase0h.VERIFIED_INLINE_CONTROLS
                            )
                            log(
                                handle,
                                f"UNRESOLVED index={index} "
                                f"task=0x{task_addr:08X} "
                                f"unverified_opcodes="
                                f"{[f'0x{x:02X}' for x in unknown]!r}",
                            )

                    if allocated and state["record"] is not None:
                        message_id = state["record"].message_id

                        if message_id == STAT_MESSAGE_ID:
                            try:
                                current_sample = take_stat_sample()
                                if state["pending"] != current_sample:
                                    state["pending"] = current_sample
                                    log(
                                        handle,
                                        f"STAT_CANDIDATE index={index} "
                                        f"task=0x{task_addr:08X} "
                                        f"packed=0x{packed:08X} "
                                        f"value={current_sample!r}",
                                    )
                                else:
                                    signature = current_sample.signature(
                                        task_addr, packed
                                    )
                                    if signature not in state["seen_signatures"]:
                                        cross = build_stat_crosscheck(
                                            current_sample, catalog
                                        )
                                        sentence = compose_stat(current_sample)
                                        log(
                                            handle,
                                            f"STAT_STABLE index={index} "
                                            f"task=0x{task_addr:08X} "
                                            f"packed=0x{packed:08X} "
                                            f"raw={current_sample!r} "
                                            f"signature={signature!r} "
                                            f"cross={cross!r} "
                                            f"final={sentence!r}",
                                        )
                                        if not cross["passed"]:
                                            raise phase0g.MessageValidationError(
                                                "stat live/local disagreement"
                                            )
                                        state["seen_signatures"].add(signature)
                                        state["resolution"] = sentence
                                        speak_and_log(
                                            handle,
                                            index,
                                            task_addr,
                                            message_id,
                                            sentence,
                                        )
                            except phase0g.MessageValidationError as exc:
                                log(
                                    handle,
                                    f"STAT_SAMPLE_REJECTED index={index} "
                                    f"task=0x{task_addr:08X} reason={exc} "
                                    f"globals={snapshot_phase0i_globals()!r}",
                                )

                        elif (
                            not state["handled"]
                            and state["pending"] is not None
                        ):
                            first = state["pending"]
                            state["handled"] = True
                            try:
                                if message_id == POISONED_MESSAGE_ID:
                                    second = take_poison_sample()
                                    kind = "poison"
                                elif message_id == LOSS_MESSAGE_ID:
                                    second = take_player_name_sample()
                                    kind = "loss"
                                else:
                                    second = (
                                        phase0g.take_substitution_sample()
                                    )
                                    kind = "verified"
                                log(
                                    handle,
                                    f"SAMPLE2 kind={kind} index={index} "
                                    f"task=0x{task_addr:08X} value={second!r}",
                                )
                                if first != second:
                                    raise phase0g.MessageValidationError(
                                        "two consecutive 50ms samples differ"
                                    )

                                cross = None
                                if message_id == POISONED_MESSAGE_ID:
                                    sentence = compose_poison(second)
                                    signature = (
                                        task_addr,
                                        packed,
                                        second.recipient,
                                    )
                                    cross = {
                                        "nickname_chain_valid": True,
                                        "recipient_pointer": (
                                            second.recipient.fight_out_pokemon
                                        ),
                                        "passed": True,
                                    }
                                elif message_id == LOSS_MESSAGE_ID:
                                    sentence = compose_loss(second)
                                    signature = (
                                        task_addr,
                                        packed,
                                        second.pointer,
                                        second.name,
                                    )
                                    cross = {
                                        "bounded_gschar_max": (
                                            PLAYER_NAME_MAX_CHARS
                                        ),
                                        "passed": True,
                                    }
                                else:
                                    record = state["record"]
                                    if any(
                                        x in (0x0E, 0x28)
                                        for x in record.opcodes
                                    ):
                                        cross = (
                                            phase0h.validate_live_local_move(
                                                second, resolver
                                            )
                                        )
                                        if not cross["passed"]:
                                            raise (
                                                phase0g.MessageValidationError(
                                                    "live/local move "
                                                    "text disagreement"
                                                )
                                            )
                                    sentence = phase0h.compose_verified(
                                        record, second
                                    )
                                    signature = (
                                        task_addr,
                                        packed,
                                        second,
                                    )

                                state["resolution"] = sentence
                                log(
                                    handle,
                                    f"RESOLUTION index={index} "
                                    f"task=0x{task_addr:08X} "
                                    f"message_id={message_id} raw={second!r} "
                                    f"signature={signature!r} "
                                    f"cross={cross!r} final={sentence!r}",
                                )
                                speak_and_log(
                                    handle,
                                    index,
                                    task_addr,
                                    message_id,
                                    sentence,
                                )
                                if message_id == LOSS_MESSAGE_ID:
                                    observed_ms = (
                                        now - state["opened_at"]
                                    ) * 1000.0
                                    log(
                                        handle,
                                        "STOP_SUCCESS battle-loss captured "
                                        f"and spoken observed_lifetime_ms="
                                        f"{observed_ms:.1f}",
                                    )
                                    stop_requested = True
                            except (
                                phase0g.MessageValidationError,
                                phase0h.InventoryError,
                            ) as exc:
                                log(
                                    handle,
                                    f"UNRESOLVED index={index} "
                                    f"task=0x{task_addr:08X} reason={exc} "
                                    f"globals={snapshot_phase0i_globals()!r}",
                                )

                    if task_state == 0 and state["task_state"] in (1, 2):
                        lifetime_ms = (now - state["opened_at"]) * 1000.0
                        old_packed = state["packed"]
                        table, message_id = phase0g.split_packed_id(old_packed)
                        record = state["record"]
                        log(
                            handle,
                            f"CLOSE index={index} task=0x{task_addr:08X} "
                            f"packed=0x{old_packed:08X} table={table} "
                            f"message_id={message_id} "
                            f"lifetime_ms={lifetime_ms:.1f} "
                            f"stable_signatures="
                            f"{len(state['seen_signatures'])} "
                            f"final={state['resolution']!r}",
                        )
                        reset_for_message(state, None, None, None)

                    state["task_state"] = task_state

                    if stop_requested:
                        break

                if not stop_requested:
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
