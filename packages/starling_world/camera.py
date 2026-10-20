"""starling_world/camera.py
----------------------------
The pinhole camera model the virtual cameras use — written to reproduce
three.js's `PerspectiveCamera` + `Object3D.lookAt` maths exactly, because
the camera rig (apps/world/static/rig.html) renders each node's frames with
three.js from the same config numbers. That is what lets
`calibration()` hand a node a floor homography that matches the pixels it
receives, the way a site survey would for a physical camera.

Frames: floor coordinates are (x east, y south, z up), metres. three.js is
Y-up, so a floor point (x, y, z) is the three.js point (x, z, y); OpenCV's
camera frame is (x right, y down, z forward).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from starling_geometry.calibration import CameraCalibration

from starling_world.config import CameraConfig, CameraFramesConfig

# floor (x, y, z-up) -> three.js (X, Y-up, Z)
_FLOOR_TO_THREE = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]])
# three.js camera frame (x right, y up, looking down -z) -> OpenCV camera frame
_THREE_CAM_TO_CV = np.diag([1.0, -1.0, -1.0])


@dataclass
class PinholeCamera:
    node_id: int
    mount: tuple[float, float, float]
    look_at: tuple[float, float, float]
    hfov_deg: float
    width: int
    height: int
    name: str = ""
    # derived
    fx: float = field(init=False)
    fy: float = field(init=False)
    cx: float = field(init=False)
    cy: float = field(init=False)
    vfov_deg: float = field(init=False)
    R_cv: np.ndarray = field(init=False, repr=False)  # floor -> OpenCV camera rotation
    t_cv: np.ndarray = field(init=False, repr=False)

    @classmethod
    def from_config(cls, cam: CameraConfig, frames: CameraFramesConfig) -> "PinholeCamera":
        return cls(
            node_id=cam.node_id,
            mount=tuple(cam.mount),
            look_at=tuple(cam.look_at),
            hfov_deg=cam.hfov_deg,
            width=frames.width_px,
            height=frames.height_px,
            name=cam.name,
        )

    def __post_init__(self) -> None:
        aspect = self.width / self.height
        tan_h = math.tan(math.radians(self.hfov_deg) / 2.0)
        tan_v = tan_h / aspect
        self.vfov_deg = math.degrees(2.0 * math.atan(tan_v))
        self.fx = (self.width / 2.0) / tan_h
        self.fy = (self.height / 2.0) / tan_v
        self.cx = self.width / 2.0
        self.cy = self.height / 2.0

        # three.js Matrix4.lookAt(eye, target, up=(0,1,0)): z = eye - target,
        # x = up × z, y = z × x; the matrix's columns are the camera's axes.
        eye = _FLOOR_TO_THREE @ np.asarray(self.mount, dtype=float)
        target = _FLOOR_TO_THREE @ np.asarray(self.look_at, dtype=float)
        z = eye - target
        z /= np.linalg.norm(z)
        x = np.cross(np.array([0.0, 1.0, 0.0]), z)
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        r_three = np.stack([x, y, z], axis=1)  # camera -> three world
        self.R_cv = _THREE_CAM_TO_CV @ r_three.T @ _FLOOR_TO_THREE
        self.t_cv = -(_THREE_CAM_TO_CV @ r_three.T @ eye)

    @property
    def K(self) -> np.ndarray:
        return np.array([[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]])

    def to_camera(self, pts: np.ndarray) -> np.ndarray:
        """Floor-frame points (N, 3) -> OpenCV camera-frame points (N, 3)."""
        pts = np.atleast_2d(np.asarray(pts, dtype=float))
        return pts @ self.R_cv.T + self.t_cv

    def project(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Floor-frame points (N, 3) -> (pixel uv (N, 2), depth (N,)). Points
        behind the camera get depth <= 0 and meaningless uv."""
        pc = self.to_camera(pts)
        depth = pc[:, 2]
        safe = np.where(np.abs(depth) < 1e-9, 1e-9, depth)
        u = self.fx * pc[:, 0] / safe + self.cx
        v = self.fy * pc[:, 1] / safe + self.cy
        return np.stack([u, v], axis=1), depth

    def in_frame(self, uv: np.ndarray, depth: np.ndarray, margin_px: float = 0.0) -> np.ndarray:
        return (
            (depth > 0.05)
            & (uv[:, 0] >= margin_px)
            & (uv[:, 0] <= self.width - margin_px)
            & (uv[:, 1] >= margin_px)
            & (uv[:, 1] <= self.height - margin_px)
        )

    def floor_to_image_h(self) -> np.ndarray:
        """3x3 homography mapping floor (x, y, 1) to image (u, v, 1)."""
        m = np.column_stack([self.R_cv[:, 0], self.R_cv[:, 1], self.t_cv])
        h = self.K @ m
        return h / h[2, 2]

    def calibration(self) -> CameraCalibration:
        """The node's calibration file contents: K, zero distortion (a
        rendered pinhole has none), R/t for diagnostics and the image->floor
        homography every claim's world position comes from. The
        reprojection error is measured on a floor grid, not assumed."""
        h_floor_to_img = self.floor_to_image_h()
        h_img_to_floor = np.linalg.inv(h_floor_to_img)
        h_img_to_floor /= h_img_to_floor[2, 2]

        xs, ys = np.meshgrid(np.linspace(-5, 35, 21), np.linspace(-5, 25, 16))
        floor = np.stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)], axis=1)
        uv, depth = self.project(floor)
        ok = self.in_frame(uv, depth)
        err = 0.0
        if ok.any():
            homog = (
                np.column_stack([floor[ok, 0], floor[ok, 1], np.ones(int(ok.sum()))])
                @ h_floor_to_img.T
            )
            uv_h = homog[:, :2] / homog[:, 2:3]
            err = float(np.sqrt(np.mean(np.sum((uv_h - uv[ok]) ** 2, axis=1))))

        return CameraCalibration(
            K=self.K,
            dist=np.zeros(5),
            reprojection_error=err,
            R=self.R_cv.copy(),
            t=self.t_cv.reshape(3, 1).copy(),
            H=h_img_to_floor,
        )

    def person_box(
        self, x: float, y: float, height_m: float, half_width_m: float = 0.28
    ) -> tuple[np.ndarray, np.ndarray]:
        """Image projection of a standing person's foot and head points, and
        of a few torso-width points — enough for a pixel-height / in-frame
        test without rendering."""
        pts = np.array(
            [
                [x, y, 0.0],
                [x, y, height_m],
                [x - half_width_m, y, height_m * 0.55],
                [x + half_width_m, y, height_m * 0.55],
                [x, y - half_width_m, height_m * 0.55],
                [x, y + half_width_m, height_m * 0.55],
            ]
        )
        return self.project(pts)


def segment_hits_box(p0: np.ndarray, p1: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> bool:
    """Slab test: does the 3D segment p0->p1 pass through the axis-aligned
    box [lo, hi]? Touching the very endpoints does not count."""
    d = p1 - p0
    t0, t1 = 1e-4, 1.0 - 1e-4
    for k in range(3):
        if abs(d[k]) < 1e-12:
            if p0[k] < lo[k] or p0[k] > hi[k]:
                return False
            continue
        a = (lo[k] - p0[k]) / d[k]
        b = (hi[k] - p0[k]) / d[k]
        if a > b:
            a, b = b, a
        t0, t1 = max(t0, a), min(t1, b)
        if t0 > t1:
            return False
    return True
