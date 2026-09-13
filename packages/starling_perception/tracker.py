"""starling_perception/tracker.py
----------------------------------
Per-camera local tracking, wrapping ultralytics ByteTrack via
`model.track(persist=True)`.

Part of the WP-01 perception-pipeline split (see detector.py, pipeline.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from ultralytics import YOLO

from starling_node.config import PerceptionConfig
from starling_perception.detector import PERSON_CLASS_ID, Detection, resolve_device


@dataclass
class Track:
    local_track_id: int
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2, unclamped frame coords
    conf: float
    age: int
    hits: int


class LocalTracker:
    """Wraps ultralytics YOLO + ByteTrack (`model.track(persist=True)`).

    `local_track_id` is NODE-SCOPED ONLY. It is an artifact of this one
    process's ByteTrack instance and carries no meaning to any other node.
    It must never be transmitted over gossip or interpreted as identity —
    that is CLAUDE.md rule 5 / STARLING_BUILD_STATE.md §5.1: identity
    assignments are never replicated, only signed observation claims are,
    and cross-node identity exists only as a resolver output over those
    claims. Confusing a local_track_id for identity is the exact mistake
    the CRDT design in WP-06 exists to make structurally impossible.
    """

    def __init__(self, cfg: PerceptionConfig) -> None:
        self.cfg = cfg
        self.device = resolve_device(cfg.device)
        self.model = YOLO(cfg.yolo_model)
        self._hits: dict[int, int] = {}

    def update(self, frame: np.ndarray, detections: list[Detection]) -> list[Track]:
        # `detections` is accepted for interface symmetry with
        # PersonDetector.detect(), but ultralytics' persist=True tracker
        # performs its own detection internally from `frame` — there is no
        # supported way to feed it externally-computed boxes without
        # reimplementing ByteTrack's association step by hand. Ambiguous
        # design choice (CLAUDE.md: take the first option named, comment,
        # continue): `detections` is unused here.
        del detections
        results = self.model.track(
            frame,
            persist=True,
            classes=[PERSON_CLASS_ID],
            conf=self.cfg.conf,
            tracker="bytetrack.yaml",
            verbose=False,
            device=self.device,
        )
        r = results[0]
        tracks: list[Track] = []
        if r.boxes is not None and r.boxes.id is not None:
            boxes = r.boxes.xyxy.cpu().numpy().astype(int)
            ids = r.boxes.id.cpu().numpy().astype(int)
            confs = r.boxes.conf.cpu().numpy()
            for box, track_id, conf in zip(boxes, ids, confs):
                track_id = int(track_id)
                self._hits[track_id] = self._hits.get(track_id, 0) + 1
                tracks.append(Track(
                    local_track_id=track_id,
                    bbox=(int(box[0]), int(box[1]), int(box[2]), int(box[3])),
                    conf=float(conf),
                    age=self._hits[track_id],
                    hits=self._hits[track_id],
                ))
        return tracks
