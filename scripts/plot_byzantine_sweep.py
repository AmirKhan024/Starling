"""scripts/plot_byzantine_sweep.py
------------------------------------
Turns `results/byzantine_sweep_c2/results.json` (produced by
`scripts/run_byzantine_sweep.py --repeat 5`) into the three figures
`docs/results_c2.md` is written around:

    docs/c2_accuracy_vs_fn.png   accuracy vs f/n, one panel per attack, one line per method
    docs/c2_rejection_rates.png  false-claim rejection AND false-rejection, together
    docs/c2_reputation_decay.png a fabricating node's final reputation vs f/n

Separated from the sweep itself so re-plotting never means re-running the
sweep (and so the sweep stays importable without matplotlib).

    python scripts/plot_byzantine_sweep.py
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
METHODS = ["unweighted", "reputation", "trimmed_mean", "krum"]
ATTACKS = ["fabricate", "suppress", "replay", "mixed"]
COLOURS = {"unweighted": "#c0392b", "reputation": "#2557d6", "trimmed_mean": "#b7791f", "krum": "#1a7f4b"}


def _clean(values: list[float]) -> list[float]:
    return [v for v in values if not (isinstance(v, float) and math.isnan(v))]


def _agg(runs: list[dict]) -> dict:
    out: dict[tuple, list[dict]] = defaultdict(list)
    for r in runs:
        out[(r["attack"], r["method"], r["f_over_n"])].append(r)
    return out


def _series(agg: dict, attack: str, method: str, key: str, fns: list[float]):
    mean, std = [], []
    for f in fns:
        vals = _clean([r[key] for r in agg.get((attack, method, f), [])])
        mean.append(st.mean(vals) if vals else float("nan"))
        std.append(st.pstdev(vals) if len(vals) > 1 else 0.0)
    return mean, std


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Plot the C2 Byzantine sweep results")
    ap.add_argument("--results", type=Path, default=REPO / "results" / "byzantine_sweep_c2" / "results.json")
    ap.add_argument("--outdir", type=Path, default=REPO / "docs")
    args = ap.parse_args(argv)

    data: dict[str, Any] = json.loads(args.results.read_text(encoding="utf-8"))
    runs = data["runs"]
    agg = _agg(runs)
    fns = sorted({r["f_over_n"] for r in runs})

    # ── 1. accuracy vs f/n, one panel per attack ────────────────────────
    fig, axes = plt.subplots(1, 4, figsize=(17, 4.2), sharey=True)
    for ax, attack in zip(axes, ATTACKS):
        for method in METHODS:
            mean, std = _series(agg, attack, method, "mean_position_error_m", fns)
            ax.errorbar(fns, mean, yerr=std, label=method, marker="o", ms=3.5, lw=1.6,
                        capsize=2, color=COLOURS[method])
        ax.set_title(attack)
        ax.set_xlabel("fraction of malicious nodes (f/n)")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("fused position error (m)\nlower is better")
    axes[0].legend(fontsize=8)
    fig.suptitle(
        f"C2: accuracy vs fraction of malicious nodes ({data['repeat']} repeats, mean ± sd)", fontweight="bold"
    )
    fig.tight_layout()
    fig.savefig(args.outdir / "c2_accuracy_vs_fn.png", dpi=130)
    plt.close(fig)

    # ── 2. rejection rates, both together ───────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for attack in ATTACKS:
        caught, _ = _series(agg, attack, "reputation", "false_claim_rejection_rate", fns)
        false_rej, _ = _series(agg, attack, "reputation", "false_rejection_rate", fns)
        axes[0].plot(fns, caught, marker="o", ms=3.5, lw=1.6, label=attack)
        axes[1].plot(fns, false_rej, marker="o", ms=3.5, lw=1.6, label=attack)
    axes[0].set_title("false-CLAIM rejection rate\n(malicious claims correctly rejected — higher is better)")
    axes[1].set_title("false-REJECTION rate\n(honest claims wrongly rejected — LOWER is better)")
    for ax in axes:
        ax.set_xlabel("fraction of malicious nodes (f/n)")
        ax.set_ylim(-0.05, 1.05)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle("C2: detection quality, method = reputation (suppress is absent by construction)", fontweight="bold")
    fig.tight_layout()
    fig.savefig(args.outdir / "c2_rejection_rates.png", dpi=130)
    plt.close(fig)

    # ── 3. reputation decay ─────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    for attack in ["fabricate", "mixed"]:
        mean, std = _series(agg, attack, "reputation", "final_malicious_reputation", fns)
        ax.errorbar(fns, mean, yerr=std, marker="o", ms=4, lw=1.7, capsize=2, label=attack)
    ax.axhline(1.0, color="#1a7f4b", ls="--", lw=1, label="an honest node (1.0)")
    ax.set_xlabel("fraction of malicious nodes (f/n)")
    ax.set_ylabel("malicious node's final reputation")
    ax.set_title("C2: a lying node's reputation, as its peers score it", fontweight="bold")
    ax.set_ylim(-0.05, 1.1)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(args.outdir / "c2_reputation_decay.png", dpi=130)
    plt.close(fig)

    print(f"wrote 3 figures to {args.outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
