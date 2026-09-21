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
from typing import Union

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
    return Scenario(name=data.get("name", Path(path).stem), workers=workers, occlusions=occlusions)
