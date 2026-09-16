"""starling_geometry/navmesh.py
---------------------------------
2D navmesh from a GeoJSON floor plan (WP-05 Part 2). CLAUDE.md /
STARLING_BUILD_STATE.md §12 rule 2: 2D only, no 3D reconstruction path —
not even behind a flag.

GeoJSON conventions (freeze these; a later work package's negative-evidence
belief update and reachability gate both read this exact shape):
  - a `Polygon` feature with no `role` (or `role: "floor"`) is walkable
    floor; more than one such feature is unioned together
  - a `Polygon` feature tagged `{"role": "obstacle"}` is subtracted from
    the free space (racking, walls, anything impassable)
  - a `LineString` feature tagged `{"role": "boundary", "boundary_id": N}`
    is a segment a node can attest about (the exact boundaries a later
    work package's coverage attestations reference)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import numpy as np
from scipy import ndimage
from shapely.geometry import Point, shape
from shapely.ops import unary_union

DEFAULT_CELL_SIZE_M = 0.25


def _rasterize_line(line, origin: tuple[float, float], cell_size: float, grid_shape: tuple[int, int]) -> list[tuple[int, int]]:
    """Sample a LineString at sub-cell intervals and convert each sample to
    a (col, row) grid cell, deduplicating consecutive repeats.
    """
    height, width = grid_shape
    length = line.length
    if length == 0:
        n_samples = 1
    else:
        n_samples = max(int(np.ceil(length / (cell_size / 2))), 2)

    cells: list[tuple[int, int]] = []
    for k in range(n_samples + 1):
        frac = k / n_samples if n_samples else 0.0
        pt = line.interpolate(frac, normalized=True)
        i = int((pt.x - origin[0]) / cell_size)
        j = int((pt.y - origin[1]) / cell_size)
        if 0 <= i < width and 0 <= j < height:
            cell = (i, j)
            if not cells or cells[-1] != cell:
                cells.append(cell)
    return cells


def _compute_boundary_components(grid: np.ndarray, boundaries: dict[int, list[tuple[int, int]]]) -> dict[int, np.ndarray]:
    """WP-09 Part 3 ("beyond the boundary" precomputation, Appendix A.3):
    for each boundary, remove its rasterised cells from the free-space
    grid as a temporary barrier, then label the connected components of
    what remains (8-connected, matching `starling_geometry.reachability`'s
    neighbourhood). A boundary LineString that fully spans the walkable
    width — the only kind this project's floor plans use (see
    `data/floorplan/demo_site.geojson`'s two gap-exit boundaries) —
    splits free space into exactly two components. `0` marks a barrier
    cell or non-free cell; component ids start at `1`. Cached once here,
    at load time, rather than recomputed per attestation.
    """
    structure = ndimage.generate_binary_structure(2, 2)  # 8-connectivity
    components: dict[int, np.ndarray] = {}
    for boundary_id, cells in boundaries.items():
        barrier_grid = grid.copy()
        height, width = barrier_grid.shape
        for i, j in cells:
            if 0 <= i < width and 0 <= j < height:
                barrier_grid[j, i] = False
        labelled, _ = ndimage.label(barrier_grid, structure=structure)
        components[boundary_id] = labelled
    return components


@dataclass
class NavMesh:
    grid: np.ndarray                                  # bool [row=j, col=i], True = free space
    origin: tuple[float, float]                        # world (x, y) metres of cell (0, 0)'s lower corner
    cell_size: float
    boundaries: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    # WP-09 Part 3: per boundary_id, an int label grid from
    # `_compute_boundary_components` — which side of that boundary each
    # free cell lies on. Left empty here; `__post_init__` always derives it
    # from `grid`/`boundaries` so it's correct regardless of which
    # constructor path built this NavMesh (`from_geojson` or the plain
    # dataclass constructor, as several WP-09 tests use directly).
    boundary_components: dict[int, np.ndarray] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.boundaries and not self.boundary_components:
            self.boundary_components = _compute_boundary_components(self.grid, self.boundaries)

    @classmethod
    def from_geojson(cls, path: Union[str, Path], cell_size_m: float = DEFAULT_CELL_SIZE_M) -> "NavMesh":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        floor_polys = []
        obstacle_polys = []
        boundary_lines = {}  # int boundary_id -> shapely LineString

        for feat in data["features"]:
            props = feat.get("properties") or {}
            geom = shape(feat["geometry"])
            role = props.get("role")

            if geom.geom_type == "Polygon":
                if role == "obstacle":
                    obstacle_polys.append(geom)
                else:
                    floor_polys.append(geom)
            elif geom.geom_type == "LineString" and role == "boundary":
                boundary_lines[int(props["boundary_id"])] = geom

        if not floor_polys:
            raise ValueError(f"{path}: no walkable floor Polygon found")

        free_space = unary_union(floor_polys)
        for obstacle in obstacle_polys:
            free_space = free_space.difference(obstacle)

        minx, miny, maxx, maxy = free_space.bounds
        origin = (minx, miny)
        width = max(int(np.ceil((maxx - minx) / cell_size_m)), 1)
        height = max(int(np.ceil((maxy - miny) / cell_size_m)), 1)

        grid = np.zeros((height, width), dtype=bool)
        for j in range(height):
            cy = miny + (j + 0.5) * cell_size_m
            for i in range(width):
                cx = minx + (i + 0.5) * cell_size_m
                grid[j, i] = free_space.contains(Point(cx, cy))

        boundaries = {
            boundary_id: _rasterize_line(line, origin, cell_size_m, grid.shape)
            for boundary_id, line in boundary_lines.items()
        }

        return cls(grid=grid, origin=origin, cell_size=cell_size_m, boundaries=boundaries)

    def world_to_cell(self, x: float, y: float) -> tuple[int, int]:
        i = int((x - self.origin[0]) / self.cell_size)
        j = int((y - self.origin[1]) / self.cell_size)
        return i, j

    def cell_to_world(self, i: int, j: int) -> tuple[float, float]:
        x = self.origin[0] + (i + 0.5) * self.cell_size
        y = self.origin[1] + (j + 0.5) * self.cell_size
        return x, y

    def is_free(self, x: float, y: float) -> bool:
        i, j = self.world_to_cell(x, y)
        height, width = self.grid.shape
        if not (0 <= i < width and 0 <= j < height):
            return False
        return bool(self.grid[j, i])

    def area_m2(self, mask: Optional[np.ndarray] = None) -> float:
        m = self.grid if mask is None else mask
        return float(np.count_nonzero(m)) * (self.cell_size ** 2)

    def cells_beyond(self, boundary_id: int, reference_xy: tuple[float, float]) -> np.ndarray:
        """WP-09 Part 3's precise definition of "beyond the boundary"
        (Appendix A.3's `B[cells beyond boundary(a)] <- 0` step): a
        boolean grid mask, True for every free cell on the OPPOSITE side
        of `boundary_id` from `reference_xy` (typically the candidate
        belief's own confirmed origin — see
        `starling_attest.negative_evidence`'s module docstring for why
        that reference point, not the attesting node's ROI, is what this
        method is given).

        Uses `boundary_components` (`__post_init__`): a boundary that
        fully spans the walkable width splits free space into exactly two
        connected components — one containing `reference_xy`'s cell (the
        "near" side, False here) and the other (the "far" side, True).
        Boundary-barrier cells and anything outside `reference_xy`'s own
        component's graph are always False: "beyond" is a specific claim
        about which side of one line a cell is on, not "unreachable".
        Returns an all-False mask for an unknown `boundary_id` or a
        `reference_xy` that isn't itself in free space.
        """
        components = self.boundary_components.get(boundary_id)
        if components is None:
            return np.zeros_like(self.grid, dtype=bool)

        ri, rj = self.world_to_cell(*reference_xy)
        height, width = components.shape
        if not (0 <= ri < width and 0 <= rj < height):
            return np.zeros_like(self.grid, dtype=bool)

        near_label = components[rj, ri]
        if near_label == 0:
            return np.zeros_like(self.grid, dtype=bool)
        return (components != near_label) & (components != 0)

    def render(self, mask: Optional[np.ndarray] = None):
        """Renders the free-space grid as a PIL image (dashboard + docs
        use this — e.g. scripts/render_reachability.py). White = free,
        dark grey = obstacle/outside, red = `mask` cells (e.g. a
        reachable-set or candidate-belief overlay).
        """
        from PIL import Image

        height, width = self.grid.shape
        rgb = np.empty((height, width, 3), dtype=np.uint8)
        rgb[self.grid] = (235, 235, 235)
        rgb[~self.grid] = (40, 40, 40)
        if mask is not None:
            rgb[mask] = (235, 70, 70)
        # Row 0 corresponds to the lowest y (origin) — flip so the image's
        # top matches larger y, the usual on-screen convention.
        return Image.fromarray(np.flipud(rgb), mode="RGB")
