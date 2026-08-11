"""Generate Companion/assets/room_services.json from the extracted scripts.

Offline, run-once-per-extraction. A room whose script reaches a service's
own standard-library call IS that service -- the same evidence rule
`npc_roles.py` and `interactable_roles.py` use, applied to room naming.

    python Companion/build_room_service_table.py
"""
import json
from pathlib import Path

from battle_narrator.npc_roles import parse_room_script

BASE = Path(__file__).resolve().parent
ROOMS = BASE / "_dialogue_extraction" / "rooms"
OUT = BASE / "assets" / "room_services.json"

SERVICE_MARKERS = {
    # The Day Care is the case that matters: nothing in a room CODE says
    # `M3_houseD_1F` is one, and the hand-written table had the label on
    # `M3_houseB_1F`, which has no Daycare call at all.
    "Day-Care": ("Daycare::depositPkm",),
}


def main():
    services = {}
    for path in sorted(ROOMS.glob("*.txt")):
        graph = parse_room_script(
            path.read_text(encoding="utf-8", errors="replace"))
        calls = set()
        for _, std in graph.values():
            calls |= std
        for service, required in SERVICE_MARKERS.items():
            if all(call in calls for call in required):
                services[path.stem] = service
    OUT.write_text(
        json.dumps(services, indent=2, sort_keys=True), encoding="utf-8")
    print(f"rooms with a derived service: {len(services)}")
    for code, service in sorted(services.items()):
        print(f"  {code:24s} {service}")


if __name__ == "__main__":
    main()
