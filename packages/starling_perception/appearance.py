"""starling_perception/appearance.py
-------------------------------------
A torch-free appearance signature for a person crop: the colour of their
clothing, body region by body region.

The crop is cut into `stripes` horizontal bands (hat/head, shoulders,
torso, hips, thighs, shins). Each band gets a hue histogram of its
chromatic pixels (weighted by saturation) plus a small value histogram of
its achromatic ones (black / dark / light / white), restricted to the
person's own pixels when a foreground mask is available and to the
central columns otherwise. Bands are normalised individually, square-
rooted (Hellinger) and the whole vector is L2-normalised, so the cosine
similarity of two signatures is in [0, 1].

This is the classic stripe-colour re-identification descriptor (the
family of ELF / SDALF-style hand-crafted features). It is far weaker than
a trained network in general, but it is honest, explainable ("same
orange vest, same blue jeans") and needs no GPU or weights — the right
tool for workers whose uniforms differ by colour. Its operating
threshold is not guessed: scripts/calibrate_world_appearance.py measures
same-person vs different-person similarity on live camera frames.
"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

DEFAULT_STRIPES = 6
DEFAULT_HUE_BINS = 12
DEFAULT_VALUE_BINS = 4
# A pixel is "chromatic" if saturation and brightness clear these (0-255 scale).
_SAT_MIN = 60
_VAL_MIN = 45
# Crops are resampled to this size before histogramming.
_CANON_H, _CANON_W = 128, 48
# Without a foreground mask, only this central fraction of columns is used.
_CENTRE_FRACTION = 0.56


def descriptor_dim(
    stripes: int = DEFAULT_STRIPES,
    hue_bins: int = DEFAULT_HUE_BINS,
    value_bins: int = DEFAULT_VALUE_BINS,
) -> int:
    return stripes * (hue_bins + value_bins)


def appearance_descriptor(
    crop_bgr: np.ndarray,
    fg_mask: Optional[np.ndarray] = None,
    stripes: int = DEFAULT_STRIPES,
    hue_bins: int = DEFAULT_HUE_BINS,
    value_bins: int = DEFAULT_VALUE_BINS,
) -> np.ndarray:
    dim = descriptor_dim(stripes, hue_bins, value_bins)
    if crop_bgr is None or crop_bgr.size == 0 or crop_bgr.shape[0] < 4 or crop_bgr.shape[1] < 2:
        return np.zeros(dim, dtype=np.float32)
    crop = cv2.resize(crop_bgr, (_CANON_W, _CANON_H), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0].astype(np.float32) * 2.0  # degrees
    s = hsv[..., 1].astype(np.float32)
    v = hsv[..., 2].astype(np.float32)

    if fg_mask is not None and fg_mask.size:
        mask = (
            cv2.resize(
                fg_mask.astype(np.uint8), (_CANON_W, _CANON_H), interpolation=cv2.INTER_NEAREST
            )
            > 0
        )
        if mask.mean() < 0.12:  # mask unusable (person absorbed into background, or no model yet)
            mask = None
    else:
        mask = None
    if mask is None:
        mask = np.zeros((_CANON_H, _CANON_W), dtype=bool)
        lo = int(round(_CANON_W * (1 - _CENTRE_FRACTION) / 2))
        mask[:, lo : _CANON_W - lo] = True

    chroma = (s >= _SAT_MIN) & (v >= _VAL_MIN)
    hue_idx = np.minimum((h / (360.0 / hue_bins)).astype(np.int32), hue_bins - 1)
    val_idx = np.minimum((v / (256.0 / value_bins)).astype(np.int32), value_bins - 1)

    out = np.zeros((stripes, hue_bins + value_bins), dtype=np.float32)
    edges = np.linspace(0, _CANON_H, stripes + 1).astype(int)
    for k in range(stripes):
        rows = slice(edges[k], edges[k + 1])
        m = mask[rows]
        c = chroma[rows] & m
        a = (~chroma[rows]) & m
        if c.any():
            np.add.at(out[k], hue_idx[rows][c], (s[rows][c] / 255.0))
        if a.any():
            np.add.at(out[k], hue_bins + val_idx[rows][a], 1.0)
        tot = out[k].sum()
        if tot > 0:
            out[k] /= tot
    vec = np.sqrt(out).ravel()
    n = float(np.linalg.norm(vec))
    return (vec / n).astype(np.float32) if n > 0 else vec.astype(np.float32)


def crop_quality(
    bbox: tuple[int, int, int, int],
    frame_shape: tuple[int, ...],
    ref_height_px: float = 110.0,
    edge_margin_px: int = 3,
) -> float:
    """[0.3, 1]: how much a crop can be trusted for appearance — mostly its
    size, and whether the person is cut off by the frame edge."""
    x1, y1, x2, y2 = bbox
    h = max(1.0, float(y2 - y1))
    q = min(1.0, h / ref_height_px)
    H, W = frame_shape[:2]
    if (
        x1 <= edge_margin_px
        or y1 <= edge_margin_px
        or x2 >= W - edge_margin_px
        or y2 >= H - edge_margin_px
    ):
        q *= 0.6
    return float(max(0.3, min(1.0, q)))
