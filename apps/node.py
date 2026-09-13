"""apps/node.py
---------------
Standalone Starling node process (D-04, D-05, D-07 — STARLING_BUILD_STATE.md
§2, §4.1). One node = one OS process = one camera = one node-local SQLite
replica (`LocalStore`) = one gossip socket (Prompt 4 adds the socket).
CLAUDE.md rule 1: never a thread, never a shared database handle. No module
here imports another node's store, config, or db_path — that guardrail is
enforced by tests/test_no_coordinator.py.

Usage
-----
    python apps/node.py --config configs/nodes/node-00.yaml [--speed N] [--max-frames N]

There is deliberately no gossip here yet (Prompt 4). See the
`# TODO(prompt-4)` marker in the main loop below for where it attaches.
"""

from __future__ import annotations

import argparse
import signal
from pathlib import Path
from typing import Optional

from starling_net.logging import get_logger, setup_logging
from starling_net.timebase import MediaClock
from starling_node.config import load_node_config
from starling_perception.pipeline import NodePerception
from starling_perception.source import PacedSource
from starling_store.identity_store import LocalStore

_HOUSEKEEPING_EVERY_N_FRAMES = 30


def run(
    config_path: Path,
    speed: float = 1.0,
    max_frames: Optional[int] = None,
) -> None:
    cfg = load_node_config(config_path)
    setup_logging(cfg.node_id)
    log = get_logger(__name__)

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

    log.info(
        "node_starting",
        source=cfg.source,
        db_path=str(db_path),
        stream_epoch=cfg.stream_epoch,
        media_clock_approximate=media_clock.is_approximate,
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
                store.append_local_observation(obs)
                # TODO(prompt-4): attach gossip publisher here — broadcast
                # each newly-appended claim to this node's configured
                # neighbour set (starling_node.config: NetConfig.neighbours).

            frame_count += 1
            if frame_count % _HOUSEKEEPING_EVERY_N_FRAMES == 0:
                log.info(
                    "node_housekeeping",
                    frames=frame_count,
                    dropped=source.dropped,
                    behind_s=round(source.behind_s, 3),
                )

            if max_frames is not None and frame_count >= max_frames:
                break
    finally:
        log.info("node_stopped", frames=frame_count, dropped=source.dropped)
        store.close()


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Standalone Starling node process")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=None)
    args = parser.parse_args(argv)

    run(config_path=args.config, speed=args.speed, max_frames=args.max_frames)


if __name__ == "__main__":
    main()
