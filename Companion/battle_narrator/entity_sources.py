"""Read-only entity-category sources, adapting existing structured memory
sources into the generic Entity representation consumed by EntityNavigator.

Each source is independent and read-only. Adding a new category means
adding a new source class here, not touching the navigator or an existing
source.
"""
from dataclasses import replace
import math
import string
import struct

from .entities import Entity
from .memory import MemoryError as GameMemoryError
from .npc_beacons import NPC, NPCMemorySource, Position
from .talk_predicate import TalkInputs, evaluate


def _letter_label(index):
    """A, B, ..., Z, AA, AB, ... -- stable per-room ordinal for NPCs with
    no resolved name (name_id 0 or missing from the PeopleIDs table).

    Spoken bare ("A", not "NPC A"): the category header already said NPCs,
    so the prefix was pure padding on the most-pressed hotkey."""
    letters = []
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters.append(string.ascii_uppercase[remainder])
    return "".join(reversed(letters))


class LetterRegistry:
    """Assigns and REMEMBERS a stable ordinal per NPC identity for a room
    visit, and turns it into a letter for the NPCs that need one.

    The letter is the NPC's position in the room's COMPLETE canonical
    roster, not "the nth unnamed NPC". So a room of
    `Eagun, Beluh, unnamed, unnamed, clerk` speaks

        Eagun, Beluh, C, D, Pokemon Mart clerk

    and never `A, B` for the two unnamed ones. Named and role-labelled NPCs
    occupy their ordinal without displaying it, which is what makes the
    letters usable as positions the player can count to: "C" is the third
    person in the room, whatever the first two are called.

    Two earlier behaviours this replaces. Letters used to be recomputed
    from whichever NPCs happened to be live on each `entities()` call, so
    one NPC despawning silently renamed every NPC after it -- the player's
    "B" became someone else's while they were walking toward it. And they
    were issued only to unnamed NPCs, so the letters bore no relation to
    the order anything was announced in.

    Ordinals are issued once per identity and kept for the room visit, so
    movement, distance sorting, despawning and a name becoming resolvable
    later all leave every other NPC's letter untouched."""

    def __init__(self):
        self.room = None
        self._ordinals = {}
        self._next = 0

    def reset(self, room):
        self.room = room
        self._ordinals = {}
        self._next = 0

    def ordinal(self, room, identity):
        """Stable position in the room's roster. Called for EVERY canonical
        NPC, named or not, so the sequence has no gaps."""
        if room != self.room:
            self.reset(room)
        if identity not in self._ordinals:
            self._ordinals[identity] = self._next
            self._next += 1
        return self._ordinals[identity]

    def letter(self, room, identity):
        return _letter_label(self.ordinal(room, identity))


class NPCEntitySource:
    """Adapts the existing, already-verified NPCMemorySource (npc_beacons.py)
    into generic Entity records. Does not duplicate its position/player-pose
    logic -- delegates to it directly.

    Only includes npc.category == "npc" -- npc_beacons.py's npcs() also
    injects synthetic item/healing entries (from its verified, hand-
    curated per-floor ITEMS/HEALING lookups) with category set to
    "item"/"healing"; those are handled by CategoryFilteredEntitySource
    below so each gets its own entity-nav category rather than being
    lumped in under "NPC". Elevator/door entries come from
    AuthoritativeElevatorEntitySource/AuthoritativeDoorEntitySource
    (authoritative_warps.py) via WarpAugmentedNPCSource instead.

    player_pose()'s "yaw" is the active camera's fixed orientation for the
    current room (this game's camera does not rotate with the character --
    confirmed live: the hero model's own rotation changed across an
    in-place turn while camera yaw stayed bit-identical). This is
    deliberate, by explicit instruction: direction is a fixed compass-style
    reading anchored to the room's camera, not the character's own facing
    -- an entity's clock position depends only on its position relative to
    the player, never on which way the player happens to be facing.
    """

    def __init__(self, memory, profile, entity_names):
        self.source = NPCMemorySource(memory, profile)
        self.entity_names = entity_names or {}

    def player_pose(self):
        return self.source.player_pose()

    def entities(self):
        seen = set()
        npcs = []
        for npc in self.source.npcs():
            if npc.category != "npc":
                continue
            if not npc.visible or not npc.talk_id:
                continue
            if npc.identity in seen:
                continue
            seen.add(npc.identity)
            npcs.append(npc)
        # Unnamed NPCs (name_id not in the PeopleIDs table) get a stable
        # per-room letter (A, B, C...) instead of no label at all, so they
        # can still be told apart and referred to. Ordered by their raw
        # floor-character index, not distance/selection order, so the
        # same NPC keeps the same letter for the whole room visit.
        unnamed_order = sorted(
            (npc for npc in npcs if not self.entity_names.get(npc.name_id)),
            key=lambda npc: npc.identity,
        )
        letters = {
            npc.identity: _letter_label(index)
            for index, npc in enumerate(unnamed_order)
        }
        result = []
        for npc in npcs:
            label = self.entity_names.get(npc.name_id) or f"NPC {letters[npc.identity]}"
            result.append(Entity(
                category="npc",
                identity=("npc",) + npc.identity,
                label=label,
                position=npc.position,
                interaction_distance=npc.interaction_radius,
                metadata={"name_id": npc.name_id},
            ))
        return result


class LiveNPCEntitySource:
    """The canonical NPC source: one entity per live actor, positioned and
    gated by the game's own state.

    Replaces `NPCEntitySource` (which iterated STATIC `floor_character`
    records and decorated them with live state). The difference that
    matters: a static record with no spawned actor now produces nothing at
    all, rather than an entity at a spawn point nobody is standing on.

    Every published entity carries:
      - `identity` = ("npc", groupID, resID) -- the engine's own key
      - `position` = the live model position
      - `interaction_position` = the neck reference `peopleTalkCheck`
        measures to, when resolvable
      - `interaction_distance` = the game's own three-term threshold
      - metadata: generation, talk script id, and the full predicate
        verdict, so downstream readers never re-derive eligibility

    NPCs the game can never talk to (talk-flag bit 0, talk-start type 3)
    are excluded entirely -- steering a blind player toward one is exactly
    the "confidently wrong target" this project must not produce. NPCs that
    are merely out of range, or currently facing-blocked, stay navigable."""

    def __init__(self, runtime, pose_source, entity_names, neck_resolver=None,
                 role_resolver=None, wall_test=None, logger=None):
        self.runtime = runtime
        self.pose_source = pose_source
        self.entity_names = entity_names or {}
        self.neck_resolver = neck_resolver
        self.role_resolver = role_resolver
        self.wall_test = wall_test
        self.logger = logger
        self.letters = LetterRegistry()
        self.rejected = ()

    def player_pose(self):
        return self.pose_source.player_pose()

    def current_floor_id(self):
        return self.runtime.current_floor_id()

    def _neck_is_plausible(self, neck, actor, info, character):
        """Is a resolved neck joint actually inside the character?

        The neck reference takes its Y from the actor base, so the offset
        from the model origin is purely horizontal -- and a neck joint
        cannot be further from its own body's centre than that body's own
        collision radius. `people_info +0x10` supplies that radius, so the
        bound is the game's own measure of the character's size rather than
        a tuned constant.

        Why this guard exists. The first live samples (2026-08-09, Agate
        Mart, colBall 4.0) produced offsets of **40.92** and **11.32**
        units, and one NPC's offset moved 0.50 -> 11.32 between two samples
        five seconds apart. A neck ten body-radii away that jumps around
        between polls is not a neck; the JObj walk is landing somewhere
        else. Two of the three NPCs did resolve sanely (0.18-0.20), so the
        walk is not uniformly wrong -- which is exactly the case a blanket
        on/off switch handles badly and a per-sample bound handles well.

        Falling back to the actor position is not a degradation: it is what
        this source published before the neck reference existed, and it is
        what the engine itself does for an actor with no neck joint."""
        limit = info.col_ball_size
        if not limit or limit <= 0.0:
            return True
        offset = math.hypot(
            neck.x - actor.position.x, neck.z - actor.position.z)
        if offset <= limit:
            return True
        if self.logger is not None:
            self.logger.debug(
                "NPC SOURCE neck rejected for %s: offset %.2f exceeds "
                "collision ball %.2f; using the actor position",
                character.identity, offset, limit)
        return False

    def _hero_state(self, actors):
        hero = self.runtime.hero_actor(
            self.pose_source.hero_model_address(), actors)
        info = (self.runtime.people_info(hero.people_info_id)
                if hero is not None else None)
        return hero, info

    def entities(self):
        room = self.runtime.current_floor_id()
        characters = self.runtime.characters()
        self.rejected = self.runtime.rejected
        if self.logger is not None and self.rejected:
            for rejection in self.rejected:
                self.logger.debug(
                    "NPC SOURCE rejected slot=%d group=%d res=%d: %s",
                    rejection.slot, rejection.group_id, rejection.res_id,
                    rejection.reason)
        pose = self.player_pose()
        actors = self.runtime.actors()
        hero_actor, hero_info = self._hero_state(actors)
        hero_col = hero_info.col_ball_size if hero_info is not None else 0.0
        hero_facing = (
            hero_actor.facing if hero_actor is not None else pose.facing)

        published = []
        for character in sorted(characters, key=lambda c: c.identity):
            actor, static, info = character.actor, character.static, character.info
            neck = actor.position
            neck_detail = None
            if self.neck_resolver is not None:
                neck_detail = self.neck_resolver.resolve(
                    actor.model, info.neck_index, actor.position)
                resolved = neck_detail.position
                if resolved is not None and self._neck_is_plausible(
                        resolved, actor, info, character):
                    neck = resolved
                else:
                    neck_detail = replace(neck_detail, source="actor base")
            wall_blocked = None
            if self.wall_test is not None and not static.talk_wall_through:
                try:
                    wall_blocked = self.wall_test(
                        pose.position, neck, hero_col)
                except Exception:
                    wall_blocked = None
            verdict = evaluate(TalkInputs(
                displayed=actor.displayed,
                talk_flag_blocked=actor.talk_flag_blocked,
                talk_start_type=static.talk_start_type,
                hero_position=pose.position,
                neck_position=neck,
                hero_facing=hero_facing,
                hero_col_ball_size=hero_col,
                npc_col_ball_size=info.col_ball_size,
                talk_distance=actor.talk_distance,
                wall_through=static.talk_wall_through,
                wall_blocked=wall_blocked,
            ))
            if verdict.blocked_permanently:
                if self.logger is not None:
                    self.logger.debug(
                        "NPC SOURCE excluded %s: %s",
                        character.identity, verdict.reason)
                continue
            published.append((character, neck, verdict, neck_detail))

        result = []
        for character, neck, verdict, neck_detail in published:
            actor, static, info = character.actor, character.static, character.info
            identity = ("npc",) + character.identity
            role = (
                self.role_resolver.resolve(room, static.talk_script_id)
                if self.role_resolver is not None else None)
            name = self.entity_names.get(static.name_id)
            # Claim the ordinal FIRST, unconditionally. A named or role
            # NPC still occupies its position in the roster -- it simply
            # does not display it -- which is what keeps the letters
            # countable: "C" is the third person in the room.
            ordinal = self.letters.ordinal(room, character.identity)
            label = role or name or _letter_label(ordinal)
            result.append(Entity(
                category="npc",
                identity=identity,
                label=label,
                position=actor.position,
                interaction_distance=verdict.threshold,
                subtype=role,
                metadata={
                    "name_id": static.name_id,
                    "talk_script_id": static.talk_script_id,
                    "people_info_id": actor.people_info_id,
                    "generation": character.generation,
                    "interaction_position": neck,
                    "neck": neck_detail,
                    "verdict": verdict,
                    "role": role,
                    "ordinal": ordinal,
                    # Raw inputs, published so an observer can settle the
                    # three questions Phase 2 left open (see
                    # ENTITY_NAVIGATION_AUDIT.md) from ordinary play,
                    # without a second pass over people_work and without
                    # reaching into this source's internals:
                    #   - is the live talk distance initialised from the
                    #     static one?  talk_distance_live vs _static
                    #   - how far is the neck reference from the model
                    #     origin, really?  position vs interaction_position
                    #   - do live talk script ids match the extracted
                    #     `talk_<N>_` numbers?  talk_script_id, above
                    "talk_distance_live": actor.talk_distance,
                    "talk_distance_static": info.static_talk_distance,
                    "col_ball_size": info.col_ball_size,
                    "spawn_position": static.position,
                },
            ))
        return result


class TalkHistory:
    """Session-local NPC conversations, versioned by global story progress."""

    STORY_PROGRESS_FLAG = 964

    def __init__(self, flag_reader):
        self.flag_reader = flag_reader
        self._talked = set()

    def story_progress(self):
        try:
            return self.flag_reader.value(self.STORY_PROGRESS_FLAG)
        except GameMemoryError:
            return None

    def mark(self, npc_identity):
        if npc_identity is not None:
            self._talked.add((tuple(npc_identity), self.story_progress()))

    def has_talked(self, entity_identity):
        raw_identity = tuple(entity_identity[1:])
        return (raw_identity, self.story_progress()) in self._talked


class TalkedNPCEntitySource:
    def __init__(self, source, history):
        self.source = source
        self.history = history

    def player_pose(self):
        return self.source.player_pose()

    def entities(self):
        result = []
        for entity in self.source.entities():
            label = entity.label
            if self.history.has_talked(entity.identity):
                label += " (talked)"
            result.append(Entity(
                category=entity.category, identity=entity.identity, label=label,
                position=entity.position,
                interaction_distance=entity.interaction_distance,
                metadata=entity.metadata,
            ))
        return result

class CategoryFilteredEntitySource:
    """Adapts npc_beacons.py's synthetic per-floor entries (its verified,
    hand-curated ITEMS/HEALING lookups, injected into NPCMemorySource.
    npcs() with a distinguishing `category`) into their own entity-nav
    category. Reused directly, not duplicated -- this class does not know
    what floors have items/healing spots, it only filters and relabels
    what npcs() already produces. (Elevator/door used to be hand-curated
    lookups here too; both now come from the authoritative interaction
    table via AuthoritativeElevatorEntitySource/AuthoritativeDoorEntitySource
    in authoritative_warps.py instead -- see WarpAugmentedNPCSource.)

    Unlike NPCEntitySource, the label comes straight from npc.label (these
    synthetic entries carry their own verified name, e.g. "Elevator" or a
    specific item name) rather than a name-ID string-table lookup.
    """

    def __init__(self, memory, profile, category):
        self.source = NPCMemorySource(memory, profile)
        self.category = category

    def player_pose(self):
        return self.source.player_pose()

    def entities(self):
        result = []
        for npc in self.source.npcs():
            if npc.category != self.category:
                continue
            result.append(Entity(
                category=self.category,
                identity=(self.category,) + npc.identity,
                label=npc.label,
                position=npc.position,
                interaction_distance=npc.interaction_radius,
            ))
        return result


class FilteredEntitySource:
    """Expose only entities accepted by a player-facing category predicate."""

    def __init__(self, source, predicate, category=None, relabel=None):
        self.source = source
        self.predicate = predicate
        self.category = category
        self.relabel = relabel

    def player_pose(self):
        return self.source.player_pose()

    def entities(self):
        result = []
        for entity in self.source.entities():
            if not self.predicate(entity):
                continue
            result.append(Entity(
                category=self.category or entity.category,
                identity=entity.identity,
                label=(self.relabel(entity) if self.relabel else entity.label),
                position=entity.position,
                interaction_distance=entity.interaction_distance,
                metadata=entity.metadata,
            ))
        return result


class CombinedEntitySource:
    """Combine independently verified entity sources into one category."""

    def __init__(self, *sources):
        self.sources = sources

    def player_pose(self):
        return self.sources[0].player_pose()

    def entities(self):
        result = []
        seen = set()
        for source in self.sources:
            for entity in source.entities():
                if entity.identity in seen:
                    continue
                seen.add(entity.identity)
                result.append(entity)
        return result

class WarpEntitySource:
    """Read-only entity source for an unidentified table, generic across
    floors. The "warp" category name is a PLACEHOLDER, not a confirmed
    type -- see Documentation/ENTITY_NAVIGATION.md's "Warp category"
    section for the full record.

    *** UNVERIFIED / TENTATIVE *** Reads the table at
    profile.warp_count_root/warp_data_root, originally labeled "treasures"
    by an unverified pre-existing diagnostic script
    (probe_overworld_entities.py). Of 115+ active records, only 4 were
    ever live-tested (all selected by "nearest to the player" -- a small,
    non-random sample), and all 4 corresponded to elevator/floor-
    transition points, not pickup-able items. That is real evidence some
    entries are transition points; it is explicitly NOT evidence the
    whole table is exclusively transition points -- the table may be a
    mixed collection (some items, some elevators/doors/other triggers)
    that this sample simply didn't happen to reveal. Do not treat entries
    from this source as confidently non-item. Kept separate from the
    "elevator" category (which reuses Codex's own independently-verified,
    hand-curated per-floor ELEVATORS lookup) since the two data sources
    have not been shown to agree or overlap.

    No warp name is resolved (none identified). No interaction-distance
    field has been identified, so interaction-range wording never appears
    for this category (Entity.interaction_distance stays None). A single
    record with a non-finite position is skipped rather than aborting the
    whole read, since this is exploratory, lower-confidence data.

    The table has no floor-ID field, so records cannot be scoped to the
    current room the way NPCs are -- it appears to be a single global
    table spanning the whole game (confirmed live: 115 of 116 records are
    "active", and without any filtering all 115 were offered regardless of
    which floor the player was actually on). Bounded instead by straight-
    line distance from the player (profile.warp_max_distance) as a
    practical stand-in, so the category returns a navigable handful of
    genuinely nearby candidates rather than the entire game's table.
    """

    def __init__(self, memory, profile, pose_source):
        self.memory = memory
        self.profile = profile
        self.pose_source = pose_source

    def player_pose(self):
        return self.pose_source.player_pose()

    def entities(self):
        p = self.profile
        count_root = self.memory.u32(p.warp_count_root, "warp count root")
        count = self.memory.u32(count_root, "warp count")
        if count > p.warp_record_max:
            raise GameMemoryError(f"invalid warp count {count}")
        pointer = self.memory.pointer(
            p.warp_data_root,
            max(1, count) * p.warp_record_stride,
            "warp table",
            4,
        )
        pose = self.pose_source.player_pose()
        result = []
        for index in range(count):
            base = pointer + index * p.warp_record_stride
            marker = self.memory.u32(base, "warp marker")
            if marker == 0:
                continue
            position = Position(*struct.unpack(
                ">fff",
                self.memory.bytes(
                    base + p.warp_position_offset, 12, "warp position", 4
                ),
            ))
            if not all(math.isfinite(v) for v in (position.x, position.y, position.z)):
                continue
            horizontal = math.hypot(
                position.x - pose.position.x, position.z - pose.position.z
            )
            if horizontal > p.warp_max_distance:
                continue
            result.append(Entity(
                category="warp",
                identity=("warp", index),
                label=None,
                position=position,
            ))
        return result


class RecategorisedNPCSource:
    """Re-label matching entries of an `npcs()` stream with a different
    category, IN PLACE.

    `WarpAugmentedNPCSource` appends a separate source's entities, which is
    right for warps and doors -- they are not in the NPC stream at all. It
    is wrong for a role NPC like a Poke Mart clerk, which already IS an
    ordinary NPC in that stream: appending it again would leave the same
    character beaconing twice, once as a generic NPC and once as a Mart,
    from the same spot. Re-labelling keeps exactly one beacon per
    character and simply changes which sound it uses."""

    def __init__(self, npc_source, predicate, category):
        self.npc_source = npc_source
        self.predicate = predicate
        self.category = category

    def player_pose(self):
        return self.npc_source.player_pose()

    def current_floor_id(self):
        return self.npc_source.current_floor_id()

    def npcs(self):
        return [
            replace(npc, category=self.category) if self.predicate(npc) else npc
            for npc in self.npc_source.npcs()
        ]


class WarpAugmentedNPCSource:
    """Expose an authoritative interaction-table entity source (warps,
    elevators, or doors -- anything with an .entities() method) to the
    spatial beacon reader. The category defaults to "warp" for backward
    compatibility; pass "elevator"/"door" to augment with those instead.
    Chain multiple instances to augment with more than one category at
    once (each wraps the previous source)."""

    def __init__(self, npc_source, warp_source, category="warp"):
        self.npc_source = npc_source
        self.warp_source = warp_source
        self.category = category

    def player_pose(self):
        return self.npc_source.player_pose()

    def current_floor_id(self):
        return self.npc_source.current_floor_id()

    def npcs(self):
        floor_id = self.current_floor_id()
        result = list(self.npc_source.npcs())
        for entity in self.warp_source.entities():
            # Beacon eligibility is NOT navigation eligibility (audit cause
            # F). Synthesising an NPC for every entity a source returns is
            # what welded them together: appearing in a list WAS beaconing,
            # so an opened item box could not be kept as a landmark without
            # also being kept audible. A source that has an opinion states
            # it in `metadata["beacon"]`; one that does not keeps the old
            # behaviour of beaconing everything it publishes.
            if entity.metadata and entity.metadata.get("beacon") is False:
                continue
            result.append(NPC(
                floor_id=floor_id,
                index=0x10000 + entity.identity[-1],
                visible=True,
                talk_id=1,
                position=entity.position,
                interaction_radius=-1.0e9,
                category=self.category,
                label=entity.label,
            ))
        return result

