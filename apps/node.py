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

WP-06 (CRDT merge) is what actually DOES something with a received claim.
For now, received claims are logged and otherwise ignored — no matching,
no merge — matching this session's rule 3 (transport and set-union only).
"""

from __future__ import annotations

import argparse
import signal
from collections import deque
from pathlib import Path
from typing import Optional

import structlog

from starling_attest.attestation import Attestor
from starling_geometry.calibration import CameraCalibration, bbox_floor_point
from starling_geometry.navmesh import NavMesh
from starling_net.gossip import GossipNode
from starling_net.keys import DEFAULT_KEYS_DIR, NodeKeys, load_keys
from starling_net.logging import get_logger, setup_logging
from starling_net.partition import PartitionTracker
from starling_net.timebase import MediaClock
from starling_node.config import load_node_config
from starling_perception.coverage import CoverageAssessor, DetectorStats
from starling_perception.pipeline import NodePerception
from starling_perception.source import PacedSource
from starling_proto.convert import (
    claim_proto_to_record,
    make_attestation_envelope,
    make_claim_envelope,
    record_to_claim_proto,
)
from starling_store.identity_store import LocalStore

_HOUSEKEEPING_EVERY_N_FRAMES = 30
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
    without loading YOLO weights.
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


def run(
    config_path: Path,
    speed: float = 1.0,
    max_frames: Optional[int] = None,
    keys_dir: Path = DEFAULT_KEYS_DIR,
) -> None:
    cfg = load_node_config(config_path)
    setup_logging(cfg.node_id)
    log = get_logger(__name__)

    # Checked first, genuinely at startup, before any of the heavier model
    # loading below.
    calib = _load_calibration(cfg, log)
    navmesh = _load_navmesh(cfg, log)

    media_clock = MediaClock.from_video(cfg.source, stream_epoch=cfg.stream_epoch)
    source = PacedSource(cfg.source, media_clock, speed=speed, realtime=True)
    perception = NodePerception(cfg.perception, node_id=cfg.node_id)

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

    def _on_gossip_message(envelope) -> None:
        tracker.on_message(envelope.sender_node_id)
        kind = envelope.WhichOneof("payload")
        if kind == "claim":
            # WP-06 Part 1: this is the CRDT merge itself — a grow-only
            # set union via LocalStore.append_remote_claims (idempotent on
            # (node_id, seq)). No matching/resolution happens here; that
            # is starling_crdt.resolver's job over the merged set.
            record = claim_proto_to_record(envelope.claim)
            store.append_remote_claims([record])
        log.info("gossip_received", kind=kind, sender=envelope.sender_node_id)

    # Loaded once, independent of whether gossip itself can start, so a
    # node with keys but no configured neighbours can still sign the
    # attestations `Attestor` builds below.
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

    # WP-09 Part 2: an attesting node needs calibration, a navmesh, and a
    # configured ROI — any one missing means "nothing to attest about",
    # not a guess. Coverage attestation degrades independently of gossip:
    # an attestor with no gossip just never gets its output published.
    attestor: Optional[Attestor] = None
    recent_confidences: "deque[float]" = deque(maxlen=cfg.coverage.ks_window)
    baseline_confidences: list[float] = []
    if calib is not None and navmesh is not None and cfg.coverage.roi_polygon:
        coverage_assessor = CoverageAssessor(cfg=cfg.coverage, calibration=calib, navmesh=navmesh)
        attestor = Attestor(node_id=cfg.node_id, coverage_assessor=coverage_assessor, cfg=cfg.attest, keys=keys)
    else:
        log.warning(
            "node_attestation_disabled",
            node_id=cfg.node_id,
            hint="calibration, a navmesh, and coverage.roi_polygon are all required for C4 attestation",
        )

    log.info(
        "node_starting",
        source=cfg.source,
        db_path=str(db_path),
        stream_epoch=cfg.stream_epoch,
        media_clock_approximate=media_clock.is_approximate,
        gossip_enabled=gossip is not None,
        attestation_enabled=attestor is not None,
    )

    shutdown = {"requested": False}

    def _handle_signal(signum, frame) -> None:
        log.info("node_signal_received", signum=signum)
        shutdown["requested"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    frame_count = 0
    try:
        for frame, frame_idx, t_media in source:
            if shutdown["requested"]:
                log.info("node_shutdown_requested", frames=frame_count)
                break

            observations = perception.process(frame, t_media)
            for obs in observations:
                world_pos = None
                pos_sigma = None
                if calib is not None:
                    u, v = bbox_floor_point(obs.bbox)
                    world_pos = calib.image_to_floor(u, v)
                    pos_sigma = calib.position_sigma(obs.bbox)

                record = store.append_local_observation(obs, world_pos=world_pos, pos_sigma=pos_sigma)
                if gossip is not None:
                    claim = record_to_claim_proto(record)
                    envelope = make_claim_envelope(claim, sender_node_id=cfg.node_id)
                    gossip.publish(envelope)

                recent_confidences.append(obs.conf)

            if not baseline_confidences and len(recent_confidences) == recent_confidences.maxlen:
                # Snapshot once, the first time the rolling window fills —
                # "how this detector behaved when it started" — and never
                # overwritten again, so later drift has something fixed to
                # be compared against (starling_perception.coverage
                # .DetectorStats' KS-statistic check).
                baseline_confidences = list(recent_confidences)

            if attestor is not None:
                # D-03: achieved_fps is derived from PacedSource's own
                # dropped/frames_read counts, never a fresh time.time()
                # measurement — no wall-clock read belongs in the identity
                # path (CLAUDE.md).
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
                if attestation is not None and gossip is not None:
                    envelope = make_attestation_envelope(attestation, sender_node_id=cfg.node_id)
                    gossip.publish(envelope)

            frame_count += 1
            if frame_count % _HOUSEKEEPING_EVERY_N_FRAMES == 0:
                tracker.tick()
                event = tracker.check_partition_event()
                structlog.contextvars.bind_contextvars(
                    coverage_completeness=tracker.coverage_completeness()
                )
                if event is not None:
                    log.warning(
                        event,
                        reachable_neighbours=tracker.reachable_neighbours(),
                        configured_neighbours=tracker.neighbour_node_ids,
                    )
                log.info(
                    "node_housekeeping",
                    frames=frame_count,
                    dropped=source.dropped,
                    behind_s=round(source.behind_s, 3),
                    gossip_stats=gossip.stats() if gossip is not None else None,
                )

            if max_frames is not None and frame_count >= max_frames:
                break
    finally:
        log.info("node_stopped", frames=frame_count, dropped=source.dropped)
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
