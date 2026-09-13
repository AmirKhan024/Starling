"""starling_perception/embedder.py
----------------------------------
Appearance-embedding backends for person re-identification.

Fixes D-01 (STARLING_BUILD_STATE.md §2): the original ``ReIDNet`` bolted a
randomly-initialised, never-trained ``Linear(576→512) + BatchNorm1d`` head
onto an ImageNet backbone. ``pretrained=True`` only ever affected the
backbone; in ``.eval()`` mode the untrained BatchNorm used its untrained
running stats (mean 0, var 1), so cosine similarity on the output was close
to meaningless and the 0.60 match threshold was arbitrary.

Three backends are selectable behind the same interface:

  osnet      (default)  OSNet trained on Market-1501, loaded via torchreid
                         if importable, else from a local state_dict/ONNX
                         file named by ``weights_path``. Falls back to
                         ``pooled`` (never to ``v1_broken``) if it cannot be
                         loaded, with a logged warning.
  pooled     (fallback) MobileNetV3-Small ImageNet backbone, globally
                         pooled, L2-normalised, no trainable head at all.
                         Worse than a properly trained ReID model, but
                         correct — unlike the original head.
  v1_broken             The original untrained-head implementation,
                         preserved verbatim so the Market-1501 benchmark in
                         starling_eval.reid_benchmark can measure the exact
                         cost of D-01. NEVER use this in a production
                         config; it exists purely for benchmarking, and
                         apps/baseline.py is the only sanctioned caller
                         (STARLING_BUILD_STATE.md: baseline is the frozen
                         V1 control condition, so it intentionally keeps the
                         original broken algorithm rather than the fix).
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as tv_models
import torchvision.transforms as T

from starling_net.logging import get_logger

logger = get_logger(__name__)

VALID_BACKENDS = ("osnet", "pooled", "v1_broken")

_REID_TRANSFORM = T.Compose([
    T.ToPILImage(),
    T.Resize((256, 128)),
    T.ToTensor(),
    T.Normalize(mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]),
])

_V1_BROKEN_WARNING = (
    "backend='v1_broken' selected: this is the untrained-head embedder "
    "preserved to measure defect D-01. Its output is a random linear "
    "projection of ImageNet features and is NOT meaningful for identity "
    "matching. Never select it in a production node config."
)


# ── crop quality ─────────────────────────────────────────────────────────────

_REFERENCE_HEIGHT_PX = 256.0
_BLUR_NORM_CONST = 500.0
_ASPECT_TARGET = 2.2
_ASPECT_TOLERANCE = 1.2


def quality(crop: np.ndarray) -> float:
    """Crop quality score in [0, 1].

    ``quality = 0.4 * blur_score + 0.3 * size_score + 0.3 * plausibility_score``

    - blur_score: variance of the Laplacian of the grayscale crop, divided
      by ``_BLUR_NORM_CONST`` and clipped to [0, 1]. A sharp crop has a
      high-variance Laplacian; a blurred one is near-flat.
    - size_score: crop pixel height divided by a reference height
      (``_REFERENCE_HEIGHT_PX``), clipped to [0, 1]. Penalises crops too
      small to carry reliable appearance information.
    - plausibility_score: ``1 - |aspect - _ASPECT_TARGET| / _ASPECT_TOLERANCE``,
      clipped to [0, 1], where ``aspect = height / width``. Penalises boxes
      that don't look like a standing person (too square, too wide).
    """
    if crop is None or crop.size == 0:
        return 0.0
    h, w = crop.shape[:2]
    if h == 0 or w == 0:
        return 0.0

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    blur_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    blur_score = float(np.clip(blur_var / _BLUR_NORM_CONST, 0.0, 1.0))

    size_score = float(np.clip(h / _REFERENCE_HEIGHT_PX, 0.0, 1.0))

    aspect = h / w
    plausibility_score = float(
        np.clip(1.0 - abs(aspect - _ASPECT_TARGET) / _ASPECT_TOLERANCE, 0.0, 1.0)
    )

    return 0.4 * blur_score + 0.3 * size_score + 0.3 * plausibility_score


# ── shared preprocessing ─────────────────────────────────────────────────────

def _resolve_device(device: str) -> torch.device:
    if device == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device)


def _crops_to_batch(crops: List[np.ndarray]) -> torch.Tensor:
    tensors = []
    for crop in crops:
        if crop is None or crop.size == 0:
            tensors.append(torch.zeros(3, 256, 128))
            continue
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        tensors.append(_REID_TRANSFORM(rgb))
    return torch.stack(tensors)


# ── pooled backend (fallback, correct-by-construction) ──────────────────────

class _PooledBackbone(nn.Module):
    """MobileNetV3-Small ImageNet backbone, globally pooled. No trainable head."""

    dim = 576

    def __init__(self) -> None:
        super().__init__()
        weights = tv_models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
        backbone = tv_models.mobilenet_v3_small(weights=weights)
        self.features = backbone.features
        self.pool = backbone.avgpool

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        x = self.pool(x).flatten(1)
        return F.normalize(x, p=2, dim=1)


class _PooledImpl:
    dim = _PooledBackbone.dim

    def __init__(self, device: torch.device, batch_size: int) -> None:
        self.device = device
        self.batch_size = batch_size
        self.model = _PooledBackbone().to(device).eval()

    @torch.no_grad()
    def extract(self, crops: List[np.ndarray]) -> np.ndarray:
        if not crops:
            return np.empty((0, self.dim), dtype=np.float32)
        tensors = _crops_to_batch(crops)
        feats = []
        for i in range(0, len(tensors), self.batch_size):
            batch = tensors[i:i + self.batch_size].to(self.device)
            feats.append(self.model(batch).cpu().numpy())
        return np.vstack(feats).astype(np.float32)


# ── osnet backend (default; requires torchreid + Market-1501 weights) ───────

class _OSNetImpl:
    dim = 512

    def __init__(self, model: nn.Module, device: torch.device, batch_size: int) -> None:
        self.model = model.to(device).eval()
        self.device = device
        self.batch_size = batch_size

    @torch.no_grad()
    def extract(self, crops: List[np.ndarray]) -> np.ndarray:
        if not crops:
            return np.empty((0, self.dim), dtype=np.float32)
        tensors = _crops_to_batch(crops)
        feats = []
        for i in range(0, len(tensors), self.batch_size):
            batch = tensors[i:i + self.batch_size].to(self.device)
            out = self.model(batch)
            feats.append(F.normalize(out, p=2, dim=1).cpu().numpy())
        return np.vstack(feats).astype(np.float32)


def _try_load_osnet(weights_path: Optional[str], device: torch.device,
                     batch_size: int) -> Optional[_OSNetImpl]:
    """Attempt to build a Market-1501-trained OSNet. Return None on any
    failure so the caller falls back to `pooled` — never to `v1_broken`.
    """
    if weights_path is None:
        logger.warning(
            "osnet backend requested but no weights_path configured; "
            "falling back to pooled backend"
        )
        return None

    path = Path(weights_path)
    if not path.exists():
        logger.warning(
            "osnet weights_path does not exist; falling back to pooled backend",
            weights_path=str(path),
        )
        return None

    if path.suffix == ".onnx":
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            logger.warning(
                "onnxruntime not importable; cannot load osnet ONNX weights, "
                "falling back to pooled backend"
            )
            return None
        logger.warning(
            "osnet ONNX loading is not yet implemented in this build; "
            "falling back to pooled backend"
        )
        return None

    try:
        import torchreid
    except ImportError:
        logger.warning(
            "torchreid not importable; cannot load osnet state_dict, "
            "falling back to pooled backend"
        )
        return None

    try:
        model = torchreid.models.build_model(
            name="osnet_x1_0", num_classes=1, pretrained=False, loss="softmax"
        )
        state = torch.load(path, map_location=device)
        state = state.get("state_dict", state) if isinstance(state, dict) else state
        model.load_state_dict(state, strict=False)
        model.classifier = nn.Identity()
    except Exception:  # noqa: BLE001 — any load failure must fall back, not crash
        logger.warning(
            "failed to load osnet weights; falling back to pooled backend",
            weights_path=str(path),
        )
        return None

    return _OSNetImpl(model, device, batch_size)


# ── v1_broken backend (preserved verbatim, benchmarking only) ───────────────

class _EmbeddingHeadV1Broken(nn.Module):
    def __init__(self, in_features: int = 576, embed_dim: int = 512) -> None:
        super().__init__()
        self.fc = nn.Sequential(
            nn.Linear(in_features, embed_dim),
            nn.BatchNorm1d(embed_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.fc(x), p=2, dim=1)


class _ReIDNetV1Broken(nn.Module):
    """D-01: this head is randomly initialised and never trained. Kept
    exactly as V1 shipped it, for benchmarking purposes only.
    """

    BACKBONE_OUT = 576

    def __init__(self, embed_dim: int = 512, pretrained: bool = True) -> None:
        super().__init__()
        weights = tv_models.MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained else None
        backbone = tv_models.mobilenet_v3_small(weights=weights)
        self.features = backbone.features
        self.pool = backbone.avgpool
        self.head = _EmbeddingHeadV1Broken(self.BACKBONE_OUT, embed_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        x = self.pool(x).flatten(1)
        return self.head(x)


class _V1BrokenImpl:
    def __init__(self, embed_dim: int, weights_path: Optional[str],
                 device: torch.device, batch_size: int) -> None:
        self.dim = embed_dim
        self.device = device
        self.batch_size = batch_size
        self.model = _ReIDNetV1Broken(embed_dim=embed_dim, pretrained=(weights_path is None))

        if weights_path and Path(weights_path).exists():
            ckpt = torch.load(weights_path, map_location=device)
            state = ckpt.get("model_state", ckpt) if isinstance(ckpt, dict) else ckpt
            self.model.load_state_dict(state, strict=False)
            logger.warning("v1_broken loaded weights", weights_path=weights_path)
        else:
            logger.warning("v1_broken using untrained random head over ImageNet backbone")

        self.model.to(device).eval()

    @torch.no_grad()
    def extract(self, crops: List[np.ndarray]) -> np.ndarray:
        if not crops:
            return np.empty((0, self.dim), dtype=np.float32)
        tensors = _crops_to_batch(crops)
        feats = []
        for i in range(0, len(tensors), self.batch_size):
            batch = tensors[i:i + self.batch_size].to(self.device)
            feats.append(self.model(batch).cpu().numpy())
        return np.vstack(feats).astype(np.float32)


# ── public interface ─────────────────────────────────────────────────────────

class FeatureExtractor:
    """Extracts L2-normalised appearance embeddings from person crops.

    Interface is stable across backends: ``extract`` / ``extract_single`` /
    ``dim``. Everything downstream reads ``.dim`` rather than assuming 512.
    """

    def __init__(
        self,
        backend: str = "osnet",
        weights_path: Optional[str] = None,
        device: str = "auto",
        batch_size: int = 8,
        embed_dim: int = 512,
    ) -> None:
        if backend not in VALID_BACKENDS:
            raise ValueError(
                f"Unknown backend {backend!r}; must be one of {VALID_BACKENDS}"
            )

        self.device = _resolve_device(device)
        self.batch_size = batch_size
        self.requested_backend = backend

        if backend == "v1_broken":
            warnings.warn(_V1_BROKEN_WARNING, RuntimeWarning, stacklevel=2)
            logger.warning(_V1_BROKEN_WARNING)
            self._impl = _V1BrokenImpl(embed_dim, weights_path, self.device, batch_size)
            self.backend = "v1_broken"

        elif backend == "osnet":
            impl = _try_load_osnet(weights_path, self.device, batch_size)
            if impl is None:
                self._impl = _PooledImpl(self.device, batch_size)
                self.backend = "pooled"
            else:
                self._impl = impl
                self.backend = "osnet"

        else:  # "pooled"
            self._impl = _PooledImpl(self.device, batch_size)
            self.backend = "pooled"

        self.dim = self._impl.dim

    def extract(self, crops: List[np.ndarray]) -> np.ndarray:
        return self._impl.extract(crops)

    def extract_single(self, crop: np.ndarray) -> Optional[np.ndarray]:
        if crop is None or crop.size == 0:
            return None
        return self.extract([crop])[0]
