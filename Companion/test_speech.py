"""
Diagnostic only: confirms cytolk can load, detect the active screen reader,
and speak/braille a test message. Does not touch Dolphin or any game memory.

Run with NVDA already running:
    Companion\\.venv\\Scripts\\python.exe Companion\\test_speech.py
"""

import sys

from cytolk import tolk

MESSAGE = "Pokémon XG accessibility companion connected."


def main() -> int:
    try:
        tolk.load()
    except Exception as exc:
        print("ERROR: Tolk failed to load.")
        print(f"       Underlying error: {exc}")
        print("       Check that NVDA (or another Tolk-supported screen reader) is installed.")
        return 1

    try:
        if not tolk.is_loaded():
            print("ERROR: Tolk reported it did not load successfully (is_loaded() is False).")
            return 1

        screen_reader = tolk.detect_screen_reader()
        if screen_reader is None:
            print("ERROR: Tolk loaded, but no active screen reader was detected.")
            print("       Start NVDA and run this script again.")
            return 1

        print(f"Active screen reader detected: {screen_reader}")

        supports_speech = tolk.has_speech()
        supports_braille = tolk.has_braille()
        print(f"Speech supported:  {supports_speech}")
        print(f"Braille supported: {supports_braille}")

        if not supports_speech:
            print("WARNING: the detected screen reader driver does not report speech support.")

        speak_ok = tolk.speak(MESSAGE, interrupt=True)
        print(f"tolk.speak() returned: {speak_ok}")
        if not speak_ok:
            print("WARNING: speak() reported failure (returned False).")

        if supports_braille:
            braille_ok = tolk.braille(MESSAGE)
            print(f"tolk.braille() returned: {braille_ok}")
            if not braille_ok:
                print("WARNING: braille() reported failure (returned False).")
        else:
            print("Skipping braille output: driver does not support it.")

        return 0 if speak_ok else 1

    finally:
        # Always unload Tolk cleanly, even if something above raised or returned early.
        try:
            tolk.unload()
            print("Tolk unloaded cleanly.")
        except Exception as exc:
            print(f"WARNING: error while unloading Tolk: {exc}")


if __name__ == "__main__":
    sys.exit(main())
