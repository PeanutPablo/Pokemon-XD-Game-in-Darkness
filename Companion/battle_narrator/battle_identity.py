"""One authoritative answer to "which Pokemon is this event about?".

Why this exists
---------------
Before this module, every battle reader answered that question its own way,
and three of those ways were guesses:

- `resolver.trainer_party_names(side, n)` returned the first *n* named slots
  of a trainer's PERSISTENT party array and used them as the send-out
  subject. Party order is not send-out order, so a mid-battle replacement
  announced the trainer's first Pokemon, and a Baton Pass made the two
  diverge permanently.
- `resolver.level_sample()` read `_ATTACK_MONS` -- the Pokemon that
  attacked, not the one that gained the experience. In a double battle
  where both party members level, that reads as the names being swapped.
- `health.ownership_for_slot()` mapped active-array index to "Player" /
  "Opponent" through a fixed tuple. The 2026-07-25 handoff recorded the
  opposite interleaving from the one `profile.summary_slot_ownership`
  encodes; a positional tuple cannot be correct in both cases.

The seven concepts below are deliberately separate. They correlate in a
simple single battle and stop correlating the moment anything interesting
happens.

    1. persistent party Pokemon   -> PartyPosition + personality
    2. trainer-side party slot    -> PartyPosition.slot
    3. live battler slot          -> BattlerIdentity.battler_slot
    4. current battle record      -> fight_out / fight_pokemon / pokemon
    5. message-event subject      -> resolved per msgctrl opcode
    6. send-out / replacement     -> BattlefieldSlotTracker epochs
    7. EXP / level-up recipient   -> get_exp_fight_pokemon_ptr

The ownership chain
-------------------
Every pointer below was taken from xd-decomp's own disassembly, not guessed:

    FightFloor  (profile.fight_floor_root)
      +0x14 + side*0x6EF0                      FightSide
        +0x64 + trainer*0x3744                 FightTrainer
          +0x97C + slot*0x300                  FightPokemon   <- PERSISTENT
            +0x04                              Pokemon
              +0x00  u16 species               Pokemon::getPokemonDataId
              +0x28  u32 personality           getRnd__7PokemonCFv
              +0x4E       nickname             pokemon_GetNicknamePtr
    FightOutPokemon                                            <- TRANSIENT
      +0x04                                    FightPokemon*
      +0x84F u8  has-been-switched             fightOutPokemon_GetIrekaetaFlag
      +0x862 s16 incoming party entry          fightOutPokemon_GetIrekaeTargetEntryId

The crucial property: a `FightPokemon` record lives INSIDE its trainer's
party array and never moves. So a `FightPokemon*` alone determines
(side, trainer, party slot) by arithmetic -- no scanning, no name matching,
no assumption about array order. That is the anchor everything else hangs
off, and it survives switching, fainting, Baton Pass, active-array
compaction, and duplicate species.

`FightOutPokemon`, by contrast, is the on-field wrapper. Its stat-stage
array lives at +0x7B0, which is why a Baton Pass can keep the wrapper and
swap only the `FightPokemon*` behind it: the stages transfer because they
were never stored on the Pokemon in the first place.

What this module deliberately does NOT do
-----------------------------------------
It does not render message text. Phase 3 owns that. The only text it reads
is the send-out name globals, because those ARE the identity evidence for a
send-out event -- the game exposes no battler pointer for one.
"""
from dataclasses import dataclass, field, replace

from .memory import MemoryError


RESOLVED = "resolved"
"""Every field needed to name this Pokemon came from an authoritative read."""
PARTIAL = "partial"
"""Enough to say something true but not enough to name the individual --
e.g. a send-out whose text is known but whose live record has not settled."""
AMBIGUOUS = "ambiguous"
"""Two or more candidates fit and nothing distinguishes them. Callers must
stay silent rather than pick one."""

PLAYER = "player"
FOE = "foe"

SEND_OUT_TEXT_OPCODES = {
    0x14: ("my_mons", "_MY_MONS", 0x16),
    0x15: ("my_mons2", "_MY_MONS2", 0x17),
    0x16: ("enemy_mons", "_ENEMY_MONS", 0x14),
    0x17: ("enemy_mons2", "_ENEMY_MONS2", 0x15),
}
"""msgctrl opcodes whose global names a Pokemon entering the field, each
paired with the opcode that mirrors it.

Transcribed from `msgctrlcode` (.data:0x80404710): 0x14 -> msgctrlMyMons,
0x15 -> msgctrlMyMons2, 0x16 -> msgctrlEnemyMons, 0x17 -> msgctrlEnemyMons2,
each an 8-byte accessor returning the global directly.

The mirror exists because the single writer,
`_fightActionFlowKaisiNyuujouPokemonSubAppearMsg`, always stores an entering
Pokemon's nickname into BOTH members of a pair -- 0x14 together with 0x16,
or 0x15 together with 0x17. Reading the partner when the named global is
null is therefore not a guess; it is the same pointer by construction."""

BATTLER_POINTER_OPCODES = {
    0x0F: "attack_mons",
    0x10: "defence_mons",
    0x12: "tsuika_mons",
}
"""msgctrl opcodes whose global holds a FightOutPokemon*, resolved through
`fightOutPokemonGetNicknamePtr` by the handler. 0x11 `_CLIENT_MONS` and
0x1E `_CLIENTNOWORK` have the same shape but no profile field yet, and are
deliberately omitted rather than guessed at an address."""


def speech_case(value):
    """The game stores nicknames upper-case; NVDA reads those as initialisms."""
    if value and value == value.upper() and any(ch.isalpha() for ch in value):
        return value.title()
    return value


def _normalised(value):
    return " ".join((value or "").split()).casefold()


@dataclass(frozen=True)
class PartyPosition:
    """Where a Pokemon permanently lives, independent of the battlefield."""
    side: int
    trainer: int
    slot: int

    @property
    def is_player_side(self):
        # Side 0 is the host side. `fightTargetIsHostSide` is the engine's
        # own name for the same distinction; deriving it from the address
        # range needs no extra read.
        return self.side == 0


@dataclass(frozen=True)
class BattlerIdentity:
    """Canonical identity for one Pokemon in one battle.

    `key` is the stable identity. It is a composite because no single field
    is universally sufficient: the personality value is unique per Pokemon
    but is not readable for a send-out event that has only supplied a name,
    and the party position is always readable but repeats across trainers.
    Together they are unique, and either one alone is enough to reject a
    wrong match.
    """
    resolution: str = AMBIGUOUS
    party: PartyPosition | None = None
    battler_slot: int | None = None
    epoch: int = 0
    fight_out: int | None = None
    fight_pokemon: int | None = None
    pokemon: int | None = None
    personality: int | None = None
    species: int | None = None
    nickname: str = ""
    level: int | None = None
    switch_pending_entry: int | None = None

    @property
    def key(self):
        return (self.party, self.personality)

    @property
    def side(self):
        return None if self.party is None else self.party.side

    @property
    def owner(self):
        if self.party is None:
            return None
        return PLAYER if self.party.is_player_side else FOE

    @property
    def is_resolved(self):
        return self.resolution == RESOLVED


@dataclass(frozen=True)
class SendOutEvent:
    """A send-out's subject as the GAME stated it.

    `names` are the text the game itself put in the msgctrl globals, in
    battlefield-entry order. `identities` are the live battler records they
    were matched to, or None where the match was not unambiguous. A caller
    may always speak `names`; it may only attribute HP or status to an
    entry whose identity resolved.
    """
    side: str
    names: tuple = ()
    identities: tuple = ()
    trainer_class: str = ""
    trainer_name: str = ""

    @property
    def trainer_label(self):
        parts = [p for p in (self.trainer_class, self.trainer_name) if p]
        return " ".join(parts)


def party_slot_address(profile, side, trainer, slot):
    """Address of one persistent FightPokemon record inside a trainer's
    party array. Pure arithmetic over verified offsets; no reads."""
    return (
        profile.fight_floor_root
        + profile.fight_side_offset + side * profile.fight_side_stride
        + profile.fight_trainer_offset + trainer * profile.fight_trainer_stride
        + profile.fight_trainer_party_offset
        + slot * profile.fight_trainer_pokemon_stride
    )


def party_position(profile, fight_pokemon):
    """(side, trainer, slot) for a FightPokemon*, or None if the pointer
    does not land exactly on a party-array cell.

    Exactness matters: an address that falls *inside* a record but not on
    its boundary is not a party Pokemon, and treating it as one would
    invent a position. Solved by arithmetic rather than a 24-cell scan so
    the cost stays constant, and it needs no memory access at all -- which
    is what lets `health.py` derive ownership without a second read."""
    if not isinstance(fight_pokemon, int) or fight_pokemon <= 0:
        return None
    for side in range(profile.fight_sides):
        for trainer in range(profile.fight_trainers_per_side):
            base = party_slot_address(profile, side, trainer, 0)
            delta = fight_pokemon - base
            if delta < 0:
                continue
            slot, remainder = divmod(
                delta, profile.fight_trainer_pokemon_stride)
            if remainder or slot >= profile.fight_trainer_party_slots:
                continue
            return PartyPosition(side, trainer, slot)
    return None


class BattleIdentityResolver:
    """Read-only. Holds no cache -- every pointer here is re-read per poll
    because a stale battler pointer is exactly the failure being removed."""

    def __init__(self, memory, profile):
        self.memory = memory
        self.profile = profile

    # -- geometry ---------------------------------------------------------

    def party_slot_address(self, side, trainer, slot):
        return party_slot_address(self.profile, side, trainer, slot)

    def party_position(self, fight_pokemon):
        return party_position(self.profile, fight_pokemon)

    # -- reads ------------------------------------------------------------

    def _pokemon_fields(self, pokemon):
        p = self.profile
        species = self.memory.u16(
            pokemon + p.pokemon_species_offset, "identity species")
        personality = self.memory.u32(
            pokemon + p.pokemon_personality_offset, "identity personality")
        level = self.memory.u8(
            pokemon + p.pokemon_level_offset, "identity level")
        return species, personality, level

    def from_fight_pokemon(self, fight_pokemon, battler_slot=None,
                           fight_out=None, epoch=0):
        """Canonical identity for a persistent FightPokemon record.

        This is the entry point for anything that names a Pokemon without an
        on-field wrapper -- most importantly the level-up recipient, which
        the game hands over as a `FightPokemon*`."""
        p = self.profile
        if not fight_pokemon:
            return BattlerIdentity(resolution=AMBIGUOUS)
        party = self.party_position(fight_pokemon)
        pokemon = fight_pokemon + p.fight_pokemon_embedded_offset
        try:
            species, personality, level = self._pokemon_fields(pokemon)
            nickname = self.memory.gschar(
                fight_pokemon + p.health_nickname_offset,
                p.health_nickname_max_chars, "identity nickname", 2)
        except MemoryError:
            return BattlerIdentity(
                resolution=AMBIGUOUS, party=party,
                fight_pokemon=fight_pokemon, battler_slot=battler_slot)
        if not nickname.strip() or not 1 <= level <= 100 or not species:
            return BattlerIdentity(
                resolution=AMBIGUOUS, party=party,
                fight_pokemon=fight_pokemon, battler_slot=battler_slot)
        switch_target = None
        if fight_out:
            try:
                raw = self.memory.u16(
                    fight_out + p.fight_out_switch_target_entry_offset,
                    "identity switch target")
                switch_target = raw - 0x10000 if raw & 0x8000 else raw
            except MemoryError:
                switch_target = None
        return BattlerIdentity(
            resolution=RESOLVED if party is not None else PARTIAL,
            party=party,
            battler_slot=battler_slot,
            epoch=epoch,
            fight_out=fight_out,
            fight_pokemon=fight_pokemon,
            pokemon=pokemon,
            personality=personality,
            species=species,
            nickname=nickname,
            level=level,
            switch_pending_entry=switch_target,
        )

    def from_fight_out(self, fight_out, battler_slot=None, epoch=0):
        """Canonical identity for an on-field FightOutPokemon wrapper."""
        p = self.profile
        if not fight_out:
            return BattlerIdentity(resolution=AMBIGUOUS)
        try:
            fight_pokemon = self.memory.u32(
                fight_out + p.fight_out_fight_pokemon_offset,
                "identity FightPokemon")
        except MemoryError:
            return BattlerIdentity(resolution=AMBIGUOUS, fight_out=fight_out)
        if not fight_pokemon:
            # A fainted or withdrawing battler keeps its wrapper with no
            # Pokemon attached. That is a real state, not an error -- but it
            # has no identity, and must not inherit the previous occupant's.
            return BattlerIdentity(
                resolution=AMBIGUOUS, fight_out=fight_out,
                battler_slot=battler_slot, epoch=epoch)
        return self.from_fight_pokemon(
            fight_pokemon, battler_slot=battler_slot,
            fight_out=fight_out, epoch=epoch)

    def from_message_global(self, address, battler_slot=None):
        """Identity behind a msgctrl opcode whose global holds a
        FightOutPokemon* -- 0x0F `_ATTACK_MONS`, 0x10 `_DEFENCE_MONS`,
        0x11 `_CLIENT_MONS`, 0x12 `_TSUIKA_MONS`, 0x1E `_CLIENTNOWORK`.

        Confirmed from `msgctrlAttackMons` (0x801541C4), which in every
        non-link battle reduces to
        `fightOutPokemonGetNicknamePtr(_ATTACK_MONS)`."""
        try:
            pointer = self.memory.u32(address, "identity message global")
        except MemoryError:
            return BattlerIdentity(resolution=AMBIGUOUS)
        return self.from_fight_out(pointer, battler_slot=battler_slot)

    def active_battlers(self, epochs=None):
        """Every occupied battlefield slot, in raw active-array order.

        Unoccupied and detached slots are skipped rather than reported as
        empty identities, matching `health.HealthMemorySource.battlers()`."""
        p = self.profile
        base = p.fight_floor_root + p.active_battler_array_offset
        result = []
        for slot in range(p.active_battler_slots):
            fight_out = self.memory.u32(
                base + slot * 4, f"identity battler {slot}")
            if not fight_out:
                continue
            epoch = 0 if epochs is None else epochs.get(slot, 0)
            identity = self.from_fight_out(
                fight_out, battler_slot=slot, epoch=epoch)
            if identity.fight_pokemon:
                result.append(identity)
        return result

    def text_at(self, address, label, maximum=11):
        """GSchar text behind a msgctrl text-pointer global (0x13/0x14/0x15/
        0x16/0x17/0x22/0x23). Returns "" rather than raising when the global
        is null -- an unset name is a normal transient state, not an error."""
        try:
            pointer = self.memory.u32(address, f"{label} pointer")
        except MemoryError:
            return ""
        if not (self.profile.mem1_start <= pointer < self.profile.mem1_end):
            return ""
        try:
            return self.memory.gschar(pointer, maximum, label, 2).strip()
        except MemoryError:
            return ""

    # -- level-up recipient ------------------------------------------------

    def resolve_level_up_recipient(self, epochs=None):
        """The Pokemon the game itself is crediting, from
        `get_exp_fight_pokemon_ptr` (.sbss:0x804EB964).

        Written by `WS_STATUS_WINDOW` (fightSeqSpAction.s:0x8021A1BC), which
        passes exactly this pointer to `fightPokemonToMenuLvupStatus` before
        opening the level-up stat window. It is a `FightPokemon*`, so it
        resolves to a party position even for a recipient that is not
        currently on the field."""
        try:
            fight_pokemon = self.memory.u32(
                self.profile.exp_recipient_pointer_address,
                "level-up recipient")
        except MemoryError:
            return BattlerIdentity(resolution=AMBIGUOUS)
        if not fight_pokemon:
            return BattlerIdentity(resolution=AMBIGUOUS)
        identity = self.from_fight_pokemon(fight_pokemon)
        if identity.fight_pokemon is None:
            return identity
        # If this Pokemon is also on the field, carry its battlefield slot
        # and epoch so HP-related readers can line the two up. Absence from
        # the field is normal (Exp. Share, a fainted participant) and must
        # not downgrade the identity.
        for active in self.active_battlers(epochs=epochs):
            if active.fight_pokemon == identity.fight_pokemon:
                return replace(
                    identity, battler_slot=active.battler_slot,
                    fight_out=active.fight_out, epoch=active.epoch)
        return identity

    # -- send-outs ---------------------------------------------------------

    def text_for_opcode(self, opcode, _follow_mirror=True):
        """GSchar text behind one send-out msgctrl opcode.

        Falls back to the opcode's mirror (see `SEND_OUT_TEXT_OPCODES`) when
        the named global is null, since the writer always populates both.
        Returns "" when neither is set."""
        entry = SEND_OUT_TEXT_OPCODES.get(opcode)
        if entry is None:
            return ""
        attribute, label, mirror = entry
        text = self.text_at(getattr(self.profile, attribute), label)
        if text or not _follow_mirror:
            return text
        return self.text_for_opcode(mirror, _follow_mirror=False)

    def send_out_names(self, opcodes):
        """The names the game placed in the send-out globals, in the order
        the MESSAGE ITSELF prints them.

        Callers pass the message template's own opcode sequence rather than
        a position index, which sidesteps a real trap. The single writer,
        `_fightActionFlowKaisiNyuujouPokemonSubAppearMsg`, stores each
        entering Pokemon's nickname into BOTH members of a pair (0x14 with
        0x16, or 0x15 with 0x17), and which pair it picks is inverted
        between the player's side and the foe's. So "the first Pokemon is
        always in `_MY_MONS`" is false. But the template already encodes the
        order the game will read them in -- 20313 prints 0x15 then 0x14,
        20305 prints 0x16 then 0x17 -- so replaying the template's own
        opcode order needs no assumption at all.

        Only the send-out opcodes are kept; formatting opcodes in the
        template are ignored."""
        return tuple(
            self.text_for_opcode(opcode)
            for opcode in opcodes
            if opcode in SEND_OUT_TEXT_OPCODES
        )

    def trainer_names(self):
        """(class, personal name) from msgctrl opcodes 0x22/0x23.

        These are the live globals the message itself substitutes, so they
        are correct for whichever trainer the current message is about --
        unlike walking side 1 / trainer 0, which is only right in a single
        battle against one trainer."""
        p = self.profile
        return (
            speech_case(self.text_at(
                p.trainer_type_name, "_TRAINER_TYPE", maximum=32)),
            speech_case(self.text_at(
                p.trainer_personal_name, "_TRAINER_NAME")),
        )

    def send_out_event(self, side, opcodes, epochs=None):
        """A send-out's full subject: the game's own names, plus the live
        battler each one refers to where that can be established without
        guessing.

        Matching is by nickname against the battlers currently on the named
        side. A name that matches exactly one candidate resolves; a name
        that matches two identical-nickname candidates stays None, because
        picking either would be a coin flip. The spoken name is unaffected
        -- it came from the game."""
        names = self.send_out_names(opcodes)
        candidates = [
            identity for identity in self.active_battlers(epochs=epochs)
            if identity.party is not None
            and identity.party.is_player_side == (side == PLAYER)
        ]
        identities = []
        for name in names:
            matches = [
                identity for identity in candidates
                if _normalised(identity.nickname) == _normalised(name)
            ]
            identities.append(matches[0] if len(matches) == 1 else None)
        trainer_class, trainer_name = self.trainer_names()
        return SendOutEvent(
            side=side, names=names, identities=tuple(identities),
            trainer_class=trainer_class, trainer_name=trainer_name)


class BattlefieldSlotTracker:
    """Replacement epochs for the active battler array.

    A "generation" is one continuous occupancy of one active-array index by
    one Pokemon. It ends the moment the occupant's `FightPokemon*` changes
    -- by switch, faint-and-replace, Baton Pass, or the array being rebuilt.

    Two rules make this useful rather than merely descriptive:

    1. The epoch increments the instant a change is SEEN, so a caller can
       reject any HP reading tagged with a stale epoch before it is ever
       spoken. This is what stops a replacement being announced with the
       outgoing Pokemon's health.
    2. The new identity is not published until it has been read identically
       `identity_stable_samples` times. Mid-switch the array can briefly
       expose a wrapper with no Pokemon attached, or a half-written pointer;
       announcing from those produces the "wrong Pokemon" symptom.
    """

    def __init__(self, resolver, profile, logger):
        self.resolver = resolver
        self.profile = profile
        self.logger = logger
        self.epochs = {}
        self.settled = {}
        self._pending = {}

    def clear(self, reason):
        if self.settled:
            self.logger.debug("IDENTITY CLEAR reason=%s", reason)
        self.epochs.clear()
        self.settled.clear()
        self._pending.clear()

    @staticmethod
    def _occupancy(identity):
        return (identity.fight_pokemon, identity.personality)

    def poll(self):
        """Advance the tracker one sample. Returns the list of slots whose
        occupancy changed this sample (i.e. whose epoch just advanced)."""
        observed = {}
        for identity in self.resolver.active_battlers():
            observed[identity.battler_slot] = identity
        changed = []
        for slot in list(self.settled):
            if slot not in observed:
                previous = self.settled.pop(slot)
                self._pending.pop(slot, None)
                self.epochs[slot] = self.epochs.get(slot, 0) + 1
                changed.append(slot)
                self.logger.debug(
                    "IDENTITY VACATED slot=%d epoch=%d previous=%r",
                    slot, self.epochs[slot], previous.nickname)
        for slot, identity in observed.items():
            settled = self.settled.get(slot)
            if settled is not None and self._occupancy(settled) == self._occupancy(identity):
                self._pending.pop(slot, None)
                continue
            pending = self._pending.get(slot)
            if pending is not None and self._occupancy(pending[0]) == self._occupancy(identity):
                count = pending[1] + 1
            else:
                count = 1
                if settled is not None:
                    # Retire the outgoing occupant the moment the change is
                    # SEEN, not when the new one settles. Leaving it
                    # published would let a consumer keep treating a reading
                    # as current for one more sample -- which is precisely
                    # how a replacement ends up announced with the outgoing
                    # Pokemon's health.
                    self.settled.pop(slot, None)
                    self.epochs[slot] = self.epochs.get(slot, 0) + 1
                    changed.append(slot)
                    self.logger.debug(
                        "IDENTITY REPLACING slot=%d epoch=%d outgoing=%r "
                        "incoming=%r",
                        slot, self.epochs[slot], settled.nickname,
                        identity.nickname)
            self._pending[slot] = (identity, count)
            if count < self.profile.identity_stable_samples:
                continue
            self._pending.pop(slot, None)
            if slot not in self.epochs:
                self.epochs[slot] = 1
                changed.append(slot)
            self.settled[slot] = replace(identity, epoch=self.epochs[slot])
            self.logger.debug(
                "IDENTITY SETTLED slot=%d epoch=%d nickname=%r party=%r "
                "personality=%s",
                slot, self.epochs[slot], identity.nickname, identity.party,
                identity.personality)
        return changed

    def identities(self):
        """Every settled battlefield occupant, in active-array order."""
        return [self.settled[slot] for slot in sorted(self.settled)]

    def identity_for_slot(self, slot):
        return self.settled.get(slot)

    def epoch_for_slot(self, slot):
        return self.epochs.get(slot, 0)

    def is_current(self, identity):
        """True when `identity` still describes its slot's live occupant.

        The guard against announcing a stale battler: an identity captured
        before a replacement fails this even though its pointers may still
        dereference successfully."""
        if identity is None or identity.battler_slot is None:
            return False
        settled = self.settled.get(identity.battler_slot)
        if settled is None:
            return False
        return (
            settled.epoch == identity.epoch
            and self._occupancy(settled) == self._occupancy(identity)
        )


class IdentityLabeller:
    """Turns an identity into the shortest phrase that cannot be confused
    with another Pokemon currently on the field.

    On the game's own vocabulary
    ----------------------------
    Phase 1 expected `_msgctrlSideName`'s messages 20327-20332 to supply a
    per-battler position word. Reading them out of the shipped
    `fight_common` table disproved that: they are

        20327/20331 "Foe's party"    20328/20332 "Ally's party"
        20329       "Foe's party is" 20330       "Ally's party is"

    -- three grammatical variants of a WHOLE-SIDE qualifier, used by
    messages like "[0x1F] covered by a veil!". The game has no built-in way
    to distinguish two identical species on the same side, because a sighted
    player simply looks at the screen.

    So the side word ("the foe's") is the game's own and is reused; the
    tie-breaking ordinal is accessibility-owned connective language, which
    is the correct category for it -- there is no game text being copied.

    The ordinal is FIRST-APPEARANCE order within a trainer, assigned once
    when a Pokemon first reaches the field and never revised. Party slot
    would be invisible to the player and active-array index reorders when
    the array compacts after a faint; appearance order does neither.
    """

    def __init__(self, species_names=None):
        # Optional {species_id: name}. Absent, the nickname is used, which
        # is what the game shows anyway unless the player renamed it.
        self.species_names = species_names or {}
        self._appearance = {}
        self._next_ordinal = {}

    def clear(self, reason=None):
        self._appearance.clear()
        self._next_ordinal.clear()

    def note(self, identity):
        """Record a Pokemon reaching the field, if not already seen."""
        if identity is None or identity.party is None:
            return
        if identity.key in self._appearance:
            return
        group = (identity.party.side, identity.party.trainer)
        ordinal = self._next_ordinal.get(group, 0) + 1
        self._next_ordinal[group] = ordinal
        self._appearance[identity.key] = ordinal

    def ordinal(self, identity):
        if identity is None:
            return None
        return self._appearance.get(identity.key)

    @staticmethod
    def _side_word(identity):
        # "the foe's" mirrors the game's own "Foe's party" wording.
        if identity.party is None:
            return ""
        return "your" if identity.party.is_player_side else "the foe's"

    def base_name(self, identity):
        return speech_case(identity.nickname)

    def label(self, identity, peers):
        """A concise phrase naming `identity` unambiguously among `peers`.

        Escalates only as far as needed:
          1. bare name, when no peer shares it;
          2. side-qualified name, when the clash is across sides;
          3. side + appearance ordinal, when the clash is within one side.
        Returns None when the identity itself is unresolved -- callers must
        not fall back to the species name, because that is precisely the
        case where two Pokemon share it."""
        if identity is None or not identity.nickname:
            return None
        name = self.base_name(identity)
        others = [
            peer for peer in peers
            if peer is not None and peer.key != identity.key
        ]
        clashes = [
            peer for peer in others
            if _normalised(peer.nickname) == _normalised(identity.nickname)
        ]
        if not clashes:
            return name
        side = self._side_word(identity)
        same_side = [
            peer for peer in clashes
            if peer.party is not None and identity.party is not None
            and peer.party.is_player_side == identity.party.is_player_side
        ]
        if not same_side:
            return f"{side} {name}".strip()
        ordinal = self.ordinal(identity)
        if ordinal is None:
            return None
        words = {1: "first", 2: "second", 3: "third", 4: "fourth",
                 5: "fifth", 6: "sixth"}
        position = words.get(ordinal, f"number {ordinal}")
        return f"{side} {position} {name}".strip()
