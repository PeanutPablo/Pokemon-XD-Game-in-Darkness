"""Read-only settled health-loss tracking for verified vanilla GXXE01."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import time
from .battle_identity import party_position
from .memory import MemoryError, PointerError, require_range
from .speech import SpeechEventClass

@dataclass(frozen=True)
class BattlerIdentity:
    slot: int
    fight_out: int
    fight_pokemon: int
    pokemon: int

@dataclass(frozen=True)
class BattlerSample:
    identity: BattlerIdentity
    raw_nickname: str
    hp: int
    max_hp: int
    condition: int = 0
    level: int = 0
    exp: int = 0
    stat_stages: tuple = ()
    # Derived from the battler's own FightPokemon address, not from its
    # active-array index. Trailing and defaulted deliberately: inserting a
    # field mid-dataclass renamed every positional argument after it and
    # broke 34 construction sites the last time (2026-08-04).
    owner: str | None = None

@dataclass(frozen=True)
class StatusSample:
    window: int
    allocation: int
    copied_nickname: str
    max_hp: int
    target_hp: int
    old_hp: int
    duration: int
    progress: int

@dataclass(frozen=True)
class HealthEvent:
    identity: BattlerIdentity
    raw_nickname: str
    old_hp: int
    new_hp: int
    max_hp: int
    sentence: str

@dataclass(frozen=True)
class ConditionEvent:
    identity: BattlerIdentity
    raw_nickname: str
    condition: int
    sentence: str

@dataclass(frozen=True)
class ExperienceEvent:
    identity: BattlerIdentity
    raw_nickname: str
    amount: int
    total: int
    sentence: str

@dataclass(frozen=True)
class StatStageEvent:
    identity: BattlerIdentity
    raw_nickname: str
    stat: str
    old_stage: int
    new_stage: int
    sentence: str


@dataclass
class PendingHealth:
    battler: BattlerSample
    old_hp: int
    new_hp: int
    healing: bool
    started: float
    missing_since: float | None = None
    window: int | None = None
    allocation: int | None = None
    last_settled: tuple | None = None
    stable_count: int = 0

def normalized_name(value):
    return " ".join(value.split()).casefold()

def speech_name(raw):
    return raw.title() if raw.isupper() else raw

def round_percent(numerator, denominator):
    raw = Decimal(numerator * 100) / Decimal(denominator)
    return raw, int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def percent_phrase(raw, rounded, remaining=False):
    if raw > 0 and rounded == 0:
        phrase = "less than one percent"
    elif rounded == 0:
        phrase = "zero percent"
    else:
        phrase = f"{rounded} percent"
    return f"{phrase} remaining" if remaining else phrase

def loss_sentence(raw_nickname, old_hp, new_hp, max_hp):
    raw_loss, rounded_loss = round_percent(old_hp - new_hp, max_hp)
    raw_left, rounded_left = round_percent(new_hp, max_hp)
    return (f"{speech_name(raw_nickname)} lost "
            f"{percent_phrase(raw_loss, rounded_loss)}. "
            f"{percent_phrase(raw_left, rounded_left, True)}.")

def ownership_for_slot(profile, slot):
    """Fallback only. Active-array index does not reliably encode side --
    see `profile.summary_slot_ownership`'s own comment. Prefer
    `owner_for_battler`, which derives the answer instead of assuming it."""
    ownership = dict(zip(
        profile.summary_slot_order,
        profile.summary_slot_ownership,
    ))
    return ownership.get(slot, "Battler")

def owner_for_battler(profile, battler):
    """"Player" or "Opponent" for a sampled battler.

    Derived from which trainer's party array the battler's persistent
    FightPokemon record physically sits in -- exact, and it survives the
    active array compacting after a faint. Falls back to the positional
    tuple only when the pointer lands outside every party range, which does
    not happen for a real battler."""
    if battler.owner is not None:
        return battler.owner
    position = party_position(profile, battler.identity.fight_pokemon)
    if position is None:
        return ownership_for_slot(profile, battler.identity.slot)
    return "Player" if position.is_player_side else "Opponent"

def recovery_sentence(profile, battler, old_hp, new_hp):
    owner = owner_for_battler(profile, battler)
    amount = new_hp - old_hp
    raw_amount, rounded_amount = round_percent(amount, battler.max_hp)
    raw_current, rounded_current = round_percent(new_hp, battler.max_hp)
    return (f"{owner} {speech_name(battler.raw_nickname)} recovered "
            f"{amount} HP, {percent_phrase(raw_amount, rounded_amount)}, "
            f"now {new_hp} of {battler.max_hp}, "
            f"{percent_phrase(raw_current, rounded_current)}.")

class HealthMemorySource:
    def __init__(self, memory, profile):
        self.memory, self.profile = memory, profile

    @staticmethod
    def _s16(value):
        return value - 0x10000 if value & 0x8000 else value

    def battlers(self):
        p = self.profile
        base = p.fight_floor_root + p.active_battler_array_offset
        result = []
        for slot in range(p.active_battler_slots):
            fight_out = self.memory.u32(base + slot * 4, f"health battler {slot}")
            if fight_out == 0:
                continue
            require_range(fight_out, p.fight_out_fight_pokemon_offset + 4,
                          f"health FightOutPokemon {slot}", p, 4)
            fight_pokemon = self.memory.u32(
                fight_out + p.fight_out_fight_pokemon_offset,
                f"health FightPokemon {slot}")
            # A fainted or withdrawing battler can temporarily retain its
            # FightOut wrapper with no FightPokemon attached.
            if fight_pokemon == 0:
                continue
            require_range(fight_pokemon, p.fight_pokemon_min_size,
                          f"health FightPokemon {slot}", p, 4)
            pokemon = fight_pokemon + p.fight_pokemon_embedded_offset
            nickname = self.memory.gschar(
                fight_pokemon + p.health_nickname_offset,
                p.health_nickname_max_chars, f"health nickname {slot}", 2)
            current = self.memory.u16(pokemon + p.pokemon_current_hp_offset,
                                      f"health current HP {slot}")
            maximum = self.memory.u16(pokemon + p.pokemon_max_hp_offset,
                                      f"health maximum HP {slot}")
            if not nickname.strip() or not 1 <= maximum <= p.maximum_plausible_hp or current > maximum:
                raise MemoryError(f"health battler {slot}: impossible data {nickname!r} {current}/{maximum}")
            condition = self.memory.u8(pokemon + p.pokemon_condition_offset,
                                       f"health condition {slot}")
            if condition not in p.valid_major_conditions:
                raise MemoryError(f"health battler {slot}: invalid condition {condition}")
            level = self.memory.u8(pokemon + p.pokemon_level_offset,
                                   f"health level {slot}")
            if not 1 <= level <= 100:
                raise MemoryError(f"health battler {slot}: invalid level {level}")
            exp = self.memory.u32(pokemon + p.pokemon_exp_offset, "experience")
            raw_stages = self.memory.bytes(
                fight_out + p.fight_out_stat_stages_offset,
                len(p.stat_stage_names), "battle stat stages", 1)
            if any(value > 12 for value in raw_stages):
                raise MemoryError(f"health battler {slot}: invalid stat stages {tuple(raw_stages)!r}")
            stages = tuple(value - p.stat_stage_neutral_value for value in raw_stages)
            position = party_position(p, fight_pokemon)
            owner = (
                None if position is None
                else "Player" if position.is_player_side else "Opponent"
            )
            result.append(BattlerSample(
                BattlerIdentity(slot, fight_out, fight_pokemon, pokemon),
                nickname, current, maximum, condition, level, exp, stages,
                owner))
        return result

    def windows(self):
        p = self.profile
        pointer = self.memory.u32(p.window_manager + p.window_list_offset,
                                  "health window-list head")
        seen, result = set(), []
        for _ in range(p.window_max_nodes):
            if pointer == 0:
                return result
            if pointer in seen:
                raise MemoryError("health window list contains a cycle")
            require_range(pointer, p.window_node_size, "health window", p, 4)
            seen.add(pointer)
            allocation = self.memory.u32(pointer + p.window_alloc_offset,
                                         "health status allocation")
            if allocation:
                try:
                    require_range(allocation, p.status_allocation_size,
                                  "health status allocation", p, 4)
                    nickname = self.memory.gschar(
                        allocation + p.status_copied_nickname_offset,
                        p.health_nickname_max_chars, "health copied nickname")
                    maximum = self._s16(self.memory.u16(
                        allocation + p.status_max_hp_offset, "health status max"))
                    target = self._s16(self.memory.u16(
                        allocation + p.status_target_hp_offset, "health status target"))
                    work = pointer + p.status_animation_work_offset
                    old = self._s16(self.memory.u16(
                        work + p.status_animation_old_hp_offset, "health animation old"))
                    duration = self._s16(self.memory.u16(
                        work + p.status_animation_duration_offset, "health animation duration"))
                    progress = self._s16(self.memory.u16(
                        work + p.status_animation_progress_offset, "health animation progress"))
                    if (nickname.strip() and 1 <= maximum <= p.maximum_plausible_hp
                            and 0 <= target <= maximum and 0 <= old <= maximum
                            and duration >= 0 and progress >= 0):
                        result.append(StatusSample(pointer, allocation, nickname,
                                                   maximum, target, old, duration, progress))
                except (MemoryError, PointerError):
                    pass
            pointer = self.memory.u32(pointer + p.window_next_offset,
                                      "health next window")
        raise MemoryError("health window list exceeds verified bound")

class HealthTracker:
    def __init__(self, source, profile, logger, clock=time.monotonic,
                 narrate_stat_stages=False):
        # `narrate_stat_stages` defaults OFF as of 2026-08-06. This tracker
        # announced every change to the persistent stat-stage array as a
        # fallback for the battle stat messages (20243/20244/20246/20247),
        # which used to fail: the target-side pair reads opcode 0x10, and
        # the old code sampled the wrong global, producing 1,790 logged
        # rejections for 20247 alone.
        #
        # Now that those messages render from their own templates, the
        # fallback is a duplicate, and the production log shows exactly what
        # that sounds like:
        #
        #   00:05:50.837 "Blastoise's Accuracy fell!"   <- this tracker
        #   00:05:50.901 "Blastoise's accuracy fell!"   <- message 20244
        #
        # The message is authoritative (it is the game's own wording and
        # capitalisation), so it wins. The stage array is still SAMPLED --
        # it is cheap, it is part of BattlerSample, and re-enabling this is
        # a constructor argument -- because a stage change with no message
        # would otherwise be invisible, and whether any such change exists
        # has not been established.
        self.narrate_stat_stages = narrate_stat_stages
        self.source, self.profile, self.logger, self.clock = source, profile, logger, clock
        self.baselines, self.slot_identities, self.pending = {}, {}, {}
        self.conditions, self.pending_conditions = {}, {}
        self.experience, self.stat_stages = {}, {}
        self.latest_battlers = []

    def clear(self, reason):
        self.logger.debug("HEALTH CLEAR reason=%s", reason)
        self.baselines.clear(); self.slot_identities.clear(); self.pending.clear()
        self.conditions.clear(); self.pending_conditions.clear()
        self.experience.clear(); self.stat_stages.clear()
        self.latest_battlers = []

    def _matches(self, battler, pending, windows):
        return [w for w in windows
                if normalized_name(w.copied_nickname) == normalized_name(battler.raw_nickname)
                and w.max_hp == battler.max_hp and w.target_hp == battler.hp
                and w.old_hp == pending.old_hp]

    def _suppress(self, identity, battler, reason):
        self.logger.warning("HEALTH SUPPRESSED identity=%s HP=%d/%d reason=%s",
                            identity, battler.hp, battler.max_hp, reason)
        self.pending.pop(identity, None)
        self.baselines[identity] = battler.hp

    def poll(self):
        now = self.clock()
        sampled, windows = self.source.battlers(), self.source.windows()
        battlers = []
        for battler in sampled:
            if (
                battler.max_hp < 1
                or battler.max_hp > self.profile.maximum_plausible_hp
                or battler.hp < 0
                or battler.hp > battler.max_hp
            ):
                self.logger.warning(
                    "HEALTH INVALID identity=%s HP=%d/%d; silent",
                    battler.identity, battler.hp, battler.max_hp)
                self.baselines.pop(battler.identity, None)
                self.pending.pop(battler.identity, None)
                continue
            battlers.append(battler)
        self.latest_battlers = list(battlers)
        current = {b.identity: b for b in battlers}
        slots = {b.identity.slot: b.identity for b in battlers}
        for slot, previous in list(self.slot_identities.items()):
            if slots.get(slot) != previous:
                self.baselines.pop(previous, None); self.pending.pop(previous, None)
                self.conditions.pop(previous, None)
                self.pending_conditions.pop(previous, None)
                self.experience.pop(previous, None); self.stat_stages.pop(previous, None)
                self.logger.debug("HEALTH REPLACEMENT slot=%d old=%s new=%s",
                                  slot, previous, slots.get(slot))
        self.slot_identities = slots
        for identity in list(self.baselines):
            if identity not in current:
                self.baselines.pop(identity, None); self.pending.pop(identity, None)
                self.conditions.pop(identity, None)
                self.pending_conditions.pop(identity, None)
                self.experience.pop(identity, None); self.stat_stages.pop(identity, None)
        events = []
        for battler in battlers:
            identity = battler.identity
            player_start = (
                self.profile.fight_floor_root
                + self.profile.fight_trainer_first_pokemon_offset
            )
            player_end = (
                player_start
                + self.profile.fight_trainer_pokemon_stride * 6
            )
            if player_start <= identity.fight_pokemon < player_end:
                previous_exp = self.experience.get(identity)
                # Message 20003 now reads the game's authoritative name and
                # quantity substitutions before A is pressed. Total EXP changes
                # only afterward, so emitting a delta here would repeat it late.
                self.experience[identity] = battler.exp
            else:
                self.experience.pop(identity, None)
            # Target-directed stat messages can appear while the transient
            # target pointer is null. The persistent stat-stage array is the
            # authoritative fallback for every actual transition.
            if battler.stat_stages:
                previous_stages = self.stat_stages.get(identity)
                if previous_stages is not None and self.narrate_stat_stages:
                    for index, (old_stage, new_stage) in enumerate(
                        zip(previous_stages, battler.stat_stages)
                    ):
                        if old_stage == new_stage:
                            continue
                        delta = new_stage - old_stage
                        stat = self.profile.stat_stage_names[index]
                        if delta >= 2:
                            change = "rose sharply"
                        elif delta > 0:
                            change = "rose"
                        elif delta <= -2:
                            change = "harshly fell"
                        else:
                            change = "fell"
                        sentence = (
                            f"{speech_name(battler.raw_nickname)}'s "
                            f"{stat.title()} {change}!"
                        )
                        events.append(StatStageEvent(
                            identity, battler.raw_nickname, stat,
                            old_stage, new_stage, sentence,
                        ))
                self.stat_stages[identity] = battler.stat_stages
            if identity not in self.conditions:
                self.conditions[identity] = battler.condition
            elif battler.condition == self.conditions[identity]:
                self.pending_conditions.pop(identity, None)
            else:
                pending_condition = self.pending_conditions.get(identity)
                stable_count = (
                    pending_condition[1] + 1
                    if pending_condition and pending_condition[0] == battler.condition
                    else 1
                )
                self.pending_conditions[identity] = (battler.condition, stable_count)
                if stable_count >= self.profile.health_stable_samples:
                    self.conditions[identity] = battler.condition
                    self.pending_conditions.pop(identity, None)
                    condition_name = {
                        5: "paralyzed",
                        6: "burned",
                        7: "frozen",
                    }.get(battler.condition)
                    if condition_name:
                        sentence = (
                            f"{speech_name(battler.raw_nickname)} "
                            f"was {condition_name}!"
                        )
                        events.append(ConditionEvent(
                            identity, battler.raw_nickname,
                            battler.condition, sentence))
                        self.logger.info(
                            "CONDITION SETTLED identity=%s nickname=%r "
                            "condition=%d sentence=%r",
                            identity, battler.raw_nickname,
                            battler.condition, sentence)
            if identity not in self.baselines:
                self.baselines[identity] = battler.hp
                self.logger.debug("HEALTH BASELINE identity=%s nickname=%r HP=%d/%d",
                                  identity, battler.raw_nickname, battler.hp, battler.max_hp)
            elif identity not in self.pending and battler.hp != self.baselines[identity]:
                old = self.baselines[identity]
                self.pending[identity] = PendingHealth(
                    battler, old, battler.hp, battler.hp > old, now)
                self.logger.debug("HEALTH START identity=%s old=%d new=%d max=%d healing=%s",
                                  identity, old, battler.hp, battler.max_hp, battler.hp > old)
        for identity, pending in list(self.pending.items()):
            battler = current.get(identity)
            if battler is None:
                self.pending.pop(identity, None); continue
            if battler.max_hp != pending.battler.max_hp:
                self._suppress(identity, battler, "maximum HP changed"); continue
            if battler.hp != pending.new_hp:
                pending.new_hp = battler.hp
                pending.healing = battler.hp > pending.old_hp
                pending.last_settled = None; pending.stable_count = 0
                self.logger.debug("HEALTH GROUP identity=%s old=%d new=%d",
                                  identity, pending.old_hp, pending.new_hp)
            matches = self._matches(battler, pending, windows)
            if len(matches) > 1:
                self._suppress(identity, battler, "ambiguous status mapping"); continue
            if not matches:
                if pending.missing_since is None:
                    pending.missing_since = now
                elif now - pending.missing_since >= self.profile.health_remap_timeout_seconds:
                    self._suppress(identity, battler, "remap timeout")
                continue
            window = matches[0]
            if pending.window != window.window or pending.allocation != window.allocation:
                self.logger.debug("HEALTH REMAP identity=%s old_window=%s new_window=0x%08X old_allocation=%s new_allocation=0x%08X nickname=%r max=%d target=%d old=%d",
                    identity, "none" if pending.window is None else f"0x{pending.window:08X}",
                    window.window, "none" if pending.allocation is None else f"0x{pending.allocation:08X}",
                    window.allocation, window.copied_nickname, window.max_hp, window.target_hp, window.old_hp)
                pending.window, pending.allocation = window.window, window.allocation
            pending.missing_since = None
            settled = window.duration == 0 and window.target_hp == battler.hp == pending.new_hp
            snapshot = (identity, battler.hp, battler.max_hp, window.target_hp, window.duration)
            if settled and snapshot == pending.last_settled:
                pending.stable_count += 1
            elif settled:
                pending.stable_count = 1
            else:
                pending.stable_count = 0
            pending.last_settled = snapshot
            self.logger.debug("HEALTH ANIMATION identity=%s old=%d target=%d duration=%d progress=%d logical=%d stable=%d",
                              identity, window.old_hp, window.target_hp, window.duration,
                              window.progress, battler.hp, pending.stable_count)
            if pending.stable_count < self.profile.health_stable_samples:
                continue
            self.baselines[identity] = pending.new_hp
            self.pending.pop(identity, None)
            if pending.healing:
                sentence = recovery_sentence(
                    self.profile, battler, pending.old_hp, pending.new_hp)
            else:
                sentence = loss_sentence(
                    battler.raw_nickname, pending.old_hp,
                    pending.new_hp, battler.max_hp)
            events.append(HealthEvent(identity, battler.raw_nickname, pending.old_hp,
                                      pending.new_hp, battler.max_hp, sentence))
            self.logger.info(
                "HEALTH SETTLED identity=%s nickname=%r old=%d new=%d "
                "max=%d healing=%s sentence=%r",
                identity, battler.raw_nickname, pending.old_hp,
                pending.new_hp, battler.max_hp, pending.healing, sentence)
        return events

class FaintCoordinator:
    """Join transient target-faint dialogue to the settled zero-HP identity."""
    def __init__(self, speech, logger, clock=time.monotonic, grace_seconds=1.0):
        self.speech, self.logger, self.clock = speech, logger, clock
        self.grace_seconds = grace_seconds
        self.pending_messages = []
        self.pending_zeroes = []
        self.resolved_identities = set()

    def clear(self, reason):
        self.logger.debug("FAINT CLEAR reason=%s", reason)
        self.pending_messages = []
        self.pending_zeroes.clear()
        self.resolved_identities.clear()

    def note_target_faint(self):
        self.pending_messages.append(self.clock())
        self.logger.debug("FAINT MESSAGE pending_messages=%d", len(self.pending_messages))
        self._resolve()

    def _emit(self, sentence):
        self.speech.emit(SpeechEventClass.BATTLE_EVENT, sentence, interrupt=False)

    def _resolve(self):
        # A unique settled zero is evidence; ordering simultaneous zeroes would be a guess.
        if self.pending_messages and len(self.pending_zeroes) == 1:
            _seen, event = self.pending_zeroes.pop()
            self.pending_messages.pop(0)
            sentence = (
                f"{event.sentence} {speech_name(event.raw_nickname)} fainted!"
            )
            self.logger.info("FAINT RESOLVED identity=%s nickname=%r sentence=%r",
                             event.identity, event.raw_nickname, sentence)
            self._emit(sentence)

    def submit_current_battlers(self, battlers, baselines=None):
        if not self.pending_messages or self.pending_zeroes:
            return
        zeroes = [b for b in battlers if b.hp == 0]
        if len(zeroes) != 1:
            if len(zeroes) > 1:
                self.logger.warning(
                    "FAINT AMBIGUOUS current_zeroes=%d; silent", len(zeroes))
            return
        battler = zeroes[0]
        self.pending_messages.pop(0)
        self.resolved_identities.add(battler.identity)
        # This path races ahead of HealthTracker's own multi-sample settle
        # (it fires as soon as a unique zero-HP battler appears, rather than
        # waiting for the HP-bar animation to finish), so there is usually no
        # settled HealthEvent yet to report a percentage from. The tracker's
        # baseline for this identity is still the pre-hit HP at this point --
        # it's only advanced once the tracker itself settles -- so it can be
        # used here to compute the same loss percentage a settled event would
        # have reported, without waiting for one.
        old_hp = baselines.get(battler.identity) if baselines else None
        if old_hp is not None and old_hp > battler.hp:
            sentence = (
                f"{loss_sentence(battler.raw_nickname, old_hp, battler.hp, battler.max_hp)} "
                f"{speech_name(battler.raw_nickname)} fainted!"
            )
        else:
            sentence = f"{speech_name(battler.raw_nickname)} fainted!"
        self.logger.info(
            "FAINT RESOLVED CURRENT identity=%s nickname=%r sentence=%r",
            battler.identity, battler.raw_nickname, sentence)
        self._emit(sentence)
    def submit_health_events(self, events):
        now = self.clock()
        for event in events:
            if (isinstance(event, HealthEvent)
                    and event.identity in self.resolved_identities):
                self.resolved_identities.discard(event.identity)
                self.logger.debug(
                    "FAINT HEALTH DEDUP identity=%s", event.identity)
            elif isinstance(event, HealthEvent) and event.new_hp == 0:
                self.pending_zeroes.append((now, event))
            else:
                self._emit(event.sentence)
        self._resolve()
        self.flush()

    def flush(self):
        now = self.clock()
        self.pending_messages = [
            seen for seen in self.pending_messages
            if now - seen < self.grace_seconds
        ]
        retained = []
        for seen, event in self.pending_zeroes:
            if now - seen >= self.grace_seconds:
                self.logger.debug("FAINT UNMATCHED identity=%s; using health narration",
                                  event.identity)
                self._emit(
                    f"{event.sentence} {speech_name(event.raw_nickname)} fainted!"
                )
            else:
                retained.append((seen, event))
        self.pending_zeroes = retained
class ProductionHealthReader:
    def __init__(self, tracker, speech, logger, faint_coordinator=None):
        self.tracker, self.speech, self.logger = tracker, speech, logger
        self.faint_coordinator = faint_coordinator
    def poll_once(self):
        events = self.tracker.poll()
        if self.faint_coordinator is not None:
            self.faint_coordinator.submit_current_battlers(
                self.tracker.latest_battlers, self.tracker.baselines)
            self.faint_coordinator.submit_health_events(events)
            return
        for event in events:
            self.speech.emit(SpeechEventClass.BATTLE_EVENT, event.sentence,
                             interrupt=False)
    def clear(self, reason):
        self.tracker.clear(reason)
        if self.faint_coordinator is not None:
            self.faint_coordinator.clear(reason)

