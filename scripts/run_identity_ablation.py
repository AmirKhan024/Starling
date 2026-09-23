"""scripts/run_identity_ablation.py
-------------------------------------
How well does identity survive, as the simulated cameras get more realistic and
as the match threshold moves?

Runs the REAL simulator and the REAL resolver offline (no sockets, no node
processes), so a full sweep takes seconds instead of minutes and is
repeatable. For each (realism profile × sim_threshold) it reports, against the
simulator's ground truth:

  fragmentation   distinct resolved identities per true worker (1.0 = perfect;
                  2.0 means each person was, on average, split in two)
  purity          fraction of claims whose identity is that person's dominant
                  identity — i.e. how much of a worker's evidence stayed together
  mixing          fraction of resolved identities that contain claims from more
                  than one true worker (an identity MERGE — two people confused)

Fragmentation and mixing trade off against each other: a loose threshold merges
people, a strict one splits them. The useful operating point minimises both.

    python scripts/run_identity_ablation.py
    python scripts/run_identity_ablation.py --seconds 120 --plot
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

import numpy as np

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from starling_crdt.claims import claim_order_key  # noqa: E402
from starling_crdt.resolver import resolve  # noqa: E402
from starling_geometry.navmesh import NavMesh  # noqa: E402
from starling_geometry.reachability import ReachabilityModel  # noqa: E402
from starling_node.config import MatchConfig  # noqa: E402
from starling_sim.config import load_simulator_config  # noqa: E402
from starling_sim.runner import SimulatorRunner  # noqa: E402

SIM_CONFIG = REPO / "configs" / "sim" / "warehouse.yaml"
FLOORPLAN = REPO / "data" / "floorplan" / "warehouse_demo.geojson"


class _Windowed:
    """Duck-types the one method `resolve()` needs from a ClaimSet."""

    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def ordered(self) -> list[dict]:
        return self._records


def collect(profile: str, seconds: float, script: Optional[str], seed: int) -> list[dict]:
    """Run the simulator headless and return claim records tagged with the TRUE
    worker id (kept only for scoring — the resolver never sees it)."""
    cfg = load_simulator_config(SIM_CONFIG)
    cfg.auto = False
    cfg.control_port = 0
    cfg.realism = profile
    cfg.seed = seed
    runner = SimulatorRunner(cfg)
    if script:
        runner.command({"kind": "script", "name": script})

    # Call observe_zone directly rather than reading tick_once's wire payloads:
    # the wire form deliberately drops `true_worker_id`, and scoring needs it.
    # Nothing here is visible to a node; this is an in-process scorer.
    from starling_sim.perception import observe_zone

    records: list[dict] = []
    seq: Counter = Counter()
    for _ in range(int(seconds * cfg.tick_hz)):
        runner.tick_once()  # advances the world (and any running script)
        for node_id in sorted(runner.world.zones):
            observed = observe_zone(
                runner.world,
                node_id,
                runner.perception_cfg,
                runner._rng,
                camera=runner.cameras.get(node_id),
                tick=runner.tick_count,
                zone_reach_m=runner._zone_reach.get(node_id, 0.0),
            )
            for obs, world_pos, pos_sigma in observed:
                if obs.true_worker_id is None:
                    continue  # a false positive has no true worker to score against
                seq[node_id] += 1
                records.append(
                    {
                        "claim_id": f"{node_id}-{seq[node_id]}",
                        "node_id": node_id,
                        "seq": seq[node_id],
                        "hlc_physical_ms": int(obs.t_media * 1000),
                        "hlc_logical": 0,
                        "local_track_id": obs.local_track_id,
                        "t_media": obs.t_media,
                        "embedding": np.asarray(obs.embedding, dtype=np.float32).tobytes(),
                        "embed_scale": 1.0,
                        "world_x": world_pos[0],
                        "world_y": world_pos[1],
                        "pos_sigma": pos_sigma,
                        "anchor_type": "FACE_ANCHOR" if obs.anchor_identity else "UNANCHORED",
                        "identity_ref": obs.anchor_identity,
                        "last_anchor_t": None,
                        "confidence": obs.conf,
                        "quality": obs.quality,
                        "signature": None,
                        # scoring only — the resolver is never shown this key
                        "_true_worker": obs.true_worker_id,
                    }
                )
    return records


def score(records: list[dict], threshold: float, geo: ReachabilityModel, slack: float) -> dict[str, Any]:
    cfg = MatchConfig(sim_threshold=threshold, gate_extra_slack_m=slack)
    ordered = sorted(records, key=claim_order_key)
    assignment, forks = resolve(_Windowed(ordered), geo, None, None, cfg)

    by_id = {r["claim_id"]: r for r in ordered}
    ids_per_worker: dict[int, set] = defaultdict(set)
    claims_per_worker_identity: dict[int, Counter] = defaultdict(Counter)
    workers_per_identity: dict[str, set] = defaultdict(set)
    assigned = 0

    for ref, cids in assignment.trajectories.items():
        for cid in cids:
            rec = by_id.get(cid)
            if rec is None:
                continue
            w = rec["_true_worker"]
            ids_per_worker[w].add(ref)
            claims_per_worker_identity[w][ref] += 1
            workers_per_identity[ref].add(w)
            assigned += 1

    workers = [w for w in ids_per_worker if ids_per_worker[w]]
    frag = float(np.mean([len(ids_per_worker[w]) for w in workers])) if workers else float("nan")
    purity = (
        float(np.mean([max(claims_per_worker_identity[w].values()) / sum(claims_per_worker_identity[w].values())
                       for w in workers]))
        if workers
        else float("nan")
    )
    mixed = [ref for ref, ws in workers_per_identity.items() if len(ws) > 1]
    mixing = len(mixed) / len(workers_per_identity) if workers_per_identity else float("nan")
    return {
        "threshold": threshold,
        "workers": len(workers),
        "identities": len(assignment.trajectories),
        "fragmentation": frag,
        "purity": purity,
        "mixing": mixing,
        "assigned_claims": assigned,
        "total_claims": len(ordered),
        "open_forks": len(forks.open_forks()),
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Identity quality vs realism profile and match threshold")
    ap.add_argument("--profiles", default="demo,realistic,harsh")
    ap.add_argument("--thresholds", default="0.20,0.25,0.30,0.32,0.35,0.40,0.50,0.60")
    ap.add_argument("--seconds", type=float, default=90.0, help="simulated seconds per profile")
    ap.add_argument("--script", default="dead_zone_healthy", help="scenario script to run (cross-zone movement)")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--slack", type=float, default=0.5, help="MatchConfig.gate_extra_slack_m")
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args(argv)

    navmesh = NavMesh.from_geojson(FLOORPLAN, cell_size_m=0.25)
    geo = ReachabilityModel(navmesh)
    profiles = [p.strip() for p in args.profiles.split(",")]
    thresholds = [float(t) for t in args.thresholds.split(",")]

    all_rows: dict[str, list[dict]] = {}
    for profile in profiles:
        records = collect(profile, args.seconds, args.script, args.seed)
        rows = [score(records, t, geo, args.slack) for t in thresholds]
        all_rows[profile] = rows
        print(f"\n=== realism = {profile}  ({len(records)} claims over {args.seconds:.0f} simulated s) ===")
        print(f"{'thresh':>7} | {'identities':>10} | {'frag/worker':>11} | {'purity':>7} | {'mixing':>7} | {'assigned':>9}")
        print("-" * 70)
        for r in rows:
            pct = r["assigned_claims"] / r["total_claims"] if r["total_claims"] else 0
            print(f"{r['threshold']:>7.2f} | {r['identities']:>10} | {r['fragmentation']:>11.2f} | "
                  f"{r['purity']:>7.3f} | {r['mixing']:>7.3f} | {pct:>8.1%}")
        best = min(rows, key=lambda r: (r["fragmentation"] - 1.0) + 3.0 * r["mixing"])
        print(f"  best operating point: threshold {best['threshold']:.2f} "
              f"(fragmentation {best['fragmentation']:.2f}, mixing {best['mixing']:.3f})")

    if args.plot:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
        for profile, rows in all_rows.items():
            ts = [r["threshold"] for r in rows]
            axes[0].plot(ts, [r["fragmentation"] for r in rows], marker="o", ms=4, label=profile)
            axes[1].plot(ts, [r["purity"] for r in rows], marker="o", ms=4, label=profile)
            axes[2].plot(ts, [r["mixing"] for r in rows], marker="o", ms=4, label=profile)
        axes[0].axhline(1.0, ls="--", color="grey", lw=1)
        axes[0].set_title("identity fragmentation\n(1.0 = each person kept one identity)")
        axes[1].set_title("purity\n(claims kept with the dominant identity)")
        axes[2].set_title("mixing\n(identities containing two real people)")
        for ax in axes:
            ax.set_xlabel("sim_threshold")
            ax.grid(alpha=0.3)
            ax.legend(fontsize=8)
        fig.suptitle("Identity quality vs match threshold, per realism profile", fontweight="bold")
        fig.tight_layout()
        out = REPO / "docs" / "identity_ablation.png"
        fig.savefig(out, dpi=130)
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
