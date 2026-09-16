"""Tests for starling_perception.coverage (WP-09 Part 1).

All synthetic — no model weights, no real footage, per WP-09's own
acceptance rule ("must be testable on synthetic frames").
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from starling_geometry.calibration import CameraCalibration
from starling_perception.coverage import CoverageAssessor, DetectorStats
from starling_node.config import CoverageConfig

WIDTH, HEIGHT = 400, 300
# Identity-like homography: floor (x, y) = pixel (u, v) * SCALE, so an
# 8m x 6m ROI maps exactly onto the frame.
SCALE = 0.02


@dataclass
class _Detection:
    bbox: tuple[float, float, float, float]
    class_id: int = 0


def _identity_calibration() -> CameraCalibration:
    H = np.array([[SCALE, 0, 0], [0, SCALE, 0], [0, 0, 1]], dtype=np.float64)
    return CameraCalibration(
        K=np.eye(3), dist=np.zeros(5), reprojection_error=0.1, H=H
    )


def _cfg(**overrides) -> CoverageConfig:
    defaults = dict(
        roi_polygon=[(0.0, 0.0), (8.0, 0.0), (8.0, 6.0), (0.0, 6.0)],
        tau_attest=0.7,
    )
    defaults.update(overrides)
    return CoverageConfig(**defaults)


def _assessor(**cfg_overrides) -> CoverageAssessor:
    return CoverageAssessor(cfg=_cfg(**cfg_overrides), calibration=_identity_calibration(), navmesh=None)


def _flat_frame(value: int) -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), value, dtype=np.uint8)


def _checkerboard_frame(low: int = 100, high: int = 156, block: int = 8) -> np.ndarray:
    xv, yv = np.meshgrid(np.arange(WIDTH), np.arange(HEIGHT))
    mask = ((xv // block + yv // block) % 2) == 0
    plane = np.where(mask, low, high).astype(np.uint8)
    return np.stack([plane] * 3, axis=-1)


# ── occlusion_ratio ───────────────────────────────────────────────────────

def test_clear_frame_gives_occlusion_near_zero():
    assessor = _assessor()
    frame = _flat_frame(128)
    assert assessor.occlusion_ratio(frame, []) == pytest.approx(0.0, abs=1e-6)


def test_dark_rectangle_over_half_roi_raises_occlusion_above_0_4():
    assessor = _assessor()
    clear = _flat_frame(128)
    assessor.occlusion_ratio(clear, [])  # establish the background

    occluded = clear.copy()
    occluded[:, : WIDTH // 2] = 0  # dark rectangle over the left half

    ratio = assessor.occlusion_ratio(occluded, [])
    assert ratio > 0.4


def test_no_roi_configured_gives_occlusion_zero():
    assessor = _assessor(roi_polygon=[])
    assert assessor.occlusion_ratio(_flat_frame(0), []) == 0.0


def test_occluder_class_detection_counts_even_on_the_first_frame():
    assessor = _assessor()
    frame = _flat_frame(128)
    # A "truck" (class_id=7) covering the left half of the frame, present
    # from the very first call — dynamic occluders (component b) don't
    # need the background model to warm up, unlike static occlusion.
    det = _Detection(bbox=(0, 0, WIDTH / 2, HEIGHT), class_id=7)
    ratio = assessor.occlusion_ratio(frame, [det])
    assert ratio > 0.4


def test_person_detection_is_never_counted_as_occlusion():
    assessor = _assessor()
    frame = _flat_frame(128)
    det = _Detection(bbox=(0, 0, WIDTH / 2, HEIGHT), class_id=0)  # PERSON_CLASS_ID
    assert assessor.occlusion_ratio(frame, [det]) == pytest.approx(0.0, abs=1e-6)


# ── illumination_score ───────────────────────────────────────────────────

def test_uniformly_dark_frame_scores_low():
    assessor = _assessor()
    assert assessor.illumination_score(_flat_frame(5)) < 0.2


def test_blown_out_white_frame_scores_low():
    assessor = _assessor()
    assert assessor.illumination_score(_flat_frame(250)) < 0.2


def test_well_exposed_textured_frame_scores_high():
    assessor = _assessor()
    assert assessor.illumination_score(_checkerboard_frame()) > 0.7


def test_well_exposed_scores_higher_than_dark_or_blown_out():
    assessor = _assessor()
    well = assessor.illumination_score(_checkerboard_frame())
    dark = _assessor().illumination_score(_flat_frame(5))
    bright = _assessor().illumination_score(_flat_frame(250))
    assert well > dark
    assert well > bright


# ── detector_health ───────────────────────────────────────────────────────

def _healthy_stats(**overrides) -> DetectorStats:
    defaults = dict(
        target_fps=25.0,
        achieved_fps=25.0,
        dropped=0,
        frames_read=100,
        recent_confidences=[0.8] * 20,
        baseline_confidences=[0.8] * 20,
    )
    defaults.update(overrides)
    return DetectorStats(**defaults)


def test_detector_health_falls_as_dropped_frame_ratio_rises():
    assessor = _assessor()
    healthy = assessor.detector_health(_healthy_stats())
    degraded = assessor.detector_health(_healthy_stats(dropped=50, frames_read=50))
    assert degraded < healthy


def test_detector_health_full_marks_for_perfect_stats():
    assessor = _assessor()
    assert assessor.detector_health(_healthy_stats()) == pytest.approx(1.0)


def test_detector_health_falls_when_confidence_distribution_shifts():
    assessor = _assessor()
    healthy = assessor.detector_health(_healthy_stats())
    shifted = assessor.detector_health(
        _healthy_stats(recent_confidences=[0.1] * 20, baseline_confidences=[0.9] * 20)
    )
    assert shifted < healthy


# ── assess() / attest_confidence ─────────────────────────────────────────

def test_attest_confidence_is_exactly_the_minimum_of_the_three():
    assessor = _assessor()
    frame = _checkerboard_frame()
    state = assessor.assess(frame, [], _healthy_stats(dropped=10, frames_read=30))
    assert state.attest_confidence == pytest.approx(
        min(1.0 - state.occlusion_ratio, state.illumination_score, state.detector_health)
    )
