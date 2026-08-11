import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path

import _dialogue_extraction_tool as extraction

from .battle_identity import (
    FOE, PLAYER, BattleIdentityResolver, speech_case,
)
from .memory import MemoryError
from .messages import LocalDataError
from .runtime_messages import RuntimeMessageCatalog


MOVE_ID = 20333
STAT_IDS = {20243, 20244, 20246, 20247}
STAT_ID = 20243
# Stat-change messages substitute either the attacker's own nickname
# (opcode 0x0F / "Pokemon 15", attack_mons) or the target's (opcode 0x10 /
# "Pokemon 16", tsuika_mons) depending on which Pokemon the stat change
# actually applies to -- e.g. a self-buff like Swords Dance vs. an
# opponent-directed drop like Growl/Leer. Confirmed via
# _dialogue_extraction_tool.py's OPCODE_NAMES table (0x0F: "Pokemon 15",
# 0x10: "Pokemon 16") and live log evidence: 20243/20246 always carry
# opcode 0x0F, 20244/20247 always carry 0x10.
STAT_ACTOR_IDS = {20243, 20246}
STAT_TARGET_IDS = {20244, 20247}
SUPER_EFFECTIVE_ID = 20256
POISONED_ID = 20032
POISON_DAMAGE_ID = 20034
FAINTED_ID = 20021
TARGET_FAINTED_ID = 20022
FAINTED_IDS = {FAINTED_ID, TARGET_FAINTED_ID}
LOSS_ID = 20024
WHITEOUT_ID = 20025
LOSS_IDS = {LOSS_ID, WHITEOUT_ID}
FULL_PARALYSIS_ID = 20050
REVERSE_MODE_ID = 20450

LEVEL_UP_ID = 20006
# --- RETIRED 2026-08-06 (Phase 3) -------------------------------------
# What stood here: ACTOR_SENTENCE_TEMPLATES (8 sentences),
# FIXED_SENTENCES (11), CATCH_TARGET_TEMPLATES (13), VICTORY_SENTENCE,
# PARTIAL_TRAINER_SENTENCES -- game text retyped into Python, plus the
# per-message-ID opcode allow-list in narrator.VERIFIED_OPCODES that
# decided which messages were allowed to use them.
#
# All of it is replaced by `message_render.MessageRenderer`, which renders
# the game's own template through the shipped `msgctrlcode` dispatch table
# (see battle_opcodes.REGISTRY). Two of the retired strings carried
# mojibake -- "Oh! A Shadow PokEmon!" with the e-acute stored as two
# cp1252 characters -- which is the concrete demonstration of why a
# hand-typed copy of game text cannot be trusted: it had silently drifted
# from the game's own and nothing failed.
#
# Per-ID detail of every retired sentence, its authoritative template, and
# the test that replaced it is in
# Documentation/BATTLE_MESSAGE_PIPELINE.md.

# IDs whose narration has a side effect beyond speaking, and which the
# narrator therefore still recognises by number. Nothing here carries text.
MOVE_LEARNING_IDS = {20007, 20008, 20009, 20010, 20011, 20012, 20013}
GO_SEND_OUT_ID = 20312
FOE_SEND_OUT_ID = 20304
DOUBLE_FOE_SEND_OUT_ID = 20305
DOUBLE_PLAYER_SEND_OUT_ID = 20313
DOUBLE_SEND_OUT_IDS = {DOUBLE_FOE_SEND_OUT_ID, DOUBLE_PLAYER_SEND_OUT_ID}
# Which side a send-out message is about. This is the ONLY thing that says
# so: the four name globals are written by both sides (the writer stores
# each entering Pokemon's nickname into a 0x14/0x16 or 0x15/0x17 pair
# regardless of whose it is), so `_ENEMY_MONS` is not "the enemy's".
PLAYER_SEND_OUT_IDS = {GO_SEND_OUT_ID, DOUBLE_PLAYER_SEND_OUT_ID}
FOE_SEND_OUT_IDS = {FOE_SEND_OUT_ID, DOUBLE_FOE_SEND_OUT_ID}
SEND_OUT_IDS = PLAYER_SEND_OUT_IDS | FOE_SEND_OUT_IDS


def normalize(value):
    return re.sub(r"\s+", " ", value).strip().casefold()


def display_case(value):
    if value and value == value.upper() and any(ch.isalpha() for ch in value):
        return value.title()
    return value


@dataclass(frozen=True)
class Actor:
    fight_out: int
    fight_pokemon: int
    nickname_address: int
    nickname: str


@dataclass(frozen=True)
class MoveSample:
    actor: Actor
    move_name_pointer: int
    suffix_pointer: int
    move_id: int
    move_name: str
    suffix: str


@dataclass(frozen=True)
class StatSample:
    actor: Actor
    stat_pointer: int
    magnitude_pointer: int
    direction_pointer: int
    stat: str
    magnitude: str
    direction: str


@dataclass(frozen=True)
class PlayerSample:
    pointer: int
    name: str


@dataclass(frozen=True)
class LevelSample:
    # `recipient` is a battle_identity.BattlerIdentity, not an Actor: the
    # Pokemon that levels up need not be on the field at all (Exp. Share, a
    # participant that fainted), so there may be no FightOutPokemon for it.
    recipient: object
    level: int


class LocalMoveData:
    STRIDE = 0x38
    # Move records begin with signed priority at +0, then base PP at +1.
    # Reading a u16 at +0 made EXTREMESPEED's `01 05` become impossible
    # 261 PP and discarded all of its otherwise-valid details.
    PP_OFFSET = 0x01
    TYPE_OFFSET = 0x02
    ACCURACY_OFFSET = 0x04
    POWER_OFFSET = 0x18
    NAME_OFFSET = 0x20
    SUFFIX_OFFSET = 0x28
    DESCRIPTION_OFFSET = 0x2C
    TYPE_NAMES = (
        "Normal", "Fighting", "Flying", "Poison", "Ground", "Rock",
        "Bug", "Ghost", "Steel", "Unknown", "Fire", "Water", "Grass",
        "Electric", "Psychic", "Ice", "Dragon", "Dark", "Shadow",
    )

    def __init__(self, extraction_dir, catalog):
        path = Path(extraction_dir) / "raw" / "files" / "common.fsys"
        if not path.is_file():
            raise LocalDataError(
                "Local move data is missing. Run the existing extraction process "
                "against your own verified game image."
            )
        try:
            files = extraction.parse_fsys(path.read_bytes())
            common_rel = next(item for item in files if item["name"] == "common_rel")
            self.data = common_rel["data"]
            rel = extraction.RelFile(self.data)
            self.moves_base = rel.get_pointer(124)
            names_base = rel.get_pointer(136)
            self.names = extraction.decode_string_table(self.data[names_base:])
        except Exception as exc:
            raise LocalDataError(f"Could not load local move data: {exc}") from exc
        self.catalog = catalog
        descriptions_path = Path(extraction_dir) / "dol_strings.json"
        try:
            self.descriptions = json.loads(
                descriptions_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise LocalDataError(
                f"Could not load move descriptions: {exc}"
            ) from exc

    def resolve(self, move_id):
        entry = self.moves_base + move_id * self.STRIDE
        if move_id <= 0 or entry < 0 or entry + self.STRIDE > len(self.data):
            raise MemoryError(f"Move ID {move_id} is outside local data")
        name_id = struct.unpack_from(">I", self.data, entry + self.NAME_OFFSET)[0]
        suffix_id = struct.unpack_from(">I", self.data, entry + self.SUFFIX_OFFSET)[0]
        tokens = self.names.get(name_id)
        suffix_message = self.catalog.get(suffix_id)
        if tokens is None or suffix_message is None or suffix_message.opcodes:
            raise MemoryError(f"Move {move_id} lacks safe local text")
        name = extraction.render_tokens(tokens)
        if any(token[0] == "ctrl" for token in tokens):
            raise MemoryError(f"Move {move_id} name contains controls")
        return name, suffix_message.template

    def details(self, move_id):
        entry = self.moves_base + move_id * self.STRIDE
        if move_id <= 0 or entry < 0 or entry + self.STRIDE > len(self.data):
            raise MemoryError(f"Move ID {move_id} is outside local data")
        type_id = self.data[entry + self.TYPE_OFFSET]
        if type_id >= len(self.TYPE_NAMES):
            raise MemoryError(f"Move {move_id} has invalid type {type_id}")
        pp = self.data[entry + self.PP_OFFSET]
        power = struct.unpack_from(">H", self.data, entry + self.POWER_OFFSET)[0]
        accuracy = self.data[entry + self.ACCURACY_OFFSET]
        description_id = struct.unpack_from(
            ">I", self.data, entry + self.DESCRIPTION_OFFSET
        )[0]
        description = self.descriptions.get(str(description_id), "")
        if not 0 < pp <= 99 or accuracy > 100:
            raise MemoryError(f"Move {move_id} has invalid properties")
        description = re.sub(r"\s+", " ", description).strip()
        if not description:
            raise MemoryError(f"Move {move_id} has an empty description")
        return MoveDetails(
            self.TYPE_NAMES[type_id], power, accuracy, pp, description
        )


@dataclass(frozen=True)
class MoveDetails:
    type_name: str
    power: int
    accuracy: int
    base_pp: int
    effect_description: str = ""

    @property
    def description(self):
        facts = [f"{self.type_name}-type"]
        facts.append(f"power {self.power}" if self.power else "status move")
        facts.append(
            f"{self.accuracy} percent accuracy"
            if self.accuracy else "does not use a standard accuracy check"
        )
        if self.effect_description:
            facts.append(self.effect_description)
        return ", ".join(facts)


class LocalAbilityData:
    """Resolves a species' ability name/description text.

    Two-part lookup, both cross-checked live against Eevee (species 133):
    species -> ability index comes from the offline species base-stats
    table (`common.rel`, REL pointer 88, `0x124`-byte stride, ability1/
    ability2 bytes at +0x32/+0x33 -- matches `Pokemon-XD-Code`'s
    `XGPokemonStats.swift` exactly); ability index -> name/description
    comes from a LIVE read of a small table embedded in the game's loaded
    executable image at a fixed RAM address (not in `common.rel`, so it
    can't be read fully offline the way move/species data can). That
    address (`profile.abilities_table_base`) was derived by hand-decoding
    the `lis`/`addi` instruction pair `Pokemon-XD-Code`'s own
    `kAbilitiesStartRAMOffset` reads from the vanilla `main.dol` at file
    offset `0x1411f8+30`/`+34` (bytes `3C 60 80 40` / `38 03 FC 50`), then
    live-verified: reading Eevee's ability index (50) from this table
    resolved to message IDs 3150/3350, which decoded via the same
    `common.rel` string table used for move names to "RUN AWAY" /
    "Makes escaping easier." -- an exact match to the project owner's own
    OCR of the live Status page.
    """
    STRIDE = 0x124
    ABILITY1_OFFSET = 0x32
    ABILITY2_OFFSET = 0x33

    def __init__(self, extraction_dir):
        path = Path(extraction_dir) / "raw" / "files" / "common.fsys"
        if not path.is_file():
            raise LocalDataError(
                "Local ability data is missing. Run the existing extraction "
                "process against your own verified game image."
            )
        try:
            files = extraction.parse_fsys(path.read_bytes())
            common_rel = next(item for item in files if item["name"] == "common_rel")
            self.data = common_rel["data"]
            rel = extraction.RelFile(self.data)
            self.species_stats_base = rel.get_pointer(88)
            names_base = rel.get_pointer(136)
            self.names = extraction.decode_string_table(self.data[names_base:])
        except Exception as exc:
            raise LocalDataError(f"Could not load local ability data: {exc}") from exc

    def species_ability_index(self, species_id, personality):
        entry = self.species_stats_base + species_id * self.STRIDE
        if species_id <= 0 or entry < 0 or entry + self.STRIDE > len(self.data):
            raise MemoryError(f"Species ID {species_id} is outside local data")
        ability1 = self.data[entry + self.ABILITY1_OFFSET]
        ability2 = self.data[entry + self.ABILITY2_OFFSET]
        if ability2 and personality % 2 == 1:
            return ability2
        return ability1

    def resolve(self, memory, profile, ability_index):
        base = profile.abilities_table_base + ability_index * profile.abilities_table_stride
        name_id = memory.u32(base + profile.abilities_name_id_offset, "ability name ID")
        desc_id = memory.u32(base + profile.abilities_description_id_offset, "ability description ID")
        name_tokens = self.names.get(name_id)
        desc_tokens = self.names.get(desc_id)
        if name_tokens is None or desc_tokens is None:
            raise MemoryError(f"Ability {ability_index} lacks safe local text")
        if any(token[0] == "ctrl" for token in name_tokens):
            raise MemoryError(f"Ability {ability_index} name contains controls")
        name = extraction.render_tokens(name_tokens)
        description = extraction.render_tokens(desc_tokens)
        return name, description


class VerifiedResolver:
    def __init__(self, memory, profile, catalog, move_data,
                 identity=None, slot_tracker=None):
        self.memory = memory
        self.profile = profile
        self.catalog = catalog
        self.move_data = move_data
        # Canonical battler identity (battle_identity.py). Optional so the
        # many existing tests that build a VerifiedResolver directly keep
        # working; production wires the real one in.
        self.identity = identity or BattleIdentityResolver(memory, profile)
        self.slot_tracker = slot_tracker

    def _epochs(self):
        return None if self.slot_tracker is None else self.slot_tracker.epochs

    def send_out_event(self, side, opcodes):
        """Authoritative subject of a send-out message.

        Replaces `trainer_party_names()`, which returned the first N named
        slots of the PERSISTENT party array -- party order, never send-out
        order. That is why a mid-battle replacement announced the trainer's
        first Pokemon and why Baton Pass made the two diverge for the rest
        of the battle. The names here are the ones the game itself put in
        the msgctrl globals for this very message."""
        return self.identity.send_out_event(
            side, opcodes, epochs=self._epochs())

    def level_up_recipient(self):
        """The Pokemon the game is crediting, from
        `get_exp_fight_pokemon_ptr`. Not `_ATTACK_MONS`: the attacker and
        the Pokemon that levels are different whenever more than one party
        member is earning experience."""
        return self.identity.resolve_level_up_recipient(epochs=self._epochs())

    def actor(self, global_address):
        p = self.profile
        fight_out = self.memory.pointer(
            global_address, p.current_move_id_offset + 2, "FightOutPokemon", 4
        )
        fight_pokemon = self.memory.pointer(
            fight_out + p.fight_out_pokemon_offset,
            p.nickname_offset + 24,
            "FightPokemon",
            4,
        )
        nickname_address = fight_pokemon + p.nickname_offset
        nickname = self.memory.gschar(nickname_address, 11, "nickname", 2)
        if not nickname.strip():
            raise MemoryError("Nickname is empty")
        return Actor(fight_out, fight_pokemon, nickname_address, nickname)

    def pointed_text(self, global_address, label, maximum=64, alignment=1):
        pointer = self.memory.pointer(
            global_address, (maximum + 1) * 2, label, alignment
        )
        return pointer, self.memory.gschar(pointer, maximum, label, alignment)

    def move_sample(self):
        p = self.profile
        actor = self.actor(p.attack_mons)
        name_pointer, name = self.pointed_text(p.waza_name, "_WAZA_NAME")
        suffix_pointer, suffix = self.pointed_text(p.ev_str_buf1, "_EV_STR_BUF1")
        move_id = self.memory.u16(
            actor.fight_out + p.current_move_id_offset, "current move ID"
        )
        return MoveSample(actor, name_pointer, suffix_pointer, move_id, name, suffix)

    def stat_sample(self, actor_global=None):
        p = self.profile
        actor = self.actor(actor_global or p.attack_mons)
        stat_pointer, stat = self.pointed_text(p.ev_str_buf0, "_EV_STR_BUF0")
        magnitude_pointer, magnitude = self.pointed_text(p.ev_str_buf1, "_EV_STR_BUF1")
        direction_pointer, direction = self.pointed_text(p.ev_str_buf2, "_EV_STR_BUF2")
        return StatSample(
            actor,
            stat_pointer,
            magnitude_pointer,
            direction_pointer,
            stat,
            magnitude,
            direction,
        )

    def trainer_party_names(self, side_index, count=2):
        if side_index not in (0, 1) or count < 1:
            raise MemoryError("Invalid trainer party request")
        trainer = self.profile.fight_floor_root + side_index * 0x6EF0 + 0x14 + 0x64
        names = []
        for slot in range(6):
            fight_pokemon = trainer + 0x97C + slot * 0x300
            name = self.memory.gschar(fight_pokemon + 0x52, 11, "trainer party nickname", 2)
            if name.strip():
                names.append(display_case(name))
            if len(names) == count:
                return tuple(names)
        raise MemoryError(f"Trainer side {side_index} has fewer than {count} named Pok?mon")

    def opponent_trainer_full_name(self):
        p = self.profile
        # The transient class/name globals are not populated while the
        # challenge line is being narrated. Follow the same permanent route
        # as fightTrainerGetPrefixNamePtr instead.
        trainer = p.fight_floor_root + 0x6EF0 + 0x14 + 0x64
        trainer_id = self.memory.u16(trainer, "opponent trainer data ID")
        deck_size = self.memory.u32(p.deck_trainer_size, "deck trainer count")
        if trainer_id >= deck_size:
            raise MemoryError("Opponent trainer data ID is outside the loaded deck")
        deck = self.memory.pointer(
            p.deck_trainer_pointer,
            deck_size * p.deck_trainer_stride,
            "deck trainer table",
            4,
        )
        kind = self.memory.u8(
            deck + trainer_id * p.deck_trainer_stride + p.deck_trainer_kind_offset,
            "opponent trainer kind",
        )
        count_pointer = self.memory.pointer(
            p.trainer_kind_count_pointer, 4, "trainer-kind count", 4
        )
        count = self.memory.u32(count_pointer, "trainer-kind count")
        if kind >= count:
            raise MemoryError("Opponent trainer kind is outside the kind table")
        kinds = self.memory.pointer(
            p.trainer_kind_data_pointer,
            count * p.trainer_kind_stride,
            "trainer-kind table",
            4,
        )
        title_id = self.memory.u32(
            kinds + kind * p.trainer_kind_stride + p.trainer_kind_title_id_offset,
            "opponent trainer title message ID",
        )
        title = RuntimeMessageCatalog(self.memory, p).text(title_id) or ""
        name = self.memory.gschar(trainer + 0x04, 11, "opponent trainer name", 2)
        title = display_case(title.strip())
        name = display_case(name.strip())
        if not title or not name:
            raise MemoryError("Opponent trainer class or name is empty")
        return f"{title} {name}"

    def opponent_trainer_name(self):
        # side 1, trainer 0; trainer+4 is its embedded Hero, whose first
        # field is the trainer name returned by fightTrainerGetNamePtr.
        trainer = self.profile.fight_floor_root + 0x6EF0 + 0x14 + 0x64
        name = self.memory.gschar(trainer + 0x04, 11, "opponent trainer name", 2)
        if not name.strip():
            raise MemoryError("Opponent trainer name is empty")
        return display_case(name)

    def player_sample(self):
        pointer, name = self.pointed_text(
            self.profile.my_name, "_MY_NAME", maximum=11, alignment=2
        )
        if not name.strip():
            raise MemoryError("Player name is empty")
        return PlayerSample(pointer, name)

    # RETIRED 2026-08-06: `move_learning_sample`, `battle_quantity_sample`
    # and `experience_message_sample` read msgvars by hand for three
    # specific message families and pasted the results into retyped English.
    # `MessageRenderer` now renders 20003 / 20007-20013 / 20026 from their
    # own templates.
    #
    # `move_learning_sample` was additionally reading the WRONG addresses.
    # It took `msgCtrlVal[1]` / `msgCtrlVal[3]` (0x804187D4 / 0x804187DC),
    # believing those to be an alternate source for opcodes 0x0D / 0x0E.
    # They are a deferred WRITE buffer: `fightMenuOpenMsg`
    # (fightMenu.s:0x80237264) flushes every non-zero entry back through
    # `msgctrlSetValue` into the ordinary msgvar and zeroes the cache before
    # the window opens, so by the time a message is visible the cache is
    # always empty. The log records that exactly -- 490 of 723 samples for
    # message 20010 rejected with `invalid address 0x00000000`, and the ones
    # that succeeded were races against the flush.

    def level_sample(self):
        """The Pokemon that actually levelled, and its new level.

        Previously read `_ATTACK_MONS` -- the Pokemon that attacked. That is
        only the same Pokemon when exactly one party member is earning
        experience; in a double battle where both level, the two
        announcements name each other's Pokemon, which is the reported
        "switched" symptom.

        `WS_GET_EXP` (fightSeqBasis.s) makes the correct source explicit. Per
        recipient it does, in order:
            fightPokemonToMenuLvupStatus(recipient, &old_menu_lvup_status)
            get_exp_fight_pokemon_ptr = recipient
            ... fightPokemonGrowBasisStatus(recipient, ...)
            fightMsgctrlSetValue(0x0D, nickname of recipient)
            ... opens 20003 / 20006 ...
            get_exp_fight_pokemon_ptr = 0
        so the pointer is non-null for exactly this recipient's messages,
        and the level read here is post-growth, i.e. the new one.

        Raises rather than falling back to `_ATTACK_MONS`: a silent fallback
        to a source known to be wrong would reintroduce the same bug with no
        way to notice."""
        recipient = self.level_up_recipient()
        if not recipient.is_resolved or recipient.level is None:
            raise MemoryError("Level-up recipient is not resolved")
        return LevelSample(recipient, recipient.level)

    def validate_move(self, sample):
        local_name, local_suffix = self.move_data.resolve(sample.move_id)
        if normalize(sample.move_name) != normalize(local_name):
            raise MemoryError("Live and local move names disagree")
        if normalize(sample.suffix) != normalize(local_suffix):
            raise MemoryError("Live and local move suffixes disagree")
        return f"{display_case(sample.actor.nickname)} used {display_case(sample.move_name)}{sample.suffix}"

    # RETIRED 2026-08-06: `validate_stat`, `poison_sentence`,
    # `actor_sentence` and `loss_sentence` each rebuilt one sentence in
    # English from parts. `loss_sentence` is the second literal in this file
    # that carried mojibake ("usable PokAcmon"), which is why none of them
    # survive: the stat message (20243/20244/20246/20247), the poison
    # message (20032/20034), the faint messages (20021/20022) and the loss
    # messages (20024/20025) all render from their own templates now, using
    # opcodes 0x0F / 0x10 / 0x12 / 0x13 / 0x0D / 0x0E / 0x41.
    #
    # `validate_stat`'s cross-check -- confirming each substituted fragment
    # matched exactly one no-opcode message in the local table -- was a
    # sound guard while the sentence was being assembled by hand. It is
    # unnecessary once the game's own template does the assembling.


