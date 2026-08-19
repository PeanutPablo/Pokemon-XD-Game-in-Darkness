"""Read-only overworld party roster (Hero.partyPokemon[6])."""
from dataclasses import dataclass
from .health import round_percent
from .memory import MemoryError

# Standard Gen 3 nature order, indexed by personality-value % 25.
# Live-confirmed: a personality value ("rnd") of 0x23CFCB26 (%25 == 18)
# resolved to "Bashful" here, exactly matching the project owner's own OCR
# of the live Info page ("BASHFUL nature.").
NATURES = (
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
    "Bold", "Docile", "Relaxed", "Impish", "Lax",
    "Timid", "Hasty", "Serious", "Jolly", "Naive",
    "Modest", "Mild", "Quiet", "Bashful", "Rash",
    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
)

@dataclass(frozen=True)
class PartyMove:
    name: str
    pp: int
    maximum_pp: int = 0
    type_name: str = ""
    description: str = ""

@dataclass(frozen=True)
class PartyStats:
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int

@dataclass(frozen=True)
class PartySlot:
    index: int
    raw_nickname: str
    level: int
    hp: int
    max_hp: int
    condition: int
    stats: PartyStats
    moves: tuple
    ot_name: str
    exp: int
    nature: str
    item_id: int
    ability_name: str
    ability_description: str
    heart_gauge_percent: int | None = None
    species: int = 0
    """National/internal species ID. `_decode_slot` has always read it (it is
    what decides whether a slot is populated at all) but never carried it on
    the slot, until `menus.progress_notification_focus` was found matching
    against `slot.species` -- an attribute that did not exist (2026-08-04).

    Deliberately a defaulted TRAILING field rather than sitting next to
    `raw_nickname` where it belongs conceptually: a dataclass's field order
    is its constructor signature, and inserting it early renamed the meaning
    of every positional argument after it, breaking 34 existing construction
    sites at once. A trailing default leaves every one of them valid, so the
    change carries no risk of quietly mis-assigning a field somewhere that
    was not re-checked."""

class PartyMemorySource:
    PCBOX_SAVEDATA_OFFSET = 0xAD0
    PCBOX_BOX_STRIDE = 0x170C
    PCBOX_BOX_HEADER = 0x14
    PCBOX_SLOT_STRIDE = 0xC4
    PCBOX_BOX_COUNT = 8
    PCBOX_SLOTS_PER_BOX = 30
    PURIFY_HALL_SAVEDATA_OFFSET = 0x1D690
    PURIFY_STAGE_COUNT = 9
    PURIFY_STAGE_SIZE = 984
    PURIFY_VISITOR_OFFSET = 784

    def __init__(self, memory, profile, move_data=None, ability_data=None):
        self.memory, self.profile = memory, profile
        self.move_data, self.ability_data = move_data, ability_data

    def _stats(self, base):
        p = self.profile
        return PartyStats(
            self.memory.u16(base + p.party_attack_offset, "party attack"),
            self.memory.u16(base + p.party_defense_offset, "party defense"),
            self.memory.u16(base + p.party_special_attack_offset, "party special attack"),
            self.memory.u16(base + p.party_special_defense_offset, "party special defense"),
            self.memory.u16(base + p.party_speed_offset, "party speed"),
        )

    def _savedata_base(self):
        return self.memory.pointer(
            self.profile.savedata_pointer_address, 4, "savedata pointer", 4)

    def _dark_status(self, base, index):
        """Returns (dark_waza, heart_gauge_percent) for this Pokemon, or
        (None, None) if it isn't currently a Shadow Pokemon at all.

        dark_waza is a 4-entry list of per-slot Shadow-move-ID overrides --
        a slot's own entry reading 0 means that specific slot isn't
        shadow-locked (confirmed live, not assumed -- see profile.py's
        dark_pokemon_data_id_offset comment), so callers should fall back
        to the normal move ID for any slot whose override is 0.

        heart_gauge_percent is 0-100: how far toward "fully open, ready to
        purify" this individual's Dark Point has drained from its
        InitDarkPoint maximum -- direction confirmed 2026-07-30 directly by
        the project owner against their own live Teddiursa (see profile.py's
        darkpokemon_array_savedata_offset comment). None if InitDarkPoint
        reads 0 (shouldn't happen for a real Shadow Pokemon, but avoids a
        division by zero if it ever does)."""
        p = self.profile
        dark_id = self.memory.u16(
            base + p.dark_pokemon_data_id_offset, f"dark pokemon id {index}")
        if not dark_id:
            return None, None
        deck_base = self.memory.pointer(
            p.deck_dark_pokemon_pointer_address,
            (dark_id + 1) * p.deck_dark_pokemon_stride,
            f"deck dark pokemon {index}",
            4,
        )
        deck_record = deck_base + dark_id * p.deck_dark_pokemon_stride
        waza = [
            self.memory.u16(
                deck_record + p.deck_dark_pokemon_waza_offset + slot * 2,
                f"dark waza {index}.{slot}")
            for slot in range(p.move_slot_count)
        ]
        max_point = self.memory.u16(
            deck_record + p.deck_dark_pokemon_init_dark_point_offset,
            f"init dark point {index}")
        if not max_point:
            return waza, None
        savedata_base = self._savedata_base()
        dark_pokemon_record = (
            savedata_base + p.darkpokemon_array_savedata_offset
            + dark_id * p.dark_pokemon_stride
        )
        flags = self.memory.u8(
            dark_pokemon_record + p.dark_pokemon_flags_offset,
            f"dark pokemon flags {index}")
        if flags & p.dark_pokemon_purified_flag:
            return None, None
        current = self.memory.u32(
            dark_pokemon_record + p.dark_point_direct_offset,
            f"current dark point {index}")
        if current & 0x80000000:
            current -= 0x100000000
        current = max(0, min(current, max_point))
        _, percent = round_percent(max_point - current, max_point)
        # A fully-open heart uses the Pokemon struct's ordinary move slots.
        # Live 2026-08-10 one-shot proof: FARQUAD had current/max 0/2500;
        # the battle UI exposed Facade/Sand Tomb/Thundershock/ExtremeSpeed
        # with IDs and properties matching LocalMoveData, while the deck's
        # still-nonzero 356/368 entries were stale Shadow Blitz/Hold data.
        # Thus a nonzero deck entry is not, by itself, a current-display
        # flag. Keep the deck override only while Dark Point remains above
        # zero; do not extrapolate unverified intermediate unlock thresholds.
        if current == 0:
            waza = [0] * p.move_slot_count
        return waza, percent

    def _moves(self, base, index, dark_waza):
        p = self.profile
        moves = []
        for slot in range(p.move_slot_count):
            move_base = base + p.pokemon_moves_offset + slot * p.pokemon_move_stride
            move_id = self.memory.u16(move_base + p.pokemon_move_id_offset,
                                      f"party move ID {index}.{slot}")
            if move_id == 0:
                continue
            shadow_override = bool(dark_waza and dark_waza[slot])
            if shadow_override:
                move_id = dark_waza[slot]
            pp = self.memory.u8(move_base + p.pokemon_move_pp_offset,
                                f"party move PP {index}.{slot}")
            maximum_pp = 0
            type_name = ""
            description = ""
            if self.move_data is None:
                name = f"move {move_id}"
            else:
                try:
                    name, _ = self.move_data.resolve(move_id)
                    if not hasattr(self.move_data, "details"):
                        moves.append(PartyMove(name, pp))
                        continue
                    details = self.move_data.details(move_id)
                    pp_ups = self.memory.u8(
                        move_base + p.pokemon_move_pp_ups_offset,
                        f"party move PP Ups {index}.{slot}",
                    )
                    if pp_ups > 3:
                        raise MemoryError("invalid PP Up count")
                    maximum_pp = details.base_pp + (
                        details.base_pp * pp_ups // 5
                    )
                    if shadow_override:
                        # Shadow overrides borrow the underlying normal move
                        # record, whose current PP/type describe that hidden
                        # move (live: Return 19 PP). Shadow moves have their own
                        # fixed 5 PP and runtime-applied Shadow typing.
                        pp = maximum_pp
                        type_name = "Shadow"
                    else:
                        type_name = details.type_name
                    description = details.effect_description
                except MemoryError:
                    name = f"move {move_id}"
            moves.append(PartyMove(
                name, pp, maximum_pp, type_name, description
            ))
        return tuple(moves)

    def _hero_base(self):
        p = self.profile
        savedata = self.memory.pointer(
            p.savedata_pointer_address,
            p.hero_offset + p.hero_party_offset
            + p.hero_party_slots * p.hero_party_stride,
            "party savedata pointer",
            4,
        )
        return savedata + p.hero_offset

    def _decode_slot(self, base, index):
        p = self.profile
        species = self.memory.u16(base + p.party_species_offset,
                                  f"party species {index}")
        if species == 0:
            return None
        nickname = self.memory.gschar(
            base + p.party_nickname_offset,
            p.party_nickname_max_chars, f"party nickname {index}", 2)
        hp = self.memory.u16(base + p.party_current_hp_offset,
                             f"party current HP {index}")
        maxhp = self.memory.u16(base + p.party_max_hp_offset,
                                f"party max HP {index}")
        level = self.memory.u8(base + p.party_level_offset,
                               f"party level {index}")
        condition = self.memory.u8(base + p.party_condition_offset,
                                   f"party condition {index}")
        if not nickname.strip() or not 1 <= maxhp <= p.maximum_plausible_hp or hp > maxhp:
            raise MemoryError(f"party slot {index}: implausible data {nickname!r} {hp}/{maxhp}")
        if not 1 <= level <= 100:
            raise MemoryError(f"party slot {index}: implausible level {level}")
        if condition not in p.valid_major_conditions:
            raise MemoryError(f"party slot {index}: invalid condition {condition}")
        stats = self._stats(base)
        try:
            dark_waza, heart_gauge_percent = self._dark_status(base, index)
        except MemoryError:
            dark_waza, heart_gauge_percent = None, None
        moves = self._moves(base, index, dark_waza)
        ot_name = self.memory.gschar(
            base + p.party_ot_offset, p.party_ot_max_chars, f"party OT {index}", 2)
        exp = self.memory.u32(base + p.party_exp_offset, f"party EXP {index}")
        personality = self.memory.u32(
            base + p.party_personality_offset, f"party personality {index}")
        nature = NATURES[personality % len(NATURES)]
        item_id = self.memory.u16(base + p.party_item_offset, f"party item {index}")
        ability_name, ability_description = self._ability(
            base, species, personality, index)
        return PartySlot(index, nickname, level, hp, maxhp, condition,
                         stats, moves, ot_name, exp, nature, item_id,
                         ability_name, ability_description, heart_gauge_percent,
                         species=species)

    def slots(self):
        p = self.profile
        hero = self._hero_base()
        result = []
        for index in range(p.hero_party_slots):
            base = hero + p.hero_party_offset + index * p.hero_party_stride
            slot = self._decode_slot(base, index)
            if slot is not None:
                result.append(slot)
        return result

    def pc_slots(self):
        """Decode every occupied Pokemon Storage cell in box/slot order."""
        savedata = self._savedata_base()
        result = []
        for box in range(self.PCBOX_BOX_COUNT):
            box_base = (savedata + self.PCBOX_SAVEDATA_OFFSET
                        + box * self.PCBOX_BOX_STRIDE
                        + self.PCBOX_BOX_HEADER)
            for index in range(self.PCBOX_SLOTS_PER_BOX):
                base = box_base + index * self.PCBOX_SLOT_STRIDE
                try:
                    slot = self._decode_slot(base, index)
                except MemoryError:
                    # Match the PC menu reader: a half-written or otherwise
                    # invalid cell is treated as empty, without hiding valid
                    # Shadow Pokemon elsewhere in storage.
                    continue
                if slot is not None:
                    result.append(slot)
        return result

    def party_and_pc_slots(self):
        """Return all occupied party and PC slots, in stable display order."""
        return self.slots() + self.pc_slots()

    def purify_chamber_slots(self):
        """Decode the Shadow visitor at the centre of every occupied SET."""
        savedata = self._savedata_base()
        result = []
        for index in range(self.PURIFY_STAGE_COUNT):
            base = (savedata + self.PURIFY_HALL_SAVEDATA_OFFSET
                    + index * self.PURIFY_STAGE_SIZE
                    + self.PURIFY_VISITOR_OFFSET)
            try:
                slot = self._decode_slot(base, index)
            except MemoryError:
                continue
            if slot is not None:
                result.append(slot)
        return result

    def shadow_gauge_slots(self):
        """All possible owned Shadow locations, in party/PC/SET order."""
        return self.slots() + self.pc_slots() + self.purify_chamber_slots()

    def slot_for_pointer(self, pointer):
        """Decode whichever Pokemon struct a live pointer references --
        used by the summary screen's `_menuStatus+0x0C` field, which
        holds the ACTUAL Pokemon* currently being displayed (party, PC
        box, or an opponent's), not necessarily tied to a party index at
        all. Same struct layout and validation as a party slot either
        way -- the game reuses one Pokemon struct format everywhere."""
        if not pointer:
            return None
        return self._decode_slot(pointer, -1)

    def _ability(self, base, species, personality, index):
        if self.ability_data is None:
            return "", ""
        ability_index = self.memory.u8(
            base + self.profile.party_ability_index_offset,
            f"party ability index {index}",
        )
        if not ability_index:
            # Compatibility for incomplete/synthetic records. Real party
            # Pokemon carry their resolved ability index at +0x1D; older
            # tests and partially populated records may leave it zero.
            try:
                ability_index = self.ability_data.species_ability_index(
                    species, personality)
            except MemoryError:
                return "", ""
        try:
            return self.ability_data.resolve(self.memory, self.profile, ability_index)
        except MemoryError:
            return f"ability {ability_index}", ""
