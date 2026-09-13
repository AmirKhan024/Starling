"""Smoke tests: the package imports, and the shared fixtures produce
what they claim. No model weights or datasets are touched here.
"""

import cv2
import numpy as np


def test_package_imports():
    import starling_perception  # noqa: F401
    import starling_store  # noqa: F401
    import starling_node  # noqa: F401
    import starling_net  # noqa: F401


def test_synthetic_video_is_readable_with_over_100_frames(synthetic_video):
    cap = cv2.VideoCapture(str(synthetic_video))
    try:
        assert cap.isOpened()
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        assert frame_count > 100
    finally:
        cap.release()


def test_sample_embeddings_rows_are_unit_norm(sample_embeddings):
    norms = np.linalg.norm(sample_embeddings, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)
