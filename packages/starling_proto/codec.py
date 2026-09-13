"""starling_proto/codec.py
---------------------------
Symmetric per-vector int8 quantisation for embeddings on the wire.

512 float32 values (2048 B) would blow IdentityClaim's 1-4 KB budget on
their own. Quantised to int8 with one shared scale factor, the same vector
is 512 B + 4 B for the scale — comfortably inside budget, at a cosine-error
cost this module's own test keeps under 0.01 for unit vectors.
"""

from __future__ import annotations

import numpy as np

_INT8_MAX = 127


def quantise(vec: np.ndarray) -> tuple[bytes, float]:
    """Symmetric per-vector int8 quantisation. Returns (bytes, scale).

    `scale = max(abs(vec)) / 127`; each component is `round(v / scale)`,
    clipped to int8 range. `scale == 0` (an all-zero vector) is encoded as
    scale `1.0` with an all-zero byte string, so dequantise never divides
    by zero.
    """
    vec = np.asarray(vec, dtype=np.float32)
    max_abs = float(np.max(np.abs(vec))) if vec.size else 0.0

    if max_abs == 0.0:
        return bytes(vec.size), 1.0

    scale = max_abs / _INT8_MAX
    quantised = np.clip(np.round(vec / scale), -_INT8_MAX, _INT8_MAX).astype(np.int8)
    return quantised.tobytes(), scale


def dequantise(b: bytes, scale: float) -> np.ndarray:
    """Returns an L2-normalised float32 vector."""
    quantised = np.frombuffer(b, dtype=np.int8).astype(np.float32)
    vec = quantised * scale
    norm = np.linalg.norm(vec)
    if norm > 1e-9:
        vec = vec / norm
    return vec.astype(np.float32)
