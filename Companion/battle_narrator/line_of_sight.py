"""Gate 11 of the talk predicate: is a wall between the player and the NPC?

`peopleTalkCheck` runs, for any character whose `talkWallThrough` bit is
clear:

    GScolsys2HitCollision(heroPos, neckPos, heroColBallSize, NULL)

and rejects the talk if it reports a hit. That is a swept capsule of the
HERO's own collision radius along the line to the neck reference.

`pathfinding._swept_points_blocked` is already exactly that primitive --
its own docstring notes it mirrors `GScolsys2HitCollision` with
`peopleInfoBiosGetColBallSize` -- so this module is a thin adapter that
owns the per-room geometry cache and nothing else. Reusing it rather than
writing a second sweep keeps one definition of "a wall blocks this".

Returns None, never a guess, when a room's collision data is unavailable:
the predicate reports the gate as UNKNOWN and the navigator declines to
promise an interaction rather than inventing a clear line.
"""
from .pathfinding import _swept_points_blocked, build_room_geometry


class RoomLineOfSight:
    def __init__(self, collision_dir, room_codes, triangle_loader,
                 walk_loader, logger):
        self.collision_dir = collision_dir
        self.room_codes = dict(room_codes)
        self.triangle_loader = triangle_loader
        self.walk_loader = walk_loader
        self.logger = logger
        self._geometry = {}
        self._walls = {}
        self._walks = {}

    def geometry(self, floor_id):
        if floor_id not in self._geometry:
            try:
                walls = self.triangle_loader(
                    self.collision_dir, self.room_codes, self._walls,
                    floor_id, self.logger)
                walks = self.walk_loader(
                    self.collision_dir, self.room_codes, self._walks,
                    floor_id, self.logger)
            except Exception as exc:
                self.logger.debug(
                    "LINE OF SIGHT geometry unavailable for 0x%X: %s",
                    floor_id, exc)
                self._geometry[floor_id] = None
                return None
            self._geometry[floor_id] = build_room_geometry(
                walks, walls, floor_id=floor_id)
        return self._geometry[floor_id]

    def blocked(self, floor_id, hero_position, target_position, radius):
        """True/False when the sweep ran, None when it could not."""
        geometry = self.geometry(floor_id)
        if geometry is None or hero_position is None or target_position is None:
            return None
        if radius <= 0.0:
            return None
        # Height band: the engine sweeps in 3D; this primitive tests walls
        # that reach a given height, so use the higher of the two ends --
        # a waist-high counter between the player and a clerk should count.
        height = max(hero_position.y, target_position.y)
        return _swept_points_blocked(
            geometry,
            (hero_position.x, hero_position.z),
            (target_position.x, target_position.z),
            height, radius)
