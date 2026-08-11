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

    def reset(self, packed=None, message=None, mode=None):
        self.packed = packed
        self.message = message
        self.mode = mode
        self.rendering = None
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
        self.stop_requested = False
        self.tracker = EventTracker(tasks.profile.task_capacity)
        self.states = [MessageState() for _ in range(tasks.profile.task_capacity)]
        # (message_id, unresolved opcodes) already reported. Without this a
        # message that cannot resolve writes a log line every 50ms for as
        # long as it is on screen.
        self._reported = set()

    # -- speech ------------------------------------------------------------

    def speak(self, sentence, snapshot, message_id):
        if hasattr(self.speaker, "emit"):
            self.speaker.emit(SpeechEventClass.BATTLE_EVENT, sentence)
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
            self.suppress(snapshot, message_id, message, "not fight_common")
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
        state.mode = "render"

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
        if state.mode != "render":
            return
        try:
            sample = self.sample(state)
            if sample is None:
                self.suppress(
                    snapshot, state.message.message_id, state.message,
                    "unresolved substitution",
                    [f"0x{code:02X}: {why}" if code is not None else why
                     for code, why in state.rendering.unresolved])
                return
            stable = state.gate.observe(sample)
            if stable is None:
                return
            sentence = self.compose(state, stable)
            if sentence is not None:
                self.speak(sentence, snapshot, state.message.message_id)
            state.mode = "done"
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
