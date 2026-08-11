"""
Refines the raw-changed-word list from _phase0_scratch_savestate_mem1_diff.py:
keeps only addresses whose value is a small, plausible index/enum (<= MAX_VAL)
in ALL FOUR snapshots (not just "changed"), and that changed in all three
transitions. This filters out the large floating-point/pointer noise from
particle/physics/animation systems that dominates a raw diff.
"""
import os
import sys

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
MEM1_BASE_VADDR = 0x80000000
MAX_VAL = 0x20

FILES = [
    ("base", "save.sav.mem1.bin"),
    ("down1", "save with 1 down press.sav.mem1.bin"),
    ("down1right1", "save with 1 down then 1 right press.sav.mem1.bin"),
    ("down1right1up1", "save with 1 down press 1 right press and 1 up press.sav.mem1.bin"),
]


def load(name):
    path = os.path.join(LOG_DIR, name)
    with open(path, "rb") as f:
        return f.read()


def main():
    data = {}
    for label, fname in FILES:
        data[label] = load(fname)

    labels = [l for l, _ in FILES]
    n = min(len(data[l]) for l in labels)

    results = []
    for off in range(0, n - 3, 4):
        vals = [int.from_bytes(data[l][off:off + 4], "big") for l in labels]
        if all(v <= MAX_VAL for v in vals):
            if vals[0] != vals[1] or vals[1] != vals[2] or vals[2] != vals[3]:
                vaddr = MEM1_BASE_VADDR + off
                results.append((vaddr, vals))

    print(f"Candidates with all 4 snapshot values <= 0x{MAX_VAL:X} and not constant: {len(results)}")
    for vaddr, vals in results:
        print(f"  0x{vaddr:08X}: base={vals[0]} down1={vals[1]} down1right1={vals[2]} down1right1up1={vals[3]}")


if __name__ == "__main__":
    sys.exit(main())
