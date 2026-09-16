"""Tests for starling_attest.attestation / starling_attest.admission (WP-09 Part 2)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from nacl.signing import SigningKey

from starling_attest.admission import admissible
from starling_attest.attestation import Attestor
from starling_geometry.calibration import CameraCalibration
from starling_geometry.navmesh import NavMesh
from starling_net.keys import NodeKeys
from starling_node.config import AttestConfig, CoverageConfig
from starling_perception.coverage import CoverageAssessor, DetectorStats

WIDTH, HEIGHT = 800, 400
SCALE = 0.01  # floor (x, y) = pixel (u, v) * SCALE -> 8m x 4m floor


@dataclass
class _Track:
    local_track_id: int
    bbox: tuple[float, float, float, float]


def _identity_calibration() -> CameraCalibration:
    H = np.array([[SCALE, 0, 0], [0, SCALE, 0], [0, 0, 1]], dtype=np.float64)
    return CameraCalibration(K=np.eye(3), dist=np.zeros(5), reprojection_error=0.1, H=H)


def _navmesh_with_boundary() -> NavMesh:
    # 8m x 4m free-space grid (cell_size=0.2m), a vertical boundary at
    # x ~= 4.1m (grid column i=20), matching demo_site's gap-exit shape.
    grid = np.ones((20, 40), dtype=bool)
    boundary_cells = [(20, j) for j in range(20)]
    return NavMesh(grid=grid, origin=(0.0, 0.0), cell_size=0.2, boundaries={1: boundary_cells})


def _checkerboard_frame(low: int = 100, high: int = 156, block: int = 8) -> np.ndarray:
    xv, yv = np.meshgrid(np.arange(WIDTH), np.arange(HEIGHT))
    mask = ((xv // block + yv // block) % 2) == 0
    plane = np.where(mask, low, high).astype(np.uint8)
    return np.stack([plane] * 3, axis=-1)


def _healthy_stats() -> DetectorStats:
    return DetectorStats(
        target_fps=25.0, achieved_fps=25.0, dropped=0, frames_read=100,
        recent_confidences=[0.8] * 20, baseline_confidences=[0.8] * 20,
    )


def _assessor(**cov_overrides) -> CoverageAssessor:
    cfg = CoverageConfig(
        roi_polygon=[(0.0, 0.0), (8.0, 0.0), (8.0, 4.0), (0.0, 4.0)],
        watched_boundary_ids=[1],
        tau_attest=0.7,
        **cov_overrides,
    )
    return CoverageAssessor(cfg=cfg, calibration=_identity_calibration(), navmesh=_navmesh_with_boundary())


def _keys(node_id: int = 0) -> NodeKeys:
    signing_key = SigningKey.generate()
    return NodeKeys(node_id=node_id, signing_key=signing_key, peer_pubkeys={node_id: signing_key.verify_key})


def _bbox_at_floor_x(x_m: float, y_m: float = 2.0) -> tuple[float, float, float, float]:
    u, v = x_m / SCALE, y_m / SCALE
    return (u - 5, v - 10, u + 5, v)


# ── healthy, no crossing -> crossing_observed=False ──────────────────────

def test_healthy_node_no_crossing_emits_crossing_observed_false():
    attestor = Attestor(node_id=0, coverage_assessor=_assessor(), cfg=AttestConfig(), keys=None)
    frame = _checkerboard_frame()

    att = None
    for t in (0.0, 0.5, 1.0, 1.5, 2.0):
        att = attestor.tick(t, frame, [], _healthy_stats())

    assert att is not None
    assert att.crossing_observed is False
    assert att.attest_confidence >= 0.7


# ── below tau_attest -> emit NOTHING ──────────────────────────────────────
# Safety-critical: an attestation carrying a low score must never be
# emitted "for completeness" — silence must never be readable as evidence.

def test_low_confidence_node_emits_nothing():
    attestor = Attestor(node_id=0, coverage_assessor=_assessor(), cfg=AttestConfig(), keys=None)
    clear = _checkerboard_frame()

    occluded = clear.copy()
    occluded[:, : int(WIDTH * 0.6)] = 0  # dark rectangle over ~60% of the ROI

    result = None
    for t, frame in ((0.0, clear), (0.5, clear), (1.0, clear), (1.5, clear), (2.0, occluded)):
        result = attestor.tick(t, frame, [], _healthy_stats())

    assert result is None


# ── crossing observed -> crossing_observed=True ───────────────────────────

def test_crossing_observed_emits_crossing_observed_true():
    attestor = Attestor(node_id=0, coverage_assessor=_assessor(), cfg=AttestConfig(), keys=None)
    frame = _checkerboard_frame()

    before = _Track(local_track_id=1, bbox=_bbox_at_floor_x(3.0))
    after = _Track(local_track_id=1, bbox=_bbox_at_floor_x(5.0))

    result = None
    for t, det in ((0.0, before), (0.5, before), (1.0, before), (1.5, before), (2.0, after)):
        result = attestor.tick(t, frame, [det], _healthy_stats())

    assert result is not None
    assert result.crossing_observed is True


# ── wire size ──────────────────────────────────────────────────────────────

def test_serialised_attestation_is_under_200_bytes():
    attestor = Attestor(node_id=0, coverage_assessor=_assessor(), cfg=AttestConfig(), keys=_keys(0))
    frame = _checkerboard_frame()

    att = None
    for t in (0.0, 0.5, 1.0, 1.5, 2.0):
        att = attestor.tick(t, frame, [], _healthy_stats())

    assert att is not None
    assert att.signature  # actually signed
    assert att.ByteSize() < 200


# ── admission ────────────────────────────────────────────────────────────

def _fresh_attestation(**overrides):
    from starling_proto.generated import starling_pb2

    fields = dict(node_id=0, crossing_observed=False, attest_confidence=0.9, signature=b"\x01" * 64)
    fields.update(overrides)
    att = starling_pb2.CoverageAttestation(**fields)
    att.t_end.physical_ms = 0
    return att


def test_admissible_rejects_stale_attestation():
    cfg = AttestConfig(freshness_window_s=10.0)
    att = _fresh_attestation()
    ok, reason = admissible(att, reputation=None, cfg=cfg, now_physical_ms=20_000)
    assert ok is False
    assert reason == "stale"


def test_admissible_rejects_low_reputation():
    cfg = AttestConfig(min_reputation=0.5)
    att = _fresh_attestation()
    ok, reason = admissible(att, reputation={0: 0.1}, cfg=cfg)
    assert ok is False
    assert reason == "low_reputation"


def test_admissible_rejects_below_tau_attest():
    cfg = AttestConfig(tau_attest=0.7)
    att = _fresh_attestation(attest_confidence=0.5)
    ok, reason = admissible(att, reputation=None, cfg=cfg)
    assert ok is False
    assert reason == "below_tau_attest"


def test_admissible_accepts_a_healthy_fresh_attestation():
    cfg = AttestConfig(tau_attest=0.7, freshness_window_s=10.0, min_reputation=0.0)
    att = _fresh_attestation()
    ok, reason = admissible(att, reputation={0: 1.0}, cfg=cfg, now_physical_ms=1_000)
    assert ok is True
    assert reason == "admissible"
