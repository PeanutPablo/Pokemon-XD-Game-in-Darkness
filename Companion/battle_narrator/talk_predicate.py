"""Companion-side reproduction of the game's own talk-eligibility test.

`peopleTalkCheck` (0x802A3444, called from `updateChat` in heroMove.s) is
the single authority on whether pressing A will do anything. This module
reproduces its gates in the same order, and reports WHICH gate rejected a
candidate rather than a bare boolean -- because "the navigator said go
here and nothing happened" is only debuggable if the reason is recorded.

The gates, decoded from the disassembly (register names as they appear):

    r31 = the hero's own people record; f28 = hero colBallSize
    for each actor r27:
      1  +0x00 occupied                                     else skip
      2  r27 != r31                                         else skip
      3  +0x0D disp                                         else skip
      4  peopleBiosCheckFlag(r27, 1)  -> +0x10 bit 0        must be CLEAR
      5  r25 = floorCharacterBiosFindByResID(+0x14, +0x18)
         if r25: floorCharacterBiosGetTalkStartType(r25) != 3
      6  r26 = peopleInfoBiosGetPtr(+0x1C)                   must be non-null
      7  f31 = PSVECDistance(heroPos, peopleGetNeckPos(...))
         f30 = peopleInfoBiosGetColBallSize(r26)
         f31 <= f28 + peopleGetTalkDistance(...) + f30
      8  |peopleVecCalcRotY(heroPos, neckPos, heroRotY)| <= radians(40)
      9  if gimmickBoxIsPushBoxFloor():
             int(heroPos.y / K) == int(neckPos.y / K)
     10  (treasure kind 1 only -- Phase 3, not modelled here)
     11  unless floorCharacterBiosGetTalkWallThrough(r25):
             GScolsys2HitCollision(heroPos, neckPos, f28) == 0
     12  if the hero has a following member:
             peopleInsideCheck(heroPos, neckPos, memberPos, npcColBall) == 0

Gate 7 is emphatically NOT "horizontal distance <= talk distance + 1.5",
which is what this project used before. Three separate corrections: the
target is the neck reference, the distance is three-dimensional, and the
threshold is the sum of three live terms.

Read-only. Computes; never reads memory itself -- callers supply the
already-read state, which is what makes every gate unit-testable.
"""
from dataclasses import dataclass
import math


TALK_CONE_DEGREES = 40.0
"""`updateChat` passes the literal 40.0, and `peopleTalkCheck` computes
`f26 = 0.017453292 * 40.0` -- that constant is pi/180, so the gate is
radians(40). Not a guess and not a tuned value."""

TALK_START_TYPE_NEVER = 3
"""`floorCharacterBiosGetTalkStartType(r25) == 3` makes the engine skip
the actor. The other three values are not distinguished here because the
engine does not distinguish them at this gate."""

PUSH_BOX_HEIGHT_UNIT = None
"""The divisor in gate 9's height-band comparison (`@2355`). Its value was
not resolved from the disassembly listing, so the gate is reported as
UNKNOWN rather than evaluated -- see `TalkVerdict.unknown_gates`. It only
applies on push-box floors, which this project has not yet identified."""


REJECT_NOT_OCCUPIED = "actor slot not occupied"
REJECT_IS_HERO = "actor is the hero"
REJECT_NOT_DISPLAYED = "actor display flag clear"
REJECT_TALK_FLAG = "people_work +0x10 bit 0 set (talking suppressed)"
REJECT_TALK_START_TYPE = "talk-start type 3 (never talkable)"
REJECT_NO_PEOPLE_INFO = "no people-info record"
REJECT_DISTANCE = "outside the talk distance threshold"
REJECT_FACING = "outside the talk cone"
REJECT_HEIGHT_BAND = "different push-box height band"
REJECT_WALL = "a wall blocks the line to the neck position"
REJECT_MEMBER = "the following partner blocks the line"


@dataclass(frozen=True)
class TalkInputs:
    """Everything gate 1-12 needs, already read from memory."""

    occupied: bool = True
    is_hero: bool = False
    displayed: bool = True
    talk_flag_blocked: bool = False
    talk_start_type: int = 0
    has_people_info: bool = True
    hero_position: object = None
    neck_position: object = None
    hero_facing: object = None
    hero_col_ball_size: float = 0.0
    npc_col_ball_size: float = 0.0
    talk_distance: float = 0.0
    wall_through: bool = True
    wall_blocked: object = None
    """True/False when a wall sweep was actually performed, None when no
    room geometry was available. None means the gate is UNKNOWN, not
    passed -- see `TalkVerdict`."""
    push_box_floor: bool = False
    """Gate 9 only applies on push-box floors. Defaults False because no
    push-box floor has been identified in this project yet; when one is,
    the caller supplies True and the gate reports UNKNOWN rather than
    silently passing."""
    member_blocked: bool = False
    """Gate 12 only runs when the hero has a following partner
    (`heroMoveIsMember`). Defaults False -- no partner -- because that is
    the ordinary overworld state and the gate is skipped entirely in it.
    A caller that can determine a partner is present supplies the real
    `peopleInsideCheck` result. Documented as an approximation rather than
    modelled, because defaulting the OTHER way would suppress every
    interaction cue in the game on an unverified assumption."""


@dataclass(frozen=True)
class TalkVerdict:
    eligible: bool
    """True only when every modelled gate passed AND no gate was unknown.
    Deliberately conservative: the navigator must never promise an
    interaction it could not fully verify."""
    reason: object
    distance: object
    threshold: object
    facing_error: object
    unknown_gates: tuple = ()

    @property
    def in_range(self):
        """Distance gate alone. An NPC may legitimately be navigable and
        out of range; this separates 'too far' from 'will never work'."""
        return (self.distance is not None and self.threshold is not None
                and self.distance <= self.threshold)

    @property
    def blocked_permanently(self):
        """The NPC can never be talked to from anywhere, so it should not
        be offered as a navigation target at all."""
        return self.reason in (
            REJECT_NOT_OCCUPIED, REJECT_IS_HERO, REJECT_NOT_DISPLAYED,
            REJECT_TALK_FLAG, REJECT_TALK_START_TYPE, REJECT_NO_PEOPLE_INFO,
        )


def distance_3d(a, b):
    return math.sqrt(
        (a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def talk_threshold(hero_col_ball_size, talk_distance, npc_col_ball_size):
    """`f28 + peopleGetTalkDistance(...) + f30`, exactly."""
    return hero_col_ball_size + talk_distance + npc_col_ball_size


def facing_error_degrees(hero_position, hero_facing, target):
    """`peopleVecCalcRotY(heroPos, neckPos)` measured against the hero's
    own rot.y (`people_work +0x40`). Returns None when facing is
    unreadable, so callers suppress rather than guess."""
    if hero_facing is None:
        return None
    dx = target.x - hero_position.x
    dz = target.z - hero_position.z
    if dx == 0.0 and dz == 0.0:
        return 0.0
    face_x, face_z = -math.sin(hero_facing), -math.cos(hero_facing)
    horizontal = math.hypot(dx, dz)
    dot = (dx * face_x + dz * face_z) / horizontal
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def evaluate(inputs):
    unknown = []
    if not inputs.occupied:
        return TalkVerdict(False, REJECT_NOT_OCCUPIED, None, None, None)
    if inputs.is_hero:
        return TalkVerdict(False, REJECT_IS_HERO, None, None, None)
    if not inputs.displayed:
        return TalkVerdict(False, REJECT_NOT_DISPLAYED, None, None, None)
    if inputs.talk_flag_blocked:
        return TalkVerdict(False, REJECT_TALK_FLAG, None, None, None)
    if inputs.talk_start_type == TALK_START_TYPE_NEVER:
        return TalkVerdict(False, REJECT_TALK_START_TYPE, None, None, None)
    if not inputs.has_people_info:
        return TalkVerdict(False, REJECT_NO_PEOPLE_INFO, None, None, None)

    distance = threshold = error = None
    if inputs.hero_position is not None and inputs.neck_position is not None:
        distance = distance_3d(inputs.hero_position, inputs.neck_position)
        threshold = talk_threshold(
            inputs.hero_col_ball_size, inputs.talk_distance,
            inputs.npc_col_ball_size)
        error = facing_error_degrees(
            inputs.hero_position, inputs.hero_facing, inputs.neck_position)
    if distance is None:
        return TalkVerdict(
            False, "position unavailable", None, None, None, ("distance",))
    if distance > threshold:
        return TalkVerdict(False, REJECT_DISTANCE, distance, threshold, error)
    if error is None:
        unknown.append("facing")
    elif error > TALK_CONE_DEGREES:
        return TalkVerdict(False, REJECT_FACING, distance, threshold, error)
    if inputs.push_box_floor:
        # Gate 9's divisor is unresolved; report it rather than assume it
        # passes. A push-box floor is rare, so this costs nothing on
        # ordinary rooms and never fabricates a pass on the ones it hits.
        unknown.append("height band")
    if not inputs.wall_through:
        if inputs.wall_blocked is None:
            unknown.append("wall")
        elif inputs.wall_blocked:
            return TalkVerdict(False, REJECT_WALL, distance, threshold, error)
    if inputs.member_blocked:
        return TalkVerdict(False, REJECT_MEMBER, distance, threshold, error)
    if unknown:
        return TalkVerdict(
            False, "unverified gate", distance, threshold, error,
            tuple(unknown))
    return TalkVerdict(True, None, distance, threshold, error)
