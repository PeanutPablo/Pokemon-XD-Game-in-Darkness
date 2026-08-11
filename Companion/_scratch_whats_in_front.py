"""One-off, read-only diagnostic: report the nearest interactable entity in
front of the player right now, across every entity-nav category. Never
sends input, never writes memory -- attaches read-only exactly like the
running narrator, using the same profile/source construction as
phase1b_app.py."""
import json
import math
from pathlib import Path

import dolphin_memory_engine as dme

from battle_narrator.authoritative_warps import (
    AuthoritativeDoorEntitySource,
    AuthoritativeElevatorEntitySource,
    AuthoritativeWarpEntitySource,
    load_door_records,
    load_elevator_records,
    load_warp_records,
)
from battle_narrator.entity_nav import relative_geometry
from battle_narrator.entity_names import load_entity_names
from battle_narrator.entity_sources import CategoryFilteredEntitySource, NPCEntitySource
from battle_narrator.memory import MemoryReader
from battle_narrator.profile import XD_US_REV0

base = Path(__file__).parent

dme.hook()
if not dme.is_hooked():
    raise SystemExit("Dolphin is not readable.")
memory = MemoryReader(dme, XD_US_REV0)

room_codes = {
    int(key, 16): value
    for key, value in json.loads(
        (base / "assets" / "room_ids.json").read_text(encoding="utf-8")
    ).items()
}
common_fsys_path = base / "_dialogue_extraction" / "raw" / "files" / "common.fsys"
warp_collision_dir = base / "_dialogue_extraction" / "collision"
entity_names = load_entity_names(common_fsys_path)

npc_source = NPCEntitySource(memory, XD_US_REV0, entity_names)
sources = {
    "npc": npc_source,
    "item": CategoryFilteredEntitySource(memory, XD_US_REV0, "item"),
    "healing": CategoryFilteredEntitySource(memory, XD_US_REV0, "healing"),
    "elevator": AuthoritativeElevatorEntitySource(
        memory, XD_US_REV0, npc_source, load_elevator_records(common_fsys_path),
        warp_collision_dir, room_codes, room_codes),
    "door": AuthoritativeDoorEntitySource(
        memory, XD_US_REV0, npc_source, load_door_records(common_fsys_path),
        warp_collision_dir, room_codes, room_codes),
    "warp": AuthoritativeWarpEntitySource(
        memory, XD_US_REV0, npc_source, load_warp_records(common_fsys_path),
        warp_collision_dir, room_codes, room_codes),
}

from battle_narrator.memory import MemoryError as GameMemoryError

pose = None
for _ in range(20):
    try:
        pose = npc_source.player_pose()
        break
    except GameMemoryError:
        continue
if pose is None:
    raise SystemExit("Could not get a stable player pose after 20 tries.")
floor_id = memory.u16(XD_US_REV0.current_floor_id, "current floor id")
print(f"Room: {room_codes.get(floor_id, hex(floor_id))} (0x{floor_id:X})")
print(f"Player position: ({pose.position.x:.2f}, {pose.position.y:.2f}, {pose.position.z:.2f}), yaw={pose.yaw:.3f}")

candidates = []
for category, source in sources.items():
    for entity in source.entities():
        horizontal, forward, right, vertical = relative_geometry(pose, entity.position)
        angle = math.degrees(math.atan2(right, forward)) if horizontal > 0.01 else 0.0
        in_range = (
            entity.interaction_distance is not None
            and horizontal <= (entity.interaction_distance + XD_US_REV0.interaction_collision_allowance)
        )
        candidates.append((category, entity, horizontal, angle, in_range))

candidates.sort(key=lambda c: c[2])

print("\nAll entities on this floor, nearest first:")
for category, entity, horizontal, angle, in_range in candidates:
    label = entity.label or "(unnamed)"
    flag = " <-- IN INTERACTION RANGE" if in_range else ""
    print(f"  [{category}] {label}: distance={horizontal:.2f}, angle={angle:.1f} deg{flag}")

facing = [c for c in candidates if abs(c[3]) <= 35]
in_range = [c for c in candidates if c[4]]
print("\n--- Best guess for 'what am I standing in front of' ---")
if in_range:
    category, entity, horizontal, angle, _ = in_range[0]
    print(f"In interaction range: [{category}] {entity.label or '(unnamed)'} at distance {horizontal:.2f}, {angle:.1f} deg off center.")
elif facing:
    category, entity, horizontal, angle, _ = facing[0]
    print(f"Nearest thing roughly ahead (not yet in range): [{category}] {entity.label or '(unnamed)'} at distance {horizontal:.2f}, {angle:.1f} deg off center.")
else:
    print("Nothing tracked directly ahead nearby.")
