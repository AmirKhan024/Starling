"""starling_world/pathing.py
----------------------------
Walking paths for the world's people: 8-connected A* over the navmesh's
free-space grid, planned on a copy with obstacles inflated by a body
radius (so nobody brushes a rack face), then shortened by greedy
line-of-sight "string pulling" so people walk straight lines between
corners instead of grid staircases.
"""

from __future__ import annotations

import heapq
import math
from typing import Optional

import numpy as np
from scipy import ndimage
from starling_geometry.navmesh import NavMesh

_SQRT2 = math.sqrt(2.0)


class PathPlanner:
    def __init__(self, navmesh: NavMesh, clearance_m: float = 0.35) -> None:
        self.navmesh = navmesh
        blocked = ~navmesh.grid
        r = max(1, int(round(clearance_m / navmesh.cell_size)))
        yy, xx = np.mgrid[-r : r + 1, -r : r + 1]
        disk = (xx * xx + yy * yy) <= r * r
        inflated = ndimage.binary_dilation(blocked, structure=disk)
        # The building's own walls are not obstacles to inflate against at
        # doorways: keep the outermost free cells usable.
        self.free = navmesh.grid & ~inflated
        self._fallback = navmesh.grid

    def _cell(self, xy: tuple[float, float]) -> tuple[int, int]:
        i, j = self.navmesh.world_to_cell(*xy)
        h, w = self.free.shape
        return min(max(i, 0), w - 1), min(max(j, 0), h - 1)

    def _nearest_free(self, cell: tuple[int, int], grid: np.ndarray) -> Optional[tuple[int, int]]:
        i0, j0 = cell
        h, w = grid.shape
        for r in range(0, 12):
            best = None
            for dj in range(-r, r + 1):
                for di in range(-r, r + 1):
                    if max(abs(di), abs(dj)) != r:
                        continue
                    i, j = i0 + di, j0 + dj
                    if 0 <= i < w and 0 <= j < h and grid[j, i]:
                        d = di * di + dj * dj
                        if best is None or d < best[0]:
                            best = (d, (i, j))
            if best is not None:
                return best[1]
        return None

    def _astar(
        self, start: tuple[int, int], goal: tuple[int, int], grid: np.ndarray
    ) -> Optional[list[tuple[int, int]]]:
        h, w = grid.shape
        gi, gj = goal

        def heur(i: int, j: int) -> float:
            dx, dy = abs(i - gi), abs(j - gj)
            return (dx + dy) + (_SQRT2 - 2.0) * min(dx, dy)

        open_heap: list[tuple[float, float, tuple[int, int]]] = [(heur(*start), 0.0, start)]
        came: dict[tuple[int, int], tuple[int, int]] = {}
        g = {start: 0.0}
        steps = [
            (1, 0, 1.0),
            (-1, 0, 1.0),
            (0, 1, 1.0),
            (0, -1, 1.0),
            (1, 1, _SQRT2),
            (1, -1, _SQRT2),
            (-1, 1, _SQRT2),
            (-1, -1, _SQRT2),
        ]
        while open_heap:
            _, cost, cur = heapq.heappop(open_heap)
            if cur == goal:
                path = [cur]
                while cur in came:
                    cur = came[cur]
                    path.append(cur)
                return path[::-1]
            if cost > g.get(cur, math.inf):
                continue
            ci, cj = cur
            for di, dj, c in steps:
                ni, nj = ci + di, cj + dj
                if not (0 <= ni < w and 0 <= nj < h) or not grid[nj, ni]:
                    continue
                if di and dj and not (grid[cj, ni] and grid[nj, ci]):
                    continue  # no cutting corners
                ng = cost + c
                if ng < g.get((ni, nj), math.inf):
                    g[(ni, nj)] = ng
                    came[(ni, nj)] = cur
                    heapq.heappush(open_heap, (ng + heur(ni, nj), ng, (ni, nj)))
        return None

    def _line_free(self, a: tuple[int, int], b: tuple[int, int], grid: np.ndarray) -> bool:
        (i0, j0), (i1, j1) = a, b
        n = int(max(abs(i1 - i0), abs(j1 - j0)) * 2) + 1
        for k in range(n + 1):
            t = k / n
            i = int(round(i0 + (i1 - i0) * t))
            j = int(round(j0 + (j1 - j0) * t))
            if not grid[j, i]:
                return False
        return True

    def plan(
        self, start_xy: tuple[float, float], goal_xy: tuple[float, float]
    ) -> list[tuple[float, float]]:
        """Waypoints from `start_xy` to `goal_xy` (both included), walking
        only through free space. Falls back to the un-inflated grid (tight
        spots) and finally to a straight line, so a caller always gets a path."""
        for grid in (self.free, self._fallback):
            s = self._nearest_free(self._cell(start_xy), grid)
            g = self._nearest_free(self._cell(goal_xy), grid)
            if s is None or g is None:
                continue
            cells = self._astar(s, g, grid)
            if cells is None:
                continue
            pulled = [cells[0]]
            k = 0
            while k < len(cells) - 1:
                nxt = len(cells) - 1
                while nxt > k + 1 and not self._line_free(cells[k], cells[nxt], grid):
                    nxt -= 1
                pulled.append(cells[nxt])
                k = nxt
            pts = [self.navmesh.cell_to_world(i, j) for i, j in pulled]
            return [tuple(start_xy)] + pts[1:-1] + [tuple(goal_xy)]
        return [tuple(start_xy), tuple(goal_xy)]
