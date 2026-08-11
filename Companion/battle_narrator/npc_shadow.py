"""Shadow comparison between the production NPC source and the canonical
one, for Phase 2 restoration.

Why this exists
---------------
`LiveNPCEntitySource` was written to replace `NPCEntitySource`, passed its
regression suite, and was then reverted out of production the same day
(2026-08-06) because it is strictly MORE selective: it publishes only NPCs
that have a live actor and survive eight validity rules, so a single wrong
offset anywhere in that chain empties the NPC category. That is what the
project owner hit, mid-dungeon, with no way to tell it had happened.

The lesson is not "the new source is wrong". It is that swapping an
unvalidated stricter source into the speaking path is the wrong order of
operations. This module runs both sources side by side, keeps speaking the
OLD one, and logs the difference -- so the evidence needed to make the swap
safely accumulates during ordinary play instead of requiring a special
diagnostic session that, per the audit, never actually happened.

It answers, from real rooms:

- does the canonical source ever return ZERO where the old one returns
  entities?  (the exact failure that forced the revert)
- which validity rule rejects each actor, and how often
- how far the old source's published position is from the live one
  (the "NPC announced where nobody is standing" defect, measured)
- `talk_distance_live` vs `talk_distance_static` -- whether the live field
  is initialised from the static one
- `neck_offset` -- how far the neck reference really sits from the model
  origin
- `talk_script_id` -- whether live ids match the extracted `talk_<N>_`
  numbers the role table is derived from

Never speaks. Never affects what any other reader publishes. Every read is
wrapped: a failure here logs and backs off, and cannot reach the poll loop.
"""
import collections
import math
import time


SAMPLE_INTERVAL = 5.0
"""Seconds between comparisons. The production hot path calls
`entities()` on every source every tick (`InteractionReadyReader`), and the
canonical source does a linear people-info search per actor, so this must
never run per tick. Five seconds is slow enough to be free and fast enough
that walking through a room produces several samples."""

DRIFT_THRESHOLD = 1.0
"""Game units between the two sources' positions for the same NPC before
it is worth a line. Below this they agree; above it, the old source is
publishing a spawn point the actor has left."""


def _distance(a, b):
    if a is None or b is None:
        return None
    try:
        return math.sqrt(
            (a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)
    except (AttributeError, TypeError):
        return None


def _fmt(value, digits=2):
    if value is None:
        return "?"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "?"
        return f"{value:.{digits}f}"
    return str(value)


def _hex(value):
    return "?" if not isinstance(value, int) else f"0x{value:08X}"


def _fmt_position(position):
    if position is None:
        return "?"
    try:
        return f"({position.x:.2f},{position.y:.2f},{position.z:.2f})"
    except AttributeError:
        return "?"


def _key(entity):
    """Correlate the two sources' identities.

    Old:  ("npc", floor_id, index)
    New:  ("npc", groupID, resID)

    `resID` IS the index into the current room's `floor_character` array --
    that is what `floorDataBiosGetCharInfo` computes
    (`charBase + resID * 0x24`), and it is why the same NPC can be found in
    both streams at all. The trailing element is therefore the common key,
    and nothing else about the two identities is comparable."""
    try:
        return entity.identity[-1]
    except (AttributeError, IndexError, TypeError):
        return None


class NPCSourceShadowReader:
    """Runs the canonical NPC source alongside the production one and logs
    the diff. Read-only observer; produces no entities of its own."""

    def __init__(self, primary, shadow, logger, clock=time.monotonic,
                 sample_interval=SAMPLE_INTERVAL,
                 drift_threshold=DRIFT_THRESHOLD):
        self.primary = primary
        self.shadow = shadow
        self.logger = logger
        self.clock = clock
        self.sample_interval = sample_interval
        self.drift_threshold = drift_threshold
        self.next_sample = 0.0
        self.samples = 0
        self.last_summary = None
        self.empty_rooms = set()
        """Rooms where the canonical source published nothing while the old
        one published something. This set IS the go/no-go list for the
        swap: it must stay empty across a real play session."""

    def clear(self, reason):
        self.next_sample = 0.0
        self.last_summary = None
        self.logger.debug("NPC SHADOW cleared: %s", reason)

    def poll_once(self, context_valid=True):
        if not context_valid:
            return
        now = self.clock()
        if now < self.next_sample:
            return
        self.next_sample = now + self.sample_interval
        try:
            self._sample()
        except Exception as error:
            # A shadow comparison must never be able to disturb the thing
            # it is shadowing. Back off a full interval and keep going.
            self.logger.debug("NPC SHADOW sample failed: %r", error)

    # ---- the comparison -------------------------------------------------

    def _sample(self):
        room = None
        try:
            room = self.shadow.current_floor_id()
        except Exception:
            pass
        primary = list(self.primary.entities())
        shadow = list(self.shadow.entities())
        self.samples += 1

        by_primary = {_key(e): e for e in primary if _key(e) is not None}
        by_shadow = {_key(e): e for e in shadow if _key(e) is not None}
        both = sorted(set(by_primary) & set(by_shadow))
        primary_only = sorted(set(by_primary) - set(by_shadow))
        shadow_only = sorted(set(by_shadow) - set(by_primary))

        rejects = collections.Counter(
            rejection.reason for rejection in getattr(self.shadow, "rejected", ()))

        drifts = []
        for key in both:
            drift = _distance(by_primary[key].position, by_shadow[key].position)
            if drift is not None and drift > self.drift_threshold:
                drifts.append((key, drift))

        starved = bool(primary) and not shadow
        if starved and room is not None:
            self.empty_rooms.add(room)

        summary = (
            f"room={room if room is None else hex(room)} "
            f"primary={len(primary)} shadow={len(shadow)} "
            f"both={len(both)} primary_only={len(primary_only)} "
            f"shadow_only={len(shadow_only)} drifting={len(drifts)}"
        )
        if starved:
            # The revert condition, named explicitly so it cannot be missed
            # in a log skim. This is the one line that blocks the swap.
            self.logger.warning(
                "NPC SHADOW STARVED %s -- the canonical source published "
                "nothing where the production source published %d. Do NOT "
                "swap sources while this appears.", summary, len(primary))
        elif summary != self.last_summary:
            self.logger.info("NPC SHADOW %s", summary)
        self.last_summary = summary

        for key in primary_only:
            entity = by_primary[key]
            self.logger.info(
                "NPC SHADOW primary-only index=%s label=%r pos=%s "
                "-- published with no live actor the canonical source "
                "accepts", key, entity.label, _fmt_position(entity.position))
        for key in shadow_only:
            entity = by_shadow[key]
            self.logger.info(
                "NPC SHADOW shadow-only index=%s label=%r pos=%s",
                key, entity.label, _fmt_position(entity.position))
        for key, drift in drifts:
            self.logger.info(
                "NPC SHADOW drift index=%s d=%s primary=%s shadow=%s "
                "labels=%r/%r", key, _fmt(drift),
                _fmt_position(by_primary[key].position),
                _fmt_position(by_shadow[key].position),
                by_primary[key].label, by_shadow[key].label)
        if rejects:
            self.logger.info(
                "NPC SHADOW rejects %s",
                "; ".join(f"{reason} x{count}"
                          for reason, count in sorted(rejects.items())))
        for key in both:
            self._log_answers(key, by_shadow[key])

    def _log_answers(self, key, entity):
        """The three questions Phase 2 left open, per NPC, straight from the
        canonical source's own published metadata."""
        metadata = entity.metadata or {}
        live = metadata.get("talk_distance_live")
        static = metadata.get("talk_distance_static")
        neck = metadata.get("interaction_position")
        offset = _distance(entity.position, neck)
        spawn_drift = _distance(entity.position, metadata.get("spawn_position"))
        verdict = metadata.get("verdict")
        self.logger.debug(
            "NPC SHADOW answers index=%s label=%r talk_live=%s "
            "talk_static=%s talk_match=%s neck_offset=%s col_ball=%s "
            "spawn_drift=%s talk_sct=%s role=%r threshold=%s eligible=%s "
            "model_res=%s",
            key, entity.label, _fmt(live), _fmt(static),
            "?" if live is None or static is None
            else str(abs(live - static) < 0.01),
            _fmt(offset), _fmt(metadata.get("col_ball_size")),
            _fmt(spawn_drift), metadata.get("talk_script_id"),
            metadata.get("role"),
            _fmt(getattr(verdict, "threshold", None)),
            getattr(verdict, "eligible", None),
            _hex(metadata.get("people_info_id")))
        self._log_neck(key, entity, metadata.get("neck"))

    def _log_neck(self, key, entity, neck):
        """The interaction-position resolver's own inputs, per the audit
        brief's required fields: model, part index, JObj pointer, which
        matrix source answered, and whether the fallback engaged.

        Logged separately from the answers line so a neck investigation can
        be grepped on its own without pulling in every other field."""
        if neck is None:
            return
        fell_back = neck.source in (None, "actor base")
        self.logger.debug(
            "NPC SHADOW neck index=%s label=%r model=%s root=%s jobj=%s "
            "req_index=%s part_index=%s blending=%s source=%s offset=%s "
            "fallback=%s reason=%s",
            key, entity.label,
            _hex(neck.model), _hex(neck.root), _hex(neck.jobj),
            neck.requested_index, neck.part_index, neck.blending,
            neck.source, _fmt(neck.offset), fell_back, neck.reason)
