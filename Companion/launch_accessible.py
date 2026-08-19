"""Start the companion and Dolphin together, using the paths Setup
recorded.

Replaces the project owner's personal `.bat`, which hardcoded one
machine's Dolphin, game image and interpreter. Everything here is either
relative to this release folder or read back from
`companion_settings.json`, so the same file works on anyone's machine.

The companion is started FIRST and detached, exactly as the original
launcher did: it waits for Dolphin to appear on its own, and starting it
first means the title screen is already being narrated by the time the
game boots. `run_accessible_pokemon_xd.py` holds a named mutex, so a
second launch attaches nothing and speaks nothing rather than doubling
every line."""
import json
import subprocess
import sys
from pathlib import Path

COMPANION = Path(__file__).resolve().parent
RELEASE = COMPANION.parent
SETTINGS = COMPANION / "companion_settings.json"
NARRATOR = COMPANION / "run_accessible_pokemon_xd.py"
GAME_DATA = COMPANION / "_dialogue_extraction"


def windowless_python():
    """The interpreter to start the narrator with, or None if there is none.

    `Runtime/` is the interpreter a built release carries with it, so a
    player needs no Python of their own; `.venv` is what a source checkout
    builds. Runtime wins when both exist, which happens when a developer
    unpacks a release inside a working tree -- the release is then the
    thing under test and its own interpreter is the one that should run.

    `pythonw.exe`, not `python.exe`: the narrator is detached and long-
    lived, and the console window `python.exe` opens would sit in the
    alt-tab order for the whole session with nothing in it."""
    for base in (RELEASE / "Runtime", COMPANION / ".venv" / "Scripts"):
        candidate = base / "pythonw.exe"
        if candidate.is_file():
            return candidate
    return None


def fail(message):
    print(message, file=sys.stderr)
    return 1


def main():
    settings = (
        json.loads(SETTINGS.read_text(encoding="utf-8"))
        if SETTINGS.is_file() else {}
    )
    # The presence of the FILE is no longer proof that Setup has run: the
    # in-game settings menu writes the player's own preferences into the
    # same file, under its own key, and can create it first. The paths
    # Setup records are what this actually needs, so they are what is
    # checked -- otherwise a player who adjusted the volume before running
    # Setup would get "Dolphin is no longer at ." instead of being told to
    # run Setup.
    if not settings.get("dolphin_exe") or not settings.get("game_image"):
        return fail(
            "No settings found. Run Setup.cmd first -- it asks where "
            "Dolphin and your game image are, and reads the game data "
            "the companion needs.")
    dolphin = Path(settings["dolphin_exe"])
    game = Path(settings["game_image"])

    # Checked before anything starts, so a moved file is one clear
    # message rather than a silent narrator plus a Dolphin error box.
    for label, path in (("Dolphin", dolphin), ("game image", game)):
        if not path.is_file():
            return fail(
                f"The {label} is no longer at {path}. Run Setup.cmd again "
                "to point at its new location.")
    if not GAME_DATA.is_dir():
        return fail(
            "The game data is missing. Run Setup.cmd to generate it from "
            "your own game image.")

    pythonw = windowless_python()
    if pythonw is None:
        return fail(
            "The Python environment is missing. Run Setup.cmd to build it.")

    subprocess.Popen(
        [str(pythonw), str(NARRATOR)],
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        cwd=str(COMPANION))
    subprocess.Popen([str(dolphin), "-b", "-e", str(game)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
