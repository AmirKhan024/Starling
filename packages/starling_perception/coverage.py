"""starling_perception/coverage.py
------------------------------------
Node coverage self-assessment (WP-09 Part 1, C4 flagship — the strongest
new idea in the project, and the one STARLING_BUILD_STATE.md §10 also
flags as genuinely uncertain: coverage self-assessment is itself a hard
perception problem). This module answers one question honestly: "what
could this node have seen?" — never "what did it see", which is the
detector/tracker's job.

Everything here is testable on synthetic frames (WP-09's own acceptance
rule) — no model weights, no real footage. `occlusion_ratio`'s dynamic-
occluder and unexplained-foreground components both work off a plain
`detections` list of duck-typed objects with a `.bbox` and an optional
`.class_id` (matching both `starling_perception.detector.Detection` and
`starling_perception.pipeline.Observation`, which are tracked people and
carry no `class_id` at all — they default to `PERSON_CLASS_ID` and are
therefore always "explained", never occlusion).

`PERSON_CLASS_ID` is duplicated here as a plain int rather than imported
from `starling_perception.detector` — that module imports `ultralytics`/
`torch`, and this one must stay importable and testable with neither
installed, per WP-09's own synthetic-frame acceptance rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np
from scipy import ndimage
from scipy.stats import ks_2samp
from shapely.geometry import Polygon
from shapely.ops import unary_union

from starling_geometry.calibration import CameraCalibration
from starling_geometry.navmesh import NavMesh
from starling_node.config import CoverageConfig

PERSON_CLASS_ID = 0


def _bbox_overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2


@dataclass
class DetectorStats:
    """Everything `detector_health` needs for one tick (WP-09 task 3).

    `recent_confidences`/`baseline_confidences`: detection-confidence
    samples for the KS-statistic drift check — a detector that is silently
    degrading (miscalibrated exposure, a partially failed sensor) shifts
    this distribution before it starts producing zero detections.
    """

    target_fps: float
    achieved_fps: float
    dropped: int  # starling_perception.source.PacedSource.dropped
    frames_read: int
    recent_confidences: Sequence[float] = field(default_factory=list)
    baseline_confidences: Sequence[float] = field(default_factory=list)


@dataclass
class CoverageState:
    occlusion_ratio: float
    illumination_score: float
    detector_health: float
    attest_confidence: float


class CoverageAssessor:
    """Per-node coverage self-assessment. Stateful across calls: an online
    background model (`occlusion_ratio`'s component (a)) accumulates from
    one `assess`/`occlusion_ratio` call to the next, so calls for the same
    node must be made in time order.

    `navmesh` is not read by any method in this class — none of the three
    self-assessment scores need it. It is kept as `self.navmesh` (alongside
    `self.calibration`) purely so a `starling_attest.attestation.Attestor`
    holding one `CoverageAssessor` has everything it needs to also detect
    boundary crossings (WP-09 Part 2) without a second, possibly-diverging
    navmesh/calibration reference of its own.
    """

    def __init__(self, cfg: CoverageConfig, calibration: CameraCalibration, navmesh: NavMesh) -> None:
        self.cfg = cfg
        self.calibration = calibration
        self.navmesh = navmesh
        self._roi_polygon: Optional[Polygon] = (
            Polygon(cfg.roi_polygon) if len(cfg.roi_polygon) >= 3 else None
        )
        self._roi_area_m2 = float(self._roi_polygon.area) if self._roi_polygon is not None else 0.0
        self._bg: Optional[np.ndarray] = None  # slow-moving grey background estimate

    # ── occlusion (WP-09 task 1) ──────────────────────────────────────────

    def occlusion_ratio(self, frame: np.ndarray, detections: Sequence[Any]) -> float:
        """Fraction of this node's ROI (floor projection) currently
        obscured, in [0, 1]. Three components, unioned in floor space:

        (a) static occlusion — an online, slowly-adapting (EMA,
            `cfg.background_alpha`) grey background model. Any foreground
            blob that survives many ticks without being absorbed into the
            background is a persistent occluder (a parked pallet).
        (b) dynamic occluders — entries in `detections` whose `.class_id`
            is one of `cfg.occluder_class_ids` (COCO car/truck/bench —
            forklift/pallet proxies), regardless of the background model.
        (c) unexplained foreground — any OTHER foreground blob (from the
            same background diff as (a)) at least `cfg.blob_area_threshold`
            pixels, that does not overlap any given detection's bbox. A
            blob overlapping a detection is "explained" (either a tracked
            person — never occlusion — or an occluder already counted by
            (b)) and is not double-counted here.

        Every occluding source is projected to floor metres by mapping its
        image bbox's four corners through `calibration.image_to_floor`
        (the bbox, not a single point, because an occluder's footprint is
        an area, unlike `bbox_floor_point`'s single foot-position use for a
        person). The union of all floor footprints is intersected with the
        ROI polygon; the ratio is that intersection's area over the ROI's
        own area.

        Ambiguous-choice note (CLAUDE.md: take the first option, comment,
        continue): the spec's (a) and (c) are both "foreground the
        background model doesn't explain" — the only difference is
        persistence, which is already captured by `background_alpha`
        (small = slow absorption = a real static occluder stays flagged
        for many ticks; a momentary lighting flicker gets absorbed and
        stops being flagged). They therefore share one code path here
        instead of two near-duplicate ones.
        """
        if self._roi_polygon is None or self._roi_area_m2 <= 0:
            # No ROI configured: nothing to protect, so nothing is occluded
            # — this mirrors the rest of the module degrading to a safe,
            # non-attesting default rather than guessing (see CoverageConfig
            # docstring).
            return 0.0

        gray = frame.astype(np.float32)
        if gray.ndim == 3:
            gray = gray.mean(axis=2)

        footprints: list[Polygon] = []
        all_boxes = [tuple(getattr(d, "bbox")) for d in detections]

        # (b) dynamic occluders.
        for det, bbox in zip(detections, all_boxes):
            class_id = getattr(det, "class_id", PERSON_CLASS_ID)
            if class_id in self.cfg.occluder_class_ids:
                fp = self._floor_footprint(bbox)
                if fp is not None:
                    footprints.append(fp)

        if self._bg is None:
            # First frame this assessor has ever seen: nothing to diff
            # against yet. This is the "online" model building up state,
            # not a false all-clear — a genuinely occluded first frame
            # only starts being flagged from the next call onward.
            self._bg = gray.copy()
        else:
            diff = np.abs(gray - self._bg)
            foreground = diff > self.cfg.bg_diff_threshold
            labelled, n_blobs = ndimage.label(foreground)
            if n_blobs:
                for idx, sl in enumerate(ndimage.find_objects(labelled), start=1):
                    if sl is None:
                        continue
                    area_px = int(np.count_nonzero(labelled[sl] == idx))
                    if area_px < self.cfg.blob_area_threshold:
                        continue
                    y0, y1 = sl[0].start, sl[0].stop
                    x0, x1 = sl[1].start, sl[1].stop
                    blob_bbox = (float(x0), float(y0), float(x1), float(y1))
                    if any(_bbox_overlaps(blob_bbox, b) for b in all_boxes):
                        continue  # (c) excludes anything already explained
                    fp = self._floor_footprint(blob_bbox)
                    if fp is not None:
                        footprints.append(fp)

            self._bg = (1 - self.cfg.background_alpha) * self._bg + self.cfg.background_alpha * gray

        if not footprints:
            return 0.0

        occluded = unary_union(footprints).intersection(self._roi_polygon)
        return float(np.clip(occluded.area / self._roi_area_m2, 0.0, 1.0))

    def _floor_footprint(self, bbox: tuple[float, float, float, float]) -> Optional[Polygon]:
        x1, y1, x2, y2 = bbox
        try:
            corners = [
                self.calibration.image_to_floor(x1, y1),
                self.calibration.image_to_floor(x2, y1),
                self.calibration.image_to_floor(x2, y2),
                self.calibration.image_to_floor(x1, y2),
            ]
        except ValueError:
            return None
        poly = Polygon(corners)
        if not poly.is_valid or poly.area <= 0:
            return None
        return poly

    # ── illumination (WP-09 task 2) ───────────────────────────────────────

    def illumination_score(self, frame: np.ndarray) -> float:
        """[0, 1], documented blend of three components (every weight and
        bound lives in `CoverageConfig`, never hardcoded here):

            score = w_exposure   * exposure_score
                  + w_clip       * (1 - clipped_fraction)
                  + w_contrast   * min(local_rms_contrast / contrast_norm, 1)

        `exposure_score = 1 - 2*|mean_luma/255 - 0.5|`: a uniformly dark
        frame (mean luma near 0) and a blown-out one (near 255) both score
        near 0; a mid-grey frame scores near 1.
        `clipped_fraction`: fraction of pixels below `illum_clip_low` or
        above `illum_clip_high`.
        `local_rms_contrast`: mean local standard deviation over a 7x7
        window (fast separable box-filter moments, not a per-pixel Python
        loop), normalised by `illum_contrast_norm`.
        """
        gray = frame.astype(np.float32)
        if gray.ndim == 3:
            gray = gray.mean(axis=2)

        mean_luma = float(gray.mean()) if gray.size else 0.0
        exposure_score = float(np.clip(1.0 - 2.0 * abs(mean_luma / 255.0 - 0.5), 0.0, 1.0))

        clipped = (gray < self.cfg.illum_clip_low) | (gray > self.cfg.illum_clip_high)
        clipped_fraction = float(np.count_nonzero(clipped)) / gray.size if gray.size else 0.0
        clip_score = float(np.clip(1.0 - clipped_fraction, 0.0, 1.0))

        window = 7
        local_mean = ndimage.uniform_filter(gray, size=window)
        local_mean_sq = ndimage.uniform_filter(gray ** 2, size=window)
        local_var = np.clip(local_mean_sq - local_mean ** 2, 0.0, None)
        local_rms_contrast = float(np.sqrt(local_var).mean()) if gray.size else 0.0
        contrast_score = float(np.clip(local_rms_contrast / self.cfg.illum_contrast_norm, 0.0, 1.0))

        score = (
            self.cfg.illum_exposure_weight * exposure_score
            + self.cfg.illum_clip_weight * clip_score
            + self.cfg.illum_contrast_weight * contrast_score
        )
        return float(np.clip(score, 0.0, 1.0))

    # ── detector health (WP-09 task 3) ────────────────────────────────────

    def detector_health(self, stats: DetectorStats) -> float:
        """[0, 1], the unweighted average of three already-normalised
        components: achieved/target FPS ratio, `1 - dropped-frame ratio`
        (`starling_perception.source.PacedSource.dropped`), and a
        KS-statistic-based score comparing the recent detection-confidence
        distribution to a rolling baseline (a detector silently degrading
        shifts this distribution before it drops to zero detections). An
        unweighted average is used rather than three more config knobs
        because all three are already on the same [0,1]=healthy scale.
        """
        fps_ratio = (
            float(np.clip(stats.achieved_fps / stats.target_fps, 0.0, 1.0))
            if stats.target_fps > 0
            else 0.0
        )

        total = stats.dropped + stats.frames_read
        dropped_ratio = stats.dropped / total if total > 0 else 0.0
        drop_score = float(np.clip(1.0 - dropped_ratio, 0.0, 1.0))

        if len(stats.recent_confidences) >= 2 and len(stats.baseline_confidences) >= 2:
            ks_stat, _ = ks_2samp(list(stats.recent_confidences), list(stats.baseline_confidences))
            ks_score = float(np.clip(1.0 - ks_stat, 0.0, 1.0))
        else:
            # Not enough samples yet to compare distributions: assume
            # healthy rather than penalising a freshly-started node for
            # lacking history.
            ks_score = 1.0

        return float(np.clip((fps_ratio + drop_score + ks_score) / 3.0, 0.0, 1.0))

    # ── combined assessment ───────────────────────────────────────────────

    def assess(self, frame: np.ndarray, detections: Sequence[Any], stats: DetectorStats) -> CoverageState:
        occl = self.occlusion_ratio(frame, detections)
        illum = self.illumination_score(frame)
        health = self.detector_health(stats)
        # Safety-critical line (CLAUDE.md rule 7 / STARLING_BUILD_STATE.md
        # WP-09 task 4): the MINIMUM, not the mean — a node is only as
        # trustworthy as its worst faculty.
        attest_confidence = min(1.0 - occl, illum, health)
        return CoverageState(
            occlusion_ratio=occl,
            illumination_score=illum,
            detector_health=health,
            attest_confidence=attest_confidence,
        )
