"""Build the local game-data indexes the companion needs, from the
player's own disc image.

Run this ONCE, after installing, before the first launch:

    Companion\\.venv\\Scripts\\python.exe bootstrap_game_data.py --disc "D:\\games\\my_copy.iso"

Why this step exists at all: the narrator reads the game's own text,
item, move and collision tables to say anything useful, and those tables
are copyrighted game data. They cannot be redistributed, so the release
ships the CODE that reads them and each player generates the DATA from
the copy they already own. Nothing here contacts the network, nothing
touches a running game, and the disc image is only ever read.

What it produces, under `Companion/_dialogue_extraction/`:

  raw/files/common.fsys        names, moves, items, warps, doors, flags
  raw/files/fight_common.fsys  battle message catalogue
  raw/files/pocket_menu.fsys   item descriptions, shop messages
  dol_strings.json             menu/system text decoded out of main.dol
  collision/*.ccd              per-room collision, for warp navigation
  worldmap/files, pda/files    world map and P*DA screens

The first four are REQUIRED -- without them the narrator refuses to
start. The rest are optional: each missing piece disables its own
feature and leaves the rest working, which is why this tool reports what
it could not build rather than failing the whole run.

Disc formats: plain `.iso`/`.gcm` are read directly. Compressed formats
(`.rvz`, `.gcz`, `.wia`, `.ciso`) are converted to a temporary ISO first
using DolphinTool, which ships with Dolphin -- so those need free disc
space for the temporary copy, and the temporary copy is deleted after.

This tool deliberately does NOT gate on the disc's game ID. A ROM hack
built on the US release keeps the engine layout while being free to
relabel the disc, so the label is neither necessary nor sufficient (see
`profile.engine_signatures`). The structures below are validated as they
are read instead, and `check_game_compatibility.py` checks the real
thing -- the loaded binary -- once the game is running.
"""
import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _dialogue_extraction_tool as extraction
from battle_narrator import game_build
from extract_warp_collision_data import collision_data

DISC_MAGIC = 0xC2339F3D
"""GameCube disc magic word at 0x1C. Checked because every offset below
is read from the header at a fixed position: handed a file that is not a
disc image, an unchecked reader would follow four arbitrary bytes as an
FST offset and fail somewhere far less explicable."""

REQUIRED_ARCHIVES = {
    "common.fsys": "raw/files",
    "fight_common.fsys": "raw/files",
    "pocket_menu.fsys": "raw/files",
}

OPTIONAL_ARCHIVES = {
    # The Name Rater's dialogue is owned by its own room archive, not by
    # any of the global tables -- message 50803 lives in M3_houseD_1F and
    # nowhere else. It was hand-extracted in an earlier session, so it
    # existed only in the one tree that session produced; generated trees
    # lacked it and the narrator refused to start. Extracted here so every
    # build gets its own copy, which it must: the text is dialogue, and a
    # hack is free to rewrite it.
    "M3_houseD_1F.fsys": "rooms/files",
    "battle_disk.fsys": "raw/files",
    "worldmap.fsys": "worldmap/files",
    "pda_menu.fsys": "pda/files",
    "menu_common.fsys": "pda/files",
    "mailopen_menu.fsys": "pda/files",
    "mail000.fsys": "pda/files",
    "mail001.fsys": "pda/files",
    "mail002.fsys": "pda/files",
}

CONVERTIBLE_SUFFIXES = {".rvz", ".gcz", ".wia", ".ciso", ".wbfs"}
RAW_SUFFIXES = {".iso", ".gcm"}


class DiscError(RuntimeError):
    pass


class DiscImage:
    """Read-only reader for a plain GameCube disc image.

    Only the two things this project needs are implemented: the file
    table, and the executable. Both come straight out of the disc header
    -- DOL offset at 0x420, FST offset at 0x424, FST size at 0x428."""

    def __init__(self, path):
        self.path = Path(path)
        self.handle = self.path.open("rb")
        # Anything that goes wrong from here on has to close the handle:
        # every failure below is a "this is the wrong file" report the
        # caller is expected to catch and carry on from, and a bootstrap
        # run that tries several candidates should not leak one each time.
        try:
            header = self._read_at(0, 0x440)
            if struct.unpack_from(">I", header, 0x1C)[0] != DISC_MAGIC:
                raise DiscError(
                    f"{self.path.name} is not a GameCube disc image "
                    "(the disc magic word at 0x1C is missing). If this is "
                    "a compressed format such as .rvz, it needs converting "
                    "first -- this tool does that automatically when "
                    "DolphinTool can be found."
                )
            self.game_id = header[0x00:0x06].decode("ascii", "replace")
            self.revision = header[0x07]
            self.internal_name = header[0x20:0x60].split(b"\x00")[0].decode(
                "ascii", "replace")
            self.dol_offset = struct.unpack_from(">I", header, 0x420)[0]
            self.fst_offset = struct.unpack_from(">I", header, 0x424)[0]
            self.fst_size = struct.unpack_from(">I", header, 0x428)[0]
            self.files = self._read_file_table()
        except Exception:
            self.handle.close()
            raise

    def close(self):
        self.handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _read_at(self, offset, size):
        self.handle.seek(offset)
        data = self.handle.read(size)
        if len(data) != size:
            raise DiscError(
                f"{self.path.name} ends early -- wanted {size} bytes at "
                f"0x{offset:X}, got {len(data)}. The image is truncated.")
        return data

    def _read_file_table(self):
        """{name: (offset, size)} for every file on the disc.

        Flattened by basename deliberately: every archive this project
        wants is uniquely named, and the directory structure is not
        otherwise interesting. A duplicate basename would be a surprise
        worth hearing about, so it raises rather than silently keeping
        one of the two."""
        raw = self._read_at(self.fst_offset, self.fst_size)
        entry_count = struct.unpack_from(">I", raw, 8)[0]
        entries_end = entry_count * 12
        if entries_end > len(raw):
            raise DiscError(
                f"{self.path.name}: file table claims {entry_count} entries "
                f"but is only {len(raw)} bytes. The image is corrupt.")
        names = raw[entries_end:]
        table = {}
        for index in range(1, entry_count):
            base = index * 12
            is_directory = raw[base]
            if is_directory:
                continue
            name_offset = int.from_bytes(raw[base + 1:base + 4], "big")
            end = names.index(b"\x00", name_offset)
            name = names[name_offset:end].decode("ascii", "replace")
            offset, size = struct.unpack_from(">II", raw, base + 4)
            if name in table and table[name] != (offset, size):
                raise DiscError(
                    f"{self.path.name}: two different files are both named "
                    f"{name!r}; this disc layout is not understood.")
            table[name] = (offset, size)
        return table

    def read(self, name):
        if name not in self.files:
            raise DiscError(f"{self.path.name} has no file named {name!r}")
        offset, size = self.files[name]
        return self._read_at(offset, size)

    def read_dol(self):
        """main.dol is NOT in the file table -- it sits at its own header
        offset, with no length field anywhere. Its size is the end of its
        furthest section, which is why the section table is walked here
        rather than a fixed size being assumed."""
        header = self._read_at(self.dol_offset, 0xE0)
        offsets = struct.unpack_from(">18I", header, 0x00)
        sizes = struct.unpack_from(">18I", header, 0x90)
        end = max(
            (offset + size for offset, size in zip(offsets, sizes) if size),
            default=0)
        if not end:
            raise DiscError(
                f"{self.path.name}: main.dol has no sections; not an "
                "executable this tool can read.")
        return self._read_at(self.dol_offset, end)


def dol_string_tables(dol):
    """Every localised string table inside main.dol, as {id: text}.

    This is where the menu, save and system text lives -- the tables the
    scripts use are in `common.fsys` instead, and neither covers the
    other.

    A table is a 16-byte header followed by `count` eight-byte
    (id, offset) records and then the encoded text, with offsets relative
    to the start of the table. The header is what makes them findable:

        0x00  u32   table id
        0x04  u16   number of entries
        0x06  2ch   two-letter uppercase language marker, e.g. "US", "JP"
        0x08  8     zero padding

    The language marker plus the zero padding is a specific enough
    signature to sweep the whole executable for, and every candidate is
    then required to have all of its entry offsets land past its own
    entry array and inside the file. Scanning beats hardcoding the three
    known addresses: those are US-revision-0 facts, and a ROM hack is
    free to move, resize or add tables.

    The marker is NOT filtered to "US" -- on a retail US disc most of the
    English text lives in a table still marked "JP", so trusting the
    marker to mean anything beyond "this looks like a table header" would
    silently drop about four fifths of the strings."""
    size = len(dol)
    combined = {}
    tables = []
    for start in range(0, size - 0x10, 4):
        if dol[start + 8:start + 0x10] != b"\x00" * 8:
            continue
        marker = dol[start + 6:start + 8]
        if not (marker.isascii() and marker.isalpha() and marker.isupper()):
            continue
        count = struct.unpack_from(">H", dol, start + 4)[0]
        if count < 1 or start + 0x10 + count * 8 > size:
            continue
        first_string = 0x10 + count * 8
        if not all(
            first_string <= struct.unpack_from(
                ">I", dol, start + 0x10 + index * 8 + 4)[0] < size - start
            for index in range(count)
        ):
            continue
        tables.append((start, count))
        for string_id, tokens in extraction.decode_string_table(
                dol[start:]).items():
            # First table wins. Ids are unique across the real tables, so
            # this only matters if a false positive slipped through, and
            # preferring the earlier find keeps the result deterministic.
            combined.setdefault(string_id, tokens)
    return (
        {str(k): extraction.render_tokens(v) for k, v in combined.items()},
        tables,
    )


def find_dolphin_tool(explicit=None):
    """DolphinTool, for disc formats that are not a plain ISO.

    Looked for beside Dolphin.exe and on PATH. It is not needed at all
    for `.iso`/`.gcm`, so a failure here is only reported when a
    conversion is actually required."""
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_file():
            raise DiscError(f"No DolphinTool at {candidate}")
        return candidate
    found = shutil.which("DolphinTool") or shutil.which("dolphin-tool")
    if found:
        return Path(found)
    dolphin = shutil.which("Dolphin")
    if dolphin:
        beside = Path(dolphin).with_name("DolphinTool.exe")
        if beside.is_file():
            return beside
    return None


def to_plain_iso(disc, dolphin_tool, workdir, log):
    """Yield a plain-ISO path for `disc`, converting only if needed."""
    suffix = Path(disc).suffix.lower()
    if suffix in RAW_SUFFIXES:
        return Path(disc), None
    if suffix not in CONVERTIBLE_SUFFIXES:
        raise DiscError(
            f"Unrecognised disc format {suffix!r}. Supported: "
            + ", ".join(sorted(RAW_SUFFIXES | CONVERTIBLE_SUFFIXES)))
    tool = find_dolphin_tool(dolphin_tool)
    if tool is None:
        raise DiscError(
            f"{suffix} images have to be converted to a plain ISO first, "
            "which needs DolphinTool (it ships with Dolphin). Point at it "
            "with --dolphin-tool, or supply an .iso instead."
        )
    target = Path(workdir) / "converted.iso"
    log(f"Converting {Path(disc).name} to a temporary ISO (this is the "
        f"slow step, and needs free space for a full-size copy)...")
    result = subprocess.run(
        [str(tool), "convert", "-i", str(disc), "-o", str(target),
         "-f", "iso"],
        capture_output=True, text=True)
    if result.returncode != 0 or not target.is_file():
        raise DiscError(
            f"DolphinTool could not convert {Path(disc).name}: "
            f"{result.stderr.strip() or result.stdout.strip()}")
    return target, target


def write_archives(disc, out, names_to_subdir, log, required):
    """Copy named FSYS archives off the disc. Returns the failures."""
    problems = []
    for name, subdir in sorted(names_to_subdir.items()):
        destination = out / subdir / name
        try:
            data = disc.read(name)
        except DiscError as exc:
            problems.append(f"{name}: {exc}")
            continue
        # Structural proof that this is the archive we think it is, before
        # anything is written -- a disc that parses as a disc can still be
        # a different game.
        try:
            extraction.parse_fsys_index(data)
        except Exception as exc:
            problems.append(f"{name}: not a readable FSYS archive ({exc})")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        log(f"  {subdir}/{name}  ({len(data) / 1e6:.1f} MB)")
    if required and problems:
        raise DiscError(
            "This disc image is missing files the companion cannot run "
            "without:\n  " + "\n  ".join(problems))
    return problems


def write_dol_strings(disc, out, log):
    dol = disc.read_dol()
    strings, tables = dol_string_tables(dol)
    if not strings:
        raise DiscError(
            "No string tables were found in main.dol. This disc's "
            "executable is not laid out the way the companion expects.")
    destination = out / "dol_strings.json"
    destination.write_text(
        json.dumps(strings, ensure_ascii=False, indent=1), encoding="utf-8")
    found = ", ".join(f"0x{start:X}({count})" for start, count in tables)
    log(f"  dol_strings.json  ({len(strings)} strings from {len(tables)} "
        f"tables: {found})")
    return len(strings)


def write_collision(disc, out, log):
    """Per-room collision, swept rather than listed.

    Which archives hold a room's collision is a property of the disc, not
    something to hardcode as a room list -- a hack can add, rename or
    remove rooms. Every archive is offered to `collision_data`, and the
    ones that yield exactly one parseable CCD are rooms by definition."""
    destination = out / "collision"
    destination.mkdir(parents=True, exist_ok=True)
    written = 0
    for name in sorted(disc.files):
        if not name.endswith(".fsys"):
            continue
        try:
            data = collision_data(disc.read(name), name)
        except Exception:
            continue
        (destination / (name[:-len(".fsys")] + ".ccd")).write_bytes(data)
        written += 1
    log(f"  collision/  ({written} rooms)")
    return written


def dol_section_table(dol):
    """[(index, file_offset, address, size)] for each populated section."""
    offsets = struct.unpack_from(">18I", dol, 0x00)
    addresses = struct.unpack_from(">18I", dol, 0x48)
    sizes = struct.unpack_from(">18I", dol, 0x90)
    return [
        (index, offsets[index], addresses[index], sizes[index])
        for index in range(18) if sizes[index]
    ]


def bootstrap(disc_path, out, dolphin_tool=None, log=print, per_build=True):
    """Generate a data tree from `disc_path`.

    With `per_build`, `out` is treated as a parent and the data lands in a
    subdirectory named for the disc, so generating from a second disc adds
    a tree instead of overwriting the first. That is what lets the
    companion pick the right one at runtime -- see `game_build.py`."""
    out = Path(out)
    workdir = Path(tempfile.mkdtemp(prefix="xg-bootstrap-"))
    temporary_iso = None
    try:
        iso_path, temporary_iso = to_plain_iso(
            disc_path, dolphin_tool, workdir, log)
        with DiscImage(iso_path) as disc:
            log(f"Disc: {disc.internal_name.strip()}  "
                f"[{disc.game_id} rev {disc.revision}]  "
                f"{len(disc.files)} files")
            try:
                fingerprint = game_build.fingerprint_from_dol(
                    disc.read_dol(), dol_section_table(disc.read_dol()))
            except ValueError as exc:
                raise DiscError(
                    f"Could not identify this build: {exc}. The companion "
                    "would not be able to tell it apart from another disc."
                ) from exc
            if per_build:
                out = out / f"{disc.game_id}-{fingerprint}"
            out.mkdir(parents=True, exist_ok=True)
            game_build.write_stamp(
                out, fingerprint, source=disc_path, game_id=disc.game_id,
                revision=disc.revision,
                internal_name=disc.internal_name.strip())
            log(f"Build: {disc.internal_name.strip()} fingerprint "
                f"{fingerprint}")
            log("Required data:")
            write_archives(disc, out, REQUIRED_ARCHIVES, log, required=True)
            write_dol_strings(disc, out, log)
            log("Optional data:")
            optional_problems = write_archives(
                disc, out, OPTIONAL_ARCHIVES, log, required=False)
            rooms = write_collision(disc, out, log)
            if not rooms:
                optional_problems.append(
                    "collision: no rooms found, so warp and door navigation "
                    "will be unavailable")
        log("")
        if optional_problems:
            log("Finished, with some optional features unavailable:")
            for problem in optional_problems:
                log(f"  - {problem}")
        else:
            log("Finished. All game data generated.")
        log(f"Data written to: {out}")
        return 0
    finally:
        if temporary_iso is not None and temporary_iso.exists():
            temporary_iso.unlink()
        shutil.rmtree(workdir, ignore_errors=True)


def parser():
    ap = argparse.ArgumentParser(
        description="Generate the companion's local game-data indexes "
                    "from your own disc image.")
    ap.add_argument(
        "--disc", required=True, type=Path,
        help="Your own Pokemon XD / XG disc image (.iso, .gcm, .rvz, "
             ".gcz, .wia, .ciso)")
    ap.add_argument(
        "--output", type=Path,
        default=Path(__file__).resolve().parent / "_dialogue_extraction",
        help="Where to write the generated data (default: the location "
             "the companion reads). One subdirectory is created per disc, "
             "so running this for a second game adds to it rather than "
             "replacing what is already there.")
    ap.add_argument(
        "--flat", action="store_true",
        help="Write straight into --output instead of a per-disc "
             "subdirectory. Only one disc's data can live there at a time.")
    ap.add_argument(
        "--dolphin-tool", type=Path, default=None,
        help="Path to DolphinTool.exe, only needed for compressed disc "
             "formats (found automatically beside Dolphin if possible)")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    if not args.disc.is_file():
        print(f"No disc image at {args.disc}", file=sys.stderr)
        return 2
    try:
        return bootstrap(args.disc, args.output, args.dolphin_tool,
                         per_build=not args.flat)
    except DiscError as exc:
        print(f"\nCould not generate game data:\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
