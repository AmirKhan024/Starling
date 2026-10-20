"""apps/bench_node.py
---------------------
A lightweight Starling BENCHMARK node process, for the scalability
experiment (scripts/run_scale_experiment.py, docs/results_scale.md).

It is apps/node.py with the camera and the perception removed, and nothing
else changed in the networking path. One process = one node = its own
SQLite replica (`LocalStore`, its own file) = its own signed ZeroMQ gossip
socket (`GossipNode`, its own port) = its own ed25519 key, gossiping to a
CONFIGURED neighbour list only (CLAUDE.md rules 1, 2 and 4). Exactly the
same modules apps/node.py uses carry the claims:

  * `LocalStore.append_local_observation` writes each new claim;
  * `record_to_claim_proto` + `make_claim_envelope` + `GossipNode.publish`
    send it, signed, to this node's neighbours (`_publish_claims`);
  * an incoming `claim` is merged by `LocalStore.append_remote_claims`;
  * `AntiEntropy.tick()` broadcasts this replica's gap-aware version vector,
    and the `vv_digest` / `vv_delta` handling below is a line-for-line copy
    of `apps/node.py`'s `_on_gossip_message` (`on_digest` -> byte-budgeted
    `chunk_by_bytes` replies -> `on_delta`).

GossipNode does NOT relay: a claim received from a neighbour is merged
into the local replica and never re-published. A claim therefore reaches
its origin's direct neighbours by the immediate publish, and everyone
further away only through anti-entropy rounds. That is the real system's
behaviour, and it is what this benchmark measures.

What is synthetic is only the claim SOURCE: instead of YOLO + tracking on
rendered frames, claims are generated at a configurable rate (default 2.6
claims/s, the live world node's measured rate: 965 claims in ~370 s,
review/world/review_summary.md) with byte-realistic content (a 96-d
float32 appearance descriptor, a floor position and its sigma, a node-local
track id, detector confidence, crop quality, and occasionally a FACE_ANCHOR
employee id), exactly the fields `_run_world` stores.

Measurement harness (NOT the identity path): for every claim this replica
holds, the wall-clock instant it first appeared here is recorded, so the
experiment can compute end-to-end propagation latency across processes.
Periodically writes a small JSON stats file; on shutdown writes the
first-seen table. Controlled by a tiny per-node command file the
experiment runner writes (start/stop producing, drop a set of peers, stop).

    python apps/bench_node.py --config data/scale/run-.../node-03.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
# Before numpy loads: one BLAS thread. The default (one per core) commits
# ~800 MB per process, which at dozens of nodes exhausts the page file.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np
from pydantic import BaseModel, Field
from starling_net.anti_entropy import AntiEntropy, VersionVector, chunk_by_bytes
from starling_net.gossip import GossipNode
from starling_net.keys import load_keys
from starling_net.logging import get_logger, setup_logging
from starling_proto.convert import (
    claim_proto_to_record,
    make_claim_envelope,
    record_to_claim_proto,
)
from starling_proto.generated import starling_pb2
from starling_store.identity_store import LocalStore

try:  # optional: RSS is reported only when psutil is installed
    import psutil
except ImportError:  # pragma: no cover - psutil is present in the dev env
    psutil = None


class BenchNodeConfig(BaseModel):
    """One benchmark node's own config, written by the experiment runner."""

    node_id: int
    listen_port: int
    neighbours: list[str]  # "host:port" of this node's configured neighbours only
    run_dir: str           # this node's files live here: node-NN.{db,stats.json,seen.json,cmd.json}
    keys_dir: str
    claims_per_s: float = 2.6       # live world node: 965 claims / ~370 s
    rate_jitter: float = 0.5        # inter-claim gap uniform in [(1-j), (1+j)] / rate
    embed_dim: int = 96             # world appearance descriptor: 6 stripes x 16 bins
    anchor_fraction: float = 0.02   # share of claims that carry a FACE_ANCHOR employee id
    claims_per_track: int = 20      # a node-local track id lasts ~this many claims
    floor_w_m: float = 30.0         # warehouse floor (configs/world/warehouse.yaml)
    floor_h_m: float = 20.0
    walk_step_m: float = 0.4        # per-claim displacement of a synthetic track
    pos_sigma_range: tuple[float, float] = (0.15, 0.45)
    conf_range: tuple[float, float] = (0.3, 0.92)
    quality_range: tuple[float, float] = (0.35, 1.0)
    # apps/node.py's world path runs housekeeping (incl. AntiEntropy.tick)
    # every 4 frames at 3 fps, i.e. every 4/3 s.
    ae_interval_s: float = 4.0 / 3.0
    stats_interval_s: float = 0.5
    cmd_poll_s: float = 0.1
    parent_check_s: float = 2.0
    max_lifetime_s: float = 1800.0  # orphan guard: a node never outlives this
    parent_pid: int | None = None
    log_level: str = "WARNING"      # the real node logs every message at INFO; that is not what is measured here
    seed: int = 0
    employee_ids: list[str] = Field(
        default_factory=lambda: ["EMP-1041", "EMP-1042", "EMP-1043", "EMP-1044"]
    )


@dataclass
class _SyntheticObservation:
    """The attributes `LocalStore.append_local_observation` reads from a
    perception `Observation`."""

    t_media: float
    local_track_id: int
    embedding: np.ndarray
    conf: float
    quality: float
    anchor_identity: str | None = None


class SyntheticClaimSource:
    """Byte-realistic world-camera claims, without a camera."""

    def __init__(self, cfg: BenchNodeConfig) -> None:
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed * 7919 + cfg.node_id)
        self.track_id = 0
        self.claims_in_track = 0
        self.pos = self._random_pos()
        self.base_desc = self._random_desc()

    def _random_pos(self) -> np.ndarray:
        return self.rng.uniform([0.0, 0.0], [self.cfg.floor_w_m, self.cfg.floor_h_m])

    def _random_desc(self) -> np.ndarray:
        # Non-negative, sparse-ish histogram bins, L2-normalised: the shape of
        # starling_perception.appearance's descriptor.
        d = self.rng.gamma(0.6, 1.0, self.cfg.embed_dim) * (self.rng.random(self.cfg.embed_dim) > 0.4)
        return d / max(float(np.linalg.norm(d)), 1e-9)

    def next(self, t_media: float) -> tuple[_SyntheticObservation, tuple[float, float], float]:
        c = self.cfg
        if self.claims_in_track >= c.claims_per_track:
            self.track_id += 1
            self.claims_in_track = 0
            self.pos = self._random_pos()
            self.base_desc = self._random_desc()
        self.claims_in_track += 1
        self.pos = np.clip(
            self.pos + self.rng.normal(0.0, c.walk_step_m, 2), [0.0, 0.0], [c.floor_w_m, c.floor_h_m]
        )
        desc = np.clip(self.base_desc + self.rng.normal(0.0, 0.03, c.embed_dim), 0.0, None)
        desc = (desc / max(float(np.linalg.norm(desc)), 1e-9)).astype(np.float32)
        anchor = None
        if self.rng.random() < c.anchor_fraction:
            anchor = str(self.rng.choice(c.employee_ids))
        obs = _SyntheticObservation(
            t_media=t_media,
            local_track_id=self.track_id,
            embedding=desc,
            conf=float(self.rng.uniform(*c.conf_range)),
            quality=float(self.rng.uniform(*c.quality_range)),
            anchor_identity=anchor,
        )
        sigma = float(self.rng.uniform(*c.pos_sigma_range))
        return obs, (float(self.pos[0]), float(self.pos[1])), sigma


class FirstSeenLog:
    """Measurement harness only: claim_id -> (origin node, wall time first held here).

    time.time() is used deliberately: this is the benchmark's cross-process
    stopwatch, not the identity path (CLAUDE.md's no-wall-clock rule is
    about claim timestamps, which still come from media time + HLC).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.first_seen: dict[str, tuple[int, float]] = {}

    def note(self, records: list[dict[str, Any]]) -> None:
        now = time.time()  # measurement harness, not the identity path
        with self._lock:
            for r in records:
                self.first_seen.setdefault(r["claim_id"], (int(r["node_id"]), now))

    def __len__(self) -> int:
        with self._lock:
            return len(self.first_seen)

    def snapshot(self) -> dict[str, tuple[int, float]]:
        with self._lock:
            return dict(self.first_seen)


def _write_json_atomic(path: Path, payload: dict[str, Any], retries: int = 20) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    for _ in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows: a reader has the target open
            time.sleep(0.01)
    os.replace(tmp, path)


def _gossip_totals(stats: dict[str, Any]) -> dict[str, int]:
    out = {"sent": 0, "sent_bytes": 0, "recv": 0, "recv_bytes": 0}
    for kind, s in stats.items():
        if kind.startswith("_"):
            continue
        for k in out:
            out[k] += int(s.get(k, 0))
    return out


class BenchNode:
    def __init__(self, cfg: BenchNodeConfig) -> None:
        self.cfg = cfg
        self.run_dir = Path(cfg.run_dir)
        stem = f"node-{cfg.node_id:02d}"
        self.db_path = self.run_dir / f"{stem}.db"
        self.stats_path = self.run_dir / f"{stem}.stats.json"
        self.seen_path = self.run_dir / f"{stem}.seen.json"
        self.cmd_path = self.run_dir / f"{stem}.cmd.json"
        self.log = get_logger(__name__)

        # Exactly one LocalStore per process, at this node's own path (rule 1/2).
        self.store = LocalStore(db_path=str(self.db_path), node_id=cfg.node_id)
        self.seen = FirstSeenLog()
        self.source = SyntheticClaimSource(cfg)
        # Same semantics as starling_consensus.attacks.PartitionControl (an
        # application-level drop of everything from these senders). Not
        # imported: that module pulls in the navmesh/scipy/shapely stack
        # (+~30 MB and ~4 s of imports per process).
        self.dropped_ids: set[int] = set()
        self.dropped_msgs = 0
        self.publish_errors = 0
        self.producing = False
        self.stop_requested = False
        self.cmd_seq_applied = -1
        self._cmd_sig: tuple[int, int] | None = None
        self.window: dict[str, Any] = {}

        keys = load_keys(cfg.node_id, keys_dir=Path(cfg.keys_dir))
        self.gossip = GossipNode(
            node_id=cfg.node_id,
            listen_port=cfg.listen_port,
            neighbours=cfg.neighbours,
            keys=keys,
            on_message=self._on_gossip_message,
        )
        self.anti_entropy = AntiEntropy(self.store, gossip=self.gossip, interval_s=cfg.ae_interval_s)
        self.proc = psutil.Process() if psutil is not None else None

    # ── gossip receive path (copied from apps/node.py _on_gossip_message) ──
    def _on_gossip_message(self, envelope: starling_pb2.Envelope) -> None:
        if envelope.sender_node_id in self.dropped_ids:
            self.dropped_msgs += 1
            return
        kind = envelope.WhichOneof("payload")
        if kind == "claim":
            record = claim_proto_to_record(envelope.claim)
            self.store.append_remote_claims([record])
            self.seen.note([record])
        elif kind == "vv_digest":
            their_vv = VersionVector.from_proto(envelope.vv_digest)
            missing = self.anti_entropy.on_digest(their_vv)
            if missing:
                chunks = chunk_by_bytes([record_to_claim_proto(c) for c in missing])
                for i, chunk in enumerate(chunks):
                    reply = starling_pb2.Envelope(sender_node_id=self.cfg.node_id)
                    reply.vv_delta.CopyFrom(starling_pb2.VVDelta(claims=chunk))
                    self._publish(reply)
                    if i + 1 < len(chunks):
                        time.sleep(0.01)  # as apps/node.py: don't outrun a subscriber's buffer
        elif kind == "vv_delta":
            claims = [claim_proto_to_record(c) for c in envelope.vv_delta.claims]
            self.anti_entropy.on_delta(claims)
            self.seen.note(claims)

    def _publish(self, envelope: starling_pb2.Envelope) -> None:
        try:
            self.gossip.publish(envelope)
        except ValueError as exc:  # over the wire cap: count it, keep running
            self.publish_errors += 1
            self.log.warning("bench_publish_rejected", error=str(exc))

    # ── claim source ──────────────────────────────────────────────────────
    def _produce_one(self) -> None:
        # Media time from the monotonic clock (system-wide QPC on Windows,
        # so it is one timeline across these processes) — no wall clock in
        # the claim itself.
        obs, world_pos, sigma = self.source.next(time.monotonic())
        record = self.store.append_local_observation(obs, world_pos=world_pos, pos_sigma=sigma)
        self.seen.note([record])
        envelope = make_claim_envelope(record_to_claim_proto(record), sender_node_id=self.cfg.node_id)
        self._publish(envelope)

    def _next_gap(self) -> float:
        j = self.cfg.rate_jitter
        return random.uniform(1.0 - j, 1.0 + j) / self.cfg.claims_per_s

    # ── control + stats ───────────────────────────────────────────────────
    def _counters(self) -> dict[str, Any]:
        t = os.times()
        g = _gossip_totals(self.gossip.stats())
        return {
            "t": time.time(),  # measurement harness, not the identity path
            "cpu_s": t.user + t.system,
            "bytes_sent": g["sent_bytes"],
            "bytes_recv": g["recv_bytes"],
            "msgs_sent": g["sent"],
            "msgs_recv": g["recv"],
            "claims_held": len(self.seen),
            "rss_mb": (self.proc.memory_info().rss / 1e6) if self.proc is not None else None,
        }

    def _poll_cmd(self) -> None:
        try:
            st = self.cmd_path.stat()
        except FileNotFoundError:
            return
        sig = (st.st_mtime_ns, st.st_size)
        if sig == self._cmd_sig:
            return
        try:
            cmd = json.loads(self.cmd_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # mid-write; next poll
        self._cmd_sig = sig
        if int(cmd.get("seq", -1)) <= self.cmd_seq_applied:
            return
        self.cmd_seq_applied = int(cmd["seq"])
        self.dropped_ids = {int(n) for n in cmd.get("drop", [])}
        produce = bool(cmd.get("produce", False))
        if produce and not self.producing:
            self.window = {"start": self._counters()}
        elif not produce and self.producing:
            self.window["end"] = self._counters()
        self.producing = produce
        if cmd.get("stop"):
            self.stop_requested = True

    def _digest(self) -> str:
        ranges = self.store.claim_ranges()
        canon = json.dumps(sorted((n, list(map(list, r))) for n, r in ranges.items()))
        return hashlib.sha1(canon.encode("utf-8")).hexdigest()

    def _write_stats(self, final: bool = False) -> None:
        payload = {
            "node_id": self.cfg.node_id,
            "ready": True,
            "final": final,
            "producing": self.producing,
            "cmd_seq": self.cmd_seq_applied,
            "dropped": sorted(self.dropped_ids),
            "dropped_msgs": self.dropped_msgs,
            "publish_errors": self.publish_errors,
            "store_claims": self.store.count_claims(),
            "digest": self._digest(),
            "now": self._counters(),
            "window": self.window,
            "gossip": self.gossip.stats(),
        }
        _write_json_atomic(self.stats_path, payload)

    def _parent_alive(self) -> bool:
        if self.cfg.parent_pid is None or psutil is None:
            return True
        return bool(psutil.pid_exists(self.cfg.parent_pid))

    # ── main loop ─────────────────────────────────────────────────────────
    def run(self) -> None:
        c = self.cfg
        self.gossip.start()
        t_start = time.monotonic()
        next_claim = float("inf")
        next_ae = t_start + random.uniform(0.0, c.ae_interval_s)  # de-synchronise rounds
        next_stats = t_start
        next_cmd = t_start
        next_parent = t_start + c.parent_check_s
        was_producing = False
        try:
            while not self.stop_requested:
                now = time.monotonic()
                if now - t_start > c.max_lifetime_s:
                    self.log.warning("bench_max_lifetime_reached")
                    break
                if now >= next_cmd:
                    self._poll_cmd()
                    next_cmd = now + c.cmd_poll_s
                    if self.producing and not was_producing:
                        next_claim = now + random.uniform(0.0, 1.0 / c.claims_per_s)
                    elif not self.producing:
                        next_claim = float("inf")
                    was_producing = self.producing
                if now >= next_claim:
                    self._produce_one()
                    next_claim += self._next_gap()
                    if next_claim < now:  # fell behind (CPU starved): don't burst
                        next_claim = now + self._next_gap()
                if now >= next_ae:
                    self.anti_entropy.tick()
                    next_ae += c.ae_interval_s
                    if next_ae < now:
                        next_ae = now + c.ae_interval_s
                if now >= next_stats:
                    self._write_stats()
                    next_stats = now + c.stats_interval_s
                if now >= next_parent:
                    if not self._parent_alive():
                        self.log.warning("bench_parent_gone")
                        break
                    next_parent = now + c.parent_check_s
                wake = min(next_claim, next_ae, next_stats, next_cmd, next_parent)
                time.sleep(max(0.0, min(wake - time.monotonic(), 0.05)))
        finally:
            self.gossip.stop()
            try:
                self._write_stats(final=True)
                snap = self.seen.snapshot()
                _write_json_atomic(self.seen_path, {"node_id": c.node_id, "first_seen": snap})
            finally:
                self.store.close()


def load_bench_config(path: Path) -> BenchNodeConfig:
    return BenchNodeConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Starling scalability benchmark node")
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    cfg = load_bench_config(args.config)
    setup_logging(cfg.node_id, level=cfg.log_level)
    random.seed(cfg.seed * 104729 + cfg.node_id)
    node = BenchNode(cfg)

    def _stop(signum: int, frame: Any) -> None:
        node.stop_requested = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    if hasattr(signal, "SIGBREAK"):  # Windows: CTRL_BREAK_EVENT from the runner
        signal.signal(signal.SIGBREAK, _stop)
    node.run()


if __name__ == "__main__":
    main()
