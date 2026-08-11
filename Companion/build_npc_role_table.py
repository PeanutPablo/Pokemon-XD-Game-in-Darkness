"""Generate Companion/assets/npc_roles.json from the extracted room scripts.

Offline, run-once-per-extraction tool. Derives which talk script ids open a
Poke Mart or heal the party, generically, from the game's own scripts -- see
battle_narrator/npc_roles.py for why this replaces the room-id guess.

    python Companion/build_npc_role_table.py
"""
import json
from pathlib import Path

from battle_narrator.npc_roles import build_role_table

BASE = Path(__file__).resolve().parent
ROOMS = BASE / "_dialogue_extraction" / "rooms"
OUT = BASE / "assets" / "npc_roles.json"


def main():
    room_codes = {
        int(key, 16): value
        for key, value in json.loads(
            (BASE / "assets" / "room_ids.json").read_text(encoding="utf-8")
        ).items()
    }
    table = build_role_table(ROOMS, room_codes)
    OUT.write_text(
        json.dumps(
            {f"0x{room:X}": roles for room, roles in sorted(table.items())},
            indent=2, sort_keys=True),
        encoding="utf-8")
    total = sum(len(roles) for roles in table.values())
    print(f"rooms with roles: {len(table)}   role NPCs: {total}")
    for room, roles in sorted(table.items()):
        print(f"  0x{room:<4X} {room_codes.get(room, '?'):<22s} {roles}")


if __name__ == "__main__":
    main()
