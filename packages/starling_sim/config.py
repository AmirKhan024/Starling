"""starling_sim/config.py
--------------------------
Pydantic config for the simulator process itself (`SimulatorConfig`,
loaded from e.g. configs/sim/warehouse.yaml) and for a sim-mode node's
side of the connection (`SimNodeConfig`). Follows this project's existing
convention (packages/starling_node/config.py) of one small BaseModel per
concern with every threshold named and defaulted, rather than a free-form
dict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml
from pydantic import BaseModel


class SimulatorConfig(BaseModel):
    floorplan_path: str
    scenario_path: str
    bind_endpoint: str = "tcp://127.0.0.1:5560"
    tick_hz: float = 5.0
    # Wall-clock speed multiplier: 1.0 = real time. The task brief's
    # "advances at real-time speed by default with a speed multiplier".
    speed: float = 1.0
    # Must match the sim nodes' perception.embed_dim (PerceptionConfig's
    # default is 512) or a resolver comparing embeddings across a sim
    # claim and a video-path claim would compare mismatched dimensions.
    embed_dim: int = 512
    pos_noise_sigma_m: float = 0.15
    embedding_noise_sigma: float = 0.05
    detection_miss_prob: float = 0.03
    conf_min: float = 0.75
    conf_max: float = 0.98
    quality_min: float = 0.5
    quality_max: float = 0.95
    seed: int = 1234
    # HTTP control endpoint of the simulator (scripts / manual occlusion), the
    # dashboard's "demo script" buttons call it. 0 disables it.
    control_port: int = 6560
    # Run the scenario's `auto` episodes by themselves.
    auto: bool = True
    # 0 = workers' appearances as distinct as random unit vectors get;
    # 1 = every worker collapses onto one shared vector (worst case for
    # appearance-based matching — a "same uniform" stress test).
    uniform_similarity: float = 0.0


def load_simulator_config(path: Union[str, Path]) -> SimulatorConfig:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return SimulatorConfig.model_validate(data)
