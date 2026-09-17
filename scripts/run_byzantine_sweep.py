"""scripts/run_byzantine_sweep.py
-----------------------------------
Headline WP-10 experiment (STARLING_BUILD_STATE.md WP-10 task 6 /
docs/threat_model.md §5): accuracy vs. fraction of malicious nodes (f/n),
per attack class, per aggregation method, against the `unweighted`
baseline. Reports the false-claim rejection rate AND the false-rejection
rate together (a rejection rate alone is not interpretable), a
fabricating node's reputation over the run, and — required, not optional
— the f/n at which reputation-weighted aggregation stops beating the
unweighted baseline.

This session does NOT run the full sweep (WP-10 Part 4 rule: it is long).
`--dry-run` lists the full planned run matrix — every (f/n, attack,
method, repeat) point — without executing anything. Whoever runs it for
real afterwards (`--repeat 5`, no `--dry-run`) fills docs/results_c2.md's
placeholders in with the actual numbers.

Simulation model (synthetic, not a live multi-node docker run — this
project's own "make ablations cheap enough to actually run" precedent,
e.g. `starling_eval.runner`'s `--local` mode, argues against spinning up
`n` real video-backed node processes per sweep point): one synthetic
person walks a straight line at `V_TRUE_M_S` across an open navmesh. At
each tick, `n` nodes each report a position claim — the `n - f` honest
ones with Gaussian sensor noise, the `f` malicious ones transformed by
`starling_consensus.attacks.AttackInjector` running the sweep's attack
class at intensity 1.0. Every claim is scored with
`starling_consensus.plausibility.check` against the last FUSED position
(never ground truth — a real fusing node never sees it either), each
node's local `ReputationTable` entry is updated from that score, and the
tick's claims are fused via `starling_consensus.aggregate.aggregate_position`
under the sweep's method. Accuracy is the fused position's error against
the (only ever synthetically known) ground truth.

Known limitation, stated rather than hidden (docs/threat_model.md's own
practice): this harness has no coverage-attestation model at all, so
SUPPRESS's detection channel — `starling_attest.negative_evidence
.detect_omission`, exercised directly in tests/test_negative_evidence.py —
is not exercised here. A SUPPRESS row in this sweep's results measures
only what claim-level plausibility checking (nothing) can say about a
claim that was never sent — expect no rejection signal there by
construction, not as a bug.

Usage
-----
    python scripts/run_byzantine_sweep.py --dry-run
    python scripts/run_byzantine_sweep.py --repeat 5 --out results/byzantine_sweep
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from starling_consensus.aggregate import aggregate_position
from starling_consensus.attacks import SYNTHETIC_SEQ_BASE, AttackInjector
from starling_consensus.plausibility import CorroboratedState, check
from starling_consensus.reputation import ReputationTable
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_node.config import AggregateConfig, AttackConfig, PlausibilityConfig, ReputationConfig

N_NODES = 10
N_TICKS = 60
DT_S = 1.0
V_TRUE_M_S = 1.0
V_MAX_M_S = V_TRUE_M_S + 0.6  # headroom over the true walking speed, like every other v_max default
POS_SIGMA_HONEST_M = 0.3

F_OVER_N_GRID = [round(float(x), 2) for x in np.arange(0.0, 0.51, 0.05)]
ATTACKS = ["fabricate", "suppress", "replay", "mixed"]
METHODS = ["unweighted", "reputation", "trimmed_mean", "krum"]


def _open_navmesh() -> NavMesh:
    # 130x130m at 1m cells: comfortably covers the trajectory below
    # (~85m total displacement) with margin for fabricated positions to
    # land off it, while staying small enough that the per-tick, per-claim
    # geodesic Dijkstra (starling_geometry.reachability's distance_field,
    # which cannot cache across ticks here since the reference position
    # moves every tick) stays affordable across hundreds of simulate_run
    # calls.
    return NavMesh(grid=np.ones((130, 130), dtype=bool), origin=(0.0, 0.0), cell_size=1.0)


@dataclass
class RunResult:
    f_over_n: float
    attack: str
    method: str
    seed: int
    mean_position_error_m: float
    false_claim_rejection_rate: float  # NaN when the attack injects nothing plausibility can see (e.g. suppress)
    false_rejection_rate: float
    final_malicious_reputation: float


def simulate_run(f_over_n: float, attack: str, method: str, seed: int, navmesh: NavMesh) -> RunResult:
    rng = np.random.default_rng(seed)
    n = N_NODES
    f = round(f_over_n * n)
    malicious_ids = set(range(f))

    geometry = ReachabilityModel(navmesh, v_max_m_s=V_MAX_M_S)
    plaus_cfg = PlausibilityConfig(v_max_m_s=V_MAX_M_S)
    rep_cfg = ReputationConfig()
    agg_cfg = AggregateConfig()
    attack_cfg = AttackConfig(attack=attack, intensity=1.0)

    # One neutral "fusing" observer's own reputation table — node_id=-1 is
    # not a real node, just this table's owner identity.
    reputation = ReputationTable(node_id=-1, cfg=rep_cfg)
    injectors = {
        nid: AttackInjector(node_id=nid, attack=attack, intensity=1.0, cfg=attack_cfg, seed=seed * 1000 + nid)
        for nid in malicious_ids
    }

    true_pos = np.array([20.0, 20.0])
    direction = np.array([1.0, 0.3])
    direction = direction / np.linalg.norm(direction)
    fused_pos: Optional[tuple[float, float]] = (float(true_pos[0]), float(true_pos[1]))

    position_errors: list[float] = []
    injected_total = 0
    injected_rejected = 0
    honest_total = 0
    honest_rejected = 0

    for tick in range(N_TICKS):
        t_media = tick * DT_S
        true_pos = true_pos + direction * V_TRUE_M_S * DT_S

        claims: list[dict[str, Any]] = []
        for nid in range(n):
            noisy = true_pos + rng.normal(scale=POS_SIGMA_HONEST_M, size=2)
            record = {
                "claim_id": f"SIM-{seed}-{nid}-{tick}",
                "node_id": nid,
                "seq": tick,
                "hlc_physical_ms": int(t_media * 1000),
                "hlc_logical": 0,
                "t_media": t_media,
                "world_x": float(noisy[0]),
                "world_y": float(noisy[1]),
                "pos_sigma": POS_SIGMA_HONEST_M,
                "confidence": 0.9,
                "quality": 0.8,
            }
            if nid in malicious_ids:
                claims.extend(injectors[nid].apply_to_claims([record], t_media, navmesh))
            else:
                claims.append(record)

        state = CorroboratedState(
            last_position=fused_pos,
            last_t_media=t_media - DT_S,
            corroborating_claims=claims,
            now_physical_ms=int(t_media * 1000),
        )
        for claim in claims:
            result = check(claim, state, geometry, plaus_cfg)
            reputation.observe(claim["node_id"], result)

            is_injected = claim["node_id"] in malicious_ids and claim["seq"] >= SYNTHETIC_SEQ_BASE
            if is_injected:
                injected_total += 1
                injected_rejected += 0 if result.passed else 1
            elif claim["node_id"] not in malicious_ids:
                honest_total += 1
                honest_rejected += 0 if result.passed else 1

        reputation_map = {nid: reputation.aggregate(nid) for nid in range(n)}
        fused = aggregate_position(claims, reputation_map, method, agg_cfg)
        if fused.position is not None:
            fused_pos = fused.position
            position_errors.append(float(np.hypot(fused.position[0] - true_pos[0], fused.position[1] - true_pos[1])))
        else:
            position_errors.append(float("nan"))

    final_malicious_reputation = (
        statistics.mean(reputation.aggregate(nid) for nid in malicious_ids) if malicious_ids else 1.0
    )
    return RunResult(
        f_over_n=f_over_n,
        attack=attack,
        method=method,
        seed=seed,
        mean_position_error_m=float(np.nanmean(position_errors)) if position_errors else float("nan"),
        false_claim_rejection_rate=(injected_rejected / injected_total) if injected_total else float("nan"),
        false_rejection_rate=(honest_rejected / honest_total) if honest_total else 0.0,
        final_malicious_reputation=final_malicious_reputation,
    )


def planned_runs(repeat: int) -> list[tuple[float, str, str, int]]:
    return [
        (f_over_n, attack, method, repeat_idx)
        for f_over_n, attack, method, repeat_idx in itertools.product(
            F_OVER_N_GRID, ATTACKS, METHODS, range(repeat)
        )
    ]


def _breaking_point(results: list[RunResult]) -> Optional[float]:
    """The lowest f/n at which `reputation`'s mean error, averaged over
    every attack class, is no longer better than `unweighted`'s — the
    explicit "where the scheme breaks" statement WP-10 Part 4 requires.
    `None` if reputation beats unweighted at every swept f/n (still worth
    stating plainly, not just omitting).
    """
    by_f: dict[float, dict[str, list[float]]] = {}
    for r in results:
        by_f.setdefault(r.f_over_n, {}).setdefault(r.method, []).append(r.mean_position_error_m)

    for f_over_n in sorted(by_f):
        methods = by_f[f_over_n]
        if "reputation" not in methods or "unweighted" not in methods:
            continue
        rep_mean = float(np.nanmean(methods["reputation"]))
        unweighted_mean = float(np.nanmean(methods["unweighted"]))
        if rep_mean >= unweighted_mean:
            return f_over_n
    return None


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="WP-10 headline Byzantine-robustness sweep")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="list the planned run matrix, execute nothing")
    args = parser.parse_args(argv)

    runs = planned_runs(args.repeat)

    if args.dry_run:
        for f_over_n, attack, method, repeat_idx in runs:
            print(f"f/n={f_over_n:.2f}  attack={attack:<10}  method={method:<12}  repeat={repeat_idx}")
        print(f"\n{len(runs)} planned runs total "
              f"({len(F_OVER_N_GRID)} f/n points x {len(ATTACKS)} attacks x {len(METHODS)} methods x {args.repeat} repeats)")
        return

    navmesh = _open_navmesh()
    results = [
        simulate_run(f_over_n, attack, method, seed=repeat_idx, navmesh=navmesh)
        for f_over_n, attack, method, repeat_idx in runs
    ]

    breaking_point = _breaking_point(results)

    out_dir = args.out or Path("results") / f"byzantine_sweep_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "repeat": args.repeat,
                "breaking_point_f_over_n": breaking_point,
                "runs": [asdict(r) for r in results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[run_byzantine_sweep] wrote {out_dir / 'results.json'}")
    print(
        f"[run_byzantine_sweep] reputation stops beating unweighted at f/n={breaking_point}"
        if breaking_point is not None
        else "[run_byzantine_sweep] reputation beat unweighted at every swept f/n"
    )


if __name__ == "__main__":
    main()
