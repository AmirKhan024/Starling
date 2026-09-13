"""Shared fixtures. Every later prompt depends on these existing.

None of these fixtures download model weights or a dataset — anything that
would need to is marked @pytest.mark.integration and must skip cleanly when
the dependency is absent.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from starling_node.config import NodeConfig


@pytest.fixture
def tmp_node_config(tmp_path: Path) -> NodeConfig:
    """A NodeConfig whose source video and DB live under tmp_path."""
    return NodeConfig(
        node_id=0,
        name="node-00",
        source=str(tmp_path / "cam0.mp4"),
        db_path=str(tmp_path / "local.db"),
    )


@pytest.fixture
def synthetic_video(tmp_path: Path) -> Path:
    """A 5s, 320x240, 25fps mp4 with a moving filled rectangle.

    Used for smoke tests that must not depend on real footage.
    """
    path = tmp_path / "synthetic.mp4"
    fps = 25
    duration_s = 5
    width, height = 320, 240
    n_frames = fps * duration_s
    rect_w, rect_h = 40, 40

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    try:
        for i in range(n_frames):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            x = int((width - rect_w) * (i / max(n_frames - 1, 1)))
            y = (height - rect_h) // 2
            cv2.rectangle(frame, (x, y), (x + rect_w, y + rect_h), (0, 255, 0), -1)
            writer.write(frame)
    finally:
        writer.release()

    return path


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(1234)


@pytest.fixture
def sample_embeddings() -> np.ndarray:
    """(10, 512) float32, L2-normalised. Rows 0-4 and rows 5-9 are two
    near-duplicate clusters, far apart from each other — enough to test
    matching logic without loading a model.
    """
    gen = np.random.default_rng(1234)
    dim = 512

    def _unit(v: np.ndarray) -> np.ndarray:
        return v / np.linalg.norm(v)

    base_a = _unit(gen.normal(size=dim))
    base_b = gen.normal(size=dim)
    base_b = base_b - base_a * float(base_a @ base_b)  # orthogonalize vs base_a
    base_b = _unit(base_b)

    rows = []
    for base in (base_a, base_b):
        for _ in range(5):
            noise = gen.normal(scale=0.02, size=dim)
            rows.append(_unit(base + noise))

    return np.array(rows, dtype=np.float32)
