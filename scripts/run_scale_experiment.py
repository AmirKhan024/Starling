"""scripts/run_scale_experiment.py
-----------------------------------
A REAL, measured scalability experiment of Starling's gossip + CRDT layer.

For each N in a configured list, spawns N independent OS processes
(apps/bench_node.py), each with its own SQLite replica, its own signed
ZeroMQ gossip socket, its own ed25519 key and a CONFIGURED neighbour set of
fixed small degree (default 4: ring +-1 plus one deterministic chord pair
+-k, a circulant graph; N <= degree+1 falls back to the plain ring, as the
4-camera demo uses — never a full mesh). Each node produces byte-realistic
synthetic claims at the live world node's measured rate. Measures, per N:

  (a) per-node gossip bytes/s in and out during claim production,
  (b) end-to-end propagation latency: claim creation at its origin ->
      present in EVERY replica (p50 / p95 / max),
  (c) whether every replica ended with the identical claim set,
  (d) CPU% and RSS per node,
and, for one N, (e) a partition test: cut the graph into two halves while
producing, heal, and measure how long until every claim made before the
heal is in every replica.

Also computes (clearly labelled as computed, not measured on a network)
the ingest a CENTRALISED design's server would need: N x one camera's video.

    python scripts/run_scale_experiment.py [--config configs/scale/experiment.yaml] [--ns 4,8,16]

Outputs docs/results_scale.json, docs/scale_bandwidth.png,
docs/scale_latency.png. Scratch data (SQLite replicas, keys, per-node logs)
goes under data/scale/run-<ts>/ and is not committed.
"""

from __future__ import annotations

import argparse
import atexit
import json
import math
import os
import platform
import signal
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, Field, model_validator

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DEFAULT_CONFIG_PATH = REPO / "configs" / "scale" / "experiment.yaml"

# A lazy proxy: binding here would freeze structlog's default (non-JSON)
# config before main() calls setup_logging.
log = structlog.get_logger("scale_experiment")


# ── config ────────────────────────────────────────────────────────────────

class PartitionTestConfig(BaseModel):
    enabled: bool = True
    n: int = 16
    before_s: float = 10.0     # producing, connected
    partition_s: float = 15.0  # producing, cut into two halves
    after_s: float = 10.0      # producing, healed


class CentralConfig(BaseModel):
    # The live world demo's camera tap (read-only GET of the latest JPEG);
    # sampled when reachable, else the stated assumption below is used.
    world_camera_tap_url: str = "http://127.0.0.1:8770/api/camera/{n}/latest.jpg"
    tap_cameras: list[int] = Field(default_factory=lambda: [0, 1, 2, 3])
    tap_samples_per_camera: int = 12
    tap_interval_s: float = 0.4
    tap_timeout_s: float = 2.0
    world_config_path: str = "configs/world/warehouse.yaml"  # camera_frames.{width_px,height_px,fps,jpeg_quality}
    fallback_world_fps: float = 3.0
    assumed_jpeg_bytes: float = 120_000.0     # 1280x720 JPEG q0.86, used only if the tap is unreachable
    h264_1080p_bits_per_s: float = 4_000_000.0  # industry-typical 1080p H.264 CCTV stream


class ExperimentConfig(BaseModel):
    ns: list[int] = Field(default_factory=lambda: [4, 8, 16, 32, 48, 64])
    degree: int = 4
    claims_per_node_per_s: float = 2.6
    rate_jitter: float = 0.5
    embed_dim: int = 96
    ae_interval_s: float = 4.0 / 3.0
    stats_interval_s: float = 0.5
    warmup_s: float = 4.0
    produce_s: float = 40.0
    settle_timeout_s: float = 90.0
    ready_timeout_s: float = 120.0
    shutdown_grace_s: float = 15.0
    poll_s: float = 0.25
    host: str = "127.0.0.1"
    base_port: int = 7600
    port_stride: int = 100     # each run gets its own port block: no rebinding a just-closed port
    forbidden_ports: list[int] = Field(
        default_factory=lambda: [5555, 5556, 5557, 5558, 6555, 6556, 6557, 6558, 5570, 8765, 8770, 7000]
    )
    max_total_rss_mb: float = 8000.0  # skip an N whose projected node RSS exceeds this
    scratch_root: str = "data/scale"
    out_json: str = "docs/results_scale.json"
    out_bandwidth_png: str = "docs/scale_bandwidth.png"
    out_latency_png: str = "docs/scale_latency.png"
    seed: int = 7
    node_log_level: str = "WARNING"
    # numpy's OpenBLAS otherwise starts one thread per core in EVERY node and
    # commits ~800 MB per process for their buffers (measured: 816 MB vs
    # 40 MB); with 24 cores that exhausted the page file at N=32. A bench
    # node never does linear algebra, so one thread costs nothing.
    child_env: dict[str, str] = Field(
        default_factory=lambda: {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    )
    partition: PartitionTestConfig = Field(default_factory=PartitionTestConfig)
    central: CentralConfig = Field(default_factory=CentralConfig)

    @model_validator(mode="after")
    def _check(self) -> ExperimentConfig:
        if self.degree < 2 or self.degree % 2:
            raise ValueError("degree must be an even number >= 2 (ring +-1 plus chord pairs)")
        if self.port_stride < max(self.ns + [self.partition.n]):
            raise ValueError("port_stride must be >= the largest N")
        return self


def load_config(path: Path | None) -> ExperimentConfig:
    if path is not None and Path(path).exists():
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return ExperimentConfig.model_validate(raw)
    return ExperimentConfig()


# ── topology (pure) ───────────────────────────────────────────────────────

def bfs_dists(adj: dict[int, list[int]], src: int) -> dict[int, int]:
    dist = {src: 0}
    q = deque([src])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


def is_connected(adj: dict[int, list[int]]) -> bool:
    return not adj or len(bfs_dists(adj, next(iter(adj)))) == len(adj)


def diameter(adj: dict[int, list[int]]) -> int:
    """Longest shortest path (hops). Raises if the graph is disconnected."""
    best = 0
    for s in adj:
        d = bfs_dists(adj, s)
        if len(d) != len(adj):
            raise ValueError("graph is disconnected")
        best = max(best, max(d.values()))
    return best


def circulant(n: int, offsets: list[int]) -> dict[int, list[int]]:
    adj: dict[int, set[int]] = {i: set() for i in range(n)}
    for i in range(n):
        for k in offsets:
            for j in ((i + k) % n, (i - k) % n):
                if j != i:
                    adj[i].add(j)
    return {i: sorted(v) for i, v in adj.items()}


def build_topology(n: int, degree: int = 4) -> tuple[dict[int, list[int]], list[int]]:
    """Ring +-1 plus (degree/2 - 1) chord offsets, each chosen
    deterministically (smallest resulting diameter, ties -> smallest offset).
    If chords would make a full mesh (n <= degree + 1) the plain ring is
    used instead, as in the 4-camera demo: a full mesh is a coordinator in
    disguise (CLAUDE.md rule 4). Returns (adjacency, offsets)."""
    if n < 2:
        raise ValueError("need at least 2 nodes")
    if n <= 3 or n <= degree + 1:
        offsets = [1]
        return circulant(n, offsets), offsets
    offsets = [1]
    for _ in range(degree // 2 - 1):
        # k < n/2 keeps +k and -k distinct, so every chord adds degree 2
        candidates = [k for k in range(2, (n + 1) // 2) if k not in offsets and 2 * k != n]
        if not candidates:
            break
        offsets.append(min(candidates, key=lambda k: (diameter(circulant(n, offsets + [k])), k)))
    return circulant(n, offsets), offsets


# ── stats helpers (pure) ──────────────────────────────────────────────────

def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    pos = (len(s) - 1) * q / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def propagation(
    seen: dict[int, dict[str, tuple[int, float]]], t_from: float = -math.inf, t_to: float = math.inf
) -> dict[str, Any]:
    """From every replica's first-seen table, per claim created at its
    origin in [t_from, t_to): time until it was in EVERY replica."""
    nodes = sorted(seen)
    lat: list[float] = []
    missing = 0
    for origin in nodes:
        for cid, (o, t_create) in seen[origin].items():
            if o != origin or not (t_from <= t_create < t_to):
                continue
            ts = [seen[r].get(cid) for r in nodes]
            if any(t is None for t in ts):
                missing += 1
                continue
            lat.append(max(t[1] for t in ts if t is not None) - t_create)
    return {"latencies_s": lat, "missing": missing}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    for _ in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── process management ────────────────────────────────────────────────────

_LIVE: list[subprocess.Popen] = []


def _kill_all() -> None:
    """Reliable Windows cleanup: CTRL_BREAK to each node's own process
    group, then terminate/kill whatever is left."""
    procs = [p for p in _LIVE if p.poll() is None]
    for p in procs:
        try:
            if os.name == "nt":
                p.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                p.terminate()
        except (OSError, ValueError):
            pass
    deadline = time.monotonic() + 5.0
    for p in procs:
        try:
            p.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
    for p in procs:
        if p.poll() is None:
            try:
                p.kill()
                p.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
    _LIVE.clear()


atexit.register(_kill_all)


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


class Mesh:
    """N bench-node processes for one run. The runner only writes each
    node's command file and reads each node's own stats/first-seen output;
    nodes never read each other's anything."""

    def __init__(self, cfg: ExperimentConfig, n: int, run_dir: Path, base_port: int, label: str) -> None:
        from starling_net.keys import generate_keypair

        self.cfg = cfg
        self.n = n
        self.dir = run_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.keys_dir = self.dir / "keys"
        self.adj, self.offsets = build_topology(n, cfg.degree)
        self.diameter = diameter(self.adj)
        self.ports = [base_port + i for i in range(n)]
        bad = [p for p in self.ports if p in cfg.forbidden_ports or not _port_free(cfg.host, p)]
        if bad:
            raise RuntimeError(f"ports unavailable for {label}: {bad[:5]}")
        for i in range(n):
            generate_keypair(i, keys_dir=self.keys_dir)
        self.cmd_seq = 0
        self.procs: list[subprocess.Popen] = []
        self.label = label

    def path(self, i: int, suffix: str) -> Path:
        return self.dir / f"node-{i:02d}.{suffix}"

    def start(self) -> None:
        from apps.bench_node import BenchNodeConfig

        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        env = {**os.environ, **self.cfg.child_env}
        for i in range(self.n):
            ncfg = BenchNodeConfig(
                node_id=i,
                listen_port=self.ports[i],
                neighbours=[f"{self.cfg.host}:{self.ports[j]}" for j in self.adj[i]],
                run_dir=str(self.dir),
                keys_dir=str(self.keys_dir),
                claims_per_s=self.cfg.claims_per_node_per_s,
                rate_jitter=self.cfg.rate_jitter,
                embed_dim=self.cfg.embed_dim,
                ae_interval_s=self.cfg.ae_interval_s,
                stats_interval_s=self.cfg.stats_interval_s,
                parent_pid=os.getpid(),
                log_level=self.cfg.node_log_level,
                seed=self.cfg.seed,
            )
            cfg_path = self.path(i, "json")
            cfg_path.write_text(ncfg.model_dump_json(indent=1), encoding="utf-8")
            with open(self.path(i, "log"), "wb") as logf:  # the child keeps its own handle
                p = subprocess.Popen(
                    [sys.executable, str(REPO / "apps" / "bench_node.py"), "--config", str(cfg_path)],
                    cwd=str(REPO),
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                    env=env,
                )
            self.procs.append(p)
            _LIVE.append(p)
        log.info("mesh_started", run=self.label, n=self.n, offsets=self.offsets, diameter=self.diameter)

    def stats(self) -> list[dict[str, Any] | None]:
        return [_read_json(self.path(i, "stats.json")) for i in range(self.n)]

    def check_alive(self) -> None:
        dead = [i for i, p in enumerate(self.procs) if p.poll() is not None]
        if dead:
            tail = self.path(dead[0], "log").read_text(encoding="utf-8", errors="replace")[-1500:]
            raise RuntimeError(f"{self.label}: node(s) {dead} exited early; node-{dead[0]:02d} log tail:\n{tail}")

    def wait_ready(self) -> None:
        deadline = time.monotonic() + self.cfg.ready_timeout_s
        while time.monotonic() < deadline:
            self.check_alive()
            if all(s is not None and s.get("ready") for s in self.stats()):
                return
            time.sleep(self.cfg.poll_s)
        raise RuntimeError(f"{self.label}: nodes not ready within {self.cfg.ready_timeout_s}s")

    def command(self, produce: bool, drop: dict[int, list[int]] | None = None, stop: bool = False) -> float:
        """Write every node's command file; returns the wall time written."""
        self.cmd_seq += 1
        for i in range(self.n):
            payload = {"seq": self.cmd_seq, "produce": produce, "drop": (drop or {}).get(i, []), "stop": stop}
            _write_json_atomic(self.path(i, "cmd.json"), payload)
        return time.time()  # measurement harness, not the identity path

    def wait_applied(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if all(s is not None and s.get("cmd_seq", -1) >= self.cmd_seq for s in self.stats()):
                return
            time.sleep(self.cfg.poll_s)
        log.warning("command_not_applied_everywhere", run=self.label, seq=self.cmd_seq)

    def wait_identical(self, t_from: float) -> tuple[bool, float]:
        """Poll the nodes' own stats until every replica reports the same
        claim-set digest. Returns (identical, seconds since t_from)."""
        deadline = time.monotonic() + self.cfg.settle_timeout_s
        while time.monotonic() < deadline:
            self.check_alive()
            st = self.stats()
            if all(s is not None for s in st):
                digests = {s["digest"] for s in st if s is not None}
                counts = {s["store_claims"] for s in st if s is not None}
                if len(digests) == 1 and len(counts) == 1:
                    newest = max(s["now"]["t"] for s in st if s is not None)
                    return True, newest - t_from
            time.sleep(self.cfg.poll_s)
        return False, float("nan")

    def stop(self) -> None:
        try:
            self.command(produce=False, stop=True)
        except OSError as exc:  # never let cleanup itself fail: fall through to the kill
            log.warning("stop_command_failed", run=self.label, error=str(exc))
        deadline = time.monotonic() + self.cfg.shutdown_grace_s
        for p in self.procs:
            try:
                p.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        _kill_all()

    def first_seen(self) -> dict[int, dict[str, tuple[int, float]]]:
        out: dict[int, dict[str, tuple[int, float]]] = {}
        for i in range(self.n):
            d = _read_json(self.path(i, "seen.json"))
            if d is None:
                raise RuntimeError(f"{self.label}: node-{i:02d} wrote no first-seen table")
            out[i] = {cid: (int(v[0]), float(v[1])) for cid, v in d["first_seen"].items()}
        return out


# ── one scaling run ───────────────────────────────────────────────────────

def _window_rates(stats: list[dict[str, Any]], degree_of: dict[int, int]) -> dict[str, Any]:
    ins, outs, pubs, cpus, rss = [], [], [], [], []
    for s in stats:
        w = s.get("window", {})
        a, b = w.get("start"), w.get("end")
        if not a or not b:
            continue
        dt = max(b["t"] - a["t"], 1e-6)
        ins.append((b["bytes_recv"] - a["bytes_recv"]) / dt)
        pub = (b["bytes_sent"] - a["bytes_sent"]) / dt
        pubs.append(pub)
        # ZeroMQ PUB fans one publish out to every connected subscriber, so
        # the bytes actually leaving the node are publish bytes x its degree.
        outs.append(pub * degree_of[s["node_id"]])
        cpus.append(100.0 * (b["cpu_s"] - a["cpu_s"]) / dt)
        if b.get("rss_mb") is not None:
            rss.append(b["rss_mb"])

    def mm(v: list[float]) -> dict[str, float]:
        return {"mean": statistics.fmean(v), "max": max(v)} if v else {"mean": float("nan"), "max": float("nan")}

    return {
        "in": mm(ins), "out": mm(outs), "publish": mm(pubs),
        "cpu_pct_mean": statistics.fmean(cpus) if cpus else None,
        "cpu_pct_max": max(cpus) if cpus else None,
        "rss_mb_mean": statistics.fmean(rss) if rss else None,
        "rss_mb_max": max(rss) if rss else None,
        "sum_in": sum(ins), "sum_out": sum(outs),
    }


def run_scaling(cfg: ExperimentConfig, n: int, run_dir: Path, base_port: int) -> dict[str, Any]:
    mesh = Mesh(cfg, n, run_dir, base_port, label=f"n{n}")
    try:
        mesh.start()
        mesh.wait_ready()
        time.sleep(cfg.warmup_s)  # ZeroMQ SUB connect handshakes ("slow joiner")
        t0 = mesh.command(produce=True)
        mesh.wait_applied()
        time.sleep(max(0.0, cfg.produce_s - (time.time() - t0)))
        t1 = mesh.command(produce=False)
        mesh.wait_applied()
        identical, settle_s = mesh.wait_identical(t1)
        final_stats = [s for s in mesh.stats() if s is not None]
    finally:
        mesh.stop()

    seen = mesh.first_seen()
    claim_sets = [frozenset(v) for v in seen.values()]
    identical = identical and all(c == claim_sets[0] for c in claim_sets)
    prop = propagation(seen)
    lat_ms = [x * 1000.0 for x in prop["latencies_s"]]
    rates = _window_rates(final_stats, {i: len(mesh.adj[i]) for i in mesh.adj})
    own = [sum(1 for o, _ in seen[i].values() if o == i) for i in seen]
    produce_window = statistics.fmean(
        [s["window"]["end"]["t"] - s["window"]["start"]["t"] for s in final_stats if s["window"].get("end")]
    )
    result = {
        "n": n,
        "degree": max(len(v) for v in mesh.adj.values()),
        "chord_offsets": mesh.offsets,
        "diameter": mesh.diameter,
        "claims_per_node_per_s": statistics.fmean(own) / produce_window,
        "duration_s": produce_window,
        "per_node_bytes_in_per_s": rates["in"],
        "per_node_bytes_out_per_s": rates["out"],
        "per_node_publish_bytes_per_s": rates["publish"],
        "latency_ms": {
            "p50": percentile(lat_ms, 50), "p95": percentile(lat_ms, 95),
            "max": max(lat_ms) if lat_ms else float("nan"),
        },
        "replicas_identical": identical,
        "claims_total": len(frozenset().union(*claim_sets)),
        "claims_missing_somewhere": prop["missing"],
        "settle_after_stop_s": settle_s,
        "rss_mb_mean": rates["rss_mb_mean"],
        "rss_mb_max": rates["rss_mb_max"],
        "cpu_pct_mean": rates["cpu_pct_mean"],
        "cpu_pct_max": rates["cpu_pct_max"],
        "inbound_over_wire_outbound": (rates["sum_in"] / rates["sum_out"]) if rates["sum_out"] else None,
        "publish_errors": sum(s.get("publish_errors", 0) for s in final_stats),
    }
    log.info("run_done", **{k: v for k, v in result.items() if k in ("n", "diameter", "replicas_identical", "claims_total")},
             in_kBps=round(rates["in"]["mean"] / 1e3, 1), p50_ms=round(result["latency_ms"]["p50"]),
             p95_ms=round(result["latency_ms"]["p95"]))
    return result


def run_partition(cfg: ExperimentConfig, run_dir: Path, base_port: int) -> dict[str, Any]:
    pc = cfg.partition
    n = pc.n
    mesh = Mesh(cfg, n, run_dir, base_port, label=f"partition-n{n}")
    side_a = list(range(n // 2))
    side_b = list(range(n // 2, n))
    for side in (side_a, side_b):
        sub = {i: [j for j in mesh.adj[i] if j in side] for i in side}
        if not is_connected(sub):
            raise RuntimeError("a partition half is internally disconnected; pick another split")
    drop = {i: (side_b if i in side_a else side_a) for i in range(n)}
    try:
        mesh.start()
        mesh.wait_ready()
        time.sleep(cfg.warmup_s)
        t0 = mesh.command(produce=True)
        time.sleep(pc.before_s)
        t_cut = mesh.command(produce=True, drop=drop)
        mesh.wait_applied()
        time.sleep(max(0.0, pc.partition_s - (time.time() - t_cut)))
        t_heal = mesh.command(produce=True)
        mesh.wait_applied()
        time.sleep(pc.after_s)
        t_end = mesh.command(produce=False)
        mesh.wait_applied()
        identical, settle_s = mesh.wait_identical(t_end)
    finally:
        mesh.stop()

    seen = mesh.first_seen()
    sets = [frozenset(v) for v in seen.values()]
    identical = identical and all(s == sets[0] for s in sets)
    # Heal-to-identical: every claim created before the heal is in every
    # replica — measured from the instant the heal command was written
    # (nodes apply it within one 0.1 s command poll, so this is conservative).
    pre = propagation(seen, t_from=t0 - 1.0, t_to=t_heal)
    done_at = []
    for origin in seen:
        for cid, (o, tc) in seen[origin].items():
            if o == origin and tc < t_heal:
                ts = [seen[r].get(cid) for r in seen]
                if all(t is not None for t in ts):
                    done_at.append(max(t[1] for t in ts if t is not None))
    heal_s = max(0.0, max(done_at) - t_heal) if done_at else float("nan")
    # Sanity: claims made on one side mid-partition must not have crossed
    # to the other side before the heal.
    leaks = 0
    for origin in seen:
        other = side_b if origin in side_a else side_a
        for cid, (o, tc) in seen[origin].items():
            if o == origin and t_cut + 0.5 <= tc < t_heal - 0.5:
                leaks += sum(1 for r in other if cid in seen[r] and seen[r][cid][1] < t_heal)
    # Claims made during the cut, before the heal, by side: how much each
    # half had to catch up on.
    diverged = sum(
        1 for origin in seen for cid, (o, tc) in seen[origin].items() if o == origin and t_cut <= tc < t_heal
    )
    result = {
        "n": n,
        "partition_s": t_heal - t_cut,
        "heal_to_identical_s": heal_s,
        "replicas_identical": identical,
        "split": [side_a, side_b],
        "claims_made_during_partition": diverged,
        "cross_partition_leaks": leaks,
        "pre_heal_claims_missing_somewhere": pre["missing"],
        "settle_after_stop_s": settle_s,
        "claims_total": len(frozenset().union(*sets)),
        "diameter": mesh.diameter,
    }
    log.info("partition_done", **result)
    return result


# ── centralised comparison (computed) ─────────────────────────────────────

def central_figures(cfg: ExperimentConfig) -> dict[str, Any]:
    c = cfg.central
    width, height, fps, q = 1280, 720, c.fallback_world_fps, None
    wpath = REPO / c.world_config_path
    if wpath.exists():
        cf = (yaml.safe_load(wpath.read_text(encoding="utf-8")) or {}).get("camera_frames", {})
        width, height = cf.get("width_px", width), cf.get("height_px", height)
        fps, q = float(cf.get("fps", fps)), cf.get("jpeg_quality")
    sizes: list[int] = []
    for n in c.tap_cameras:
        last = None
        for _ in range(c.tap_samples_per_camera):
            try:
                with urllib.request.urlopen(c.world_camera_tap_url.format(n=n), timeout=c.tap_timeout_s) as r:
                    body = r.read()
                if body and body[:2] == b"\xff\xd8" and body != last:  # a JPEG, and a new frame
                    sizes.append(len(body))
                    last = body
            except OSError:
                break
            time.sleep(c.tap_interval_s)
    assumptions = [
        "Centralised ingest is COMPUTED, not measured on a network: ingest = N x one camera's stream bitrate.",
        f"H.264 figure: industry-typical 1080p CCTV stream at {c.h264_1080p_bits_per_s / 1e6:g} Mbit/s.",
    ]
    if sizes:
        mean_jpeg = statistics.fmean(sizes)
        assumptions.append(
            f"World-demo figure: mean of {len(sizes)} distinct {width}x{height} JPEG frames (quality {q}) sampled from "
            f"the running world server's camera tap ({c.world_camera_tap_url.format(n='{n}')}), x {fps:g} fps "
            f"from {c.world_config_path}."
        )
        source = "measured_from_live_camera_tap"
    else:
        mean_jpeg = c.assumed_jpeg_bytes
        assumptions.append(
            f"World-demo figure: ASSUMED {mean_jpeg / 1e3:g} KB per {width}x{height} JPEG (q {q}) x {fps:g} fps; "
            "the live camera tap was not reachable."
        )
        source = "assumed"
    return {
        "per_camera_bytes_per_s_world_demo": mean_jpeg * fps,
        "per_camera_bytes_per_s_h264_1080p": c.h264_1080p_bits_per_s / 8.0,
        "assumptions": assumptions,
        "world_demo_source": source,
        "world_demo_mean_jpeg_bytes": mean_jpeg,
        "world_demo_jpeg_samples": len(sizes),
        "world_demo_fps": fps,
    }


# ── plots ─────────────────────────────────────────────────────────────────

# Reference categorical palette (light): blue, orange, aqua; text inks.
_C1, _C2, _C3 = "#2a78d6", "#eb6834", "#1baf7a"
_INK, _INK2, _SURF = "#0b0b0b", "#52514e", "#fcfcfb"


def _style(ax: Any) -> None:
    ax.set_facecolor(_SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#b8b7b2")
    ax.tick_params(colors=_INK2, labelsize=9)
    ax.grid(True, which="major", color="#e6e5e1", linewidth=0.8)
    ax.set_axisbelow(True)


def plot(results: dict[str, Any], cfg: ExperimentConfig) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    runs = [r for r in results["runs"] if r.get("replicas_identical") is not None]
    ns = [r["n"] for r in runs]
    cen = results["central"]

    fig, ax = plt.subplots(figsize=(7.6, 4.6), dpi=150, facecolor=_SURF)
    _style(ax)
    max_in = [r["per_node_bytes_in_per_s"]["max"] / 1e3 for r in runs]
    mean_in = [r["per_node_bytes_in_per_s"]["mean"] / 1e3 for r in runs]
    world = [n * cen["per_camera_bytes_per_s_world_demo"] / 1e3 for n in ns]
    h264 = [n * cen["per_camera_bytes_per_s_h264_1080p"] / 1e3 for n in ns]
    ax.plot(ns, world, color=_C2, lw=2, marker="o", ms=5, label="Central server ingest: N x world-demo JPEG stream")
    ax.plot(ns, h264, color=_C3, lw=2, marker="o", ms=5, label="Central server ingest: N x 1080p H.264 @ 4 Mbit/s")
    ax.plot(ns, max_in, color=_C1, lw=2, marker="o", ms=5, label="Starling busiest node, gossip in (measured)")
    ax.plot(ns, mean_in, color=_C1, lw=1.5, ls="--", marker="o", ms=4, mfc=_SURF,
            label="Starling mean node, gossip in (measured)")
    ax.set_yscale("log")
    ax.set_xlabel("Cameras / nodes (N)", color=_INK2)
    ax.set_ylabel("KB/s at the busiest receiver (log)", color=_INK2)
    ax.set_title("Hotspot bandwidth: one Starling node vs a central video server", color=_INK, fontsize=11, loc="left")
    ax.set_xticks(ns)
    ax.legend(frameon=False, fontsize=8, labelcolor=_INK2, loc="lower right")
    fig.tight_layout()
    fig.savefig(REPO / cfg.out_bandwidth_png, facecolor=_SURF)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.6, 4.4), dpi=150, facecolor=_SURF)
    _style(ax)
    p50 = [r["latency_ms"]["p50"] / 1e3 for r in runs]
    p95 = [r["latency_ms"]["p95"] / 1e3 for r in runs]
    ax.plot(ns, p50, color=_C1, lw=2, marker="o", ms=5, label="p50")
    ax.plot(ns, p95, color=_C2, lw=2, marker="o", ms=5, label="p95")
    for r, y in zip(runs, p95):
        ax.annotate(f"diam {r['diameter']}", (r["n"], y), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8, color=_INK2)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Cameras / nodes (N), degree-4 neighbour graph", color=_INK2)
    ax.set_ylabel("Seconds until a claim is in EVERY replica", color=_INK2)
    ax.set_title("End-to-end claim propagation latency", color=_INK, fontsize=11, loc="left")
    ax.set_xticks(ns)
    ax.legend(frameon=False, fontsize=9, labelcolor=_INK2, loc="upper left")
    fig.tight_layout()
    fig.savefig(REPO / cfg.out_latency_png, facecolor=_SURF)
    plt.close(fig)


# ── main ──────────────────────────────────────────────────────────────────

def _machine() -> dict[str, Any]:
    out: dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
    }
    try:
        import psutil

        vm = psutil.virtual_memory()
        out.update(
            ram_total_gb=round(vm.total / 1e9, 1),
            ram_available_gb_at_start=round(vm.available / 1e9, 1),
            cpu_busy_pct_at_start=psutil.cpu_percent(interval=1.0),
        )
    except ImportError:
        pass
    return out


def _fit_slope(xs: list[float], ys: list[float]) -> tuple[float, float]:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return b, my - b * mx


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Starling gossip + CRDT scalability experiment")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--ns", type=str, default=None, help="override, e.g. 4,8,16")
    parser.add_argument("--produce-s", type=float, default=None)
    parser.add_argument("--no-partition", action="store_true")
    parser.add_argument("--out-json", type=str, default=None)
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--plot-only", action="store_true", help="redraw the PNGs from the existing JSON")
    args = parser.parse_args(argv)

    from starling_net.logging import setup_logging

    setup_logging(None)
    structlog.contextvars.bind_contextvars(node_id="scale-runner")
    cfg = load_config(args.config)
    if args.ns:
        cfg.ns = [int(x) for x in args.ns.split(",")]
    if args.produce_s is not None:
        cfg.produce_s = args.produce_s
    if args.no_partition:
        cfg.partition.enabled = False
    if args.out_json:
        cfg.out_json = args.out_json
    cfg = ExperimentConfig.model_validate(cfg.model_dump())
    if args.plot_only:
        plot(json.loads((REPO / cfg.out_json).read_text(encoding="utf-8")), cfg)
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    root = REPO / cfg.scratch_root / f"run-{stamp}"
    root.mkdir(parents=True, exist_ok=True)
    machine = _machine()
    log.info("experiment_start", scratch=str(root), ns=cfg.ns, machine=machine)

    def _on_sigint(signum: int, frame: Any) -> None:
        _kill_all()
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _on_sigint)

    runs: list[dict[str, Any]] = []
    notes: list[str] = []
    partition: dict[str, Any] | None = None
    rss_per_node: float | None = None
    try:
        for idx, n in enumerate(cfg.ns):
            if rss_per_node is not None and n * rss_per_node > cfg.max_total_rss_mb:
                notes.append(f"N={n} skipped: projected {n * rss_per_node:.0f} MB of node RSS > {cfg.max_total_rss_mb:.0f} MB cap.")
                log.warning("skip_n_memory", n=n)
                continue
            try:
                r = run_scaling(cfg, n, root / f"n{n:03d}", cfg.base_port + idx * cfg.port_stride)
            except (RuntimeError, OSError) as exc:
                notes.append(f"N={n} failed: {exc}".splitlines()[0])
                log.error("run_failed", n=n, error=str(exc))
                continue
            runs.append(r)
            if r["rss_mb_max"] is not None:
                rss_per_node = r["rss_mb_max"]
        if cfg.partition.enabled:
            try:
                partition = run_partition(
                    cfg, root / f"partition-n{cfg.partition.n:03d}",
                    cfg.base_port + len(cfg.ns) * cfg.port_stride,
                )
            except (RuntimeError, OSError) as exc:
                notes.append(f"Partition test failed: {exc}".splitlines()[0])
                log.error("partition_failed", error=str(exc))
    finally:
        _kill_all()

    central = central_figures(cfg)
    if len(runs) >= 2:
        slope, icpt = _fit_slope([r["n"] for r in runs], [r["per_node_bytes_in_per_s"]["mean"] for r in runs])
        slope_max, _ = _fit_slope([r["n"] for r in runs], [r["per_node_bytes_in_per_s"]["max"] for r in runs])
        per_claim = statistics.fmean(
            r["per_node_bytes_in_per_s"]["mean"] / (r["n"] * r["claims_per_node_per_s"]) for r in runs
        )
        notes.append(
            f"Linear fit of mean per-node inbound gossip vs N: {slope / 1e3:.2f} KB/s per added node "
            f"(intercept {icpt / 1e3:.2f} KB/s); busiest node: {slope_max / 1e3:.2f} KB/s per added node."
        )
        notes.append(
            f"Inbound bytes per claim delivered to a replica (all redundancy and anti-entropy overhead "
            f"included), averaged over runs: {per_claim:.0f} B."
        )
        for key, label in (("per_camera_bytes_per_s_world_demo", "world-demo JPEG"),
                           ("per_camera_bytes_per_s_h264_1080p", "1080p H.264")):
            v = central[key]
            notes.append(
                f"Aggregate network bytes cross over ({label}): full replication moves ~N x {slope_max / 1e3:.2f} KB/s "
                f"into each of N nodes (O(N^2) total) vs N x {v / 1e3:.0f} KB/s into one server (O(N) total) — "
                f"equal at N ~ {v / slope_max:.0f} for the busiest-node slope, {v / slope:.0f} for the mean."
            )
    results = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": machine,
        "config": cfg.model_dump(),
        "runs": runs,
        "partition_test": partition,
        "central": central,
        "notes": notes,
    }
    out = REPO / cfg.out_json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1, allow_nan=False, default=str) if _finite(results)
                   else json.dumps(_denan(results), indent=1), encoding="utf-8")
    log.info("results_written", path=str(out))
    if runs and not args.no_plots:
        plot(results, cfg)
    return 0 if runs else 1


def _finite(x: Any) -> bool:
    if isinstance(x, float):
        return math.isfinite(x)
    if isinstance(x, dict):
        return all(_finite(v) for v in x.values())
    if isinstance(x, (list, tuple)):
        return all(_finite(v) for v in x)
    return True


def _denan(x: Any) -> Any:
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _denan(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_denan(v) for v in x]
    return x


if __name__ == "__main__":
    sys.exit(main())
