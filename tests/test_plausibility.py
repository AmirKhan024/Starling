"""Tests for starling_consensus.plausibility (WP-10 Part 2)."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pytest

from starling_consensus.plausibility import CorroboratedState, check
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_node.config import PlausibilityConfig


def _open_navmesh(height: int = 200, width: int = 200, cell_size: float = 0.5) -> NavMesh:
    return NavMesh(grid=np.ones((height, width), dtype=bool), origin=(0.0, 0.0), cell_size=cell_size)


def _claim(
    node_id: int = 1,
    t_media: float = 10.0,
    world_xy: Optional[tuple[float, float]] = (0.0, 0.0),
    pos_sigma: float = 0.3,
    hlc_physical_ms: Optional[int] = None,
    claim_id: str = "C-1",
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "node_id": node_id,
        "t_media": t_media,
        "world_x": world_xy[0] if world_xy is not None else None,
        "world_y": world_xy[1] if world_xy is not None else None,
        "pos_sigma": pos_sigma,
        "hlc_physical_ms": hlc_physical_ms if hlc_physical_ms is not None else int(t_media * 1000),
    }


# ── REACHABILITY (hard fail) ─────────────────────────────────────────────

def test_hard_fail_reachability_records_implied_speed():
    geometry = ReachabilityModel(_open_navmesh(), v_max_m_s=1.6)
    cfg = PlausibilityConfig()
    state = CorroboratedState(last_position=(0.0, 0.0), last_t_media=0.0)
    claim = _claim(t_media=2.0, world_xy=(50.0, 0.0))

    result = check(claim, state, geometry, cfg)

    assert result.passed is False
    assert result.score == 0.0
    assert result.failures == ["reachability"]
    assert result.details["implied_speed_m_s"] == pytest.approx(25.0)
    assert "25" in result.details["rejection_reason"]


def test_reachable_claim_does_not_hard_fail():
    geometry = ReachabilityModel(_open_navmesh(), v_max_m_s=1.6)
    cfg = PlausibilityConfig()
    state = CorroboratedState(last_position=(0.0, 0.0), last_t_media=0.0)
    claim = _claim(t_media=2.0, world_xy=(1.0, 0.0))  # 0.5 m/s, well within v_max

    result = check(claim, state, geometry, cfg)

    assert "reachability" not in result.failures
    assert result.passed is True
    assert result.score == pytest.approx(1.0)


def test_no_prior_corroborated_position_skips_reachability_gate():
    """First sighting of a person (no corroborated prior position) cannot
    be reachability-gated — mirrors starling_crdt.resolver's own
    "no candidates -> spawn new identity" precedent for the same situation.
    """
    geometry = ReachabilityModel(_open_navmesh(), v_max_m_s=1.6)
    cfg = PlausibilityConfig()
    state = CorroboratedState()  # no last_position
    claim = _claim(t_media=2.0, world_xy=(500.0, 0.0))

    result = check(claim, state, geometry, cfg)

    assert "reachability" not in result.failures
    assert result.passed is True


# ── KINEMATICS (graded) ──────────────────────────────────────────────────

def test_kinematics_graded_without_geometry():
    """Without a ReachabilityModel there is no hard reachability gate, but
    kinematics still grades the implied speed against cfg.v_max_m_s.
    """
    cfg = PlausibilityConfig()
    state = CorroboratedState(last_position=(0.0, 0.0), last_t_media=0.0)
    claim = _claim(t_media=2.0, world_xy=(50.0, 0.0))  # 25 m/s, way over v_max=1.6

    result = check(claim, state, geometry=None, cfg=cfg)

    assert "reachability" not in result.failures  # cannot hard-fail without geometry
    assert "kinematics" in result.failures
    assert result.details["kinematics_score"] < 1.0
    assert result.score < 1.0


# ── CORROBORATION (graded) ───────────────────────────────────────────────

def test_corroboration_contradicted_by_three_scores_low_but_not_hard_fail():
    cfg = PlausibilityConfig()
    state = CorroboratedState(
        corroborating_claims=[
            _claim(node_id=2, t_media=10.0, world_xy=(20.0, 20.0), claim_id="C-2"),
            _claim(node_id=3, t_media=10.0, world_xy=(21.0, 20.0), claim_id="C-3"),
            _claim(node_id=4, t_media=10.0, world_xy=(19.0, 21.0), claim_id="C-4"),
        ]
    )
    claim = _claim(node_id=1, t_media=10.0, world_xy=(0.0, 0.0), claim_id="C-1")

    result = check(claim, state, geometry=None, cfg=cfg)

    assert "reachability" not in result.failures
    assert "corroboration" in result.failures
    assert result.details["corroborators_checked"] == 3
    assert result.details["corroborators_consistent"] == 0
    assert result.details["corroboration_score"] == pytest.approx(0.0)
    assert 0.0 < result.score < 1.0  # graded down, not zeroed


def test_corroboration_consistent_claims_score_high():
    cfg = PlausibilityConfig()
    state = CorroboratedState(
        corroborating_claims=[
            _claim(node_id=2, t_media=10.0, world_xy=(0.05, 0.0), claim_id="C-2"),
            _claim(node_id=3, t_media=10.0, world_xy=(-0.05, 0.02), claim_id="C-3"),
        ]
    )
    claim = _claim(node_id=1, t_media=10.0, world_xy=(0.0, 0.0), claim_id="C-1")

    result = check(claim, state, geometry=None, cfg=cfg)

    assert "corroboration" not in result.failures
    assert result.details["corroboration_score"] == pytest.approx(1.0)


def test_no_corroborators_available_is_neutral_not_penalised():
    cfg = PlausibilityConfig()
    state = CorroboratedState()
    claim = _claim(node_id=1, t_media=10.0, world_xy=(0.0, 0.0))

    result = check(claim, state, geometry=None, cfg=cfg)

    assert "corroboration" not in result.failures
    assert result.passed is True


# ── FRESHNESS (graded / replay detection) ────────────────────────────────

def test_freshness_flags_claim_outside_replay_window():
    cfg = PlausibilityConfig(replay_window_s=10.0)
    claim = _claim(t_media=50.0, hlc_physical_ms=50_000)  # embedded event time: 50s
    state = CorroboratedState(now_physical_ms=100_000)  # arrives "now": 100s -> age 50s

    result = check(claim, state, geometry=None, cfg=cfg)

    assert "freshness" in result.failures
    assert result.details["claim_age_s"] == pytest.approx(50.0)
    assert result.details["freshness_score"] < 1.0


def test_freshness_within_window_is_not_flagged():
    cfg = PlausibilityConfig(replay_window_s=10.0)
    claim = _claim(t_media=95.0, hlc_physical_ms=95_000)
    state = CorroboratedState(now_physical_ms=100_000)  # age 5s, within window

    result = check(claim, state, geometry=None, cfg=cfg)

    assert "freshness" not in result.failures
    assert result.details["freshness_score"] == pytest.approx(1.0)


def test_freshness_check_skipped_without_now():
    cfg = PlausibilityConfig(replay_window_s=10.0)
    claim = _claim(t_media=0.0, hlc_physical_ms=0)
    state = CorroboratedState(now_physical_ms=None)

    result = check(claim, state, geometry=None, cfg=cfg)

    assert "freshness" not in result.failures
    assert "claim_age_s" not in result.details
