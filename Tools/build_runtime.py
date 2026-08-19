"""Stage a self-contained Python into a release, so players need none.

Setup used to open by telling the player to go and install Python 3.12 --
specifically 3.12, because `dolphin-memory-engine` publishes no wheel for
anything newer, and a player who already had 3.13 had to be talked into
installing an older one alongside it. That is a hard first step for anyone,
and a genuinely hostile one for the audience this project is for. A release
now carries its own interpreter with every package already inside it, so
first-run setup installs nothing, needs no internet, and cannot be defeated
by whatever Python is or is not on the machine.

The interpreter is CPython's official **embeddable** package for Windows:
a plain zip of the same binaries as the installer build, with no installer,
no registry entries and no effect on any Python already present.

    python Tools/build_runtime.py --target "<stage>/Runtime"

Two things about the embeddable package drive everything below.

**It is deliberately isolated.** It ships a `python312._pth` file, and when
that file exists CPython treats `sys.path` as fully specified by it: the
script's own directory is NOT prepended, and `site-packages` is not
consulted. That is why the `._pth` is rewritten rather than left alone.
Adding `..\\Companion` to it is what makes `import battle_narrator` work
from every entry point without any of them having to manipulate `sys.path`.

**It has no pip.** Packages are therefore installed by the BUILD machine's
pip with `--target`, which unpacks wheels into a directory without needing
an interpreter there to run. That only produces working binaries if the
build interpreter and the embedded one agree on version and architecture,
so that is checked rather than assumed -- a cp312 wheel dropped beside a
3.13 runtime fails at import time on the player's machine, which is the
worst possible place to find out.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import sysconfig
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_VERSION = "3.12.10"
"""The newest 3.12 python.org publishes. 3.12 rather than newest-overall
because `dolphin-memory-engine` stops there; see `requirements.txt`."""

KNOWN_HASHES = {
    "3.12.10": "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3",
}
"""SHA-256 of `python-<version>-embed-amd64.zip` as served by python.org.

Pinned on first download (2026-08-18, over HTTPS with certificate
validation) and checked on every build since. This is trust-on-first-use:
it does not prove the first download was honest, but it does mean that
every release this project ever ships is built from those exact bytes, and
that a later substitution fails the build loudly instead of shipping a
different interpreter to players. A version with no entry here refuses to
build rather than downloading unverified -- add its hash deliberately."""

DOWNLOAD_URL = ("https://www.python.org/ftp/python/{version}/"
                "python-{version}-embed-amd64.zip")

REQUIRED_IMPORTS = ("numpy", "pygame", "dolphin_memory_engine", "cytolk")
"""Import names, not distribution names, for the end-to-end check. The two
differ (`dolphin-memory-engine` imports as `dolphin_memory_engine`), and it
is the import that has to work on the player's machine."""


class RuntimeError_(RuntimeError):
    """Raised for every condition that should stop a release being built."""


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_build_interpreter(version):
    """Refuse unless this interpreter can produce wheels the runtime loads.

    `pip install --target` selects wheels for the interpreter RUNNING it,
    so a mismatch here is silent at build time and fatal at import time on
    someone else's computer."""
    major, minor, _ = version.split(".", 2)
    wanted = (int(major), int(minor))
    if sys.version_info[:2] != wanted:
        raise RuntimeError_(
            f"This is Python {sys.version_info.major}."
            f"{sys.version_info.minor}, but the runtime being built is "
            f"{major}.{minor}. Binary wheels are chosen for the interpreter "
            f"running pip, so they would not load. Run this with Python "
            f"{major}.{minor} -- Companion/.venv is one.")
    platform = sysconfig.get_platform()
    if platform != "win-amd64":
        raise RuntimeError_(
            f"The embeddable runtime is win-amd64 and this interpreter "
            f"reports {platform}. Wheels chosen here would not load there.")


def fetch(version, cache):
    """The embeddable zip, downloaded if absent, verified either way."""
    expected = KNOWN_HASHES.get(version)
    if expected is None:
        raise RuntimeError_(
            f"No pinned SHA-256 for Python {version}. Add one to "
            f"KNOWN_HASHES deliberately rather than building against an "
            f"unverified download.")
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"python-{version}-embed-amd64.zip"
    if not archive.is_file():
        url = DOWNLOAD_URL.format(version=version)
        print(f"  Downloading {url} ...")
        with urllib.request.urlopen(url, timeout=120) as response:
            archive.write_bytes(response.read())
    found = sha256(archive)
    if found != expected:
        # Left in place rather than deleted: a hash mismatch is worth
        # looking at, and deleting the evidence helps nobody.
        raise RuntimeError_(
            f"{archive.name} does not match its pinned SHA-256.\n"
            f"  expected {expected}\n  found    {found}\n"
            f"Refusing to build a release around it.")
    print(f"  Verified {archive.name} ({archive.stat().st_size:,} bytes).")
    return archive


def path_file(target):
    """The `._pth` the embeddable package ships, whatever it is called."""
    found = sorted(target.glob("python*._pth"))
    if not found:
        raise RuntimeError_(
            f"No python*._pth in {target}. The embeddable package always "
            f"ships one; without it sys.path is not under our control.")
    return found[0]


def write_search_path(target):
    """Replace the shipped `._pth` so the companion is importable.

    The stdlib zip and the runtime directory are what the package ships
    with. The two additions are the point:

      Lib\\site-packages   where --target puts numpy, pygame and the rest
      ..\\Companion        so `import battle_narrator` works from anywhere,
                          which the isolation the ._pth itself imposes
                          would otherwise prevent

    `import site` is restored because pip's `--target` layout relies on it,
    and because without it `sys.path` cannot be extended at runtime at all."""
    lines = [
        f"python{sys.version_info.major}{sys.version_info.minor}.zip",
        ".",
        "Lib\\site-packages",
        "..\\Companion",
        "",
        "# Uncommented deliberately: see Tools/build_runtime.py.",
        "import site",
        "",
    ]
    destination = path_file(target)
    destination.write_text("\n".join(lines), encoding="ascii")
    return destination


def install_packages(target, requirements):
    """Unpack the required wheels into the runtime's site-packages."""
    site_packages = target / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade",
         "--target", str(site_packages), "-r", str(requirements)],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError_(
            "Installing the runtime's packages failed:\n"
            + (result.stderr.strip() or result.stdout.strip()))


def verify(target, companion):
    """Prove the staged runtime imports what the companion needs.

    Run as the player's machine will run it -- the staged `python.exe`,
    resolving through the `._pth` just written -- because every failure
    mode this function exists to catch (a wheel for the wrong ABI, a
    `._pth` that lost site-packages, a Companion path that does not
    resolve) looks perfectly fine from the build interpreter."""
    exe = target / "python.exe"
    if not exe.is_file():
        raise RuntimeError_(f"No python.exe in {target}.")
    program = (
        "import sys\n"
        + "".join(f"import {name}\n" for name in REQUIRED_IMPORTS)
        + "import battle_narrator.profile\n"
        "print(sys.version.split()[0])\n"
    )
    # pygame greets stdout on import unless told not to, which would
    # otherwise be read back as the version number.
    environment = dict(os.environ, PYGAME_HIDE_SUPPORT_PROMPT="1")
    result = subprocess.run([str(exe), "-c", program],
                            capture_output=True, text=True,
                            cwd=str(companion), env=environment)
    if result.returncode != 0:
        raise RuntimeError_(
            "The staged runtime cannot import what the companion needs:\n"
            + (result.stderr.strip() or result.stdout.strip()))
    reported = result.stdout.strip().splitlines()
    return reported[-1] if reported else "(version not reported)"


def build(target, requirements, companion, cache, version=DEFAULT_VERSION):
    """Produce a complete, verified runtime at `target`."""
    target = Path(target)
    check_build_interpreter(version)
    archive = fetch(version, cache)

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(target)
    print(f"  Extracted the interpreter to {target.name}\\.")

    write_search_path(target)
    print("  Rewrote the search path.")

    install_packages(target, Path(requirements))
    print("  Installed the required packages.")

    reported = verify(target, Path(companion))
    print(f"  Verified: Python {reported} imports every required package.")
    return target


def parser():
    parsed = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parsed.add_argument("--target", required=True,
                        help="directory to create the runtime in")
    parsed.add_argument("--requirements", required=True,
                        help="Companion/requirements.txt")
    parsed.add_argument("--companion", required=True,
                        help="the staged Companion directory, for the "
                             "import check")
    parsed.add_argument("--cache", required=True,
                        help="where to keep the downloaded embeddable zip")
    parsed.add_argument("--version", default=DEFAULT_VERSION,
                        help=f"Python version (default {DEFAULT_VERSION})")
    return parsed


def main(argv=None):
    arguments = parser().parse_args(argv)
    try:
        build(arguments.target, arguments.requirements, arguments.companion,
              arguments.cache, arguments.version)
    except RuntimeError_ as problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
