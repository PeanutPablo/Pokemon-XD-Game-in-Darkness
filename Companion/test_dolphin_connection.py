"""
Diagnostic only: attempts to hook onto a running Dolphin process using
dolphin-memory-engine. Reports whether Dolphin was found and whether
attachment succeeded.

This script deliberately does NOT:
    - read any game memory address
    - write to memory under any circumstances
    - assume any particular game is running

It only exercises hook() / is_hooked() / get_status() / un_hook().

Run with (or without) Dolphin running:
    Companion\\.venv\\Scripts\\python.exe Companion\\test_dolphin_connection.py
"""

import sys

import dolphin_memory_engine as dme

STATUS_MESSAGES = {
    "hooked": "Attached successfully. Dolphin is running with emulation active.",
    "notRunning": "Dolphin was not found running on this system.",
    "noEmu": "Dolphin is running, but no game/emulation is currently active.",
    "unHooked": "Not attached (no hook attempt has succeeded yet).",
}


def main() -> int:
    try:
        dme.hook()
    except Exception as exc:
        print("ERROR: hook() raised an unexpected exception.")
        print(f"       Underlying error: {exc}")
        return 1

    try:
        status = dme.get_status()
        status_name = status.name
        message = STATUS_MESSAGES.get(status_name, f"Unrecognized status: {status_name}")

        print(f"DolphinStatus: {status_name}")
        print(message)

        hooked = dme.is_hooked()
        print(f"is_hooked(): {hooked}")

        if hooked:
            print("Result: Dolphin found AND attachment succeeded.")
            return 0
        elif status_name == "notRunning":
            print("Result: Dolphin not found. This is expected — Dolphin is not installed/running yet.")
            return 0
        elif status_name == "noEmu":
            print("Result: Dolphin found, but no game is running, so attachment did not complete.")
            return 0
        else:
            print("Result: Dolphin was not successfully attached to.")
            return 0

    finally:
        # Always release the hook cleanly, even if nothing was attached.
        try:
            dme.un_hook()
            print("un_hook() called; connection released cleanly.")
        except Exception as exc:
            print(f"WARNING: error while un-hooking: {exc}")


if __name__ == "__main__":
    sys.exit(main())
