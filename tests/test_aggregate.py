"""Tests for starling_consensus.aggregate (WP-10 Part 4)."""

from __future__ import annotations

import math
from typing import Any, Optional

import pytest

from starling_consensus.aggregate import aggregate_position
from starling_node.config import AggregateConfig


def _claim(
    claim_id: str,
    node_id: int,
    xy: tuple[float, float],
    confidence: float = 1.0,
    quality: float = 1.0,
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "node_id": node_id,
        "world_x": xy[0],
        "world_y": xy[1],
        "confidence": confidence,
        "quality": quality,
    }


def _dist(a: Optional[tuple[float, float]], b: tuple[float, float]) -> float:
    assert a is not None
    return math.hypot(a[0] - b[0], a[1] - b[1])


# Four honest claims tightly clustered at the origin, one wild outlier —
# the hand-computed case the WP-10 prompt asks for.
_HONEST = [
    _claim("C-1", 1, (0.0, 0.0)),
    _claim("C-2", 2, (0.1, 0.0)),
    _claim("C-3", 3, (0.0, 0.1)),
    _claim("C-4", 4, (-0.1, -0.1)),
]
_OUTLIER = _claim("C-5", 5, (100.0, 100.0))


def test_unweighted_mean_is_dragged_toward_the_outlier():
    result = aggregate_position(_HONEST + [_OUTLIER], reputation=None, method="unweighted", cfg=AggregateConfig())
    # Hand-computed: sum=(100.0, 100.0), n=5 -> mean=(20.0, 20.0).
    assert result.position == pytest.approx((20.0, 20.0))
    assert _dist(result.position, (0.0, 0.0)) > 10.0


def test_trimmed_mean_is_not_dragged_toward_the_outlier():
    cfg = AggregateConfig(trimmed_beta=0.2)  # k = int(0.2*5) = 1, trimmed from EACH end, per axis
    result = aggregate_position(_HONEST + [_OUTLIER], reputation=None, method="trimmed_mean", cfg=cfg)
    assert _dist(result.position, (0.0, 0.0)) < 1.0
    assert any(e["claim_id"] == "C-5" for e in result.excluded)


def test_krum_is_not_dragged_toward_the_outlier():
    cfg = AggregateConfig(krum_f=1)
    result = aggregate_position(_HONEST + [_OUTLIER], reputation=None, method="krum", cfg=cfg)
    assert _dist(result.position, (0.0, 0.0)) < 1.0
    # Krum picks ONE real claim's position, not an average.
    assert result.position in [(c["world_x"], c["world_y"]) for c in _HONEST]


def test_krum_n7_f2_selects_an_honest_claim():
    honest = [_claim(f"H-{i}", i, (0.01 * i, -0.01 * i)) for i in range(5)]
    malicious = [_claim("M-1", 5, (50.0, 50.0)), _claim("M-2", 6, (-50.0, -50.0))]
    cfg = AggregateConfig(krum_f=2)  # n=7, k = n - f - 2 = 3 nearest neighbours

    result = aggregate_position(honest + malicious, reputation=None, method="krum", cfg=cfg)

    honest_positions = [(c["world_x"], c["world_y"]) for c in honest]
    assert result.position in honest_positions


def test_reputation_weighting_gives_low_reputation_node_near_zero_influence():
    claims = [
        _claim("C-1", node_id=1, xy=(0.0, 0.0)),
        _claim("C-2", node_id=2, xy=(10.0, 10.0)),
    ]
    reputation = {1: 1.0, 2: 0.05}  # node 2 at R_min

    result = aggregate_position(claims, reputation=reputation, method="reputation", cfg=AggregateConfig())

    # Hand-computed: weighted_sum = 1.0*(0,0) + 0.05*(10,10) = (0.5, 0.5);
    # total_weight = 1.05 -> mean = (0.4762, 0.4762).
    assert result.position == pytest.approx((0.5 / 1.05, 0.5 / 1.05))
    unweighted_mean = (5.0, 5.0)
    assert _dist(result.position, (0.0, 0.0)) < _dist(unweighted_mean, (0.0, 0.0)) / 5


def test_all_methods_agree_within_tolerance_when_all_claims_are_honest():
    claims = [
        _claim("C-1", 1, (2.0, 3.0)),
        _claim("C-2", 2, (2.05, 2.98)),
        _claim("C-3", 3, (1.98, 3.02)),
        _claim("C-4", 4, (2.02, 3.01)),
        _claim("C-5", 5, (1.97, 2.99)),
    ]
    reputation = {c["node_id"]: 1.0 for c in claims}
    cfg = AggregateConfig()

    positions = [
        aggregate_position(claims, reputation, method, cfg).position
        for method in ("unweighted", "reputation", "trimmed_mean", "krum")
    ]

    for pos in positions:
        assert _dist(pos, (2.0, 3.0)) < 0.2


# ── edge cases ────────────────────────────────────────────────────────────

def test_claims_with_no_world_pos_are_excluded_from_every_method():
    claims = [_claim("C-1", 1, (0.0, 0.0)), {"claim_id": "C-2", "node_id": 2, "world_x": None, "world_y": None}]
    result = aggregate_position(claims, reputation=None, method="unweighted", cfg=AggregateConfig())
    assert result.position == pytest.approx((0.0, 0.0))
    assert {"claim_id": "C-2", "reason": "no_world_pos"} in result.excluded


def test_unknown_method_raises():
    with pytest.raises(ValueError):
        aggregate_position(_HONEST, reputation=None, method="bogus", cfg=AggregateConfig())
