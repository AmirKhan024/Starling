"""Pydantic config models for a Starling node.

Every threshold that was hardcoded in V1 (0.60, 0.35, 120, 30, ...) is a
documented field here instead. Nothing in the identity/perception path may
read a magic number directly — it comes from one of these models, loaded
from configs/nodes/node-NN.yaml.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class PerceptionConfig(BaseModel):
    yolo_model: str = "yolov8n.pt"
    conf: float = 0.35
    embed_dim: int = 512
    batch_size: int = 8
    device: str = "auto"
    save_crops: bool = False
    crop_interval_s: float = 10.0
    # D-01 fix: selectable ReID backend. "osnet" (Market-1501-trained, falls
    # back to "pooled" if weights/torchreid are unavailable) is the only
    # backend permitted in a production node config. "v1_broken" is the
    # preserved untrained head, for starling_eval.reid_benchmark only.
    backend: str = "osnet"
    weights_path: str | None = None


class MatchConfig(BaseModel):
    sim_threshold: float = 0.60
    margin_threshold: float = 0.10
    lost_threshold_s: float = 120.0
    ema_alpha: float = 0.10
    # Deliberately not a real value yet — Prompt 2 (WP-01) replaces this
    # with a threshold chosen from a plotted ROC curve. Until then the
    # config says out loud that 0.60 above was a guess, not a measurement.
    threshold_source: str = "UNCALIBRATED-GUESS"
    # WP-06 Part 1 (starling_crdt.claims.ClaimSet.prune): claims older than
    # this are dropped, weakening the pure CRDT guarantee to "eventual
    # consistency within the retention window" — a deliberate trade-off,
    # documented in claims.py, that doubles as spec §13's short-retention
    # privacy measure.
    retention_window_s: float = 3600.0
    # WP-06 Part 4b (D-10): the resolver sweeps only the last
    # `resolve_window_s` seconds of claims during normal operation, and
    # does a full recompute over the retention window only when a
    # partition heals — re-running the full resolver on every claim is
    # O(n^2) and will not hold at scale.
    resolve_window_s: float = 300.0
    # WP-06 Part 2 (D-08 fix): the identity prototype is a small gallery
    # of recent high-quality embeddings, never a single mean vector (a
    # mean cannot express anchor -> propagate -> decay -> re-anchor and
    # cannot be merged — you cannot recover what was averaged).
    gallery_size: int = 5


class NetConfig(BaseModel):
    listen_port: int = 5555
    neighbours: list[str] = Field(default_factory=list)  # "host:port"
    gossip_interval_s: float = 2.0


class GeometryConfig(BaseModel):
    # WP-05: shared by every node in a deployment (one floor plan), unlike
    # calib_path which is per-camera. Null until a floor plan exists.
    navmesh_path: str | None = None
    cell_size_m: float = 0.25


class CoverageConfig(BaseModel):
    """WP-09 Part 1 (C4 flagship): per-node coverage self-assessment.

    `roi_polygon` and `watched_boundary_ids` are empty by default — a node
    with no ROI configured cannot assess coverage or emit an attestation at
    all (starling_perception.coverage.CoverageAssessor degrades to "fully
    open, nothing to protect" rather than guessing), mirroring D-09's
    "an unconfigured node's claims are unverifiable" posture instead of
    silently assuming full coverage.
    """

    roi_polygon: list[tuple[float, float]] = Field(default_factory=list)  # floor metres
    watched_boundary_ids: list[int] = Field(default_factory=list)  # NavMesh.boundaries keys this node attests about
    tau_attest: float = 0.7
    # WP-09 task 1(a): EMA update rate for the online background model.
    # Small = slow to absorb foreground into the background, which is what
    # makes a long-persisting occluder (a parked pallet) register as
    # "static occlusion" for a sustained span of ticks rather than
    # vanishing into the background after one frame.
    background_alpha: float = 0.02
    bg_diff_threshold: float = 25.0  # 0-255 grey-level delta counted as foreground
    blob_area_threshold: int = 500  # min. connected foreground blob size, pixels
    # COCO80 class ids: car=2, truck=7, bench=13 — forklift/pallet proxies
    # (WP-09 task 1(b)); starling_perception.detector.PERSON_CLASS_ID=0 is
    # deliberately absent, a tracked person is never itself "occlusion".
    occluder_class_ids: list[int] = Field(default_factory=lambda: [2, 7, 13])
    illum_clip_low: int = 10
    illum_clip_high: int = 245
    illum_exposure_weight: float = 0.5
    illum_clip_weight: float = 0.3
    illum_contrast_weight: float = 0.2
    illum_contrast_norm: float = 40.0  # local RMS contrast treated as "fully textured" (score saturates to 1.0)
    ks_window: int = 200  # rolling baseline sample count for detector_health's confidence-distribution KS test


class AttestConfig(BaseModel):
    """WP-09 Part 2: attestation emission timing + admission thresholds."""

    tick_interval_s: float = 2.0  # media-time interval between attestation emissions
    # Mirrors CoverageConfig.tau_attest — the same operating threshold,
    # duplicated here because starling_attest.admission.admissible() is
    # tested and used independently of a CoverageAssessor/CoverageConfig
    # and needs its own self-sufficient config object.
    tau_attest: float = 0.7
    # admission.py rejects an attestation older than this relative to the
    # admitting node's current media time.
    freshness_window_s: float = 10.0
    # admission.py's reputation floor. WP-10 (reputation, not built yet)
    # is what will ever lower a real node's score below this in practice —
    # this session's Part 3 (detect_omission) only emits the signal
    # reputation will consume, per CLAUDE.md rule 3 for this session.
    min_reputation: float = 0.0


class NegativeEvidenceConfig(BaseModel):
    """WP-09 Part 3: candidate-belief fusion over the navmesh."""

    # Ablation switch (WP-09 rule 2): False = positive-evidence-only arm.
    # Every C4 metric is defined as the difference between the two arms.
    negative_evidence_enabled: bool = True
    # Mirrors CoverageConfig.tau_attest / AttestConfig.tau_attest (see
    # AttestConfig's docstring for why this duplication is deliberate):
    # starling_attest.negative_evidence.CandidateBelief re-derives
    # admissibility itself at the point mass actually gets zeroed.
    tau_attest: float = 0.7
    v_max_m_s: float = 1.6  # matches starling_geometry.reachability.DEFAULT_V_MAX_M_S
    eps: float = 1e-6  # belief-mass threshold for area_m2()/mask()
    likelihood_sigma_m: float = 1.0  # Gaussian sigma for apply_observation when a claim carries no pos_sigma
    min_omission_corroborators: int = 2  # detect_omission: distinct corroborating nodes required


class PlausibilityConfig(BaseModel):
    """WP-10 Part 2 (C2): `starling_consensus.plausibility.check` thresholds.

    Mirrors `NegativeEvidenceConfig.v_max_m_s` / `AttestConfig.tau_attest`'s
    own precedent of a small, deliberate duplication across config models
    rather than a cross-package import — `starling_consensus` stays
    self-sufficient and independently testable.
    """

    v_max_m_s: float = 1.6  # matches starling_geometry.reachability.DEFAULT_V_MAX_M_S
    # Corroboration position-match tolerance, added to the claim's own
    # pos_sigma — how far apart two nodes' reported positions may be and
    # still count as "the same person", not a contradiction.
    pos_sigma_m: float = 0.3
    corroboration_pass_threshold: float = 0.5
    # HLC vs. admitting-node "now": a claim older than this when it
    # actually arrives is a replay candidate (Appendix A.5 / docs/threat_model.md).
    # TBD-drift note in docs/threat_model.md §1 applies here too — this is
    # an engineering default, not yet informed by a measured clock offset.
    replay_window_s: float = 10.0
    # The three graded checks' weights in the overall score. Reachability
    # is never weighted in — it is a hard fail, handled separately.
    kinematics_weight: float = 0.34
    corroboration_weight: float = 0.33
    freshness_weight: float = 0.33
    # Overall graded score floor for PlausibilityResult.passed (the s_ij in
    # Appendix A.5 that reputation.py's EWMA update consumes).
    pass_score_threshold: float = 0.5


class ReputationConfig(BaseModel):
    """WP-10 Part 2 (C2) / Appendix A.5: `starling_consensus.reputation.ReputationTable`."""

    alpha: float = 0.05
    r_min: float = 0.05  # floor, never 0 — a repaired node can recover (see reputation.py)
    r_initial: float = 1.0  # a node with no observations yet is trusted, not suspected
    # WP-07 (C6) weak-signal cap: a topology distribution shift is equally
    # consistent with an innocent environment change as with misbehaviour
    # (see reputation.py::penalise_topology_shift), so whatever weight a
    # caller passes is hard-clamped here — this can never, by itself, drive
    # a reputation anywhere near r_min the way a failed plausibility check can.
    topology_shift_max_weight: float = 0.15


class TopologyConfig(BaseModel):
    """WP-07 (C6): `starling_topology.learner.TopologyLearner`.

    Learning topology from a handoff the resolver itself was barely
    confident about would teach the system its own mistakes, so
    `handoff_confidence_min` gates what `observe_handoff` accepts at all —
    independent of, and stricter than, `MatchConfig.margin_threshold`.
    """

    handoff_confidence_min: float = 0.5
    # Edge existence rule (WP-07): count >= k_min AND the fitted sigma is
    # tighter than a uniform null over the same observed range. k_min=5
    # deliberately low enough that the "5 random-uniform transits" test
    # exercises the sigma test, not just this count floor.
    k_min: int = 5
    # Fitted RAW-seconds sigma must be below this fraction of the uniform
    # null's sigma ((max-min)/sqrt(12), raw seconds) to count as a real
    # edge (a peaked distribution), not a spurious near-flat spread.
    # Chosen from numerical separation: a genuinely uniform raw sample's
    # ratio sits at/above ~1.0 at every sample size tested (n=5..100000),
    # a log-normal corridor's sits at ~0.5-0.8 (see learner.py module
    # docstring for why the test runs in raw space, not log space).
    null_sigma_ratio: float = 0.85
    # detect_shift: windowed mean-shift (CUSUM-style) test. Each half of
    # the most recent `2 * shift_window` raw observations is compared;
    # a real environment/behaviour change should be visible mid-window.
    shift_window: int = 15
    shift_threshold_sigma: float = 3.0
    # Raw weak-signal weight `apply_shift_penalties` requests from
    # `ReputationTable.penalise_topology_shift` — the table itself clamps
    # this again at `ReputationConfig.topology_shift_max_weight`, so this
    # value only matters below that ceiling.
    topology_shift_weight: float = 0.3


class AttackConfig(BaseModel):
    """WP-10 Part 3 (C2): `starling_consensus.attacks.AttackInjector` defaults
    and the node's runtime control endpoint (demo/eval only).
    """

    attack: str = "none"  # none | fabricate | suppress | replay | mixed
    intensity: float = 0.0
    replay_age_s: float = 30.0  # how far back a replayed claim's embedded HLC is dated
    # apps/node.py's control HTTP endpoint (listen_port + 1000) — the
    # "Make node N lie" demo button / scenario runner hook. Demo-only.
    enable_control_endpoint: bool = True
    # WP-13: the interface the control endpoint binds. "127.0.0.1" (the
    # default) is correct and safe when the dashboard runs as the SAME OS
    # process's neighbour on the SAME host (configs/nodes/local/*.yaml) —
    # loopback is shared there. It is WRONG inside Docker: each container
    # has its own independent loopback namespace, so a dashboard container
    # can never reach another container's 127.0.0.1 no matter what port is
    # published. The docker-hostname node configs (configs/nodes/node-NN
    # .yaml) override this to "0.0.0.0", which only exposes the control
    # port on the private `starling-net` bridge network (never the public
    # internet) — still not exposed beyond this deployment's own containers.
    control_bind_host: str = "127.0.0.1"


class AggregateConfig(BaseModel):
    """WP-10 Part 4 (C2): `starling_consensus.aggregate.aggregate_position`."""

    trimmed_beta: float = 0.2  # fraction discarded from EACH end by trimmed_mean
    # Krum's "n - f - 2 nearest neighbours" — f is the assumed max number
    # of Byzantine claims among the candidates passed to aggregate_position
    # in a single call, an aggregation-time parameter, not a global system
    # constant (a real deployment does not know the true f in advance).
    krum_f: int = 1


class SimNodeConfig(BaseModel):
    """Only meaningful when `NodeConfig.source == "sim"` (STATUS.md Step
    4): where this node's `starling_sim.node_client.SimNodeSource`
    connects to reach the simulator process's ZMQ PUB socket
    (`starling_sim.config.SimulatorConfig.bind_endpoint`). Defined here
    rather than imported from `starling_sim`, matching every other
    sub-model in this file (`PerceptionConfig`, `MatchConfig`, ...): a
    node's config schema is defined once, in `starling_node`, regardless
    of which package actually consumes a given field.
    """

    connect_endpoint: str = "tcp://127.0.0.1:5560"


class NodeConfig(BaseModel):
    node_id: int
    name: str
    # Video source: file path, RTSP URL, webcam index (as a string) — or
    # the literal string "sim", meaning this node reads from a running
    # starling_sim simulator process (see `sim` below) instead of a real
    # or recorded camera. Kept a free-form string rather than an enum so
    # existing video-path configs need no schema migration.
    source: str
    is_chokepoint: bool = False
    db_path: str
    calib_path: str | None = None
    # Only read when source == "sim". Left at its default even for a
    # video-path config — harmless, since apps/node.py never looks at it
    # unless source == "sim".
    sim: SimNodeConfig = Field(default_factory=SimNodeConfig)
    # D-03 (starling_net.timebase.MediaClock): unix seconds marking t=0 of
    # this node's recorded source. ALL nodes replaying the same scenario
    # must share the same stream_epoch, or their media times sit on
    # different timelines and no cross-camera reasoning is meaningful. A
    # scenario runner is what injects one shared value into every node's
    # config for a given run; 0.0 here is only a single-node-testing default.
    stream_epoch: float = 0.0
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    match: MatchConfig = Field(default_factory=MatchConfig)
    net: NetConfig = Field(default_factory=NetConfig)
    geometry: GeometryConfig = Field(default_factory=GeometryConfig)
    coverage: CoverageConfig = Field(default_factory=CoverageConfig)
    attest: AttestConfig = Field(default_factory=AttestConfig)
    negative_evidence: NegativeEvidenceConfig = Field(default_factory=NegativeEvidenceConfig)
    plausibility: PlausibilityConfig = Field(default_factory=PlausibilityConfig)
    reputation: ReputationConfig = Field(default_factory=ReputationConfig)
    attack: AttackConfig = Field(default_factory=AttackConfig)
    aggregate: AggregateConfig = Field(default_factory=AggregateConfig)
    topology: TopologyConfig = Field(default_factory=TopologyConfig)

    @staticmethod
    def write_template(path: Path, node_id: int) -> None:
        """Write a fully commented default YAML config for one node."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        template = f"""\
# Starling node config — node-{node_id:02d}
# Every threshold below has a documented default in
# packages/starling_node/config.py. Edit here, not in code.

node_id: {node_id}
name: "node-{node_id:02d}"

# Video source: file path, RTSP URL, webcam index (as a string), or the
# literal string "sim" (STATUS.md Step 4: reads from a running
# starling_sim simulator process instead of a camera — see `sim:` below).
source: "data/videos/cam{node_id}.mp4"

# Set true only for a node whose FOV covers a chokepoint (WP-12: face
# recognition runs there and nowhere else).
is_chokepoint: false

# Per-node SQLite replica. Never shared with another node (CLAUDE.md rule 1).
db_path: "data/nodes/node-{node_id:02d}/local.db"

# Path to this camera's intrinsics/extrinsics YAML (WP-05). Null until
# calibration is done.
calib_path: null

# Only read when source == "sim" (STATUS.md Step 4).
sim:
  connect_endpoint: "tcp://127.0.0.1:5560"   # the simulator process's ZMQ PUB socket

# Unix seconds marking t=0 of this node's recorded source. ALL nodes
# replaying the same scenario must use the SAME stream_epoch, or their
# media times sit on different timelines (D-03). A scenario runner injects
# one shared value per run; 0.0 here is only a single-node-testing default.
stream_epoch: 0.0

perception:
  yolo_model: "yolov8n.pt"   # YOLOv8 variant: n/s/m/l/x.pt
  conf: 0.35                 # detection confidence threshold
  embed_dim: 512             # ReID embedding dimensionality
  batch_size: 8              # embedding extraction batch size
  device: "auto"             # auto | cuda | cpu
  save_crops: false          # D-14: off by default, privacy + disk usage
  crop_interval_s: 10.0      # min seconds between saved crops per identity
  backend: "osnet"           # osnet (falls back to pooled) | pooled | v1_broken
  weights_path: null         # Market-1501-trained OSNet weights (D-01 fix)

match:
  sim_threshold: 0.60        # cosine similarity cutoff for identity match
  margin_threshold: 0.10     # required separation over the second-best match
  lost_threshold_s: 120.0    # seconds absent before a person is marked LOST
  ema_alpha: 0.10            # embedding running-average blend weight
  # "UNCALIBRATED-GUESS" until Prompt 2 (WP-01) picks sim_threshold from a
  # plotted ROC curve. Do not treat 0.60 above as measured until this changes.
  threshold_source: "UNCALIBRATED-GUESS"
  retention_window_s: 3600.0   # claims older than this are pruned (WP-06)
  resolve_window_s: 300.0      # sliding-window incremental resolution (WP-06)
  gallery_size: 5               # embeddings kept per identity prototype (WP-06, D-08)

net:
  listen_port: {5555 + node_id}          # this node's gossip PUB port
  neighbours: []               # "host:port" list — configured, never full-mesh
  gossip_interval_s: 2.0       # anti-entropy gossip round interval

geometry:
  navmesh_path: null           # GeoJSON floor plan (WP-05), shared across all nodes
  cell_size_m: 0.25            # navmesh grid resolution

coverage:
  roi_polygon: []               # this node's floor ROI, [[x,y], ...] metres; empty = attests nothing (WP-09)
  watched_boundary_ids: []      # NavMesh.boundaries ids this node can attest crossings for
  tau_attest: 0.7                # attest_confidence floor; below this, emit NOTHING (silence != evidence)
  background_alpha: 0.02         # online background model EMA rate
  bg_diff_threshold: 25.0        # grey-level delta counted as foreground
  blob_area_threshold: 500       # min. connected foreground blob size, pixels
  occluder_class_ids: [2, 7, 13] # COCO80 car/truck/bench — forklift/pallet proxies
  illum_clip_low: 10
  illum_clip_high: 245
  illum_exposure_weight: 0.5
  illum_clip_weight: 0.3
  illum_contrast_weight: 0.2
  illum_contrast_norm: 40.0
  ks_window: 200                 # detector_health confidence-distribution KS baseline size

attest:
  tick_interval_s: 2.0           # media-time interval between attestation emissions
  tau_attest: 0.7                 # mirrors coverage.tau_attest for admission.py's own use
  freshness_window_s: 10.0       # admission.py rejects attestations older than this
  min_reputation: 0.0            # admission.py reputation floor (WP-10 populates real scores)

negative_evidence:
  negative_evidence_enabled: true  # ablation switch — every C4 metric is with/without this
  tau_attest: 0.7                 # mirrors coverage.tau_attest for CandidateBelief's own use
  v_max_m_s: 1.6
  eps: 1.0e-6
  likelihood_sigma_m: 1.0
  min_omission_corroborators: 2

plausibility:
  v_max_m_s: 1.6
  pos_sigma_m: 0.3                # corroboration position-match tolerance (WP-10)
  corroboration_pass_threshold: 0.5
  replay_window_s: 10.0           # TBD-drift note: docs/threat_model.md §1
  kinematics_weight: 0.34
  corroboration_weight: 0.33
  freshness_weight: 0.33
  pass_score_threshold: 0.5

reputation:
  alpha: 0.05                     # EWMA update rate (Appendix A.5)
  r_min: 0.05                     # floor — never 0, so a repaired node can recover
  r_initial: 1.0

attack:
  attack: "none"                  # none | fabricate | suppress | replay | mixed (WP-10)
  intensity: 0.0
  replay_age_s: 30.0
  enable_control_endpoint: true   # demo-only HTTP control on listen_port+1000
  control_bind_host: "127.0.0.1"  # "0.0.0.0" in the docker-hostname node configs — see config.py

aggregate:
  trimmed_beta: 0.2               # fraction discarded from EACH end by trimmed_mean
  krum_f: 1                       # assumed max Byzantine claims per aggregate_position() call

topology:
  handoff_confidence_min: 0.5     # WP-07: handoffs below this are never learned from
  k_min: 5                        # min. observations before a node-pair can become an edge
  null_sigma_ratio: 0.85          # fitted RAW-seconds sigma must be this fraction of the uniform-null sigma
  shift_window: 15                # windowed mean-shift test half-window size
  shift_threshold_sigma: 3.0
  topology_shift_weight: 0.3      # weak-signal weight requested from reputation (further clamped there)
"""
        path.write_text(template, encoding="utf-8")


def load_node_config(path: Path) -> NodeConfig:
    """Load and validate a NodeConfig from a YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return NodeConfig.model_validate(data)
