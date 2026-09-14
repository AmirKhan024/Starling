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
from pathlib import Path
from typing import Optional

from starling_geometry.calibration import CameraCalibration, bbox_floor_point
from starling_net.gossip import GossipNode
from starling_net.keys import DEFAULT_KEYS_DIR, load_keys
from starling_net.logging import get_logger, setup_logging
from starling_net.timebase import MediaClock
from starling_node.config import load_node_config
from starling_perception.pipeline import NodePerception
from starling_perception.source import PacedSource
from starling_proto.convert import make_claim_envelope, record_to_claim_proto
from starling_store.identity_store import LocalStore

_HOUSEKEEPING_EVERY_N_FRAMES = 30


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

    def _on_gossip_message(envelope) -> None:
        # WP-06 does the merging. For now: log and otherwise ignore, per
        # this session's rule 3 (transport and set-union only, no CRDT
        # merge / identity resolution here).
        kind = envelope.WhichOneof("payload")
        log.info("gossip_received", kind=kind, sender=envelope.sender_node_id)

    gossip: Optional[GossipNode] = None
    try:
        keys = load_keys(cfg.node_id, keys_dir=keys_dir)
        gossip = GossipNode(
            node_id=cfg.node_id,
            listen_port=cfg.net.listen_port,
            neighbours=cfg.net.neighbours,
            keys=keys,
            on_message=_on_gossip_message,
        )
        gossip.start()
    except FileNotFoundError:
        log.warning(
            "gossip_disabled_no_keys",
            node_id=cfg.node_id,
            keys_dir=str(keys_dir),
            hint="python -m starling_net.keys --generate N",
        )
        gossip = None

    log.info(
        "node_starting",
        source=cfg.source,
        db_path=str(db_path),
        stream_epoch=cfg.stream_epoch,
        media_clock_approximate=media_clock.is_approximate,
        gossip_enabled=gossip is not None,
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

            frame_count += 1
            if frame_count % _HOUSEKEEPING_EVERY_N_FRAMES == 0:
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
