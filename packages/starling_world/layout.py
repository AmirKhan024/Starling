"""starling_world/layout.py
----------------------------
Static site geometry derived from configs/world/warehouse.yaml: the
walkable floor, the 3D obstacle boxes, and — the part that matters for
C4 — each camera's ZONE.

A camera zone is not drawn by hand. `compute_camera_zones` asks, for every
walkable floor cell, "would a person standing here be fully in this
camera's frame, unoccluded by racking or stock, and at least
`min_person_px` tall?", and gives the cell to the camera that sees it best.
That makes a zone exactly the area a healthy camera can vouch for — which
is what a coverage attestation claims, and what negative evidence
subtracts. Cells no camera can vouch for (the racking aisles, a few
corners) belong to no zone: silence there is never evidence.

`write_floorplan_geojson` writes the result in the floor-plan schema the
rest of Starling already reads (starling_geometry.navmesh, the dashboard).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import numpy as np
from shapely.geometry import MultiPolygon, Polygon, box, mapping
from shapely.ops import unary_union

from starling_world.camera import PinholeCamera, segment_hits_box
from starling_world.config import WorldConfig

# Body points (fractions of standing height) whose line of sight must be
# clear for a cell to count as covered: torso and head. Feet may hide
# behind a low pallet without the person going undetected.
_SIGHT_FRACTIONS = (0.55, 0.95)
# Zone pieces smaller than this are dropped (isolated cells add nothing but noise).
_MIN_ZONE_PIECE_M2 = 1.0


@dataclass(frozen=True)
class Obstacle:
    name: str
    kind: str
    x0: float
    y0: float
    x1: float
    y1: float
    height_m: float

    @property
    def lo(self) -> np.ndarray:
        return np.array([self.x0, self.y0, 0.0])

    @property
    def hi(self) -> np.ndarray:
        return np.array([self.x1, self.y1, self.height_m])


def obstacles(cfg: WorldConfig) -> list[Obstacle]:
    out = [Obstacle(r.name, "rack", r.x0, r.y0, r.x1, r.y1, r.height_m) for r in cfg.racks]
    out += [
        Obstacle(f"{p.kind}-{i}", p.kind, p.x0, p.y0, p.x1, p.y1, p.height_m)
        for i, p in enumerate(cfg.props)
    ]
    return out


def floor_polygon(cfg: WorldConfig) -> Polygon:
    return box(0.0, 0.0, cfg.building.width_m, cfg.building.depth_m)


def walkable(cfg: WorldConfig) -> Polygon:
    free = floor_polygon(cfg)
    for ob in obstacles(cfg):
        free = free.difference(box(ob.x0, ob.y0, ob.x1, ob.y1))
    return free


def cameras(cfg: WorldConfig) -> dict[int, PinholeCamera]:
    return {c.node_id: PinholeCamera.from_config(c, cfg.camera_frames) for c in cfg.cameras}


def _grid(cfg: WorldConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cell centres on the same grid NavMesh.from_geojson builds (origin at
    the floor's min corner, `navmesh_cell_m` cells), so a zone mask and the
    navmesh line up cell for cell."""
    c = cfg.navmesh_cell_m
    nx = int(np.ceil(cfg.building.width_m / c))
    ny = int(np.ceil(cfg.building.depth_m / c))
    xs = (np.arange(nx) + 0.5) * c
    ys = (np.arange(ny) + 0.5) * c
    free = np.zeros((ny, nx), dtype=bool)
    poly = walkable(cfg)
    from shapely.geometry import Point
    from shapely.prepared import prep

    pp = prep(poly)
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            free[j, i] = pp.contains(Point(x, y))
    return xs, ys, free


def person_visibility(
    cam: PinholeCamera, x: float, y: float, cfg: WorldConfig, obs: list[Obstacle]
) -> float:
    """Projected pixel height of a standing person at (x, y) if this camera
    can fully see them — in frame, unoccluded, and not from too steep
    above — else 0."""
    h = cfg.camera_frames.person_height_m
    eye = np.asarray(cam.mount, dtype=float)
    depression = np.degrees(np.arctan2(eye[2], np.hypot(x - eye[0], y - eye[1])))
    if depression > cfg.camera_frames.max_depression_deg:
        return 0.0
    uv, depth = cam.person_box(x, y, h)
    if not cam.in_frame(uv, depth, margin_px=4.0).all():
        return 0.0
    for frac in _SIGHT_FRACTIONS:
        target = np.array([x, y, h * frac])
        for ob in obs:
            if segment_hits_box(eye, target, ob.lo, ob.hi):
                return 0.0
    return float(abs(uv[1, 1] - uv[0, 1]))


def compute_camera_zones(
    cfg: WorldConfig,
) -> tuple[dict[int, np.ndarray], np.ndarray, dict[int, np.ndarray]]:
    """Returns ({node_id: bool zone mask}, walkable mask, {node_id: pixel-height grid})."""
    xs, ys, free = _grid(cfg)
    obs = obstacles(cfg)
    cams = cameras(cfg)
    px = {n: np.zeros(free.shape) for n in cams}
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            if not free[j, i]:
                continue
            for n, cam in cams.items():
                px[n][j, i] = person_visibility(cam, float(x), float(y), cfg, obs)
    stack = np.stack([px[n] for n in sorted(cams)], axis=0)
    best = np.argmax(stack, axis=0)
    good = stack.max(axis=0) >= cfg.camera_frames.min_person_px
    order = sorted(cams)
    zones = {n: (best == k) & good & free for k, n in enumerate(order)}
    return zones, free, px


def mask_to_geometry(mask: np.ndarray, cell: float) -> Union[Polygon, MultiPolygon]:
    squares = []
    for j, i in zip(*np.nonzero(mask)):
        squares.append(box(i * cell, j * cell, (i + 1) * cell, (j + 1) * cell))
    if not squares:
        return Polygon()
    geom = unary_union(squares)
    parts = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    parts = [p for p in parts if p.area >= _MIN_ZONE_PIECE_M2]
    # Shrink a hair so a cell-centre test reproduces exactly this mask.
    parts = [p.buffer(-cell * 0.05, join_style=2) for p in parts]
    parts = [p for p in parts if not p.is_empty]
    if not parts:
        return Polygon()
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def write_floorplan_geojson(cfg: WorldConfig, out_path: Union[str, Path]) -> dict:
    zones, free, px = compute_camera_zones(cfg)
    cell = cfg.navmesh_cell_m
    feats = [
        {
            "type": "Feature",
            "properties": {"role": "floor", "name": "warehouse_floor"},
            "geometry": mapping(floor_polygon(cfg)),
        }
    ]
    names = {c.node_id: c.name for c in cfg.cameras}
    covered = np.zeros_like(free)
    stats: dict[str, dict] = {}
    for n in sorted(zones):
        geom = mask_to_geometry(zones[n], cell)
        covered |= zones[n]
        feats.append(
            {
                "type": "Feature",
                "properties": {"role": "camera_zone", "name": names[n], "node_id": n},
                "geometry": mapping(geom),
            }
        )
        stats[str(n)] = {
            "area_m2": round(float(geom.area), 1),
            "median_person_px": round(
                float(np.median(px[n][zones[n]])) if zones[n].any() else 0.0, 1
            ),
        }
    blind = mask_to_geometry(free & ~covered, cell)
    feats.append(
        {
            "type": "Feature",
            "properties": {"role": "blind", "name": "not covered by any camera"},
            "geometry": mapping(blind),
        }
    )
    for ob in obstacles(cfg):
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "role": "obstacle",
                    "name": ob.name,
                    "kind": ob.kind,
                    "height_m": ob.height_m,
                },
                "geometry": mapping(box(ob.x0, ob.y0, ob.x1, ob.y1)),
            }
        )
    data = {
        "type": "FeatureCollection",
        "generator": "scripts/build_world_floorplan.py (from configs/world/warehouse.yaml)",
        "stats": {
            "walkable_m2": round(float(free.sum()) * cell * cell, 1),
            "blind_m2": round(float(blind.area), 1),
            "zones": stats,
        },
        "features": feats,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data
