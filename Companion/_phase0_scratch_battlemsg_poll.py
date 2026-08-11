"""
Read-only, non-pausing poll of multiple battle-message-ID candidates via
dolphin_memory_engine -- same non-pausing rationale as
_phase0_scratch_msgid_poll.py (no watchpoints, no CPU pauses, normal
game speed/audio throughout).

Candidates, derived by disassembling fightFloorBiosGetFightFloorPtr
(returns the fixed constant 0x804A1730, not a pointer load) and the
fightFloorBios{Get,Set}*MsgId family (each does `addis r3,r3,1` then a
negative-offset lwz/stw -- the net offset from whatever pointer is
passed as r3): if that pointer is the fixed base itself, the resulting
live addresses are:
    0x804AF558  AttackMsgId    (fightFloorBiosGetAttackMsgId,   +0xDE28)
    0x804AF55C  CriticalMsgId  (fightFloorBiosGetCriticalMsgId, +0xDE2C)
    0x804AF560  WazakoukaMsgId (fightFloorBiosGetWazakoukaMsgId,+0xDE30, "kouka"=effectiveness)
    0x804AF564  AppointMsgId   (fightFloorBiosGetAppointMsgId,  +0xDE34)
This is unverified -- the pointer passed to these accessors may not
actually be the fixed base (the null-check on r3 in each accessor
suggests it could be a separate, possibly-null per-battler-slot
pointer instead). Testing directly, read-only, is the fastest way to
find out either way.

Also keeps watching _MsgID (0x804EB284) for continuity/comparison.

Read-only: only dme.hook()/read_word()/un_hook() are ever called.
"""
import sys
import time
import os

import dolphin_memory_engine as dme

CANDIDATES = {
    "_MsgID": 0x804EB284,
    "AttackMsgId": 0x804AF558,
    "CriticalMsgId": 0x804AF55C,
    "WazakoukaMsgId": 0x804AF560,
    "AppointMsgId": 0x804AF564,
}
POLL_INTERVAL_SEC = 0.15

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "battlemsg_poll.log")


def log(f, message):
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{ts}] {message}"
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        log(f, "=== Battle-message-ID candidate poll starting ===")
        log(f, "Watching: " + ", ".join(f"{name}=0x{addr:08X}" for name, addr in CANDIDATES.items()))
        dme.hook()
        if not dme.is_hooked():
            log(f, f"Failed to hook Dolphin. Status: {dme.get_status()}")
            return 1
        log(f, "Hooked successfully. Polling every %.2fs, no pausing." % POLL_INTERVAL_SEC)

        last = {name: None for name in CANDIDATES}
        try:
            while True:
                for name, addr in CANDIDATES.items():
                    try:
                        val = dme.read_word(addr)
                    except Exception as exc:
                        log(f, f"{name}: read error (will retry): {exc}")
                        continue
                    if val != last[name]:
                        log(f, f"{name} (0x{addr:08X}) changed: {last[name]} -> {val} (0x{val:X})")
                        last[name] = val
                time.sleep(POLL_INTERVAL_SEC)
        except KeyboardInterrupt:
            log(f, "Stopped by user (Ctrl+C).")
        finally:
            try:
                dme.un_hook()
                log(f, "Un-hooked cleanly.")
            except Exception as exc:
                log(f, f"WARNING: error un-hooking: {exc}")


if __name__ == "__main__":
    sys.exit(main() or 0)
