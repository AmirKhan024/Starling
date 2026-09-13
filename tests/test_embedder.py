"""Tests for starling_perception.embedder (D-01 fix).

torchreid and OSNet weights are not available in this environment, so
requesting backend="osnet" is expected to fall back to "pooled" — these
tests exercise that fallback path plus the "pooled" and "v1_broken"
backends directly. No network access or dataset is required.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from starling_perception.embedder import FeatureExtractor, quality


def _checkerboard(size: int = 128, square: int = 8) -> np.ndarray:
    """A sharp synthetic BGR pattern, deterministic and content-distinct
    from `_solid` below.
    """
    xx, yy = np.meshgrid(np.arange(size), np.arange(size))
    pattern = (((xx // square) + (yy // square)) % 2).astype(np.uint8) * 255
    return np.stack([pattern, pattern, pattern], axis=-1)


def _solid(size: int = 128, value: int = 60) -> np.ndarray:
    return np.full((size, size, 3), value, dtype=np.uint8)


def test_pooled_backend_produces_unit_norm_vectors_of_declared_dim():
    extractor = FeatureExtractor(backend="pooled")
    crops = [_checkerboard(), _solid()]
    embeddings = extractor.extract(crops)

    assert embeddings.shape == (2, extractor.dim)
    norms = np.linalg.norm(embeddings, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_pooled_backend_same_pattern_scores_higher_than_different_pattern():
    extractor = FeatureExtractor(backend="pooled")

    a1, a2 = _checkerboard(square=8), _checkerboard(square=8)
    b = _solid(value=200)

    emb_a1, emb_a2, emb_b = extractor.extract([a1, a2, b])

    same_sim = float(np.dot(emb_a1, emb_a2))
    diff_sim = float(np.dot(emb_a1, emb_b))

    assert same_sim > diff_sim


def test_requesting_unavailable_osnet_falls_back_to_pooled_never_v1_broken():
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        extractor = FeatureExtractor(backend="osnet")

    assert extractor.backend != "v1_broken"
    assert extractor.backend == "pooled"
    assert extractor.dim == 576


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        FeatureExtractor(backend="not_a_real_backend")


def test_v1_broken_emits_runtime_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        extractor = FeatureExtractor(backend="v1_broken", embed_dim=512)

    assert extractor.backend == "v1_broken"
    assert any(issubclass(w.category, RuntimeWarning) for w in caught)


def test_quality_scores_sharp_crop_above_blurred_copy():
    import cv2

    sharp = _checkerboard(size=128, square=4)
    blurred = cv2.GaussianBlur(sharp, (15, 15), 0)

    assert quality(sharp) > quality(blurred)


def test_quality_is_bounded_in_zero_one():
    assert 0.0 <= quality(_checkerboard()) <= 1.0
    assert quality(np.zeros((0, 0, 3), dtype=np.uint8)) == 0.0
    assert quality(None) == 0.0
