"""Speak battle messages, rendered from the game's own text.

What this used to be
--------------------
A per-message-ID dispatch: `VERIFIED_OPCODES` decided which messages were
allowed to speak at all, `state.mode` picked one of seventeen bespoke
samplers, and `compose()` filled in one of ~51 English sentences retyped
from the game into Python. Coverage was bounded by what somebody had
enumerated -- 118 distinct message IDs in the production log were suppressed
as "unverified controls", including every sleep, freeze, immunity and reward
message the project owner reported missing.

What it is now
--------------
One mode. `MessageRenderer.render()` reproduces what the engine itself would
draw, by reading the same msgvar globals the same `msgctrlcode` handlers
read. A message speaks when it renders completely and stays silent when it
does not, and the log names the exact opcode that failed.

The safety contract, restated here because this is where it is enforced:
a message speaks only if it resolves to a real template, every opcode is
recognised, every argument resolves, the text is nonempty, it carries no
double-encoding signature, and the same event has not already been spoken.
A partial sentence -- "Go! ", "It doesn't affect..." -- is never emitted.

Two things the renderer deliberately does not do
------------------------------------------------
1. Fainting still routes through `FaintCoordinator` when one is wired in.
   The rendered sentence names the Pokemon, but the coordinator's job is to
   join the faint to the settled zero-HP identity so the player hears the
   damage and the faint as one utterance instead of two racing ones.
2. Duplicate-species disambiguation is added *after* rendering, and only
   when the field actually contains two battlers answering to the same
   name. The game's own sentence is never replaced -- a short clarifier is
   appended, because the game had no reason to disambiguate for a player
   who can see the screen.
"""
import time
from dataclasses import dataclass, field

from .battle_identity import FOE, PLAYER
from .battle_opcodes import REGISTRY
from .events import EventTracker, StabilityGate
from .memory import MemoryError
from .resolver import (
    LOSS_IDS,
    PLAYER_SEND_OUT_IDS,
    SEND_OUT_IDS,
    TARGET_FAINTED_ID,
)
from .speech import SpeechEventClass
from .tasks import split_packed_id


@dataclass
class MessageState:
    packed: int | None = None
    message: object = None
    gate: StabilityGate = field(default_factory=StabilityGate)
    mode: str | None = None
    rendering: object = None
    spoken: bool = False
    """Whether anything has been said for this open cycle. Only used to keep
    the log honest: once a message has spoken, its substitutions being torn
    down as the box closes must not be reported as an unresolved failure."""
    spoken_subjects: tuple | None = None
    """The battler pointers this message was ABOUT when it last spoke --
    `Rendering.subjects` frozen. `None` until something has been said.

    Exists to tell two things apart that otherwise look identical to an
    armed state: the game printing a genuinely new line into the same task,
    and a battler-pointer global drifting under a box that is still open.
    See `process_allocated`."""

    def reset(self, packed=None, message=None, mode=None):
        self.packed = packed
        self.message = message
        self.mode = mode
        self.rendering = None
        self.spoken = False
        self.spoken_subjects = None
        self.gate.reset()


class BattleNarrator:
    def __init__(
        self,
        connection,
        tasks,
        catalog,
        resolver,
        speaker,
        logger,
        poll_interval=0.05,
        stop_after_loss=False,
        faint_coordinator=None,
        slot_tracker=None,
        labeller=None,
        renderer=None,
        supplemental_catalog=None,
        supplemental_active=None,
    ):
        self.connection = connection
        self.tasks = tasks
        # The OFFLINE fight_common catalog. Still used for two things the
        # runtime tables cannot answer: whether a message ID belongs to this
        # reader at all, and the human-readable template for the log.
        self.catalog = catalog
        self.resolver = resolver
        self.speaker = speaker
        self.logger = logger
        self.poll_interval = poll_interval
        self.stop_after_loss = stop_after_loss
        self.faint_coordinator = faint_coordinator
        self.slot_tracker = slot_tracker
        self.labeller = labeller
        self.renderer = renderer
        self.supplemental_catalog = supplemental_catalog
        self.supplemental_active = supplemental_active
        self.stop_requested = False
        self.tracker = EventTracker(tasks.profile.task_capacity)
        self.states = [MessageState() for _ in range(tasks.profile.task_capacity)]
        # (message_id, unresolved opcodes) already reported. Without this a
        # message that cannot resolve writes a log line every 50ms for as
        # long as it is on screen.
        self._reported = set()

    # -- speech ------------------------------------------------------------

    def speak(self, sentence, snapshot, message_id, event_class=None):
        event_class = event_class or SpeechEventClass.BATTLE_EVENT
        if hasattr(self.speaker, "emit"):
            self.speaker.emit(event_class, sentence,
                              interrupt=event_class == SpeechEventClass.DIALOGUE)
        else:
            self.speaker.speak(sentence, interrupt=False)
        self.logger.info(sentence)
        self.logger.debug(
            "SPOKEN index=%d task=0x%08X state=%d packed=0x%08X "
            "message_id=%d text=%r",
            snapshot.index,
            snapshot.address,
            snapshot.state,
            snapshot.packed_id,
            message_id,
            sentence,
        )

    def suppress(self, snapshot, message_id, message, reason, detail=()):
        key = (message_id, tuple(detail))
        if key in self._reported:
            return
        self._reported.add(key)
        self.logger.warning("A battle message could not be safely resolved.")
        self.logger.debug(
            "SUPPRESSED index=%d task=0x%08X packed=0x%08X message_id=%d "
            "template=%r template_opcodes=%r reason=%s unresolved=%r",
            snapshot.index,
            snapshot.address,
            snapshot.packed_id,
            message_id,
            message.template if message else None,
            list(message.opcodes) if message else None,
            reason,
            list(detail),
        )

    # -- message lifecycle --------------------------------------------------

    def open_message(self, snapshot):
        table, message_id = split_packed_id(snapshot.packed_id)
        message = self.catalog.get(message_id) if table == 0 else None
        if (message is None and table == 0
                and self.supplemental_catalog is not None
                and (self.supplemental_active is None
                     or self.supplemental_active())):
            message = self.supplemental_catalog.get(message_id)
        state = self.states[snapshot.index]
        state.reset(snapshot.packed_id, message)
        self.logger.debug(
            "OPEN index=%d task=0x%08X state=%d packed=0x%08X table=%d "
            "message_id=%d template=%r opcodes=%r",
            snapshot.index,
            snapshot.address,
            snapshot.state,
            snapshot.packed_id,
            table,
            message_id,
            message.template if message else None,
            list(message.opcodes) if message else None,
        )
        if message is None:
            # Not a battle message. Field dialogue, shop notices and title
            # messages share this task array and have their own readers;
            # ownership is partitioned by which table the ID lives in.
            self.suppress(snapshot, message_id, message,
                          "not an active owned message table")
            state.mode = "suppressed"
            return
        if self.renderer is None:
            self.suppress(snapshot, message_id, message, "no renderer wired")
            state.mode = "suppressed"
            return
        unknown = [code for code in message.opcodes if code not in REGISTRY]
        if unknown:
            # An opcode absent from the shipped dispatch table has an
            # unknown argument width, so everything after it in the string
            # may already be garbage. Refuse before rendering.
            self.suppress(snapshot, message_id, message,
                          "opcode not in msgctrlcode", unknown)
            state.mode = "suppressed"
            return
        state.mode = ("render_pocket_menu"
                      if message.context == "pocket_menu" else "render")

    def sample(self, state):
        """The rendered sentence, or None when the message cannot resolve.

        Returning None rather than raising keeps the two outcomes distinct:
        a rendering failure is a *diagnosable* state with a named opcode,
        and gets the once-only SUPPRESSED line; a memory read that blew up
        is a transient and gets the per-poll SAMPLE_REJECTED line."""
        rendering = self.renderer.render(state.message.message_id)
        state.rendering = rendering
        if not rendering.is_speakable:
            return None
        # The gate double-samples this string, so a substitution that is
        # still settling re-arms instead of speaking a half-written name.
        return rendering.text

    def compose(self, state, sample):
        message_id = state.message.message_id
        if (message_id == TARGET_FAINTED_ID
                and self.faint_coordinator is not None):
            # The coordinator joins this to the settled zero-HP identity and
            # speaks both as one utterance. Returning None here is what
            # keeps the faint from being announced twice.
            self.faint_coordinator.note_target_faint()
            return None
        sentence = sample
        clarifier = self._clarifier(state, message_id)
        if clarifier:
            sentence = f"{sentence} {clarifier}"
        return sentence

    # -- duplicate-species disambiguation ------------------------------------

    def _field_identities(self):
        tracker = self.slot_tracker
        return [] if tracker is None else tracker.identities()

    def _clarifier(self, state, message_id):
        """A short clause naming which of two identically-named battlers
        this message is about, or "" when there is no ambiguity.

        Appended rather than substituted: the game's sentence is the
        authoritative text and stays intact. This exists because the game
        never needed to disambiguate for a player who can see which
        Pokemon flashed."""
        labeller = self.labeller
        if labeller is None or state.rendering is None:
            return ""
        peers = self._field_identities()
        if len(peers) < 2:
            return ""
        for peer in peers:
            labeller.note(peer)
        subjects = self._subject_identities(state, message_id)
        labels = []
        for identity in subjects:
            label = labeller.label(identity, peers)
            if label is None:
                self.logger.warning(
                    "SUBJECT AMBIGUOUS message_id=%d nickname=%r peers=%d",
                    message_id, identity.nickname, len(peers))
                continue
            # Only interesting when the label had to escalate past the bare
            # name -- otherwise it repeats what the sentence already said.
            if label.casefold() != labeller.base_name(identity).casefold():
                labels.append(label)
        if not labels:
            return ""
        return " ".join(f"{label[0].upper()}{label[1:]}." for label in labels)

    @staticmethod
    def _subject_anchor_lost(previous, current):
        """True when NOTHING the message was last about is still among the
        battlers it is about now.

        Both empty-or-absent cases answer False: a message with no battler
        substitution at all ("It's super effective!") cannot drift, and a
        message that has not spoken yet has nothing to have drifted from."""
        if not previous or not current:
            return False
        was = dict(previous)
        return not any(was.get(code) == value for code, value in current)

    def _subjects_key(self, state):
        """WHICH POKEMON this rendering is about, as a comparable key.
        Empty for a message with no battler substitution at all.

        Keyed on the canonical `BattlerIdentity.key` -- (party position,
        personality) -- and NOT on the raw `FightOutPokemon*` in
        `Rendering.subjects`. The pointer is the on-field WRAPPER, which is
        not a stable name for a Pokemon: `battle_identity`'s own module
        docstring records that a Baton Pass keeps the wrapper and swaps the
        `FightPokemon*` behind it, so pointer identity answers a different
        question than "is this still about the same Pokemon". Using the
        pointer here made the two lines of a Dragon Dance look like two
        different subjects and swallowed the second one.

        Falls back to the raw pointer for any subject that cannot be
        resolved, so an unresolvable battler still participates in the
        comparison rather than silently collapsing to a key that matches
        everything."""
        rendering = state.rendering
        subjects = {} if rendering is None else rendering.subjects
        resolver = getattr(self.resolver, "identity", None)
        key = []
        for code, fight_out in sorted(subjects.items()):
            resolved = None
            if resolver is not None:
                try:
                    identity = resolver.from_fight_out(fight_out)
                except MemoryError:
                    identity = None
                if identity is not None and identity.is_resolved:
                    resolved = identity.key
            key.append((code, resolved if resolved is not None else fight_out))
        return tuple(key)

    def _subject_identities(self, state, message_id):
        """Canonical identities for the battlers this message named.

        Two sources, both authoritative: opcodes whose global is a
        `FightOutPokemon*` give a pointer the renderer already dereferenced,
        and send-out messages give a name that the identity layer matches
        against the field."""
        identity_resolver = getattr(self.resolver, "identity", None)
        if identity_resolver is None:
            return []
        found = []
        for fight_out in state.rendering.subjects.values():
            identity = identity_resolver.from_fight_out(fight_out)
            if identity.is_resolved:
                found.append(identity)
        if message_id in SEND_OUT_IDS:
            side = PLAYER if message_id in PLAYER_SEND_OUT_IDS else FOE
            try:
                event = self.resolver.send_out_event(
                    side, state.message.opcodes)
            except (MemoryError, AttributeError):
                return found
            found.extend(i for i in event.identities if i is not None)
        return found

    # -- polling -------------------------------------------------------------

    def process_allocated(self, snapshot):
        state = self.states[snapshot.index]
        if state.mode not in {"render", "render_pocket_menu"}:
            return
        try:
            sample = self.sample(state)
            if sample is None:
                if not state.spoken:
                    # Already-spoken messages have their substitutions torn
                    # down as the box closes; reporting that as a failure
                    # would bury the real ones.
                    self.suppress(
                        snapshot, state.message.message_id, state.message,
                        "unresolved substitution",
                        [f"0x{code:02X}: {why}" if code is not None else why
                         for code, why in state.rendering.unresolved])
                return
            stable = state.gate.observe(sample)
            if stable is None:
                return
            subjects = self._subjects_key(state)
            if self._subject_anchor_lost(state.spoken_subjects, subjects):
                # EVERY BATTLER MOVED UNDER A BOX THAT NEVER REOPENED.
                #
                # Live, 2026-08-18 17:12:52-53, one OPEN and one CLOSE with
                # TWO utterances between them:
                #
                #   .503 OPEN  message_id=20451 '[Pokemon 15] is in Rage Mode!'
                #   .566 SPEECH 'Taillow is in Rage Mode!'   <- real
                #   .756 SPEECH 'Numel is in Rage Mode!'     <- invented
                #   .819 CLOSE previous_packed=20451
                #
                # Numel was neither a Shadow Pokemon nor the player's, and
                # never entered Rage Mode. What changed in that 1.2s was
                # `_ATTACK_MONS` advancing to the next attacker in the turn
                # while the box was still up; the armed state re-rendered
                # the same template around the new pointer, and because the
                # gate dedups on the RENDERED STRING the result looked like
                # a new fact.
                #
                # The re-arm itself is still right, and the test is narrow
                # ON PURPOSE. All three shapes below really occur in the
                # production log, and only the last is wrong:
                #
                #   20243 Dragon Dance   actor unchanged, stat text changes
                #                        -> 13 occurrences, all real
                #   20215 Intimidate     actor unchanged, TARGET changes
                #                        (a double battle: it cuts both
                #                        foes' Attack from one box)
                #                        -> real, and it must keep speaking
                #   20451 Rage Mode      the sole battler changes outright
                #                        -> the invented line
                #
                # So the rule is not "a subject changed" -- that would have
                # swallowed the second half of every Intimidate. It is
                # "NOTHING it was about is still what it is about": a real
                # continuation of an event keeps an anchor (the actor is
                # still the actor), while a pointer that drifted into an
                # unrelated context shares nothing with what was spoken.
                #
                # Deliberately the conservative direction. A single-subject
                # message that legitimately re-renders for a second Pokemon
                # in one box would be suppressed, and none has been
                # observed -- but if one exists, losing a line is the
                # better error than inventing one, which is this project's
                # standing rule for a cue the player would act on. Logged
                # at WARNING with both keys so a live session can tell.
                self.logger.warning(
                    "SUBJECT DRIFT suppressed message_id=%d text=%r "
                    "spoken_subjects=%r now=%r",
                    state.message.message_id, stable,
                    state.spoken_subjects, subjects)
                return
            sentence = (stable if state.mode == "render_pocket_menu"
                        else self.compose(state, stable))
            if sentence is not None:
                event_class = (SpeechEventClass.DIALOGUE
                               if state.mode == "render_pocket_menu" else None)
                self.speak(sentence, snapshot, state.message.message_id,
                           event_class)
            state.spoken = True
            state.spoken_subjects = subjects
            if state.mode == "render_pocket_menu":
                # Left latched deliberately: this path belongs to the
                # in-battle bag work and its re-announcement policy is not
                # mine to change.
                state.mode = "done"
            # Otherwise stay ARMED. A move that changes several stats reuses
            # ONE task and ONE message ID for each line -- Dragon Dance sends
            # 20243 for Attack and 20243 again for Speed -- so `EventTracker`
            # emits no event between them and nothing would re-arm a latched
            # state. Live proof, 2026-08-10 19:26: the Attack line spoke and
            # the Speed line produced no OPEN at all. Curse got two of its
            # three only because Speed uses a different ID (20246), which
            # counts as an id_change.
            #
            # Safe to stay armed because `StabilityGate` dedups on the
            # RENDERED STRING, not on the message ID: an unchanged
            # substitution is already in `seen` and returns None, while a
            # changed one is a new fact. This is what the pre-Phase-3 code
            # achieved with `if state.mode != "stat"`, and collapsing every
            # message into one mode dropped it.
            #
            # CORRECTED 2026-08-18: "a changed one is a genuinely new fact"
            # was too strong, and invented a Rage Mode line about a Pokemon
            # that was not even the player's. A re-render in which EVERY
            # battler changed is not a new fact -- see the subject-drift
            # guard above, which is the only thing keeping this re-arm
            # honest.
            if state.message.message_id in LOSS_IDS and self.stop_after_loss:
                self.stop_requested = True
        except MemoryError as exc:
            self.logger.debug(
                "SAMPLE_REJECTED index=%d task=0x%08X message_id=%d reason=%s",
                snapshot.index,
                snapshot.address,
                state.message.message_id,
                exc,
            )

    def poll_once(self):
        if self.slot_tracker is not None:
            # Advance battlefield-occupancy epochs BEFORE interpreting any
            # message this tick, so a message that opens in the same poll as
            # a replacement already sees the new generation rather than the
            # outgoing Pokemon's.
            try:
                for slot in self.slot_tracker.poll():
                    self.logger.debug(
                        "IDENTITY EPOCH slot=%d epoch=%d",
                        slot, self.slot_tracker.epoch_for_slot(slot))
                if self.labeller is not None:
                    for identity in self.slot_tracker.identities():
                        self.labeller.note(identity)
            except MemoryError as exc:
                self.logger.debug("IDENTITY POLL SKIPPED reason=%s", exc)
        snapshots = self.tasks.snapshots()
        by_index = {snapshot.index: snapshot for snapshot in snapshots}
        for event in self.tracker.update(snapshots):
            if event.kind in {"open", "id_change"}:
                self.open_message(event.snapshot)
            elif event.kind == "close":
                self.logger.debug(
                    "CLOSE index=%d task=0x%08X previous_packed=%r",
                    event.snapshot.index,
                    event.snapshot.address,
                    event.previous_packed,
                )
                self.states[event.snapshot.index].reset()
        for index, snapshot in by_index.items():
            if snapshot.state in (1, 2):
                self.process_allocated(snapshot)

    def clear(self, reason="battle narration cleared"):
        """Battle transition cleanup. Without this the suppression-dedup set
        would keep an unresolvable message quiet across a whole session even
        after the state that made it unresolvable had gone."""
        self.logger.debug("NARRATOR CLEAR reason=%s", reason)
        self._reported.clear()
        for state in self.states:
            state.reset()

    def run(self):
        while not self.stop_requested:
            if not self.connection.is_readable():
                raise MemoryError("Dolphin disconnected")
            self.poll_once()
            time.sleep(self.poll_interval)
