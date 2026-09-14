"""scripts/calibrate_intrinsics.py
------------------------------------
Checkerboard intrinsics calibration. Solves K/dist from a folder of
checkerboard images or a live webcam capture session, writes
`configs/calib/cam-NN.yaml`, and refuses to write above the safety
threshold (STARLING_BUILD_STATE.md §7: three of seven contributions rest
on this being done right).

Usage
-----
    python scripts/calibrate_intrinsics.py --node-id 0 --images data/calib_images/cam0/
    python scripts/calibrate_intrinsics.py --node-id 0 --webcam 0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from starling_geometry.calibration import (
    MAX_REPROJECTION_ERROR_PX,
    WARN_REPROJECTION_ERROR_PX,
    CameraCalibration,
)

MIN_USABLE_VIEWS = 5


def find_checkerboard_corners(
    image_paths: list[Path],
    board_size: tuple[int, int],
    square_size_m: float,
):
    """Returns (objpoints, imgpoints, image_size) for cv2.calibrateCamera,
    skipping any image where a checkerboard isn't found.
    """
    objp = np.zeros((board_size[0] * board_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:board_size[0], 0:board_size[1]].T.reshape(-1, 2) * square_size_m

    objpoints = []
    imgpoints = []
    image_size = None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

    for path in image_paths:
        img = cv2.imread(str(path))
        if img is None:
            print(f"  [skip] could not read {path}")
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        image_size = gray.shape[::-1]
        found, corners = cv2.findChessboardCorners(gray, board_size)
        if not found:
            print(f"  [skip] no checkerboard found in {path}")
            continue
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        objpoints.append(objp)
        imgpoints.append(corners)

    return objpoints, imgpoints, image_size


def solve_intrinsics(objpoints, imgpoints, image_size) -> tuple[np.ndarray, np.ndarray, float]:
    _, K, dist, rvecs, tvecs = cv2.calibrateCamera(objpoints, imgpoints, image_size, None, None)

    total_error = 0.0
    for i in range(len(objpoints)):
        projected, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], K, dist)
        total_error += cv2.norm(imgpoints[i], projected, cv2.NORM_L2) / len(projected)
    mean_error = total_error / max(len(objpoints), 1)

    return K, dist, float(mean_error)


def capture_from_webcam(
    device: int, board_size: tuple[int, int], out_dir: Path, max_images: int = 20
) -> list[Path]:
    """Live capture: SPACE saves the current frame if a checkerboard is
    detected, ESC finishes early.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open webcam device {device}")

    saved: list[Path] = []
    print(f"Press SPACE to capture (need a detected checkerboard), ESC to finish. Target: {max_images} images.")
    try:
        while len(saved) < max_images:
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            found, corners = cv2.findChessboardCorners(gray, board_size)
            display = frame.copy()
            if found:
                cv2.drawChessboardCorners(display, board_size, corners, found)
            cv2.imshow("calibrate_intrinsics", display)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key == ord(" ") and found:
                path = out_dir / f"capture_{len(saved):03d}.png"
                cv2.imwrite(str(path), frame)
                saved.append(path)
                print(f"  captured {path}  ({len(saved)}/{max_images})")
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return saved


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Checkerboard intrinsics calibration")
    parser.add_argument("--node-id", type=int, required=True)
    parser.add_argument("--images", type=Path, help="Folder of checkerboard images")
    parser.add_argument("--webcam", type=int, default=None, help="Webcam device index for live capture")
    parser.add_argument("--board-cols", type=int, default=9, help="Inner corners, not squares")
    parser.add_argument("--board-rows", type=int, default=6)
    parser.add_argument("--square-size-m", type=float, default=0.025)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.images and args.webcam is None:
        parser.error("Provide --images <folder> or --webcam <device index>")

    board_size = (args.board_cols, args.board_rows)

    if args.images:
        image_paths = sorted(args.images.glob("*.jpg")) + sorted(args.images.glob("*.png"))
        if not image_paths:
            print(f"No .jpg/.png images found in {args.images}", file=sys.stderr)
            sys.exit(1)
    else:
        capture_dir = Path(f"data/calib_images/cam{args.node_id}")
        image_paths = capture_from_webcam(args.webcam, board_size, capture_dir)
        if not image_paths:
            print("No checkerboard images captured.", file=sys.stderr)
            sys.exit(1)

    objpoints, imgpoints, image_size = find_checkerboard_corners(image_paths, board_size, args.square_size_m)
    if len(objpoints) < MIN_USABLE_VIEWS:
        print(
            f"Only {len(objpoints)} usable checkerboard views found "
            f"(need >= {MIN_USABLE_VIEWS} for a reliable calibration).",
            file=sys.stderr,
        )
        sys.exit(1)

    K, dist, reprojection_error = solve_intrinsics(objpoints, imgpoints, image_size)

    print(f"Used {len(objpoints)} views. Reprojection error: {reprojection_error:.4f} px")
    if reprojection_error > WARN_REPROJECTION_ERROR_PX:
        print(f"WARNING: exceeds the {WARN_REPROJECTION_ERROR_PX}px target — consider recalibrating.")
    if reprojection_error > MAX_REPROJECTION_ERROR_PX:
        print(
            f"REFUSING to write: {reprojection_error:.4f}px exceeds the "
            f"{MAX_REPROJECTION_ERROR_PX}px hard safety threshold.",
            file=sys.stderr,
        )
        sys.exit(1)

    out_path = args.out or Path(f"configs/calib/cam-{args.node_id:02d}.yaml")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    CameraCalibration(K=K, dist=dist, reprojection_error=reprojection_error).to_yaml(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
