"""Apply a UPS patch, verifying every checksum the format carries.

Written so this project does not have to download and run an unvetted
patcher binary to produce its own target image. UPS is a small, fully
specified format, and -- unlike dragging a file onto a GUI patcher -- doing
it here means the three CRC32s the patch carries (patch, input, output) are
all checked and reported, so "the ROM hack built correctly" is a proven
statement rather than an assumption.

That matters especially for this machine, which holds two different disc
images that both call themselves GXXE01 revision 0 (see
Documentation/REPOSITORY_AUDIT.md). The patch's input CRC32 identifies which
one the hack's author actually built against, which no disc label can.

Usage:

    python apply_ups_patch.py --inspect PATCH.ups
    python apply_ups_patch.py --check-base PATCH.ups BASE.iso
    python apply_ups_patch.py PATCH.ups BASE.iso OUTPUT.iso

The base file is opened read-only and is never modified.
"""
import argparse
import mmap
import os
import shutil
import sys
import zlib

MAGIC = b"UPS1"
FOOTER = 12  # three little-endian u32 CRC32s: input, output, patch
COPY_CHUNK = 8 * 1024 * 1024


class PatchError(Exception):
    pass


def _read_vli(buf, pos):
    """Decode one UPS variable-length integer. Returns (value, new_pos)."""
    value = 0
    shift = 1
    while True:
        if pos >= len(buf):
            raise PatchError("patch ended in the middle of a number")
        byte = buf[pos]
        pos += 1
        value += (byte & 0x7F) * shift
        if byte & 0x80:
            return value, pos
        shift <<= 7
        value += shift


class UpsPatch:
    def __init__(self, data):
        if len(data) < len(MAGIC) + FOOTER:
            raise PatchError("file is too small to be a UPS patch")
        if data[:4] != MAGIC:
            raise PatchError(
                f"not a UPS patch: expected magic {MAGIC!r}, "
                f"found {data[:4]!r}"
            )
        self.data = data
        self.patch_crc_stored = int.from_bytes(data[-4:], "little")
        self.patch_crc_actual = zlib.crc32(data[:-4])
        self.input_crc = int.from_bytes(data[-12:-8], "little")
        self.output_crc = int.from_bytes(data[-8:-4], "little")
        pos = len(MAGIC)
        self.input_size, pos = _read_vli(data, pos)
        self.output_size, pos = _read_vli(data, pos)
        self.body_start = pos
        self.body_end = len(data) - FOOTER

    @property
    def self_consistent(self):
        return self.patch_crc_stored == self.patch_crc_actual

    def apply_to(self, view):
        """XOR the patch body over `view`, a writable buffer of output_size."""
        data = self.data
        pos = self.body_start
        end = self.body_end
        out = 0
        chunks = 0
        while pos < end:
            delta, pos = _read_vli(data, pos)
            out += delta
            stop = data.find(b"\x00", pos, end)
            if stop < 0:
                raise PatchError("patch ended without a chunk terminator")
            run = data[pos:stop]
            pos = stop + 1
            if run:
                if out + len(run) > self.output_size:
                    raise PatchError(
                        "patch writes past the end of the declared output size"
                    )
                current = view[out:out + len(run)]
                merged = (
                    int.from_bytes(current, "big") ^ int.from_bytes(run, "big")
                ).to_bytes(len(run), "big")
                view[out:out + len(run)] = merged
                out += len(run)
            out += 1  # the terminator occupies an output position
            chunks += 1
        return chunks


def crc32_file(path, label=None):
    size = os.path.getsize(path)
    done = 0
    crc = 0
    last_pct = -1
    with open(path, "rb") as handle:
        while True:
            block = handle.read(COPY_CHUNK)
            if not block:
                break
            crc = zlib.crc32(block, crc)
            done += len(block)
            if label and size:
                pct = done * 100 // size
                if pct != last_pct and pct % 10 == 0:
                    print(f"  {label}: {pct}%", flush=True)
                    last_pct = pct
    return crc


def describe(patch):
    print(f"Input size      : {patch.input_size:,} bytes")
    print(f"Output size     : {patch.output_size:,} bytes")
    print(f"Expects input   : CRC32 {patch.input_crc:08X}")
    print(f"Produces output : CRC32 {patch.output_crc:08X}")
    state = "OK" if patch.self_consistent else "CORRUPT"
    print(
        f"Patch integrity : {state} "
        f"(stored {patch.patch_crc_stored:08X}, "
        f"actual {patch.patch_crc_actual:08X})"
    )


def load(patch_path):
    with open(patch_path, "rb") as handle:
        patch = UpsPatch(handle.read())
    if not patch.self_consistent:
        raise PatchError(
            "the patch file's own CRC32 does not match -- it is corrupt or "
            "was not downloaded completely"
        )
    return patch


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patch")
    parser.add_argument("base", nargs="?")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--inspect", action="store_true",
                        help="print the patch header and exit")
    parser.add_argument("--check-base", action="store_true",
                        help="report whether BASE is the file this patch "
                             "expects, without writing anything")
    args = parser.parse_args(argv)

    try:
        patch = load(args.patch)
    except (OSError, PatchError) as exc:
        print(f"ERROR: {exc}")
        return 2
    describe(patch)

    if args.inspect:
        return 0
    if not args.base:
        parser.error("BASE is required unless --inspect is given")

    base_size = os.path.getsize(args.base)
    print(f"\nBase file       : {args.base}")
    print(f"Base size       : {base_size:,} bytes")
    if base_size != patch.input_size:
        print("\nVERDICT: WRONG BASE -- size does not match. Not patching.")
        return 1
    print("Hashing base (this reads the whole file)...", flush=True)
    base_crc = crc32_file(args.base, "base")
    print(f"Base CRC32      : {base_crc:08X}")
    if base_crc != patch.input_crc:
        print("\nVERDICT: WRONG BASE -- size matches but contents differ.")
        print("This is a different dump or build from the one the patch was")
        print("made against. Patching it would produce a corrupt image.")
        return 1
    print("Base matches the patch's expected input exactly.")

    if args.check_base:
        print("\nVERDICT: CORRECT BASE. Nothing written (--check-base).")
        return 0
    if not args.output:
        parser.error("OUTPUT is required unless --check-base is given")
    if os.path.exists(args.output):
        print(f"\nERROR: {args.output} already exists. Refusing to overwrite.")
        return 2

    print(f"\nCopying base to {args.output} ...", flush=True)
    shutil.copyfile(args.base, args.output)
    with open(args.output, "r+b") as handle:
        if patch.output_size != base_size:
            handle.truncate(patch.output_size)
        handle.flush()
        with mmap.mmap(handle.fileno(), 0) as view:
            print("Applying patch ...", flush=True)
            chunks = patch.apply_to(view)
            view.flush()
    print(f"Applied {chunks:,} patch chunks.")

    print("Hashing result ...", flush=True)
    out_crc = crc32_file(args.output, "output")
    print(f"Output CRC32    : {out_crc:08X}")
    if out_crc != patch.output_crc:
        print("\nVERDICT: FAILED -- the patched image does not match the")
        print("checksum the patch declares. Do not use this file.")
        return 1
    print("\nVERDICT: SUCCESS. The patched image matches the patch's declared")
    print("output checksum exactly. The base file was not modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
