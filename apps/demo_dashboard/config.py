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
    # The centralised comparison server (apps/central_server_sim.py). NOT Starling.
    central_url: str = "http://127.0.0.1:7000"
    central_port: int = 7000
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
    # The configured gossip links (drawn by the technical view; static
    # deployment topology, the same pairs as the nodes' `net.neighbours`).
    topology_edges: list[list[int]] = Field(default_factory=list)
    # Partition button: these two groups are cut from each other.
    partition_groups: list[list[int]] = Field(default_factory=lambda: [[0, 1], [2, 3]])
    lie_attack: str = "fabricate"
    lie_intensity: float = 0.9
    event_log_size: int = 60
    resolve_min_interval_s: float = 1.0
    # A fork the resolver reported stays on the panel this long (wall s) after it
    # leaves the resolver window, so it can be read (display memory of a DERIVED
    # result; the resolver itself is a pure function of the window).
    fork_memory_s: float = 150.0
    # Conflict scenarios: heal the partition this many seconds after starting it.
    conflict_heal_after_s: float = 38.0
    # The same conflict variant cannot be started again for this long (its twins are still walking).
    conflict_cooldown_s: float = 100.0
    # A zone-coverage attestation counts as current for this long (media s) after
    # its interval ends; nodes attest every 2 s, so a few missed ones are tolerated.
    attest_validity_s: float = 4.5
    # The dashboard resolves the last N media-seconds of claims (the resolver
    # is O(claims x identities); a demo runs for many minutes). Labels stay
    # stable across windows via claim overlap.
    resolve_window_s: float = 45.0
    # "sim" = the 2D simulator demo; "world" = the live 3D world demo
    # (apps/world): identities are named by employee verification at the
    # entrance gate, never from ground truth (see world_view.py).
    mode: str = "sim"
    world_config_path: str = "configs/world/warehouse.yaml"
    # The world server (physical-world controls: cover a lens, send on break).
    world_url: str = "http://127.0.0.1:8770"
    # Manager view: an employee last seen this close to the staff door, and
    # unseen for this long, has left the building.
    door_exit_radius_m: float = 3.0
    # An anchor by the gate camera within the gate radius + this is a check-in.
    gate_match_slack_m: float = 0.75
    left_after_s: float = 6.0
    # ...and one unseen this long anywhere else is reported missing.
    lost_after_s: float = 90.0
    # A gap shorter than this between sightings is not shown to a manager.
    manager_unseen_grace_s: float = 3.0
    # An identity no gate ever verified is reported once it has this many claims.
    unverified_min_claims: int = 30
    # ...and stays listed (out of view) this many media seconds after its last sighting.
    unknown_keep_s: float = 45.0
    # ...but only while its search region is still at least this big (a region attested
    # down to nothing means a stale fragment, not a hidden person).
    unknown_min_region_m2: float = 1.0
    # An unnamed identity within this distance of a named employee, at the same moment
    # (media s), is the same body tracked twice — not a stranger.
    unknown_split_radius_m: float = 1.5
    unknown_split_window_s: float = 2.0
    # Someone this close to the entrance gate is about to be verified, not a stranger.
    # (covers the walk in from the staff door to the gate)
    gate_approach_radius_m: float = 5.5
    # A re-formed unknown track inherits the number of one last listed this recently
    # (media s), if it is within slack + walking speed x elapsed of where that one was.
    unknown_inherit_s: float = 30.0
    unknown_inherit_slack_m: float = 3.0
    unknown_walk_speed_m_s: float = 1.6
    # ...and such a re-formed track is listed after this many claims, not unverified_min_claims.
    unknown_reform_min_claims: int = 8
    # A camera whose peer-reported reputation falls below this is flagged.
    # Honest world nodes stay at ~1.0; a liar cannot fall much below ~0.7,
    # because lies placed inside its OWN zone contradict nobody.
    lying_reputation_alert: float = 0.85
    # ── showcase (apps/demo_dashboard/showcase.py) ──────────────────────
    # Gossip bytes/s per node are averaged over this many wall seconds.
    bandwidth_window_s: float = 10.0
    # "Ask every camera": each node resolves its own replica over the window
    # ending this many media seconds before the newest claim (so claims still
    # travelling round the ring by anti-entropy have arrived everywhere).
    replica_settle_s: float = 6.0
    replica_window_s: float = 60.0
    replica_timeout_s: float = 3.0
    # An unanchored identity in a node's answer counts as an unknown person
    # if it was seen within this many media seconds of the window's end.
    replica_unknown_recent_s: float = 10.0
    # A "where is" answer shows each camera's own view if "ask every camera"
    # ran within this many wall seconds.
    ask_reuse_s: float = 20.0
    # Out of view with at least this fraction of the search area inside the
    # camera-less aisles = "in the aisles" (and provably still inside).
    aisles_fraction_for_inside: float = 0.6
    # A camera node processing below this fraction of its target frame rate means
    # the demo machine is overloaded (the pages say so: people can be missed).
    overload_fps_fraction: float = 0.7
    # Comparison page: someone unseen this briefly (media s) still counts as placed on both sides.
    compare_recent_s: float = 10.0
    # The site's named camera-less aisles (configs/world/warehouse.yaml `areas`).
    aisles_area_name: str = "Storage aisles"
    # "Is anyone in <area>": the area is reported EMPTY only if healthy
    # attestations cover at least this fraction of it.
    area_clear_coverage: float = 0.85
    # A hidden person "could be" in an area if their search region overlaps it by this much.
    area_maybe_min_m2: float = 1.0
    # Written by scripts/run_world_demo.py: the exact command lines of each
    # camera node and of the central comparison server, so a node whose plug
    # was pulled can be powered back on from the dashboard.
    launch_manifest: str = "data/demo/world/launch.json"
    negative_evidence: NegativeEvidenceConfig = Field(default_factory=NegativeEvidenceConfig)
    plausibility: PlausibilityConfig = Field(default_factory=PlausibilityConfig)


def load_demo_config(path: Path) -> DemoDashboardConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return DemoDashboardConfig.model_validate(data or {})
