"""Read the world position of a model's joint -- specifically the neck
joint the game's talk check measures to.

`peopleGetNeckPos` is:

    peopleGetPartsPos(group, res, peopleInfoBiosGetNeckIndex(info), out)
    out.y = peopleBiosGetPosPtr(actor).y      <- Y comes from the ACTOR base

and `peopleGetPartsPos` with a non-negative index is:

    GSmodelGetPart(model, index) -> GSpartGetTransform(part, out, 0, 0)

`GSpartGetTransform` calls `GSmodelUpdate` and `HSD_JObjSetupMatrixSub`,
which an external read-only companion cannot call. It does not need to:
those calls exist to REFRESH the joint's world matrix, and the game
refreshes it every rendered frame anyway. The value they produce is read
straight back out of the JObj:

    .L_80100394:  lfs f29, 0x50(r30)
                  lfs f28, 0x60(r30)
                  lfs f27, 0x70(r30)

which is the translation column of a 3x4 row-major matrix based at +0x44
(0x44+0x0C, 0x54+0x0C, 0x64+0x0C). So the neck world position is readable
without calling anything.

JObj layout, from `HSD_JObjWalkTree0` (0x80252ED0):

    +0x08  next sibling
    +0x0C  parent
    +0x10  first child
    +0x14  flags   (bit 19 / 0x1000: do not descend into children)
    +0x38  cached position, used instead of the matrix WHILE BLENDING
    +0x44  world matrix; translation at +0x50 / +0x60 / +0x70

Part index -> JObj is `GSpartGetJObjPtr`, a pre-order walk counting every
visited node from 0. `GSmodelGetPart` adds 1 to the requested index when
the model's own flags carry 0x00020000.

Three corrections, 2026-08-09
-----------------------------
The first live samples produced neck offsets of 0.18, 0.20, 0.50, **11.32**
and **40.92** against a 4.0 collision ball, one actor moving 0.50 -> 11.32
in five seconds. Re-tracing the chain found three divergences from the
engine, all of which this module now follows exactly.

**1. The walk must not leave the root's subtree.** `GSpartGetJObjPtr`
calls `HSD_JObjWalkTree` (0x80252E40), not `HSD_JObjWalkTree0`, and the
two differ in exactly one way that matters: `HSD_JObjWalkTree` visits the
root, then iterates `root->child` -- it **never reads `root->next`**. This
module used to push every node's sibling including the root's, so once an
index ran past the end of this model's hierarchy the walk continued into
whatever JObj followed it in memory and returned a joint belonging to a
DIFFERENT MODEL. That is the shape of a 40-unit offset. The engine returns
NULL there, and so does this now.

**2. The blend position is only for a blending model.**
`GSpartGetTransform` selects `+0x38/+0x3C/+0x40` only inside the
`GSmodelIsBlending(model)` branch; with blending off it reads
`+0x50/+0x60/+0x70` whatever the joint's own bits say. This module applied
the blend path on the joint flags alone. `GSmodelIsBlending` is
`model_flags & 0x80` -- the same bit that selects the render JObj, which
is consistent: a blending model has its blended tree at `+0x14`.

**3. A cached matrix genuinely can be stale, and the engine says when.**
Before reading, `GSpartGetTransform` calls `GSmodelUpdate`, and then
recomputes the joint outright via `HSD_JObjSetupMatrixSub` when
`!(jobj_flags & 0x00800000) && (jobj_flags & 0x40)`. A read-only companion
cannot recompute. Reading the matrix anyway in that state is reading a
value the engine itself considers invalid, so this now returns None and
lets the caller fall back.

No parent composition is needed on this path: `peopleGetPartsPos` calls
`GSpartGetTransform(part, out, 0, 0)`, and both trailing zero arguments
skip the `parentList` block entirely -- the value stored to `out` is the
joint's own cached world translation and nothing else.

**Status: statically traced against the engine, live-validation pending.**
Every consumer must tolerate `None`, and `LiveNPCEntitySource` keeps its
collision-ball sanity bound on top of this as corruption protection.
"""
from dataclasses import dataclass, replace
import math
import struct

from .memory import MemoryError as GameMemoryError
from .npc_beacons import Position


@dataclass(frozen=True)
class NeckResolution:
    """Everything needed to explain a neck offset without re-reading it."""

    model: object = None
    requested_index: object = None
    part_index: object = None
    """`requested_index` plus GSmodelGetPart's +1 bias, when the model's
    flags carry 0x00020000."""
    root: object = None
    jobj: object = None
    model_flags: object = None
    blending: object = None
    source: object = None
    """"matrix", "blend", "actor base", or None when unresolved."""
    position: object = None
    base_position: object = None
    reason: object = None
    """Why `position` is None. Present only on failure."""

    @property
    def offset(self):
        if self.position is None or self.base_position is None:
            return None
        return math.hypot(
            self.position.x - self.base_position.x,
            self.position.z - self.base_position.z)


JOBJ_NEXT_OFFSET = 0x08
JOBJ_CHILD_OFFSET = 0x10
JOBJ_FLAGS_OFFSET = 0x14
JOBJ_NO_DESCEND_FLAG = 0x00001000
JOBJ_BLEND_FLAGS = 0x00600000
JOBJ_BLEND_POSITION_OFFSET = 0x38
JOBJ_MATRIX_X_OFFSET = 0x50
JOBJ_MATRIX_Y_OFFSET = 0x60
JOBJ_MATRIX_Z_OFFSET = 0x70

JOBJ_MATRIX_TRUSTED_FLAG = 0x00800000
JOBJ_MATRIX_DIRTY_FLAG = 0x00000040
"""`GSpartGetTransform`'s own staleness test, in its own terms:

    if !(flags & 0x00800000) && (flags & 0x40): HSD_JObjSetupMatrixSub(jobj)

i.e. the cached matrix is REBUILT before being read whenever the first bit
is clear and the second set. A read-only reader cannot rebuild it, so that
combination means "this matrix is not currently valid" and resolves to
None rather than to a stale position."""

MODEL_FLAGS_OFFSET = 0x00
MODEL_RENDER_JOBJ_FLAG = 0x00000080
MODEL_BLENDING_FLAG = 0x00000080
"""`GSmodelIsBlending` is `extrwi r3, model_flags, 1, 24` -- bit 24 from
the MSB, i.e. 0x80. The same bit `modelGetRenderJObj` tests, which is
consistent rather than a coincidence: a blending model keeps its blended
hierarchy at `+0x14`."""
MODEL_JOBJ_OFFSET = 0x0C
MODEL_RENDER_JOBJ_OFFSET = 0x14
MODEL_PART_INDEX_BIAS_FLAG = 0x00020000

MAX_JOBJ_NODES = 512
"""Hard bound on the pre-order walk. A character hierarchy is a few dozen
joints; anything past this means a corrupt or mid-write pointer graph, and
walking it further would be reading noise."""


class NeckPositionResolver:
    """Resolves a live actor's neck world position. Returns None for any
    read failure -- never raises into a caller's poll loop, and never
    substitutes a different position silently."""

    def __init__(self, memory, profile):
        self.memory, self.profile = memory, profile
        self.failures = 0
        self.last_failure = None

    def _valid(self, address):
        return bool(address) and (
            self.profile.mem1_start <= address < self.profile.mem1_end)

    def _float(self, address, label):
        value = struct.unpack(
            ">f", self.memory.bytes(address, 4, label, 4))[0]
        if not math.isfinite(value):
            raise GameMemoryError(f"{label} is non-finite")
        return value

    def _root_jobj(self, model):
        flags = self.memory.u32(model + MODEL_FLAGS_OFFSET, "model flags")
        offset = (MODEL_RENDER_JOBJ_OFFSET if flags & MODEL_RENDER_JOBJ_FLAG
                  else MODEL_JOBJ_OFFSET)
        return self.memory.u32(model + offset, "model render JObj"), flags

    def _children(self, node, flags):
        if flags & JOBJ_NO_DESCEND_FLAG:
            return 0
        return self.memory.u32(node + JOBJ_CHILD_OFFSET, "JObj child")

    def _find_part(self, root, target_index):
        """`GSpartGetJObjPtr` -> `HSD_JObjWalkTree(root, cb)`: visit the
        root, then walk each child's subtree, counting every visited node
        from zero.

        The root's OWN sibling chain is never followed. `HSD_JObjWalkTree`
        reads `root->child` and recurses with `HSD_JObjWalkTree0`; nothing
        in either function reads `root->next`. Following it -- which this
        did until 2026-08-09 -- turns an out-of-range index from a clean
        miss into a joint belonging to whatever model happens to sit next
        in the hierarchy, which is how a neck ended up 40.92 units from its
        own body. An index past the end of this model now returns None,
        exactly as the engine does."""
        visited = 0
        guard = 0
        # Each stack entry is a node whose subtree is still to be walked,
        # in the order HSD_JObjWalkTree0 would recurse. Seeded with the
        # ROOT ALONE; the root's siblings are deliberately unreachable.
        stack = [root]
        while stack:
            node = stack.pop()
            if not self._valid(node):
                continue
            guard += 1
            if guard > MAX_JOBJ_NODES:
                raise GameMemoryError("JObj walk exceeded the node bound")
            if visited == target_index:
                return node
            visited += 1
            flags = self.memory.u32(node + JOBJ_FLAGS_OFFSET, "JObj flags")
            child = self._children(node, flags)
            if not child:
                continue
            # The parent's loop iterates `child->next`; each child's own
            # subtree is walked before the next sibling. Collect the chain
            # and push it reversed so the first child pops first.
            siblings = []
            cursor = child
            while cursor and self._valid(cursor):
                siblings.append(cursor)
                guard += 1
                if guard > MAX_JOBJ_NODES:
                    raise GameMemoryError("JObj sibling chain exceeded the bound")
                cursor = self.memory.u32(
                    cursor + JOBJ_NEXT_OFFSET, "JObj next")
            stack.extend(reversed(siblings))
        return None

    def _jobj_position(self, node, model_flags):
        """`GSpartGetTransform`'s read, branch for branch.

        Returns (Position, source) or raises. `source` names which of the
        engine's three cases produced it, for the diagnostic."""
        flags = self.memory.u32(node + JOBJ_FLAGS_OFFSET, "JObj flags")
        if model_flags & MODEL_BLENDING_FLAG:
            if flags & JOBJ_BLEND_FLAGS:
                base = node + JOBJ_BLEND_POSITION_OFFSET
                return Position(
                    self._float(base, "JObj blend x"),
                    self._float(base + 4, "JObj blend y"),
                    self._float(base + 8, "JObj blend z")), "blend"
        elif (not flags & JOBJ_MATRIX_TRUSTED_FLAG
                and flags & JOBJ_MATRIX_DIRTY_FLAG):
            # The engine would rebuild this matrix before reading it. We
            # cannot, and reading it anyway means reporting a position the
            # engine itself does not consider current.
            raise GameMemoryError(
                f"JObj matrix needs a rebuild (flags 0x{flags:08X})")
        return Position(
            self._float(node + JOBJ_MATRIX_X_OFFSET, "JObj matrix x"),
            self._float(node + JOBJ_MATRIX_Y_OFFSET, "JObj matrix y"),
            self._float(node + JOBJ_MATRIX_Z_OFFSET, "JObj matrix z")), "matrix"

    def resolve(self, model, neck_index, base_position):
        """Full result, for the diagnostic: position plus every input the
        brief requires to explain an offset -- JObj pointer, requested and
        biased part index, which matrix source was used, and why a
        resolution failed when it did."""
        detail = NeckResolution(
            model=model, requested_index=neck_index,
            base_position=base_position)
        if base_position is None:
            return replace(detail, reason="no base position")
        if neck_index is None or neck_index < 0:
            # The engine's own "no neck joint" case: `peopleGetPartsPos`
            # takes the actor's base position for a negative index. Not a
            # degradation -- it is the answer.
            return replace(
                detail, position=base_position, source="actor base",
                reason="negative neck index")
        if not self._valid(model):
            return replace(detail, reason="model pointer outside MEM1")
        try:
            root, model_flags = self._root_jobj(model)
            detail = replace(detail, root=root, model_flags=model_flags,
                             blending=bool(model_flags & MODEL_BLENDING_FLAG))
            if not self._valid(root):
                return replace(detail, reason="root JObj outside MEM1")
            index = neck_index + (
                1 if model_flags & MODEL_PART_INDEX_BIAS_FLAG else 0)
            detail = replace(detail, part_index=index)
            node = self._find_part(root, index)
            if node is None:
                return replace(
                    detail,
                    reason=f"part {index} is past the end of this model")
            detail = replace(detail, jobj=node)
            joint, source = self._jobj_position(node, model_flags)
        except GameMemoryError as exc:
            self.failures += 1
            self.last_failure = str(exc)
            return replace(detail, reason=str(exc))
        return replace(
            detail, source=source,
            position=Position(joint.x, base_position.y, joint.z))

    def neck_position(self, model, neck_index, base_position):
        """The game's own talk target: neck-joint X/Z with the ACTOR's base
        Y, exactly as `peopleGetNeckPos` assembles it. None when it cannot
        be resolved; callers fall back to the actor position."""
        return self.resolve(model, neck_index, base_position).position
