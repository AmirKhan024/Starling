"""starling_eval/runner.py
----------------------------
One command that runs a scenario end to end and emits numbers. This is
what makes ablations cheap enough to actually run, which is what makes the
rest of the project finishable — it exists in WP-11, *before* the hard
distributed-systems work packages, so there is always something to point a
metric at.

    python -m starling_eval.runner scenarios/east_wing_drop.yaml [--local] [--out DIR] [--repeat N] [--compare baseline]

`--local` runs plain `apps/node.py` subprocesses — no Docker required, so
iteration is fast. This is the ONLY path exercised by this session's own
tests. It has one honest limitation, recorded in the results themselves
rather than hidden: it cannot apply the scenario's network events
(partition/degrade/kill/revive/lie) at all, since those need iptables/tc
inside real container network namespaces (deploy/netem/apply.py). Without
`--local`, the runner drives `docker compose` and applies the timeline for
real, but that path was not run end-to-end this session (consistent with
Prompt 3/4: `docker compose up` itself wasn't exercised there either).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from starling_eval.metrics import bytes_per_node_hour
from starling_eval.scenario import Scenario, load_scenario

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ── local (subprocess) node management ───────────────────────────────────────

@dataclass
class _NodeProcess:
    node_id: int
    proc: subprocess.Popen
    log_file: Any
    log_path: Path
    db_path: Path


def _ring_neighbours(nodes: list[int], node_id: int) -> list[str]:
    nodes_sorted = sorted(nodes)
    n = len(nodes_sorted)
    if n <= 1:
        return []
    idx = nodes_sorted.index(node_id)
    neighbour_ids = {nodes_sorted[(idx - 1) % n], nodes_sorted[(idx + 1) % n]}
    return [f"127.0.0.1:{5555 + nid}" for nid in sorted(neighbour_ids)]


def _build_local_node_config(scenario: Scenario, node_id: int, out_dir: Path) -> Path:
    cfg = {
        "node_id": node_id,
        "name": f"node-{node_id:02d}",
        "source": scenario.videos[node_id],
        "db_path": str(out_dir / "data" / "nodes" / f"node-{node_id:02d}" / "local.db"),
        "stream_epoch": scenario.stream_epoch,
        "net": {
            "listen_port": 5555 + node_id,
            "neighbours": _ring_neighbours(scenario.nodes, node_id),
            "gossip_interval_s": 2.0,
        },
    }
    config_path = out_dir / "configs" / f"node-{node_id:02d}.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return config_path


def _start_local_node(
    scenario: Scenario, node_id: int, out_dir: Path, keys_dir: Optional[Path]
) -> _NodeProcess:
    config_path = _build_local_node_config(scenario, node_id, out_dir)
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"node-{node_id:02d}.jsonl"
    log_file = open(log_path, "w", encoding="utf-8")

    cmd = [sys.executable, "apps/node.py", "--config", str(config_path), "--speed", str(scenario.speed)]
    if keys_dir is not None:
        cmd += ["--keys-dir", str(keys_dir)]

    proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=log_file, stderr=subprocess.STDOUT)
    db_path = out_dir / "data" / "nodes" / f"node-{node_id:02d}" / "local.db"
    return _NodeProcess(node_id=node_id, proc=proc, log_file=log_file, log_path=log_path, db_path=db_path)


def _stop_local_node(node: _NodeProcess, grace_s: float = 5.0) -> None:
    if node.proc.poll() is None:
        node.proc.terminate()
        try:
            node.proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            node.proc.kill()
            try:
                node.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    node.log_file.close()


# ── collecting results ───────────────────────────────────────────────────────

def _extract_last_gossip_stats(log_path: Path) -> Optional[dict]:
    if not log_path.exists():
        return None
    last = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("event") == "node_housekeeping" and entry.get("gossip_stats"):
            last = entry["gossip_stats"]
    return last


def _count_claims(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    finally:
        conn.close()


def _merge_timeline(nodes: list[_NodeProcess], out_dir: Path) -> Path:
    entries = []
    for node in nodes:
        if not node.log_path.exists():
            continue
        for line in node.log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    entries.sort(key=lambda e: e.get("timestamp", ""))

    out_path = out_dir / "timeline.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return out_path


def run_local_once(scenario: Scenario, out_dir: Path, keys_dir: Optional[Path] = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes = [_start_local_node(scenario, nid, out_dir, keys_dir) for nid in scenario.nodes]

    if scenario.events:
        (out_dir / "LOCAL_MODE_LIMITATIONS.txt").write_text(
            "This run used --local: network events (partition/degrade/kill/"
            "revive/lie) require Docker container network namespaces and "
            "were NOT applied. Run without --local (docker compose) to "
            "exercise them for real.\n",
            encoding="utf-8",
        )

    start = time.monotonic()
    timeout_s = scenario.duration_s / max(scenario.speed, 1e-6) + 30.0
    deadline = start + timeout_s
    for node in nodes:
        remaining = max(deadline - time.monotonic(), 0.0)
        try:
            node.proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            pass  # still running at the scenario's nominal duration; stopped below
    for node in nodes:
        _stop_local_node(node)
    wall_clock_s = time.monotonic() - start

    _merge_timeline(nodes, out_dir)

    gossip_stats_list = [
        s for s in (_extract_last_gossip_stats(n.log_path) for n in nodes) if s is not None
    ]
    total_claims = sum(_count_claims(n.db_path) for n in nodes)
    node_summaries = [
        {"node_id": n.node_id, "claims": _count_claims(n.db_path), "returncode": n.proc.returncode}
        for n in nodes
    ]

    metrics = {
        "system": {
            "bytes_per_node_hour": (
                bytes_per_node_hour(gossip_stats_list, wall_clock_s) if gossip_stats_list else 0.0
            ),
            "wall_clock_s": wall_clock_s,
            "total_claims": total_claims,
            "nodes": len(nodes),
        }
    }
    return {"metrics": metrics, "nodes": node_summaries, "wall_clock_s": wall_clock_s}


# ── docker mode (not exercised by this session's tests) ─────────────────────

def run_docker_once(scenario: Scenario, out_dir: Path) -> dict:
    """Overwrites configs/nodes/node-NN.yaml (the paths deploy/docker-
    compose.yml mounts) with this scenario's stream_epoch injected, brings
    the compose stack up, applies the scenario's timeline for real via
    deploy/netem/apply.py in a background thread, waits duration_s, tears
    down, and collects each container's logs. NOT exercised by this
    session's tests — see the module docstring.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    compose_file = REPO_ROOT / "deploy" / "docker-compose.yml"

    for node_id in scenario.nodes:
        cfg_path = REPO_ROOT / "configs" / "nodes" / f"node-{node_id:02d}.yaml"
        if cfg_path.exists():
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            data["stream_epoch"] = scenario.stream_epoch
            cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    subprocess.run(["docker", "compose", "-f", str(compose_file), "up", "-d"], cwd=str(REPO_ROOT), check=False)

    scenario_path = REPO_ROOT / "scenarios" / f"{scenario.name}.yaml"
    apply_thread = threading.Thread(
        target=lambda: subprocess.run(
            [sys.executable, "deploy/netem/apply.py", str(scenario_path)],
            cwd=str(REPO_ROOT), check=False,
        ),
        daemon=True,
    )
    apply_thread.start()

    time.sleep(scenario.duration_s / max(scenario.speed, 1e-6))

    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    for node_id in scenario.nodes:
        container = f"starling-node-{node_id:02d}"
        result = subprocess.run(
            ["docker", "logs", container], cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
        )
        (logs_dir / f"node-{node_id:02d}.jsonl").write_text(result.stdout, encoding="utf-8")

    subprocess.run(["docker", "compose", "-f", str(compose_file), "down"], cwd=str(REPO_ROOT), check=False)

    return {
        "metrics": {
            "system": {
                "bytes_per_node_hour": 0.0,
                "wall_clock_s": scenario.duration_s,
                "total_claims": 0,
                "nodes": len(scenario.nodes),
            }
        },
        "nodes": [],
        "wall_clock_s": scenario.duration_s,
        "note": "docker mode: metrics collection from container logs is best-effort and untested this session",
    }


# ── baseline comparison ──────────────────────────────────────────────────────

def run_baseline_comparison(scenario: Scenario, out_dir: Path) -> dict:
    videos = [scenario.videos[nid] for nid in sorted(scenario.nodes)]
    db_path = out_dir / "baseline.db"
    result = subprocess.run(
        [
            sys.executable, "apps/baseline.py",
            "--videos", *videos,
            "--output", str(out_dir / "baseline_out"),
            "--db", str(db_path),
            "--no-video", "--device", "cpu",
        ],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600,
        encoding="utf-8", errors="replace",
    )

    stats: dict = {}
    if db_path.exists():
        from starling_store.identity_store import IdentityStore
        stats = IdentityStore(db_path=str(db_path)).stats()

    return {"returncode": result.returncode, "stats": stats}


# ── results output ───────────────────────────────────────────────────────────

def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = statistics.mean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return mean, std


def _write_results(out_dir: Path, scenario: Scenario, runs: list[dict], baseline: Optional[dict]) -> None:
    bph_mean, bph_std = _mean_std([r["metrics"]["system"]["bytes_per_node_hour"] for r in runs])
    claims_mean, claims_std = _mean_std([r["metrics"]["system"]["total_claims"] for r in runs])
    wall_mean, wall_std = _mean_std([r["wall_clock_s"] for r in runs])

    summary = {
        "scenario": scenario.name,
        "repeats": len(runs),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system": {
            "bytes_per_node_hour": {"mean": bph_mean, "std": bph_std},
            "total_claims": {"mean": claims_mean, "std": claims_std},
            "wall_clock_s": {"mean": wall_mean, "std": wall_std},
        },
        "runs": runs,
    }
    if baseline is not None:
        summary["baseline"] = baseline

    (out_dir / "results.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    lines = [
        f"# Results — {scenario.name}", "",
        f"Repeats: {len(runs)}  |  Generated: {summary['generated_at']}", "",
        "| Metric | Mean | Std |",
        "|---|---|---|",
        f"| bytes/node-hour | {bph_mean:.1f} | {bph_std:.1f} |",
        f"| total claims | {claims_mean:.1f} | {claims_std:.1f} |",
        f"| wall clock (s) | {wall_mean:.1f} | {wall_std:.1f} |",
    ]
    if baseline is not None:
        lines += ["", "## Baseline comparison (apps/baseline.py, centralized control condition)", "",
                   f"Return code: {baseline['returncode']}  |  Stats: {baseline['stats']}"]
    (out_dir / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _maybe_push_wandb(scenario: Scenario, results_json_path: Path) -> None:
    """Never fails the run if W&B is unavailable or misconfigured."""
    if not os.environ.get("WANDB_API_KEY"):
        return
    try:
        import wandb

        with open(results_json_path, encoding="utf-8") as f:
            summary = json.load(f)
        run = wandb.init(project="starling", name=scenario.name, config={"scenario": scenario.name})
        wandb.log(summary.get("system", {}))
        run.finish()
    except Exception as exc:  # noqa: BLE001 — must never fail the run
        print(f"[runner] W&B push skipped: {exc}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Run a Starling scenario end to end and emit metrics")
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--local", action="store_true", help="plain subprocesses, no Docker required")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--compare", choices=["baseline"], default=None)
    parser.add_argument("--keys-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    scenario = load_scenario(args.scenario)

    if args.out is not None:
        out_dir = args.out
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = Path("results") / f"{scenario.name}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.local:
        print(
            "[runner] Docker mode: not exercised by this session's tests; "
            "requires `docker compose up` and iptables/tc inside containers. "
            "Pass --local for a fast, Docker-free run.",
            file=sys.stderr,
        )

    repeat = max(args.repeat, 1)
    runs = []
    for i in range(repeat):
        run_dir = (out_dir / f"run_{i:02d}") if repeat > 1 else out_dir
        result = (
            run_local_once(scenario, run_dir, keys_dir=args.keys_dir)
            if args.local
            else run_docker_once(scenario, run_dir)
        )
        runs.append(result)
        print(f"[runner] run {i + 1}/{repeat} complete: {result['metrics']['system']}")

    baseline = run_baseline_comparison(scenario, out_dir) if args.compare == "baseline" else None

    _write_results(out_dir, scenario, runs, baseline)
    _maybe_push_wandb(scenario, out_dir / "results.json")

    print(f"[runner] wrote {out_dir / 'results.json'} and {out_dir / 'results.md'}")


if __name__ == "__main__":
    main()
