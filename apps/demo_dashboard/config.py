"""apps/demo_dashboard/config.py
---------------------------------
Config for the simulator demo dashboard. Extends the existing
`DashboardConfig` (peers, keys_dir, navmesh, match, stale_after_s,
control_port_offset) with the demo-specific knobs. Every threshold the
dashboard's logic uses lives here (CLAUDE.md: no magic numbers in logic).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import Field

from apps.dashboard.config import DashboardConfig
from starling_node.config import NegativeEvidenceConfig, PlausibilityConfig


class DemoDashboardConfig(DashboardConfig):
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    # The simulator's PUB socket; the dashboard subscribes ONLY to its
    # ground-truth topic (CLAUDE.md rule 8 + the task's "gossip and the
    # simulator's ground-truth topic only").
    sim_endpoint: str = "tcp://127.0.0.1:5560"
    # The simulator's HTTP control endpoint (scenario scripts). The dashboard
    # drives the WORLD with it, exactly like the partition/lie buttons drive nodes.
    sim_control_url: str = "http://127.0.0.1:6560"
    # Pre-issued capability tokens (the launcher signs them; the dashboard
    # never holds a private key). File name = purpose.
    token_dir: str = "data/demo/tokens"
    compute_interval_s: float = 0.5
    control_poll_interval_s: float = 1.0
    control_timeout_s: float = 0.4
    # An identity whose newest claim is older than this (media seconds,
    # relative to the newest claim in the mesh) is "unseen" and gets a
    # candidate-region belief.
    unseen_after_s: float = 1.5
    # Identity fragments with fewer claims than this are not drawn.
    min_identity_claims: int = 8
    # An identity unseen for longer than this (media seconds) is no longer
    # drawn: it is almost always a stale duplicate fragment, and its region
    # would only grow to cover the whole floor.
    hide_unseen_after_s: float = 40.0
    # Display-only naming of a resolved identity as "worker N": nearest
    # ground-truth worker within this many metres, needing this many votes.
    name_match_max_dist_m: float = 3.0
    name_min_votes: int = 3
    trail_points: int = 24
    trail_span_s: float = 6.0
    # Claim-count spread (max - min across live nodes) still counted as
    # converged; covers claims in flight while the sim keeps producing.
    converge_tolerance_claims: int = 30
    # The query is asked "from" this node's side of any partition.
    query_vantage_node: int = 0
    query_window_s: float = 600.0
    # Partition button: these two groups are cut from each other.
    partition_groups: list[list[int]] = Field(default_factory=lambda: [[0, 1], [2, 3]])
    lie_attack: str = "fabricate"
    lie_intensity: float = 0.9
    event_log_size: int = 60
    resolve_min_interval_s: float = 1.0
    # A zone-coverage attestation counts as current for this long (media s) after
    # its interval ends; nodes attest every 2 s, so a few missed ones are tolerated.
    attest_validity_s: float = 4.5
    # The dashboard resolves the last N media-seconds of claims (the resolver
    # is O(claims x identities); a demo runs for many minutes). Labels stay
    # stable across windows via claim overlap.
    resolve_window_s: float = 45.0
    negative_evidence: NegativeEvidenceConfig = Field(default_factory=NegativeEvidenceConfig)
    plausibility: PlausibilityConfig = Field(default_factory=PlausibilityConfig)


def load_demo_config(path: Path) -> DemoDashboardConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return DemoDashboardConfig.model_validate(data or {})
