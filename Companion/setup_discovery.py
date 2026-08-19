"""Find Dolphin and the player's disc image, so Setup can stop asking.

Setup used to open with two questions that a blind player answers by
typing an absolute path from memory, into a console, with no completion
and no browse dialog -- the least accessible thing in the whole release.
This module removes the typing from the common cases. It looks where
Dolphin and disc images actually are, ranks what it finds, and hands
Setup a list to read out. Typing a path stays available and is still the
final fallback, because discovery cannot be exhaustive.

Two ordering rules, both deliberate:

  Nearest first. A release folder dropped INSIDE the Dolphin folder, or
  beside it, is the arrangement this is optimised for -- that case should
  cost the player zero questions, and it does, because `Dolphin.exe` is
  then the first and only candidate.

  Dolphin's own opinion beats ours. For disc images, the paths Dolphin is
  configured to scan come before anything found by guessing at Downloads
  or the desktop. If the player can already see the game in Dolphin's
  list, the file behind that entry is the one they mean.

Nothing here decides whether an image is the RIGHT game. That question
belongs to `check_image_compatibility.py` and to the build fingerprint in
`battle_narrator/game_build.py`, both of which answer it from engine
bytes. Discovery only reports the disc header -- game ID, revision,
internal name -- so the pick list says something more useful than a bare
filename. A disc label is neither necessary nor sufficient here (XG
relabels nothing, and two different vanilla XD builds ship under the same
ID), so the header is presented as description and never used to filter.

Search is bounded. Every walk has a depth limit and the whole discovery
run shares one budget of directories it may visit, so pointing this at a
home folder with a million files cannot turn first-run setup into a disk
crawl with no output.
"""
import os
import struct
import sys
from pathlib import Path

DISC_SUFFIXES = (".iso", ".gcm", ".rvz", ".gcz", ".wia", ".ciso", ".wbfs")
"""Kept in step with `setup_companion.DISC_SUFFIXES` and with Dolphin's
own GameCube-capable formats. `.iso` and `.gcm` can be inspected here;
the rest are containers whose header this module cannot read, and they
are offered undescribed rather than hidden."""

INSPECTABLE_SUFFIXES = (".iso", ".gcm")
"""The suffixes whose header this module can read for itself, and so the
only ones it is entitled to REJECT. `.iso` is not a GameCube-specific
extension -- this machine had two PlayStation 3 images sitting in
`Program Files (x86)` that discovery offered as game candidates until
they were checked -- and an `.iso` whose disc magic is absent is not a
GameCube disc, established by reading it rather than by judging its name.
Everything outside this tuple is a compressed container whose header is
not where this looks, so it is offered undescribed instead of judged."""

DISC_MAGIC = 0xC2339F3D
"""The same constant `bootstrap_game_data.DiscImage` validates. It is
read here directly out of a 0x440-byte header rather than by building a
`DiscImage`, because triage wants the cheapest possible "is this a
GameCube disc at all" and `DiscImage` also parses the whole file table."""

DIRECTORY_BUDGET = 6000
"""Total directories one discovery run may open. Reached only on an
unusually deep or crowded home folder; when it is, discovery returns what
it has and Setup still offers to take a typed path."""

MAX_DEPTH = 3
"""Levels below a search root. Three is what the observed layouts need:
`Desktop/apps/Dolphin-x64/Dolphin.exe` is depth 3, and a disc image in
`Documents/My Games/<project>/GameImages/` is depth 3 from Documents."""

SKIP_DIRECTORY_NAMES = frozenset({
    "__pycache__", "node_modules", ".git", ".venv", "AppData", "Windows",
    "$RECYCLE.BIN", "System Volume Information", "Program Files",
    "Program Files (x86)", "ProgramData",
})
"""Pruned during walks. These are either known-huge, known-irrelevant,
or -- for the Program Files pair -- reached deliberately as roots in
their own right and not worth descending into a second time."""


class Candidate:
    """One found path, with why it was found and what it looks like.

    `source` is a phrase Setup reads aloud, so it is written to complete
    the sentence "found ..." ("beside Dolphin", "in this folder").
    `detail` is whatever could be established cheaply, and is empty when
    nothing could be."""

    __slots__ = ("path", "source", "detail")

    def __init__(self, path, source, detail=""):
        self.path = Path(path)
        self.source = source
        self.detail = detail

    def __repr__(self):
        return f"Candidate({self.path!r}, {self.source!r}, {self.detail!r})"

    def __eq__(self, other):
        return (isinstance(other, Candidate)
                and self.path == other.path
                and self.source == other.source
                and self.detail == other.detail)

    def describe(self):
        """One line for the pick list: what it is, then where it is."""
        parts = [self.path.name]
        if self.detail:
            parts.append(self.detail)
        parts.append(f"{self.source}, in {self.path.parent}")
        return " -- ".join(parts)


class _Budget:
    """Shared cap on directories opened, so two walks cannot each spend
    the whole allowance."""

    def __init__(self, limit=DIRECTORY_BUDGET):
        self.remaining = limit

    def spend(self):
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def _resolve(path):
    """Absolute, symlink-free, case-folded key for de-duplication.

    Discovery reaches the same file by several routes on purpose -- the
    Dolphin folder is both a search root and the parent of the release --
    and on Windows those routes disagree about case."""
    try:
        return str(Path(path).resolve()).casefold()
    except OSError:
        return str(path).casefold()


def _walk(root, budget, depth=MAX_DEPTH):
    """Yield directories at or under `root`, nearest first, within budget.

    Breadth-first on purpose: the shallow hit is the likely one, and a
    budget exhausted deep in one branch must not cost the sibling
    branches their turn."""
    root = Path(root)
    if not root.is_dir():
        return
    level = [root]
    for _ in range(depth + 1):
        if not level:
            return
        following = []
        for directory in level:
            if not budget.spend():
                return
            yield directory
            try:
                with os.scandir(directory) as scan:
                    entries = sorted(scan, key=lambda e: e.name)
            except OSError:
                continue
            for entry in entries:
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                if (entry.name in SKIP_DIRECTORY_NAMES
                        or entry.name.startswith(".")):
                    continue
                following.append(Path(entry.path))
        level = following


def user_roots(environ=None):
    """Places worth searching on this machine, nearest-to-the-user first.

    Built from the environment rather than from `Path.home()` because the
    folders that matter are routinely redirected: with OneDrive Backup
    on, Desktop and Documents live under `%OneDrive%` and the literal
    `~/Desktop` is either absent or an empty stub. Both are returned;
    whichever exists gets searched."""
    environ = os.environ if environ is None else environ
    roots = []

    def add(value, *parts):
        if value:
            roots.append(Path(value).joinpath(*parts))

    profile = environ.get("USERPROFILE") or environ.get("HOME")
    onedrive = environ.get("OneDrive") or environ.get("OneDriveConsumer")
    for base in (onedrive, profile):
        add(base, "Desktop")
        add(base, "Downloads")
        add(base, "Documents")
    add(environ.get("LOCALAPPDATA"), "Programs")
    add(environ.get("ProgramFiles"))
    add(environ.get("ProgramFiles(x86)"))
    return roots


def _where(directory, root):
    """Where something is, said relative to the root it was found under."""
    try:
        relative = directory.relative_to(root)
    except ValueError:
        return f"in {directory}"
    if str(relative) == ".":
        return f"in {root.name}"
    return f"in {root.name}{os.sep}{relative}"


# --------------------------------------------------------------------------
# Dolphin
# --------------------------------------------------------------------------

def _dolphin_in(directory):
    """`Dolphin.exe` directly inside `directory`, or None.

    Case-insensitive by listing rather than by probing a fixed name, so a
    build shipping `dolphin.exe` is still found on a case-sensitive mount
    such as a network share."""
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.casefold() != "dolphin.exe":
                    continue
                try:
                    if entry.is_file():
                        return Path(entry.path)
                except OSError:
                    continue
    except OSError:
        pass
    return None


def _registry_dolphin_directories():
    """Install locations Windows knows about. Empty everywhere else.

    Dolphin's installer writes an uninstall entry; a portable unzip does
    not, which is why this is one source among several rather than the
    source."""
    try:
        import winreg
    except ImportError:
        return []
    found = []
    roots = (
        (winreg.HKEY_CURRENT_USER,
         r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, subkey in roots:
        try:
            key = winreg.OpenKey(hive, subkey)
        except OSError:
            continue
        with key:
            try:
                count = winreg.QueryInfoKey(key)[0]
            except OSError:
                continue
            for index in range(count):
                location = None
                try:
                    name = winreg.EnumKey(key, index)
                    with winreg.OpenKey(key, name) as entry:
                        display = winreg.QueryValueEx(entry, "DisplayName")[0]
                        if "dolphin" in str(display).casefold():
                            location = winreg.QueryValueEx(
                                entry, "InstallLocation")[0]
                except OSError:
                    continue
                if location:
                    found.append(Path(location))
    return found


def _dolphin_detail(exe):
    """Version, if Windows will tell us, else the folder's own name.

    Worth the effort because the most confusing thing a player can be
    shown here is two identical lines both reading "Dolphin.exe"."""
    fallback = exe.parent.name
    try:
        import ctypes
        import ctypes.wintypes as wintypes
    except (ImportError, ValueError):
        return fallback
    try:
        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(str(exe), None)
        if not size:
            return fallback
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(exe), 0, size, buffer):
            return fallback
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(
                buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return fallback
        fixed = ctypes.cast(
            pointer, ctypes.POINTER(ctypes.c_uint32 * 4)).contents
        most, least = fixed[2], fixed[3]
        return (f"version {most >> 16}.{most & 0xFFFF}."
                f"{least >> 16}.{least & 0xFFFF}")
    except Exception:
        # Version resources are optional and the API is fiddly. A missing
        # or malformed one must not cost the player a candidate.
        return fallback


def find_dolphin(release_dir, environ=None, budget=None, roots=None):
    """Ranked `Candidate`s for `Dolphin.exe`, best first, de-duplicated.

    Order is confidence, not alphabet:

      1. inside the release folder      a portable Dolphin dropped in
      2. beside the release folder      the release dropped into Dolphin's
      3. registry install locations     an installed Dolphin
      4. the usual places               desktop, downloads, program files
      5. the system PATH

    `roots` overrides step 4 outright, so tests search a temporary tree
    instead of whatever happens to be on the machine running them."""
    release_dir = Path(release_dir)
    budget = _Budget() if budget is None else budget
    search_roots = (user_roots(environ) if roots is None
                    else [Path(root) for root in roots])

    ordered = []
    seen = set()

    def offer(path, source):
        if path is None:
            return
        key = _resolve(path)
        if key in seen:
            return
        seen.add(key)
        ordered.append(Candidate(path, source, _dolphin_detail(Path(path))))

    offer(_dolphin_in(release_dir), "in this folder")
    offer(_dolphin_in(release_dir.parent), "beside this folder")
    for directory in _registry_dolphin_directories():
        offer(_dolphin_in(directory), "installed on this computer")
    for root in search_roots:
        for directory in _walk(root, budget):
            offer(_dolphin_in(directory), _where(directory, root))

    from shutil import which
    on_path = which("Dolphin")
    if on_path:
        offer(Path(on_path), "on the system PATH")
    return ordered


# --------------------------------------------------------------------------
# Disc images
# --------------------------------------------------------------------------

def dolphin_config_dir(dolphin_exe, environ=None):
    """Where this Dolphin keeps `Dolphin.ini`, or None.

    Two layouts, and the portable one has to be checked first: a build
    with `portable.txt` beside the executable ignores the Documents copy
    entirely, so preferring Documents would read a config the player's
    Dolphin is not using."""
    environ = os.environ if environ is None else environ
    if dolphin_exe:
        folder = Path(dolphin_exe).parent
        if (folder / "portable.txt").is_file():
            return folder / "User" / "Config"
    for base in (environ.get("OneDrive"), environ.get("USERPROFILE"),
                 environ.get("HOME")):
        if not base:
            continue
        config = Path(base) / "Documents" / "Dolphin Emulator" / "Config"
        if config.is_dir():
            return config
    return None


def iso_paths_from_ini(text):
    """The `ISOPath0..N` values in a `Dolphin.ini`'s `[General]` section.

    Hand-parsed rather than handed to `configparser`, which rejects real
    Dolphin configs: they carry duplicate keys and values containing `%`
    that interpolation then chokes on. `ISOPaths` -- the count, not a
    path -- is skipped by name."""
    paths = []
    section = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].casefold()
            continue
        if section != "general" or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().casefold()
        value = value.strip()
        if key.startswith("isopath") and key != "isopaths" and value:
            paths.append(value)
    return paths


def describe_disc(path):
    """The disc header as one phrase, or None if this is not a disc.

    Reads 0x440 bytes and nothing else. Compressed containers (.rvz and
    friends) have no readable header here and return None; they are still
    offered, just undescribed, because `bootstrap_game_data` converts
    them through DolphinTool later."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(0x440)
    except OSError:
        return None
    if len(header) < 0x440:
        return None
    if struct.unpack_from(">I", header, 0x1C)[0] != DISC_MAGIC:
        return None
    game_id = header[0x00:0x06].decode("ascii", "replace")
    revision = header[0x07]
    name = header[0x20:0x60].split(b"\x00")[0].decode("ascii", "replace")
    described = f"{game_id} rev {revision}"
    return f"{described}, {name}" if name else described


def _disc_files_in(directory):
    try:
        with os.scandir(directory) as scan:
            entries = sorted(scan, key=lambda e: e.name)
    except OSError:
        return
    for entry in entries:
        if Path(entry.name).suffix.casefold() not in DISC_SUFFIXES:
            continue
        try:
            if entry.is_file():
                yield Path(entry.path)
        except OSError:
            continue


def find_disc_images(release_dir, dolphin_exe=None, environ=None,
                     budget=None, roots=None):
    """Ranked `Candidate`s for a GameCube image, best first.

    Order:

      1. in and beside the release folder
      2. every path Dolphin is configured to scan for games
      3. the folder Dolphin itself lives in
      4. the usual places

    Step 2 is what makes this feel like it read the player's mind: a game
    already listed in Dolphin is a game whose file Dolphin can name."""
    release_dir = Path(release_dir)
    budget = _Budget() if budget is None else budget
    search_roots = (user_roots(environ) if roots is None
                    else [Path(root) for root in roots])

    ordered = []
    seen = set()

    def offer(path, source):
        key = _resolve(path)
        if key in seen:
            return
        seen.add(key)
        detail = describe_disc(path)
        if detail is None and Path(path).suffix.casefold() in INSPECTABLE_SUFFIXES:
            # Readable, and read: this one is not a GameCube disc. Dropping
            # it is a conclusion from its own bytes, not from its name.
            return
        ordered.append(Candidate(path, source, detail or ""))

    def sweep(root, source_for):
        for directory in _walk(root, budget):
            for path in _disc_files_in(directory):
                offer(path, source_for(directory))

    sweep(release_dir, lambda directory: "in this folder")
    for path in _disc_files_in(release_dir.parent):
        offer(path, "beside this folder")

    config = dolphin_config_dir(dolphin_exe, environ)
    if config:
        try:
            text = (config / "Dolphin.ini").read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for configured in iso_paths_from_ini(text):
            sweep(Path(configured),
                  lambda directory: "in Dolphin's own game list")

    if dolphin_exe:
        sweep(Path(dolphin_exe).parent, lambda directory: "beside Dolphin")

    for root in search_roots:
        sweep(root, lambda directory, root=root: _where(directory, root))
    return ordered


def main(argv=None):
    """Report what discovery finds here. Diagnostic only; changes nothing."""
    release = Path(__file__).resolve().parent.parent
    print(f"Release folder: {release}")
    dolphins = find_dolphin(release)
    print()
    print(f"Dolphin candidates ({len(dolphins)}):")
    for candidate in dolphins:
        print(f"  {candidate.describe()}")
    best = dolphins[0].path if dolphins else None
    discs = find_disc_images(release, best)
    print()
    print(f"Disc image candidates ({len(discs)}):")
    for candidate in discs:
        print(f"  {candidate.describe()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(argv=sys.argv[1:]))
