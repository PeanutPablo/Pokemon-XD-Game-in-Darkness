"""First-run setup: find Dolphin and your game, then generate the data.

Run this once, from the release folder:

    Setup.cmd

Everything it writes stays inside this folder; nothing is installed
system-wide, nothing is sent anywhere, and your game image is only ever
read.

Written to be usable with a screen reader: every prompt states what it
wants and what happens next, every step reports its own result, and
nothing depends on reading a progress bar.

**What changed on 2026-08-18, and why.** This used to open with two
questions answered by typing an absolute path from memory into a console
-- no completion, no browse dialog, no way to check a typo before pressing
Enter. It was the least accessible thing in the release, and it was the
first thing a new player met. `setup_discovery` now looks for Dolphin and
for disc images where they actually are, and this asks the player to
confirm or pick a number instead. Typing a path still works and is still
the fallback when discovery finds nothing, because discovery cannot be
exhaustive.

**Two environments, one script.** A built release ships its own
interpreter in `Runtime/` with every package already in place, so setup
has nothing to install and needs no internet. A source checkout has no
`Runtime/`, and the `.venv` path below builds one exactly as before. The
release case is the one a player sees; the checkout case is the one this
project develops against, and both have to keep working."""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from setup_discovery import find_disc_images, find_dolphin  # noqa: E402

COMPANION = Path(__file__).resolve().parent
RELEASE = COMPANION.parent
RUNTIME = RELEASE / "Runtime"
VENV = COMPANION / ".venv"
SETTINGS = COMPANION / "companion_settings.json"

MAX_SUPPORTED_PYTHON = (3, 12)
"""dolphin-memory-engine publishes wheels up to 3.12 only. On a newer
interpreter pip falls through to a source build that needs a C++
toolchain, and the failure message is about compilers rather than about
the version -- so the version is checked up front and said plainly.

Only reachable in a source checkout. A release carries its own 3.12 in
`Runtime/` and never consults whatever Python the player may have."""

DISC_SUFFIXES = (".iso", ".gcm", ".rvz", ".gcz", ".wia", ".ciso", ".wbfs")

CANCEL_WORDS = frozenset({"q", "quit", "stop", "cancel", "exit"})
"""Typed to stop setup. A word rather than a bare Enter, because Enter now
means "yes, the one you found" -- the whole point of discovery is that the
common case is a single keystroke."""


WINDOWS_PATH_LIMIT = 260
"""The classic `MAX_PATH`. The failure it causes says nothing about
length or about folders -- the observed one is `ImportError: DLL load
failed while importing _dolphin_memory_engine: The filename or extension
is too long`, raised when the narrator starts, naming a package."""


def long_paths_enabled():
    """Whether Windows accepts ordinary paths past `MAX_PATH` here.

    Checked rather than assumed, because it decides whether a long path is
    fatal for the release's data files, and refusing to set up a copy that
    would in fact have worked is its own defect. It does NOT decide the
    question for binary extension modules -- see `LOADABLE_SUFFIXES`."""
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return bool(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
    except (ImportError, OSError, ValueError):
        return False


LOADABLE_SUFFIXES = (".pyd", ".dll")
"""Binary extension modules, which Windows loads with `LoadLibrary`.

These are measured separately from everything else because `LoadLibrary`
is capped at `MAX_PATH` **even when long-path support is switched on**.
That is not a guess: on the machine this was developed on the registry's
`LongPathsEnabled` is 1, ordinary file access past the limit works, and
importing `dolphin_memory_engine` from a 281-character path still failed
with "The filename or extension is too long". Long-path support saves
data files. It does not save DLLs."""


def longest_paths(root):
    """(longest overall, longest loadable) full path lengths inside `root`.

    Measured rather than estimated from a constant. A release carries
    about 1,800 files, the deepest inside numpy's bundled licences, and
    that depth changes whenever a dependency is updated -- a hardcoded
    margin would be wrong the first time numpy reorganised."""
    longest = len(str(root))
    loadable = 0
    for folder, _directories, files in os.walk(root):
        for name in files:
            length = len(folder) + 1 + len(name)
            longest = max(longest, length)
            if name.casefold().endswith(LOADABLE_SUFFIXES):
                loadable = max(loadable, length)
    return longest, loadable


def too_deep(longest, loadable, long_paths):
    """The length that makes this folder unusable, or None if it is fine.

    Split out from the reporting so the rule itself can be tested without
    a 1,800-file tree: a loadable module past the limit is fatal whatever
    the machine is configured to allow, and everything else is fatal only
    when long-path support is off."""
    if loadable >= WINDOWS_PATH_LIMIT:
        return loadable
    if longest >= WINDOWS_PATH_LIMIT and not long_paths:
        return longest
    return None


def check_path_length():
    """Stop now, with an explanation, rather than fail cryptically later.

    This is the one first-run failure that cannot be diagnosed from its
    own error message -- it surfaces minutes later, as an ImportError
    naming a package, with nothing pointing at the folder the player
    chose. So it is checked before anything else happens."""
    longest, loadable = longest_paths(RELEASE)
    long_paths = long_paths_enabled()
    fatal = too_deep(longest, loadable, long_paths)
    if fatal is None:
        if longest >= WINDOWS_PATH_LIMIT:
            print()
            print("  Note: some files here have paths longer than "
                  f"{WINDOWS_PATH_LIMIT} characters. This computer allows "
                  "that, and nothing that has to be loaded as a program is "
                  "affected.")
        return
    raise SystemExit(
        f"This folder is too deep inside your drive for Windows.\n"
        f"\n"
        f"  {RELEASE}\n"
        f"\n"
        f"A file inside it needs {fatal} characters and Windows allows "
        f"{WINDOWS_PATH_LIMIT}. Nothing is wrong with the download -- it "
        f"just cannot live this far down. Setup is stopping here because "
        f"the failure it would otherwise cause appears much later, and "
        f"says nothing about folders.\n"
        f"\n"
        f"Move this whole folder somewhere shorter, such as C:\\Games\\, "
        f"and run Setup.cmd again.")


def runtime_python(name="python.exe"):
    """The bundled interpreter in a release, or None in a checkout."""
    candidate = RUNTIME / name
    return candidate if candidate.is_file() else None


def venv_python(name="python.exe"):
    return VENV / "Scripts" / name


def interpreter(name="python.exe"):
    """Whichever interpreter this installation runs the companion with."""
    return runtime_python(name) or venv_python(name)


def prompt(question, lines=()):
    """Ask, having first said everything needed to answer.

    Each option on its own line: a screen reader reads line by line, and a
    numbered list crammed onto one line has to be replayed to be used."""
    print()
    print(question)
    for line in lines:
        print(line)
    return input("> ").strip().strip('"')


def choose(what, candidates, validate, describe_typed):
    """Confirm one found path, pick from several, or type one.

    `validate` returns a complaint or None, and is applied to typed paths
    AND to picked ones -- a candidate that has been deleted between the
    scan and the answer must not sail through just because discovery
    listed it."""
    while True:
        if not candidates:
            answer = prompt(
                f"Could not find {what} automatically. Type the full path to "
                f"it:",
                [f"  ({describe_typed})",
                 "  Or type q to stop setup."])
            if not answer or answer.casefold() in CANCEL_WORDS:
                raise SystemExit("Setup cancelled.")
            problem = validate(answer)
            if problem is None:
                return Path(answer)
            print(f"  {problem}")
            continue

        if len(candidates) == 1:
            only = candidates[0]
            print()
            print(f"Found {what}:")
            print(f"  {only.describe()}")
            answer = prompt(
                "Press Enter to use it, or type the full path to a "
                "different one.",
                ["  Or type q to stop setup."])
            if not answer:
                problem = validate(str(only.path))
                if problem is None:
                    return only.path
                print(f"  {problem}")
                candidates = []
                continue
        else:
            print()
            print(f"Found {len(candidates)} possibilities for {what}:")
            for index, candidate in enumerate(candidates, start=1):
                print(f"  {index}. {candidate.describe()}")
            answer = prompt(
                f"Type a number from 1 to {len(candidates)}, or the full "
                f"path to one that is not listed.",
                ["  Press Enter for number 1.",
                 "  Or type q to stop setup."])
            if not answer:
                answer = "1"

        if answer.casefold() in CANCEL_WORDS:
            raise SystemExit("Setup cancelled.")
        if answer.isdigit():
            index = int(answer)
            if not 1 <= index <= len(candidates):
                print(f"  There is no number {index} in that list. "
                      f"Try again.")
                continue
            chosen = candidates[index - 1].path
            problem = validate(str(chosen))
            if problem is None:
                return chosen
            print(f"  {problem}")
            continue
        problem = validate(answer)
        if problem is None:
            return Path(answer)
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


def build_environment(step):
    """Create `.venv` and install the packages. Source checkouts only.

    `venv` is imported HERE, not at the top of the file. CPython's
    embeddable package -- the interpreter a release carries -- ships
    without `venv`, `ensurepip` or `tkinter`, so a module-level import
    made this file unimportable on exactly the machines it was rewritten
    to serve: setup died with `ModuleNotFoundError: No module named
    'venv'` before printing a single line. Nothing on the release path
    needs it, and this function is unreachable when `Runtime/` exists."""
    import venv

    print()
    print(f"{step}: building the Python environment.")
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
    sys.stdout.flush()
    result = subprocess.run(
        [str(venv_python()), "-m", "pip", "install", "--quiet",
         "-r", str(COMPANION / "requirements.txt")],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            "Installing the required packages failed:\n"
            + (result.stderr.strip() or result.stdout.strip()))
    print("  Done.")


def generate_game_data(step, disc):
    print()
    print(f"{step}: reading your game image.")
    print("  This reads the game's own text, item, move and collision")
    print("  tables out of your copy. It can take a minute, and for")
    print("  compressed images it needs room for a temporary full-size")
    print("  copy. Your image is not modified.")
    # Flushed before the child starts, or the child's output -- which goes
    # straight to the same handle -- arrives ahead of the heading that is
    # supposed to introduce it. Only visible when stdout is not a console,
    # which is exactly how this gets tested, and a screen reader announcing
    # a minute of bootstrap output before the words explaining it is a bad
    # enough experience to be worth two lines here.
    sys.stdout.flush()
    result = subprocess.run(
        [str(interpreter()), str(COMPANION / "bootstrap_game_data.py"),
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
    print("This looks for Dolphin and for your game image, and asks you to")
    print("confirm what it finds. Neither is included in this download and")
    print("neither is uploaded anywhere. Type q at any prompt to stop.")

    check_path_length()

    bundled = runtime_python() is not None
    total = 2 if bundled else 3
    step = 0

    print()
    print("Looking for Dolphin and your game image ...")
    dolphins = find_dolphin(RELEASE)
    dolphin = choose(
        "Dolphin", dolphins, existing_file(".exe"),
        "the file is called Dolphin.exe")

    discs = find_disc_images(RELEASE, dolphin)
    disc = choose(
        "your Pokemon XD / XG game image", discs,
        existing_file(*DISC_SUFFIXES),
        f"one of: {', '.join(DISC_SUFFIXES)}")

    if not bundled:
        step += 1
        build_environment(f"Step {step} of {total}")

    step += 1
    generate_game_data(f"Step {step} of {total}", disc)

    step += 1
    print()
    print(f"Step {step} of {total}: saving your settings.")
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
