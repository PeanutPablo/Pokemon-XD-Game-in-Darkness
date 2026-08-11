"""
Read-only, non-pausing poll of the battle-message staging pair discovered
via live snapshot diff: 0x804A9114 (type, 4 bytes) / 0x804A9118 (msg ID,
4 bytes), plus the ring-buffer entry counter 0x804A16FC for cross-check.
Same no-pause rationale as the other _phase0_scratch_*_poll.py scripts.

Read-only: only dme.hook()/read_word()/un_hook() are ever called.
"""
import sys
import time
import os

import dolphin_memory_engine as dme

CANDIDATES = {
    "MsgStagingType": 0x804A9114,
    "MsgStagingID": 0x804A9118,
    "LogEntryCounter": 0x804A16FC,
    "MinorCounter_AA8FC": 0x804AA8FC,
}
POLL_INTERVAL_SEC = 0.1

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "battlemsg_poll2.log")


def log(f, message):
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{ts}] {message}"
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        log(f, "=== Battle-message staging-pair poll starting ===")
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
