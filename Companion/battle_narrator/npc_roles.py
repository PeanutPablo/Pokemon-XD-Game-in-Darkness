"""Which NPCs are Poke Mart clerks, Pokemon Centre nurses, and so on --
derived from the game's own room scripts, not from a curated room list.

The defect this replaces
------------------------
`phase1b_app.py` decided roles with
`{0x85: "Pokemon Center nurse", 0x86: "Pokemon Mart clerk"}` matched
against `entity.identity[1]` -- which is the FLOOR ID. Every NPC standing
in Agate's Mart was therefore announced as a clerk (the project owner's
"three clerks" report; reproduced in the log at 2026-08-05 21:58:44), and
every Mart and Centre outside Agate had no role at all.

The authoritative signal
------------------------
An NPC's `floor_character +0x14` is its talk SCRIPT id
(`floorCharacterBiosGetTalkSctID`). The script that id runs is what makes
an NPC a clerk: the Agate clerk's talk function calls
`Dialogs::openPokemartMenu`, and a Centre nurse's calls
`Player::healParty`. Those are global standard-library functions, so the
rule generalises to every shop and every Centre in the game -- 11 rooms
call `openPokemartMenu` and 24 call `healParty` across the extracted
scripts, against the two rooms the old table knew about.

Roles are resolved TRANSITIVELY: a talk function that calls a helper that
opens the shop still counts, because the player still ends up in a shop.

How a live talk id maps to a script function -- SETTLED 2026-08-09
------------------------------------------------------------------
This module used to read the `<N>` in a `talk_<N>_<description>` function
name as the talk script id, and said so as an explicitly UNVERIFIED
assumption. **It was wrong**, and the shadow reader settled it on the
first run that reached the Agate Mart:

    live floor_character +0x14 : 0x01000006  0x01000007  0x01000008
    M3_shop_1F function table  : [6] talk_121_ojisan1
                                 [7] talk_122_shop_m     <- the clerk
                                 [8] talk_125_ippan_f

The low bits are the **index into the owning room script's own function
table**, not the number in the name (121 / 122 / 125). It is the same
encoding the room-script interaction records use (see
INTERACTABLE_OBJECTS.md), and the same class of index-versus-id confusion
as defect R6.

Corroboration that the right NPC is picked out: function index 7,
`talk_122_shop_m` -- "shop man" -- belongs to the one NPC of the three
whose live talk distance is **9.0** rather than 3.0, giving it a 16.5-unit
interaction threshold instead of 10.5. A longer reach is exactly what an
NPC you talk to across a shop counter needs, and nothing in this
derivation looked at that field.

The top byte (`0x01`) is treated as a KIND marker. Only that kind is
resolved; any other resolves to None rather than being masked and guessed
at, so a talk id from a source this module has not seen cannot be turned
into a confident wrong label.
"""
import json
import re


ROLE_MARKERS = {
    "Pokemon Mart clerk": ("Dialogs::openPokemartMenu",),
    "Pokemon Center nurse": ("Character::101",),
}
"""Standard-library calls that define a role. Accessibility-owned wording
for a game-owned behaviour: the label is this project's, the *membership
test* is entirely the game's.

`Character::101` is `useHealingMachine` -- class 35, method 101, which
HEALING_SERVICE_SCRIPT_TRACE.md established independently (and corrected a
still earlier session's "People method 85", which was the internal
`cmpPeople` jump-table index after the dispatch subtracts 0x10). It
appears in 15 rooms: every Pokemon Centre plus the HQ Lab, Cipher Lab,
Citadark and Snagem healing points. Two markers that were tried and
rejected, recorded so they are not retried:

- `Player::healParty` heals the party without a healing machine -- Mt.
  Battle's rest points and story courtesies. Those NPCs are genuinely
  useful but they are not nurses, and labelling them so would be the same
  class of error as the room-id guess. Healing OBJECTS are Phase 4.
- The room id. See this module's docstring."""

ROOM_SCRIPT_KIND = 0x01
"""Top byte of a live `floor_character +0x14`, observed as `0x01` for every
talk script in the Agate Mart. Read as "this id addresses the owning room
script's function table"."""

TALK_SCRIPT_KIND_SHIFT = 24
TALK_SCRIPT_INDEX_MASK = (1 << TALK_SCRIPT_KIND_SHIFT) - 1


def decode_talk_script_id(talk_script_id):
    """`0x01000007` -> function index 7, or None for a kind this module has
    not seen. None means unresolved; it never falls through to a guess."""
    if talk_script_id is None:
        return None
    if (talk_script_id >> TALK_SCRIPT_KIND_SHIFT) != ROOM_SCRIPT_KIND:
        return None
    return talk_script_id & TALK_SCRIPT_INDEX_MASK


def function_table(text):
    """Declared function names in INDEX order.

    Declaration order is index order, and the dumps list every function
    twice (an FTBL section then a HEAD section), so the list stops at the
    first repeat. Independently corroborated: decoding the room-script
    interaction records' own function field this way resolved 241 of 241
    records with none out of range (INTERACTABLE_OBJECTS.md §2)."""
    names, seen = [], set()
    for line in text.splitlines():
        match = DECLARATION.match(line)
        if not match:
            continue
        name = match.group(1)
        if name in seen:
            break
        seen.add(name)
        names.append(name)
    return names


TALK_FUNCTION = re.compile(r"^talk_(\d+)_")
DECLARATION = re.compile(r'^\s*\.function\s+([A-Za-z_][\w]*)\s*(?:,.*)?$')
"""Matches both forms the dumps use: the FTBL section's
`.function name, "name"` and the HEAD section's bare `.function name`.
Accepting only the bare form worked on real files by accident (every
function appears in both sections) and silently found nothing in a dump
that had only one."""
LABEL = re.compile(r"^([A-Za-z_][\w]*):\s*$")
CALL = re.compile(r"^\s*call\s+([A-Za-z_][\w]*)\s*$")
CALLSTD = re.compile(r"^\s*callstd\s+([A-Za-z_][\w:]*)\s*$")


def parse_room_script(text):
    """{function name -> (called function names, called stdlib names)}."""
    declared = set()
    for line in text.splitlines():
        match = DECLARATION.match(line)
        if match:
            declared.add(match.group(1))
    calls, stdcalls = {}, {}
    current = None
    for line in text.splitlines():
        label = LABEL.match(line)
        if label and label.group(1) in declared:
            current = label.group(1)
            calls.setdefault(current, set())
            stdcalls.setdefault(current, set())
            continue
        if current is None:
            continue
        call = CALL.match(line)
        if call:
            calls[current].add(call.group(1))
            continue
        std = CALLSTD.match(line)
        if std:
            stdcalls[current].add(std.group(1))
    return {name: (calls.get(name, set()), stdcalls.get(name, set()))
            for name in calls}


def _reaches(name, graph, markers, seen=None):
    """Does `name` reach any marker call, following ordinary `call` edges?"""
    if seen is None:
        seen = set()
    if name in seen or name not in graph:
        return False
    seen.add(name)
    calls, stdcalls = graph[name]
    if stdcalls & markers:
        return True
    return any(_reaches(callee, graph, markers, seen) for callee in calls)


def room_roles(text):
    """{function index -> role} for one room script dump.

    Keyed on the function's INDEX, which is what a live talk id carries,
    not on the number in its name. Functions are not filtered by name: a
    function that reaches `openPokemartMenu` opens a shop whatever it is
    called, and an entry no NPC's talk id points at is simply never looked
    up. Filtering on `talk_` would have silently missed every room whose
    shop function is named anything else."""
    graph = parse_room_script(text)
    indices = {name: index for index, name in enumerate(function_table(text))}
    result = {}
    for role, marker_names in ROLE_MARKERS.items():
        markers = set(marker_names)
        for name in graph:
            index = indices.get(name)
            if index is None or not _reaches(name, graph, markers):
                continue
            result[index] = role
    return result


def build_role_table(room_script_dir, room_codes):
    """{room id -> {talk script id -> role}} across every extracted room."""
    table = {}
    for room_id, code in room_codes.items():
        path = room_script_dir / f"{code}.txt"
        if not path.is_file():
            continue
        roles = room_roles(path.read_text(encoding="utf-8", errors="replace"))
        if roles:
            table[room_id] = roles
    return table


def _as_int(value):
    return value if isinstance(value, int) else int(str(value), 0)


class NPCRoleResolver:
    """Looks up a live NPC's role by its own talk script id.

    Never falls back to the room. A room the table does not cover, or an
    NPC in a covered room whose talk id is not a role script, resolves to
    None -- which is the correct answer for the two ordinary shoppers
    standing next to Agate's clerk."""

    def __init__(self, table):
        # base 0, not base 10: the generated asset keys rooms as "0x86" to
        # stay readable next to room_ids.json, and int(x) rejects that.
        self.table = {
            _as_int(room): {_as_int(talk): role for talk, role in roles.items()}
            for room, roles in (table or {}).items()
        }

    @classmethod
    def from_json(cls, path):
        with open(path, "r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    def resolve(self, room_id, talk_script_id):
        index = decode_talk_script_id(talk_script_id)
        if index is None:
            return None
        return self.table.get(room_id, {}).get(index)

    def covers(self, room_id):
        return room_id in self.table
