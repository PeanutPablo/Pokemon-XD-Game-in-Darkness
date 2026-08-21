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
import os
import subprocess
import sys
import time
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


def _running_pids_from(folder):
    """PIDs of processes whose executable lives under `folder`.

    Uses the ToolHelp snapshot API directly rather than shelling out to
    PowerShell or `wmic`: `wmic` is gone from current Windows, and starting
    a PowerShell for this would cost most of a second and flash a console
    at a player who cannot see it dismissed.

    Matched on the executable's own path, not on a command line or a
    window title. Anything running out of this installation's own folder
    belongs to this installation -- there is nothing else in there -- and
    that keeps the test from ever reaching a Python the player is using
    for something of their own."""
    import ctypes
    import ctypes.wintypes as wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    folder = str(folder).casefold()
    found = []
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE:
        return found
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(snapshot, ctypes.byref(entry)):
            return found
        while True:
            pid = entry.th32ProcessID
            if pid not in (0, os.getpid()):
                handle = kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    try:
                        size = wintypes.DWORD(32768)
                        buffer = ctypes.create_unicode_buffer(size.value)
                        if kernel32.QueryFullProcessImageNameW(
                                handle, 0, buffer, ctypes.byref(size)):
                            if buffer.value.casefold().startswith(folder):
                                found.append(pid)
                    finally:
                        kernel32.CloseHandle(handle)
            if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def dolphin_already_running(dolphin):
    """Is the Dolphin Setup recorded already open?

    Matched on the exact executable, not on its folder: a Dolphin install
    also ships `DolphinTool.exe` and `Updater.exe`, and `bootstrap_game_
    data.py` runs DolphinTool to convert compressed disc images. Matching
    the folder would call that a running Dolphin and refuse to boot the
    game for a reason the player could never guess."""
    return bool(_running_pids_from(dolphin))


def stop_existing_companion():
    """End any companion already running out of this folder, and wait.

    Starting a second one on top of a first is the single most confusing
    state this project produces: every line is spoken twice, over itself,
    and the player has no way to see that two processes exist. The
    narrator's named mutex already stops the second one doing any work,
    but that leaves the FIRST one -- possibly running stale code from
    before an update -- as the one still talking.

    So the launcher clears the ground instead of hoping. It is also what
    makes replacing this folder safe: a companion holding its log open is
    what turns an update into a half-deleted installation.

    Returns how many it stopped. Failures are ignored deliberately -- a
    process that will not die must not stop the player launching, and the
    mutex still prevents the doubled speech that would matter."""
    import ctypes

    stopped = 0
    for pid in _running_pids_from(RELEASE):
        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
        if not handle:
            continue
        try:
            if ctypes.windll.kernel32.TerminateProcess(handle, 0):
                stopped += 1
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    if stopped:
        # Terminate is asynchronous; the handles it held, the log file
        # above all, are not released the instant it returns.
        time.sleep(0.5)
    return stopped


ESSENTIAL_RELEASE_FILES = (
    "Setup.cmd",
    "Companion/run_accessible_pokemon_xd.py",
    "Companion/battle_narrator/phase1b_app.py",
    "Runtime/python.exe",
    "sounds",
)
"""What a release cannot run without. Checked before anything else.

A partly-deleted installation is a real state, not a hypothetical: it
happens whenever something tries to replace this folder while the
companion is running. Windows refuses to remove the open log file, the
delete stops halfway, and what is left is a folder that still LOOKS like
an install -- same name, same place, `Companion\\logs` present -- with the
launcher, the interpreter and the sounds gone.

It cost a real session here on 2026-08-20: a rebuild into a folder that
still had a companion running in it removed everything it could, and the
next launch did nothing at all because `Access Layer.cmd` was one
of the casualties.

Without this check the failure reads as "The Python environment is
missing. Run Setup.cmd to build it." -- advice that cannot work, because
Setup.cmd was deleted too, and that sends the player looking for a
problem with their machine instead of re-extracting the download."""


def missing_essentials():
    """Which required parts of a release are absent, in listed order.

    Only meaningful for a release. A source checkout has no `Runtime/` and
    no `VERSION`, and is not broken for lacking them, so the caller gates
    on `VERSION` before believing this."""
    return [
        name for name in ESSENTIAL_RELEASE_FILES
        if not (RELEASE / name).exists()
    ]


def check_installation_intact():
    """Refuse, and say what is actually wrong, if files have gone missing.

    `VERSION` is the discriminator: the builder writes it into every
    release and a checkout has none, so its presence means this is a
    release and the parts listed above should all be here."""
    if not (RELEASE / "VERSION").is_file():
        return None
    missing = missing_essentials()
    if not missing:
        return None
    return fail(
        "This copy is incomplete -- some of its files are missing:\n"
        + "".join(f"    {name}\n" for name in missing)
        + "\n"
        "That usually means something replaced or deleted part of this\n"
        "folder while the companion was running, so the delete stopped\n"
        "halfway.\n"
        "\n"
        "Re-extract the download to a fresh folder and run Setup.cmd there.\n"
        "Do not extract on top of this one -- delete it first, and make\n"
        "sure Dolphin and the companion are both closed before you do.")


def main():
    broken = check_installation_intact()
    if broken is not None:
        return broken

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

    # Before anything starts, not after: a companion left over from an
    # earlier session is stale code holding the log open, and starting a
    # second one beside it is how everything comes out twice.
    stopped = stop_existing_companion()
    if stopped:
        print(f"Closed {stopped} companion "
              f"{'process' if stopped == 1 else 'processes'} still running "
              f"from an earlier session.")

    subprocess.Popen(
        [str(pythonw), str(NARRATOR)],
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        cwd=str(COMPANION))
    if dolphin_already_running(dolphin):
        # Deliberately NOT starting a second one, and deliberately not
        # closing the first.
        #
        # Starting a second is what made this look broken: Dolphin does not
        # open twice, so the `-b -e` that boots the disc is simply
        # discarded, and the instance already open stays sitting at its
        # game list. The companion then waits for a game that nothing is
        # going to boot, and the player is told nothing at all.
        #
        # Closing the first is worse. It may have a game running with
        # progress in it, and this cannot tell from out here -- reading
        # whether a game is booted needs the memory backend the narrator
        # owns. Throwing away someone's unsaved play to save them a
        # keystroke is not a trade worth making.
        print("Dolphin is already open, so the game was not booted for you.")
        print("Start your game in the Dolphin window that is already open.")
        print("The companion is running and will begin speaking as soon as "
              "the game loads.")
        return 0

    subprocess.Popen([str(dolphin), "-b", "-e", str(game)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
