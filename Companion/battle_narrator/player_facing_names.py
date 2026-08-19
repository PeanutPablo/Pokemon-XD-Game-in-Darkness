"""Translate authoritative game identifiers into player-facing labels."""
import re

LOCATION_NAMES = {
    "M1": "Phenac City", "M2": "Pyrite Town", "M3": "Agate Village",
    "M5": "Pokemon HQ Lab", "M6": "Gateon Port", "S1": "Outskirt Stand",
    "S2": "Snagem Hideout", "S3": "Kaminko's House", "D1": "Cipher Lab",
    "D2": "Mt. Battle", "D3": "S.S. Libra", "D4": "Realgam Tower",
    "D5": "Cipher Key Lair", "D6": "Citadark Isle", "D7": "Orre Colosseum",
}
"""Location per room-code prefix.

**Four entries were wrong until 2026-08-10**, and the project already held
the right answers in a second, contradictory table
(`npc_beacons.MAP_NAMES`). That duplication is now gone -- `npc_beacons`
imports this one -- so the two cannot disagree again.

| Prefix | Was | Is | Evidence |
|---|---|---|---|
| S3 | Cipher Key Lair | **Kaminko's House** | `S3_labo_1F` declares `kaminco_book` and `chobin_book`; the game's own world-map text carries "Kaminko'S House" as a destination distinct from "Cipher Key Lair" |
| S2 | ONBS | **Snagem Hideout** | `S2_building_1F_2` declares `talk_100_snatchdan`, `battle_100_snatchdan`, `snatchdan_battle_check` -- Team Snagem. ONBS is in Pyrite (`M2_building_*`) |
| D5 | Shadow Pokemon Lab | **Cipher Key Lair** | D5 is the `D5_factory_*` complex; "Shadow Pokemon Lab" is not a world-map destination at all, and the Shadow lab is D1 |
| D7 | Poke Spot | **Orre Colosseum** | D7 is a single outdoor room, `D7_out`. The Poke Spots are the `esaba_*` rooms |

The world-map string table (`worldmap.fsys`, messages 54501-54531) is the
game's own list of these locations and is what settles the names. The
project owner heard the contradiction directly: the world map announced
"Kaminko'S House. The peculiar manor that is home to the eccentric
scientist DR. KAMINKO." and the very next line announced the room as
"Map: Cipher Key Lair."
"""
EXACT_ROOM_NAMES = {
    # REMOVED 2026-08-10, both unprovable or provably wrong:
    #
    #   "M3_houseA_1F": "Eagun's House, first floor"
    #       Nothing in the extraction ties a house to a resident. The room
    #       code says "house", its script has no service, and no game
    #       resource names it. Restoring it needs a source, not a memory.
    #
    #   "M3_houseB_1F": "Agate Village Day-Care"
    #       **Wrong house.** `M3_houseD_1F` is the only room in all 425
    #       extracted scripts that calls `Daycare::depositPkm` /
    #       `withdrawPkm` / `getLevelsGained`. `M3_houseB_1F` makes no
    #       Daycare call at all. The Day Care is now DERIVED -- see
    #       `room_services.json` and `build_room_service_table.py` -- so
    #       the label follows the game rather than this table.
    # Named by the project owner, 2026-08-10, and both corroborated:
    #
    #   M3_cave_1F_1 is the passage to the shrine -- its own warp table
    #   leads onward to `M3_shrine_1F` and nowhere else.
    #
    #   M3_cave_1F_2 is a dead end whose one talk handler,
    #   `talk_129_baba1` ("old woman"), calls `Player::getPartyPkm`,
    #   `Pokemon::getNickname` and `Pokemon::34/35/36/37` -- a move
    #   tutor working on a party Pokemon. "Teacher lady" is what she is.
    #
    # These replace "Agate Village cave, 1st floor" A/B, where the letters
    # were assignment order and told the player nothing about which cave
    # reached the Relic Stone.
    "M3_cave_1F_1": "Relic Stone cave",
    "M3_cave_1F_2": "teacher lady cave",
    "M3_shrine_1F": "Relic Stone",
    "M5_apart_1F": "Pokemon HQ Lab residence, first floor",
    "M5_apart_2F": "Pokemon HQ Lab residence, second floor",
    "M5_labo_1F": "Pokemon HQ Lab, first floor",
    "M5_labo_2F": "Pokemon HQ Lab, second floor",
    "M5_labo_B1": "Pokemon HQ Lab, basement",
    # Mt. Battle, named by the project owner 2026-08-18 and corroborated
    # from the rooms' own scripts rather than taken on trust:
    #
    #   D2_pc_1F is the ENTRANCE building, not a Pokemon Center. The code
    #   says `pc` because it reuses the Center's building template -- the
    #   owner's own words, "it shares certain elements to a pokemon center,
    #   but it's the enterance" -- and the generic `pc` rule therefore
    #   announced it as "Pokemon Center, 1st floor". Its script settles it:
    #   it declares `mtbtl`, `mtbtl_chart` and `mtbtl_menu_1/2/3`, the Mt.
    #   Battle challenge chart and its menus. No other `_pc_` room in the
    #   game declares anything of the kind.
    #
    #   D2_out is the outdoor area. It was "Mt. Battle", which is also what
    #   LOCATION_NAMES calls the whole location, so a warp leading back out
    #   announced the same words as the place you were already in. "Mt.
    #   Battle outside" distinguishes the two; the world-map destination
    #   entry is unaffected, since that text comes from the game's own
    #   worldmap string table (message 54508), not from here.
    "D2_out": "Mt. Battle outside",
    "D2_pc_1F": "Mt. Battle entrance",
    "S1_shop_1F": "Outskirt Stand shop",
    # Rewritten 2026-08-10 onto the CORRECTED locations. These said "ONBS"
    # and "Cipher Key Lair" for rooms that are Snagem Hideout and
    # Kaminko's House. The floor wording is accessibility-owned, as before;
    # what changed is that the place is now the one the game names.
    "S2_building_1F_2": "Snagem Hideout, first floor",
    "S2_building_2F_2": "Snagem Hideout, second floor",
    "S2_building_3F_2": "Snagem Hideout, third floor",
    "S3_labo_1F": "Kaminko's House, first floor",
    "S3_labo_B1low": "Kaminko's House, lower basement",
    "S3_labo_B1up": "Kaminko's House, upper basement",
    "worldmap": "world map",
}
PART_NAMES = {
    "pc": "Pokemon Center", "shop": "Pokemon Mart", "hotel": "hotel",
    "police": "police station", "gym": "Pre Gym", "stadium": "stadium",
    "guild": "windmill", "windmill": "windmill", "labo": "lab",
    "garage": "garage", "factory": "factory", "tower": "tower",
    "ship": "S.S. Libra", "dome": "dome", "fort": "fortress",
    "junk": "parts shop", "crab": "Krabby Club", "shrine": "Relic Stone",
    "cave": "cave",
}

def _ordinal(number):
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"

def _floor_suffix(parts):
    for part in reversed(parts):
        match = re.fullmatch(r"(\d+)F", part)
        if match:
            return f", {_ordinal(int(match.group(1)))} floor"
        match = re.fullmatch(r"B(\d+)", part)
        if match:
            number = int(match.group(1))
            return ", basement" if number == 1 else f", basement level {number}"
    return ""

def player_facing_room_name(code, services=None):
    """Return a speakable label while keeping the room code as identity.

    `services` maps a room code to a service DERIVED from that room's own
    script (see `build_room_service_table.py`). It is consulted only when
    the code-based rule would produce the generic "house in X" form: a room
    code that already says `pc` or `shop` names itself correctly, and a
    service call is not a licence to rename an outdoor area after a vending
    machine it happens to contain."""
    if not code:
        return None
    code = code.removesuffix("_bf")
    if code in EXACT_ROOM_NAMES:
        return EXACT_ROOM_NAMES[code]
    parts = code.split("_")
    location = LOCATION_NAMES.get(parts[0])
    if not location:
        return " ".join(parts)
    if len(parts) == 1 or parts[1].startswith("out"):
        # An outdoor area IS its location -- "Pyrite Town" is the room's own
        # name here, not a prefix, so nothing is stripped below.
        return location
    # **The location prefix is deliberately NOT included from here down**
    # (project owner, 2026-08-12: "remove the map name from entities...
    # especially from buildings list").
    #
    # Every warp, door and elevator in a room leads somewhere in the same
    # map, so the town name was repeated on every single entry of the exits
    # list while telling the player nothing they did not already know from
    # standing there -- "to Pyrite Town Pokemon Mart, to Pyrite Town police
    # station, to Pyrite Town hotel".
    #
    # Applied HERE rather than in entity-nav's own labelling so the room
    # announcer keeps agreeing with the door that led to it -- an earlier
    # explicit request (see room_announcer.py's docstring: a door announced
    # as X must arrive somewhere that calls itself X). Both now say
    # "Pokemon Center, 2nd floor".
    #
    # `EXACT_ROOM_NAMES` above is untouched: those are hand-curated proper
    # names, and the location-looking words in them ("Pokemon HQ Lab",
    # "Snagem Hideout", "Kaminko's House") are what those buildings are
    # actually called, not a map prefix.
    kind = parts[1]
    building = PART_NAMES.get(kind)
    if building:
        return building + _floor_suffix(parts[2:])
    if kind.lower().startswith("house"):
        service = (services or {}).get(code)
        if service:
            return service + _floor_suffix(parts[2:])
        return "house" + _floor_suffix(parts[2:])
    return " ".join(parts[1:])

def build_room_names(room_codes, services=None):
    return {
        room_id: player_facing_room_name(code, services)
        for room_id, code in room_codes.items()
    }

def player_facing_npc_name(name, trainer_class=None):
    """Use trainer class plus name when both have authoritative sources."""
    name, trainer_class = (name or "").strip(), (trainer_class or "").strip()
    return " ".join(part for part in (trainer_class, name) if part) or None

