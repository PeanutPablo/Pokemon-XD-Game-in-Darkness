"""Answer the compatibility question from a disc image, without booting it.

`check_game_compatibility.py` asks the same question of a running Dolphin.
This asks it of a file, which is better in two ways: it can be answered
before the game is ever launched, and it can compare two images directly to
show exactly what a ROM hack moved.

The gate is identical, deliberately -- `profile.engine_signatures`, exact
byte matches at fixed addresses in engine-internal functions. The only
difference is where the bytes come from: at runtime they are read out of
MEM1, here they are read out of `main.dol`'s section table and mapped back
to the addresses the loader will copy them to. A signature that matches
statically will match at runtime, because the loader copies sections
verbatim.

    python check_image_compatibility.py GAME.iso
    python check_image_compatibility.py GAME.iso --against BASE.iso

`--against` adds a section-by-section diff of the two executables, which is
what turns "supported" into "supported, and here is what changed".

Read-only. Neither image is modified.
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bootstrap_game_data import DiscError, DiscImage  # noqa: E402
from battle_narrator.profile import XD_US_REV0  # noqa: E402

SECTION_COUNT = 18
TEXT_SECTIONS = 7


def dol_sections(dol):
    """[(index, file_offset, address, size)] for every populated section."""
    offsets = struct.unpack_from(">18I", dol, 0x00)
    addresses = struct.unpack_from(">18I", dol, 0x48)
    sizes = struct.unpack_from(">18I", dol, 0x90)
    return [
        (index, offsets[index], addresses[index], sizes[index])
        for index in range(SECTION_COUNT)
        if sizes[index]
    ]


def section_name(index):
    return f"text{index}" if index < TEXT_SECTIONS else f"data{index - TEXT_SECTIONS}"


def read_at_address(dol, sections, address, length):
    """The `length` bytes the loader will place at `address`, or None."""
    for _, file_offset, section_address, size in sections:
        if section_address <= address and address + length <= section_address + size:
            start = file_offset + (address - section_address)
            return dol[start:start + length]
    return None


def check(dol, profile):
    """[(name, address, expected, found_or_None)] for failing signatures."""
    sections = dol_sections(dol)
    failures = []
    for name, address, expected in profile.engine_signatures:
        found = read_at_address(dol, sections, address, len(expected))
        if found != expected:
            failures.append((name, address, expected, found))
    return failures


def describe_image(image, dol):
    print(f"Image           : {image.path.name}")
    print(f"Disc label      : {image.game_id} revision {image.revision}")
    print(f"Internal name   : {image.internal_name}")
    print(f"main.dol        : {len(dol):,} bytes at 0x{image.dol_offset:X}")


def compare(dol, other_dol, label, other_label):
    print(f"\n--- {label} main.dol vs {other_label} main.dol ---")
    sections = {i: (o, a, s) for i, o, a, s in dol_sections(dol)}
    other = {i: (o, a, s) for i, o, a, s in dol_sections(other_dol)}
    if set(sections) != set(other):
        print("Section layouts differ; the executables are not comparable "
              "section by section.")
        return
    print(f"{'section':<8} {'address':>10} {'size':>10}  changed bytes")
    identical = True
    for index in sorted(sections):
        offset, address, size = sections[index]
        other_offset, other_address, other_size = other[index]
        name = section_name(index)
        if (address, size) != (other_address, other_size):
            identical = False
            print(f"{name:<8} {address:#010x} {size:>10,}  "
                  f"MOVED/RESIZED (other: {other_address:#010x}, "
                  f"{other_size:,} bytes)")
            continue
        block = dol[offset:offset + size]
        other_block = other_dol[other_offset:other_offset + size]
        differing = sum(1 for a, b in zip(block, other_block) if a != b)
        if differing:
            identical = False
        share = differing * 100.0 / size if size else 0.0
        print(f"{name:<8} {address:#010x} {size:>10,}  "
              f"{differing:>10,} ({share:5.2f}%)")
    if identical:
        print("\nThe two executables are byte-identical.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--against", help="a second image to diff against")
    args = parser.parse_args(argv)

    profile = XD_US_REV0
    try:
        with DiscImage(args.image) as image:
            dol = image.read_dol()
            describe_image(image, dol)
            failures = check(dol, profile)
            base = None
            if args.against:
                with DiscImage(args.against) as other:
                    base = (other.read_dol(), other.path.name)
    except (OSError, DiscError) as exc:
        print(f"ERROR: {exc}")
        return 2

    total = len(profile.engine_signatures)
    print(f"\nEngine checks   : {total - len(failures)} of {total} matched")
    for name, address, expected, found in failures:
        print(f"  MISMATCH {name} at {address:#010x}")
        print(f"     expected {expected.hex()}")
        if found is None:
            print("     found    (address is not in any loaded section)")
        else:
            print(f"     found    {found.hex()}")

    if base:
        compare(dol, base[0], Path(args.image).name, base[1])

    if failures:
        print("\nVERDICT: NOT SUPPORTED. This binary is not laid out the way")
        print("every address in the profile assumes. The narrator will refuse")
        print("to start, which is deliberate.")
        return 1

    print("\nVERDICT: SUPPORTED. Every engine signature is present at the")
    print("address the profile expects, so the code layout the narrator's")
    print("addresses depend on is intact.")
    print("\nThis says nothing about game DATA -- species, moves, trainers,")
    print("dialogue and map contents are all free to differ, and are read")
    print("from the game's own live tables rather than assumed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
