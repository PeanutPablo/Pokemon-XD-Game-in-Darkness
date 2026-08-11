"""
Read-only GDB RSP trace of the battle-message ring buffer, using a Z2
write watchpoint (proven reliable this session -- Z0 execution
breakpoints are confirmed broken in this Dolphin/GDBStub configuration,
per PHASE_0_RESULTS.md) spanning several upcoming ring-buffer slots.

Rather than guessing an ID-to-string offset arithmetically, this script
captures the actual live write: PC, LR, full GPRs, and resolves both PC
and LR against config/GXXE01/symbols.txt so the responsible function and
its caller are identified directly from evidence, not inference.

SAFETY: same strict allowlist as the other _phase0_scratch_gdb_*.py
scripts. Only ? g p m Z2 z2 c D are ever sent. No M/X/G/P/qRcmd/Z0/z0/s.
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

LOG_COUNTER_ADDR = 0x804A16FC
ANCHOR_SEQ = 0x17
ANCHOR_ADDR = 0x804AFEB4
RECORD_STRIDE = 0x30
TYPE_OFFSET = -0x1C
MSGID_OFFSET = -0x0C
SLOTS_TO_WATCH = 10

SYMBOLS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "xd-decomp", "config", "GXXE01", "symbols.txt")

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "gdb_rsp_battlemsg_trace.log")


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


def seq_field_addr(seq):
    return (ANCHOR_ADDR + (seq - ANCHOR_SEQ) * RECORD_STRIDE) & 0xFFFFFFFF


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        log(f, "=== Battle-message ring-buffer TRACE (Z2, symbol-resolved) starting ===")
        syms = load_symbols()
        addrs_sorted = [s[0] for s in syms]
        log(f, f"Loaded {len(syms)} symbols.")

        client = RSPClient(HOST, PORT, timeout=600)
        stop = client.query("?")
        log(f, f"Initial stop status: {stop}")

        counter_bytes = client.read_memory(LOG_COUNTER_ADDR, 4)
        current_seq = int.from_bytes(counter_bytes, "big")
        log(f, f"Current LogEntryCounter: {current_seq} (0x{current_seq:X})")

        watch_start = seq_field_addr(current_seq + 1) + TYPE_OFFSET
        watch_end = seq_field_addr(current_seq + SLOTS_TO_WATCH) + 4
        watch_len = watch_end - watch_start
        log(f, f"Arming Z2 watchpoint over next {SLOTS_TO_WATCH} ring-buffer slots: "
                f"0x{watch_start:08X} - 0x{watch_end:08X} (len 0x{watch_len:X})")

        resp = client.set_write_watchpoint(watch_start, watch_len)
        log(f, f"set_write_watchpoint response: {resp!r}")
        if resp != "OK":
            log(f, "WARNING: watchpoint may not have been set successfully.")

        log(f, "Continuing emulation. Waiting for the user's distinctive battle action...")
        client.cont()

        hit_count = 0
        try:
            while True:
                stop = client.wait_for_stop(timeout=600)
                hit_count += 1
                log(f, f"--- HIT #{hit_count} --- stop packet: {stop}")

                gprs = client.read_all_gprs()
                pc = client.read_register(64)
                lr = client.read_register(67)
                sp = gprs[1]

                pc_sym = resolve_symbol(syms, addrs_sorted, pc)
                lr_sym = resolve_symbol(syms, addrs_sorted, lr)

                log(f, f"  PC=0x{pc:08X} [{pc_sym}]  LR=0x{lr:08X} [{lr_sym}]  SP(r1)=0x{sp:08X}")
                log(f, "  GPRs r3-r10: " + " ".join(f"r{i}=0x{gprs[i]:08X}" for i in range(3, 11)))

                # Dump stack words immediately (before continuing) -- a nested
                # internal call can clobber LR before the trap is serviced, so
                # any saved return addresses on the stack are the only way to
                # recover the true call chain at this exact instant.
                stack_words = client.read_memory(sp, 0x60)
                log(f, "  Stack dump from SP (each word resolved if it looks like a code address):")
                for i in range(0, len(stack_words), 4):
                    word = int.from_bytes(stack_words[i:i+4], "big")
                    off = i
                    note = ""
                    if 0x80000000 <= word < 0x81800000:
                        note = f"  -> {resolve_symbol(syms, addrs_sorted, word)}"
                    log(f, f"    SP+0x{off:02X}: 0x{word:08X}{note}")

                # Re-read the current LogEntryCounter and dump the newest record(s)
                new_seq_bytes = client.read_memory(LOG_COUNTER_ADDR, 4)
                new_seq = int.from_bytes(new_seq_bytes, "big")
                log(f, f"  LogEntryCounter now: {new_seq} (was {current_seq})")

                for s in range(current_seq + 1, new_seq + 1):
                    rec_addr = seq_field_addr(s)
                    type_addr = rec_addr + TYPE_OFFSET
                    msgid_addr = rec_addr + MSGID_OFFSET
                    type_val = int.from_bytes(client.read_memory(type_addr, 4), "big")
                    msgid_val = int.from_bytes(client.read_memory(msgid_addr, 4), "big")
                    log(f, f"    seq {s}: type=0x{type_val:X} msgid=0x{msgid_val:X} ({msgid_val}) "
                            f"[type_addr=0x{type_addr:08X} msgid_addr=0x{msgid_addr:08X}]")

                current_seq = new_seq
                log(f, "  Continuing to catch further entries from the same action...")
                client.cont()

        except KeyboardInterrupt:
            log(f, "Stopped by user (Ctrl+C).")
        except (ConnectionError, socket.timeout) as exc:
            log(f, f"Connection ended: {exc}")
        finally:
            try:
                client.remove_write_watchpoint(watch_start, watch_len)
                log(f, "Watchpoint removed.")
            except Exception as exc:
                log(f, f"WARNING: could not remove watchpoint cleanly: {exc}")
            client.detach()
            log(f, "Detached. Session ended.")


if __name__ == "__main__":
    sys.exit(main() or 0)
