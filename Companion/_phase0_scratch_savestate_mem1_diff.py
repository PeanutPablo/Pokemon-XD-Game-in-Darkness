"""
Diffs the raw MEM1 dumps produced by _phase0_scratch_savestate_diff.py.
Pure offline byte comparison -- no live emulator connection.

Compares three consecutive transitions (each corresponding to exactly one
controller press the user made and then saved a state):
  base            -> down1          : effect of 1x Down
  down1           -> down1right1    : effect of 1x Right
  down1right1     -> down1right1up1 : effect of 1x Up

For each transition, finds every 4-byte-aligned word that changed, then
reports:
  1. A per-0x1000-region histogram (to spot noisy regions like XFB/audio
     vs. tight clusters of static-data changes).
  2. Full detail (old -> new value) restricted to a configurable address
     window of interest.
  3. Addresses that changed in ALL THREE transitions (strong candidates
     for something the menu-navigation code touches on every input).
"""
import os
import sys

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
MEM1_BASE_VADDR = 0x80000000

FILES = [
    ("base", "save.sav.mem1.bin"),
    ("down1", "save with 1 down press.sav.mem1.bin"),
    ("down1right1", "save with 1 down then 1 right press.sav.mem1.bin"),
    ("down1right1up1", "save with 1 down press 1 right press and 1 up press.sav.mem1.bin"),
]

# Address window of interest for detailed reporting -- matches the range
# where previously-confirmed static globals (e.g. menuFightStatus at
# 0x804EA728) live, avoiding the huge, expected-to-be-noisy XFB/audio
# regions elsewhere in MEM1.
DETAIL_LO = 0x80300000
DETAIL_HI = 0x80600000


def load(name):
    path = os.path.join(LOG_DIR, name)
    with open(path, "rb") as f:
        return f.read()


def diff_words(a, b):
    """Returns dict {vaddr: (old_u32, new_u32)} for every changed 4-byte-aligned word."""
    changed = {}
    n = min(len(a), len(b))
    for off in range(0, n - 3, 4):
        if a[off:off + 4] != b[off:off + 4]:
            vaddr = MEM1_BASE_VADDR + off
            old = int.from_bytes(a[off:off + 4], "big")
            new = int.from_bytes(b[off:off + 4], "big")
            changed[vaddr] = (old, new)
    return changed


def histogram(changed, bucket=0x1000):
    buckets = {}
    for vaddr in changed:
        b = vaddr - (vaddr % bucket)
        buckets[b] = buckets.get(b, 0) + 1
    return buckets


def main():
    data = {}
    for label, fname in FILES:
        print(f"Loading {label} ({fname}) ...")
        data[label] = load(fname)

    transitions = [
        ("base->down1 (press: Down)", "base", "down1"),
        ("down1->down1right1 (press: Right)", "down1", "down1right1"),
        ("down1right1->down1right1up1 (press: Up)", "down1right1", "down1right1up1"),
    ]

    all_changed = []
    for title, a_label, b_label in transitions:
        print(f"\n=== {title} ===")
        changed = diff_words(data[a_label], data[b_label])
        print(f"Total changed 4-byte words: {len(changed)}")
        all_changed.append(changed)

        buckets = histogram(changed)
        top_buckets = sorted(buckets.items(), key=lambda kv: -kv[1])[:15]
        print("Top changed 0x1000 regions (region_start: count):")
        for b, count in top_buckets:
            print(f"  0x{b:08X}: {count}")

        detail = {v: vals for v, vals in changed.items() if DETAIL_LO <= v < DETAIL_HI}
        print(f"\nDetail within 0x{DETAIL_LO:08X}-0x{DETAIL_HI:08X} ({len(detail)} words):")
        for vaddr in sorted(detail):
            old, new = detail[vaddr]
            print(f"  0x{vaddr:08X}: 0x{old:08X} -> 0x{new:08X}")

    common = set(all_changed[0]) & set(all_changed[1]) & set(all_changed[2])
    common_in_window = sorted(v for v in common if DETAIL_LO <= v < DETAIL_HI)
    print(f"\n=== Addresses changed in ALL THREE transitions, within 0x{DETAIL_LO:08X}-0x{DETAIL_HI:08X} ===")
    print(f"Count: {len(common_in_window)}")
    for vaddr in common_in_window:
        vals = [all_changed[i][vaddr] for i in range(3)]
        print(f"  0x{vaddr:08X}: " + "  ".join(f"[{old:08X}->{new:08X}]" for old, new in vals))

    common_global = sorted(common)
    print(f"\n=== Addresses changed in ALL THREE transitions, ANYWHERE in MEM1 ===")
    print(f"Count: {len(common_global)}")
    for vaddr in common_global[:200]:
        vals = [all_changed[i][vaddr] for i in range(3)]
        print(f"  0x{vaddr:08X}: " + "  ".join(f"[{old:08X}->{new:08X}]" for old, new in vals))
    if len(common_global) > 200:
        print(f"  ... ({len(common_global) - 200} more, truncated)")


if __name__ == "__main__":
    sys.exit(main())
