"""scripts/measure_sim_realism.py
-----------------------------------
How hard is the simulator's identity problem, really?

Reports, per realism profile, the distribution of appearance similarity for
observations of the SAME person versus DIFFERENT people — split by whether the
two observations came from the same camera or different ones, because
cross-camera is the case that actually matters and the case the `demo` profile
makes free.

Reference (published multi-camera re-ID, Market-1501 / DukeMTMC family):

    same person, different camera   cosine ~ 0.40 - 0.75
    different people                cosine ~ 0.20 - 0.55
    gap ~ 0.15 - 0.25, WITH substantial overlap

A profile whose cross-camera gap is far above that range is making
re-identification easier than reality; one with zero overlap is not testing
the matching logic at all.

    python scripts/measure_sim_realism.py
    python scripts/measure_sim_realism.py --profile realistic --samples 4000
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
from starling_sim.realism import PROFILES, build_camera_models, get_profile  # noqa: E402
from starling_sim.world import load_camera_zones  # noqa: E402

FLOORPLAN = REPO / "data" / "floorplan" / "warehouse_demo.geojson"


def _auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """P(a same-person pair scores above a different-person pair) — 1.0 means
    perfectly separable (the giveaway that the problem is too easy)."""
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty(len(order), dtype=float)
    ranks[order] = np.arange(1, len(order) + 1)
    r_pos = ranks[: len(pos)].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def measure(profile_name: str, samples: int, n_workers: int, embed_dim: int, seed: int) -> dict:
    profile = get_profile(profile_name)
    zones = load_camera_zones(FLOORPLAN)
    cams = build_camera_models(zones, profile, embed_dim, seed)
    cam_ids = sorted(cams)

    vectors = make_identity_vectors(n_workers, embed_dim, seed=seed, uniform_similarity=profile.uniform_similarity)
    rng = np.random.default_rng(seed + 5)

    same_cross, same_intra, diff_cross = [], [], []
    for _ in range(samples):
        a, b = rng.choice(n_workers, size=2, replace=False)
        ca, cb = rng.choice(cam_ids, size=2, replace=False)
        # distance stands in for "somewhere in this camera's zone"
        da, db = float(rng.uniform(1.0, 8.0)), float(rng.uniform(1.0, 8.0))

        ea = cams[ca].observed_embedding(vectors[a], da, 0.05)
        eb_same_cross = cams[cb].observed_embedding(vectors[a], db, 0.05)
        eb_same_intra = cams[ca].observed_embedding(vectors[a], db, 0.05)
        eb_diff_cross = cams[cb].observed_embedding(vectors[b], db, 0.05)

        same_cross.append(float(ea @ eb_same_cross))
        same_intra.append(float(ea @ eb_same_intra))
        diff_cross.append(float(ea @ eb_diff_cross))

    sc, si, dc = np.array(same_cross), np.array(same_intra), np.array(diff_cross)
    overlap = float((dc > sc.min()).mean())
    return {
        "profile": profile_name,
        "same_person_cross_camera": (sc.mean(), sc.std()),
        "same_person_same_camera": (si.mean(), si.std()),
        "different_people": (dc.mean(), dc.std()),
        "gap_cross_camera": float(sc.mean() - dc.mean()),
        "overlap_fraction": overlap,
        "separability_auc": _auc(sc, dc),
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Measure how hard the simulator's identity problem is")
    ap.add_argument("--profile", default=None, help="one profile, or all if omitted")
    ap.add_argument("--samples", type=int, default=4000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--embed-dim", type=int, default=64)
    ap.add_argument("--seed", type=int, default=1234)
    args = ap.parse_args(argv)

    names = [args.profile] if args.profile else list(PROFILES)
    print(f"{'profile':>10} | {'same (x-cam)':>14} | {'same (same cam)':>16} | {'different':>14} | "
          f"{'gap':>6} | {'overlap':>8} | {'AUC':>6}")
    print("-" * 96)
    rows = []
    for name in names:
        m = measure(name, args.samples, args.workers, args.embed_dim, args.seed)
        rows.append(m)
        sc, si, dc = m["same_person_cross_camera"], m["same_person_same_camera"], m["different_people"]
        print(f"{name:>10} | {sc[0]:>6.3f} ± {sc[1]:<5.3f} | {si[0]:>7.3f} ± {si[1]:<6.3f} | "
              f"{dc[0]:>6.3f} ± {dc[1]:<5.3f} | {m['gap_cross_camera']:>6.3f} | "
              f"{m['overlap_fraction']:>7.1%} | {m['separability_auc']:>6.3f}")
    print()
    print("reference (published multi-camera re-ID): same 0.40-0.75, different 0.20-0.55,")
    print("                                          gap 0.15-0.25, with substantial overlap")
    print()
    for m in rows:
        g = m["gap_cross_camera"]
        if m["overlap_fraction"] < 0.01:
            print(f"  {m['profile']:>10}: NO overlap — appearance matching is free, the resolver is untested")
        elif 0.10 <= g <= 0.30:
            print(f"  {m['profile']:>10}: gap {g:.3f} is inside the published range — realistic")
        elif g < 0.10:
            print(f"  {m['profile']:>10}: gap {g:.3f} is HARDER than published re-ID — a deliberately bad site")
        else:
            print(f"  {m['profile']:>10}: gap {g:.3f} is easier than the published 0.15-0.25 range")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
