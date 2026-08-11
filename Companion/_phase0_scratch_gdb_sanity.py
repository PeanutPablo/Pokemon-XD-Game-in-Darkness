"""
Sanity check: does an execution breakpoint (Z0) fire at all in this
session? PADRead (0x800BB348, real decompiled source in xd-decomp,
src/dolphin/pad/Pad.c) MUST execute every frame for the game to read
controller input. If this doesn't hit within a few seconds, the
execution-breakpoint mechanism itself is suspect, not the menuFight*
symbol choices.

Read-only: only ? g p Z0 z0 c D are ever sent.
"""
import socket
import sys
import time
import os

sys.path.insert(0, os.path.dirname(__file__))
from _phase0_scratch_gdb_watchpoint import RSPClient

HOST = "127.0.0.1"
PORT = 55555
BP_ADDR = 0x800BB348  # PADRead

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "gdb_rsp_sanity.log")


def log(f, message):
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{ts}] {message}"
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        log(f, "=== Sanity check: execution breakpoint on PADRead ===")
        client = RSPClient(HOST, PORT, timeout=30)
        log(f, "Connected.")

        stop = client.query("?")
        log(f, f"Initial stop status: {stop}")

        resp = client.set_exec_breakpoint(BP_ADDR)
        log(f, f"set_exec_breakpoint(PADRead @ 0x{BP_ADDR:08X}) response: {resp!r}")

        log(f, "Continuing...")
        client.cont()

        try:
            stop = client.wait_for_stop(timeout=10)
            pc = client.read_register(64)
            log(f, f"HIT within 10 seconds! stop={stop} PC=0x{pc:08X}")
            log(f, "CONCLUSION: execution breakpoints DO work. The menuFight* negative results are real.")
        except (ConnectionError, socket.timeout) as exc:
            log(f, f"NO HIT within 10 seconds: {exc}")
            log(f, "CONCLUSION: execution breakpoints may not be firing reliably in this session -- the menuFight* negative results are suspect.")
        finally:
            try:
                client.remove_exec_breakpoint(BP_ADDR)
            except Exception:
                pass
            client.detach()
            log(f, "Detached. Sanity check ended.")


if __name__ == "__main__":
    sys.exit(main() or 0)
