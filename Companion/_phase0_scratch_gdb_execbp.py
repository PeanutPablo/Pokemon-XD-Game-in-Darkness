"""
Read-only GDB RSP execution-breakpoint trace of menuTitleGetSelect
(0x800A3194, vanilla US GXXE01 Rev 0), to determine its calling convention
and confirm/refute the static-disassembly hypothesis that it returns a
16-bit selection value from near _menuTitleWork+0x40.

SAFETY: same strict allowlist as _phase0_scratch_gdb_watchpoint.py.
No M/X/G/P packets, no qRcmd. Only ? g p m Z0 z0 c s D.

On each breakpoint hit: single-steps through the whole function (it is
only 6 instructions / 0x18 bytes long) logging registers after every step,
then continues (does not remove the breakpoint) so subsequent calls are
captured too.
"""
import socket
import sys
import time
import os

sys.path.insert(0, os.path.dirname(__file__))
from _phase0_scratch_gdb_watchpoint import RSPClient, decode_instruction

HOST = "127.0.0.1"
PORT = 55555
BP_ADDR = 0x800A3194
BP_LEN = 0x18  # menuTitleGetSelect's full size, per symbols.txt

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "gdb_rsp_execbp_menutitle.log")


def log(f, message):
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{ts}] {message}"
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        log(f, "=== GDB RSP execution-breakpoint trace: menuTitleGetSelect ===")
        log(f, f"Connecting to {HOST}:{PORT} ...")
        client = RSPClient(HOST, PORT, timeout=600)
        log(f, "Connected.")

        stop = client.query("?")
        log(f, f"Initial stop status: {stop}")

        resp = client.set_exec_breakpoint(BP_ADDR)
        log(f, f"set_exec_breakpoint(0x{BP_ADDR:08X}) response: {resp!r}")

        log(f, "Continuing (this un-pauses emulation; boot sequence will need to be re-navigated).")
        client.cont()

        hit_count = 0
        try:
            while True:
                stop = client.wait_for_stop(timeout=600)
                hit_count += 1
                log(f, f"=== BREAKPOINT HIT #{hit_count} === stop packet: {stop}")

                gprs = client.read_all_gprs()
                pc = client.read_register(64)
                lr = client.read_register(67)
                log(f, f"  Entry: PC=0x{pc:08X}  LR=0x{lr:08X}  r3=0x{gprs[3]:08X}  r4=0x{gprs[4]:08X}  r1(SP)=0x{gprs[1]:08X}")
                log(f, f"  Full entry GPRs r3-r10: " + " ".join(f"r{i}=0x{gprs[i]:08X}" for i in range(3, 11)))

                # Single-step through the function, logging each instruction.
                step_num = 0
                while step_num < 10:  # generous cap; function is 6 instructions
                    step_num += 1
                    client.single_step()
                    step_stop = client.wait_for_stop(timeout=30)
                    step_pc = client.read_register(64)
                    step_gprs = client.read_all_gprs()
                    instr_bytes = client.read_memory(step_pc, 4)
                    word = int.from_bytes(instr_bytes, "big")
                    text = decode_instruction(word)
                    log(f, f"  step {step_num}: PC=0x{step_pc:08X}  {text}  r3=0x{step_gprs[3]:08X} r4=0x{step_gprs[4]:08X} r5=0x{step_gprs[5]:08X}")
                    if step_pc < BP_ADDR or step_pc >= BP_ADDR + BP_LEN:
                        log(f, f"  -> stepped outside menuTitleGetSelect's range (now at 0x{step_pc:08X}, likely returned to caller). Stopping trace for this hit.")
                        break

                log(f, "  Continuing to await next call...")
                client.cont()

        except KeyboardInterrupt:
            log(f, "Stopped by user (Ctrl+C).")
        except (ConnectionError, socket.timeout) as exc:
            log(f, f"Connection ended: {exc}")
        finally:
            try:
                client.remove_exec_breakpoint(BP_ADDR)
                log(f, "Breakpoint removed.")
            except Exception as exc:
                log(f, f"WARNING: could not remove breakpoint cleanly: {exc}")
            client.detach()
            log(f, "Detached. Session ended.")


if __name__ == "__main__":
    sys.exit(main() or 0)
