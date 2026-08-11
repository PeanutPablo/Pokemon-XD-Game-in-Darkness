"""Development-only diagnostic correlating what entity navigation SAYS
with what the game's own `peopleTalkCheck` would actually do.

Why this exists before the fix, not after
-----------------------------------------
Phase 1 established four independent reasons an NPC can be announced as
reachable when it is not (wrong body reference, wrong distance formula,
four unimplemented gates, wrong people-info lookup). It could not
establish their RELATIVE weight, because nothing in 367 MB of logs records
whether an A press actually landed. This closes that gap: it logs the full
predicate state for the selected NPC, and lets the project owner mark the
exact moment they press A so the prediction can be scored against the real
outcome.

Never sends input. Never presses A. The marker is a separate hotkey the
player triggers themselves, and all this module does is record what
happened around it.

Off by default. `--interaction-diagnostics` turns it on; with it off,
nothing here is constructed and nothing is logged.
"""
from dataclasses import dataclass
import math
import time

from .memory import MemoryError as GameMemoryError
from .talk_predicate import TalkInputs, evaluate


SAMPLE_INTERVAL = 0.5
"""Seconds between passive samples. Slow enough that a short focused
capture stays readable by hand, fast enough to catch a player walking into
and out of range. This is a diagnostic, not a telemetry firehose."""

DIALOGUE_WINDOW = 3.0
"""How long after a marker to keep watching for dialogue to open before
recording the press as having produced nothing."""


def _fmt(value, digits=2):
    if value is None:
        return "?"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _fmt_position(position):
    if position is None:
        return "?"
    return f"({position.x:.2f},{position.y:.2f},{position.z:.2f})"


@dataclass
class PendingMark:
    at: float
    identity: object
    label: object
    predicted: bool
    reason: object


class InteractionDiagnostics:
    """Samples the selected NPC's full talk-predicate state, and scores
    manual A presses against the prediction.

    `selection()` is injected rather than reading the navigator's private
    state, so this stays a pure observer of a published interface."""

    def __init__(self, memory, profile, runtime, neck_resolver, pose_source,
                 selection, hotkey, logger, dialogue_active=None,
                 wall_test=None, clock=time.monotonic,
                 sample_interval=SAMPLE_INTERVAL):
        self.memory, self.profile = memory, profile
        self.runtime = runtime
        self.neck_resolver = neck_resolver
        self.pose_source = pose_source
        self.selection = selection
        self.hotkey = hotkey
        self.logger = logger
        self.dialogue_active = dialogue_active or (lambda: False)
        self.wall_test = wall_test
        self.clock = clock
        self.sample_interval = sample_interval
        self.next_sample = 0.0
        self.pending = None
        self.samples = 0
        self.marks = 0
        self._dialogue_was_active = False

    def clear(self, reason):
        self.pending = None
        self.next_sample = 0.0
        self.logger.debug("INTERACTION DIAG cleared: %s", reason)

    # ---- the sample ---------------------------------------------------

    def _describe(self, character, hero_actor, hero_info, pose, room_code):
        actor, static, info = character.actor, character.static, character.info
        neck = self.neck_resolver.neck_position(
            actor.model, info.neck_index, actor.position)
        hero_position = pose.position
        hero_col = hero_info.col_ball_size if hero_info else 0.0
        hero_facing = hero_actor.facing if hero_actor else pose.facing
        wall_blocked = None
        if self.wall_test is not None and neck is not None:
            try:
                wall_blocked = self.wall_test(hero_position, neck, hero_col)
            except Exception:
                wall_blocked = None
        verdict = evaluate(TalkInputs(
            occupied=True,
            displayed=actor.displayed,
            talk_flag_blocked=actor.talk_flag_blocked,
            talk_start_type=static.talk_start_type,
            has_people_info=True,
            hero_position=hero_position,
            neck_position=neck,
            hero_facing=hero_facing,
            hero_col_ball_size=hero_col,
            npc_col_ball_size=info.col_ball_size,
            talk_distance=actor.talk_distance,
            wall_through=static.talk_wall_through,
            wall_blocked=wall_blocked,
        ))
        horizontal = None
        if neck is not None:
            horizontal = math.hypot(
                neck.x - hero_position.x, neck.z - hero_position.z)
        neck_offset = None
        if neck is not None and actor.position is not None:
            neck_offset = math.hypot(
                neck.x - actor.position.x, neck.z - actor.position.z)
        drift = None
        if actor.position is not None:
            drift = math.hypot(
                actor.position.x - static.position.x,
                actor.position.z - static.position.z)
        return verdict, {
            "room_code": room_code,
            "identity": character.identity,
            "generation": character.generation,
            "work": f"0x{actor.address:08X}",
            "slot": actor.slot,
            "group_id": actor.group_id,
            "res_id": actor.res_id,
            "people_info_id": actor.people_info_id,
            "name_id": static.name_id,
            "talk_script_id": static.talk_script_id,
            "model_pos": actor.position,
            "static_pos": static.position,
            "spawn_drift": drift,
            "neck_pos": neck,
            "neck_offset": neck_offset,
            "hero_pos": hero_position,
            "hero_facing": hero_facing,
            "camera_yaw": pose.yaw,
            "distance_3d": verdict.distance,
            "distance_horizontal": horizontal,
            "hero_col_ball": hero_col,
            "npc_col_ball": info.col_ball_size,
            "live_talk_distance": actor.talk_distance,
            "static_talk_distance": info.static_talk_distance,
            "threshold": verdict.threshold,
            "flags": f"0x{actor.flags:08X}",
            "talk_flag_bit0": actor.talk_flag_blocked,
            "disp": actor.displayed,
            "static_visible": static.visible,
            "load_init": static.load_init,
            "talk_start_type": static.talk_start_type,
            "talk_wall_through": static.talk_wall_through,
            "wall_blocked": wall_blocked,
            "facing_error": verdict.facing_error,
            "eligible": verdict.eligible,
            "reject_reason": verdict.reason,
            "unknown_gates": verdict.unknown_gates,
        }

    def _selected_character(self):
        identity = self.selection()
        if identity is None:
            return None, None
        for character in self.runtime.characters():
            if ("npc",) + character.identity == identity or (
                    character.identity == identity):
                return character, identity
        return None, identity

    def _log_sample(self, prefix, verdict, fields):
        self.logger.info(
            "%s room=%s identity=%s gen=%d work=%s slot=%d group=%d res=%d "
            "info=%d name_id=%d talk_sct=%d model=%s static=%s drift=%s "
            "neck=%s neck_offset=%s hero=%s facing=%s yaw=%s "
            "dist3d=%s dist_h=%s hero_ball=%s npc_ball=%s "
            "talk_live=%s talk_static=%s threshold=%s "
            "flags=%s bit0=%s disp=%s static_visible=%s load_init=%s "
            "start_type=%d wall_through=%s wall_blocked=%s "
            "facing_error=%s ELIGIBLE=%s reason=%s unknown=%s",
            prefix,
            fields["room_code"], fields["identity"], fields["generation"],
            fields["work"], fields["slot"], fields["group_id"],
            fields["res_id"], fields["people_info_id"], fields["name_id"],
            fields["talk_script_id"],
            _fmt_position(fields["model_pos"]),
            _fmt_position(fields["static_pos"]), _fmt(fields["spawn_drift"]),
            _fmt_position(fields["neck_pos"]), _fmt(fields["neck_offset"], 3),
            _fmt_position(fields["hero_pos"]), _fmt(fields["hero_facing"], 4),
            _fmt(fields["camera_yaw"], 4),
            _fmt(fields["distance_3d"]), _fmt(fields["distance_horizontal"]),
            _fmt(fields["hero_col_ball"]), _fmt(fields["npc_col_ball"]),
            _fmt(fields["live_talk_distance"]),
            _fmt(fields["static_talk_distance"]), _fmt(fields["threshold"]),
            fields["flags"], fields["talk_flag_bit0"], fields["disp"],
            fields["static_visible"], fields["load_init"],
            fields["talk_start_type"], fields["talk_wall_through"],
            fields["wall_blocked"], _fmt(fields["facing_error"], 1),
            fields["eligible"], fields["reject_reason"],
            ",".join(fields["unknown_gates"]) or "-",
        )

    # ---- polling ------------------------------------------------------

    def poll_once(self, room_code=None, announced_in_range=None):
        marker_fired = self.hotkey.poll() if self.hotkey is not None else False
        now = self.clock()
        dialogue = bool(self.dialogue_active())
        opened = dialogue and not self._dialogue_was_active
        self._dialogue_was_active = dialogue

        if self.pending is not None:
            if opened:
                self.logger.info(
                    "INTERACTION MARK RESULT identity=%s label=%r "
                    "predicted=%s reason=%s outcome=DIALOGUE_OPENED "
                    "elapsed=%.3fs AGREES=%s",
                    self.pending.identity, self.pending.label,
                    self.pending.predicted, self.pending.reason,
                    now - self.pending.at, self.pending.predicted)
                self.pending = None
            elif now - self.pending.at > DIALOGUE_WINDOW:
                self.logger.info(
                    "INTERACTION MARK RESULT identity=%s label=%r "
                    "predicted=%s reason=%s outcome=NO_DIALOGUE "
                    "elapsed=%.3fs AGREES=%s",
                    self.pending.identity, self.pending.label,
                    self.pending.predicted, self.pending.reason,
                    now - self.pending.at, not self.pending.predicted)
                self.pending = None

        if not marker_fired and now < self.next_sample:
            return
        self.next_sample = now + self.sample_interval

        try:
            character, identity = self._selected_character()
            if identity is None:
                if marker_fired:
                    self.logger.info(
                        "INTERACTION MARK identity=None "
                        "(no NPC selected; nothing to score)")
                return
            if character is None:
                if marker_fired:
                    self.logger.info(
                        "INTERACTION MARK identity=%s outcome=NOT_LIVE "
                        "(selected identity has no live actor)", identity)
                return
            pose = self.pose_source.player_pose()
            actors = self.runtime.actors()
            hero_actor = self.runtime.hero_actor(
                self.pose_source.hero_model_address(), actors)
            hero_info = (
                self.runtime.people_info(hero_actor.people_info_id)
                if hero_actor is not None else None)
            verdict, fields = self._describe(
                character, hero_actor, hero_info, pose, room_code)
        except GameMemoryError as exc:
            self.logger.debug("INTERACTION DIAG read failure: %s", exc)
            return

        self.samples += 1
        if announced_in_range is not None:
            fields = dict(fields, nav_says_in_range=announced_in_range)
            self.logger.info(
                "INTERACTION DIAG NAV identity=%s nav_in_range=%s "
                "predicate_eligible=%s AGREE=%s",
                fields["identity"], announced_in_range, verdict.eligible,
                bool(announced_in_range) == bool(verdict.eligible))
        self._log_sample("INTERACTION DIAG", verdict, fields)

        if marker_fired:
            self.marks += 1
            self.pending = PendingMark(
                at=now, identity=fields["identity"],
                label=self.selection_label() if self.selection_label else None,
                predicted=verdict.eligible, reason=verdict.reason)
            self.logger.info(
                "INTERACTION MARK identity=%s predicted_eligible=%s "
                "reason=%s dist3d=%s threshold=%s facing_error=%s "
                "-- watching %.1fs for dialogue",
                fields["identity"], verdict.eligible, verdict.reason,
                _fmt(verdict.distance), _fmt(verdict.threshold),
                _fmt(verdict.facing_error, 1), DIALOGUE_WINDOW)

    selection_label = None
    """Optional callable supplying the selected entity's spoken label, so a
    mark record names the NPC the way the player heard it. Left as a plain
    attribute so the app can attach it without widening the constructor."""
