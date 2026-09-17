"""starling_consensus/aggregate.py
------------------------------------
Robust position aggregation (WP-10 Part 4, C2). Four interchangeable
strategies behind one interface, so they can be ablated against each other
by `scripts/run_byzantine_sweep.py`: `unweighted` is the plain-mean
baseline that is EXPECTED to lose under a Byzantine minority (Appendix B:
Yin et al.'s trimmed-mean/median and Blanchard et al.'s Krum are both
literature specifically about beating an unweighted mean under adversarial
inputs); `reputation` applies Appendix A.5's `w = R_j * confidence *
quality`; `trimmed_mean` is the COORDINATE-WISE trimmed mean (Yin et al.
2018 — trim each of x/y independently, not a single scalar ranking, since
"top and bottom beta fraction" is a 1-D operation and a 2D position has no
single well-defined greatest/least without picking an axis); `krum`
(Blanchard et al. 2017) selects the single claim minimising the sum of
squared distances to its `n - f - 2` nearest neighbours, rather than
averaging anything.

Ambiguous-choice note (CLAUDE.md): the WP-10 prompt does not say what
"which claims were excluded and why" means for `trimmed_mean`, where
trimming happens per-coordinate rather than per-claim. Resolved by
reporting a claim as excluded once per axis it was trimmed on
(`"trimmed_x"` / `"trimmed_y"`), and giving it partial `weight` (0.5 if
trimmed on only one axis, 0.0 if both, 1.0 if neither) — the simplest
reading that is still auditable per-claim, which is what the dashboard/
audit log this docstring's own sibling module comment promises actually
needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import numpy as np

from starling_node.config import AggregateConfig


@dataclass
class AggregateResult:
    position: Optional[tuple[float, float]]
    method: str
    weights: dict[str, float] = field(default_factory=dict)  # claim_id -> weight actually used
    excluded: list[dict[str, Any]] = field(default_factory=list)  # [{"claim_id", "reason"}, ...]


def _claim_pos(claim: dict[str, Any]) -> Optional[tuple[float, float]]:
    x, y = claim.get("world_x"), claim.get("world_y")
    if x is None or y is None:
        return None
    return float(x), float(y)


def _positioned(claims: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split `claims` into (positioned, excluded-for-no-world_pos)."""
    positioned, excluded = [], []
    for c in claims:
        if _claim_pos(c) is None:
            excluded.append({"claim_id": c.get("claim_id"), "reason": "no_world_pos"})
        else:
            positioned.append(c)
    return positioned, excluded


def aggregate_position(
    claims: list[dict[str, Any]],
    reputation: Optional[Mapping[int, float]],
    method: str,
    cfg: AggregateConfig,
) -> AggregateResult:
    positioned, excluded = _positioned(claims)
    if not positioned:
        return AggregateResult(position=None, method=method, weights={}, excluded=excluded)

    if method == "unweighted":
        result = _unweighted(positioned)
    elif method == "reputation":
        result = _reputation_weighted(positioned, reputation)
    elif method == "trimmed_mean":
        result = _trimmed_mean(positioned, cfg)
    elif method == "krum":
        result = _krum(positioned, cfg)
    else:
        raise ValueError(f"unknown aggregation method: {method!r}")

    result.excluded = excluded + result.excluded
    return result


# ── unweighted (baseline, EXPECTED to lose under attack) ────────────────

def _unweighted(claims: list[dict[str, Any]]) -> AggregateResult:
    positions = np.array([_claim_pos(c) for c in claims])
    mean = positions.mean(axis=0)
    n = len(claims)
    weights = {c.get("claim_id"): 1.0 / n for c in claims}
    return AggregateResult(position=(float(mean[0]), float(mean[1])), method="unweighted", weights=weights)


# ── reputation-weighted ──────────────────────────────────────────────────

def _reputation_weighted(
    claims: list[dict[str, Any]], reputation: Optional[Mapping[int, float]]
) -> AggregateResult:
    weights: dict[str, float] = {}
    weighted_sum = np.zeros(2)
    total_weight = 0.0
    for c in claims:
        r_j = 1.0 if reputation is None else reputation.get(c["node_id"], 1.0)
        # Fixed order (R_j * confidence * quality), per Appendix A.5 and
        # matching starling_crdt.resolver._score's own "fixed multiplication
        # order" convention.
        w = r_j * c.get("confidence", 1.0) * c.get("quality", 1.0)
        weights[c.get("claim_id")] = w
        weighted_sum += np.array(_claim_pos(c)) * w
        total_weight += w

    if total_weight <= 0.0:
        # Every claim weighed to (near) zero — no defensible fused position
        # to report; falling back to an unweighted mean would silently
        # hide that every contributor was distrusted, which is exactly
        # the situation an operator needs to SEE, not have smoothed over.
        return AggregateResult(position=None, method="reputation", weights=weights)

    mean = weighted_sum / total_weight
    return AggregateResult(position=(float(mean[0]), float(mean[1])), method="reputation", weights=weights)


# ── coordinate-wise trimmed mean ─────────────────────────────────────────

def _trimmed_mean(claims: list[dict[str, Any]], cfg: AggregateConfig) -> AggregateResult:
    n = len(claims)
    k = int(cfg.trimmed_beta * n)  # trimmed from EACH end, per axis

    xs = np.array([_claim_pos(c)[0] for c in claims])
    ys = np.array([_claim_pos(c)[1] for c in claims])
    order_x = np.argsort(xs)
    order_y = np.argsort(ys)

    trimmed_x_idx = set(order_x[:k].tolist()) | set(order_x[n - k :].tolist()) if k > 0 else set()
    trimmed_y_idx = set(order_y[:k].tolist()) | set(order_y[n - k :].tolist()) if k > 0 else set()

    kept_x = np.delete(xs, list(trimmed_x_idx)) if trimmed_x_idx else xs
    kept_y = np.delete(ys, list(trimmed_y_idx)) if trimmed_y_idx else ys
    mean = (float(kept_x.mean()), float(kept_y.mean()))

    weights: dict[str, float] = {}
    excluded: list[dict[str, Any]] = []
    for i, c in enumerate(claims):
        trimmed_axes = []
        if i in trimmed_x_idx:
            trimmed_axes.append("x")
        if i in trimmed_y_idx:
            trimmed_axes.append("y")
        weights[c.get("claim_id")] = 1.0 - 0.5 * len(trimmed_axes)
        for axis in trimmed_axes:
            excluded.append({"claim_id": c.get("claim_id"), "reason": f"trimmed_{axis}"})

    return AggregateResult(position=mean, method="trimmed_mean", weights=weights, excluded=excluded)


# ── Krum ──────────────────────────────────────────────────────────────────

def _krum(claims: list[dict[str, Any]], cfg: AggregateConfig) -> AggregateResult:
    n = len(claims)
    positions = np.array([_claim_pos(c) for c in claims])
    # n - f - 2 nearest neighbours (Blanchard et al. 2017); with too few
    # claims to support that many neighbours, fall back to every OTHER
    # claim rather than raising — a graceful degradation, not silence.
    k = max(1, min(n - cfg.krum_f - 2, n - 1))

    scores = np.zeros(n)
    for i in range(n):
        dists = np.sum((positions - positions[i]) ** 2, axis=1)
        dists[i] = np.inf  # never a neighbour of itself
        nearest = np.sort(dists)[:k]
        scores[i] = float(np.sum(nearest))

    winner = int(np.argmin(scores))
    weights = {c.get("claim_id"): (1.0 if i == winner else 0.0) for i, c in enumerate(claims)}
    excluded = [
        {"claim_id": c.get("claim_id"), "reason": "krum: not the minimum-score claim"}
        for i, c in enumerate(claims)
        if i != winner
    ]
    winner_pos = _claim_pos(claims[winner])
    return AggregateResult(position=winner_pos, method="krum", weights=weights, excluded=excluded)
