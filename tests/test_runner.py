"""Tests for starling_eval.runner (WP-11 Part 5).

Marked @pytest.mark.integration since it launches real apps/node.py
subprocesses that load YOLO weights; skips cleanly when those aren't
available locally (same guard as the other node-launching tests).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from starling_eval import runner


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
def test_local_runner_completes_and_writes_results(tmp_path: Path, synthetic_video: Path):
    scenario_dict = {
        "name": "smoke_test",
        "duration_s": 10,
        "stream_epoch": 0.0,
        "speed": 20.0,
        "nodes": [0],
        "videos": {0: str(synthetic_video)},
        "events": [],
    }
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(yaml.safe_dump(scenario_dict), encoding="utf-8")

    out_dir = tmp_path / "results" / "smoke"

    runner.main([str(scenario_path), "--local", "--out", str(out_dir), "--repeat", "1"])

    results_path = out_dir / "results.json"
    assert results_path.exists()

    results = json.loads(results_path.read_text(encoding="utf-8"))
    assert "system" in results
    assert "bytes_per_node_hour" in results["system"]
    assert "total_claims" in results["system"]
    assert "wall_clock_s" in results["system"]

    assert (out_dir / "results.md").exists()
    assert (out_dir / "timeline.jsonl").exists()
    assert (out_dir / "logs" / "node-00.jsonl").exists()
