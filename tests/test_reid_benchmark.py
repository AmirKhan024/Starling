"""Tests for starling_eval.reid_benchmark using synthetic embeddings —
no dataset or image files are needed. Real Market-1501 evaluation is the
user's job (see WP-01 prompt); this proves the evaluation math is correct.
"""

from __future__ import annotations

import numpy as np

from starling_eval.reid_benchmark import (
    compute_distance_matrix,
    evaluate_market1501,
    parse_market1501_filename,
)


def _onehot(index: int, dim: int) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[index] = 1.0
    return v


def test_parse_market1501_filename():
    assert parse_market1501_filename("0002_c1s1_000451_03.jpg") == (2, 0)
    assert parse_market1501_filename("-1_c6s3_001234_00.jpg") == (-1, 5)


def test_perfectly_separable_set_gives_rank1_and_map_of_one():
    dim = 6
    num_ids = 6

    gallery_emb = np.array([_onehot(i, dim) for i in range(num_ids)])
    g_pids = np.arange(1, num_ids + 1)  # avoid 0/-1: Market-1501 junk ids
    g_camids = np.ones(num_ids, dtype=int)  # all gallery shots from camera 1

    query_emb = gallery_emb.copy()
    q_pids = g_pids.copy()
    q_camids = np.zeros(num_ids, dtype=int)  # all queries from camera 0

    distmat = compute_distance_matrix(query_emb, gallery_emb)
    metrics = evaluate_market1501(distmat, q_pids, q_camids, g_pids, g_camids, max_rank=5)

    assert metrics["rank1"] == 1.0
    assert metrics["rank5"] == 1.0
    assert metrics["mAP"] == 1.0
    assert metrics["num_valid_queries"] == num_ids


def test_same_camera_same_person_gallery_entries_are_excluded():
    dim = 4
    gallery_emb = np.array([_onehot(0, dim), _onehot(1, dim)])
    g_pids = np.array([1, 2])
    g_camids = np.array([0, 1])

    # Query A: pid=1, camera=0 — its only gallery match shares (pid, camid)
    # with it, so the standard protocol must exclude it, leaving no valid
    # match: this query is skipped entirely (not counted).
    # Query B: pid=2, camera=0 — its gallery match is a different camera,
    # so it is a genuine, countable match.
    query_emb = np.array([_onehot(0, dim), _onehot(1, dim)])
    q_pids = np.array([1, 2])
    q_camids = np.array([0, 0])

    distmat = compute_distance_matrix(query_emb, gallery_emb)
    metrics = evaluate_market1501(distmat, q_pids, q_camids, g_pids, g_camids, max_rank=2)

    assert metrics["num_valid_queries"] == 1
    assert metrics["rank1"] == 1.0
    assert metrics["mAP"] == 1.0


def test_random_embeddings_give_low_map():
    rng = np.random.default_rng(42)
    dim = 32
    num_query, num_gallery, num_ids = 30, 60, 10

    def _random_unit(n):
        v = rng.normal(size=(n, dim)).astype(np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    query_emb = _random_unit(num_query)
    gallery_emb = _random_unit(num_gallery)

    q_pids = rng.integers(0, num_ids, size=num_query)
    q_camids = rng.integers(0, 3, size=num_query)
    g_pids = rng.integers(0, num_ids, size=num_gallery)
    g_camids = rng.integers(1, 4, size=num_gallery)  # disjoint-ish from query cams

    distmat = compute_distance_matrix(query_emb, gallery_emb)
    metrics = evaluate_market1501(distmat, q_pids, q_camids, g_pids, g_camids, max_rank=5)

    assert metrics["mAP"] < 0.5
