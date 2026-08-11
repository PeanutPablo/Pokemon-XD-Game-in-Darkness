"""Phase 1F second validation: separate direct and poison HP events.

Imports the first successful Phase 1F PoC without modifying it.  Vanilla
GXXE01 only; all Dolphin access remains read-only.
"""

from dataclasses import dataclass
import os
import sys
import time

import dolphin_memory_engine as dme
from cytolk import tolk

import phase1f_hp_damage_poc as hp


LOG_PATH = os.path.join(
    os.path.dirname(__file__),
    "logs",
    "phase1f_hp_poison_separation_poc.log",
)
DIRECT_MESSAGE_ID = 20333
POISON_APPLIED_ID = 20032
POISON_DAMAGE_ID = 20034
SETTLED_SAMPLES = 2
REMAP_FAILSAFE_SECONDS = 5.0


@dataclass
class Pending:
    identity: tuple
    raw_nickname: str
    old_hp: int
    new_hp: int
    max_hp: int
    classification: str
    started: float
    gsmsg_at_start: tuple
    window: int
    allocation: int
    missing_since: float | None = None
    last_snapshot: tuple | None = None
    stable_count: int = 0


def speech_name(raw):
    # Normalize game-generated all-uppercase names. Preserve mixed-case
    # player-created nicknames exactly.
    return raw.title() if raw.isupper() else raw


def log_line(handle, text):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    line = f"[{stamp}.{int(time.time() * 1000) % 1000:03d}] {text}"
    print(line, flush=True)
    handle.write(line + "\n")
    handle.flush()


def status_candidates(battler, windows):
    return hp.correlation_candidates(battler, windows)


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
        completed = []
        seen_task_keys = set()
        message_history = []
        poison_applied = False
        poison_boundary = False
        last_inventory = None
        ready_reported = False

        with open(LOG_PATH, "a", encoding="utf-8") as log:
            log_line(log, "=== Phase 1F direct/poison separation started ===")
            log_line(
                log,
                "audit: imported Phase 1F bounded readers; DME "
                "hook/is_hooked/read_bytes/un_hook only; no writes/GDB",
            )

            while dme.is_hooked():
                tick = time.monotonic()
                try:
                    battlers = hp.sample_battlers()
                    windows = hp.sample_windows()
                    gsmsg = hp.sample_gsmsg_ids()

                    active_keys = set()
                    for index, state, packed, message_id in gsmsg:
                        key = (index, packed)
                        active_keys.add(key)
                        if key not in seen_task_keys:
                            message_history.append((tick, message_id))
                            log_line(
                                log,
                                f"GSMSG open index={index} state={state} "
                                f"packed=0x{packed:08X} message_id={message_id}",
                            )
                            if message_id == POISON_APPLIED_ID:
                                poison_applied = True
                                log_line(log, "POISON application observed")
                            if message_id == POISON_DAMAGE_ID:
                                poison_boundary = True
                                log_line(log, "POISON damage boundary observed")
                    seen_task_keys.intersection_update(active_keys)
                    seen_task_keys.update(active_keys)

                    inventory = (
                        tuple(
                            (b.identity, b.nickname, b.hp, b.max_hp)
                            for b in battlers
                        ),
                        tuple(
                            (
                                w.address,
                                w.allocation,
                                w.nickname,
                                w.max_hp,
                                w.target_hp,
                                w.old_hp,
                                w.duration,
                                w.progress,
                            )
                            for w in windows
                        ),
                    )
                    if inventory != last_inventory:
                        for battler in battlers:
                            log_line(log, "BATTLER " + hp.describe_battler(battler))
                        for window in windows:
                            log_line(
                                log, "STATUS_CANDIDATE " + hp.describe_window(window)
                            )
                        last_inventory = inventory

                    identities = {b.identity for b in battlers}
                    for identity in list(baselines):
                        if identity not in identities:
                            del baselines[identity]

                    for battler in battlers:
                        choices = status_candidates(battler, windows)
                        if battler.identity not in baselines:
                            if len(choices) != 1:
                                continue
                            baselines[battler.identity] = battler.hp
                            log_line(
                                log,
                                f"BASELINE {hp.describe_battler(battler)} "
                                f"window=0x{choices[0].address:08X} "
                                f"allocation=0x{choices[0].allocation:08X}",
                            )

                    if baselines and all(
                        len(status_candidates(b, windows)) == 1
                        for b in battlers
                        if b.identity in baselines
                    ):
                        if not ready_reported:
                            log_line(log, "READY: baselines and mappings valid")
                            ready_reported = True

                    if pending is None:
                        for battler in battlers:
                            if battler.identity not in baselines:
                                continue
                            old_hp = baselines[battler.identity]
                            if battler.hp == old_hp:
                                continue
                            choices = status_candidates(battler, windows)

                            if len(choices) != 1:
                                log_line(
                                    log,
                                    f"INCONCLUSIVE: {battler.nickname!r} HP changed "
                                    f"with {len(choices)} status matches; no speech",
                                )
                                return 2
                            window = choices[0]
                            if window.target_hp != battler.hp:
                                log_line(
                                    log,
                                    "INCONCLUSIVE: logical HP and status target disagree",
                                )
                                return 2
                            if window.old_hp != old_hp:
                                log_line(
                                    log,
                                    f"INCONCLUSIVE: animation old HP {window.old_hp} "
                                    f"does not match settled baseline {old_hp}",
                                )
                                return 2
                            classification = (
                                "poison" if poison_boundary else "direct"
                            )
                            if classification == "poison" and not completed:
                                log_line(
                                    log,
                                    "INCONCLUSIVE: poison reduction preceded a "
                                    "settled direct event",
                                )
                                return 2
                            pending = Pending(
                                battler.identity,
                                battler.nickname,
                                old_hp,
                                battler.hp,
                                battler.max_hp,
                                classification,
                                tick,
                                gsmsg,
                                window.address,
                                window.allocation,
                            )
                            log_line(
                                log,
                                f"EVENT begin class={classification} "
                                f"nickname={battler.nickname!r} "
                                f"identity={battler.identity!r} old={old_hp} "
                                f"new={battler.hp} max={battler.max_hp} "
                                f"window=0x{window.address:08X} "
                                f"allocation=0x{window.allocation:08X} "
                                f"animation_old={window.old_hp} "
                                f"target={window.target_hp} "
                                f"duration={window.duration} "
                                f"progress={window.progress} GSmsg={gsmsg!r}",
                            )
                            break
                    else:
                        battler = next(
                            (
                                item
                                for item in battlers
                                if item.identity == pending.identity
                            ),
                            None,
                        )
                        if battler is None:
                            log_line(
                                log,
                                "STOP: pending battler identity changed or vanished; "
                                "event discarded without speech",
                            )
                            return 4
                        choices = status_candidates(battler, windows)
                        if len(choices) > 1:
                            log_line(
                                log,
                                f"AMBIGUOUS: pending status mapping count "
                                f"{len(choices)}; event suppressed",
                            )
                            return 2
                        if not choices:
                            if pending.missing_since is None:
                                pending.missing_since = tick
                                log_line(
                                    log,
                                    "REMAP waiting: zero current matches during "
                                    "bounded status reconstruction",
                                )
                            elif tick - pending.missing_since >= REMAP_FAILSAFE_SECONDS:
                                log_line(
                                    log,
                                    f"INCONCLUSIVE: no unique status mapping returned "
                                    f"within {REMAP_FAILSAFE_SECONDS:.1f}s; timeout is "
                                    "not settlement evidence",
                                )
                                return 2
                            elapsed = time.monotonic() - tick
                            time.sleep(max(0.0, hp.POLL_SECONDS - elapsed))
                            continue
                        window = choices[0]
                        pending.missing_since = None
                        if (
                            window.address != pending.window
                            or window.allocation != pending.allocation
                        ):
                            log_line(
                                log,
                                f"REMAP old_window=0x{pending.window:08X} "
                                f"new_window=0x{window.address:08X} "
                                f"old_allocation=0x{pending.allocation:08X} "
                                f"new_allocation=0x{window.allocation:08X} "
                                f"evidence=identity{pending.identity!r},"
                                f"copied_nickname={window.nickname!r},"
                                f"max={window.max_hp},target={window.target_hp},"
                                f"logical={battler.hp},old={window.old_hp}",
                            )
                            pending.window = window.address
                            pending.allocation = window.allocation
                        if battler.max_hp != pending.max_hp:
                            log_line(log, "INCONCLUSIVE: maximum HP changed")
                            return 2
                        if battler.hp != pending.new_hp:
                            if window.duration > 0:
                                pending.new_hp = battler.hp
                                log_line(
                                    log,
                                    f"EVENT grouped update class="
                                    f"{pending.classification} new={battler.hp}",
                                )
                            else:
                                log_line(log, "INCONCLUSIVE: second unrelated HP change")
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
                            f"ANIMATION class={pending.classification} "
                            f"window=0x{window.address:08X} "
                            f"allocation=0x{window.allocation:08X} "
                            f"old={window.old_hp} target={window.target_hp} "
                            f"duration={window.duration} "
                            f"progress={window.progress} logical={battler.hp}",
                        )
                        settled = (
                            window.duration == 0
                            and battler.hp == window.target_hp == pending.new_hp
                        )
                        if settled and snapshot == pending.last_snapshot:
                            pending.stable_count += 1
                        elif settled:
                            pending.stable_count = 1
                        else:
                            pending.stable_count = 0
                        pending.last_snapshot = snapshot

                        if pending.stable_count >= SETTLED_SAMPLES:
                            if pending.new_hp >= pending.old_hp:
                                log_line(log, "INCONCLUSIVE: event was not damage")
                                return 2
                            raw_change, rounded_change = hp.round_half_up(
                                pending.old_hp - pending.new_hp,
                                pending.max_hp,
                            )
                            raw_remaining, rounded_remaining = hp.round_half_up(
                                pending.new_hp, pending.max_hp
                            )
                            sentence = (
                                f"{speech_name(pending.raw_nickname)} lost "
                                f"{hp.percent_words(raw_change, rounded_change)}. "
                                f"{hp.percent_words(raw_remaining, rounded_remaining, True)}."
                            )
                            settling = tick - pending.started
                            log_line(
                                log,
                                f"SETTLED class={pending.classification} "
                                f"old={pending.old_hp} new={pending.new_hp} "
                                f"max={pending.max_hp} "
                                f"raw_change_percent={raw_change} "
                                f"rounded_change={rounded_change} "
                                f"raw_remaining_percent={raw_remaining} "
                                f"rounded_remaining={rounded_remaining} "
                                f"settling_seconds={settling:.3f} "
                                f"sentence={sentence!r}",
                            )
                            spoke = tolk.speak(sentence, interrupt=False)
                            log_line(
                                log,
                                f"NVDA class={pending.classification} "
                                f"spoke={spoke} sentence={sentence!r}",
                            )
                            baselines[pending.identity] = pending.new_hp
                            completed.append(pending.classification)
                            if pending.classification == "direct":
                                log_line(
                                    log,
                                    f"BASELINE advanced after direct event to "
                                    f"{pending.new_hp}",
                                )
                                if pending.new_hp == 0:
                                    log_line(
                                        log,
                                        "STOP: direct damage fainted the battler; "
                                        "poison separation unavailable",
                                    )
                                    return 3
                            elif pending.classification == "poison":
                                if not poison_applied:
                                    log_line(
                                        log,
                                        "INCONCLUSIVE: poison damage lacked prior "
                                        "poison-application evidence",
                                    )
                                    return 2
                                log_line(
                                    log,
                                    "SUCCESS: direct and poison damage settled "
                                    "as separate events",
                                )
                                return 0
                            pending = None

                except hp.ValidationError as exc:
                    log_line(log, f"SAMPLE rejected safely: {exc}")

                elapsed = time.monotonic() - tick
                time.sleep(max(0.0, hp.POLL_SECONDS - elapsed))

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
