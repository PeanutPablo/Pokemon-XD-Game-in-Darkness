"""What a battle target actually IS, spoken while you are choosing it.

Both target screens used to say a bare name -- "Targets. D-pad up, Latios."
and "Target: Opponent Wurmple." A sighted player is looking at that
Pokemon's HP bar and status icon at the moment they aim, so the name alone
is all they need; without the bar, the name alone is not enough to choose
between two foes, and the information arrives only after the attack lands.
This module supplies the rest of it.

Two sources, each used for what it can prove
--------------------------------------------
**HP comes from the status panel the game is displaying.** Both readers
already dereference that window's allocation to read the target's
nickname; max HP and current HP sit in the same 0x1C-byte record at +0x18
and +0x1A, which `health.HealthMemorySource.windows()` already reads and
treats as signed 16-bit. Taking HP from there needs no matching at all --
it is, by construction, the HP of the panel the cursor is on.

**Level and major status come from the live battler.** The status
allocation does not carry them, so they are matched by nickname against
the active battler array. That match is the one place a wrong answer is
possible -- two battlers can share a nickname -- so a duplicated name
yields NOTHING rather than a coin flip, exactly as
`BattleIdentityResolver.send_out_event` does. The HP half is unaffected,
because it never depended on the name.

Every part is independently optional. A field that cannot be read or
validated is simply left out of the sentence; nothing here substitutes a
default, because "level 0" or "0 of 0 HP" spoken confidently is worse
than a shorter sentence.
"""
from dataclasses import dataclass

from .health import STATUS_NAMES, round_percent
from .memory import MemoryError, require_range


@dataclass(frozen=True)
class TargetFacts:
    """The parts of a target that only the live battler record knows."""
    level: int | None = None
    condition: int | None = None


def _normalised(value):
    return " ".join((value or "").split()).casefold()


def _s16(value):
    return value - 0x10000 if value & 0x8000 else value


class TargetFactsSource:
    """Level and major status for every battler on the field, by nickname.

    Deliberately per-slot tolerant: one unreadable or half-initialised
    battler drops that battler and nothing else. `health.
    HealthMemorySource.battlers()` is all-or-nothing by design -- it raises
    on any implausible slot, because a health TRACKER that silently skipped
    a battler would miss damage -- and that policy is wrong here, where the
    worst case is one target described a little less fully."""

    def __init__(self, memory, profile):
        self.memory = memory
        self.profile = profile

    def _battler(self, slot):
        p = self.profile
        base = p.fight_floor_root + p.active_battler_array_offset
        fight_out = self.memory.u32(base + slot * 4, f"target battler {slot}")
        if not fight_out:
            return None, None
        require_range(fight_out, p.fight_out_fight_pokemon_offset + 4,
                      f"target FightOutPokemon {slot}", p, 4)
        fight_pokemon = self.memory.u32(
            fight_out + p.fight_out_fight_pokemon_offset,
            f"target FightPokemon {slot}")
        if not fight_pokemon:
            return None, None
        require_range(fight_pokemon, p.fight_pokemon_min_size,
                      f"target FightPokemon {slot}", p, 4)
        nickname = self.memory.gschar(
            fight_pokemon + p.health_nickname_offset,
            p.health_nickname_max_chars, f"target nickname {slot}", 2)
        pokemon = fight_pokemon + p.fight_pokemon_embedded_offset
        level = self.memory.u8(
            pokemon + p.pokemon_level_offset, f"target level {slot}")
        condition = self.memory.u8(
            pokemon + p.pokemon_condition_offset, f"target condition {slot}")
        return nickname, TargetFacts(
            level=level if 1 <= level <= 100 else None,
            condition=(condition if condition in p.valid_major_conditions
                       else None),
        )

    def facts(self):
        found = {}
        for slot in range(self.profile.active_battler_slots):
            try:
                nickname, facts = self._battler(slot)
            except MemoryError:
                continue
            key = _normalised(nickname)
            if not key or facts is None:
                continue
            # A repeated nickname makes both entries useless: nothing here
            # can say which one the cursor is on, and naming the wrong
            # one's HP is the failure this whole module exists to avoid.
            found[key] = None if key in found else facts
        return {key: value for key, value in found.items() if value is not None}


def status_panel_hp(memory, profile, allocation, label):
    """(current HP, max HP) from a battle status window's allocation, or
    (None, None) when the record does not hold a plausible pair.

    Same offsets and same signed handling as `health.HealthMemorySource.
    windows()`. Validation is the same shape too -- max HP in range and
    current HP not above it -- so a window that is allocated but not yet
    populated reads as "no HP known" rather than as a Pokemon at 0."""
    try:
        maximum = _s16(memory.u16(
            allocation + profile.status_max_hp_offset, f"{label} max HP"))
        current = _s16(memory.u16(
            allocation + profile.status_target_hp_offset,
            f"{label} current HP"))
    except MemoryError:
        return None, None
    if not 1 <= maximum <= profile.maximum_plausible_hp:
        return None, None
    if not 0 <= current <= maximum:
        return None, None
    return current, maximum


def target_detail(facts=None, hp=None, max_hp=None):
    """The clause that follows a target's name, or "" when nothing about
    it could be established. Never starts or ends with punctuation -- the
    caller owns the sentence."""
    pieces = []
    if facts is not None and facts.level is not None:
        pieces.append(f"level {facts.level}")
    if hp is not None and max_hp:
        _, percentage = round_percent(hp, max_hp)
        pieces.append(f"{hp} of {max_hp} HP")
        pieces.append("zero percent" if percentage == 0
                      else f"{percentage} percent")
        if hp == 0:
            pieces.append("fainted")
    if facts is not None:
        status = STATUS_NAMES.get(facts.condition)
        if status is not None:
            pieces.append(status)
    return ", ".join(pieces)
