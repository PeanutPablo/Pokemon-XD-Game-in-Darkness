"""
Read-only GDB RSP multi-breakpoint trace of the battle command menu.
Sets execution breakpoints on all known menuFight* symbols simultaneously
and logs every hit (which function, register context) so idle-period
activity can be compared against activity from one exact controller press.

SAFETY: same strict allowlist as the other _phase0_scratch_gdb_*.py
scripts. Only ? g p m Z0 z0 c s D are ever sent. No M/X/G/P/qRcmd.
"""
import socket
import sys
import time
import os

sys.path.insert(0, os.path.dirname(__file__))
from _phase0_scratch_gdb_watchpoint import RSPClient

HOST = "127.0.0.1"
PORT = 55555

BREAKPOINTS = {
    0x8001D088: "menuFightMainCtrl",
    0x8001E3E0: "menuFightOpenTop",
    0x8001E36C: "menuFightCloseTop",
    0x8001EBB4: "menuFightSetStatus",
    0x8001EBBC: "menuFightGetStatus",
    0x8001CAC8: "menuFightDrawCmdMsg",
    0x8001CA24: "menuFightDrawNew",
    0x800176DC: "menuFightStatusCtrl",
    0x80017F40: "menuFightCtrlTimer",
    0x8001C868: "menuFightDrawWaza",
    0x8001C758: "menuFightDrawType",
    0x8001C530: "menuFightDrawPP",
    0x8001D9A8: "menuFightOpenTarget",
    0x8001DCC8: "menuFightOpenPokemon",
    0x8001E014: "menuFightOpenWaza",
}

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "gdb_rsp_battlemenu.log")


def log(f, message):
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{ts}] {message}"
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        log(f, "=== GDB RSP battle-menu multi-breakpoint trace ===")
        log(f, f"Connecting to {HOST}:{PORT} ...")
        client = RSPClient(HOST, PORT, timeout=1800)
        log(f, "Connected.")

        stop = client.query("?")
        log(f, f"Initial stop status: {stop}")

        for addr, name in BREAKPOINTS.items():
            resp = client.set_exec_breakpoint(addr)
            log(f, f"set_exec_breakpoint({name} @ 0x{addr:08X}) response: {resp!r}")

        log(f, "Continuing (this un-pauses emulation; boot sequence will need to be re-navigated to a battle).")
        client.cont()

        hit_count = 0
        try:
            while True:
                stop = client.wait_for_stop(timeout=1800)
                hit_count += 1

                gprs = client.read_all_gprs()
                pc = client.read_register(64)
                lr = client.read_register(67)
                name = BREAKPOINTS.get(pc, f"UNKNOWN (0x{pc:08X})")

                log(f, f"=== HIT #{hit_count}: {name} === LR=0x{lr:08X} r3=0x{gprs[3]:08X} r4=0x{gprs[4]:08X} r5=0x{gprs[5]:08X} r1(SP)=0x{gprs[1]:08X}")
                log(f, f"  Full r3-r10: " + " ".join(f"r{i}=0x{gprs[i]:08X}" for i in range(3, 11)))

                client.cont()

        except KeyboardInterrupt:
            log(f, "Stopped by user (Ctrl+C).")
        except (ConnectionError, socket.timeout) as exc:
            log(f, f"Connection ended: {exc}")
        finally:
            for addr, name in BREAKPOINTS.items():
                try:
                    client.remove_exec_breakpoint(addr)
                except Exception as exc:
                    log(f, f"WARNING: could not remove breakpoint at {name}: {exc}")
            log(f, "All breakpoints removed.")
            client.detach()
            log(f, "Detached. Session ended.")


if __name__ == "__main__":
    sys.exit(main() or 0)
