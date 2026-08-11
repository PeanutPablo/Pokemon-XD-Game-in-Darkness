"""Controlled-room, read-only forward collision prediction.

Diagnostic vertical slice only, not route guidance. It parses ordinary
room collision and tests whether a short hero-facing centerline intersects
a vertical triangle at the hero's current height.
"""
import math
import struct
from dataclasses import dataclass

from .speech import SpeechEventClass


@dataclass(frozen=True)
class CollisionTriangle:
    vertices: tuple
    normal: tuple
    collision_type: int
    entry_index: int


@dataclass(frozen=True)
class WalkTriangle:
    """One triangle from CCD slot +0x24 (`CCD_WALKMDL_HEAD`) -- the engine's
    OWN walkable-ground model, established 2026-07-31 by disassembling
    `GScolsys2WalkGetHeight`/`GScolsys2WalkGetLayer` (both called by real
    player locomotion in `heroMove.s` and NPC locomotion in `people.s`).
    Kept as its own dataclass rather than coerced into `CollisionTriangle`,
    which has no field for layer identity and would silently discard the
    one piece of information that disambiguates stacked terraces.

    `layer_a`/`layer_b` are the two 4-bit nibbles of triangle byte +0x31,
    exactly what `GScolsys2WalkGetLayer` returns for whichever candidate
    surface it selects. A triangle where `layer_a == layer_b` is an
    ordinary same-layer walking surface; where they differ, it is an
    explicit TRANSITION triangle joining those two layers (e.g. a ramp) --
    confirmed live: the exact XZ/Y position where the project owner started
    climbing the `M3_out` terrace sits on a `layer_a=0, layer_b=1` triangle.

    `raw_metadata_byte` is triangle byte +0x30, untouched. In every `M3_out`
    triangle sampled it was `0xFF` (both nibbles the engine's own 0xF
    sentinel/"no value" marker, per the `GScolsys2WalkGetHeight`
    disassembly) -- other rooms show non-sentinel values whose meaning is
    not yet decoded. Preserved raw rather than discarded so a future
    investigation can decode it without re-parsing every `.ccd` file.

    `entry_index` is the top-level CCD entry (object) this triangle
    belongs to -- the same index `GScolsys2GetObjEnable`/`SetObjEnable`
    operate on (see `collision_object_enable.py`), so it doubles as this
    triangle's (currently statically-scoped -- see that module's own
    docstring) enable-state identity."""
    vertices: tuple
    normal: tuple
    layer_a: int
    layer_b: int
    raw_metadata_byte: int
    entry_index: int


@dataclass(frozen=True)
class ForwardCollision:
    distance: float
    point: tuple
    triangle: CollisionTriangle


def parse_environment_triangles(data):
    """Parse CCD slot +0x28, `CCD_HITMDL_HEAD` -- obstacle/wall geometry
    used for movement blocking and forward-collision prediction. This is
    NOT walkable-ground data (see `parse_walk_model_triangles`, CCD slot
    +0x24, for that) -- do not repurpose this function's output as a floor
    source; that was this project's own root-cause bug, corrected
    2026-07-31 (see `WORLD_NAVIGATION_ARCHITECTURE.md`)."""
    if len(data) < 8:
        raise ValueError("CCD header is truncated")

    def u32(offset):
        if offset < 0 or offset + 4 > len(data):
            raise ValueError(f"CCD pointer outside file at 0x{offset:X}")
        return struct.unpack_from(">I", data, offset)[0]

    list_start = u32(0)
    entry_count = u32(4)
    if entry_count > 4096 or list_start + entry_count * 0x40 > len(data):
        raise ValueError("CCD top-level table is invalid")
    triangles = []
    for entry_index in range(entry_count):
        entry = list_start + entry_index * 0x40
        pointer = u32(entry + 0x28)
        if pointer == 0:
            continue
        triangle_start = u32(pointer)
        count = u32(pointer + 4)
        if count > 100000 or triangle_start + count * 0x34 > len(data):
            raise ValueError("CCD triangle list is invalid")
        for index in range(count):
            offset = triangle_start + index * 0x34
            values = struct.unpack_from(">12f", data, offset)
            if not all(math.isfinite(value) for value in values):
                raise ValueError("CCD triangle contains a non-finite value")
            vertices = tuple(
                tuple(values[base:base + 3]) for base in (0, 3, 6)
            )
            triangles.append(CollisionTriangle(
                vertices=vertices,
                normal=tuple(values[9:12]),
                collision_type=struct.unpack_from(">H", data, offset + 0x30)[0],
                entry_index=entry_index,
            ))
    return tuple(triangles)


WALK_MODEL_SLOT = 0x24
"""CCD top-level entry offset for `CCD_WALKMDL_HEAD` -- established via
`_offsetCCD__FP12CCD_FILEHEAD` (relocates six model pointers per 0x40-byte
entry: +0x24/+0x28/+0x2C/+0x30/+0x34/+0x38) and confirmed twice independently
by `drawWalkMdl(CCD_WALKMDL_HEAD*)` being called with `lwz r3, 0x24(r29)` in
`GScolsys2Draw.s`, and by `GScolsys2WalkGetHeight` itself reading
`lwz r29, 0x24(r30)`."""


def parse_walk_model_triangles(data):
    """Parse CCD slot +0x24, `CCD_WALKMDL_HEAD` -- the engine's own
    walkable-ground model. Deliberately a full, independent parse (not a
    shared helper with `parse_environment_triangles`) so a bug in one can
    never silently affect the other -- these two slots have carried this
    project's entire walkability story and its complete failure mode
    respectively; the risk of a shared-code mistake outweighs the small
    duplication.

    Every triangle is kept regardless of its normal -- the walk model
    itself contains a mix of near-horizontal walking surfaces and steeper
    connector geometry (confirmed by a 177-room scan: slot +0x24 contains
    triangles across the full normal range, not just upward-facing ones),
    and `GScolsys2WalkGetHeight`'s own disassembly applies no normal-angle
    filter when scanning -- it just point-in-polygon tests every triangle
    and lets the plane-height division naturally produce nothing useful for
    a near-vertical one (see `pathfinding.walk_height_candidates`, which
    mirrors that by skipping triangles whose normal is too close to
    vertical to yield a meaningful height, not by excluding them here at
    parse time)."""
    if len(data) < 8:
        raise ValueError("CCD header is truncated")

    def u32(offset):
        if offset < 0 or offset + 4 > len(data):
            raise ValueError(f"CCD pointer outside file at 0x{offset:X}")
        return struct.unpack_from(">I", data, offset)[0]

    list_start = u32(0)
    entry_count = u32(4)
    if entry_count > 4096 or list_start + entry_count * 0x40 > len(data):
        raise ValueError("CCD top-level table is invalid")
    triangles = []
    for entry_index in range(entry_count):
        entry = list_start + entry_index * 0x40
        pointer = u32(entry + WALK_MODEL_SLOT)
        if pointer == 0:
            continue
        triangle_start = u32(pointer)
        count = u32(pointer + 4)
        if count > 100000 or triangle_start + count * 0x34 > len(data):
            raise ValueError("CCD walk-model triangle list is invalid")
        for index in range(count):
            offset = triangle_start + index * 0x34
            values = struct.unpack_from(">12f", data, offset)
            if not all(math.isfinite(value) for value in values):
                # Skip this ONE triangle rather than failing the whole file.
                # Measured 2026-08-02 across all 177 `.ccd` files: exactly
                # three rooms (`M6_pc_1F`, `M6_tower_3F`, `M6_tower_4F`)
                # contain such triangles, and in every case the three
                # VERTICES are valid real coordinates while only the NORMAL
                # is NaN (raw `ffc00000 ffc00000 ffc00000`) -- the signature
                # of a degenerate triangle whose collinear/coincident points
                # give a zero-length cross product that NaNs when
                # normalised. It is 1-2 triangles out of 179-875 (0.1-0.6%).
                # The engine's own `GScolsys2WalkGetHeight` would never
                # match such a triangle either (a degenerate triangle fails
                # point-in-polygon, and `pathfinding` additionally skips
                # near-vertical normals), so dropping it loses nothing real
                # -- whereas raising cost those three rooms ALL routing,
                # discarding 800+ perfectly good triangles apiece.
                #
                # Structural problems (bad pointers, impossible counts) still
                # raise above; this leniency is deliberately scoped to a
                # single geometrically-meaningless triangle.
                continue
            vertices = tuple(
                tuple(values[base:base + 3]) for base in (0, 3, 6)
            )
            metadata_byte = data[offset + 0x30]
            layer_byte = data[offset + 0x31]
            triangles.append(WalkTriangle(
                vertices=vertices,
                normal=tuple(values[9:12]),
                layer_a=(layer_byte >> 4) & 0xF,
                layer_b=layer_byte & 0xF,
                raw_metadata_byte=metadata_byte,
                entry_index=entry_index,
            ))
    return tuple(triangles)


def _cross(ax, az, bx, bz):
    return ax * bz - az * bx


def ray_segment_distance(origin, direction, length, start, end):
    """Return ray distance for a 2-D segment intersection, or None.

    Public (not `predict_forward_collision`-private) because `pathfinding.py`
    reuses this exact math for tile-adjacency wall checks: a segment-vs-segment
    test is just this same ray form with `direction` = normalized(end - start)
    of the tile-to-tile segment and `length` = its distance."""
    rx, rz = direction[0] * length, direction[1] * length
    sx, sz = end[0] - start[0], end[1] - start[1]
    denominator = _cross(rx, rz, sx, sz)
    if abs(denominator) < 1e-7:
        return None
    qx, qz = start[0] - origin[0], start[1] - origin[1]
    ray_fraction = _cross(qx, qz, sx, sz) / denominator
    segment_fraction = _cross(qx, qz, rx, rz) / denominator
    if (-1e-7 <= ray_fraction <= 1.0 + 1e-7 and
            -1e-7 <= segment_fraction <= 1.0 + 1e-7):
        return max(0.0, ray_fraction * length)
    return None


def predict_forward_collision(triangles, pose, distance=12.0):
    """Find the nearest vertical CCD triangle hit by a short forward ray."""
    if distance <= 0:
        raise ValueError("forward distance must be positive")
    direction = (-math.sin(pose.yaw), -math.cos(pose.yaw))
    origin = (pose.position.x, pose.position.z)
    best = None
    for triangle in triangles:
        if abs(triangle.normal[1]) > 0.35:
            continue
        ys = [vertex[1] for vertex in triangle.vertices]
        if pose.position.y < min(ys) - 0.25 or pose.position.y > max(ys) + 0.25:
            continue
        projected = [(vertex[0], vertex[2]) for vertex in triangle.vertices]
        pairs = ((0, 1), (1, 2), (2, 0))
        a, b = max(
            pairs,
            key=lambda pair: math.dist(projected[pair[0]], projected[pair[1]])
        )
        if math.dist(projected[a], projected[b]) < 1e-5:
            continue
        hit_distance = ray_segment_distance(
            origin, direction, distance, projected[a], projected[b]
        )
        if hit_distance is None:
            continue
        point = (
            origin[0] + direction[0] * hit_distance,
            pose.position.y,
            origin[1] + direction[1] * hit_distance,
        )
        hit = ForwardCollision(hit_distance, point, triangle)
        if best is None or hit.distance < best.distance:
            best = hit
    return best


class ControlledRoomCollisionProbe:
    """Foreground-hotkey diagnostic for exactly one room and one CCD."""

    def __init__(
        self, floor_id, ccd_path, pose_source, hotkey, speech, logger,
        forward_distance=12.0,
    ):
        self.floor_id = floor_id
        self.pose_source = pose_source
        self.hotkey = hotkey
        self.speech = speech
        self.logger = logger
        self.forward_distance = forward_distance
        self.triangles = parse_environment_triangles(ccd_path.read_bytes())

    def poll_once(self, current_floor_id, context_valid):
        fired = self.hotkey.poll()
        if not fired or not context_valid:
            return
        if current_floor_id != self.floor_id:
            text = "Forward collision probe is unavailable in this room."
            self.speech.emit(
                SpeechEventClass.ENTITY_NAV, text,
                deduplicate=False, interrupt=True,
            )
            self.logger.info(
                "COLLISION PROBE unsupported floor=%s expected=%s",
                current_floor_id, self.floor_id,
            )
            return
        pose = self.pose_source.player_pose()
        hit = predict_forward_collision(
            self.triangles, pose, self.forward_distance
        )
        if hit is None:
            text = f"Forward clear for {self.forward_distance:g}."
            self.logger.info(
                "COLLISION PROBE clear floor=%s x=%.3f y=%.3f z=%.3f "
                "yaw=%.5f distance=%.2f",
                current_floor_id, pose.position.x, pose.position.y,
                pose.position.z, pose.yaw, self.forward_distance,
            )
        else:
            text = f"Wall ahead, distance {hit.distance:.1f}."
            self.logger.info(
                "COLLISION PROBE hit floor=%s x=%.3f y=%.3f z=%.3f "
                "yaw=%.5f distance=%.3f point=(%.3f,%.3f,%.3f) "
                "entry=%s type=%s",
                current_floor_id, pose.position.x, pose.position.y,
                pose.position.z, pose.yaw, hit.distance, *hit.point,
                hit.triangle.entry_index, hit.triangle.collision_type,
            )
        self.speech.emit(
            SpeechEventClass.ENTITY_NAV, text,
            deduplicate=False, interrupt=True,
        )