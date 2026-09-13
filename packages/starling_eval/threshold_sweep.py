"""starling_eval/threshold_sweep.py
------------------------------------
Replaces the guessed `sim_threshold: 0.60` (STARLING_BUILD_STATE.md D-01's
sibling issue: the threshold was never calibrated) with a number derived
from a ROC sweep over labelled same-person / different-person embedding
pairs.

Two candidate operating points are reported:
  - the F1-maximising threshold
  - the threshold at FPR = 0.01

We RECOMMEND the FPR = 0.01 threshold. In a safety system, a false identity
merge (two different people collapsed into one record) is worse than a
miss: a miss just loses a track, but a false merge produces a confident,
wrong claim about where a person was. F1 treats both error types
symmetrically, which is the wrong trade-off for this system.

CLI
---
    python -m starling_eval.threshold_sweep --data <path> --backend osnet
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Optional

import numpy as np

from starling_net.logging import get_logger

logger = get_logger(__name__)


def cosine_similarities(pairs: list[tuple[np.ndarray, np.ndarray, bool]]) -> tuple[np.ndarray, np.ndarray]:
    """Given (emb_a, emb_b, is_same_person) triples, return
    (similarities, labels) as parallel arrays.
    """
    sims = np.array([float(np.dot(a, b)) for a, b, _ in pairs], dtype=np.float64)
    labels = np.array([bool(same) for _, _, same in pairs], dtype=bool)
    return sims, labels


def sweep_thresholds(
    sims: np.ndarray, labels: np.ndarray, steps: int = 101
) -> list[dict]:
    """Sweep cosine threshold 0.00 -> 1.00 in `steps` increments (default:
    0.01 steps), computing TPR, FPR, precision, recall, F1 at each.
    """
    thresholds = np.linspace(0.0, 1.0, steps)
    rows = []
    for t in thresholds:
        pred = sims >= t
        tp = int(np.sum(pred & labels))
        fp = int(np.sum(pred & ~labels))
        fn = int(np.sum(~pred & labels))
        tn = int(np.sum(~pred & ~labels))

        tpr = tp / (tp + fn) if (tp + fn) else 0.0
        fpr = fp / (fp + tn) if (fp + tn) else 0.0
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tpr
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        rows.append({
            "threshold": float(t),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "tpr": tpr, "fpr": fpr,
            "precision": precision, "recall": recall, "f1": f1,
        })
    return rows


def pick_f1_max(rows: list[dict]) -> dict:
    return max(rows, key=lambda r: r["f1"])


def pick_at_fpr(rows: list[dict], target_fpr: float = 0.01) -> dict:
    """The most permissive (lowest) threshold whose FPR is still <= target —
    i.e. the best recall achievable without exceeding the false-positive
    budget. Falls back to the row with the lowest FPR if none meet target.
    """
    candidates = [r for r in rows if r["fpr"] <= target_fpr]
    if not candidates:
        return min(rows, key=lambda r: r["fpr"])
    return min(candidates, key=lambda r: r["threshold"])


def _write_roc_plot(rows: list[dict], out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fpr = [r["fpr"] for r in rows]
    tpr = [r["tpr"] for r in rows]
    fig, ax = plt.subplots()
    ax.plot(fpr, tpr, marker=".", markersize=2)
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray")
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title("ROC — cosine similarity threshold sweep")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def load_pairs_json(path: str) -> list[tuple[np.ndarray, np.ndarray, bool]]:
    """Load precomputed pairs from a JSON file:
    `[{"emb_a": [...], "emb_b": [...], "same": true}, ...]`.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        (np.asarray(row["emb_a"], dtype=np.float32),
         np.asarray(row["emb_b"], dtype=np.float32),
         bool(row["same"]))
        for row in data
    ]


def run_sweep(
    pairs: list[tuple[np.ndarray, np.ndarray, bool]],
    backend: str,
) -> dict:
    sims, labels = cosine_similarities(pairs)
    rows = sweep_thresholds(sims, labels)
    f1_pick = pick_f1_max(rows)
    fpr01_pick = pick_at_fpr(rows, target_fpr=0.01)

    date_str = _dt.date.today().isoformat()
    return {
        "backend": backend,
        "date": date_str,
        "rows": rows,
        "f1_max": f1_pick,
        "fpr01": fpr01_pick,
        "recommended": fpr01_pick,
        "threshold_source": f"roc_fpr01_{backend}_{date_str}",
    }


def _print_report(result: dict) -> None:
    print(f"\nThreshold sweep — backend={result['backend']}  date={result['date']}")
    print("-" * 60)
    print(f"F1-maximising threshold : {result['f1_max']['threshold']:.2f}  "
          f"(F1={result['f1_max']['f1']:.3f}, "
          f"TPR={result['f1_max']['tpr']:.3f}, FPR={result['f1_max']['fpr']:.3f})")
    print(f"Threshold at FPR=0.01   : {result['fpr01']['threshold']:.2f}  "
          f"(F1={result['fpr01']['f1']:.3f}, "
          f"TPR={result['fpr01']['tpr']:.3f}, FPR={result['fpr01']['fpr']:.3f})")
    print(
        "\nRecommendation: use the FPR=0.01 threshold. In a safety system, a "
        "false identity merge (two people collapsed into one record) is "
        "worse than a missed match, because it produces a confident, wrong "
        "claim about where a person was. F1 optimises a symmetric trade-off "
        "that is the wrong shape for this failure mode."
    )
    print("\nPaste into configs/nodes/node-NN.yaml:")
    print("match:")
    print(f"  sim_threshold: {result['fpr01']['threshold']:.2f}")
    print(f"  threshold_source: \"{result['threshold_source']}\"")


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Sweep cosine-similarity threshold over labelled embedding pairs"
    )
    parser.add_argument("--data", required=True,
                         help="Market-1501 split directory, or a JSON file of precomputed pairs")
    parser.add_argument("--backend", default="osnet")
    parser.add_argument("--pairs-per-id", type=int, default=5,
                         help="When --data is a Market-1501 dir: positive/negative pairs sampled per id")
    args = parser.parse_args(argv)

    data_path = Path(args.data)
    if data_path.suffix == ".json":
        pairs = load_pairs_json(args.data)
    else:
        pairs = _pairs_from_market1501_dir(data_path, args.backend, args.pairs_per_id)

    result = run_sweep(pairs, backend=args.backend)
    _print_report(result)

    out_dir = Path("results")
    out_dir.mkdir(parents=True, exist_ok=True)
    sweep_path = out_dir / f"threshold_roc_{args.backend}.json"
    sweep_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nWrote {sweep_path}")

    try:
        plot_path = out_dir / f"threshold_roc_{args.backend}.png"
        _write_roc_plot(result["rows"], plot_path)
        print(f"Wrote {plot_path}")
    except ImportError:
        logger.warning("matplotlib not available; skipped ROC plot")


def _pairs_from_market1501_dir(
    data_dir: Path, backend: str, pairs_per_id: int
) -> list[tuple[np.ndarray, np.ndarray, bool]]:
    """Build same-person / different-person pairs from a Market-1501 query
    split, extracting embeddings with the given backend.
    """
    import cv2

    from starling_eval.reid_benchmark import load_split
    from starling_perception.embedder import FeatureExtractor

    samples = load_split(data_dir / "query")
    extractor = FeatureExtractor(backend=backend)
    crops = [cv2.imread(str(s.path)) for s in samples]
    embeddings = extractor.extract(crops)

    by_pid: dict[int, list[int]] = {}
    for i, s in enumerate(samples):
        by_pid.setdefault(s.person_id, []).append(i)

    pairs = []
    pids = list(by_pid.keys())
    for pid, idxs in by_pid.items():
        for i in range(min(pairs_per_id, len(idxs) - 1)):
            pairs.append((embeddings[idxs[i]], embeddings[idxs[i + 1]], True))
        other_pid = pids[(pids.index(pid) + 1) % len(pids)]
        if other_pid != pid:
            other_idx = by_pid[other_pid][0]
            pairs.append((embeddings[idxs[0]], embeddings[other_idx], False))
    return pairs


if __name__ == "__main__":
    main()
