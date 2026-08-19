"""First-run setup: build the environment, generate the game data, and
record where Dolphin and your game image live.

Run this once, from the release folder:

    Setup.cmd

It asks three questions, then does the work. Everything it writes stays
inside this folder; nothing is installed system-wide, nothing is sent
anywhere, and your game image is only ever read.

Written to be usable with a screen reader: every prompt states what it
wants and what happens next, every step reports its own result, and
nothing depends on reading a progress bar."""
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

COMPANION = Path(__file__).resolve().parent
RELEASE = COMPANION.parent
VENV = COMPANION / ".venv"
SETTINGS = COMPANION / "companion_settings.json"

MAX_SUPPORTED_PYTHON = (3, 12)
"""dolphin-memory-engine publishes wheels up to 3.12 only. On a newer
interpreter pip falls through to a source build that needs a C++
toolchain, and the failure message is about compilers rather than about
the version -- so the version is checked up front and said plainly."""

DISC_SUFFIXES = (".iso", ".gcm", ".rvz", ".gcz", ".wia", ".ciso", ".wbfs")


def ask(question, validate):
    """Prompt until `validate` accepts. Blank input aborts setup."""
    while True:
        print()
        print(question)
        answer = input("> ").strip().strip('"')
        if not answer:
            raise SystemExit("Setup cancelled.")
        problem = validate(answer)
        if problem is None:
            return answer
        print(f"  {problem}")


def existing_file(*suffixes):
    def check(answer):
        path = Path(answer)
        if not path.is_file():
            return f"There is no file at {path}. Try again."
        if suffixes and path.suffix.lower() not in suffixes:
            return (f"{path.name} is not one of: {', '.join(suffixes)}. "
                    "Try again.")
        return None
    return check


def venv_python(name="python.exe"):
    return VENV / "Scripts" / name


def build_environment():
    print()
    print("Step 1 of 3: building the Python environment.")
    if sys.version_info[:2] > MAX_SUPPORTED_PYTHON:
        raise SystemExit(
            f"This is Python {sys.version_info.major}.{sys.version_info.minor}, "
            f"but one of the required packages (dolphin-memory-engine) only "
            f"publishes builds up to Python "
            f"{MAX_SUPPORTED_PYTHON[0]}.{MAX_SUPPORTED_PYTHON[1]}. Install "
            f"Python {MAX_SUPPORTED_PYTHON[0]}.{MAX_SUPPORTED_PYTHON[1]} and "
            f"run Setup.cmd again."
        )
    if not venv_python().is_file():
        print("  Creating .venv ...")
        venv.EnvBuilder(with_pip=True).create(VENV)
    print("  Installing required packages (this needs an internet "
          "connection, and takes a minute) ...")
    result = subprocess.run(
        [str(venv_python()), "-m", "pip", "install", "--quiet",
         "-r", str(COMPANION / "requirements.txt")],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            "Installing the required packages failed:\n"
            + (result.stderr.strip() or result.stdout.strip()))
    print("  Done.")


def generate_game_data(disc):
    print()
    print("Step 2 of 3: reading your game image.")
    print("  This reads the game's own text, item, move and collision")
    print("  tables out of your copy. It can take a minute, and for")
    print("  compressed images it needs room for a temporary full-size")
    print("  copy. Your image is not modified.")
    result = subprocess.run(
        [str(venv_python()), str(COMPANION / "bootstrap_game_data.py"),
         "--disc", str(disc)])
    if result.returncode != 0:
        raise SystemExit(
            "Reading the game image failed -- see the messages above. "
            "The companion cannot start without this data.")


def write_settings(dolphin, disc):
    """Record the paths, keeping anything else already in the file.

    Merged rather than rewritten because this is no longer the only writer:
    the in-game settings menu stores the player's accessibility preferences
    in the same file under its own key. Re-running Setup to point at a moved
    Dolphin must not silently reset the volumes someone tuned by ear."""
    document = {}
    if SETTINGS.is_file():
        try:
            existing = json.loads(SETTINGS.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                document = existing
        except (OSError, ValueError):
            # An unreadable settings file is replaced, not repaired: Setup
            # exists to put this machine into a known-good state.
            document = {}
    document["dolphin_exe"] = str(dolphin)
    document["game_image"] = str(disc)
    SETTINGS.write_text(json.dumps(document, indent=2), encoding="utf-8")


def main():
    print("Pokemon XG accessibility companion -- setup")
    print("=" * 44)
    print()
    print("You will be asked for your own game image and for Dolphin.")
    print("Neither is included in this download and neither is uploaded")
    print("anywhere. Press Enter on a blank line at any point to stop.")

    disc = Path(ask(
        "Full path to your Pokemon XD / XG disc image "
        f"({', '.join(DISC_SUFFIXES)}):",
        existing_file(*DISC_SUFFIXES)))
    dolphin = Path(ask(
        "Full path to Dolphin.exe:",
        existing_file(".exe")))

    build_environment()
    generate_game_data(disc)

    print()
    print("Step 3 of 3: saving your settings.")
    write_settings(dolphin, disc)
    print(f"  Written to {SETTINGS.name}.")
    print()
    print("Setup finished. Start the game with 'Launch Accessible XD.cmd'.")
    print("If you move Dolphin or your game image later, run Setup.cmd again.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit("\nSetup cancelled.")
