"""Single-instance entry point used by the accessible Pokémon XD launcher."""

import ctypes
import sys

from battle_narrator.phase1b_app import run


ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = r"Local\PokemonXGAccessibility.BattleNarrator"


def main():
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not mutex:
        return 1
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(mutex)
        return 0
    try:
        return run()
    finally:
        kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    sys.exit(main())
