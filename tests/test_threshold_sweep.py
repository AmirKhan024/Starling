"""Tests for starling_eval.threshold_sweep (D-01 threshold calibration) and
the D-06 EMA re-normalisation fix in starling_store.identity_store.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from starling_eval.threshold_sweep import pick_f1_max, sweep_thresholds
from starling_store.identity_store import IdentityStore


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def test_perfectly_separable_pairs_reach_f1_of_one():
    rng = np.random.default_rng(7)
    n = 200
    # Same-person pairs: cosine similarity ~1.0. Different-person: ~0.0.
    same_sims = np.clip(rng.normal(loc=0.95, scale=0.01, size=n), 0.0, 1.0)
    diff_sims = np.clip(rng.normal(loc=0.05, scale=0.01, size=n), 0.0, 1.0)

    sims = np.concatenate([same_sims, diff_sims])
    labels = np.concatenate([np.ones(n, dtype=bool), np.zeros(n, dtype=bool)])

    rows = sweep_thresholds(sims, labels)
    best = pick_f1_max(rows)

    assert best["f1"] == pytest.approx(1.0)


def test_fully_overlapping_pairs_never_exceed_f1_of_0_7():
    rng = np.random.default_rng(11)
    n = 500
    # Same distribution for both classes: no cosine threshold can separate them.
    same_sims = rng.uniform(0.0, 1.0, size=n)
    diff_sims = rng.uniform(0.0, 1.0, size=n)

    sims = np.concatenate([same_sims, diff_sims])
    labels = np.concatenate([np.ones(n, dtype=bool), np.zeros(n, dtype=bool)])

    rows = sweep_thresholds(sims, labels)
    best = pick_f1_max(rows)

    assert best["f1"] < 0.7


def test_stored_embedding_norm_holds_at_one_after_100_ema_updates(tmp_path: Path):
    store = IdentityStore(
        db_path=str(tmp_path / "identities.db"),
        similarity_threshold=0.0,  # always matches the same person
        ema_alpha=0.10,
    )
    rng = np.random.default_rng(3)
    dim = 512

    base = _unit(rng.normal(size=dim)).astype(np.float32)
    global_id, is_new, _ = store.match_or_create(
        embedding=base, camera_id=0, frame_idx=0, bbox=[0, 0, 10, 10], conf=0.9,
    )
    assert is_new

    for i in range(1, 101):
        noisy = _unit(base + rng.normal(scale=0.05, size=dim)).astype(np.float32)
        gid, is_new, _ = store.match_or_create(
            embedding=noisy, camera_id=0, frame_idx=i, bbox=[0, 0, 10, 10], conf=0.9,
        )
        assert gid == global_id
        assert not is_new

    person = store.get_person(global_id)
    from starling_store.identity_store import _blob_to_emb
    stored = _blob_to_emb(person["embedding"])
    assert abs(np.linalg.norm(stored) - 1.0) < 1e-5
