"""
Read-only, non-pausing poll of _MsgID (0x804EB284, .sbss, 4 bytes) via
dolphin_memory_engine -- deliberately NOT using the GDB stub/watchpoints
for this test, since watchpoints pause the CPU on every hit, which makes
the game's audio choppy/frame-by-frame and hard to use as a feedback
signal for a blind player. dolphin_memory_engine does a simple periodic
read of live RAM with no pausing at all -- the game keeps running at
full normal speed and normal audio the whole time.

Read-only: only dme.hook()/read_word()/un_hook() are ever called. No
write_* function is called anywhere in this file.
"""
import sys
import time
import os

import dolphin_memory_engine as dme

ADDR = 0x804EB284  # _MsgID
POLL_INTERVAL_SEC = 0.15

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "msgid_poll.log")


def log(f, message):
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{ts}] {message}"
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        log(f, "=== _MsgID non-pausing poll starting ===")
        dme.hook()
        if not dme.is_hooked():
            log(f, f"Failed to hook Dolphin. Status: {dme.get_status()}")
            return 1
        log(f, "Hooked successfully. Polling every %.2fs, no pausing." % POLL_INTERVAL_SEC)

        last = None
        try:
            while True:
                try:
                    val = dme.read_word(ADDR)
                except Exception as exc:
                    log(f, f"read error (will retry): {exc}")
                    time.sleep(0.5)
                    continue
                if val != last:
                    log(f, f"_MsgID changed: {last} -> {val} (0x{val:X})")
                    last = val
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
