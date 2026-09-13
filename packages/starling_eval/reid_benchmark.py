"""starling_eval/reid_benchmark.py
-----------------------------------
Standard Market-1501 person re-identification evaluation: Rank-1, Rank-5,
mAP, under the standard protocol (gallery entries sharing both person id and
camera id with the query are excluded; junk ids -1 and 0 are ignored).

This module is the first place this project has ever computed a measured
number for its perception layer (fixes D-11's sibling gap — no benchmark
existed at all). It exists to quantify what defect D-01 (embedder.py) cost,
by running the same evaluation against the `v1_broken`, `pooled`, and
`osnet` backends and comparing.

Dataset acquisition and actually running this against real Market-1501 data
is explicitly NOT this session's job (see the WP-01 prompt) — this module
is exercised here only with synthetic embeddings in
tests/test_reid_benchmark.py.

CLI
---
    python -m starling_eval.reid_benchmark --data <path> --backend osnet [--max-query N]
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from starling_net.logging import get_logger

logger = get_logger(__name__)

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")
_FILENAME_RE = re.compile(r"^(-?\d+)_c(\d+)")

# Market-1501 junk ids: -1 = distractor, 0 = junk (unused in official protocol)
_JUNK_PIDS = (-1, 0)


@dataclass
class ReIDSample:
    path: Path
    person_id: int
    camera_id: int  # 0-indexed


def parse_market1501_filename(filename: str) -> tuple[int, int]:
    """Parse a Market-1501 filename like '0002_c1s1_000451_03.jpg' into
    (person_id, camera_id), with camera_id converted to 0-indexed.
    """
    match = _FILENAME_RE.match(filename)
    if not match:
        raise ValueError(f"Cannot parse Market-1501 filename: {filename!r}")
    person_id, camera_id = match.groups()
    return int(person_id), int(camera_id) - 1


def load_split(directory: Path) -> list[ReIDSample]:
    """List all images in a Market-1501 split directory (query/ or
    bounding_box_test/) as ReIDSamples.
    """
    directory = Path(directory)
    samples = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in _IMAGE_EXTS:
            continue
        person_id, camera_id = parse_market1501_filename(path.name)
        samples.append(ReIDSample(path=path, person_id=person_id, camera_id=camera_id))
    return samples


def compute_distance_matrix(query_emb: np.ndarray, gallery_emb: np.ndarray) -> np.ndarray:
    """Cosine distance matrix: distmat[i, j] = 1 - cos_sim(query_i, gallery_j).

    Embeddings are assumed L2-normalised, so this is a plain dot product.
    """
    return 1.0 - query_emb @ gallery_emb.T


def evaluate_market1501(
    distmat: np.ndarray,
    q_pids: np.ndarray,
    q_camids: np.ndarray,
    g_pids: np.ndarray,
    g_camids: np.ndarray,
    max_rank: int = 5,
) -> dict:
    """Standard Market-1501 CMC + mAP evaluation.

    For each query, gallery entries sharing BOTH person id and camera id
    with the query are excluded (they are the same physical capture, not a
    genuine cross-camera match), as are junk ids -1 and 0.
    """
    q_pids = np.asarray(q_pids)
    q_camids = np.asarray(q_camids)
    g_pids = np.asarray(g_pids)
    g_camids = np.asarray(g_camids)

    num_q, num_g = distmat.shape
    rank_cap = min(max_rank, num_g)

    order = np.argsort(distmat, axis=1)
    matches = (g_pids[order] == q_pids[:, np.newaxis]).astype(np.int32)

    all_cmc = []
    all_ap = []
    num_valid_q = 0

    for q_idx in range(num_q):
        q_pid = q_pids[q_idx]
        q_camid = q_camids[q_idx]

        idx_order = order[q_idx]
        same_capture = (g_pids[idx_order] == q_pid) & (g_camids[idx_order] == q_camid)
        junk = np.isin(g_pids[idx_order], _JUNK_PIDS)
        keep = ~(same_capture | junk)

        raw_cmc = matches[q_idx][keep]
        if not np.any(raw_cmc):
            # No valid ground-truth match remains in the gallery for this query.
            continue

        cmc = raw_cmc.cumsum()
        cmc[cmc > 1] = 1
        all_cmc.append(cmc[:rank_cap])
        num_valid_q += 1

        num_rel = raw_cmc.sum()
        tmp_cmc = raw_cmc.cumsum()
        precision_at_k = tmp_cmc / (np.arange(len(raw_cmc)) + 1.0)
        ap = (precision_at_k * raw_cmc).sum() / num_rel
        all_ap.append(ap)

    if num_valid_q == 0:
        raise ValueError("No valid query after excluding same-capture and junk gallery entries")

    cmc_curve = np.asarray(all_cmc, dtype=np.float64).sum(axis=0) / num_valid_q
    rank1 = float(cmc_curve[0])
    rank5 = float(cmc_curve[min(4, rank_cap - 1)])
    mean_ap = float(np.mean(all_ap))

    return {"rank1": rank1, "rank5": rank5, "mAP": mean_ap, "num_valid_queries": num_valid_q}


def run_benchmark(
    data_dir: str,
    backend: str = "osnet",
    weights_path: Optional[str] = None,
    device: str = "auto",
    max_query: Optional[int] = None,
) -> dict:
    """Extract embeddings for query/ and bounding_box_test/ under `data_dir`
    with the given backend, then run the standard evaluation.
    """
    from starling_perception.embedder import FeatureExtractor
    import cv2

    data_dir = Path(data_dir)
    query_samples = load_split(data_dir / "query")
    gallery_samples = load_split(data_dir / "bounding_box_test")

    if max_query is not None:
        query_samples = query_samples[:max_query]

    extractor = FeatureExtractor(backend=backend, weights_path=weights_path, device=device)

    def _extract_all(samples: list[ReIDSample]) -> np.ndarray:
        crops = [cv2.imread(str(s.path)) for s in samples]
        return extractor.extract(crops)

    query_emb = _extract_all(query_samples)
    gallery_emb = _extract_all(gallery_samples)

    distmat = compute_distance_matrix(query_emb, gallery_emb)

    metrics = evaluate_market1501(
        distmat,
        q_pids=np.array([s.person_id for s in query_samples]),
        q_camids=np.array([s.camera_id for s in query_samples]),
        g_pids=np.array([s.person_id for s in gallery_samples]),
        g_camids=np.array([s.camera_id for s in gallery_samples]),
    )
    metrics["backend"] = extractor.backend
    metrics["dim"] = extractor.dim
    metrics["num_query"] = len(query_samples)
    metrics["num_gallery"] = len(gallery_samples)
    return metrics


def _print_table(metrics: dict) -> None:
    print(f"\n{'Backend':<12} {'Rank-1':>8} {'Rank-5':>8} {'mAP':>8} {'Dim':>6}")
    print("-" * 46)
    print(
        f"{metrics['backend']:<12} {metrics['rank1']:>8.4f} {metrics['rank5']:>8.4f} "
        f"{metrics['mAP']:>8.4f} {metrics['dim']:>6}"
    )


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Market-1501 Rank-1/Rank-5/mAP benchmark for a ReID backend"
    )
    parser.add_argument("--data", required=True, help="Market-1501 root directory")
    parser.add_argument("--backend", default="osnet", help="osnet | pooled | v1_broken")
    parser.add_argument("--weights", default=None, help="Path to backend weights")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--max-query", type=int, default=None, help="Limit number of queries")
    args = parser.parse_args(argv)

    metrics = run_benchmark(
        data_dir=args.data,
        backend=args.backend,
        weights_path=args.weights,
        device=args.device,
        max_query=args.max_query,
    )
    _print_table(metrics)

    out_dir = Path("results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"reid_benchmark_{metrics['backend']}.json"
    out_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
