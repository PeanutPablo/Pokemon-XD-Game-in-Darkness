"""
Read-only GDB Remote Serial Protocol client for investigating the writer(s)
of guest address 0x804FFCEF via Dolphin's built-in GDB stub (GDBPort=55555
in Dolphin.ini, localhost-only per Windows Firewall inbound block).

SAFETY: this client implements an explicit ALLOWLIST of outgoing packet
types. No function anywhere in this file sends M, X, G, or P (memory-write
or register-write) packets, and no monitor/qRcmd commands are sent. The
watchpoint is a WRITE watchpoint (Z2) on the target, which the stub itself
supports removing (z2) -- no memory is ever written by this client.
Execution breakpoints (Z0/z0) and single-step (s) are execution-control
only -- they do not write memory or registers either.

Allowed outgoing packet types: ? g p m Z0 z0 Z2 z2 c s D qSupported
Prohibited (never implemented, not just unused): M X G P qRcmd

Connects only to 127.0.0.1:55555 (loopback; the GDB stub itself binds
0.0.0.0, mitigated by a Windows Firewall inbound block rule on that port).
"""
import socket
import sys
import time
import os

HOST = "127.0.0.1"
PORT = 55555
WATCH_ADDR = 0x804E84CC  # gLastSelectedIndex (.sdata, confirmed real named static global, size 0x4)
WATCH_LEN = 4

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "gdb_rsp_watchpoint_glastselectedindex_controlled.log")


def log(f, message):
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{ts}] {message}"
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


class RSPClient:
    def __init__(self, host, port, timeout=60):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)

    def _checksum(self, data: bytes) -> int:
        return sum(data) % 256

    def _send_packet(self, data: str):
        payload = data.encode("ascii")
        pkt = b"$" + payload + b"#" + f"{self._checksum(payload):02x}".encode("ascii")
        self.sock.sendall(pkt)
        # Wait for +/- ack from the stub.
        ack = self.sock.recv(1)
        if ack == b"-":
            self.sock.sendall(pkt)
            self.sock.recv(1)

    def _recv_byte(self):
        b = self.sock.recv(1)
        if not b:
            raise ConnectionError("Dolphin GDB stub closed the connection")
        return b

    def _read_packet(self, timeout=None):
        if timeout is not None:
            self.sock.settimeout(timeout)
        # Skip to the next '$'
        while True:
            c = self._recv_byte()
            if c == b"$":
                break
        raw = b""
        while True:
            c = self._recv_byte()
            if c == b"#":
                break
            if c == b"*":
                # Run-length encoding: next byte encodes repeat count of the
                # PRECEDING character. count = byte - 29.
                rep_byte = self._recv_byte()
                count = rep_byte[0] - 29
                raw += raw[-1:] * count
            else:
                raw += c
        _checksum_hex = self._recv_byte() + self._recv_byte()
        # Ack receipt.
        self.sock.sendall(b"+")
        return raw.decode("ascii", errors="replace")

    def query(self, cmd: str, timeout=None) -> str:
        self._send_packet(cmd)
        return self._read_packet(timeout=timeout)

    def wait_for_stop(self, timeout=None) -> str:
        """Blocks until a stop-reply packet (from a prior 'c') arrives."""
        return self._read_packet(timeout=timeout)

    # --- Allowlisted read-only operations ---

    def read_memory(self, addr: int, length: int) -> bytes:
        resp = self.query(f"m{addr:x},{length:x}")
        # A real GDB RSP error reply is always exactly "E" + 2 hex digits
        # (3 chars total). A successful read is `length*2` hex chars, which
        # can legitimately start with the digit 'E' (e.g. a byte 0xE0-0xEF)
        # -- checking startswith("E") alone false-positives on those.
        if resp.startswith("E") and len(resp) <= 3:
            raise RuntimeError(f"read_memory error response: {resp}")
        return bytes.fromhex(resp)

    def read_register(self, reg_id: int) -> int:
        resp = self.query(f"p{reg_id:x}")
        if resp.startswith("E") or not resp:
            raise RuntimeError(f"read_register({reg_id}) error response: {resp!r}")
        return int(resp, 16)

    def read_all_gprs(self) -> list:
        resp = self.query("g")
        # 32 GPRs * 8 hex chars each, big-endian hex already.
        return [int(resp[i:i + 8], 16) for i in range(0, 256, 8)]

    def set_write_watchpoint(self, addr: int, length: int) -> str:
        return self.query(f"Z2,{addr:x},{length:x}")

    def remove_write_watchpoint(self, addr: int, length: int) -> str:
        return self.query(f"z2,{addr:x},{length:x}")

    def set_exec_breakpoint(self, addr: int) -> str:
        return self.query(f"Z0,{addr:x},4")

    def remove_exec_breakpoint(self, addr: int) -> str:
        return self.query(f"z0,{addr:x},4")

    def single_step(self):
        """Sends single-step. Does NOT wait for a reply -- caller must
        separately call wait_for_stop()."""
        self._send_packet("s")

    def cont(self):
        """Sends continue. Does NOT wait for a reply -- caller must
        separately call wait_for_stop()."""
        self._send_packet("c")

    def detach(self):
        try:
            self._send_packet("D")
        except Exception:
            pass
        self.sock.close()


# --- Minimal PowerPC store-instruction decoder ---
# Covers the D-form and X-form integer store instructions -- enough to
# identify which instruction near a reported PC actually performed a
# byte/halfword/word store, and to what effective address.

D_FORM_STORES = {
    36: "stw", 37: "stwu",
    38: "stb", 39: "stbu",
    44: "sth", 45: "sthu",
}
X_FORM_STORES = {
    151: "stwx", 183: "stwux",
    215: "stbx", 247: "stbux",
    407: "sthx", 439: "sthux",
}


def decode_instruction(word: int) -> str:
    opcode = (word >> 26) & 0x3F
    rS = (word >> 21) & 0x1F
    rA = (word >> 16) & 0x1F

    if opcode in D_FORM_STORES:
        mnem = D_FORM_STORES[opcode]
        d = word & 0xFFFF
        if d >= 0x8000:
            d -= 0x10000
        return f"{mnem} r{rS}, {d}(r{rA})"

    if opcode == 31:
        xo = (word >> 1) & 0x3FF
        if xo in X_FORM_STORES:
            mnem = X_FORM_STORES[xo]
            rB = (word >> 11) & 0x1F
            return f"{mnem} r{rS}, r{rA}, r{rB}"

    return f".long 0x{word:08X}"


def effective_address_if_store(word: int, gprs: list):
    """Returns (addr, mnemonic_text) if `word` is a store instruction whose
    effective address can be computed from `gprs`, else None."""
    opcode = (word >> 26) & 0x3F
    rA = (word >> 16) & 0x1F
    if opcode in D_FORM_STORES:
        d = word & 0xFFFF
        if d >= 0x8000:
            d -= 0x10000
        base = gprs[rA] if rA != 0 else 0
        addr = (base + d) & 0xFFFFFFFF
        return addr, decode_instruction(word)
    if opcode == 31:
        xo = (word >> 1) & 0x3FF
        if xo in X_FORM_STORES:
            rB = (word >> 11) & 0x1F
            base = gprs[rA] if rA != 0 else 0
            addr = (base + gprs[rB]) & 0xFFFFFFFF
            return addr, decode_instruction(word)
    return None


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        log(f, "=== GDB RSP watchpoint session starting ===")
        log(f, f"Connecting to {HOST}:{PORT} ...")
        client = RSPClient(HOST, PORT)
        log(f, "Connected.")

        # CPU boots paused when the stub is active -- query stop reason.
        stop = client.query("?")
        log(f, f"Initial stop status: {stop}")

        # Confirm current value at the candidate address BEFORE anything else.
        initial_val = client.read_memory(WATCH_ADDR, WATCH_LEN)
        log(f, f"Initial value at 0x{WATCH_ADDR:08X}: {initial_val.hex()} ({int.from_bytes(initial_val, 'big')})")

        # Set the write watchpoint.
        resp = client.set_write_watchpoint(WATCH_ADDR, WATCH_LEN)
        log(f, f"set_write_watchpoint response: {resp!r}")
        if resp != "OK":
            log(f, "WARNING: watchpoint may not have been set successfully.")

        log(f, "Sending continue to un-pause emulation (CPU boots paused under the stub).")
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
                cr = client.read_register(66)
                ctr = client.read_register(68)
                xer = client.read_register(69)
                sp = gprs[1]

                new_val = client.read_memory(WATCH_ADDR, WATCH_LEN)

                log(f, f"  PC=0x{pc:08X}  LR=0x{lr:08X}  SP(r1)=0x{sp:08X}  CR=0x{cr:08X}  CTR=0x{ctr:08X}  XER=0x{xer:08X}")
                log(f, f"  GPRs: " + " ".join(f"r{i}=0x{v:08X}" for i, v in enumerate(gprs)))
                if WATCH_LEN >= 8:
                    slots = " ".join(f"[{i}]=0x{int.from_bytes(new_val[i*2:i*2+2],'big'):04X}" for i in range(WATCH_LEN // 2))
                    log(f, f"  New values (array slots): {slots}")
                else:
                    log(f, f"  New value at watch addr: {new_val.hex()} ({int.from_bytes(new_val, 'big')})")

                # Disassembly window: PC-16 to PC+16 (4 instructions before, 4 after).
                window_start = pc - 16
                raw = client.read_memory(window_start, 32)
                log(f, "  Disassembly window:")
                writer_found = False
                for i in range(0, 32, 4):
                    addr = window_start + i
                    word = int.from_bytes(raw[i:i+4], "big")
                    text = decode_instruction(word)
                    marker = "  <-- PC" if addr == pc else ""
                    ea_info = effective_address_if_store(word, gprs)
                    ea_marker = ""
                    if ea_info is not None:
                        ea_addr, _ = ea_info
                        if ea_addr == WATCH_ADDR:
                            ea_marker = f"  <-- WRITES TO WATCH ADDR (effective addr 0x{ea_addr:08X})"
                            writer_found = True
                        else:
                            ea_marker = f"  (store, effective addr 0x{ea_addr:08X})"
                    log(f, f"    0x{addr:08X}: 0x{word:08X}  {text}{marker}{ea_marker}")

                if not writer_found:
                    log(f, "  NOTE: no instruction in the +/-16 byte window had an effective address matching the watch address. The true writer may be further away, or PC may not be adjacent to the write as assumed -- widen the window if this recurs.")

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
