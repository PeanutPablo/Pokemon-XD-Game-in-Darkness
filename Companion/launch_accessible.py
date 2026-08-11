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
SETTINGS = COMPANION / "companion_settings.json"
NARRATOR = COMPANION / "run_accessible_pokemon_xd.py"
GAME_DATA = COMPANION / "_dialogue_extraction"


def fail(message):
    print(message, file=sys.stderr)
    return 1


def main():
    if not SETTINGS.is_file():
        return fail(
            "No settings found. Run Setup.cmd first -- it asks where "
            "Dolphin and your game image are, and reads the game data "
            "the companion needs.")
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    dolphin = Path(settings.get("dolphin_exe", ""))
    game = Path(settings.get("game_image", ""))

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

    pythonw = COMPANION / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.is_file():
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
