"""Protects apps/baseline.py, the frozen centralized control condition
(CLAUDE.md "Preserved baseline"), from behavioural drift.

Marked @pytest.mark.integration since it launches a real subprocess loading
YOLO weights; skips cleanly when those aren't available locally (same
guard as tests/test_perception_pipeline.py and tests/test_node_process.py).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from starling_store.identity_store import IdentityStore

REPO_ROOT = Path(__file__).resolve().parent.parent


def _yolo_weights_available() -> bool:
    try:
        from ultralytics.utils import SETTINGS
        weights_dir = Path(SETTINGS.get("weights_dir", "weights"))
    except Exception:
        weights_dir = Path("weights")
    candidates = [Path.cwd() / "yolov8n.pt", weights_dir / "yolov8n.pt"]
    return any(p.exists() for p in candidates)


def _run_baseline(video_path: Path, output_dir: Path, db_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, "apps/baseline.py",
            "--videos", str(video_path),
            "--output", str(output_dir),
            "--db", str(db_path),
            "--no-video",
            "--device", "cpu",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # baseline.py prints emoji; avoid a cp1252 decode crash on Windows
        timeout=180,
    )


@pytest.mark.integration
@pytest.mark.skipif(not _yolo_weights_available(), reason="YOLO weights not available locally")
def test_baseline_is_deterministic_across_two_runs(tmp_path: Path, synthetic_video: Path):
    db_1 = tmp_path / "run1.db"
    db_2 = tmp_path / "run2.db"

    result_1 = _run_baseline(synthetic_video, tmp_path / "out1", db_1)
    assert result_1.returncode == 0, result_1.stderr

    result_2 = _run_baseline(synthetic_video, tmp_path / "out2", db_2)
    assert result_2.returncode == 0, result_2.stderr

    stats_1 = IdentityStore(db_path=str(db_1)).stats()
    stats_2 = IdentityStore(db_path=str(db_2)).stats()

    assert stats_1["active"] + stats_1["lost"] + stats_1["resolved"] == \
        stats_2["active"] + stats_2["lost"] + stats_2["resolved"]
    assert stats_1["sightings"] == stats_2["sightings"]
