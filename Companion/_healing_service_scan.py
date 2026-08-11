"""Extract room scripts from the disc and report which ones call
`Character::101` (`useHealingMachine`).

Phase 2/3 of `Documentation/HEALING_SERVICE_SCRIPT_TRACE.md`, generalised
from the single-room slice that document proved by hand.

Pipeline per room:
    <room>.fsys  (DolphinTool, straight out of the RVZ -- no ISO conversion)
      -> the type-7 entry whose magic is "TCOD"        (the .scd script)
      -> XDscriptTools disassembly                     (structural decode)
      -> grep the DECODED INSTRUCTION STREAM for a call to class 35 / 101

The last step reads decoded instructions, never raw bytes: §4 of the trace
document explains why scanning for the byte 0x65 (or 0x55) cannot work --
immediates, branch offsets, string data and other classes' method IDs all
produce indistinguishable false positives. The class is what disambiguates,
so class and method have to be read together as decoded operands.

Usage:
    python _healing_service_scan.py [room ...]

With no arguments it runs the validation set from §7 Phase 6: known healing
locations, plus Poke Marts as the false-positive control. The controls MUST
come back negative -- that is the guard against §5's warning that a widened
talk distance (every desk NPC has one) is not a healing signal.

Read-only with respect to the game and to production code. Writes only under
the gitignored `_dialogue_extraction/rooms/`.
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dialogue_extraction_tool import parse_fsys

DOLPHIN_TOOL = Path(
    r"C:\Users\psych\OneDrive\Desktop\apps\Dolphin-x64\DolphinTool.exe")
RVZ = Path(
    r"C:\Users\psych\OneDrive\Desktop\apps\Dolphin-x64"
    r"\Pokemon XD - Gale of Darkness (USA).rvz")
DISASSEMBLER = (
    Path(__file__).resolve().parents[1]
    / "Research" / "ThirdParty" / "XDscriptTools" / "XDscriptDisassembler.py")
OUT = Path(__file__).resolve().parent / "_dialogue_extraction" / "rooms"

SCRIPT_ENTRY_TYPE = 7
TCOD_MAGIC = b"TCOD"

HEALING_CLASS = "Character"
HEALING_METHOD = 101

HEALING_SIGNATURES = {
    ("Character", 101): "useHealingMachine",
    ("Player", 58): "healPartyAtPokeCenter",
}
"""BOTH script routes into `recoveryEventPC`, not just the obvious one.

`recoveryEventPC` has exactly two callers. `objPeople.s:839` is
`Character::101`. The other, `objHero.s:962`, was resolved from `cmpHero`'s
own jump table (`@2588`, 54 entries, same `subi ..., 0x10` shape): the call
sits in table index 42, so method `42 + 0x10` = 58, which GoD Tool names
class 43 (`Player`) method 58 `healPartyAtPokeCenter`.

An earlier version of this scan searched `Character::101` alone and so could
not have found a room healing via the other route. Re-scanning all 276
extracted scripts for both found the same 15 rooms and **zero** users of
`Player::58` — so the inventory is complete against both known signatures,
rather than merely against the one that was looked for.

A third route on some other class would still be invisible here. That is the
standing limitation of any search that has to know what to look for."""

GOD_TOOL_NAMES = (
    Path(__file__).resolve().parents[1]
    / "Pokemon-XD-Code" / "Objects" / "scripts" / "XD"
    / "XGScriptClassFunctionsData.swift")

# ("name", index, paramCount, [types], returnType, "hint") -- POSITIONAL
# tuples. §3.1 records that a regex expecting `(name: "...", index: ...)`
# silently matches nothing, which cost one wrong result during the original
# investigation. Parse by position, and only trust a name when the index it
# sits next to is the one being looked up.
_ENTRY = re.compile(r'\(\s*"(?P<name>\w+)"\s*,\s*(?P<index>\d+)\s*,')


CHARACTER_CLASS_ID = 35
"""Confirmed from the binary, not assumed: `cmpPeople` checks the script
variant's type with `cmpwi r0, 0x23` before dispatching."""

_CLASS_BLOCK = re.compile(r"^\t(?P<class>\d+)\s*:\s*\[", re.MULTILINE)


def character_method_names(class_id=CHARACTER_CLASS_ID):
    """GoD Tool's names for a script class's methods.

    XDscriptTools decodes the call correctly but its own FunctionInfo.py
    names only 5 of this class's methods, so the decoder and the name source
    are deliberately different tools -- see §3.2.

    Keyed on the CLASS NUMBER's own block (`35 : [ ... ]`), not on a text
    search for "Character": method numbers are per-class, so the same index
    means something unrelated on `Camera` or `Pokemon`, and the string
    "Character" also appears inside every entry's parameter list. A first
    attempt at scoping by that string silently returned another table's
    names ("getvx", "zerofloat"), which is the same shape of error §3.1
    warns about."""
    if not GOD_TOOL_NAMES.is_file():
        return {}
    text = GOD_TOOL_NAMES.read_text(encoding="utf-8", errors="replace")
    blocks = list(_CLASS_BLOCK.finditer(text))
    for index, match in enumerate(blocks):
        if int(match.group("class")) != class_id:
            continue
        end = blocks[index + 1].start() if index + 1 < len(blocks) else len(text)
        block = text[match.end():end]
        names = {}
        for entry in _ENTRY.finditer(block):
            names.setdefault(int(entry.group("index")), entry.group("name"))
        return names
    return {}

# §7 Phase 6's required validation set.
VALIDATION_SET = [
    ("M3_pc_1F", "expected: HEALING (Agate nurse -- the known case)"),
    ("D2_pc_1F", "expected: HEALING (Mt. Battle, healed live 2026-08-04)"),
    ("M6_pc_1F", "expected: HEALING (Gateon Port -- second Centre)"),
    ("M1_shop_1F", "CONTROL -- must NOT classify as healing"),
    ("S1_shop_1F", "CONTROL -- must NOT classify as healing"),
]


def extract_fsys(room):
    """Pull <room>.fsys out of the RVZ. DolphinTool reads the RVZ directly,
    so there is no ISO conversion step and no third-party extractor."""
    destination = OUT / "files" / f"{room}.fsys"
    if destination.is_file():
        return destination
    OUT.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(DOLPHIN_TOOL), "extract", "-i", str(RVZ),
         "-s", f"{room}.fsys", "-o", str(OUT)],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{room}: DolphinTool failed: {result.stderr.strip()}")
    if not destination.is_file():
        raise RuntimeError(f"{room}: DolphinTool wrote no {destination}")
    return destination


def script_entry(fsys_path):
    """The script resource is identified by its "TCOD" magic, NOT by entry
    size or index -- see §6a finding 2, where the plausible-looking type-14
    entry is not the script."""
    entries = parse_fsys(fsys_path.read_bytes())
    candidates = [
        entry for entry in entries
        if entry.get("type") == SCRIPT_ENTRY_TYPE
        and entry.get("data", b"")[:4] == TCOD_MAGIC
    ]
    if not candidates:
        magic_anywhere = [
            entry for entry in entries
            if entry.get("data", b"")[:4] == TCOD_MAGIC
        ]
        if magic_anywhere:
            raise RuntimeError(
                f"{fsys_path.name}: TCOD found but at entry type(s) "
                f"{[e.get('type') for e in magic_anywhere]}, not "
                f"{SCRIPT_ENTRY_TYPE} -- the type assumption needs revisiting")
        return None
    if len(candidates) > 1:
        raise RuntimeError(
            f"{fsys_path.name}: {len(candidates)} TCOD entries; the "
            f"one-script-per-room assumption does not hold here")
    return candidates[0]["data"]


def disassemble(room, scd_bytes):
    """XDscriptDisassembler writes a .txt beside its input and prints
    nothing -- see §6a finding 3, where that silence looked like failure."""
    scd_path = OUT / f"{room}.scd"
    scd_path.write_bytes(scd_bytes)
    txt_path = OUT / f"{room}.txt"
    if txt_path.is_file():
        txt_path.unlink()
    result = subprocess.run(
        [sys.executable, str(DISASSEMBLER), str(scd_path)],
        capture_output=True, text=True)
    if not txt_path.is_file():
        raise RuntimeError(
            f"{room}: disassembler produced no {txt_path.name}: "
            f"{result.stderr.strip() or result.stdout.strip()}")
    return txt_path.read_text(encoding="utf-8", errors="replace")


CALL_PATTERN = re.compile(
    r"^\s*(?P<line>\d+)?\s*(?P<op>call\w*)\s+(?P<class>\w+)::(?P<method>\d+)",
    re.MULTILINE)


_FTBL_ENTRY = re.compile(r'^\s*\.function\s+(?P<name>\w+),\s*"', re.MULTILINE)
_LABEL = re.compile(r"^(?P<name>[A-Za-z_]\w*):\s*$")


def function_table(disassembly):
    """The script's own FTBL section -- the developer-assigned function
    names, e.g. `talk_124_pc_f`. These are real names shipped in the game
    data, not anything this project invented.

    Only FTBL entries count as function boundaries. `loc_NN:` labels are
    branch targets INSIDE a function: the Gateon healing call sits under
    `loc_61:`, which is a jump target within `talk_124_pc_f`, so treating
    every label as a function would attribute the call to a branch instead
    of the actor's talk handler."""
    head = disassembly.split('.section "CODE"')[0]
    return [match.group("name") for match in _FTBL_ENTRY.finditer(head)]


def enclosing_functions(disassembly):
    """Maps line number -> the FTBL function that line belongs to."""
    functions = set(function_table(disassembly))
    current = None
    mapping = {}
    for index, text in enumerate(disassembly.splitlines(), start=1):
        match = _LABEL.match(text)
        if match and match.group("name") in functions:
            current = match.group("name")
        mapping[index] = current
    return mapping


_RECEIVER = re.compile(r"^\s*ld\w*\s+(?P<operand>\$[\w\[\]]+)")


def receiver_before(lines, call_line):
    """The `Character` object the healing call is invoked ON.

    Arguments are pushed before the call and the receiver is pushed last,
    so it is the load instruction immediately preceding `callstd`. Two
    forms show up, and they need different runtime binding:

      `ldvar $characters[N]`  -- a literal room-relative character index.
      `ldncpvar $stack[N]`    -- whichever actor was passed into this
                                 function, i.e. inside a `talk_*` handler,
                                 the actor the player is talking to.

    Returns the operand text, or None if the preceding line is not a load
    (which would mean the receiver is computed, and attribution for that
    site needs real dataflow rather than this one-instruction rule)."""
    index = call_line - 2               # call_line is 1-based; step back one
    while index >= 0 and not lines[index].strip():
        index -= 1
    if index < 0:
        return None
    match = _RECEIVER.match(lines[index])
    return match.group("operand") if match else None


def find_calls(disassembly):
    """Every decoded `<class>::<method>` call site in the instruction
    stream, as (line-in-file, opcode, class, method)."""
    calls = []
    for index, text in enumerate(disassembly.splitlines(), start=1):
        match = re.search(r"(call\w*)\s+(\w+)::(\d+)", text)
        if match:
            calls.append((index, match.group(1), match.group(2),
                          int(match.group(3))))
    return calls


def scan(room):
    fsys_path = extract_fsys(room)
    scd = script_entry(fsys_path)
    if scd is None:
        return {"room": room, "status": "NO SCRIPT", "calls": [], "healing": []}
    disassembly = disassemble(room, scd)
    calls = find_calls(disassembly)
    owners = enclosing_functions(disassembly)
    lines = disassembly.splitlines()
    healing = [
        call + (owners.get(call[0]), receiver_before(lines, call[0]))
        for call in calls
        if call[2] == HEALING_CLASS and call[3] == HEALING_METHOD
    ]
    return {
        "room": room,
        "status": "HEALING" if healing else "no healing call",
        "calls": calls,
        "healing": healing,
        "functions": function_table(disassembly),
        "script_bytes": len(scd),
    }


def main(argv):
    rooms = argv[1:] or [room for room, _ in VALIDATION_SET]
    notes = dict(VALIDATION_SET)
    print(f"disc : {RVZ}")
    print(f"seek : {HEALING_CLASS}::{HEALING_METHOD} (useHealingMachine)")
    print()
    results = []
    for room in rooms:
        try:
            result = scan(room)
        except Exception as exc:                     # noqa: BLE001
            print(f"{room:<14} ERROR  {exc}")
            continue
        results.append(result)
        distinct = sorted({(c[2], c[3]) for c in result["calls"]})
        print(f"{room:<14} {result['status']:<16} "
              f"script {result.get('script_bytes', 0):>5}B  "
              f"{len(result['calls']):>3} calls, "
              f"{len(distinct):>3} distinct methods")
        if notes.get(room):
            print(f"{'':14} {notes[room]}")
        for line, op, klass, method, owner, receiver in result["healing"]:
            print(f"{'':14} -> {owner or '<no FTBL function>':<26} "
                  f"receiver {receiver or '<computed>':<16} (line {line})")
    names = character_method_names()
    print(f"GoD Tool names {len(names)} Character methods")
    print()
    print("Character methods called by each room:")
    for result in results:
        character = sorted({c[3] for c in result["calls"]
                            if c[2] == HEALING_CLASS})
        print(f"  {result['room']}:")
        for method in character:
            label = names.get(method, "<unnamed>")
            mark = "  <== HEALING" if method == HEALING_METHOD else ""
            print(f"      {method:>4}  {label}{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
