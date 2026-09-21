"""starling_sim/scenario.py
----------------------------
A scenario is the script the demo follows: which workers walk which
waypoint routes, and which nodes go through a scripted occlusion event and
when. `configs/sim/scenarios/warehouse_demo.yaml` is the default scenario
this project ships; the format here is deliberately small — this is a demo
script, not a general animation language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import yaml


@dataclass
class ScenarioWorker:
    worker_id: int
    name: str
    route: list[tuple[float, float]]
    speed_m_s: float = 1.2
    # "Pausing sometimes" (task brief): each tick, an independent chance
    # to stop for a random duration, rather than a fixed pause scripted at
    # every waypoint — simpler to reason about and still reads as natural
    # movement on the dashboard.
    pause_prob_per_tick: float = 0.0
    pause_duration_s: tuple[float, float] = (1.0, 3.0)
    loop: bool = True
    # Actors that only exist while a script runs (spawned by an `assign` step).
    active: bool = True
    # Appearance is a near-copy of another worker's (a "twin").
    twin_of: Optional[int] = None
    # What a face-recognition anchor at a gate reports for this person. Two
    # people sharing one value is a face mismatch: the source of a fork.
    face_identity: Optional[str] = None


@dataclass
class AnchorPoint:
    """A face-recognition gate: a worker with a `face_identity` standing
    within `radius` of (x, y) in `node_id`'s zone yields a FACE_ANCHOR claim."""

    node_id: int
    x: float
    y: float
    radius: float = 2.0


@dataclass
class ScenarioOcclusion:
    node_id: int
    start_s: float
    duration_s: float
    occlusion_ratio: float = 0.9
    detector_health: float = 0.3


@dataclass
class Scenario:
    name: str
    workers: list[ScenarioWorker] = field(default_factory=list)
    occlusions: list[ScenarioOcclusion] = field(default_factory=list)
    anchors: list[AnchorPoint] = field(default_factory=list)
    # name -> list of steps ({assign: {...}} / {occlude: {...}}, each with an
    # optional delay_s), run on demand by the simulator's control endpoint.
    scripts: dict = field(default_factory=dict)
    # Scripts started automatically: [{at_s, script}], repeating every auto_period_s.
    auto: list = field(default_factory=list)
    auto_period_s: float = 0.0


def load_scenario(path: Union[str, Path]) -> Scenario:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    workers = [
        ScenarioWorker(
            worker_id=w["worker_id"],
            name=w.get("name", f"worker-{w['worker_id']}"),
            route=[tuple(p) for p in w["route"]],
            speed_m_s=w.get("speed_m_s", 1.2),
            pause_prob_per_tick=w.get("pause_prob_per_tick", 0.0),
            pause_duration_s=tuple(w.get("pause_duration_s", (1.0, 3.0))),
            loop=w.get("loop", True),
            active=w.get("active", True),
            twin_of=w.get("twin_of"),
            face_identity=w.get("face_identity"),
        )
        for w in data.get("workers", [])
    ]
    occlusions = [
        ScenarioOcclusion(
            node_id=o["node_id"],
            start_s=o["start_s"],
            duration_s=o["duration_s"],
            occlusion_ratio=o.get("occlusion_ratio", 0.9),
            detector_health=o.get("detector_health", 0.3),
        )
        for o in data.get("occlusions", [])
    ]
    anchors = [AnchorPoint(a["node_id"], a["x"], a["y"], a.get("radius", 2.0)) for a in data.get("anchors", [])]
    return Scenario(
        name=data.get("name", Path(path).stem), workers=workers, occlusions=occlusions, anchors=anchors,
        scripts=data.get("scripts", {}) or {}, auto=data.get("auto", []) or [],
        auto_period_s=float(data.get("auto_period_s", 0.0)),
    )
