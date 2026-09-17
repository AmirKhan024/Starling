"""scripts/run_headline.py
----------------------------
The headline three-way experiment (WP-14 Part 4 / spec S10) — the single
experiment most likely to convince a reviewer. The IDENTICAL input videos
and ground truth, run three ways:

  Arm 1: centralized baseline (`apps/baseline.py`, the V1 system)
  Arm 2: Starling, healthy network            (`scenarios/healthy.yaml`)
  Arm 3: Starling, partitioned + one lying node (`scenarios/headline.yaml`)

This session verifies this script with `--dry-run` ONLY (WP-14 Part 4 own
rule: "it is long; do not execute it in this session"). Whoever runs it
for real next (`--repeat 5`, no `--dry-run`) fills `docs/results_headline
.md`'s TBD placeholders in from that run's `results.json` — same
scaffold-now/fill-in-later convention as `scripts/run_byzantine_sweep.py`
and `docs/results_c2.md`.

Honest architecture note: Arm 3 needs a REAL partition and a REAL live
attack switch, which need actual container network namespaces
(`deploy/netem/apply.py`, `starling_eval.runner.run_docker_once`) — the
same limitation `scenarios/east_wing_drop.yaml` already states for
`--local` mode. Arm 3 therefore can only ever be run via `docker compose`,
not `--local`; Arm 2 (no events) can use either.

Honest scope note on the metrics table: `starling_eval.runner`'s existing
`run_local_once`/`run_docker_once` only ever computed SYSTEM-level numbers
(bytes/node-hour, wall-clock, claim counts) — nothing in this repo today
wires a scenario run's OWN output into `starling_eval.metrics`'s tracking
functions (IDF1/MOTA/HOTA need a predicted-tracks file in MOTChallenge
format compared against `data/gt/`, which no scenario runner emits yet).
This script computes and reports the system metrics it can actually
produce from a real run, and marks every other column in the headline
table "not yet measured — see docs/results_headline.md" rather than
inventing a number for it (STARLING_BUILD_STATE.md §12 rule 9).

Usage
-----
    python scripts/run_headline.py --dry-run
    python scripts/run_headline.py --repeat 5 --out results/headline
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from starling_eval.runner import run_baseline_comparison, run_docker_once, run_local_once
from starling_eval.scenario import Scenario, load_scenario

HEADLINE_METRICS = [
    "IDF1", "MOTA", "HOTA", "ID switches",
    "identity consistency after merge", "time to reconverge",
    "unresolved fork rate", "candidate region area", "false exclusion rate",
    "bytes per node-hour", "end-to-end p95 latency",
]

ARM_DESCRIPTIONS = {
    "baseline": "Arm 1: centralized baseline (apps/baseline.py, V1)",
    "starling_healthy": "Arm 2: Starling, healthy network (scenarios/healthy.yaml, --local)",
    "starling_headline": "Arm 3: Starling, partitioned + fabricate@0.4 (scenarios/headline.yaml, docker compose)",
}


@dataclass
class ArmRun:
    arm: str
    bytes_per_node_hour: Optional[float]
    wall_clock_s: Optional[float]
    total_claims: Optional[float]
    returncode: Optional[int] = None


def _mean_std(values: list[float]) -> tuple[float, float]:
    values = [v for v in values if v is not None]
    if not values:
        return 0.0, 0.0
    mean = statistics.mean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return mean, std


def planned_arms(repeat: int) -> list[tuple[str, str, int]]:
    """`[(arm, mode, repeat_idx), ...]` — the exact list `--dry-run` prints."""
    return [
        ("baseline", "subprocess (apps/baseline.py)", i) for i in range(repeat)
    ] + [
        ("starling_healthy", "--local (scenarios/healthy.yaml)", i) for i in range(repeat)
    ] + [
        ("starling_headline", "docker compose (scenarios/headline.yaml)", i) for i in range(repeat)
    ]


def run_arm_baseline(scenario: Scenario, out_dir: Path, repeat_idx: int) -> ArmRun:
    run_dir = out_dir / "baseline" / f"run_{repeat_idx:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    result = run_baseline_comparison(scenario, run_dir)
    return ArmRun(
        arm="baseline",
        bytes_per_node_hour=0.0,  # centralized: no gossip at all -- this IS the comparison point, not a missing number
        wall_clock_s=None,
        total_claims=result["stats"].get("sightings") if result.get("stats") else None,
        returncode=result["returncode"],
    )


def run_arm_healthy(scenario: Scenario, out_dir: Path, repeat_idx: int, keys_dir: Optional[Path]) -> ArmRun:
    run_dir = out_dir / "starling_healthy" / f"run_{repeat_idx:02d}"
    result = run_local_once(scenario, run_dir, keys_dir=keys_dir)
    sysm = result["metrics"]["system"]
    return ArmRun(
        arm="starling_healthy",
        bytes_per_node_hour=sysm["bytes_per_node_hour"],
        wall_clock_s=result["wall_clock_s"],
        total_claims=sysm["total_claims"],
    )


def run_arm_headline(scenario: Scenario, out_dir: Path, repeat_idx: int) -> ArmRun:
    run_dir = out_dir / "starling_headline" / f"run_{repeat_idx:02d}"
    result = run_docker_once(scenario, run_dir)
    sysm = result["metrics"]["system"]
    return ArmRun(
        arm="starling_headline",
        bytes_per_node_hour=sysm["bytes_per_node_hour"],
        wall_clock_s=result["wall_clock_s"],
        total_claims=sysm["total_claims"],
    )


def _write_results_doc(out_dir: Path, repeat: int, arm_runs: dict[str, list[ArmRun]]) -> None:
    summary = {}
    for arm, runs in arm_runs.items():
        bph_mean, bph_std = _mean_std([r.bytes_per_node_hour for r in runs])
        wall_mean, wall_std = _mean_std([r.wall_clock_s for r in runs])
        summary[arm] = {
            "bytes_per_node_hour": {"mean": bph_mean, "std": bph_std},
            "wall_clock_s": {"mean": wall_mean, "std": wall_std},
            "runs": [asdict(r) for r in runs],
        }

    results_json = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repeat": repeat,
        "arms": summary,
    }
    (out_dir / "results.json").write_text(json.dumps(results_json, indent=2), encoding="utf-8")

    lines = [
        "# Headline results — the three-way failure-mode experiment", "",
        f"Repeats: {repeat}  |  Generated: {results_json['generated_at']}", "",
        "**A single run of a distributed system is not evidence.** Every number",
        f"below is mean +/- std over {repeat} repeats, or is marked not yet measured.", "",
        "## The one table", "",
        "| Arm | " + " | ".join(HEADLINE_METRICS) + " |",
        "|---|" + "---|" * len(HEADLINE_METRICS),
    ]
    for arm in ("baseline", "starling_healthy", "starling_headline"):
        if arm not in summary:
            continue
        bph = summary[arm]["bytes_per_node_hour"]
        row_values = []
        for metric in HEADLINE_METRICS:
            if metric == "bytes per node-hour":
                row_values.append(f"{bph['mean']:.1f} +/- {bph['std']:.1f}")
            else:
                row_values.append("not yet measured")
        lines.append(f"| {ARM_DESCRIPTIONS[arm]} | " + " | ".join(row_values) + " |")

    lines += [
        "", "## Why most cells above say \"not yet measured\"", "",
        "`starling_eval.runner`'s `run_local_once`/`run_docker_once` compute",
        "SYSTEM-level numbers only (bytes/node-hour, wall-clock, claim counts) —",
        "nothing in this repo yet wires a scenario run's own claim/resolver output",
        "into `starling_eval.metrics`'s tracking functions (IDF1/MOTA/HOTA need a",
        "predicted-tracks file in MOTChallenge format compared against `data/gt/`,",
        "which no scenario runner emits). Filling in a plausible-looking number",
        "for any of them without that pipeline would violate",
        "STARLING_BUILD_STATE.md §12 rule 9 — so they stay `not yet measured` here",
        "rather than being estimated.",
        "",
        "## Timeline plot", "",
        "TBD — a plot of per-arm activity (claims/attestations/gossip observed)",
        "over the scenario's 600s, showing arm 1 producing NO output at all during",
        "the [120, 300]s partition window (its coordinator is unreachable), while",
        "arms 2 and 3 continue, arm 3 visibly degrading (fewer/less-confident",
        "claims, dropped/rejected fabricated ones) rather than stopping. Requires a",
        "real run's merged timeline (`_merge_timeline` in `starling_eval.runner`,",
        "docker-mode log collection) — none exists yet.", "",
        "## What Arm 3 does worse than Arm 2 (required, not optional)", "",
        "TBD — this must be filled in honestly once real numbers exist. Expected,",
        "not-yet-measured candidates worth checking specifically: higher end-to-end",
        "claim latency during and immediately after the partition (anti-entropy",
        "catch-up cost), a nonzero unresolved-fork rate where Arm 2 has none, a",
        "temporarily larger candidate-region area for identities that crossed",
        "through node-02 while it was fabricating, and the bytes/node-hour cost of",
        "reconverging after heal. A results table with no cost stated is not",
        "credible — do not skip this section once real numbers are in hand.",
    ]
    (Path("docs") / "results_headline.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="WP-14 headline three-way experiment: baseline vs. Starling healthy vs. Starling partitioned+Byzantine")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--keys-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="list all three arms and their run plan, execute nothing")
    args = parser.parse_args(argv)

    repeat = max(args.repeat, 1)
    plan = planned_arms(repeat)

    if args.dry_run:
        for arm, mode, repeat_idx in plan:
            print(f"{ARM_DESCRIPTIONS[arm]:<75} mode={mode:<45} repeat={repeat_idx}")
        print(f"\n{len(plan)} planned runs total (3 arms x {repeat} repeats)")
        return

    out_dir = args.out or Path("results") / f"headline_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    healthy_scenario = load_scenario(Path("scenarios/healthy.yaml"))
    headline_scenario = load_scenario(Path("scenarios/headline.yaml"))

    arm_runs: dict[str, list[ArmRun]] = {"baseline": [], "starling_healthy": [], "starling_headline": []}
    for i in range(repeat):
        arm_runs["baseline"].append(run_arm_baseline(healthy_scenario, out_dir, i))
        arm_runs["starling_healthy"].append(run_arm_healthy(healthy_scenario, out_dir, i, args.keys_dir))
        arm_runs["starling_headline"].append(run_arm_headline(headline_scenario, out_dir, i))
        print(f"[run_headline] repeat {i + 1}/{repeat} complete")

    _write_results_doc(out_dir, repeat, arm_runs)
    print(f"[run_headline] wrote {out_dir / 'results.json'} and docs/results_headline.md")


if __name__ == "__main__":
    main()
