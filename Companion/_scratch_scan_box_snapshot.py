"""Passive, offline scan of an already-captured MEM1 snapshot (no further
live interaction) for a repeating array of Pokemon-like structs -- the
Pokemon Storage box grid. Reuses the exact plausibility checks already
proven for finding the live party array (valid species range, level 1-100,
null-padded ASCII nickname), but instead of looking for one instance,
looks for a RUN of many instances at a fixed stride in a row, which is a
much stronger, purely-structural signal for "this is a box array" than a
single match could ever be.
"""
import struct
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = path.read_bytes()
base_addr = 0x80000000

CANDIDATE_STRIDES = [0xC4, 0x8C, 0x80, 0x74, 0x64, 0x58, 0x50, 0x48, 0x40]


def looks_like_nickname(chunk):
    end = chunk.find(b"\x00")
    if end <= 0:
        return False
    text = chunk[:end]
    if not all(32 <= b < 127 for b in text):
        return False
    return chunk[end:] == b"\x00" * (len(chunk) - end)


def plausible_species_at(species_offset_data):
    species = struct.unpack_from(">H", species_offset_data, 0)[0]
    return 1 <= species <= 440


def scan_stride(stride, nickname_offset=0x4E, nickname_len=11, level_offset=0x11):
    best_runs = []
    step = 4
    limit = len(data) - stride
    pos = 0
    run_start = None
    run_len = 0
    while pos < limit:
        species_ok = plausible_species_at(data[pos:pos + 2])
        level = data[pos + level_offset] if pos + level_offset < len(data) else 0
        level_ok = 1 <= level <= 100
        nick_ok = False
        if pos + nickname_offset + nickname_len <= len(data):
            nick_ok = looks_like_nickname(data[pos + nickname_offset: pos + nickname_offset + nickname_len])
        valid = species_ok and level_ok and nick_ok
        if valid:
            if run_start is None:
                run_start = pos
                run_len = 1
            else:
                run_len += 1
        else:
            if run_start is not None and run_len >= 4:
                best_runs.append((run_start, run_len))
            run_start = None
            run_len = 0
        pos += stride
    if run_start is not None and run_len >= 4:
        best_runs.append((run_start, run_len))
    return best_runs


for stride in CANDIDATE_STRIDES:
    runs = scan_stride(stride)
    if runs:
        print(f"stride=0x{stride:X}: {len(runs)} run(s)")
        for start, length in runs:
            addr = base_addr + start
            print(f"  run at 0x{addr:08X}, {length} consecutive plausible slots")
