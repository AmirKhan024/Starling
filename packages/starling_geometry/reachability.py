"""starling_geometry/reachability.py
--------------------------------------
Speed-bounded geodesic reachability over the navmesh (D-09,
STARLING_BUILD_STATE.md Appendix A.2). Implements *exactly* the algorithm
specified there — do not invent a different one:

    precompute (once, per FOV exit point e):
        D_e = geodesic distance field over the free-space grid, via
              Dijkstra (8-connected, diagonal cost sqrt(2)*cell,
              obstacles impassable)

    query reachable_set(e, dt, v_max=1.6):
        return D_e <= v_max*dt          # boolean mask, O(1) threshold

Being slightly PERMISSIVE is correct, not a bug — say this loudly because
it is the one design choice in this module a reviewer is most likely to
push back on: a false exclusion in a safety system is far worse than a
false inclusion, because it tells a search team a person cannot be
somewhere they actually are. Every query here adds slack (`pos_sigma` and
at least one grid cell) to the raw Dijkstra distance rather than reporting
it unpadded.
"""

from __future__ import annotations

import heapq
from collections import OrderedDict
import math

import numpy as np

from starling_geometry.navmesh import NavMesh

DEFAULT_V_MAX_M_S = 1.6
_SQRT2 = math.sqrt(2.0)

# (di, dj, step cost in cells) for the 8-connected neighbourhood.
_NEIGHBOUR_OFFSETS = [
    (-1, -1, _SQRT2), (0, -1, 1.0), (1, -1, _SQRT2),
    (-1, 0, 1.0), (1, 0, 1.0),
    (-1, 1, _SQRT2), (0, 1, 1.0), (1, 1, _SQRT2),
]


_LRU_MAX_FIELDS = 64  # 64 * (100x160 float64 = 128KB) ~ 8MB per model


class ReachabilityModel:
    def __init__(self, navmesh: NavMesh, v_max_m_s: float = DEFAULT_V_MAX_M_S) -> None:
        self.navmesh = navmesh
        self.v_max_m_s = v_max_m_s
        self._cache: dict[tuple[int, int], np.ndarray] = {}
        # Bounded LRU of fields for origins that were NOT `precompute`d.
        # Without it every plausibility check re-ran a pure-Python
        # Dijkstra (~30 ms on a 100x160 grid), which wedged a node's main
        # loop when a post-partition backlog arrived. The precomputed
        # `_cache` above is never evicted.
        self._lru: "OrderedDict[tuple[int, int], np.ndarray]" = OrderedDict()

    def distance_field(self, origin_xy: tuple[float, float]) -> np.ndarray:
        """Geodesic distance (metres) from `origin_xy` to every cell,
        `inf` where unreachable. Uses the `precompute`d cache when this
        origin's cell has one.
        """
        origin_cell = self.navmesh.world_to_cell(*origin_xy)
        if origin_cell in self._cache:
            return self._cache[origin_cell]
        cached = self._lru.get(origin_cell)
        if cached is not None:
            self._lru.move_to_end(origin_cell)
            return cached
        field = self._dijkstra_from_cell(origin_cell)
        self._lru[origin_cell] = field
        if len(self._lru) > _LRU_MAX_FIELDS:
            self._lru.popitem(last=False)
        return field

    def _dijkstra_from_cell(self, origin_cell: tuple[int, int]) -> np.ndarray:
        grid = self.navmesh.grid
        height, width = grid.shape
        cell_size = self.navmesh.cell_size

        dist = np.full((height, width), np.inf, dtype=np.float64)
        oi, oj = origin_cell
        if not (0 <= oi < width and 0 <= oj < height) or not grid[oj, oi]:
            return dist  # origin isn't free space: nothing reachable

        dist[oj, oi] = 0.0
        heap: list[tuple[float, int, int]] = [(0.0, oi, oj)]
        while heap:
            d, i, j = heapq.heappop(heap)
            if d > dist[j, i]:
                continue  # stale heap entry
            for di, dj, step_cells in _NEIGHBOUR_OFFSETS:
                ni, nj = i + di, j + dj
                if not (0 <= ni < width and 0 <= nj < height) or not grid[nj, ni]:
                    continue
                nd = d + step_cells * cell_size
                if nd < dist[nj, ni]:
                    dist[nj, ni] = nd
                    heapq.heappush(heap, (nd, ni, nj))
        return dist

    def reachable_set(
        self, origin_xy: tuple[float, float], dt_s: float, extra_slack_m: float = 0.0
    ) -> np.ndarray:
        """`distance_field(origin_xy) <= v_max*dt_s + extra_slack_m`, a
        boolean mask over the navmesh grid.
        """
        dist = self.distance_field(origin_xy)
        radius = self.v_max_m_s * dt_s + extra_slack_m
        return dist <= radius

    def is_reachable(
        self,
        origin_xy: tuple[float, float],
        target_xy: tuple[float, float],
        dt_s: float,
        pos_sigma: float = 0.0,
    ) -> bool:
        """Permissive by design: slack = 2*pos_sigma + one grid cell."""
        slack = 2.0 * pos_sigma + self.navmesh.cell_size
        mask = self.reachable_set(origin_xy, dt_s, extra_slack_m=slack)

        ti, tj = self.navmesh.world_to_cell(*target_xy)
        height, width = mask.shape
        if not (0 <= ti < width and 0 <= tj < height):
            return False
        return bool(mask[tj, ti])

    def precompute(self, origin_points: list[tuple[float, float]]) -> None:
        """Cache a distance field for each FOV exit point (keyed by its
        rounded/snapped grid cell), so runtime queries against these
        origins are an O(1) threshold on a cached array rather than a
        fresh Dijkstra search each time.
        """
        for origin_xy in origin_points:
            cell = self.navmesh.world_to_cell(*origin_xy)
            if cell not in self._cache:
                self._cache[cell] = self._dijkstra_from_cell(cell)
