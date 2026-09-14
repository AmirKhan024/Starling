"""scripts/calibrate_homography.py
------------------------------------
Interactive floor homography calibration: click >=4 points in a
representative image, type each one's measured floor coordinates in
metres, solve with cv2.findHomography, and write H into the same
cam-NN.yaml calibrate_intrinsics.py produced. Self-checks by reporting the
residual of each correspondence in metres.

Usage
-----
    python scripts/calibrate_homography.py --node-id 0 --image data/calib_images/cam0/floor_ref.jpg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from starling_geometry.calibration import CameraCalibration


class _ClickCollector:
    def __init__(self, window_name: str) -> None:
        self.window_name = window_name
        self.points: list[tuple[int, int]] = []

    def on_mouse(self, event, x, y, flags, param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self.points.append((x, y))
            print(f"  clicked image point #{len(self.points) - 1}: ({x}, {y})")


def collect_correspondences_interactive(
    image_path: Path, min_points: int = 4
) -> tuple[list[tuple[int, int]], list[tuple[float, float]]]:
    img = cv2.imread(str(image_path))
    if img is None:
        raise RuntimeError(f"Cannot read {image_path}")

    collector = _ClickCollector("calibrate_homography")
    cv2.namedWindow(collector.window_name)
    cv2.setMouseCallback(collector.window_name, collector.on_mouse)

    print(f"Click at least {min_points} floor-plane points, then press any key to finish.")
    while True:
        display = img.copy()
        for i, (x, y) in enumerate(collector.points):
            cv2.circle(display, (x, y), 5, (0, 255, 0), -1)
            cv2.putText(display, str(i), (x + 6, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.imshow(collector.window_name, display)
        key = cv2.waitKey(20) & 0xFF
        if key != 255 and len(collector.points) >= min_points:
            break
    cv2.destroyAllWindows()

    floor_points = []
    for i, (x, y) in enumerate(collector.points):
        raw = input(f"  Measured floor coords (metres) for point #{i} at image ({x},{y}), as 'x,y': ")
        fx, fy = (float(v) for v in raw.split(","))
        floor_points.append((fx, fy))

    return collector.points, floor_points


def solve_homography(
    image_points: list[tuple[float, float]], floor_points: list[tuple[float, float]]
) -> np.ndarray:
    src = np.array(image_points, dtype=np.float64)
    dst = np.array(floor_points, dtype=np.float64)
    H, _ = cv2.findHomography(src, dst)
    return H


def residuals_m(
    H: np.ndarray,
    image_points: list[tuple[float, float]],
    floor_points: list[tuple[float, float]],
) -> list[float]:
    """Self-check: residual of each correspondence, in metres, after
    solving. Large residuals mean either a bad click or a bad floor
    measurement — this is what catches that before it becomes silent
    downstream error.
    """
    out = []
    for (u, v), (fx, fy) in zip(image_points, floor_points):
        p = H @ np.array([u, v, 1.0])
        p = p / p[2]
        out.append(float(np.hypot(p[0] - fx, p[1] - fy)))
    return out


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Interactive floor homography calibration")
    parser.add_argument("--node-id", type=int, required=True)
    parser.add_argument("--image", type=Path, required=True, help="A representative frame from this camera")
    parser.add_argument("--calib", type=Path, default=None)
    args = parser.parse_args(argv)

    calib_path = args.calib or Path(f"configs/calib/cam-{args.node_id:02d}.yaml")
    if not calib_path.exists():
        print(f"{calib_path} does not exist — run calibrate_intrinsics.py first.", file=sys.stderr)
        sys.exit(1)
    calib = CameraCalibration.from_yaml(calib_path)

    image_points, floor_points = collect_correspondences_interactive(args.image)
    H = solve_homography(image_points, floor_points)

    residuals = residuals_m(H, image_points, floor_points)
    print("Correspondence residuals (metres):")
    for i, r in enumerate(residuals):
        print(f"  point #{i}: {r:.4f} m")
    print(f"  mean: {np.mean(residuals):.4f} m   max: {np.max(residuals):.4f} m")

    calib.H = H
    calib.to_yaml(calib_path)
    print(f"Wrote homography into {calib_path}")


if __name__ == "__main__":
    main()
