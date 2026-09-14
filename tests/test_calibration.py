"""Tests for starling_geometry.calibration (WP-05 Part 1)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from starling_geometry.calibration import CameraCalibration, bbox_floor_point


def _synthetic_nadir_camera(height_m: float = 5.0) -> np.ndarray:
    """A camera looking straight down at the floor (Z=0 plane) from
    `height_m` metres above the origin. Returns H (image -> floor).
    """
    K = np.array([[800, 0, 320], [0, 800, 240], [0, 0, 1]], dtype=np.float64)
    R = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], dtype=np.float64)
    camera_center = np.array([0.0, 0.0, height_m])
    t = -R @ camera_center

    h_floor_to_image = K @ np.column_stack([R[:, 0], R[:, 1], t])
    return np.linalg.inv(h_floor_to_image)


def _project_floor_to_image(h_image_to_floor: np.ndarray, x: float, y: float) -> tuple[float, float]:
    h_floor_to_image = np.linalg.inv(h_image_to_floor)
    p = h_floor_to_image @ np.array([x, y, 1.0])
    p = p / p[2]
    return float(p[0]), float(p[1])


def test_image_to_floor_recovers_known_points_within_1cm():
    H = _synthetic_nadir_camera(height_m=5.0)
    calib = CameraCalibration(K=np.eye(3), dist=np.zeros(5), reprojection_error=0.1, H=H)

    known_floor_points = [(0.0, 0.0), (1.0, 0.5), (1.2, 1.0), (0.3, -0.8)]
    for x, y in known_floor_points:
        u, v = _project_floor_to_image(H, x, y)
        rx, ry = calib.image_to_floor(u, v)
        assert abs(rx - x) < 0.01
        assert abs(ry - y) < 0.01


def test_floor_to_image_is_the_inverse_of_image_to_floor():
    H = _synthetic_nadir_camera()
    calib = CameraCalibration(K=np.eye(3), dist=np.zeros(5), reprojection_error=0.1, H=H)

    u0, v0 = 400.0, 300.0
    x, y = calib.image_to_floor(u0, v0)
    u1, v1 = calib.floor_to_image(x, y)
    assert abs(u1 - u0) < 1e-6
    assert abs(v1 - v0) < 1e-6


def test_to_yaml_from_yaml_round_trips(tmp_path: Path):
    H = _synthetic_nadir_camera()
    calib = CameraCalibration(
        K=np.array([[800, 0, 320], [0, 800, 240], [0, 0, 1]], dtype=np.float64),
        dist=np.array([0.01, -0.02, 0.0, 0.0, 0.0]),
        reprojection_error=0.42,
        H=H,
    )
    path = tmp_path / "cam-00.yaml"
    calib.to_yaml(path)

    restored = CameraCalibration.from_yaml(path)
    assert np.allclose(restored.K, calib.K)
    assert np.allclose(restored.dist, calib.dist)
    assert np.allclose(restored.H, calib.H)
    assert restored.reprojection_error == pytest.approx(calib.reprojection_error)


def test_from_yaml_refuses_a_calibration_above_the_error_threshold(tmp_path: Path):
    calib = CameraCalibration(
        K=np.eye(3), dist=np.zeros(5), reprojection_error=1.5,  # above MAX_REPROJECTION_ERROR_PX
    )
    path = tmp_path / "bad-cam.yaml"
    calib.to_yaml(path)

    with pytest.raises(ValueError, match="reprojection_error"):
        CameraCalibration.from_yaml(path)


def test_bbox_floor_point_is_bottom_centre():
    assert bbox_floor_point((10.0, 20.0, 30.0, 100.0)) == (20.0, 100.0)


def test_position_sigma_is_positive_and_includes_floor_flatness_floor():
    H = _synthetic_nadir_camera()
    calib = CameraCalibration(K=np.eye(3), dist=np.zeros(5), reprojection_error=0.1, H=H)
    sigma = calib.position_sigma((300.0, 200.0, 340.0, 280.0), floor_flatness_m=0.05)
    assert sigma >= 0.05
