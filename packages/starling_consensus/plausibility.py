"""starling_consensus/plausibility.py
--------------------------------------
Plausibility checking for a received `IdentityClaim` (WP-10 Part 2, C2 —
docs/threat_model.md §2/§4). This is the mechanism behind two of the three
detection columns in that table: REACHABILITY/KINEMATICS catch FABRICATE,
FRESHNESS catches REPLAY. (SUPPRESS is caught elsewhere, by
`starling_attest.negative_evidence.detect_omission` — plausibility checking
has nothing to say about a claim that was never sent.)

Four checks, exactly as STARLING_BUILD_STATE.md WP-10 Part 2 / Appendix A.5
specify: REACHABILITY is a hard fail (unreachable → `passed=False`,
`score=0.0`, checked no further); KINEMATICS, CORROBORATION and FRESHNESS
are graded and blended into `score`, which is itself what `passed` gates on
once reachability has cleared (`score >= cfg.pass_score_threshold`) — this
is deliberately how a claim that clears the hard gate but is badly
corroborated or stale still ends up `passed=False` without needing a
second hard-fail branch.

Ambiguous-choice note (CLAUDE.md: take the first-named option, comment,
continue) — `check()`'s signature is fixed by the WP-10 prompt as
`check(claim, corroborated_state, geometry, cfg)`, but nothing in the
prompt specifies what `corroborated_state` actually carries. `CorroboratedState`
below is a plain dataclass holding exactly what the four checks need: the
last CORROBORATED (not merely claimed) position/time to gate and grade
against, the list of other nodes' claims to corroborate against, and the
admitting node's own "now" (so FRESHNESS has something to compare the
claim's embedded HLC to — mirroring `starling_attest.admission.admissible`'s
own `now_physical_ms` keyword-argument precedent for exactly this need).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from starling_geometry.reachability import ReachabilityModel
from starling_node.config import PlausibilityConfig


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _claim_pos(claim: dict[str, Any]) -> Optional[tuple[float, float]]:
    x, y = claim.get("world_x"), claim.get("world_y")
    if x is None or y is None:
        return None
    return float(x), float(y)


def _euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


@dataclass
class PlausibilityResult:
    passed: bool
    score: float  # [0, 1]
    failures: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CorroboratedState:
    """What `check()` needs beyond the claim itself — see module docstring's
    ambiguous-choice note for why this shape.
    """

    last_position: Optional[tuple[float, float]] = None
    last_t_media: Optional[float] = None
    # Other nodes' claim records (the same dict shape as `claim` — see
    # starling_crdt.claims / tests/test_resolver.py's `_claim` helper) for
    # the same identity/window, used by CORROBORATION. This node's own
    # claims must not be included — `check()` filters by node_id defensively
    # anyway, but a caller should not rely on that.
    corroborating_claims: list[dict[str, Any]] = field(default_factory=list)
    # The admitting node's current physical-time reading (milliseconds),
    # for FRESHNESS. `None` skips the freshness check entirely (mirrors
    # starling_attest.admission.admissible's now_physical_ms=None precedent).
    now_physical_ms: Optional[int] = None


def check(
    claim: dict[str, Any],
    corroborated_state: CorroboratedState,
    geometry: Optional[ReachabilityModel],
    cfg: PlausibilityConfig,
) -> PlausibilityResult:
    """Score one claim against the corroborated recent state. See the
    module docstring for the hard-fail-then-graded structure.
    """
    failures: list[str] = []
    details: dict[str, Any] = {"claim_id": claim.get("claim_id"), "node_id": claim.get("node_id")}

    claim_pos = _claim_pos(claim)
    origin = corroborated_state.last_position
    dt_s: Optional[float] = None
    if origin is not None:
        dt_s = max(0.0, claim["t_media"] - (corroborated_state.last_t_media or 0.0))

    speed_known = False
    if origin is not None and claim_pos is not None and dt_s is not None:
        if geometry is not None:
            ti, tj = geometry.navmesh.world_to_cell(*claim_pos)
            height, width = geometry.navmesh.grid.shape
            distance_m = (
                float(geometry.distance_field(origin)[tj, ti])
                if (0 <= ti < width and 0 <= tj < height)
                else float("inf")
            )
        else:
            distance_m = _euclidean(origin, claim_pos)

        implied_speed = distance_m / max(dt_s, 1e-6)
        details.update(distance_m=distance_m, dt_s=dt_s, implied_speed_m_s=implied_speed)
        speed_known = True

        # REACHABILITY — hard fail. Only checkable with geometry: without
        # it there is no reachable_set to test against, so kinematics
        # grading below is the only check that still applies.
        if geometry is not None:
            pos_sigma = claim.get("pos_sigma") or 0.0
            if not geometry.is_reachable(origin, claim_pos, dt_s, pos_sigma):
                failures.append("reachability")
                details["rejection_reason"] = (
                    f"implied speed {implied_speed:.2f} m/s over {dt_s:.2f}s exceeds what is "
                    f"reachable from the last corroborated position (v_max={geometry.v_max_m_s} m/s)"
                )
                return PlausibilityResult(passed=False, score=0.0, failures=failures, details=details)
    else:
        details["reachability_skipped"] = (
            "no geometry-independent prior corroborated position, or claim has no world_pos"
        )

    # KINEMATICS — graded. cfg.v_max_m_s (not geometry's, which may be None)
    # so this still grades even without a ReachabilityModel.
    if speed_known:
        v = details["implied_speed_m_s"]
        kinematics_score = _clip(cfg.v_max_m_s / max(v, cfg.v_max_m_s), 0.0, 1.0)
        if v > cfg.v_max_m_s:
            failures.append("kinematics")
    else:
        kinematics_score = 1.0  # nothing to compare against; neither reward nor penalise

    # CORROBORATION — graded by the fraction of positioned corroborators
    # whose reported position agrees within tolerance.
    corroboration_score = 1.0
    corroborators = [
        c for c in corroborated_state.corroborating_claims if c.get("node_id") != claim.get("node_id")
    ]
    if claim_pos is not None and corroborators:
        tolerance = cfg.pos_sigma_m + (claim.get("pos_sigma") or 0.0)
        checked = 0
        consistent = 0
        for other in corroborators:
            other_pos = _claim_pos(other)
            if other_pos is None:
                continue
            checked += 1
            if _euclidean(other_pos, claim_pos) <= tolerance:
                consistent += 1
        if checked:
            corroboration_score = consistent / checked
            details["corroborators_checked"] = checked
            details["corroborators_consistent"] = consistent
            if corroboration_score < cfg.corroboration_pass_threshold:
                failures.append("corroboration")

    # FRESHNESS — graded; a replay candidate when the claim's own HLC is
    # older than cfg.replay_window_s relative to the admitting node's "now".
    freshness_score = 1.0
    if corroborated_state.now_physical_ms is not None:
        age_s = (corroborated_state.now_physical_ms - claim["hlc_physical_ms"]) / 1000.0
        details["claim_age_s"] = age_s
        if age_s > cfg.replay_window_s:
            failures.append("freshness")
            freshness_score = _clip(cfg.replay_window_s / max(age_s, 1e-6), 0.0, 1.0)

    score = (
        cfg.kinematics_weight * kinematics_score
        + cfg.corroboration_weight * corroboration_score
        + cfg.freshness_weight * freshness_score
    )
    details.update(
        kinematics_score=kinematics_score,
        corroboration_score=corroboration_score,
        freshness_score=freshness_score,
    )
    return PlausibilityResult(passed=score >= cfg.pass_score_threshold, score=score, failures=failures, details=details)
