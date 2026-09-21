"""starling_sim/identity.py
----------------------------
Per-worker identity embeddings. A real node's `FeatureExtractor` produces a
unit-norm appearance embedding per detection; the simulator stands in for
that by giving each worker a fixed random unit vector at world-creation
time and re-noising it on every observation, exactly the way a real
detector's embedding jitters frame to frame for the same person.
"""

from __future__ import annotations

import numpy as np


def make_identity_vectors(
    n_workers: int, dim: int, seed: int, uniform_similarity: float = 0.0
) -> np.ndarray:
    """`n_workers` fixed unit vectors, one per worker, generated once for
    the lifetime of a simulator run.

    `uniform_similarity` in [0, 1] is the "uniform similarity" knob from
    the task brief: 0 means the workers' appearances are as distinct as
    random unit vectors get; 1 collapses every worker onto the same
    shared random vector (maximally similar-looking, as workers wearing
    the same uniform would be to a real re-ID embedding). Values in
    between blend each worker's own vector toward the shared one before
    renormalising.
    """
    rng = np.random.default_rng(seed)
    vectors = rng.normal(size=(n_workers, dim))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    if uniform_similarity > 0:
        shared = rng.normal(size=dim)
        shared /= np.linalg.norm(shared)
        vectors = (1.0 - uniform_similarity) * vectors + uniform_similarity * shared
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    return vectors.astype(np.float32)


def noisy_embedding(vector: np.ndarray, noise_sigma: float, rng: np.random.Generator) -> np.ndarray:
    """One noisy, renormalised observation of a worker's identity vector —
    what a real embedder would produce for one more frame of the same
    person: close to `vector`, never identical to it or to any other
    observation of it.
    """
    noisy = vector + rng.normal(scale=noise_sigma, size=vector.shape)
    norm = np.linalg.norm(noisy)
    if norm > 0:
        noisy = noisy / norm
    return noisy.astype(np.float32)
