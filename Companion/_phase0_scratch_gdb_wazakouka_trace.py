"""
Narrow Z2 write watchpoint on 0x804AF560 (fightFloor_SetWazakoukaMsgId's
resolved destination, when called with a null pointer defaulting to the
fixed FightFloorPtr base 0x804A1730 -- confirmed via static disassembly
this session, not guessed).

Expected sequence, per static analysis: fightSeqWazaExec resets this
field to 0 at the start of move processing (a confirmed `li r4,0` call
site). This script auto-continues past that first hit (logging it as
the expected reset), then captures full evidence -- old/new value, PC,
LR, r3-r10, symbol-resolved containing function -- on the SECOND write,
which would be the real value if one occurs.

SAFETY: same strict allowlist as the other _phase0_scratch_gdb_*.py
scripts. Only ? g p m Z2 z2 c D are ever sent. No M/X/G/P/qRcmd/Z0/z0/s.
No writes of any kind.
"""
import re
import socket
import sys
import os
import time
import bisect

sys.path.insert(0, os.path.dirname(__file__))
from _phase0_scratch_gdb_watchpoint import RSPClient

HOST = "127.0.0.1"
PORT = 55555

WATCH_ADDR = 0x804AF560  # fightFloor_SetWazakoukaMsgId destination (fixed-base resolved)
WATCH_LEN = 4

SYMBOLS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "xd-decomp", "config", "GXXE01", "symbols.txt")

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "gdb_rsp_wazakouka_trace.log")


def log(f, message):
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{ts}] {message}"
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


def load_symbols():
    syms = []
    pattern = re.compile(r'(\S+) = \.(\w+):0x([0-9A-Fa-f]+); // type:(\w+) size:0x([0-9A-Fa-f]+)')
    with open(SYMBOLS_PATH, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = pattern.match(line)
            if m:
                name, sec, addr, typ, size = m.groups()
                syms.append((int(addr, 16), int(size, 16), name, sec, typ))
    syms.sort()
    return syms


def resolve_symbol(syms, addrs_sorted, addr):
    i = bisect.bisect_right(addrs_sorted, addr) - 1
    if i < 0:
        return "?"
    a, sz, name, sec, typ = syms[i]
    if a <= addr < a + sz:
        return f"{name}+0x{addr - a:X}" if addr != a else name
    return f"(gap, nearest-before: {name}+0x{addr - a:X})"


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        log(f, "=== Narrow WazakoukaMsgId (0x804AF560) trace starting ===")
        syms = load_symbols()
        addrs_sorted = [s[0] for s in syms]
        log(f, f"Loaded {len(syms)} symbols.")

        client = RSPClient(HOST, PORT, timeout=600)
        stop = client.query("?")
        log(f, f"Initial stop status: {stop}")

        initial_val = int.from_bytes(client.read_memory(WATCH_ADDR, WATCH_LEN), "big")
        log(f, f"Initial value at 0x{WATCH_ADDR:08X}: {initial_val}")

        resp = client.set_write_watchpoint(WATCH_ADDR, WATCH_LEN)
        log(f, f"set_write_watchpoint response: {resp!r}")

        log(f, "Continuing. Waiting for the reset-to-zero write, then the user's super-effective hit...")
        client.cont()

        hit_count = 0
        last_val = initial_val
        try:
            while True:
                stop = client.wait_for_stop(timeout=600)
                hit_count += 1

                gprs = client.read_all_gprs()
                pc = client.read_register(64)
                lr = client.read_register(67)
                sp = gprs[1]
                new_val = int.from_bytes(client.read_memory(WATCH_ADDR, WATCH_LEN), "big")

                pc_sym = resolve_symbol(syms, addrs_sorted, pc)
                lr_sym = resolve_symbol(syms, addrs_sorted, lr)

                log(f, f"--- HIT #{hit_count} --- old={last_val} new={new_val}")
                log(f, f"  PC=0x{pc:08X} [{pc_sym}]  LR=0x{lr:08X} [{lr_sym}]  SP(r1)=0x{sp:08X}")
                log(f, "  GPRs r3-r10: " + " ".join(f"r{i}=0x{gprs[i]:08X}" for i in range(3, 11)))

                if hit_count == 1 and new_val == 0:
                    log(f, "  (expected reset-to-zero -- auto-continuing)")
                else:
                    log(f, "  *** NON-RESET WRITE CAPTURED ***")
                    if new_val == 20256:
                        log(f, "  *** VALUE EXACTLY MATCHES fight_common.fsys ID 20256 (\"It's super effective!\") ***")

                last_val = new_val
                log(f, "  Continuing...")
                client.cont()

        except KeyboardInterrupt:
            log(f, "Stopped by user (Ctrl+C).")
        except (ConnectionError, socket.timeout) as exc:
            log(f, f"Connection ended: {exc}")
        finally:
            try:
                client.remove_write_watchpoint(WATCH_ADDR, WATCH_LEN)
                log(f, "Watchpoint removed.")
            except Exception as exc:
                log(f, f"WARNING: could not remove watchpoint cleanly: {exc}")
            client.detach()
            log(f, "Detached. Session ended.")


if __name__ == "__main__":
    sys.exit(main() or 0)
