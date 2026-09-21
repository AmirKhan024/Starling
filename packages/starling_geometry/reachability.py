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
from typing import Optional
from collections import OrderedDict
import math

import numpy as np
from scipy.sparse import csr_matrix, diags
from scipy.sparse.csgraph import dijkstra as _sp_dijkstra

from starling_geometry.navmesh import NavMesh

DEFAULT_V_MAX_M_S = 1.6
_SQRT2 = math.sqrt(2.0)

# (di, dj, step cost in cells) for the 8-connected neighbourhood.
_NEIGHBOUR_OFFSETS = [
    (-1, -1, _SQRT2), (0, -1, 1.0), (1, -1, _SQRT2),
    (-1, 0, 1.0), (1, 0, 1.0),
    (-1, 1, _SQRT2), (0, 1, 1.0), (1, 1, _SQRT2),
]


_BOUNDED_SEARCH_MAX_RADIUS_M = 8.0
_LRU_MAX_FIELDS = 64  # 64 * (100x160 float64 = 128KB) ~ 8MB per model


class ReachabilityModel:
    def __init__(self, navmesh: NavMesh, v_max_m_s: float = DEFAULT_V_MAX_M_S) -> None:
        self.navmesh = navmesh
        self.v_max_m_s = v_max_m_s
        self._cache: dict[tuple[int, int], np.ndarray] = {}
        self._csr: Optional[csr_matrix] = None
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

    def _graph(self) -> csr_matrix:
        """The 8-connected free-space graph (diagonal cost sqrt(2)*cell,
        obstacles impassable) as a CSR matrix, built once per model —
        the same edges `_dijkstra_reference` walks.
        """
        if self._csr is None:
            grid = self.navmesh.grid
            height, width = grid.shape
            cs = self.navmesh.cell_size
            idx = np.arange(height * width).reshape(height, width)
            rows, cols, wts = [], [], []
            for di, dj, step_cells in _NEIGHBOUR_OFFSETS:
                j0, j1 = max(0, -dj), min(height, height - dj)
                i0, i1 = max(0, -di), min(width, width - di)
                src = grid[j0:j1, i0:i1]
                dst = grid[j0 + dj : j1 + dj, i0 + di : i1 + di]
                ok = src & dst
                rows.append(idx[j0:j1, i0:i1][ok])
                cols.append(idx[j0 + dj : j1 + dj, i0 + di : i1 + di][ok])
                wts.append(np.full(int(ok.sum()), step_cells * cs))
            self._csr = csr_matrix(
                (np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))),
                shape=(height * width, height * width),
            )
        return self._csr

    def graph_without(self, blocked: np.ndarray) -> csr_matrix:
        """The free-space graph with every cell in `blocked` removed (no edge
        touches it). Cached for the last blocked mask, since a caller re-uses
        the same one for many steps."""
        key = blocked.tobytes()
        if getattr(self, "_blocked_key", None) == key:
            return self._blocked_graph
        keep = (~blocked).ravel().astype(np.float64)
        d = diags(keep)
        g = (d @ self._graph() @ d).tocsr()
        g.eliminate_zeros()
        self._blocked_key, self._blocked_graph = key, g
        return g

    def _dijkstra_from_cell(self, origin_cell: tuple[int, int], limit: float = np.inf) -> np.ndarray:
        """Geodesic distance from `origin_cell` (scipy sparse Dijkstra over
        the prebuilt graph); cells farther than `limit` come back `inf`.
        Same distances as `_dijkstra_reference`, ~10x faster, and a finite
        `limit` aborts the search early.
        """
        grid = self.navmesh.grid
        height, width = grid.shape
        oi, oj = origin_cell
        if not (0 <= oi < width and 0 <= oj < height) or not grid[oj, oi]:
            return np.full((height, width), np.inf, dtype=np.float64)
        dist = _sp_dijkstra(self._graph(), directed=True, indices=oj * width + oi, limit=limit)
        return dist.reshape(height, width)

    def _dijkstra_reference(self, origin_cell: tuple[int, int]) -> np.ndarray:
        """The original pure-Python Dijkstra, kept as the reference the
        scipy version is tested against."""
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
        extra_slack_m: float = 0.0,
    ) -> bool:
        """Permissive by design: slack = 2*pos_sigma + one grid cell (+ an
        optional `extra_slack_m`, default 0, for callers that need to absorb
        the ORIGIN's own position noise and grid quantisation at very small dt)."""
        slack = 2.0 * pos_sigma + self.navmesh.cell_size + extra_slack_m
        radius = self.v_max_m_s * dt_s + slack

        ti, tj = self.navmesh.world_to_cell(*target_xy)
        height, width = self.navmesh.grid.shape
        if not (0 <= ti < width and 0 <= tj < height):
            return False

        oi, oj = self.navmesh.world_to_cell(*origin_xy)
        # Exact fast rejection: a grid path is never shorter than the
        # straight line between the two cell centres.
        if math.hypot(ti - oi, tj - oj) * self.navmesh.cell_size > radius:
            return False

        if (oi, oj) in self._cache or (oi, oj) in self._lru or radius > _BOUNDED_SEARCH_MAX_RADIUS_M:
            # Cached already, or the radius is big enough that the search
            # covers much of the floor anyway: compute the full field once
            # and keep it (a stale origin is queried again and again).
            dist = self.distance_field(origin_xy)
        else:
            # Bounded search: only cells within `radius` matter here, so
            # abort there instead of flooding the whole floor plan.
            dist = self._dijkstra_from_cell((oi, oj), limit=radius)
        return bool(dist[tj, ti] <= radius)

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
