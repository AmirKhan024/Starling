"""apps/dashboard/config.py
----------------------------
The dashboard is not a Starling node (CLAUDE.md rule 8: "a read-only
gossip observer with no privileged access") so it gets its own small
config model rather than `starling_node.config.NodeConfig` — it has no
camera, no local store, no gossip publish port, none of a node's
identity-path fields. `peers` is the one thing it needs that a node
config doesn't: every node's OWN gossip PUB address, so the observer's SUB
sockets know who to connect to (the observer is never itself a
`neighbour` any node gossips TO — see `apps/dashboard/observer.py`).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from starling_node.config import GeometryConfig, MatchConfig


class DashboardConfig(BaseModel):
    # node_id -> "host:port" of THAT node's own gossip PUB socket (the
    # same address a real neighbour would put in its own `net.neighbours`
    # list to hear from that node).
    peers: dict[int, str] = Field(default_factory=dict)
    keys_dir: str = "configs/keys"
    # Shared floor plan — the same file every node's own GeometryConfig
    # points at. Reading it is not a privileged operation: it is static,
    # non-secret site geometry, not another node's private state.
    navmesh_path: str | None = "data/floorplan/demo_site.geojson"
    match: MatchConfig = Field(default_factory=MatchConfig)
    geometry: GeometryConfig = Field(default_factory=GeometryConfig)
    # An identity with no claim newer than this is shown in the Lost
    # Registry / gets a candidate-belief region on the floor plan.
    lost_threshold_s: float = 120.0
    # A peer the observer hasn't heard a signed message from within this
    # many seconds is shown offline/partitioned in Node Health.
    stale_after_s: float = 10.0
    # Matches apps/node.py's AttackInjector control-port convention
    # (listen_port + 1000) — the "Make node N lie" button's target.
    control_port_offset: int = 1000


def load_dashboard_config(path: Path) -> DashboardConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return DashboardConfig.model_validate(data or {})
