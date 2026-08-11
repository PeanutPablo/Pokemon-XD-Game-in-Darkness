"""Check whether the game currently running in Dolphin is one the
accessibility layer can safely read.

Run this after loading a disc image -- especially a converted one, a
different dump, or a ROM hack -- to get a plain answer before starting the
narrator:

    Companion\\.venv\\Scripts\\python.exe check_game_compatibility.py

Read-only. Hooks Dolphin, reads a few bytes, prints a verdict, exits.

What it actually checks: not the disc label, but whether the loaded binary
is laid out the way every address in the profile assumes. See
`profile.engine_signatures` for why that distinction matters -- in short, a
ROM hack built on the US release keeps the layout while being free to
relabel the disc, and the label alone is neither necessary nor sufficient.
"""
import sys

from battle_narrator.dolphin import (
    engine_mismatches, engine_not_loaded, read_disc_label,
)
from battle_narrator.memory import MemoryError, MemoryReader
from battle_narrator.profile import XD_US_REV0


class Backend:
    def __init__(self):
        import dolphin_memory_engine as dme
        self.dme = dme

    def hook(self):
        self.dme.hook()

    def is_hooked(self):
        return self.dme.is_hooked()

    def get_status(self):
        return self.dme.get_status()

    def read_bytes(self, address, size):
        return self.dme.read_bytes(address, size)


def main():
    profile = XD_US_REV0
    try:
        backend = Backend()
    except ImportError:
        print("dolphin_memory_engine is not installed in this environment.")
        return 2
    backend.hook()
    if not backend.is_hooked():
        print("Could not attach to Dolphin. Is it running with a game loaded?")
        return 2

    memory = MemoryReader(backend, profile)
    try:
        game_id, revision = read_disc_label(memory, profile)
    except MemoryError as exc:
        print(f"Could not read the disc header: {exc}")
        return 2
    label = game_id.decode("ascii", errors="replace")
    canonical = profile.game_id.decode("ascii", errors="replace")
    print(f"Disc label      : {label} revision {revision}")
    print(f"Profile expects : {canonical} revision {profile.revision} "
          f"({profile.label})")
    if game_id == b"\0" * 6:
        print("\nNo game is booted yet. Load a game and run this again.")
        return 2

    try:
        mismatches = engine_mismatches(memory, profile)
    except MemoryError as exc:
        print(f"Could not read engine code: {exc}")
        return 2

    total = len(profile.engine_signatures)
    if engine_not_loaded(mismatches, total):
        print("\nThe game has not finished booting -- none of the engine code "
              "is in memory yet. Wait for the title screen and run again.")
        return 2

    print(f"\nEngine checks   : {total - len(mismatches)} of {total} matched")
    for name, address, expected, found in mismatches:
        print(f"  MISMATCH {name} at 0x{address:08X}")
        print(f"     expected {expected.hex()}")
        print(f"     found    {found.hex()}")

    if mismatches:
        print("\nVERDICT: NOT SUPPORTED.")
        print("This is a different build from the one every address in the")
        print("profile was derived from -- most likely a different region")
        print("(PAL/Japanese) or revision. The narrator will refuse to start,")
        print("which is deliberate: running anyway would read the wrong")
        print("memory and speak confident, wrong information.")
        return 1

    print("\nVERDICT: SUPPORTED.")
    if label != canonical or revision != profile.revision:
        print(f"The disc calls itself {label} revision {revision} rather than")
        print(f"{canonical} revision {profile.revision}, but the engine is the")
        print("one this profile targets, so it is safe to read. That is the")
        print("expected result for a ROM hack of the US release, such as XG.")
    print("Note that a hack may still change game DATA (species, moves,")
    print("trainers, dialogue). Text is read from the game's own live string")
    print("tables, so rewritten dialogue is narrated correctly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
