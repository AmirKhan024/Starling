"""starling_perception/detector.py
-----------------------------------
Person detection, wrapping ultralytics YOLO restricted to the person class.

Part of the WP-01 perception-pipeline split: previously this logic was
inlined inside `CameraWorker._process_frame` in the pre-restructure V1
tracker. Detection is a plain per-frame forward pass with no temporal
state — tracking state lives in `tracker.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from ultralytics import YOLO

from starling_node.config import PerceptionConfig

PERSON_CLASS_ID = 0


@dataclass
class Detection:
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2, unclamped frame coords
    conf: float
    class_id: int


class PersonDetector:
    """Wraps ultralytics YOLO, person class only. Stateless across frames."""

    def __init__(self, cfg: PerceptionConfig) -> None:
        self.cfg = cfg
        self.model = YOLO(cfg.yolo_model)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        results = self.model(
            frame,
            classes=[PERSON_CLASS_ID],
            conf=self.cfg.conf,
            device=self.cfg.device,
            verbose=False,
        )
        r = results[0]
        detections: list[Detection] = []
        if r.boxes is not None:
            boxes = r.boxes.xyxy.cpu().numpy().astype(int)
            confs = r.boxes.conf.cpu().numpy()
            class_ids = r.boxes.cls.cpu().numpy().astype(int)
            for box, conf, class_id in zip(boxes, confs, class_ids):
                detections.append(Detection(
                    bbox=(int(box[0]), int(box[1]), int(box[2]), int(box[3])),
                    conf=float(conf),
                    class_id=int(class_id),
                ))
        return detections
