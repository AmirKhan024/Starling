"""starling_perception/pipeline.py
-----------------------------------
Single per-frame entry point for a node: detect -> track -> crop -> embed ->
quality, in one call. This is the WP-01 replacement for the inline
`CameraWorker._process_frame` logic that used to live in the pre-restructure
V1 tracker.

`NodePerception.__init__` takes `cfg: PerceptionConfig` (the perception
sub-model, not the whole `NodeConfig` — this class only ever touches
perception thresholds and has no need of net/match config) and `node_id`
so that logs and future claim construction can be tagged, per CLAUDE.md's
node-scoping rules. Detector/tracker/extractor may be injected (e.g. so a
caller wanting one shared YOLO/embedder instance across several
`NodePerception`s can do so); by default each instance builds its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from starling_node.config import PerceptionConfig
from starling_perception.detector import PersonDetector
from starling_perception.embedder import FeatureExtractor, quality
from starling_perception.tracker import LocalTracker

# Crops at or below this pixel area are too small to carry reliable
# appearance information and are dropped before embedding extraction.
_MIN_CROP_PIXELS = 100


@dataclass
class Observation:
    local_track_id: int
    bbox: tuple[int, int, int, int]  # clamped to frame bounds
    conf: float
    embedding: np.ndarray
    quality: float
    t_media: float
    crop: Optional[np.ndarray] = None  # NEVER serialised — raw video/crops
    # never cross the wire (CLAUDE.md rule 3).


class NodePerception:
    """Runs detect -> track -> crop -> embed -> quality for one frame."""

    def __init__(
        self,
        cfg: PerceptionConfig,
        node_id: int,
        detector: Optional[PersonDetector] = None,
        tracker: Optional[LocalTracker] = None,
        extractor: Optional[FeatureExtractor] = None,
    ) -> None:
        self.cfg = cfg
        self.node_id = node_id
        self.detector = detector or PersonDetector(cfg)
        self.tracker = tracker or LocalTracker(cfg)
        self.extractor = extractor or FeatureExtractor(
            backend=cfg.backend,
            weights_path=cfg.weights_path,
            device=cfg.device,
            batch_size=cfg.batch_size,
            embed_dim=cfg.embed_dim,
        )

    def process(self, frame: np.ndarray, t_media: float) -> list[Observation]:
        detections = self.detector.detect(frame)
        tracks = self.tracker.update(frame, detections)

        h, w = frame.shape[:2]
        crops = []
        valid = []
        for tr in tracks:
            x1, y1, x2, y2 = tr.bbox
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            crop = frame[y1:y2, x1:x2]
            if crop.size <= _MIN_CROP_PIXELS:
                continue
            crops.append(crop)
            valid.append((tr, (x1, y1, x2, y2), crop))

        embeddings = (
            self.extractor.extract(crops)
            if crops
            else np.empty((0, self.extractor.dim), dtype=np.float32)
        )

        observations = []
        for i, (tr, bbox, crop) in enumerate(valid):
            observations.append(Observation(
                local_track_id=tr.local_track_id,
                bbox=bbox,
                conf=tr.conf,
                embedding=embeddings[i],
                quality=quality(crop),
                t_media=t_media,
                crop=crop,
            ))
        return observations
