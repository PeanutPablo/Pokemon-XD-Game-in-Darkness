"""How many Pokemon the opponent brought, announced once per battle.

A sighted player learns this from the row of Poke Balls at the top of the
battle screen, before choosing a single move. It decides whether to open
with a sweeper or a wall, whether a Shadow Pokemon is worth spending turns
weakening, and whether the battle is nearly over. Nothing in the companion
spoke it, so this module does.

Where the number comes from
---------------------------
The persistent party array that `battle_identity` already documents and
`battle_identity.party_slot_address` already addresses:

    FightFloor -> +0x14 + side*0x6EF0    FightSide
                  +0x64 + trainer*0x3744 FightTrainer
                    +0x97C + slot*0x300  FightPokemon   (6 slots)
                      +0x04              Pokemon

Side 0 is the host (player) side -- the same rule `PartyPosition.
is_player_side` states -- so the opponent's parties are side 1, trainers 0
and 1. Counting occupied cells there needs no new offset and no scanning:
it is the identical arithmetic the ctrl+H summary derives ownership from.

A cell counts as occupied on IDENTITY evidence only: species set, level
1-100, nickname not blank. Both foe trainer arrays are read because a
double battle can field two trainers; in a single battle trainer 1's array
simply holds nothing that passes, and contributes nothing.

**HP is deliberately not part of that test**, unlike
`health.HealthMemorySource.battlers()`, which requires a plausible HP pair
before it will believe a battler at all. That is right for a health tracker
-- every Pokemon it looks at is standing on the field. It would be wrong
here. `ACCESSIBILITY_COVERAGE_MATRIX.md`'s "Opponent's remaining Pokemon
count" entry records an unresolved question from the 2026-07-30
investigation: whether a not-yet-sent-out Pokemon's HP field holds its real
party HP or reads 0 until first use. The one battle examined had every
opposing Pokemon already sent out, so it settled nothing. At battle start
-- the exact moment this announcement fires -- MOST of the opponent's party
has never been sent out, so requiring HP would risk announcing "1 Pokemon"
for a full team of six. Species, level and nickname are copied from the
persistent party at battle setup and do not depend on having been sent out.

**Still needs one live check.** Nothing here establishes what an UNUSED
cell of a short party holds -- whether slots 3 to 5 of a three-Pokemon
trainer are zeroed at setup or retain a previous battle's data. Plausible
stale data would be over-counted. `OpponentPartySource.counts` therefore
logs every cell it accepted, with the species, level and nickname it read,
so a single real battle against a trainer with a known party size settles
it from the log alone.

Why it is not driven off a battle-start message
-----------------------------------------------
There is no single message that starts every battle -- a wild encounter, a
trainer challenge, and a story-scripted fight each open differently, and
several open with no message at all. The field itself is the one signal
common to all of them, so this watches the active battler array instead:
the battle has started when a resolved battler is standing on it.

Two guards keep that honest. The count must repeat across
`identity_stable_samples` consecutive polls before it is spoken, so a
half-initialised array cannot be announced; and the announcement re-arms
only after the field has been EMPTY for `rearm_seconds`, so the brief gap
while a fainted Pokemon is replaced cannot be mistaken for a new battle.
"""
import time

from .battle_identity import party_slot_address
from .memory import MemoryError
from .speech import SpeechEventClass


PLAYER_SIDE = 0
"""`PartyPosition.is_player_side`'s rule, restated for the one place here
that needs the foe side by number."""


class OpponentPartySource:
    """Counts the occupied cells in each opposing trainer's party array."""

    def __init__(self, memory, profile, logger=None):
        self.memory = memory
        self.profile = profile
        self.logger = logger

    def occupant(self, fight_pokemon, label):
        """(species, level, nickname) if this cell holds a real Pokemon, or
        None. See the module docstring for why HP is not consulted."""
        p = self.profile
        pokemon = fight_pokemon + p.fight_pokemon_embedded_offset
        species = self.memory.u16(
            pokemon + p.pokemon_species_offset, f"{label} species")
        if species == 0:
            return None
        level = self.memory.u8(
            pokemon + p.pokemon_level_offset, f"{label} level")
        if not 1 <= level <= 100:
            return None
        nickname = self.memory.gschar(
            fight_pokemon + p.health_nickname_offset,
            p.health_nickname_max_chars, f"{label} nickname", 2)
        if not nickname.strip():
            return None
        return species, level, nickname.strip()

    def counts(self):
        """One count per opposing trainer that has any Pokemon at all, in
        trainer order. Empty when the opposing side holds nothing -- which
        is the normal state outside a battle."""
        p = self.profile
        result = []
        for side in range(p.fight_sides):
            if side == PLAYER_SIDE:
                continue
            for trainer in range(p.fight_trainers_per_side):
                accepted = []
                for slot in range(p.fight_trainer_party_slots):
                    address = party_slot_address(p, side, trainer, slot)
                    label = f"opponent party {side}.{trainer}.{slot}"
                    try:
                        occupant = self.occupant(address, label)
                    except MemoryError:
                        # A cell that cannot be read is not a Pokemon that
                        # can be counted. Skipping it is right: the
                        # alternative -- abandoning the whole count -- would
                        # silence the announcement over one bad cell.
                        continue
                    if occupant is not None:
                        accepted.append((slot,) + occupant)
                if accepted:
                    result.append(len(accepted))
                    self._log_cells(side, trainer, accepted)
        return result

    def _log_cells(self, side, trainer, accepted):
        """Per-cell evidence, so one real battle against a trainer with a
        known party size settles whether unused cells of a short party are
        zeroed. See the module docstring's "Still needs one live check"."""
        if self.logger is None:
            return
        cells = ", ".join(
            f"[{slot}] species={species} level={level} {nickname!r}"
            for slot, species, level, nickname in accepted)
        self.logger.info(
            "OPPONENT PARTY side=%d trainer=%d count=%d cells=%s",
            side, trainer, len(accepted), cells)


def announcement(counts):
    """The sentence for a set of per-trainer opponent party sizes."""
    if not counts:
        return None
    if len(counts) == 1:
        return f"Opponent has {counts[0]} Pokémon."
    listed = ", ".join(str(count) for count in counts[:-1])
    return (
        f"Opponents have {listed} and {counts[-1]} Pokémon, "
        f"{sum(counts)} in total."
    )


class BattleStartAnnouncer:
    """Speaks the opponent's party size once, when a battle begins."""

    def __init__(self, resolver, source, profile, speech, logger,
                 clock=time.monotonic, rearm_seconds=1.5):
        self.resolver = resolver
        self.source = source
        self.profile = profile
        self.speech = speech
        self.logger = logger
        self.clock = clock
        self.rearm_seconds = rearm_seconds
        self.announced = False
        self.pending = None
        self.stable_count = 0
        self.empty_since = None

    def clear(self, reason):
        self.announced = False
        self.pending = None
        self.stable_count = 0
        self.empty_since = None
        self.logger.debug("BATTLE START CLEAR reason=%s", reason)

    def _field_occupied(self):
        return any(
            identity.party is not None
            for identity in self.resolver.active_battlers()
        )

    def poll_once(self):
        try:
            occupied = self._field_occupied()
        except MemoryError as exc:
            self.logger.debug("BATTLE START field read failed: %s", exc)
            return
        if not occupied:
            now = self.clock()
            if self.empty_since is None:
                self.empty_since = now
            elif (self.announced
                    and now - self.empty_since >= self.rearm_seconds):
                self.logger.debug("BATTLE START re-armed: field empty")
                self.announced = False
            self.pending = None
            self.stable_count = 0
            return
        self.empty_since = None
        if self.announced:
            return
        counts = tuple(self.source.counts())
        if not counts:
            self.pending = None
            self.stable_count = 0
            return
        if counts != self.pending:
            self.pending = counts
            self.stable_count = 1
            return
        self.stable_count += 1
        if self.stable_count < self.profile.identity_stable_samples:
            return
        text = announcement(counts)
        self.announced = True
        self.pending = None
        self.stable_count = 0
        if text is None:
            return
        self.speech.emit(SpeechEventClass.BATTLE_EVENT, text, interrupt=False)
        self.logger.info("BATTLE START %s", text)
