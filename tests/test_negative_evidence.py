"""Tests for starling_attest.negative_evidence (WP-09 Part 3)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from starling_attest.negative_evidence import CandidateBelief, detect_omission
from starling_eval.metrics import false_exclusion_rate
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_node.config import NegativeEvidenceConfig


@dataclass
class _Att:
    node_id: int
    crossing_observed: bool
    attest_confidence: float
    region_ids: list


@dataclass
class _Claim:
    node_id: int


def _open_navmesh(height=20, width=40, cell_size=0.2) -> NavMesh:
    grid = np.ones((height, width), dtype=bool)
    return NavMesh(grid=grid, origin=(0.0, 0.0), cell_size=cell_size)


def _boundary_navmesh(height=20, width=40, cell_size=0.2, boundary_col=20) -> NavMesh:
    grid = np.ones((height, width), dtype=bool)
    boundary_cells = [(boundary_col, j) for j in range(height)]
    return NavMesh(grid=grid, origin=(0.0, 0.0), cell_size=cell_size, boundaries={1: boundary_cells})


def _belief(navmesh: NavMesh, **cfg_overrides) -> CandidateBelief:
    cfg = NegativeEvidenceConfig(**cfg_overrides)
    reachability = ReachabilityModel(navmesh, v_max_m_s=cfg.v_max_m_s)
    return CandidateBelief(navmesh, reachability, cfg)


# ── dilation ───────────────────────────────────────────────────────────────

def _walled_navmesh(height=20, width=40, cell_size=0.2, wall_row=10, gap_col=20) -> NavMesh:
    # A wall splits the grid into two halves, with a single gap — the only
    # legal path across.
    grid = np.ones((height, width), dtype=bool)
    grid[wall_row, :] = False
    grid[wall_row, gap_col] = True
    return NavMesh(grid=grid, origin=(0.0, 0.0), cell_size=cell_size)


def test_dilation_grows_area_as_dt_grows():
    navmesh = _walled_navmesh()

    small = _belief(navmesh, v_max_m_s=1.6)
    small.initialise((2.0, 1.0))
    small.step(dt_s=0.1)

    large = _belief(navmesh, v_max_m_s=1.6)
    large.initialise((2.0, 1.0))
    large.step(dt_s=1.25)

    assert large.area_m2() > small.area_m2()
    assert large.area_m2() <= navmesh.area_m2()


def test_dilation_never_crosses_an_obstacle():
    """The wavefront must route geodesically through the single gap, not
    in a straight line through the wall: a far-side cell whose EUCLIDEAN
    distance from the origin is well inside the dilation radius, but whose
    only legal path (through the gap) is not, must stay excluded — while a
    near-side cell at a similar euclidean distance, with a clear straight
    path, is included.
    """
    navmesh = _walled_navmesh()
    belief = _belief(navmesh, v_max_m_s=1.6)
    belief.initialise((2.0, 1.0))
    belief.step(dt_s=1.25)  # radius = 2.0m

    mask = belief.mask()
    obstacle = ~navmesh.grid
    assert not np.any(mask & obstacle)  # never a wall cell itself

    near_side = navmesh.world_to_cell(2.0, 1.8)  # 0.8m away, clear straight path
    far_side = navmesh.world_to_cell(2.0, 2.2)  # 1.2m euclidean, ~4.5m geodesic via the gap
    assert mask[near_side[1], near_side[0]]
    assert not mask[far_side[1], far_side[0]]


# ── attestation zeroing ───────────────────────────────────────────────────

def test_admissible_attestation_shrinks_area_and_zeros_cells_beyond_boundary():
    navmesh = _boundary_navmesh()
    belief = _belief(navmesh, tau_attest=0.7)
    origin = (1.0, 2.0)  # west of the boundary at column 20 (x ~= 4.1m)
    belief.initialise(origin)
    belief.step(dt_s=20.0)  # dilate far enough to spread across both sides

    before_area = belief.area_m2()
    beyond_mask = navmesh.cells_beyond(1, origin)
    assert before_area > 0
    assert belief.mask()[beyond_mask].any()  # some mass did reach the far side

    att = _Att(node_id=1, crossing_observed=False, attest_confidence=0.9, region_ids=[1])
    belief.apply_attestation(att)
    belief.normalise()

    after_area = belief.area_m2()
    assert after_area < before_area
    assert not belief.mask()[beyond_mask].any()


def test_inadmissible_low_confidence_attestation_does_not_shrink_area():
    """Safety-critical: an attestation that has not cleared tau_attest must
    never remove candidate-belief mass, regardless of what it claims —
    this is the exact failure mode CLAUDE.md rule 7 / WP-09 exist to
    prevent (a low-confidence "no crossing" claim silently treated as
    negative evidence).
    """
    navmesh = _boundary_navmesh()
    belief = _belief(navmesh, tau_attest=0.7)
    origin = (1.0, 2.0)
    belief.initialise(origin)
    belief.step(dt_s=20.0)

    before_area = belief.area_m2()

    att = _Att(node_id=1, crossing_observed=False, attest_confidence=0.3, region_ids=[1])
    belief.apply_attestation(att)
    belief.normalise()

    after_area = belief.area_m2()
    assert after_area == pytest.approx(before_area)


def test_ablation_switch_disables_attestation_zeroing():
    navmesh = _boundary_navmesh()
    belief = _belief(navmesh, tau_attest=0.7, negative_evidence_enabled=False)
    origin = (1.0, 2.0)
    belief.initialise(origin)
    belief.step(dt_s=20.0)

    before_area = belief.area_m2()
    att = _Att(node_id=1, crossing_observed=False, attest_confidence=0.9, region_ids=[1])
    belief.apply_attestation(att)
    belief.normalise()

    assert belief.area_m2() == pytest.approx(before_area)


# ── false exclusion rate ──────────────────────────────────────────────────

def test_false_exclusion_rate_is_zero_when_true_position_always_retained():
    navmesh = _open_navmesh()
    belief = _belief(navmesh)
    origin_xy = (2.0, 2.0)
    belief.initialise(origin_xy)

    excluded_masks = []
    true_positions = []
    origin_cell = navmesh.world_to_cell(*origin_xy)  # (col, row) = (i, j)
    for _ in range(5):
        belief.step(dt_s=0.5)
        belief.normalise()
        excluded_masks.append(~belief.mask())
        true_positions.append(origin_cell)  # stays put; always inside B_0's cell

    assert false_exclusion_rate(excluded_masks, true_positions) == 0.0


# ── detect_omission ────────────────────────────────────────────────────────

def test_detect_omission_true_with_two_corroborators():
    cfg = NegativeEvidenceConfig(tau_attest=0.7, min_omission_corroborators=2)
    att = _Att(node_id=0, crossing_observed=False, attest_confidence=0.9, region_ids=[1])
    corroborating = [_Claim(node_id=1), _Claim(node_id=2)]
    assert detect_omission(att, corroborating, cfg) is True


def test_detect_omission_false_with_one_corroborator():
    cfg = NegativeEvidenceConfig(tau_attest=0.7, min_omission_corroborators=2)
    att = _Att(node_id=0, crossing_observed=False, attest_confidence=0.9, region_ids=[1])
    corroborating = [_Claim(node_id=1)]
    assert detect_omission(att, corroborating, cfg) is False


def test_detect_omission_false_when_crossing_was_observed():
    cfg = NegativeEvidenceConfig(tau_attest=0.7, min_omission_corroborators=2)
    att = _Att(node_id=0, crossing_observed=True, attest_confidence=0.9, region_ids=[1])
    corroborating = [_Claim(node_id=1), _Claim(node_id=2)]
    assert detect_omission(att, corroborating, cfg) is False


def test_detect_omission_false_when_attestation_itself_inadmissible():
    cfg = NegativeEvidenceConfig(tau_attest=0.7, min_omission_corroborators=2)
    att = _Att(node_id=0, crossing_observed=False, attest_confidence=0.3, region_ids=[1])
    corroborating = [_Claim(node_id=1), _Claim(node_id=2)]
    assert detect_omission(att, corroborating, cfg) is False
