"""Tests for starling_sim.identity."""

from __future__ import annotations

import numpy as np
import pytest

from starling_sim.identity import make_identity_vectors, noisy_embedding


def test_identity_vectors_are_unit_norm_and_distinct_by_default():
    vectors = make_identity_vectors(5, dim=32, seed=1)
    norms = np.linalg.norm(vectors, axis=1)
    assert norms == pytest.approx(1.0, abs=1e-5)

    # Distinct workers should not be near-duplicates of each other.
    for i in range(5):
        for j in range(i + 1, 5):
            cos_sim = float(vectors[i] @ vectors[j])
            assert cos_sim < 0.9


def test_uniform_similarity_one_collapses_workers_onto_one_vector():
    vectors = make_identity_vectors(5, dim=32, seed=1, uniform_similarity=1.0)
    for i in range(1, 5):
        cos_sim = float(vectors[0] @ vectors[i])
        assert cos_sim == pytest.approx(1.0, abs=1e-5)


def test_uniform_similarity_increases_average_pairwise_cosine_similarity():
    rng_seed = 7
    distinct = make_identity_vectors(6, dim=64, seed=rng_seed, uniform_similarity=0.0)
    similar = make_identity_vectors(6, dim=64, seed=rng_seed, uniform_similarity=0.8)

    def _mean_pairwise_cos(vectors: np.ndarray) -> float:
        sims = [
            float(vectors[i] @ vectors[j])
            for i in range(len(vectors))
            for j in range(i + 1, len(vectors))
        ]
        return sum(sims) / len(sims)

    assert _mean_pairwise_cos(similar) > _mean_pairwise_cos(distinct)


def test_noisy_embedding_is_unit_norm_and_close_to_but_not_equal_to_source():
    rng = np.random.default_rng(3)
    vector = make_identity_vectors(1, dim=32, seed=1)[0]

    observed = noisy_embedding(vector, noise_sigma=0.05, rng=rng)

    assert np.linalg.norm(observed) == pytest.approx(1.0, abs=1e-5)
    assert not np.allclose(observed, vector)
    assert float(observed @ vector) > 0.8  # still recognisably the same identity
