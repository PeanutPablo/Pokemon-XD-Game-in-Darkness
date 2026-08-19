"""Identify which game build is running, so the right data is loaded.

The companion's offline tables are generated from one disc and describe
only that disc. Pointed at a different build they do not fail loudly --
they disagree, and `menus.py` refuses to speak rather than announce a
wrong move name. That has happened twice, in both directions (vanilla
data with XG running, 2026-08-12; XG data with vanilla running,
2026-08-13), and both times the player was left with a mostly-silent move
menu. This module exists so the companion can pick the matching data
itself instead of relying on the player to remember.

Why a fingerprint of the running code, and not something easier
------------------------------------------------------------------
Every simpler discriminator was tried against the two real images and
found wanting:

* **The disc label.** Identical: both are `GXXE01` revision 0, internal
  name `POKeMON XD`. XG is a hack of the US release and is under no
  obligation to relabel, and does not.
* **The engine signatures** in `profile.engine_signatures`. All eight
  match on both builds -- correctly, since the code they check is
  unchanged. They answer "can this be read at all", not "which build".
* **Dolphin's configuration.** Records the game-list folder, not what is
  currently booted, and would be stale the moment the player loads
  something else. Memory is the only source that describes what is
  actually running.
* **The string tables in `main.dol`.** These *are* the text the data
  provides, so they looked ideal -- but they are rewritten in place at
  load (relative offsets become pointers), so live bytes match neither
  disc. Measured, not assumed.
* **Hashing a whole code section.** Live `text1` matches neither disc
  either: the game patches four of its own pages at runtime.

What does work is sampling code the game leaves alone. Measured against
a running vanilla disc, exactly four of `text1`'s 740 pages are written
after load, clustered at pages 448-457. Sampling 32 pages at an even
stride steps over that cluster entirely, matches the disc byte for byte,
and separates the two builds. (A denser 64-page sampling lands on page
451 and fails -- which is why the stride is pinned here rather than left
to taste.)

If a future build writes somewhere these samples do land, the fingerprint
will match nothing and the companion says so. That is the designed
failure: an unrecognised build produces a warning, never a wrong table.
"""
import json
import zlib
from pathlib import Path

STAMP_NAME = "build_id.json"

PAGE_SIZE = 0x1000
SAMPLE_COUNT = 32
"""Pinned by measurement. See the module docstring: 64 samples collide
with the engine's own runtime-written pages, 32 do not."""

REGION_ADDRESS = 0x800056A0
REGION_SIZE = 3033312
"""main.dol's largest text section, at the same address and size in both
known builds. A build that placed it elsewhere would fingerprint to
nothing and be reported as unrecognised, which is the safe outcome."""


def sample_offsets():
    """Byte offsets into the region, in order. Deterministic."""
    pages = REGION_SIZE // PAGE_SIZE
    step = pages // SAMPLE_COUNT
    return [index * step * PAGE_SIZE for index in range(SAMPLE_COUNT)]


def _fingerprint(read_page):
    digest = 0
    for offset in sample_offsets():
        page = read_page(offset)
        if len(page) != PAGE_SIZE:
            raise ValueError(
                f"short read of {len(page)} bytes at region offset "
                f"{offset:#x}")
        digest = zlib.crc32(page, digest)
    return f"{digest:08X}"


def fingerprint_from_dol(dol, sections):
    """The fingerprint of a disc's executable, for stamping at bootstrap.

    `sections` is the DOL section table as
    `[(index, file_offset, address, size)]`."""
    for _index, file_offset, address, size in sections:
        if address <= REGION_ADDRESS and (
                REGION_ADDRESS + REGION_SIZE <= address + size):
            base = file_offset + (REGION_ADDRESS - address)
            return _fingerprint(
                lambda offset: dol[base + offset:base + offset + PAGE_SIZE])
    raise ValueError(
        "this executable has no section covering the fingerprint region")


def fingerprint_from_memory(read_bytes):
    """The fingerprint of the running game. `read_bytes(address, size)`."""
    return _fingerprint(
        lambda offset: read_bytes(REGION_ADDRESS + offset, PAGE_SIZE))


def write_stamp(directory, fingerprint, source=None, game_id=None,
                revision=None, internal_name=None):
    """Record which build a generated data tree describes."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = {
        "fingerprint": fingerprint,
        "region_address": REGION_ADDRESS,
        "region_size": REGION_SIZE,
        "sample_count": SAMPLE_COUNT,
        "page_size": PAGE_SIZE,
        "game_id": game_id,
        "revision": revision,
        "internal_name": internal_name,
        "source_image": str(source) if source else None,
    }
    (directory / STAMP_NAME).write_text(
        json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    return stamp


def read_stamp(directory):
    """The stamp in `directory`, or None if it has none or is unreadable."""
    path = Path(directory) / STAMP_NAME
    try:
        stamp = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(stamp, dict) or not stamp.get("fingerprint"):
        return None
    # A stamp written by a different sampling scheme cannot be compared.
    for key, value in (("region_address", REGION_ADDRESS),
                       ("region_size", REGION_SIZE),
                       ("sample_count", SAMPLE_COUNT),
                       ("page_size", PAGE_SIZE)):
        if stamp.get(key) != value:
            return None
    return stamp


def describe(stamp):
    if not stamp:
        return "unstamped data"
    name = stamp.get("internal_name") or stamp.get("game_id") or "unknown"
    return f"{name} [{stamp['fingerprint']}]"


def candidate_directories(base):
    """Data trees to consider: each immediate subdirectory, then `base`.

    `base` itself comes last so a stamped per-build tree always wins over
    a legacy flat one left in place beside it."""
    base = Path(base)
    directories = []
    try:
        directories = sorted(
            child for child in base.iterdir() if child.is_dir())
    except OSError:
        directories = []
    directories.append(base)
    return directories


def select(base, fingerprint):
    """(directory, stamp, reason) for the tree matching `fingerprint`.

    Returns (None, None, reason) when nothing matches, so the caller can
    report it rather than guess. A guess here would reintroduce exactly
    the silent-wrong-data failure this module exists to prevent."""
    seen = []
    for directory in candidate_directories(base):
        stamp = read_stamp(directory)
        if stamp is None:
            continue
        seen.append((directory, stamp))
        if fingerprint and stamp["fingerprint"] == fingerprint:
            return directory, stamp, f"matched {describe(stamp)}"
    if not seen:
        return None, None, "no data tree carries a build stamp"
    known = ", ".join(describe(stamp) for _d, stamp in seen)
    return None, None, (
        f"the running game fingerprints to {fingerprint}, which matches "
        f"none of the installed data ({known})")
