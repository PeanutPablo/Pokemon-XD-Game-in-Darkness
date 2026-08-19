"""Live bridge connection points for Gateon Port's rotating piers.

What a blind player needs here is not "there is a bridge" but "which way
can I cross, right now" -- the configuration changes under them, and there
is no visual cue that it has. This publishes one entity per connection
that is CURRENTLY open AND actually leads somewhere, and nothing for the
ones that do not.

Everything is derived. Nothing in this module is a coordinate, a room
list, or a direction typed in by hand:

    general flag 968                    <- read live, every query
      -> pier_def's own enable table    <- PARSED from the extracted room
                                           script, not transcribed
      -> CCD entries 23-31              <- the bridge segments
      -> their own hit geometry         <- position and direction
      -> the two deck footprints        <- which pier, and the walk height

**`enable == 1` means that direction is BLOCKED.**

That polarity is the one thing here that could be catastrophically wrong
-- getting it backwards points a blind player at a wall in every alignment
-- and it was **wrong from 2026-08-09 until 2026-08-18**, when the project
owner reported the category listing places the bridge was not connected to.
`ENTITY_NAVIGATION_ARCHITECTURE.md` §3.7 had it right all along, calling
entries 23-31 the bridge's *blocking* geometry; this module's original
docstring "corrected" it, and the correction was the error.

Why the original evidence did not hold
--------------------------------------
It rested on `pier_def`'s table agreeing 12 of 12 with the `ALIGNMENTS`
prose in the retired `gateon_bridge.py`. That agreement was **circular**.
The prose is a field-for-field restatement of the enable bits -- state 0's
"north and west" is exactly `{24, 27}`, state 1's "south and west" exactly
`{25, 27}`, and "centre open" exactly `26 == 1` -- so it reproduces the bit
pattern by construction and cannot discriminate the two readings. A second
description of the same table is not a second observation.

What actually settles it
------------------------
Three independent facts from the room's own collision data, none of which
depend on any prose:

1. **None of entries 23-31 is walkable.** They contribute 0 triangles to
   `M6_out`'s walk model and exist only in the environment (hit) model.
   The walk surfaces here are the two decks (58, 59) and the ground mesh
   (45). A thing you cannot stand on is not a connection.
2. **Seven of the nine are flat gates** -- 2 triangles each, collapsed
   onto a single plane (entry 27 spans x -271.6..-271.6; entry 30 spans
   z -121.6..-121.6), plus the centre passage at 0.4 units deep. A plane
   with no footprint is a barrier across the 20-unit-wide opening in that
   side of the pier's railing, not a surface. The remaining two (23, 24)
   are closed volumes, and are not walkable either.
3. **The call is an ENABLE on a collision object.**
   `GScolsys2SetObjEnable(1, obj)` switches a collision blocker ON. The
   engine's own verb agrees with the geometry.

The corrected reading is also the only one that makes the puzzle work. A
crossing between the two piers has to pass three gates in a line at
x = -240: the northern deck's south gate (z 78.4), the centre passage
(z 10), and the southern deck's north gate (z -58.4). Under "1 ==
connected" those three are never simultaneously open in any of the four
alignments -- the piers could never be crossed between. Under "1 ==
blocked" alignment 0 opens all three, and the other three alignments do
not, which is a puzzle rather than an impossibility.

Connections that lead nowhere are also withheld
-----------------------------------------------
Being open is necessary but not sufficient. A pier's INTERIOR-facing gate
-- the one pointing at the other pier, derived here from the decks' own
positions rather than named -- opens onto the centre passage and nothing
else, so it is published only when the passage is open too. The passage
itself is published only when at least one interior gate is open, since
otherwise it cannot be reached from either deck. Alignments 2 and 3 each
leave exactly one such dead-end gate open, and alignment 1 leaves the
passage open with neither gate; before this they were all announced as
somewhere to walk.
"""
from dataclasses import dataclass
import collections
import math
import re

from .entities import Entity
from .memory import MemoryError as GameMemoryError
from .npc_beacons import Position


BRIDGE_FLAG = 968
"""`pier_def` and `pier_move`'s own flag. Read live every query; this is
the only number here that identifies anything, and it comes from the
script both functions are parsed out of."""

BLOCKED = 1
OPEN = 0
"""What `pier_def` writes for one collision object, and what it means.

Named rather than compared as bare literals because this project got the
polarity backwards once already; a reader of `entities()` should not have
to remember which way round `== 1` reads. See the module docstring for the
evidence. Anything that is NEITHER value -- an entry this alignment's row
does not mention at all -- is treated as not-open, because a connection
that cannot be shown to be open must not be offered."""

SEGMENT_FUNCTION = "pier_def"
ENABLE_CALL = "UnknownClass46::16"
"""The script-level `GScolsys2SetObjEnable`. Called as
`(enable, objectIndex)` -- decided by inspection, not assumed: across all
36 calls the second-pushed value is always one of the nine object indices
and the first is always 0 or 1."""


def parse_pier_enable_table(script_text, function=SEGMENT_FUNCTION):
    """`{flag value: {ccd entry: enabled}}` straight out of the extracted
    room script.

    Parsed rather than transcribed so the table cannot drift away from the
    game's own data, and so a different pier (or a hack that retunes this
    one) is picked up without a code change."""
    ldimm = re.compile(r"^ldimm\s+int,\s*=(-?\d+)$")
    table = collections.defaultdict(dict)
    state = None
    pending = []
    inside = False
    for raw in script_text.splitlines():
        line = raw.strip()
        if line.startswith(f"{function}:"):
            inside = True
            continue
        if not inside:
            continue
        if re.match(r"^\w+:", line) and not line.startswith("loc_"):
            break
        match = ldimm.match(line)
        if match:
            pending.append(int(match.group(1)))
            continue
        if line.startswith("callstd") and "getFlag" in line:
            # The flag id was consumed by the call; whatever is compared
            # against its result next is the state this block belongs to.
            pending = []
            continue
        if line.startswith("operator") and line.endswith("equ"):
            if pending:
                state = pending[-1]
            pending = []
            continue
        if ENABLE_CALL in line:
            if state is not None and len(pending) >= 2:
                enable, entry = pending[-2], pending[-1]
                table[state][entry] = enable
            pending = []
            continue
    return {state: dict(row) for state, row in table.items()}


def _footprint(triangles):
    points = [vertex for triangle in triangles for vertex in triangle.vertices]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


def _centre(triangles):
    (x0, x1), _, (z0, z1) = _footprint(triangles)
    return (x0 + x1) / 2, (z0 + z1) / 2


def _gap_to_box(triangles, box):
    """XZ distance from a segment's geometry to a deck footprint. Zero when
    they overlap."""
    (sx0, sx1), _, (sz0, sz1) = _footprint(triangles)
    (bx0, bx1), _, (bz0, bz1) = box
    dx = max(bx0 - sx1, sx0 - bx1, 0.0)
    dz = max(bz0 - sz1, sz0 - bz1, 0.0)
    return math.hypot(dx, dz)


def _nearest_point_xz(triangles, x, z):
    """Nearest point of a segment's own geometry to (x, z), in the XZ plane.

    The audit's defect P1 in miniature: a region's centre is not where the
    player walks. For a 68-unit bridge span the difference is most of the
    span."""
    best = None
    best_distance = None
    for triangle in triangles:
        vertices = triangle.vertices
        for index in range(3):
            ax, _, az = vertices[index]
            bx, _, bz = vertices[(index + 1) % 3]
            dx, dz = bx - ax, bz - az
            length = dx * dx + dz * dz
            if length == 0.0:
                px, pz = ax, az
            else:
                t = ((x - ax) * dx + (z - az) * dz) / length
                t = max(0.0, min(1.0, t))
                px, pz = ax + t * dx, az + t * dz
            distance = math.hypot(px - x, pz - z)
            if best_distance is None or distance < best_distance:
                best_distance, best = distance, (px, pz)
    return best


@dataclass(frozen=True)
class Deck:
    """One rotating pier: the square the player actually stands on."""

    entry_index: int
    box: tuple
    centre: tuple
    walk_height: float
    name: str


@dataclass(frozen=True)
class Segment:
    """One bridge segment: a direction this pier can connect in, when the
    current alignment enables it."""

    entry_index: int
    triangles: tuple
    centre: tuple
    deck: object
    direction: object
    """None for the passage between the two piers, which belongs to
    neither -- established from the geometry, not assumed: its nearest
    approach to either deck is an order of magnitude larger than the
    uniform 4.9-unit gap every deck segment stands at."""

    @property
    def label(self):
        if self.direction is None:
            return "Centre passage"
        return f"{self.deck.name} bridge, {self.direction} connection"


def interior_facing_entries(decks, segments):
    """CCD entries for the gates that face the other pier.

    Derived, not named: the direction from one deck's centre to the other's
    is computed with the same rule `_direction` uses for a segment, so the
    gate whose own direction matches it is the one pointing across the gap.
    A layout that is not two decks yields nothing, and every gate is then
    treated as leading outward -- the pre-existing behaviour, and the safe
    one, since it withholds nothing."""
    if len(decks) != 2:
        return frozenset()
    first, second = decks
    inward = {
        first.entry_index: _direction(second.centre, first.centre),
        second.entry_index: _direction(first.centre, second.centre),
    }
    return frozenset(
        segment.entry_index
        for segment in segments
        if segment.deck is not None
        and segment.direction == inward.get(segment.deck.entry_index)
    )


def _direction(segment_centre, deck_centre):
    dx = segment_centre[0] - deck_centre[0]
    dz = segment_centre[1] - deck_centre[1]
    if abs(dx) >= abs(dz):
        return "east" if dx > 0 else "west"
    return "north" if dz > 0 else "south"


def derive_layout(walk_triangles, hit_triangles, entries):
    """Decks and segments, derived from the room's own collision geometry.

    `entries` is the set of CCD entries the pier script drives -- so the
    layout follows the script rather than a list of indices written here.
    """
    segments_by_entry = collections.defaultdict(list)
    for triangle in hit_triangles:
        if triangle.entry_index in entries:
            segments_by_entry[triangle.entry_index].append(triangle)
    if not segments_by_entry:
        return (), ()

    points = [
        vertex
        for triangles in segments_by_entry.values()
        for triangle in triangles
        for vertex in triangle.vertices
    ]
    span_x = (min(p[0] for p in points), max(p[0] for p in points))
    span_z = (min(p[2] for p in points), max(p[2] for p in points))
    span_area = (span_x[1] - span_x[0]) * (span_z[1] - span_z[0])

    # The decks are the walk surfaces inside the pier's own footprint that
    # are SMALL -- the room's ground plane also passes through here, and it
    # is orders of magnitude larger. Both bounds come from the segment
    # geometry itself, so nothing is tuned to this particular room.
    walk_by_entry = collections.defaultdict(list)
    for triangle in walk_triangles:
        walk_by_entry[triangle.entry_index].append(triangle)
    candidates = []
    for entry_index, triangles in walk_by_entry.items():
        box = _footprint(triangles)
        (x0, x1), (y0, y1), (z0, z1) = box
        area = (x1 - x0) * (z1 - z0)
        if area <= 0 or area >= span_area:
            continue
        centre = ((x0 + x1) / 2, (z0 + z1) / 2)
        if not (span_x[0] <= centre[0] <= span_x[1]
                and span_z[0] <= centre[1] <= span_z[1]):
            continue
        candidates.append((entry_index, box, centre, (y0 + y1) / 2))
    if len(candidates) < 2:
        return (), ()

    # "Northern" and "southern" are read off the geometry, not assigned:
    # of the two decks, the one at greater Z is the northern one.
    candidates.sort(key=lambda item: item[2][1], reverse=True)
    names = ("Northern", "Southern")
    decks = tuple(
        Deck(entry_index=entry_index, box=box, centre=centre,
             walk_height=height, name=names[index])
        for index, (entry_index, box, centre, height)
        in enumerate(candidates[:2])
    )

    segments = []
    for entry_index in sorted(segments_by_entry):
        triangles = tuple(segments_by_entry[entry_index])
        centre = _centre(triangles)
        gaps = sorted(
            ((_gap_to_box(triangles, deck.box), deck) for deck in decks),
            key=lambda item: item[0])
        nearest_gap, nearest_deck = gaps[0]
        # A deck segment stands just off its deck's edge. The passage
        # between the piers stands off BOTH by far more than a deck's own
        # half-width, which is the scale this compares against so no
        # absolute distance is written here.
        half_width = min(
            (nearest_deck.box[0][1] - nearest_deck.box[0][0]) / 2,
            (nearest_deck.box[2][1] - nearest_deck.box[2][0]) / 2)
        if nearest_gap > half_width:
            segments.append(Segment(
                entry_index=entry_index, triangles=triangles, centre=centre,
                deck=None, direction=None))
            continue
        segments.append(Segment(
            entry_index=entry_index, triangles=triangles, centre=centre,
            deck=nearest_deck,
            direction=_direction(centre, nearest_deck.centre)))
    return decks, tuple(segments)


class BridgeConnectionEntitySource:
    """Entity-nav source for the connections the pier currently offers.

    Publishes ONLY connections that are open in the live alignment AND lead
    somewhere. A direction that is not currently crossable produces nothing
    -- not an entity marked closed -- because entity navigation is a list
    of places worth walking to, and this is a category where being wrong
    walks a blind player into a wall."""

    def __init__(self, memory, profile, flag_reader, pose_source, room_id,
                 decks, segments, logger=None):
        self.memory = memory
        self.profile = profile
        self.flag_reader = flag_reader
        self.pose_source = pose_source
        self.room_id = room_id
        self.decks = tuple(decks)
        self.segments = tuple(segments)
        self.logger = logger
        self.enable_table = {}
        self.alignment = None
        self.generation = 0
        self.interior_entries = interior_facing_entries(self.decks, self.segments)
        self.passage_entries = frozenset(
            segment.entry_index for segment in self.segments
            if segment.deck is None)

    def player_pose(self):
        return self.pose_source.player_pose()

    def open_entries(self, row):
        """CCD entries that are open AND reachable, for one alignment row.

        Two rules, in order. An entry is open when its collision blocker is
        switched off (see `BLOCKED`/`OPEN`). Then the gates that face the
        other pier are dropped unless the centre passage between them is
        open as well, and the passage is dropped unless at least one of
        those gates is open -- either way it is a gate onto nothing, which
        is exactly what this category must not announce."""
        opened = {
            segment.entry_index for segment in self.segments
            if row.get(segment.entry_index) == OPEN
        }
        passage_open = bool(opened & self.passage_entries)
        interior_open = bool(opened & self.interior_entries)
        if not passage_open:
            opened -= self.interior_entries
        if not interior_open:
            opened -= self.passage_entries
        return opened

    def current_alignment(self):
        """The live flag, or None when it cannot be read or is not one of
        the alignments the script defines. None publishes nothing."""
        try:
            value = self.flag_reader.value(BRIDGE_FLAG)
        except Exception:
            return None
        return value if value in self.enable_table else None

    def entities(self):
        if not self.segments or not self.enable_table:
            return []
        try:
            room = self.memory.u16(
                self.profile.current_floor_id, "bridge connection room")
        except GameMemoryError:
            return []
        if room != self.room_id:
            if self.alignment is not None:
                self.alignment = None
            return []
        alignment = self.current_alignment()
        if alignment is None:
            if self.logger is not None and self.alignment is not None:
                self.logger.debug(
                    "BRIDGE CONNECTIONS suppressed: flag %d is not one of "
                    "the alignments pier_def defines", BRIDGE_FLAG)
            self.alignment = None
            return []
        if alignment != self.alignment:
            # A rotation replaces the runtime entities wholesale: the
            # endpoints that were there are gone. The generation makes that
            # observable to a consumer holding a stale selection.
            self.generation += 1
            self.alignment = alignment
            if self.logger is not None:
                self.logger.info(
                    "BRIDGE CONNECTIONS alignment %d, generation %d",
                    alignment, self.generation)
        opened = self.open_entries(self.enable_table[alignment])
        pose = self.player_pose()
        result = []
        for segment in self.segments:
            if segment.entry_index not in opened:
                continue
            height = (
                segment.deck.walk_height if segment.deck is not None
                else sum(deck.walk_height for deck in self.decks) / len(self.decks)
            )
            nearest = _nearest_point_xz(
                segment.triangles, pose.position.x, pose.position.z)
            result.append(Entity(
                category="bridge",
                identity=("bridge", segment.entry_index),
                label=segment.label,
                position=Position(segment.centre[0], height, segment.centre[1]),
                # Walk-into, not press-A: the engine gates these on
                # collision, not on `peopleTalkCheck`, so no interaction
                # radius exists to report and none is invented.
                interaction_distance=None,
                subtype=segment.direction,
                metadata={
                    "alignment": alignment,
                    "generation": self.generation,
                    "entry_index": segment.entry_index,
                    "deck": None if segment.deck is None else segment.deck.name,
                    "interaction_position": Position(
                        nearest[0], height, nearest[1]),
                },
            ))
        return result
