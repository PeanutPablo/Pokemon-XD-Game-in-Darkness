"""Live probe: the engine's scripted-stick override, as used by autowalk.

**This is the ONLY script in this project that writes memory in order to
move the player, and it does so deliberately.** `--verify` alone is
read-only and is what should be run first; a write happens only when
`--walk` is passed explicitly.

Everything autowalk rests on was derived statically from `xd-decomp`
(`_setStickData` 0x8014E7D4, `_getStickData` 0x8014E7F8, the flag at
`HeroMove+0x3AE`) and nothing has ever been written to those addresses on a
running game. This closes that gap in two separate steps, so a failure at
the first one costs nothing:

  --verify  Compares both accessors against the decomp's bytes and reports
            the current flag/stick values. Reads only. Run this first, and
            on any new build. It answers "is this the same engine", which is
            the question a byte comparison can actually settle.

  --walk    Sets the flag and holds one fixed stick direction for a short
            bounded time, then releases and reports how far the player
            moved. This is the step that proves the mechanism, and it is the
            first time anything in this project has written these bytes on a
            live game.

Run `--walk` somewhere deliberately boring: an indoor room with space ahead,
no ledges, no grass, standing still, not in a menu or conversation. The
whole point is to answer "does the character walk, and does it stop", which
does not need an interesting location and is much easier to judge in a dull
one. The release is in a `finally`, so an interrupt still hands the
controller back.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dolphin_memory_engine as dme

from battle_narrator.hero_stick import (
    GET_STICK_ADDRESS,
    GET_STICK_BYTES,
    SET_STICK_ADDRESS,
    SET_STICK_BYTES,
)
from battle_narrator.memory import MemoryReader
from battle_narrator.npc_beacons import NPCMemorySource
from battle_narrator.profile import XD_US_REV0 as P

FLAG = P.hero_move_base + P.hero_move_stick_override_offset
STICK = P.hero_move_base + P.hero_move_stick_data_offset
FULL = P.hero_move_stick_full_deflection

DIRECTIONS = {
    # Camera-relative, per _getStickData's own D-pad branch: up is -Y.
    "forward": (0, -FULL),
    "back": (0, FULL),
    "left": (-FULL, 0),
    "right": (FULL, 0),
}


def signed(value):
    return value - 256 if value >= 128 else value


def player_position(pose_source):
    """Production's own resolution chain, not a re-derived one -- the hero
    model is found by a keyed walk of the resource list (see
    `NPCMemorySource.hero_model_address`), and a probe that guessed at it
    could report "did not move" for a reason that has nothing to do with
    the thing being tested."""
    position = pose_source.player_pose().position
    return position.x, position.y, position.z


def verify():
    setter = dme.read_bytes(SET_STICK_ADDRESS, len(SET_STICK_BYTES))
    getter = dme.read_bytes(GET_STICK_ADDRESS, len(GET_STICK_BYTES))
    ok = setter == SET_STICK_BYTES and getter == GET_STICK_BYTES
    print(f"_setStickData @ 0x{SET_STICK_ADDRESS:08X}: "
          f"{'match' if setter == SET_STICK_BYTES else 'DIFFERS'}")
    print(f"_getStickData @ 0x{GET_STICK_ADDRESS:08X}: "
          f"{'match' if getter == GET_STICK_BYTES else 'DIFFERS'}")
    flag = dme.read_byte(FLAG)
    sticks = tuple(signed(b) for b in dme.read_bytes(STICK, 4))
    print(f"override flag = {flag}, stick bytes = {sticks}")
    if flag:
        print("  NOTE: the flag is already set -- the game is driving the "
              "hero itself right now (a cutscene, or a slow-stop in "
              "progress). Do not run --walk against that.")
    return ok


def walk(direction, seconds, pose_source):
    x, y = DIRECTIONS[direction]
    start = player_position(pose_source)
    print(f"start position: ({start[0]:.2f}, {start[1]:.2f}, {start[2]:.2f})")
    print(f"holding {direction} = ({x}, {y}) for {seconds:g}s")
    data = bytes((1, x & 0xFF, y & 0xFF, x & 0xFF, y & 0xFF))
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            # Rewritten each tick rather than set once: the flag is
            # level-held, but any of the engine's own paths that clear it
            # (initialisation, a slow-stop) would otherwise silently end the
            # test and make a real failure look like a partial success.
            dme.write_bytes(FLAG, data)
            time.sleep(0.05)
    finally:
        dme.write_bytes(FLAG, b"\x00")
        print("released")
    time.sleep(0.5)
    end = player_position(pose_source)
    print(f"end position:   ({end[0]:.2f}, {end[1]:.2f}, {end[2]:.2f})")
    moved = ((end[0] - start[0]) ** 2 + (end[2] - start[2]) ** 2) ** 0.5
    print(f"moved {moved:.2f} units horizontally, "
          f"{end[1] - start[1]:+.2f} vertically")
    print(f"flag now reads {dme.read_byte(FLAG)} (expected 0)")
    if moved < 1.0:
        print("VERDICT: the player did not move. Either the game was paused, "
              "control was not free (menu/dialogue/cutscene), or the "
              "mechanism does not work as derived.")
    else:
        print("VERDICT: the override moved the player.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true",
                        help="read-only signature and state check")
    parser.add_argument("--walk", choices=sorted(DIRECTIONS),
                        help="WRITES MEMORY: hold this direction briefly")
    parser.add_argument("--seconds", type=float, default=1.0,
                        help="how long to hold (default 1.0, max 3.0)")
    args = parser.parse_args()
    if not args.verify and not args.walk:
        parser.error("pass --verify (read-only) or --walk DIRECTION")
    if args.seconds <= 0 or args.seconds > 3.0:
        parser.error("--seconds must be between 0 and 3.0")

    dme.hook()
    if not dme.is_hooked():
        print(f"not hooked: {dme.get_status()}")
        return 1
    print("disc header:", dme.read_bytes(0x80000000, 8))
    matched = verify()
    if not matched:
        print("\nSignature mismatch: these addresses do not describe this "
              "build. Not writing anything.")
        return 1
    if args.walk:
        print()
        pose_source = NPCMemorySource(MemoryReader(dme, P), P)
        walk(args.walk, args.seconds, pose_source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
