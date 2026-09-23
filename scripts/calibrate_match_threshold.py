"""scripts/calibrate_match_threshold.py
----------------------------------------
Pick `MatchConfig.sim_threshold` from a measured ROC curve instead of guessing
it — the deliverable WP-01 asks for, and the reason
`MatchConfig.threshold_source` has read `"UNCALIBRATED-GUESS"` until now.

Why this matters, concretely. The resolver admits a match when

    proto_score x topo x reputation x quality  >=  sim_threshold

With the simulator's `demo` profile, two observations of the same person score
~0.86 and two different people ~-0.07, so the shipped 0.60 threshold works by a
wide margin — and would work anywhere in [0.0, 0.85]. Under the `realistic`
profile (calibrated to published multi-camera re-ID separability) the same
person scores ~0.47 across cameras, so once quality is folded in the best
achievable score is ~0.40 and **no cross-camera match can ever clear 0.60**.
The identity silently breaks at every zone boundary. The threshold, not the
matching logic, is the bug.

This script samples same-person and different-person pairs from a realism
profile, sweeps the threshold, and reports the operating point that maximises
Youden's J (TPR - FPR), alongside the F1-optimal point and what the shipped
value would do.

    python scripts/calibrate_match_threshold.py
    python scripts/calibrate_match_threshold.py --profile harsh --plot
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import numpy as np

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from starling_sim.identity import make_identity_vectors  # noqa: E402
from starling_sim.realism import build_camera_models, get_profile  # noqa: E402
from starling_sim.world import load_camera_zones  # noqa: E402

FLOORPLAN = REPO / "data" / "floorplan" / "warehouse_demo.geojson"
SHIPPED_THRESHOLD = 0.60


def sample_scores(
    profile_name: str, samples: int, n_workers: int, embed_dim: int, seed: int,
    quality_lo: float = 0.75, quality_hi: float = 0.95,
) -> tuple[np.ndarray, np.ndarray]:
    """Resolver-scale scores (cosine x quality) for same-person and
    different-person CROSS-CAMERA pairs — the case that decides whether an
    identity survives a zone boundary."""
    profile = get_profile(profile_name)
    zones = load_camera_zones(FLOORPLAN)
    cams = build_camera_models(zones, profile, embed_dim, seed)
    cam_ids = sorted(cams)
    vecs = make_identity_vectors(n_workers, embed_dim, seed=seed, uniform_similarity=profile.uniform_similarity)
    rng = np.random.default_rng(seed + 11)

    same, diff = [], []
    for _ in range(samples):
        a, b = rng.choice(n_workers, size=2, replace=False)
        ca, cb = rng.choice(cam_ids, size=2, replace=False)
        da, db = float(rng.uniform(1.0, 8.0)), float(rng.uniform(1.0, 8.0))
        q = float(rng.uniform(quality_lo, quality_hi))

        ea = cams[ca].observed_embedding(vecs[a], da, 0.05)
        same.append(float(ea @ cams[cb].observed_embedding(vecs[a], db, 0.05)) * q)
        diff.append(float(ea @ cams[cb].observed_embedding(vecs[b], db, 0.05)) * q)
    return np.array(same), np.array(diff)


def roc(same: np.ndarray, diff: np.ndarray, steps: int = 400):
    lo = float(min(same.min(), diff.min()))
    hi = float(max(same.max(), diff.max()))
    ths = np.linspace(lo, hi, steps)
    tpr = np.array([(same >= t).mean() for t in ths])
    fpr = np.array([(diff >= t).mean() for t in ths])
    return ths, tpr, fpr


def _f1(same: np.ndarray, diff: np.ndarray, t: float) -> float:
    tp = float((same >= t).sum())
    fp = float((diff >= t).sum())
    fn = float((same < t).sum())
    if tp == 0:
        return 0.0
    prec, rec = tp / (tp + fp), tp / (tp + fn)
    return 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Calibrate MatchConfig.sim_threshold from a measured ROC curve")
    ap.add_argument("--profile", default="realistic", help="realism profile to calibrate against")
    ap.add_argument("--samples", type=int, default=6000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--embed-dim", type=int, default=64)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--plot", action="store_true", help="also write docs/perception_roc.png")
    args = ap.parse_args(argv)

    same, diff = sample_scores(args.profile, args.samples, args.workers, args.embed_dim, args.seed)
    ths, tpr, fpr = roc(same, diff)

    j = tpr - fpr
    t_j = float(ths[int(np.argmax(j))])
    f1s = np.array([_f1(same, diff, t) for t in ths])
    t_f1 = float(ths[int(np.argmax(f1s))])
    auc = float(np.trapezoid(tpr[::-1], fpr[::-1]))

    def at(t: float) -> str:
        return (f"TPR {(same >= t).mean():.3f}  FPR {(diff >= t).mean():.3f}  F1 {_f1(same, diff, t):.3f}")

    print(f"profile              : {args.profile}   ({args.samples} cross-camera pairs)")
    print(f"same-person score    : {same.mean():.3f} ± {same.std():.3f}")
    print(f"different-people     : {diff.mean():.3f} ± {diff.std():.3f}")
    print(f"ROC AUC              : {auc:.4f}")
    print()
    print(f"shipped   {SHIPPED_THRESHOLD:.2f}       : {at(SHIPPED_THRESHOLD)}")
    print(f"Youden J  {t_j:.2f}       : {at(t_j)}   <-- recommended")
    print(f"F1-optimal {t_f1:.2f}      : {at(t_f1)}")
    print()
    if (same >= SHIPPED_THRESHOLD).mean() < 0.5:
        print(f"WARNING: at the shipped {SHIPPED_THRESHOLD:.2f}, only "
              f"{(same >= SHIPPED_THRESHOLD).mean():.1%} of genuine same-person pairs would match —")
        print("         identities will break at zone boundaries under this profile.")

    if args.plot:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
        axes[0].hist(diff, bins=60, alpha=0.65, label="different people", color="#c0392b")
        axes[0].hist(same, bins=60, alpha=0.65, label="same person (cross-camera)", color="#2557d6")
        axes[0].axvline(SHIPPED_THRESHOLD, color="k", ls="--", lw=1.4, label=f"shipped {SHIPPED_THRESHOLD:.2f}")
        axes[0].axvline(t_j, color="#1a7f4b", lw=1.8, label=f"calibrated {t_j:.2f}")
        axes[0].set_xlabel("resolver score (cosine × quality)")
        axes[0].set_ylabel("pairs")
        axes[0].set_title(f"score distributions — {args.profile}")
        axes[0].legend(fontsize=8)
        axes[1].plot(fpr, tpr, lw=1.8, color="#2557d6")
        axes[1].scatter([(diff >= t_j).mean()], [(same >= t_j).mean()], color="#1a7f4b", zorder=5,
                        label=f"calibrated {t_j:.2f}")
        axes[1].scatter([(diff >= SHIPPED_THRESHOLD).mean()], [(same >= SHIPPED_THRESHOLD).mean()],
                        color="k", marker="x", zorder=5, label=f"shipped {SHIPPED_THRESHOLD:.2f}")
        axes[1].plot([0, 1], [0, 1], ls=":", color="grey", lw=1)
        axes[1].set_xlabel("false positive rate")
        axes[1].set_ylabel("true positive rate")
        axes[1].set_title(f"ROC (AUC {auc:.3f})")
        axes[1].legend(fontsize=8)
        fig.suptitle("Identity match threshold calibration", fontweight="bold")
        fig.tight_layout()
        out = REPO / "docs" / f"perception_roc_{args.profile}.png"
        fig.savefig(out, dpi=130)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
