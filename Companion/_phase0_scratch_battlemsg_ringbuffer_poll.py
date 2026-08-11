"""
Read-only, non-pausing poll of the battle-message ring buffer discovered
via live snapshot diffing. No watchpoints, no CPU pauses -- game runs at
full normal speed/audio throughout.

Discovered structure (from two independent live before/after snapshot
diffs around the FightFloorPtr neighborhood, 0x80490000-0x804D0000):
  - LogEntryCounter (0x804A16FC, 4 bytes): monotonically increasing
    sequence number, one new ring-buffer record per battle-log event.
  - Ring buffer: fixed-size 0x30-byte records, one per sequence number,
    stride exactly 0x30 bytes/record (verified across two separate
    moves spanning sequence numbers 0xE-0x17 with zero deviation).
  - Anchor: sequence number 0x17 corresponds to record (seq-field)
    address 0x804AFEB4. General formula (untested outside the observed
    range -- may need re-anchoring if the buffer wraps):
        seq_field_addr(seq) = 0x804AFEB4 + (seq - 0x17) * 0x30
  - Within a record, relative to its own seq-field address:
        type_field  = seq_field_addr - 0x1C
        msgid_field = seq_field_addr - 0x0C
    Only entries with type_field == 0x13 have carried a non-zero,
    plausible message ID in the msgid_field so far (0x151, 0x59, 0xBC
    all confirmed this way against two independent moves). Other type
    values (0xB, 0xE, 0xF, 0xD, ...) are presumed to be non-text log
    events (animation/state-change bookkeeping) -- not yet identified
    individually.

Read-only: only dme.hook()/read_word()/un_hook() are ever called.
"""
import sys
import time
import os

import dolphin_memory_engine as dme

LOG_COUNTER_ADDR = 0x804A16FC
ANCHOR_SEQ = 0x17
ANCHOR_ADDR = 0x804AFEB4
RECORD_STRIDE = 0x30
TYPE_OFFSET = -0x1C
MSGID_OFFSET = -0x0C
TEXT_MESSAGE_TYPE = 0x13

POLL_INTERVAL_SEC = 0.1

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "battlemsg_ringbuffer_poll.log")


def log(f, message):
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{ts}] {message}"
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


def seq_field_addr(seq):
    return (ANCHOR_ADDR + (seq - ANCHOR_SEQ) * RECORD_STRIDE) & 0xFFFFFFFF


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        log(f, "=== Battle-message ring-buffer poll starting ===")
        dme.hook()
        if not dme.is_hooked():
            log(f, f"Failed to hook Dolphin. Status: {dme.get_status()}")
            return 1
        log(f, "Hooked successfully. Polling every %.2fs, no pausing." % POLL_INTERVAL_SEC)

        last_seq = None
        try:
            while True:
                try:
                    seq = dme.read_word(LOG_COUNTER_ADDR)
                except Exception as exc:
                    log(f, f"read error (will retry): {exc}")
                    time.sleep(0.5)
                    continue

                if seq != last_seq:
                    if last_seq is None:
                        log(f, f"Initial LogEntryCounter: {seq} (0x{seq:X})")
                    else:
                        # Report every new entry between last_seq+1 .. seq inclusive,
                        # in case multiple entries landed between polls.
                        for s in range(last_seq + 1, seq + 1):
                            addr = seq_field_addr(s)
                            type_addr = (addr + TYPE_OFFSET) & 0xFFFFFFFF
                            msgid_addr = (addr + MSGID_OFFSET) & 0xFFFFFFFF
                            try:
                                type_val = dme.read_word(type_addr)
                                msgid_val = dme.read_word(msgid_addr)
                            except Exception as exc:
                                log(f, f"  seq {s}: read error: {exc}")
                                continue
                            tag = "TEXT MESSAGE" if type_val == TEXT_MESSAGE_TYPE else "other event"
                            log(f, f"  seq {s} (record @0x{addr:08X}): type=0x{type_val:X} [{tag}] msgid=0x{msgid_val:X} ({msgid_val})")
                    last_seq = seq
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
