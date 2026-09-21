"""starling_sim/world.py
-------------------------
The simulated warehouse's ground truth: worker positions and scripted
coverage/occlusion state, advanced one tick at a time. This is the part of
`starling_sim` that is allowed to know everything (see the package
docstring) — `starling_sim.perception`/`starling_sim.coverage` are what
restrict what actually reaches a given node.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import numpy as np
from shapely.geometry import Point, base as shapely_base, shape

from starling_geometry.navmesh import NavMesh
from starling_sim.identity import make_identity_vectors
from starling_sim.scenario import Scenario


def load_camera_zones(floorplan_path: Union[str, Path]) -> dict[int, "shapely_base.BaseGeometry"]:
    """Every `{"role": "camera_zone", "node_id": N}` polygon in a floor
    plan GeoJSON (data/floorplan/warehouse_demo.geojson's schema — see
    starling_geometry.navmesh's module docstring for the shared
    conventions), keyed by node_id. Read independently of
    `NavMesh.from_geojson`, which does not preserve per-zone node_id
    assignment (it only needs "is this polygon walkable or an obstacle").
    """
    with open(floorplan_path, encoding="utf-8") as f:
        data = json.load(f)

    zones: dict[int, "shapely_base.BaseGeometry"] = {}
    for feat in data["features"]:
        props = feat.get("properties") or {}
        if props.get("role") == "camera_zone" and "node_id" in props:
            zones[int(props["node_id"])] = shape(feat["geometry"])
    return zones


@dataclass
class Worker:
    worker_id: int
    name: str
    route: list[tuple[float, float]]
    speed_m_s: float
    identity_vector: np.ndarray
    pause_prob_per_tick: float = 0.0
    pause_duration_s: tuple[float, float] = (1.0, 3.0)
    loop: bool = True
    pos: tuple[float, float] = field(init=False)
    _dist_traveled: float = field(default=0.0, init=False, repr=False)
    _pause_remaining_s: float = field(default=0.0, init=False, repr=False)
    _path: list[tuple[float, float]] = field(init=False, repr=False)
    _cum_lengths: list[float] = field(init=False, repr=False)
    _path_length: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.route:
            raise ValueError(f"worker {self.worker_id}: route must have at least one waypoint")
        path = list(self.route)
        # A looping worker's path is the route plus an implicit closing
        # segment back to its own start, so `_position_at` never needs a
        # special "wrap around" case — distance traveled modulo the total
        # path length (closing segment included) always lands somewhere
        # on this one continuous polyline.
        if self.loop and len(path) > 1 and path[-1] != path[0]:
            path = path + [path[0]]
        self._path = path

        cum = [0.0]
        for p0, p1 in zip(path, path[1:]):
            cum.append(cum[-1] + math.hypot(p1[0] - p0[0], p1[1] - p0[1]))
        self._cum_lengths = cum
        self._path_length = cum[-1] if len(cum) > 1 else 0.0
        self.pos = path[0]

    def tick(self, dt_s: float, rng: np.random.Generator) -> None:
        if self._pause_remaining_s > 0:
            self._pause_remaining_s = max(0.0, self._pause_remaining_s - dt_s)
            return
        if self.pause_prob_per_tick > 0 and rng.random() < self.pause_prob_per_tick:
            self._pause_remaining_s = float(rng.uniform(*self.pause_duration_s))
            return
        if self._path_length <= 0:
            return

        self._dist_traveled += self.speed_m_s * dt_s
        if self.loop:
            self._dist_traveled %= self._path_length
        else:
            self._dist_traveled = min(self._dist_traveled, self._path_length)
        self.pos = self._position_at(self._dist_traveled)

    def _position_at(self, dist: float) -> tuple[float, float]:
        for i in range(len(self._cum_lengths) - 1):
            seg_end = self._cum_lengths[i + 1]
            if dist <= seg_end or i == len(self._cum_lengths) - 2:
                seg_len = seg_end - self._cum_lengths[i]
                frac = 0.0 if seg_len == 0 else (dist - self._cum_lengths[i]) / seg_len
                p0, p1 = self._path[i], self._path[i + 1]
                return (p0[0] + (p1[0] - p0[0]) * frac, p0[1] + (p1[1] - p0[1]) * frac)
        return self._path[-1]


@dataclass
class OcclusionEvent:
    node_id: int
    start_s: float
    duration_s: float
    occlusion_ratio: float
    detector_health: float

    def active_at(self, t_media: float) -> bool:
        return self.start_s <= t_media < self.start_s + self.duration_s


class World:
    """Owns the whole simulated warehouse's ground truth: every worker's
    position and every node's scripted occlusion state, advanced one tick
    at a time. `starling_sim.perception.observe_zone` and
    `starling_sim.coverage.coverage_state_for_node` are the only things
    allowed to read from a `World` on behalf of a specific node — the
    simulator process itself (`starling_sim.runner`) is the only thing
    that sees a `World` whole.
    """

    def __init__(
        self,
        navmesh: NavMesh,
        zones: dict[int, "shapely_base.BaseGeometry"],
        scenario: Scenario,
        embed_dim: int = 512,
        seed: int = 1234,
        uniform_similarity: float = 0.0,
    ) -> None:
        self.navmesh = navmesh
        self.zones = zones
        self.t_media = 0.0
        self._rng = np.random.default_rng(seed)

        vectors = make_identity_vectors(
            len(scenario.workers), embed_dim, seed=seed, uniform_similarity=uniform_similarity
        )
        self.workers = [
            Worker(
                worker_id=sw.worker_id,
                name=sw.name,
                route=sw.route,
                speed_m_s=sw.speed_m_s,
                identity_vector=vectors[i],
                pause_prob_per_tick=sw.pause_prob_per_tick,
                pause_duration_s=sw.pause_duration_s,
                loop=sw.loop,
            )
            for i, sw in enumerate(scenario.workers)
        ]
        self.occlusions = [
            OcclusionEvent(o.node_id, o.start_s, o.duration_s, o.occlusion_ratio, o.detector_health)
            for o in scenario.occlusions
        ]

    def tick(self, dt_s: float) -> None:
        self.t_media += dt_s
        for worker in self.workers:
            worker.tick(dt_s, self._rng)

    def positions(self) -> dict[int, tuple[float, float]]:
        return {w.worker_id: w.pos for w in self.workers}

    def workers_in_zone(self, node_id: int) -> list[Worker]:
        polygon = self.zones.get(node_id)
        if polygon is None:
            return []
        return [w for w in self.workers if polygon.contains(Point(*w.pos))]

    def active_occlusion(self, node_id: int) -> Optional[OcclusionEvent]:
        for event in self.occlusions:
            if event.node_id == node_id and event.active_at(self.t_media):
                return event
        return None
