"""Which part of an interaction region the player is being sent to.

**One decision, used by both speech and routing.** The invariant this module
exists to hold is that the component entity navigation *says* is the one the
route is actually *targeting*. Before this, the two were derived
independently -- speech took the Euclidean-nearest point over the whole
region, routing took whichever arrival tile the graph could reach -- so for
a region with several volumes they could name different places, and the
player was told to walk toward a doorway the route was not using.

Three rules, in order (project owner, 2026-08-12):

1. if the player is inside a component, that is the component;
2. otherwise choose among components the navigation graph can actually
   reach, preferring the lowest ordinary route cost;
3. never prefer a nearer component that is wall-separated over a farther one
   that is reachable.

If no component is reachable, this says so, and the caller must not report
`VERIFIED` routing.

Reachability is supplied by the caller as a `cost` callback rather than
computed here, because this module owns geometry and selection, not the
navigation graph. When no callback is available the selector degrades to
nearest-point -- the pre-existing behaviour -- rather than guessing.
"""
import math

from .region_geometry import Region

SWITCH_MARGIN = 8.0
"""How much better a rival component must be, in world units, before the
selection moves to it.

Hysteresis exists because the nearest point of a region moves continuously
as the player walks, and two candidates are equally good exactly on the
midpoint between them. Without a margin the beacon flips between two
doorway edges, or between two volumes of the same region, on sub-unit
drift -- the same class of thrashing the committed waypoint sequence exists
to prevent for routing (WORLD_NAVIGATION_ARCHITECTURE.md 6a).

One tile. Large enough that ordinary walking jitter cannot cross it, small
enough that a genuine change of approach still switches promptly. Not tuned
by ear; chosen to match the lattice the routing graph already uses."""


class RegionTargetSelector:
    """Remembers which component of each region is currently being targeted.

    One selector per entity source, keyed by region index, so the choice
    persists across polls -- which is what makes hysteresis possible at all.
    """

    def __init__(self, switch_margin=SWITCH_MARGIN):
        self.switch_margin = switch_margin
        self._chosen = {}

    def clear(self, reason=None):
        self._chosen.clear()

    def select(self, region, x, z, cost=None):
        """Choose a component of `region` for a player at `(x, z)`.

        `cost(component)` returns the ordinary route cost to that component,
        `None` if the graph cannot reach it, or the callback itself may be
        `None` when no graph is available.

        Returns `(component, inside, reachable)`:
        `inside` is True when the player already stands in the component,
        and `reachable` is False only when a cost callback was supplied and
        reported every component unreachable -- the case where the caller
        must not claim a verified route."""
        components = region.components()
        if len(components) == 1 and cost is None:
            return components[0], _inside(components[0], x, z), True

        # 1. Already inside one? That settles it, regardless of cost --
        #    walking out of a trigger to approach it "properly" is absurd.
        for component in components:
            if _inside(component, x, z):
                self._chosen[region.index] = component
                return component, True, True

        scored = []
        any_reachable = False
        for component in components:
            distance = component.distance(x, z)
            if distance is None:
                continue
            if cost is None:
                scored.append((distance, distance, component))
                continue
            route = cost(component)
            if route is None:
                continue          # 3. wall-separated: never a candidate
            any_reachable = True
            scored.append((route, distance, component))
        if not scored:
            # Nothing reachable. Fall back to nearest for SPEECH -- the
            # player still deserves a direction -- but say so, so the caller
            # can refuse to call it a route.
            fallback = min(
                (c for c in components if c.distance(x, z) is not None),
                key=lambda c: c.distance(x, z), default=components[0])
            self._chosen[region.index] = fallback
            return fallback, False, False

        # 2. Lowest ordinary route cost, with hysteresis against the
        #    component already being used.
        scored.sort(key=lambda item: (item[0], item[1]))
        best_score, best_distance, best = scored[0]
        current = self._chosen.get(region.index)
        if current is not None:
            for score, distance, component in scored:
                if not _same(component, current):
                    continue
                # Keep the current choice unless the rival is materially
                # better. Compared on DISTANCE, which is what the player
                # hears; route cost decides which candidates exist at all.
                if distance <= best_distance + self.switch_margin:
                    self._chosen[region.index] = component
                    return component, False, True or any_reachable
                break
        self._chosen[region.index] = best
        return best, False, True


def _inside(component, x, z):
    distance = component.distance(x, z)
    return distance is not None and distance <= 0.0


def _same(a, b):
    return a.triangles == b.triangles
