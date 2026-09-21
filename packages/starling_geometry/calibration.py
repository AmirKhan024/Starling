"""starling_geometry/calibration.py
-------------------------------------
Per-camera intrinsics, extrinsics, and floor homography (WP-05).

STARLING_BUILD_STATE.md §7 is blunt: three of the seven contributions
(C2's plausibility check, C3's reachability gate, C4's candidate region)
rest on this two-hour task, and it is easy to do badly. The checks are
built into the code path rather than left to discipline:
`from_yaml` refuses to load a calibration whose `reprojection_error`
exceeds 1.0 px, and `scripts/calibrate_intrinsics.py` refuses to *write*
one above that threshold in the first place.

2D only (CLAUDE.md / STARLING_BUILD_STATE.md §12 rule 2): `R`/`t` are kept
only because a full 3D pose is occasionally useful diagnostic context (and
`cv2.calibrateCamera` produces them essentially for free alongside `K`),
never as a 3D reconstruction path. Every claim's actual position comes
from `H`, the 2D floor homography — that is the one and only geometry
Starling reasons about.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import cv2
import numpy as np

MAX_REPROJECTION_ERROR_PX = 1.0
WARN_REPROJECTION_ERROR_PX = 0.5

# Perturbation radius used by position_sigma's pixel-noise term, and the
# additive term standing in for the floor not being perfectly flat. Both
# are rough by design — STARLING_BUILD_STATE.md §7: "having a number at
# all is what matters", because an arbitrary tolerance is indefensible but
# a *missing* one is worse (Prompt 8's plausibility check has nothing to
# gate on at all).
DEFAULT_PIXEL_PERTURBATION_PX = 2.0
DEFAULT_FLOOR_FLATNESS_M = 0.05


def bbox_floor_point(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """The image-plane point a floor homography is actually valid at: the
    bottom-centre of the bbox, approximating where the feet meet the
    floor plane. The bbox centroid — used naively in some pipelines — sits
    at roughly torso height, nowhere near the floor plane the homography
    was solved for, and mapping it through `H` produces a meaningless
    "floor position".
    """
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2)


@dataclass
class CameraCalibration:
    K: np.ndarray
    dist: np.ndarray
    reprojection_error: float
    R: Optional[np.ndarray] = None
    t: Optional[np.ndarray] = None
    H: Optional[np.ndarray] = None

    def image_to_floor(self, u: float, v: float) -> tuple[float, float]:
        """Map an image pixel to floor metres via `H`. Only valid for
        points actually on the floor plane — use `bbox_floor_point` to get
        one from a detection bbox.
        """
        if self.H is None:
            raise ValueError("No floor homography set — run calibrate_homography.py first")
        pt = self.H @ np.array([u, v, 1.0])
        pt = pt / pt[2]
        return float(pt[0]), float(pt[1])

    def floor_to_image(self, x: float, y: float) -> tuple[float, float]:
        if self.H is None:
            raise ValueError("No floor homography set — run calibrate_homography.py first")
        h_inv = np.linalg.inv(self.H)
        pt = h_inv @ np.array([x, y, 1.0])
        pt = pt / pt[2]
        return float(pt[0]), float(pt[1])

    def position_sigma(
        self,
        bbox: tuple[float, float, float, float],
        pixel_perturbation_px: float = DEFAULT_PIXEL_PERTURBATION_PX,
        floor_flatness_m: float = DEFAULT_FLOOR_FLATNESS_M,
    ) -> float:
        """Rough 1-sigma position uncertainty in metres for a detection's
        floor position: perturb the bbox's floor point by
        +/- `pixel_perturbation_px` pixels in each axis, push each
        perturbed point through `H`, take the largest resulting spread
        from the unperturbed estimate, and add `floor_flatness_m` (the
        floor is not perfectly planar; homography error grows with real
        deviation from the calibration plane). This is not a rigorous
        uncertainty propagation — it is a defensible order-of-magnitude
        number for a threshold that otherwise has nothing at all.
        """
        u, v = bbox_floor_point(bbox)
        center = np.array(self.image_to_floor(u, v))

        offsets = [
            (-pixel_perturbation_px, 0.0), (pixel_perturbation_px, 0.0),
            (0.0, -pixel_perturbation_px), (0.0, pixel_perturbation_px),
        ]
        spread_m = max(
            float(np.linalg.norm(np.array(self.image_to_floor(u + du, v + dv)) - center))
            for du, dv in offsets
        )
        return spread_m + floor_flatness_m

    def to_yaml(self, path: Union[str, Path]) -> None:
        """Write via cv2.FileStorage (OpenCV's YAML dialect) — this is the
        format scripts/calibrate_intrinsics.py and
        scripts/calibrate_homography.py both read and write, so a
        calibration can be built up across the two stages.
        """
        fs = cv2.FileStorage(str(path), cv2.FILE_STORAGE_WRITE)
        try:
            fs.write("K", self.K)
            fs.write("dist", self.dist)
            fs.write("reprojection_error", float(self.reprojection_error))
            if self.R is not None:
                fs.write("R", self.R)
            if self.t is not None:
                fs.write("t", self.t)
            if self.H is not None:
                fs.write("H", self.H)
        finally:
            fs.release()

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "CameraCalibration":
        fs = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
        try:
            k_node = fs.getNode("K")
            dist_node = fs.getNode("dist")
            err_node = fs.getNode("reprojection_error")
            if k_node.empty() or dist_node.empty() or err_node.empty():
                raise ValueError(f"{path}: missing K/dist/reprojection_error — not a valid calibration file")

            reprojection_error = float(err_node.real())
            if reprojection_error > MAX_REPROJECTION_ERROR_PX:
                raise ValueError(
                    f"{path}: reprojection_error={reprojection_error:.3f}px exceeds the "
                    f"{MAX_REPROJECTION_ERROR_PX}px safety threshold — this calibration must "
                    f"be redone, not loaded (STARLING_BUILD_STATE.md §7)"
                )

            def _opt_mat(name: str) -> Optional[np.ndarray]:
                node = fs.getNode(name)
                return None if node.empty() else node.mat()

            return cls(
                K=k_node.mat(),
                # OpenCV FileStorage round-trips a 1-D array as a (N,1)
                # matrix, not the original (N,) shape — flatten so
                # `dist` compares equal to what was written (D-issue
                # found in review: test_to_yaml_from_yaml_round_trips).
                dist=dist_node.mat().flatten(),
                reprojection_error=reprojection_error,
                R=_opt_mat("R"),
                t=_opt_mat("t"),
                H=_opt_mat("H"),
            )
        finally:
            fs.release()
