"""starling_eval/scenario.py
-----------------------------
Declarative partition/degradation scenario schema (WP-04 Part 4). This is
what turns "our system tolerates partitions" from an assertion into a
measurement: a scenario is a YAML timeline of network events, executed
against running node containers by deploy/netem/apply.py.

Event kinds
-----------
partition  t, groups                                  hard split (iptables DROP)
heal       t                                           remove all rules
degrade    t, nodes, loss_pct, latency_ms, jitter_ms   tc netem
kill       t, node                                     stop the container
revive     t, node                                     start it again
lie        t, node, attack, intensity                  consumed in a later
                                                        work package (Byzantine
                                                        attack injection)
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Union

import yaml
from pydantic import BaseModel, Field, model_validator


class PartitionEvent(BaseModel):
    t: float
    action: Literal["partition"] = "partition"
    groups: list[list[int]]


class HealEvent(BaseModel):
    t: float
    action: Literal["heal"] = "heal"


class DegradeEvent(BaseModel):
    t: float
    action: Literal["degrade"] = "degrade"
    nodes: list[int]
    loss_pct: float = 0.0
    latency_ms: float = 0.0
    jitter_ms: float = 0.0


class KillEvent(BaseModel):
    t: float
    action: Literal["kill"] = "kill"
    node: int


class ReviveEvent(BaseModel):
    t: float
    action: Literal["revive"] = "revive"
    node: int


class LieEvent(BaseModel):
    t: float
    action: Literal["lie"] = "lie"
    node: int
    attack: str
    intensity: float = 1.0


ScenarioEvent = Annotated[
    Union[PartitionEvent, HealEvent, DegradeEvent, KillEvent, ReviveEvent, LieEvent],
    Field(discriminator="action"),
]


class Scenario(BaseModel):
    name: str
    duration_s: float
    stream_epoch: float = 0.0
    speed: float = 1.0
    nodes: list[int]
    videos: dict[int, str] = Field(default_factory=dict)
    events: list[ScenarioEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sort_events_by_time(self) -> "Scenario":
        self.events.sort(key=lambda e: e.t)
        return self


def load_scenario(path: Path) -> Scenario:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Scenario.model_validate(data)
