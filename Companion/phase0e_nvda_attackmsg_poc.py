"""
Phase 0E: controlled validation of the attack-message field at 0x804AF558,
using the same read-only NVDA proof-of-concept mechanism confirmed working
in Phase 0D (Companion/phase0d_nvda_wazakouka_poc.py) -- adapted to poll
only this one field, per instruction.

Static grounding (confirmed by disassembly this session, not assumed):
`fightFloor_SetAttackMsgId`/`fightFloorBiosGetAttackMsgId` follow the
identical offset pattern as the already-confirmed Wazakouka field --
offset +0xDE28 from the fixed FightFloorPtr base (0x804A1730, resolved
via fightFloorBiosGetFightFloorPtr when called with a null pointer),
landing at 0x804AF558. Same wrapper structure, same reset-to-zero call
site inside fightSeqWazaExec (li r3,0; li r4,0) as Wazakouka/Critical.
This confirms it is a genuine message-ID slot in the same family --
it does NOT confirm what text it carries. That is deliberately left to
the live test below, per instruction not to assume it holds the move
name or a generic attack sentence.

Everything else is unchanged from Phase 0D: 50ms poll interval, same
dedup/re-arm logic (zero-to-nonzero detection, re-arm only after
observing an exact return to 0), same logging shape, same read-only
dolphin_memory_engine usage (hook/is_hooked/get_status/read_word/
un_hook only -- no write_* call anywhere), same local gitignored
lookup table.
"""
import json
import os
import sys
import time

import dolphin_memory_engine as dme
from cytolk import tolk

FIELD_ADDR = 0x804AF558  # fightFloor_SetAttackMsgId destination (fixed-base resolved)
POLL_INTERVAL_SEC = 0.05

STRINGS_PATH = os.path.join(os.path.dirname(__file__), "_dialogue_extraction", "fight_common_strings.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "phase0e_nvda_attackmsg_poc.log")


def log(f, message):
    now = time.time()
    ts = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now * 1000) % 1000:03d}"
    line = f"[{ts}] {message}"
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    with open(STRINGS_PATH, encoding="utf-8") as sf:
        strings = json.load(sf)

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        log(f, "=== Phase 0E NVDA PoC starting (field 0x{:08X} only) ===".format(FIELD_ADDR))
        log(f, f"Loaded {len(strings)} strings from {STRINGS_PATH}")

        dme.hook()
        if not dme.is_hooked():
            log(f, f"Failed to hook Dolphin. Status: {dme.get_status()}")
            return 1
        log(f, "Hooked to Dolphin (read-only: hook/is_hooked/read_word/un_hook only).")

        try:
            tolk.load()
        except Exception as exc:
            log(f, f"ERROR: Tolk failed to load: {exc}")
            dme.un_hook()
            return 1

        if not tolk.is_loaded():
            log(f, "ERROR: Tolk did not report loaded.")
            dme.un_hook()
            return 1

        screen_reader = tolk.detect_screen_reader()
        if screen_reader is None:
            log(f, "ERROR: no active screen reader detected. Start NVDA and retry.")
            tolk.unload()
            dme.un_hook()
            return 1
        log(f, f"Screen reader detected: {screen_reader}")

        last_value = None
        armed = True
        became_nonzero_at = None
        spoken_count = 0

        log(f, f"Polling every {POLL_INTERVAL_SEC}s. Waiting for one ordinary move-use event...")

        try:
            while True:
                val = dme.read_word(FIELD_ADDR)
                now = time.time()

                if val != last_value:
                    if val != 0 and armed:
                        became_nonzero_at = now
                        text = strings.get(str(val))
                        spoke = False
                        if text is not None:
                            try:
                                spoke = tolk.speak(text, interrupt=True)
                            except Exception as exc:
                                log(f, f"  Tolk speak() raised: {exc}")
                        else:
                            log(f, f"  WARNING: value {val} not found in local string table -- not speaking.")
                        log(f, f"EVENT: old={last_value} new={val} (0x{val:X})  "
                                f"resolved_text={text!r}  spoken={spoke}")
                        armed = False
                        spoken_count += 1
                    elif val == 0 and last_value is not None:
                        lifetime = (now - became_nonzero_at) if became_nonzero_at else None
                        lifetime_str = f"{lifetime*1000:.1f}ms" if lifetime is not None else "unknown"
                        log(f, f"  field returned to 0 (was {last_value}, held for ~{lifetime_str}) -- re-armed")
                        armed = True
                        became_nonzero_at = None
                    last_value = val

                time.sleep(POLL_INTERVAL_SEC)

        except KeyboardInterrupt:
            log(f, "Stopped by user (Ctrl+C).")
        finally:
            try:
                dme.un_hook()
                log(f, "Un-hooked from Dolphin.")
            except Exception as exc:
                log(f, f"WARNING: error un-hooking: {exc}")
            try:
                tolk.unload()
                log(f, "Tolk unloaded.")
            except Exception as exc:
                log(f, f"WARNING: error unloading Tolk: {exc}")
            log(f, f"Total spoken events this session: {spoken_count}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
