"""Tests for starling_perception.pipeline.NodePerception.

Anything requiring YOLO weights is marked @pytest.mark.integration and
skips cleanly when the weights file isn't present locally — this suite
never attempts a network download.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from starling_node.config import PerceptionConfig
from starling_perception.pipeline import NodePerception

_WEIGHTS_NAME = "yolov8n.pt"


def _yolo_weights_available() -> bool:
    try:
        from ultralytics.utils import SETTINGS
        weights_dir = Path(SETTINGS.get("weights_dir", "weights"))
    except Exception:
        weights_dir = Path("weights")
    candidates = [Path.cwd() / _WEIGHTS_NAME, weights_dir / _WEIGHTS_NAME]
    return any(p.exists() for p in candidates)


@pytest.mark.integration
@pytest.mark.skipif(not _yolo_weights_available(), reason="YOLO weights not available locally")
def test_node_perception_process_returns_valid_observations(synthetic_video):
    cfg = PerceptionConfig(backend="pooled")
    perception = NodePerception(cfg, node_id=0)

    cap = cv2.VideoCapture(str(synthetic_video))
    try:
        ret, frame = cap.read()
    finally:
        cap.release()
    assert ret

    t_media = 1.23
    observations = perception.process(frame, t_media=t_media)

    for obs in observations:
        assert obs.t_media == t_media
        assert 0.0 <= obs.quality <= 1.0
        norm = np.linalg.norm(obs.embedding)
        assert abs(norm - 1.0) < 1e-4
