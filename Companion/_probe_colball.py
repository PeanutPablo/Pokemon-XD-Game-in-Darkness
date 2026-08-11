"""Read-only live probe: the peopleInfo collision-ball radii.

Step 1 of the swept-circle passability work. `heroMove.s:1186-1196` moves the
real player by fetching its `peopleInfo` record, reading
`peopleInfoBiosGetColBallSize`, and sweeping that ball against the CCD hit
model via `GScolsys2HitCollision`. Pathfinding should ask the same question
with the same radius instead of sampling five lines between tile centres.

This probe reads the whole `peopleInfo` table and reports the distribution of
`colBallSize` (+0x10) and `talkDistance` (+0x24), using the addresses the
companion already trusts in production (`profile.py`).

Reads only. Attaches alongside the running narrator, which is safe: both are
pure readers.
"""
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dolphin_memory_engine as dme

from battle_narrator.profile import XD_US_REV0 as P

COL_BALL_SIZE_OFFSET = 0x10


def f32(address):
    raw = dme.read_bytes(address, 4)
    return struct.unpack(">f", raw)[0]


def u32(address):
    return struct.unpack(">I", dme.read_bytes(address, 4))[0]


def main():
    dme.hook()
    if not dme.is_hooked():
        print("Dolphin not found / not hooked")
        return 1
    # Double indirection, matching npc_beacons.py: the "count root" holds a
    # POINTER to the count, not the count itself.
    count_root = u32(P.people_info_count_root)
    count = u32(count_root)
    root = u32(P.people_info_root)
    print(f"people_info count root 0x{P.people_info_count_root:08X} "
          f"-> 0x{count_root:08X} -> {count}")
    print(f"people_info root      0x{P.people_info_root:08X} -> 0x{root:08X}")
    print(f"stride 0x{P.people_info_stride:X}, "
          f"colBallSize +0x{COL_BALL_SIZE_OFFSET:02X}, "
          f"talkDistance +0x{P.people_info_talk_distance_offset:02X}")
    print()
    if not (0x80000000 <= root < 0x81800000) or not (0 < count < 4096):
        print("implausible root/count -- refusing to read")
        return 1

    balls, talks = Counter(), Counter()
    rows = []
    for index in range(count):
        base = root + index * P.people_info_stride
        try:
            ball = f32(base + COL_BALL_SIZE_OFFSET)
            talk = f32(base + P.people_info_talk_distance_offset)
        except Exception as exc:                      # noqa: BLE001
            print(f"  record {index}: read failed: {exc}")
            break
        if not (0.0 <= ball < 1000.0) or not (0.0 <= talk < 1000.0):
            continue
        balls[round(ball, 3)] += 1
        talks[round(talk, 3)] += 1
        rows.append((index, ball, talk))

    print(f"records read: {len(rows)}")
    print()
    print("colBallSize distribution (radius the engine sweeps for movement):")
    for value, n in sorted(balls.items()):
        bar = "#" * min(50, n)
        print(f"   {value:>8.3f}  x{n:<5} {bar}")
    print()
    print("talkDistance distribution (for comparison -- staging, not collision):")
    for value, n in sorted(talks.items()):
        print(f"   {value:>8.3f}  x{n}")
    print()
    distinct = sorted(balls)
    print(f"distinct colBallSize values: {len(distinct)} -> {distinct[:12]}")
    if distinct:
        print(f"min {distinct[0]}, max {distinct[-1]}")
        print()
        print("Implication for pathfinding: a tile must be able to represent")
        print(f"a passage the player fits through, i.e. ~{2 * distinct[0]:.1f} "
              f"units across at minimum.")
        print(f"Current TILE_SIZE is 8.0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
