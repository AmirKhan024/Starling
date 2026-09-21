"""starling_sim/node_client.py
-------------------------------
A sim-mode node's counterpart to `starling_perception.source.PacedSource`:
connects to the simulator process's PUB socket and yields this node's own
ticks only — subscribed to exactly one topic (its own), per the
simulator's "only ever send a node its own zone" rule. Wired into
`apps/node.py`'s `source: "sim"` branch in STATUS.md Step 4.
"""

from __future__ import annotations

from typing import Any, Optional

from starling_sim.coverage import CoverageState
from starling_sim.messages import node_topic
from starling_sim.perception import SimObservation, dict_to_obs
from starling_sim.transport import SimSubscriber


class SimNodeSource:
    def __init__(self, connect_endpoint: str, node_id: int) -> None:
        self.node_id = node_id
        self._sub = SimSubscriber(connect_endpoint, node_topic(node_id))

    def recv(self, timeout_ms: int = 1000) -> Optional[dict[str, Any]]:
        return self._sub.recv(timeout_ms=timeout_ms)

    def close(self) -> None:
        self._sub.close()


def observations_from_tick(
    tick: dict[str, Any],
) -> list[tuple[SimObservation, tuple[float, float], float]]:
    return [dict_to_obs(d) for d in tick.get("observations", [])]


def coverage_from_tick(tick: dict[str, Any]) -> CoverageState:
    cov = tick["coverage"]
    return CoverageState(
        occlusion_ratio=cov["occlusion_ratio"],
        illumination_score=cov["illumination_score"],
        detector_health=cov["detector_health"],
    )
