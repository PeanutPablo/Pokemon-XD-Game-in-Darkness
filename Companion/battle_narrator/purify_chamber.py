"""Purify Chamber model: what is on each SET, and its Tempo and Flow.

The Chamber is the one screen in this game whose entire point is a number
the player cannot otherwise perceive. TEMPO and FLOW are drawn as bar
widgets and coloured connecting lines -- there is no text anywhere on the
screen stating either value, so a blind player has no way at all to tell a
good arrangement from a bad one. Reading the occupants aloud without them
would be like reading a chessboard without saying who is winning.

Neither value is stored anywhere. `CReliveStage::getTempo` (0x8028DB78)
and `getPassionWoBonus` (0x8028DDBC) recompute from the Pokemon on the SET
every time the screen redraws, and nothing caches the result -- confirmed
by checking every caller of both (only the draw path and the hero-walk
callback call them). So this module ports the two functions.

Ported, not approximated: every constant below is read out of the running
game's own tables at call time rather than typed in, so a build with
different numbers stays correct.

    _tempoBase   0x8041A7B0   base value per dancer count (5 ints)
    _tempoGood   0x8041A7C4   bonus per adjacent pair at matchup level 2-3
    _tempoNormal 0x8041A7D8   bonus per adjacent pair at matchup level 1
    jyoutai2levelTbl 0x804E8698   4 u16 type-chart states -> matchup level
    flow multipliers 0x802FAD00   3 floats, [1.0, 1.5, 2.0]
    _bonusStageBonusTbl 0x8041A7EC   perfect-SET bonus (10 ints)

The one cross-check that makes the whole port credible: the maximum Tempo
this produces (four dancers, every adjacent pair at the best matchup ->
48 + 4*12 = 96) times the largest Flow multiplier (2.0) is exactly 192 --
the literal `CReliveStage::isBonusGet` (0x8028E1E8) compares
`getPassionWoBonus()` against to decide a SET is perfect. Two independent
paths, same number.

Terminology: the game's own symbols call the centre Shadow Pokemon the
"visitor" and the surrounding regular Pokemon "dancers", and a SET is a
"stage". Player-facing text uses the manual's words (SET, Shadow Pokemon,
Tempo, Flow) -- see the docstring on `describe_set`.
"""
from dataclasses import dataclass

from .memory import MemoryError
from .speech import SpeechEventClass

# --- CReliveHall, savedata section 21 -----------------------------------
# savedataGetStatus(savedata, 21) -> savedata + 0x20000 - 10608. The same
# jump table (rodata 0x8040C4F8) gives section 15 as savedata + 0xE380,
# which is exactly profile.darkpokemon_array_savedata_offset -- an
# independent confirmation that this offset was read correctly.
RELIVE_HALL_SAVEDATA_OFFSET = 0x1D690
STAGE_COUNT = 9
STAGE_SIZE = 984
DANCER_CAPACITY = 4
DANCER_STRIDE = 196
VISITOR_OFFSET = 784
FACING_OFFSET = 980
"""Signed byte: which dancer slot the Shadow Pokemon faces."""

# --- Pokemon struct (the same 196-byte record party.py already decodes)
POKEMON_DATA_ID_OFFSET = 0x00
POKEMON_LEVEL_OFFSET = 0x11
POKEMON_NICKNAME_OFFSET = 0x4E
POKEMON_NICKNAME_MAX = 10

# --- species database ---------------------------------------------------
POKEMON_DATA_NUMBER, POKEMON_DATA = 0x804EA634, 0x804EA638
POKEMON_DATA_STRIDE = 0x124
POKEMON_NAME_OFFSET = 0x18
POKEMON_TYPE_OFFSET = 0x30
"""Two u8 type ids at +0x30 and +0x31 (pokemonDataBiosGetZokuseiDataId)."""

# --- type database and chart --------------------------------------------
ZOKUSEI_DATA_NUMBER, ZOKUSEI_DATA = 0x804E87C8, 0x804E87CC
ZOKUSEI_STRIDE = 0x30
ZOKUSEI_NAME_OFFSET = 0x08
ZOKUSEI_CHART_OFFSET = 0x0C
"""18 u16 effectiveness states per attacking type."""
ZOKUSEI_DEFENDER_LIMIT = 18

JYOUTAI_TO_LEVEL_TABLE = 0x804E8698
JYOUTAI_TO_LEVEL_ENTRIES = 4
UNMATCHED_LEVEL = 123
"""What the engine's own linear search yields for a chart state that is
not in `jyoutai2levelTbl`. Reproduced rather than normalised because the
engine then falls through its switch and reuses the PREVIOUS pair's
contribution -- see `_pair_bonus`."""

TEMPO_BASE_TABLE = 0x8041A7B0
TEMPO_GOOD_TABLE = 0x8041A7C4
TEMPO_NORMAL_TABLE = 0x8041A7D8
BONUS_STAGE_TABLE = 0x8041A7EC
BONUS_STAGE_ENTRIES = 10
FLOW_MULTIPLIER_TABLE = 0x802FAD00
FLOW_MULTIPLIER_ENTRIES = 3

PERFECT_TEMPO = 96
"""`getReliveGiveStageQuantity` (0x8028D1AC) counts SETs at exactly this
Tempo with all-unique types -- the game's own definition of a BEST
CIRCLE."""
PERFECT_FLOW = 192
"""`isBonusGet` (0x8028E1E8) threshold."""

# Tempo -> the three-level bar the screen actually draws
# (`relivehallTempoToLevel`, 0x8003AAA4).
TEMPO_LEVEL_THRESHOLDS = (26, 53)
TEMPO_LEVEL_NAMES = ("low", "medium", "high")


@dataclass(frozen=True)
class ChamberPokemon:
    slot: int
    data_id: int
    nickname: str
    level: int
    types: tuple
    species: str = ""

    @property
    def type_names(self):
        return tuple(name for name in self.types if name)


@dataclass(frozen=True)
class ChamberSet:
    index: int
    dancers: tuple
    """Occupied outer positions, in game order, contiguous from 0."""
    visitor: object
    """The centre Shadow Pokemon, or None."""
    facing: int
    """Which dancer position the Shadow Pokemon faces."""
    tempo: int
    flow: int
    bonus: int
    """Perfect-SET bonus already included in `flow`, or 0."""

    @property
    def occupied(self):
        return len(self.dancers)

    @property
    def tempo_level(self):
        level = 0
        for threshold in TEMPO_LEVEL_THRESHOLDS:
            if self.tempo > threshold:
                level += 1
        return level

    @property
    def is_perfect(self):
        return self.bonus > 0

    @property
    def is_empty(self):
        return not self.dancers and self.visitor is None


class PurifyChamberModel:
    """Read-only. The Chamber lives in save data, not in the menu, so
    every method here works whether or not the edit screen is open --
    which is what lets a hotkey summary answer "how are my SETs doing?"
    from the overworld."""

    def __init__(self, memory, profile):
        self.memory = memory
        self.profile = profile

    # -- plumbing --------------------------------------------------------

    def _valid(self, pointer):
        return (
            isinstance(pointer, int)
            and self.profile.mem1_start <= pointer < self.profile.mem1_end
        )

    def _deref_count(self, address, label):
        """The database counts are a DOUBLE indirection ([[symbol]]) while
        the bases are a single one. That asymmetry is straight off
        pokemonDataBiosGetPtr / zokuseiBiosGetWazaJoutai; reading both the
        same way yields a pointer where a count belongs and silently
        rejects every lookup."""
        pointer = self.memory.u32(address, f"{label} count pointer")
        if not self._valid(pointer):
            return 0
        return self.memory.u32(pointer, f"{label} count")

    def hall_base(self):
        savedata = self.memory.pointer(
            self.profile.savedata_pointer_address,
            RELIVE_HALL_SAVEDATA_OFFSET + STAGE_COUNT * STAGE_SIZE,
            "purify chamber savedata", 4)
        return savedata + RELIVE_HALL_SAVEDATA_OFFSET

    def stage_address(self, index):
        if not 0 <= index < STAGE_COUNT:
            raise MemoryError(f"purify chamber SET index {index} out of range")
        return self.hall_base() + index * STAGE_SIZE

    # -- species / type lookups -------------------------------------------

    def _species_record(self, data_id):
        if not data_id or data_id >= self._deref_count(
                POKEMON_DATA_NUMBER, "species"):
            return None
        base = self.memory.u32(POKEMON_DATA, "species data base")
        if not self._valid(base):
            return None
        return base + data_id * POKEMON_DATA_STRIDE

    def species_types(self, data_id):
        """The pair of type ids, as `pokemonDataBiosGetZokuseiDataId` reads
        them. A single-typed Pokemon reports the same id twice -- that is
        how the data is stored, and the engine's matchup loop relies on it
        (the 2x2 cross product degenerates correctly)."""
        record = self._species_record(data_id)
        if record is None:
            return (0, 0)
        return (
            self.memory.u8(record + POKEMON_TYPE_OFFSET, "type 1"),
            self.memory.u8(record + POKEMON_TYPE_OFFSET + 1, "type 2"),
        )

    def species_name_message(self, data_id):
        record = self._species_record(data_id)
        if record is None:
            return 0
        return self.memory.u32(record + POKEMON_NAME_OFFSET, "species name id")

    def type_name_message(self, type_id):
        if type_id >= self._deref_count(ZOKUSEI_DATA_NUMBER, "type"):
            return 0
        base = self.memory.u32(ZOKUSEI_DATA, "type data base")
        if not self._valid(base):
            return 0
        return self.memory.u32(
            base + type_id * ZOKUSEI_STRIDE + ZOKUSEI_NAME_OFFSET,
            "type name id")

    def _chart_state(self, attacking, defending):
        """`zokuseiBiosGetWazaJoutai` (0x80117B28), bounds and all."""
        if attacking >= self._deref_count(ZOKUSEI_DATA_NUMBER, "type"):
            return 0
        if defending >= ZOKUSEI_DEFENDER_LIMIT:
            return 0
        base = self.memory.u32(ZOKUSEI_DATA, "type data base")
        if not self._valid(base):
            return 0
        return self.memory.u16(
            base + attacking * ZOKUSEI_STRIDE + ZOKUSEI_CHART_OFFSET
            + defending * 2, "type chart state")

    def _state_to_level(self, state):
        for index in range(JYOUTAI_TO_LEVEL_ENTRIES):
            entry = self.memory.u16(
                JYOUTAI_TO_LEVEL_TABLE + index * 2, "jyoutai2level entry")
            if entry == state:
                # The engine computes max(index - 1, 0) here, so its four
                # chart states collapse to three matchup levels (0, 0, 1, 2).
                return max(index - 1, 0)
        return UNMATCHED_LEVEL

    def matchup_level(self, first, second):
        """`reliveHallPokemonToAisyou` (0x8028C5A8): the best of the four
        type pairings between two Pokemon. -1 when either is absent."""
        if first is None or second is None:
            return -1
        level = 0
        for attacking in first.types:
            for defending in second.types:
                if attacking == 0 and defending == 0:
                    # Both pure Normal. The engine special-cases this to
                    # the "good" level instead of consulting the chart --
                    # a real quirk of the shipped code, reproduced rather
                    # than corrected.
                    value = 2
                else:
                    value = self._state_to_level(
                        self._chart_state(attacking, defending))
                level = max(level, value)
        return level

    # -- occupancy --------------------------------------------------------

    def _read_pokemon(self, address, slot):
        data_id = self.memory.u16(
            address + POKEMON_DATA_ID_OFFSET, "chamber Pokemon id")
        if not data_id:
            return None
        # `pokemonCheckValid` (0x8014130C) also rejects illegitimate and
        # unattested records. Those checks guard against corrupt or
        # hacked save data, not against anything a normal player can put
        # in a chamber slot, so a non-zero species id is the operative
        # test here; the species lookup below rejects a wild value anyway.
        types = self.species_types(data_id)
        try:
            nickname = self.memory.gschar(
                address + POKEMON_NICKNAME_OFFSET, POKEMON_NICKNAME_MAX,
                "chamber Pokemon nickname", 2)
        except MemoryError:
            nickname = ""
        return ChamberPokemon(
            slot=slot,
            data_id=data_id,
            nickname=nickname.strip(),
            level=self.memory.u8(
                address + POKEMON_LEVEL_OFFSET, "chamber Pokemon level"),
            types=types,
        )

    def dancers(self, stage):
        """Occupants of the outer positions.

        `getDancerQuantity` (0x8028E61C) stops at the FIRST empty slot
        rather than scanning all four, so the occupied positions are
        always a contiguous run from 0. Matching that exactly matters:
        Tempo pairs adjacent positions by index, so treating a gap as
        skippable would pair the wrong Pokemon together."""
        found = []
        for slot in range(DANCER_CAPACITY):
            pokemon = self._read_pokemon(stage + slot * DANCER_STRIDE, slot)
            if pokemon is None:
                break
            found.append(pokemon)
        return tuple(found)

    def visitor(self, stage):
        return self._read_pokemon(stage + VISITOR_OFFSET, -1)

    def facing(self, stage):
        value = self.memory.u8(stage + FACING_OFFSET, "chamber facing")
        return value - 256 if value > 127 else value

    # -- tempo and flow ----------------------------------------------------

    def _table_entry(self, table, index, label):
        return self.memory.u32(table + index * 4, label)

    def _pair_bonus(self, level, count, previous):
        """Contribution of one adjacent pair, exactly as the engine's own
        switch assigns it. `previous` reproduces the fall-through: for an
        unrecognised chart state the engine leaves its accumulator
        register untouched, so the pair silently contributes whatever the
        pair before it did."""
        if level == 1:
            return self._table_entry(
                TEMPO_NORMAL_TABLE, count, "tempo normal")
        if level in (2, 3):
            return self._table_entry(TEMPO_GOOD_TABLE, count, "tempo good")
        if level in (-1, 0):
            return 0
        return previous

    def tempo(self, dancers):
        """`CReliveStage::getTempo` (0x8028DB78)."""
        count = len(dancers)
        total = self._table_entry(TEMPO_BASE_TABLE, count, "tempo base")
        contribution = 0
        for index in range(count):
            partner = dancers[(index + 1) % count]
            contribution = self._pair_bonus(
                self.matchup_level(dancers[index], partner),
                count, contribution)
            total += contribution
        return total

    def flow(self, dancers, visitor, facing):
        """`CReliveStage::getPassionWoBonus` (0x8028DDBC): Tempo scaled by
        how well the Shadow Pokemon's type matches the one it faces."""
        if visitor is None:
            return 0
        tempo = self.tempo(dancers)
        if tempo == 0:
            return 0
        faced = dancers[facing] if 0 <= facing < len(dancers) else None
        level = self.matchup_level(visitor, faced)
        if level < 0 or level >= FLOW_MULTIPLIER_ENTRIES:
            return 0
        multiplier = self.memory.f32(
            FLOW_MULTIPLIER_TABLE + level * 4, "flow multiplier")
        return int(tempo * multiplier)

    def types_all_unique(self, dancers, visitor=None):
        """`isPokemonZokuseiAllUnique` (0x8028DA0C). A dual-typed Pokemon
        claims both of its types; a single-typed one claims only the one
        (its two stored ids are equal, and the engine stops at the repeat)."""
        claimed = set()
        for pokemon in tuple(dancers) + ((visitor,) if visitor else ()):
            previous = None
            for type_id in pokemon.types:
                if type_id == previous:
                    break
                if type_id in claimed:
                    return False
                claimed.add(type_id)
                previous = type_id
        return True

    def perfect_set_count(self):
        """`getReliveGiveStageQuantity` (0x8028D1AC): how many of the nine
        SETs are BEST CIRCLEs. Feeds the perfect-SET bonus, so it is a
        whole-chamber read even when only one SET is being looked at."""
        total = 0
        for index in range(STAGE_COUNT):
            stage = self.stage_address(index)
            dancers = self.dancers(stage)
            if (self.types_all_unique(dancers)
                    and self.tempo(dancers) == PERFECT_TEMPO):
                total += 1
        return total

    def bonus(self, dancers, visitor, flow):
        """`isBonusGet` (0x8028E1E8) plus `_bonusStageBonusTbl`."""
        if visitor is None or flow != PERFECT_FLOW:
            return 0
        if not self.types_all_unique(dancers, visitor):
            return 0
        index = min(self.perfect_set_count(), BONUS_STAGE_ENTRIES - 1)
        return self._table_entry(BONUS_STAGE_TABLE, index, "stage bonus")

    def read_set(self, index):
        stage = self.stage_address(index)
        dancers = self.dancers(stage)
        visitor = self.visitor(stage)
        facing = self.facing(stage)
        flow = self.flow(dancers, visitor, facing)
        bonus = self.bonus(dancers, visitor, flow)
        return ChamberSet(
            index=index,
            dancers=dancers,
            visitor=visitor,
            facing=facing,
            tempo=self.tempo(dancers),
            flow=flow + bonus,
            bonus=bonus,
        )

    def read_all(self):
        return tuple(self.read_set(index) for index in range(STAGE_COUNT))


# --- the live edit screen -----------------------------------------------
# `CMenuReliveHall`, allocated while the edit screen is open. Offsets are
# from the disassembly of the class's own accessors:
#   setStage (0x800405E8)            stw r4, 0x338(this) ; stw r3, 0x33C(this)
#   getCurrentPokemonPointer (0x800406F4)
#                                    r3 = [this + 0x80F64]      "catch" object
#                                    if picked-up: return catch + 0x20
#                                    pos = [catch + 0x0C]
#                                    0..5 -> getDancerPointer(stage, pos)
#                                    6    -> getVisitorPointer(stage)
MENU_POINTER = 0x804EA7F4
MENU_STAGE_INDEX_OFFSET = 0x338
MENU_CATCH_OFFSET = 0x80F64
CATCH_POSITION_OFFSET = 0x0C
CATCH_POKEMON_OFFSET = 0x20
CENTRE_POSITION = 6
OUTER_POSITIONS = 6
"""Cursor positions 0-5 ring the circle; 6 is the centre. Only the first
`len(dancers)` of the outer ones hold a Pokemon -- the rest are the empty
markers the game draws where another Pokemon could go
(`_markerDancerEmptyDirTbl`, 0x8032E674).

Confirmed from `_cursorPositionTblDefault` (0x8032E6B4), which is the
cursor's SCREEN position per index on a 640x480 display:

    [0]-[5]  -1        computed at runtime -- the ring, which moves with
                       the dancer count
    [6]      (320,280) horizontal centre, upper area: the Shadow Pokemon
    [7]      (198,428) bottom row, far left
    [8]      (539,428) bottom row, far right

`_cursorPositionTblAddPc` (0x804E7F28) inserts (336,428) and (379,428)
between them when the PC option is available.

Live sampling saw 0-5, 7 and 8 but never 6 -- consistent with the centre
not being a valid stop while the SET holds no Shadow Pokemon and none is
being carried."""

BOTTOM_ROW_POSITIONS = (7, 8)
"""Cursor stops on the bottom button row, left to right.

Their LABELS are not yet known -- the screen has `PC/PARTY POKeMON`, the
SET buttons and `Cancel` among its bottom-row text (messages 53539, 53532
/53533, 53538), but which index is which has not been confirmed. Until it
is, the reader announces the position, which is true and derived from the
coordinate table above, rather than guessing a label and sending the
player to the wrong button."""
BOTTOM_ROW_DESCRIPTIONS = {
    7: "Bottom menu, far left",
    8: "Bottom menu, far right",
}

# The action popup's option lists, read from the game's data rather than
# typed out: each is {count, message id...}. Which one opens depends on
# whether a Pokemon is being carried and what the cursor is over.
ACTION_MENU_TABLES = {
    ("carrying", "centre", "occupied"): 0x8032E768,
    ("carrying", "outer", "occupied"): 0x8032E780,
    ("carrying", "centre", "empty"): 0x8032E798,
    ("carrying", "outer", "empty"): 0x8032E7B0,
    ("empty-handed", "centre", "occupied"): 0x8032E7C8,
    ("empty-handed", "outer", "occupied"): 0x8032E7E0,
}
ACTION_MENU_MAX_OPTIONS = 5


class PurifyChamberReader:
    """Speaks the Purify Chamber edit screen.

    Four things change independently and each is announced on its own
    change, so nothing is repeated when it did not move:

      SET      selected with L and R -- announced with its whole state,
               because switching SETs is how the player compares them
      cursor   moved around the circle
      carrying whether a Pokemon is picked up
      action   the A-button popup (MOVE / PLACE / EXCHANGE / ROTATE /
               SUMMARY / CANCEL), whose labels come from the game's own
               message table

    Deliberately NOT handled here: the PC/party picker the Chamber opens
    to choose a Pokemon. That is the ordinary PC interface and
    `PCMenuReader` already narrates it; adding it here would double-speak
    every cell."""

    def __init__(self, memory, profile, model, catalog, speech, logger,
                 name_provider=None):
        self.memory = memory
        self.profile = profile
        self.model = model
        self.catalog = catalog
        self.speech = speech
        self.logger = logger
        self.name_provider = name_provider
        self.active = False
        self.last_set = None
        self.last_cursor = None
        self.last_carrying = None
        self.last_action = None

    def clear(self, reason="purify chamber closed"):
        if self.active:
            self.logger.debug("PURIFY CHAMBER CLEAR reason=%s", reason)
        self.active = False
        self.last_set = None
        self.last_cursor = None
        self.last_carrying = None
        self.last_action = None

    # -- naming -----------------------------------------------------------

    def _species(self, pokemon):
        return self.catalog.text(
            self.model.species_name_message(pokemon.data_id)) or "Pokemon"

    def _types(self, pokemon):
        seen = []
        for type_id in pokemon.types:
            if type_id in seen:
                continue
            seen.append(type_id)
        names = [self.catalog.text(self.model.type_name_message(t))
                 for t in seen]
        return " ".join(name for name in names if name)

    def describe_pokemon(self, pokemon, with_types=True):
        if pokemon is None:
            return "empty"
        name = pokemon.nickname or self._species(pokemon)
        parts = [name, f"level {pokemon.level}"]
        if with_types:
            types = self._types(pokemon)
            if types:
                parts.append(types)
        return ", ".join(parts)

    def describe_set(self, chamber_set):
        """The whole state of one SET, in the manual's vocabulary.

        Tempo is spoken as both the number and the level the on-screen bar
        shows, because the bar is what the guides talk about but the number
        is what actually decides whether adding a Pokemon helped."""
        if chamber_set.is_empty:
            return f"SET {chamber_set.index + 1}, empty."
        parts = [f"SET {chamber_set.index + 1}"]
        parts.append(
            f"{chamber_set.occupied} of {DANCER_CAPACITY} Pokemon placed")
        parts.append(
            f"Tempo {chamber_set.tempo}, {TEMPO_LEVEL_NAMES[chamber_set.tempo_level]}")
        if chamber_set.visitor is None:
            parts.append("no Shadow Pokemon, Flow zero")
        else:
            parts.append(f"Shadow {self.describe_pokemon(chamber_set.visitor)}")
            faced = (chamber_set.dancers[chamber_set.facing]
                     if 0 <= chamber_set.facing < chamber_set.occupied else None)
            if faced is not None:
                name = faced.nickname or self._species(faced)
                parts.append(f"facing position {chamber_set.facing + 1}, {name}")
            else:
                parts.append("facing an empty position")
            parts.append(f"Flow {chamber_set.flow}")
        if chamber_set.is_perfect:
            parts.append(f"best circle, bonus {chamber_set.bonus}")
        return ". ".join(parts) + "."

    # -- live menu --------------------------------------------------------

    def _menu(self):
        pointer = self.memory.u32(MENU_POINTER, "purify chamber menu pointer")
        if not self.model._valid(pointer):
            return None
        return pointer

    def _catch(self, menu):
        pointer = self.memory.u32(
            menu + MENU_CATCH_OFFSET, "purify chamber cursor object")
        return pointer if self.model._valid(pointer) else None

    def _carried(self, catch):
        """The Pokemon currently picked up, or None."""
        return self.model._read_pokemon(catch + CATCH_POKEMON_OFFSET, -1)

    def _action_options(self, carrying, position, occupied):
        table = ACTION_MENU_TABLES.get((
            "carrying" if carrying else "empty-handed",
            "centre" if position == CENTRE_POSITION else "outer",
            "occupied" if occupied else "empty",
        ))
        if table is None:
            return ()
        count = self.memory.u32(table, "purify action option count")
        if not 0 < count <= ACTION_MENU_MAX_OPTIONS:
            raise MemoryError(f"invalid purify action option count {count}")
        options = []
        for index in range(count):
            message_id = self.memory.u32(
                table + 4 + index * 4, "purify action option")
            options.append(self.catalog.text(message_id) or "")
        return tuple(options)

    def describe_cursor(self, chamber_set, position):
        if position == CENTRE_POSITION:
            return (f"Centre. {self.describe_pokemon(chamber_set.visitor)}."
                    if chamber_set.visitor
                    else "Centre, empty. Shadow Pokemon only.")
        if position in BOTTOM_ROW_DESCRIPTIONS:
            # Position, not a label. Saying "PC/PARTY POKeMON" when it might
            # be "Cancel" would send the player out of the screen they are
            # trying to use; saying nothing leaves the bottom row silent and
            # unusable. Announcing where the cursor is, is true either way.
            return f"{BOTTOM_ROW_DESCRIPTIONS[position]}."
        if not 0 <= position < OUTER_POSITIONS:
            return None
        if position < chamber_set.occupied:
            pokemon = chamber_set.dancers[position]
            return f"Position {position + 1}. {self.describe_pokemon(pokemon)}."
        return f"Position {position + 1}, empty."

    def poll_once(self):
        menu = self._menu()
        if menu is None:
            if self.active:
                self.clear()
            return
        catch = self._catch(menu)
        if catch is None:
            return
        index = self.memory.u32(
            menu + MENU_STAGE_INDEX_OFFSET, "purify chamber SET index")
        if not 0 <= index < STAGE_COUNT:
            raise MemoryError(f"invalid purify chamber SET index {index}")
        chamber_set = self.model.read_set(index)
        position = self.memory.u32(
            catch + CATCH_POSITION_OFFSET, "purify chamber cursor position")
        carried = self._carried(catch)
        carrying = carried.nickname if carried else None
        first = not self.active
        self.active = True

        if index != self.last_set:
            self.speech.emit(
                SpeechEventClass.ENTITY_NAV, self.describe_set(chamber_set),
                interrupt=True)
            self.logger.info(
                "PURIFY CHAMBER SET %d tempo=%d flow=%d occupied=%d",
                index + 1, chamber_set.tempo, chamber_set.flow,
                chamber_set.occupied)
            self.last_set = index
            self.last_cursor = None

        if carrying != self.last_carrying:
            if carrying:
                self.speech.emit(
                    SpeechEventClass.ENTITY_NAV, f"Holding {carrying}.",
                    interrupt=True)
            elif self.last_carrying is not None and not first:
                self.speech.emit(
                    SpeechEventClass.ENTITY_NAV,
                    f"Released {self.last_carrying}.", interrupt=True)
            self.last_carrying = carrying

        if position != self.last_cursor:
            text = self.describe_cursor(chamber_set, position)
            if text:
                self.speech.emit(
                    SpeechEventClass.ENTITY_NAV, text, interrupt=True)
            self.last_cursor = position
