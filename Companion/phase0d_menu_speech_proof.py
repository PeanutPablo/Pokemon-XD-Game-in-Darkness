"""
Phase 0D read-only speech proof (see Documentation/FIRST_VERTICAL_SLICE.md).

Polls the confirmed title-menu selection byte (0x804FFCEF, vanilla US
GXXE01 Rev 0 only -- see Documentation/PHASE_0_RESULTS.md for the
discovery evidence) and speaks the corresponding label through NVDA/Tolk
when the SELECTED option changes.

Important discovered behavior: this byte does not hold a clean, stable
selection index at all times. Live testing showed it also carries a
highlight/blink-style animation that cycles through unmapped values
(4, and fade-like values approaching 255) between the resting selection
values 0-3. Dedup below is therefore keyed on the last *spoken* (known,
mapped) value, not the last raw byte -- otherwise every blink cycle
back to the same real selection re-triggers speech, which is exactly
the "reads them randomly passively" bug observed in the first live test.

Label table is the user's own recollection of the menu, NOT independently
verified from decoded on-screen text or source. Treat spoken labels as
best-effort, not ground truth, until cross-checked.

Constraints (per FIRST_VERTICAL_SLICE.md Phase 0D):
- Read-only. No dolphin_memory_engine write_* call appears anywhere below.
- Polls conservatively, deduplicates unchanged values.
- Logs raw value, normalized selection, spoken text, and timestamp.
- Provides a manual "repeat current selection" key (R).
- Press Ctrl+C to stop. Never expands into dialogue/battle -- title menu only.
"""
import sys
import time
import msvcrt

import dolphin_memory_engine as dme
from cytolk import tolk

SELECTION_ADDR = 0x804FFCEF
POLL_INTERVAL_SECONDS = 0.15

LABEL_TABLE = {
    0: "New Game",
    1: "Continue",
    2: "VS Battle Mode",
    3: "Exit Game",
}

LOG_PATH = "Companion/logs/phase0d_menu_scan.log"


def log_line(f, message):
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{timestamp}] {message}"
    print(line)
    f.write(line + "\n")
    f.flush()


def main():
    import os
    os.makedirs("Companion/logs", exist_ok=True)

    dme.hook()
    if not dme.is_hooked():
        print("ERROR: could not hook Dolphin. Is it running with the game loaded?")
        return 1

    try:
        tolk.load()
    except Exception as exc:
        print(f"ERROR: Tolk failed to load: {exc}")
        dme.un_hook()
        return 1

    with open(LOG_PATH, "a", encoding="utf-8") as logf:
        try:
            if not tolk.is_loaded():
                print("ERROR: Tolk did not load successfully.")
                return 1

            screen_reader = tolk.detect_screen_reader()
            if screen_reader is None:
                print("ERROR: no active screen reader detected. Start NVDA and retry.")
                return 1

            log_line(logf, f"companion ready (screen reader: {screen_reader})")
            tolk.speak("Companion ready.", interrupt=True)

            last_raw = None
            last_known_index = None  # last value that was actually in LABEL_TABLE
            last_spoken_label = None

            print("Polling. Press R to repeat current selection. Ctrl+C to stop.")

            while True:
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key in (b"r", b"R"):
                        if last_spoken_label is not None:
                            tolk.speak(last_spoken_label, interrupt=True)
                            log_line(logf, f"manual repeat: \"{last_spoken_label}\"")
                        else:
                            tolk.speak("No selection yet.", interrupt=True)

                if not dme.is_hooked():
                    log_line(logf, "lost connection to Dolphin; attempting to reconnect")
                    dme.hook()
                    time.sleep(1.0)
                    continue

                raw = dme.read_byte(SELECTION_ADDR)

                if raw != last_raw:
                    label = LABEL_TABLE.get(raw)
                    if label is not None:
                        # Only speak if this is a genuinely different selection
                        # than the last one we actually spoke -- ignores the
                        # blink/highlight animation revisiting the same value.
                        if raw != last_known_index:
                            tolk.speak(label, interrupt=True)
                            log_line(logf, f"raw={raw} normalized={raw} spoken=\"{label}\"")
                            last_spoken_label = label
                        else:
                            log_line(logf, f"raw={raw} normalized={raw} (same as last known selection, not re-spoken)")
                        last_known_index = raw
                    else:
                        log_line(logf, f"raw={raw} normalized=UNKNOWN (not in label table, not spoken)")
                    last_raw = raw

                time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            log_line(logf, "stopped by user (Ctrl+C)")
        finally:
            try:
                tolk.unload()
            except Exception:
                pass
            dme.un_hook()
            log_line(logf, "un_hook() called; companion stopped cleanly")

    return 0


if __name__ == "__main__":
    sys.exit(main())
