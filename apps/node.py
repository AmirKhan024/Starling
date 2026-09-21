"""apps/node.py
---------------
Standalone Starling node process (D-04, D-05, D-07 — STARLING_BUILD_STATE.md
§2, §4.1). One node = one OS process = one camera = one node-local SQLite
replica (`LocalStore`) = one gossip socket (`starling_net.gossip.GossipNode`,
wired in WP-04). CLAUDE.md rule 1: never a thread, never a shared database
handle. No module here imports another node's store, config, or db_path —
that guardrail is enforced by tests/test_no_coordinator.py.

Usage
-----
    python apps/node.py --config configs/nodes/node-00.yaml [--speed N] [--max-frames N] [--keys-dir DIR]

If this node's keypair isn't found under `--keys-dir` (default
configs/keys/, populated by `python -m starling_net.keys --generate N`),
the node runs with gossip disabled and a loud warning rather than failing
— useful for local perception-only testing (e.g. tests/test_node_process.py).

Two input sources (STATUS.md Step 4)
-------------------------------------
`cfg.source` is either a video path/RTSP URL/webcam index (unchanged since
WP-01) or the literal string `"sim"`, meaning this node reads from a
running `starling_sim` simulator process instead of a camera —
`_run_sim` replaces `PacedSource`/`NodePerception`/calibration with
`starling_sim.node_client.SimNodeSource`, but feeds the exact same
downstream path (`store.append_local_observation`, the attack injector,
gossip publish) the video path already does. `NodePerception`/`PacedSource`
(and the torch/ultralytics they pull in) are imported lazily, inside
`_run_video` only, so a sim-only deployment never needs torch installed
(requirements-sim.txt).

Everything below the input source is genuinely shared between the two
paths: periodic anti-entropy (recovers claims missed during an
application-level partition — `starling_consensus.attacks.PartitionControl`,
also new in Step 4), a periodic plausibility/reputation pass over this
node's own merged claim set (so "a lying node's reputation drops" is
visible from inside the mesh, not only in the dashboard's separate
observer), and gossiped `ReputationUpdate`s.
"""

from __future__ import annotations

import argparse
import bisect
import signal
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import structlog

from starling_attest.attestation import Attestor
from starling_consensus.attacks import AttackInjector, ControlServer, PartitionControl
from starling_consensus.plausibility import CorroboratedState, PlausibilityConfig
from starling_consensus.plausibility import check as plausibility_check
from starling_consensus.reputation import ReputationTable
from starling_crdt.claims import ClaimSet, claim_order_key
from starling_geometry.calibration import CameraCalibration, bbox_floor_point
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_net.anti_entropy import AntiEntropy, VersionVector, chunk_by_bytes
from starling_net.gossip import GossipNode
from starling_net.keys import DEFAULT_KEYS_DIR, NodeKeys, load_keys
from starling_net.logging import get_logger, setup_logging
from starling_net.partition import PartitionTracker
from starling_net.timebase import MediaClock
from starling_node.config import NodeConfig, load_node_config
from starling_perception.coverage import CoverageAssessor, DetectorStats
from starling_proto.convert import (
    claim_proto_to_record,
    make_attestation_envelope,
    make_claim_envelope,
    make_reputation_envelope,
    record_to_claim_proto,
)
from starling_proto.generated import starling_pb2
from starling_store.identity_store import LocalStore

_HOUSEKEEPING_EVERY_N_FRAMES = 30
# Sim ticks arrive much coarser than video frames (tick_hz is typically
# 5, not ~30) — a separate, smaller cadence keeps housekeeping (partition
# detection, anti-entropy, reputation) running at a comparable real-time
# rate rather than once every 6 seconds.
_SIM_HOUSEKEEPING_EVERY_N_TICKS = 5
_SIM_RECV_TIMEOUT_MS = 500
# How far apart (media-time seconds) two different nodes' claims may be
# and still count as candidate corroborators of each other in the
# in-node plausibility pass (_ReputationLoop) below.
_CORROBORATION_WINDOW_S = 5.0
# A track counts as ESTABLISHED (usable as a reference for a new track's
# first claims) once this many of its claims were accepted.
_MIN_ESTABLISHED_CLAIMS = 3
_MAX_TRACKS = 256
# Anti-entropy delta replies are chunked by BYTE budget
# (starling_net.anti_entropy.chunk_by_bytes), not a fixed claim count: the
# wire cap (starling_proto.limits.MAX_MESSAGE_BYTES, 8192B) applies per
# envelope, and how many claims fit depends on the embedding dimension
# (~2.2KB each at 512-d float32, ~0.5KB at the sim's 64-d).
# _ReputationLoop's minimum gap between corroborated-position baseline
# refreshes. See _ReputationLoop.run_pass's docstring for why a dt_s this
# small (e.g. one sim tick apart) makes the REACHABILITY hard-fail
# unreliable rather than merely noisy.
_MIN_BASELINE_REFRESH_S = 2.0
# Matches starling_node.config.NodeConfig.write_template's
# `listen_port = 5555 + node_id` convention, followed by every generated
# config in this project. GossipNode has no relay/forwarding logic yet
# (STARLING_BUILD_STATE.md §4.1), so a received envelope's sender_node_id
# is always the direct peer that published it — this mapping only tells
# PartitionTracker which node_ids to expect from the configured neighbour
# addresses, it does not route anything.
_BASE_GOSSIP_PORT = 5555


def _neighbour_node_ids(neighbours: list[str]) -> list[int]:
    return [int(addr.rsplit(":", 1)[1]) - _BASE_GOSSIP_PORT for addr in neighbours]


def _load_calibration(cfg, log) -> Optional[CameraCalibration]:
    """This node's `CameraCalibration`, or `None` with a loud warning if
    `cfg.calib_path` isn't set (D-09 / WP-05: an uncalibrated node cannot
    produce a world_pos, and a claim without one is unverifiable —
    §5.1's hard rule). Do not fail silently — a positionless claim that
    quietly bypasses the plausibility gate is exactly the kind of bug
    that survives to the viva. Factored out of `run()` so it's testable
    without loading YOLO weights. Never called for a `source: "sim"` node
    (the simulator supplies world_pos directly — see `run()`).
    """
    if cfg.calib_path:
        return CameraCalibration.from_yaml(cfg.calib_path)
    log.warning(
        "node_uncalibrated",
        node_id=cfg.node_id,
        hint="claims will be unverifiable; C2/C3/C4 are disabled for this node",
    )
    return None


def _load_navmesh(cfg, log) -> Optional[NavMesh]:
    """This node's `NavMesh`, or `None` with a loud warning if
    `cfg.geometry.navmesh_path` isn't set — C4 attestation (WP-09) has
    nothing to reason about without one. Factored out for the same
    testability reason as `_load_calibration`.
    """
    if cfg.geometry.navmesh_path:
        return NavMesh.from_geojson(cfg.geometry.navmesh_path, cell_size_m=cfg.geometry.cell_size_m)
    log.warning(
        "node_no_navmesh",
        node_id=cfg.node_id,
        hint="C4 coverage attestation is disabled for this node",
    )
    return None


class _ReputationLoop:
    """Periodic in-node plausibility + reputation pass over this node's
    own merged claim set (STATUS.md Step 4). Before this existed, only
    the dashboard's separate `GossipObserver` ever computed reputation —
    purely from what it overheard, never from inside a node. This is what
    makes "a lying node's reputation drops" a fact a node itself derives
    and gossips (`ReputationUpdate`), not only something the dashboard
    happens to notice.

    Simplification, stated plainly: the baseline is this node's own most
    recently ACCEPTED position on the SAME (source node, local_track_id)
    track — not a per-identity kinematics model. A node watching two people
    at once interleaves their claims, so a single per-node baseline would
    "teleport" between them and wrongly fail an honest node. A claim on a
    track with no baseline yet (a new person, or a fabricated claim, which
    always carries a fresh track id) is graded against that node's
    ESTABLISHED tracks instead (>= `_MIN_ESTABLISHED_CLAIMS` accepted
    claims): reachable from any of them passes, from none of them fails. So
    a fabricated teleport is still caught, while one fabrication can never
    become the baseline a later one is graded against (it never gets to
    be an established track). A baseline only advances on a claim that
    itself passed.
    """

    def __init__(
        self,
        node_id: int,
        store: LocalStore,
        geometry: Optional[ReachabilityModel],
        cfg: PlausibilityConfig,
        reputation_table: ReputationTable,
        min_baseline_refresh_s: float = _MIN_BASELINE_REFRESH_S,
        lookback_s: Optional[float] = None,
    ) -> None:
        # None = grade the whole merged claim set every pass (what a node
        # does); a number = only claims within that many media seconds of
        # `now_t_media` (the demo dashboard, which runs for a long time).
        self.lookback_s = lookback_s
        self.node_id = node_id
        self.store = store
        self.geometry = geometry
        self.cfg = cfg
        self.reputation_table = reputation_table
        self.min_baseline_refresh_s = min_baseline_refresh_s
        # (source node, local_track_id) -> latest accepted position/time,
        # and how many of that track's claims have been accepted so far.
        self._last_position: dict[tuple[int, Any], tuple[float, float]] = {}
        self._last_t_media: dict[tuple[int, Any], float] = {}
        self._accepted: Counter[tuple[int, Any]] = Counter()
        self._evaluated_claim_ids: set[str] = set()
        # Per source node: claims graded / claims that failed plausibility
        # (surfaced by the demo dashboard).
        self.evaluated_by_node: Counter[int] = Counter()
        self.rejected_by_node: Counter[int] = Counter()

    def run_pass(self, now_t_media: float) -> None:
        """Evaluate every not-yet-evaluated remote claim against the
        baseline `last_position`/`last_t_media` this pass STARTED with —
        never updated more often than once every `min_baseline_refresh_s`
        (see `pending_baseline` below), and never claim-by-claim within
        the same pass. Two things make a very short `dt_s` (a fraction of
        a second, e.g. between consecutive 5Hz sim ticks) unreliable for
        the REACHABILITY hard-fail specifically, not just noisy: (1)
        `ReachabilityModel.distance_field` is itself a GRID-quantized
        geodesic distance (`NavMesh.cell_size`, 0.25m by default) — over a
        true displacement of a few tens of centimetres, quantization
        alone can round the measured distance up by a whole cell or more;
        (2) each claim's own position-noise sigma
        (`starling_sim.config.SimulatorConfig.pos_noise_sigma_m`) is
        comparable in size to one tick's worth of real movement at that
        rate. Both errors are roughly CONSTANT in metres, so they shrink
        to noise as a fraction of the true displacement once `dt_s` is
        large enough — keeping the baseline fixed for at least
        `min_baseline_refresh_s` between refreshes is what guarantees
        that, while a fabricated claim's tens-of-metres jump still fails
        by a wide margin regardless of how fresh the baseline is.
        """
        if self.lookback_s is None:
            claims = ClaimSet(self.store).ordered()
        else:
            claims = sorted(
                self.store.local_observations(now_t_media - self.lookback_s, float("inf")),
                key=claim_order_key,
            )
        # Corroborator lookup by media-time window via bisect, instead of
        # rescanning every claim for every new claim (that was O(N^2) and
        # wedged a node's main loop for many seconds when a post-partition
        # anti-entropy catch-up delivered a large backlog at once).
        by_time = sorted(range(len(claims)), key=lambda i: claims[i]["t_media"])
        times = [claims[i]["t_media"] for i in by_time]
        pending_baseline: dict[tuple[int, Any], tuple[tuple[float, float], float]] = {}
        pending_provisional: dict[tuple[int, Any], tuple[tuple[float, float], float]] = {}
        newly_accepted: Counter[tuple[int, Any]] = Counter()

        for claim in claims:
            claim_id = claim["claim_id"]
            source_node = claim["node_id"]
            if source_node == self.node_id or claim_id in self._evaluated_claim_ids:
                continue
            self._evaluated_claim_ids.add(claim_id)

            lo = bisect.bisect_left(times, claim["t_media"] - _CORROBORATION_WINDOW_S)
            hi = bisect.bisect_right(times, claim["t_media"] + _CORROBORATION_WINDOW_S)
            corroborators = [
                claims[i]
                for i in sorted(by_time[lo:hi])  # keep the canonical claim order
                if claims[i]["node_id"] != source_node
            ]
            track = (source_node, claim.get("local_track_id"))

            # Baseline candidates, all fixed as of the START of this pass.
            # A claim that arrived (via gossip or an anti-entropy catch-up
            # round) chronologically AT OR BEFORE a baseline is not
            # something that baseline can meaningfully grade — the
            # resulting dt_s would be ~0, giving even a small position
            # difference an enormous implied speed. That is an
            # out-of-delivery-order artifact, not evidence of a physically
            # implausible jump, so such a baseline is simply not used
            # (reachability/kinematics skipped; corroboration/freshness
            # still apply).
            own_t = self._last_t_media.get(track)
            if own_t is not None:
                candidates = [(self._last_position[track], own_t)] if claim["t_media"] > own_t else []
            else:
                candidates = [
                    (self._last_position[k], self._last_t_media[k])
                    for k in self._last_position
                    if k[0] == source_node
                    and self._accepted[k] >= _MIN_ESTABLISHED_CLAIMS
                    and claim["t_media"] > self._last_t_media[k]
                ]

            result = None
            for position, t_baseline in candidates or [(None, None)]:
                state = CorroboratedState(
                    last_position=position,
                    last_t_media=t_baseline,
                    corroborating_claims=corroborators,
                    now_physical_ms=int(now_t_media * 1000),
                )
                attempt = plausibility_check(claim, state, self.geometry, self.cfg)
                if result is None or attempt.passed:
                    result = attempt
                if attempt.passed:
                    break
            assert result is not None
            self.reputation_table.observe(source_node, result)
            self.evaluated_by_node[source_node] += 1
            if not result.passed:
                self.rejected_by_node[source_node] += 1

            has_pos = claim.get("world_x") is not None and claim.get("world_y") is not None
            if result.passed:
                newly_accepted[track] += 1
            if has_pos:
                position_t = ((claim["world_x"], claim["world_y"]), claim["t_media"])
                if track not in self._last_position:
                    pending_provisional.setdefault(track, position_t)  # first sighting of this track
                elif result.passed and claim["t_media"] - own_t >= self.min_baseline_refresh_s:
                    pending_baseline[track] = position_t

        for track, (position, t_media) in {**pending_provisional, **pending_baseline}.items():
            self._last_position[track] = position
            self._last_t_media[track] = t_media
        self._accepted.update(newly_accepted)
        self._prune_tracks()

    def _prune_tracks(self) -> None:
        """Bound memory: fabricated claims each open a fresh one-claim track."""
        if len(self._last_t_media) <= _MAX_TRACKS:
            return
        oldest_first = sorted(self._last_t_media, key=self._last_t_media.get)  # type: ignore[arg-type]
        for track in oldest_first[: len(self._last_t_media) - _MAX_TRACKS]:
            self._last_position.pop(track, None)
            self._last_t_media.pop(track, None)
            self._accepted.pop(track, None)


@dataclass
class _RunContext:
    """Everything genuinely shared between `_run_video` and `_run_sim` —
    built once in `run()` before branching on `cfg.source`."""

    cfg: NodeConfig
    navmesh: Optional[NavMesh]
    store: LocalStore
    tracker: PartitionTracker
    anti_entropy: AntiEntropy
    reputation_loop: _ReputationLoop
    reputation_table: ReputationTable
    injector: AttackInjector
    gossip: Optional[GossipNode]
    log: Any
    shutdown: dict[str, bool]
    max_frames: Optional[int]


def _publish_claims(ctx: _RunContext, records: list[dict], t_media: float) -> None:
    outgoing_records = ctx.injector.apply_to_claims(records, t_media, ctx.navmesh)
    if ctx.gossip is not None:
        for record in outgoing_records:
            claim = record_to_claim_proto(record)
            envelope = make_claim_envelope(claim, sender_node_id=ctx.cfg.node_id)
            ctx.gossip.publish(envelope)


def _publish_attestation(ctx: _RunContext, attestation) -> None:
    if attestation is None or ctx.gossip is None:
        return
    for outgoing in ctx.injector.apply_to_attestations([attestation]):
        envelope = make_attestation_envelope(outgoing, sender_node_id=ctx.cfg.node_id)
        ctx.gossip.publish(envelope)


def _run_housekeeping(ctx: _RunContext, t_media: float, frames: int, extra_stats: dict[str, Any]) -> None:
    ctx.tracker.tick()
    event = ctx.tracker.check_partition_event()
    structlog.contextvars.bind_contextvars(coverage_completeness=ctx.tracker.coverage_completeness())
    if event is not None:
        ctx.log.warning(
            event,
            reachable_neighbours=ctx.tracker.reachable_neighbours(),
            configured_neighbours=ctx.tracker.neighbour_node_ids,
        )

    ctx.anti_entropy.tick()
    ctx.reputation_loop.run_pass(t_media)
    if ctx.gossip is not None:
        for update in ctx.reputation_table.to_updates():
            envelope = make_reputation_envelope(update, sender_node_id=ctx.cfg.node_id)
            ctx.gossip.publish(envelope)

    ctx.log.info("node_housekeeping", frames=frames, **extra_stats)


def _run_video(
    ctx: _RunContext, calib: Optional[CameraCalibration], speed: float, keys: Optional[NodeKeys]
) -> int:
    # Imported here, not at module level, so a source: "sim" node never
    # pulls in torch/ultralytics (NodePerception -> detector/embedder) —
    # STATUS.md Step 1's deferred decision, completed here in Step 4.
    from starling_perception.pipeline import NodePerception
    from starling_perception.source import PacedSource

    cfg = ctx.cfg
    media_clock = MediaClock.from_video(cfg.source, stream_epoch=cfg.stream_epoch)
    source = PacedSource(cfg.source, media_clock, speed=speed, realtime=True)
    perception = NodePerception(cfg.perception, node_id=cfg.node_id)

    attestor: Optional[Attestor] = None
    recent_confidences: "deque[float]" = deque(maxlen=cfg.coverage.ks_window)
    baseline_confidences: list[float] = []
    if calib is not None and ctx.navmesh is not None and cfg.coverage.roi_polygon:
        coverage_assessor = CoverageAssessor(cfg=cfg.coverage, calibration=calib, navmesh=ctx.navmesh)
        attestor = Attestor(node_id=cfg.node_id, coverage_assessor=coverage_assessor, cfg=cfg.attest, keys=keys)
    else:
        ctx.log.warning(
            "node_attestation_disabled",
            node_id=cfg.node_id,
            hint="calibration, a navmesh, and coverage.roi_polygon are all required for C4 attestation",
        )

    frame_count = 0
    for frame, frame_idx, t_media in source:
        if ctx.shutdown["requested"]:
            ctx.log.info("node_shutdown_requested", frames=frame_count)
            break

        observations = perception.process(frame, t_media)
        records = []
        for obs in observations:
            world_pos = None
            pos_sigma = None
            if calib is not None:
                u, v = bbox_floor_point(obs.bbox)
                world_pos = calib.image_to_floor(u, v)
                pos_sigma = calib.position_sigma(obs.bbox)
            record = ctx.store.append_local_observation(obs, world_pos=world_pos, pos_sigma=pos_sigma)
            records.append(record)
            recent_confidences.append(obs.conf)

        _publish_claims(ctx, records, t_media)

        if not baseline_confidences and len(recent_confidences) == recent_confidences.maxlen:
            baseline_confidences = list(recent_confidences)

        if attestor is not None:
            total_ticks = source.frames_read + source.dropped
            achieved_fps = (
                media_clock.fps * source.frames_read / total_ticks if total_ticks else media_clock.fps
            )
            stats = DetectorStats(
                target_fps=media_clock.fps,
                achieved_fps=achieved_fps,
                dropped=source.dropped,
                frames_read=source.frames_read,
                recent_confidences=list(recent_confidences),
                baseline_confidences=baseline_confidences or list(recent_confidences),
            )
            attestation = attestor.tick(t_media, frame, observations, stats)
            _publish_attestation(ctx, attestation)

        frame_count += 1
        if frame_count % _HOUSEKEEPING_EVERY_N_FRAMES == 0:
            _run_housekeeping(
                ctx,
                t_media,
                frame_count,
                {
                    "dropped": source.dropped,
                    "behind_s": round(source.behind_s, 3),
                    "gossip_stats": ctx.gossip.stats() if ctx.gossip is not None else None,
                },
            )

        if ctx.max_frames is not None and frame_count >= ctx.max_frames:
            break

    ctx.log.info("node_stopped", frames=frame_count, dropped=source.dropped)
    return frame_count


def _run_sim(ctx: _RunContext, keys: Optional[NodeKeys]) -> int:
    # Imported here, not at module level, so a video-path node never pulls
    # in ZMQ for no reason and so `starling_sim` stays an optional,
    # clearly-separate dependency of the node process.
    from starling_sim.coverage import SimAttestor
    from starling_sim.node_client import SimNodeSource, coverage_from_tick, observations_from_tick

    cfg = ctx.cfg

    sim_attestor: Optional[SimAttestor] = None
    if ctx.navmesh is not None and cfg.coverage.watched_boundary_ids:
        sim_attestor = SimAttestor(
            node_id=cfg.node_id,
            watched_boundary_ids=cfg.coverage.watched_boundary_ids,
            tau_attest=cfg.attest.tau_attest,
            tick_interval_s=cfg.attest.tick_interval_s,
            keys=keys,
        )
    else:
        ctx.log.warning(
            "node_attestation_disabled",
            node_id=cfg.node_id,
            hint="a navmesh and coverage.watched_boundary_ids are both required for C4 attestation in sim mode",
        )

    sim_source = SimNodeSource(cfg.sim.connect_endpoint, cfg.node_id)
    tick_count = 0
    try:
        while not ctx.shutdown["requested"]:
            tick = sim_source.recv(timeout_ms=_SIM_RECV_TIMEOUT_MS)
            if tick is None:
                continue

            t_media = tick["t_media"]
            records = [
                ctx.store.append_local_observation(obs, world_pos=world_pos, pos_sigma=pos_sigma)
                for obs, world_pos, pos_sigma in observations_from_tick(tick)
            ]
            _publish_claims(ctx, records, t_media)

            if sim_attestor is not None:
                sim_attestor.observe_tick(tick.get("boundary_crossings", {}))
                attestation = sim_attestor.tick(t_media, coverage_from_tick(tick))
                _publish_attestation(ctx, attestation)

            tick_count += 1
            if tick_count % _SIM_HOUSEKEEPING_EVERY_N_TICKS == 0:
                _run_housekeeping(
                    ctx,
                    t_media,
                    tick_count,
                    {"gossip_stats": ctx.gossip.stats() if ctx.gossip is not None else None},
                )

            if ctx.max_frames is not None and tick_count >= ctx.max_frames:
                break
    finally:
        sim_source.close()

    ctx.log.info("node_stopped", frames=tick_count)
    return tick_count


def run(
    config_path: Path,
    speed: float = 1.0,
    max_frames: Optional[int] = None,
    keys_dir: Path = DEFAULT_KEYS_DIR,
) -> None:
    cfg = load_node_config(config_path)
    setup_logging(cfg.node_id)
    log = get_logger(__name__)

    is_sim = cfg.source == "sim"
    # Checked first, genuinely at startup, before any of the heavier model
    # loading below. A sim node has no calib_path (the simulator supplies
    # world_pos directly) so this is simply never called for one.
    calib = None if is_sim else _load_calibration(cfg, log)
    navmesh = _load_navmesh(cfg, log)

    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Exactly one LocalStore per process, at this node's own db_path only
    # (CLAUDE.md rule 1/2) — tests/test_no_coordinator.py enforces this.
    store = LocalStore(
        db_path=str(db_path),
        lost_threshold_secs=cfg.match.lost_threshold_s,
        similarity_threshold=cfg.match.sim_threshold,
        ema_alpha=cfg.match.ema_alpha,
        node_id=cfg.node_id,
    )

    # WP-06 Part 4a: liveness of each configured neighbour, purely
    # inferred from whether it has gossiped anything to us recently — see
    # starling_net.partition for why no heartbeat/ping is needed.
    tracker = PartitionTracker(_neighbour_node_ids(cfg.net.neighbours))
    structlog.contextvars.bind_contextvars(coverage_completeness=tracker.coverage_completeness())

    # STATUS.md Step 4: application-level partition control. A node told
    # to "drop" a peer ignores EVERYTHING from that peer — claim,
    # attestation, reputation, and anti-entropy digest/delta alike — before
    # any of it reaches the CRDT merge or the partition tracker. This is
    # not real packet loss (see PartitionControl's own docstring for the
    # honest limitation and deploy/netem's stronger alternative).
    partition_control = PartitionControl()

    def _on_gossip_message(envelope: "starling_pb2.Envelope") -> None:
        if partition_control.is_dropped(envelope.sender_node_id):
            log.debug("gossip_dropped_partitioned_peer", sender=envelope.sender_node_id)
            return

        tracker.on_message(envelope.sender_node_id)
        kind = envelope.WhichOneof("payload")
        if kind == "claim":
            # WP-06 Part 1: this is the CRDT merge itself — a grow-only
            # set union via LocalStore.append_remote_claims (idempotent on
            # (node_id, seq)). No matching/resolution happens here; that
            # is starling_crdt.resolver's job over the merged set.
            record = claim_proto_to_record(envelope.claim)
            store.append_remote_claims([record])
        elif kind == "reputation":
            reputation_table.ingest_gossiped(envelope.reputation)
        elif kind == "vv_digest":
            # STATUS.md Step 4: AntiEntropy existed and was fully tested
            # (tests/test_anti_entropy.py) but no app ever dispatched to
            # it — this is that wiring. A peer's digest tells us what
            # THEY have; we reply with whatever of ours they're missing.
            their_vv = VersionVector.from_proto(envelope.vv_digest)
            missing = anti_entropy.on_digest(their_vv)
            if missing and gossip is not None:
                chunks = chunk_by_bytes([record_to_claim_proto(c) for c in missing])
                for i, chunk in enumerate(chunks):
                    reply = starling_pb2.Envelope(sender_node_id=cfg.node_id)
                    reply.vv_delta.CopyFrom(starling_pb2.VVDelta(claims=chunk))
                    gossip.publish(reply)
                    if i + 1 < len(chunks):
                        # A tight back-to-back publish burst can outrun a
                        # subscriber's receive buffer (each message also
                        # costs it an ed25519 signature verification,
                        # synchronously, on the same poll thread) — a
                        # short pause between chunks costs little for the
                        # rare large backlog and avoids that.
                        time.sleep(0.01)
        elif kind == "vv_delta":
            claims = [claim_proto_to_record(c) for c in envelope.vv_delta.claims]
            anti_entropy.on_delta(claims)
        log.info("gossip_received", kind=kind, sender=envelope.sender_node_id)

    # Loaded once, independent of whether gossip itself can start, so a
    # node with keys but no configured neighbours can still sign the
    # attestations/reputation updates built below.
    keys: Optional[NodeKeys] = None
    try:
        keys = load_keys(cfg.node_id, keys_dir=keys_dir)
    except FileNotFoundError:
        log.warning(
            "node_no_keys",
            node_id=cfg.node_id,
            keys_dir=str(keys_dir),
            hint="python -m starling_net.keys --generate N",
        )

    gossip: Optional[GossipNode] = None
    if keys is not None:
        gossip = GossipNode(
            node_id=cfg.node_id,
            listen_port=cfg.net.listen_port,
            neighbours=cfg.net.neighbours,
            keys=keys,
            on_message=_on_gossip_message,
        )
        gossip.start()
    else:
        log.warning("gossip_disabled_no_keys", node_id=cfg.node_id, keys_dir=str(keys_dir))

    anti_entropy = AntiEntropy(store, gossip=gossip, interval_s=cfg.net.gossip_interval_s)

    reputation_table = ReputationTable(node_id=cfg.node_id, cfg=cfg.reputation, keys=keys)
    reachability = ReachabilityModel(navmesh, v_max_m_s=cfg.plausibility.v_max_m_s) if navmesh is not None else None
    reputation_loop = _ReputationLoop(cfg.node_id, store, reachability, cfg.plausibility, reputation_table)

    # WP-10 Part 3: this node's own Byzantine behaviour, "none" by default
    # and live-switchable via the control endpoint below / a scenario `lie`
    # event (starling_eval.netem_plan.plan_lie). Constructed unconditionally
    # (like below) so a node with gossip disabled is still testable in
    # isolation.
    injector = AttackInjector(
        node_id=cfg.node_id, attack=cfg.attack.attack, intensity=cfg.attack.intensity, cfg=cfg.attack,
        embed_dim=cfg.perception.embed_dim,
    )
    control_server: Optional[ControlServer] = None
    if cfg.attack.enable_control_endpoint:
        control_server = ControlServer(
            injector,
            port=cfg.net.listen_port + 1000,
            host=cfg.attack.control_bind_host,
            partition=partition_control,
        )
        control_server.start()

    log.info(
        "node_starting",
        source=cfg.source,
        db_path=str(db_path),
        stream_epoch=cfg.stream_epoch,
        gossip_enabled=gossip is not None,
        control_endpoint_enabled=control_server is not None,
    )

    shutdown = {"requested": False}

    def _handle_signal(signum: int, frame: Any) -> None:
        log.info("node_signal_received", signum=signum)
        shutdown["requested"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    ctx = _RunContext(
        cfg=cfg,
        navmesh=navmesh,
        store=store,
        tracker=tracker,
        anti_entropy=anti_entropy,
        reputation_loop=reputation_loop,
        reputation_table=reputation_table,
        injector=injector,
        gossip=gossip,
        log=log,
        shutdown=shutdown,
        max_frames=max_frames,
    )

    try:
        if is_sim:
            _run_sim(ctx, keys)
        else:
            _run_video(ctx, calib, speed, keys)
    finally:
        if control_server is not None:
            control_server.stop()
        if gossip is not None:
            gossip.stop()
        store.close()


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Standalone Starling node process")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--keys-dir", type=Path, default=DEFAULT_KEYS_DIR)
    args = parser.parse_args(argv)

    run(
        config_path=args.config,
        speed=args.speed,
        max_frames=args.max_frames,
        keys_dir=args.keys_dir,
    )


if __name__ == "__main__":
    main()
