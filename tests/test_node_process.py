"""Tests for apps/node.py (D-04, D-05, D-07: the standalone node process).

Marked @pytest.mark.integration since it launches a real subprocess that
loads YOLO weights; skips cleanly when those aren't available locally (see
tests/test_perception_pipeline.py for the same guard).
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import structlog
import yaml

import apps.node as node_app
from starling_geometry.calibration import CameraCalibration
from starling_node.config import NodeConfig

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_load_calibration_warns_and_returns_none_when_uncalibrated(tmp_path: Path):
    """D-09 / WP-05: a node without calib_path must warn loudly, not fail
    silently, and must not produce a calibration. Fast — no YOLO weights
    needed, since _load_calibration is factored out of run() precisely so
    this doesn't require the rest of node startup.
    """
    cfg = NodeConfig(
        node_id=7,
        name="node-07",
        source=str(tmp_path / "unused.mp4"),
        db_path=str(tmp_path / "local.db"),
        calib_path=None,
    )
    log = structlog.get_logger("test")

    with structlog.testing.capture_logs() as captured:
        calib = node_app._load_calibration(cfg, log)

    assert calib is None
    assert any(entry.get("event") == "node_uncalibrated" for entry in captured)


def test_load_calibration_loads_and_does_not_warn_when_calib_path_set(tmp_path: Path):
    calib_path = tmp_path / "cam-00.yaml"
    CameraCalibration(K=np.eye(3), dist=np.zeros(5), reprojection_error=0.1).to_yaml(calib_path)

    cfg = NodeConfig(
        node_id=0,
        name="node-00",
        source=str(tmp_path / "unused.mp4"),
        db_path=str(tmp_path / "local.db"),
        calib_path=str(calib_path),
    )
    log = structlog.get_logger("test")

    with structlog.testing.capture_logs() as captured:
        calib = node_app._load_calibration(cfg, log)

    assert calib is not None
    assert not any(entry.get("event") == "node_uncalibrated" for entry in captured)


def _yolo_weights_available() -> bool:
    try:
        from ultralytics.utils import SETTINGS
        weights_dir = Path(SETTINGS.get("weights_dir", "weights"))
    except Exception:
        weights_dir = Path("weights")
    candidates = [Path.cwd() / "yolov8n.pt", weights_dir / "yolov8n.pt"]
    return any(p.exists() for p in candidates)


@pytest.mark.integration
@pytest.mark.skipif(not _yolo_weights_available(), reason="YOLO weights not available locally")
def test_node_process_writes_only_its_own_db(tmp_path: Path, synthetic_video: Path):
    db_root = tmp_path / "data" / "nodes"
    db_path = db_root / "node-00" / "local.db"

    config = {
        "node_id": 0,
        "name": "node-00",
        "source": str(synthetic_video),
        "db_path": str(db_path),
    }
    config_path = tmp_path / "node-00.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "apps/node.py",
            "--config", str(config_path),
            "--max-frames", "50",
            "--speed", "20",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr

    assert db_path.exists()

    conn = sqlite3.connect(str(db_path))
    try:
        # The synthetic_video fixture draws a plain moving rectangle, not a
        # person-shaped object, so YOLO may legitimately find zero "person"
        # detections and the claims table can be empty. What proves the
        # node process actually ran LocalStore end-to-end (schema created,
        # at least one write committed) is node_meta's persisted seq
        # counter row, which is written unconditionally on first use.
        node_meta_rows = conn.execute("SELECT COUNT(*) FROM node_meta").fetchone()[0]
        claim_rows = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    finally:
        conn.close()

    assert node_meta_rows > 0
    assert claim_rows >= 0  # may be 0 for this fixture; table must at least exist

    # No other node directory was created.
    assert [p.name for p in db_root.iterdir()] == ["node-00"]
