"""scripts/validate_calibration.py
------------------------------------
The "10 metre walk" test: click the two endpoints of a known-distance line
in a video frame, reconstruct the distance via the calibration's floor
homography, and report PASS/FAIL against a 0.3 m tolerance. Writes
docs/calibration_validation.md.

Usage
-----
    python scripts/validate_calibration.py --calib configs/calib/cam-00.yaml \\
        --video data/videos/cam0.mp4 --known-distance-m 10.0
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from starling_geometry.calibration import CameraCalibration

TOLERANCE_M = 0.3


class _ClickCollector:
    def __init__(self, window_name: str) -> None:
        self.window_name = window_name
        self.points: list[tuple[int, int]] = []

    def on_mouse(self, event, x, y, flags, param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self.points.append((x, y))
            print(f"  clicked point #{len(self.points) - 1}: ({x}, {y})")


def collect_two_points_interactive(frame: np.ndarray) -> tuple[tuple[int, int], tuple[int, int]]:
    collector = _ClickCollector("validate_calibration")
    cv2.namedWindow(collector.window_name)
    cv2.setMouseCallback(collector.window_name, collector.on_mouse)

    print("Click the two endpoints of the known-distance line, then press any key.")
    while True:
        display = frame.copy()
        for x, y in collector.points:
            cv2.circle(display, (x, y), 5, (0, 0, 255), -1)
        cv2.imshow(collector.window_name, display)
        key = cv2.waitKey(20) & 0xFF
        if key != 255 and len(collector.points) >= 2:
            break
    cv2.destroyAllWindows()
    return collector.points[0], collector.points[1]


def write_report(
    out_path: Path,
    calib_path: Path,
    video_path: Path,
    known_m: float,
    reconstructed_m: float,
    error_m: float,
    passed: bool,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    status = "PASS" if passed else "FAIL"
    content = f"""# Calibration validation — 10 m walk test

| Field | Value |
|---|---|
| Calibration | `{calib_path}` |
| Video | `{video_path}` |
| Known distance | {known_m:.3f} m |
| Reconstructed distance | {reconstructed_m:.3f} m |
| Error | {error_m:.3f} m |
| Tolerance | {TOLERANCE_M} m |
| Result | **{status}** |

Generated {datetime.now(timezone.utc).isoformat()} by `scripts/validate_calibration.py`.
"""
    out_path.write_text(content, encoding="utf-8")
    print(f"Wrote {out_path}")


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="10-metre-walk calibration validation")
    parser.add_argument("--calib", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--known-distance-m", type=float, default=10.0)
    parser.add_argument("--frame-index", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("docs/calibration_validation.md"))
    args = parser.parse_args(argv)

    calib = CameraCalibration.from_yaml(args.calib)

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        print(f"Cannot open {args.video}", file=sys.stderr)
        sys.exit(1)
    if args.frame_index:
        cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame_index)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print("Could not read a frame from the video.", file=sys.stderr)
        sys.exit(1)

    (u1, v1), (u2, v2) = collect_two_points_interactive(frame)
    x1, y1 = calib.image_to_floor(u1, v1)
    x2, y2 = calib.image_to_floor(u2, v2)
    reconstructed_m = float(np.hypot(x2 - x1, y2 - y1))
    error_m = abs(reconstructed_m - args.known_distance_m)
    passed = error_m <= TOLERANCE_M

    print(f"Known distance:         {args.known_distance_m:.3f} m")
    print(f"Reconstructed distance: {reconstructed_m:.3f} m")
    print(f"Error:                  {error_m:.3f} m  (tolerance {TOLERANCE_M} m)")
    print(f"Result: {'PASS' if passed else 'FAIL'}")

    write_report(args.out, args.calib, args.video, args.known_distance_m, reconstructed_m, error_m, passed)

    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
