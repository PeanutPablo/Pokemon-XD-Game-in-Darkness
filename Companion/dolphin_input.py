"""Safety-checked, one-action keyboard driver for live Dolphin tests.

Diagnostic tooling only. This module is not imported by the narrator and does
not read or write emulated memory.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import time
from ctypes import wintypes
from pathlib import Path


EXPECTED_EXE = Path(
    r"C:\Users\psych\OneDrive\Desktop\apps\Dolphin-x64\Dolphin.exe"
)
SCAN_CODES = {
    "up": (0x48, True),
    "down": (0x50, True),
    "left": (0x4B, True),
    "right": (0x4D, True),
    "dpad_up": (0x14, False),  # T
    "dpad_down": (0x22, False),  # G
    "dpad_left": (0x21, False),  # F
    "dpad_right": (0x23, False),  # H
    "confirm": (0x2D, False),  # X
    "cancel": (0x2C, False),  # Z
    "start": (0x1C, False),  # Return
}
QUERY_PROCESS = 0x1000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
SW_RESTORE = 9


class DriverError(RuntimeError):
    pass


def _process_path(user32, kernel32, hwnd: int) -> Path:
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    process = kernel32.OpenProcess(QUERY_PROCESS, False, process_id.value)
    if not process:
        raise DriverError("Unable to inspect a candidate process")
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            process, 0, buffer, ctypes.byref(size)
        ):
            raise DriverError("Unable to resolve a candidate executable")
        return Path(buffer.value)
    finally:
        kernel32.CloseHandle(process)


def _game_window(user32, kernel32) -> int:
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    @callback_type
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, len(title))
        if "GXXE01" not in title.value:
            return True
        try:
            executable = _process_path(user32, kernel32, hwnd)
        except DriverError:
            return True
        if executable.resolve() == EXPECTED_EXE.resolve():
            matches.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    if len(matches) != 1:
        raise DriverError(
            f"Expected one visible GXXE01 gameplay window; found {len(matches)}"
        )
    return matches[0]


def send_action(
    action: str, *, hold_ms: int = 100, settle_ms: int = 300
) -> dict:
    if action not in SCAN_CODES:
        raise DriverError(f"Unsupported action: {action}")
    if not 30 <= hold_ms <= 500:
        raise DriverError("Hold duration must be between 30 and 500 ms")
    if not 0 <= settle_ms <= 5000:
        raise DriverError("Settle duration must be between 0 and 5000 ms")
    if not EXPECTED_EXE.is_file():
        raise DriverError(f"Approved Dolphin executable is missing: {EXPECTED_EXE}")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hwnd = _game_window(user32, kernel32)
    previous = user32.GetForegroundWindow()
    user32.ShowWindow(hwnd, SW_RESTORE)
    if not user32.SetForegroundWindow(hwnd):
        raise DriverError("Dolphin could not be brought to the foreground")
    time.sleep(0.15)
    if user32.GetForegroundWindow() != hwnd:
        raise DriverError("Dolphin did not obtain foreground focus")

    scan_code, extended = SCAN_CODES[action]
    flags = KEYEVENTF_SCANCODE
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    user32.keybd_event(0, scan_code, flags, 0)
    try:
        time.sleep(hold_ms / 1000)
    finally:
        user32.keybd_event(0, scan_code, flags | KEYEVENTF_KEYUP, 0)
    time.sleep(settle_ms / 1000)

    if previous and previous != hwnd and user32.IsWindow(previous):
        user32.SetForegroundWindow(previous)
    return {
        "action": action,
        "scan_code": scan_code,
        "dolphin_hwnd": hwnd,
        "hold_ms": hold_ms,
        "settle_ms": settle_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send one approved keyboard action to Pokémon XD in Dolphin"
    )
    parser.add_argument("action", choices=tuple(SCAN_CODES))
    parser.add_argument("--hold-ms", type=int, default=100)
    parser.add_argument("--settle-ms", type=int, default=300)
    args = parser.parse_args()
    try:
        result = send_action(
            args.action,
            hold_ms=args.hold_ms,
            settle_ms=args.settle_ms,
        )
    except DriverError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

