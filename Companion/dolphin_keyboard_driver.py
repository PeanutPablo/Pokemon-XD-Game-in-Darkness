"""Send one safety-checked keyboard action to the configured Dolphin window.

This is diagnostic tooling only. It does not read or write emulated memory and
is not imported by the production narrator.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import time
from ctypes import wintypes
from pathlib import Path


EXPECTED_DOLPHIN = Path(
    r"C:\Users\psych\OneDrive\Desktop\apps\Dolphin-x64\Dolphin.exe"
)

ACTIONS = {
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "dpad_up": 0x54,  # T
    "dpad_down": 0x47,  # G
    "dpad_left": 0x46,  # F
    "dpad_right": 0x48,  # H
    "confirm": 0x58,  # X
    "cancel": 0x5A,  # Z
    "start": 0x0D,  # Return
}

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9


class DriverError(RuntimeError):
    pass


def _window_process_path(user32, kernel32, hwnd: int) -> Path:
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    process = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value
    )
    if not process:
        raise DriverError("Unable to inspect the Dolphin process")
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            process, 0, buffer, ctypes.byref(size)
        ):
            raise DriverError("Unable to resolve the Dolphin executable")
        return Path(buffer.value)
    finally:
        kernel32.CloseHandle(process)


def _find_dolphin_window(user32, kernel32, expected_path: Path) -> int:
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    @callback_type
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        try:
            actual = _window_process_path(user32, kernel32, hwnd)
        except DriverError:
            return True
        if actual.resolve() == expected_path.resolve():
            matches.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    if len(matches) != 1:
        raise DriverError(
            f"Expected exactly one visible Dolphin window; found {len(matches)}"
        )
    return matches[0]


def send_action(
    action: str,
    *,
    expected_path: Path = EXPECTED_DOLPHIN,
    hold_ms: int = 80,
    settle_ms: int = 250,
) -> dict:
    if action not in ACTIONS:
        raise DriverError(f"Unsupported action: {action}")
    if not 30 <= hold_ms <= 500:
        raise DriverError("Hold duration must be between 30 and 500 ms")
    if not 0 <= settle_ms <= 5000:
        raise DriverError("Settle duration must be between 0 and 5000 ms")
    if not expected_path.is_file():
        raise DriverError(f"Approved Dolphin executable is missing: {expected_path}")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hwnd = _find_dolphin_window(user32, kernel32, expected_path)
    previous = user32.GetForegroundWindow()

    user32.ShowWindow(hwnd, SW_RESTORE)
    if not user32.SetForegroundWindow(hwnd):
        raise DriverError("Dolphin could not be brought to the foreground")
    time.sleep(0.1)
    if user32.GetForegroundWindow() != hwnd:
        raise DriverError("Dolphin did not obtain foreground focus")

    virtual_key = ACTIONS[action]
    scan_code = user32.MapVirtualKeyW(virtual_key, 0)
    extended = KEYEVENTF_EXTENDEDKEY if virtual_key in (0x25, 0x26, 0x27, 0x28) else 0
    user32.keybd_event(virtual_key, scan_code, extended, 0)
    time.sleep(hold_ms / 1000)
    user32.keybd_event(
        virtual_key, scan_code, extended | KEYEVENTF_KEYUP, 0
    )
    time.sleep(settle_ms / 1000)

    if previous and previous != hwnd and user32.IsWindow(previous):
        user32.SetForegroundWindow(previous)

    return {
        "action": action,
        "virtual_key": virtual_key,
        "dolphin_hwnd": hwnd,
        "hold_ms": hold_ms,
        "settle_ms": settle_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send one approved keyboard action to Dolphin"
    )
    parser.add_argument("action", choices=tuple(ACTIONS))
    parser.add_argument("--hold-ms", type=int, default=80)
    parser.add_argument("--settle-ms", type=int, default=250)
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
