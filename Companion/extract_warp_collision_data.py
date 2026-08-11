"""Extract room CCDs from user-owned XD map FSYS archives for warp navigation."""
import argparse
from pathlib import Path

import _dialogue_extraction_tool as extraction
from battle_narrator.authoritative_warps import parse_interactable_region_centers


def collision_data(archive_bytes, label="archive"):
    """The one valid CCD inside an FSYS archive, or ValueError.

    Indexed rather than fully parsed: bootstrap_game_data.py sweeps every
    archive on the disc through here, and decompressing each archive's
    models and textures on the way past turns a ~20-second pass into a
    quarter of an hour. Only the type-3 candidates are decoded.

    "Exactly one" is the real contract, not "the first one" -- an archive
    with two parseable CCDs is a structure this code does not understand,
    and guessing between them would silently place a room's warps wrong."""
    entries = extraction.parse_fsys_index(archive_bytes)
    valid = []
    for entry in entries:
        if entry["type"] != 3:
            continue
        data = extraction.read_fsys_entry(archive_bytes, entry)
        try:
            parse_interactable_region_centers(data)
        except ValueError:
            continue
        valid.append(data)
    if len(valid) != 1:
        raise ValueError(f"{label}: expected one valid CCD, found {len(valid)}")
    return valid[0]


def extract_archive(path, output_dir):
    data = collision_data(Path(path).read_bytes(), str(path))
    output = Path(output_dir) / (Path(path).stem + ".ccd")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("archives", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    paths = []
    for value in args.archives:
        paths.extend(value.rglob("*.fsys") if value.is_dir() else (value,))
    successes = 0
    for path in paths:
        try:
            output = extract_archive(path, args.output)
        except ValueError as exc:
            print(f"skip: {exc}")
            continue
        print(output)
        successes += 1
    print(f"Extracted {successes} collision files.")
    return 0 if successes else 1


if __name__ == "__main__":
    raise SystemExit(main())
