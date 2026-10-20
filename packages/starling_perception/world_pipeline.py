"""starling_perception/world_pipeline.py
-----------------------------------------
Perception for a node whose camera is one of the live 3D world's virtual
cameras. It sees only JPEG frames — the same thing a physical camera
delivers — and works everything out from pixels:

  1. person detection + local tracking: YOLOv8 (COCO "person") with
     ByteTrack, one forward pass per frame;
  2. floor position: the bbox's foot point through this camera's
     calibrated floor homography (`CameraCalibration.image_to_floor`),
     lightly smoothed per track, with `position_sigma` as its uncertainty;
  3. appearance signature: the stripe-colour descriptor
     (`starling_perception.appearance`) on the person's own pixels, picked
     out by a slow background model of this static camera;
  4. at the entrance gate only: employee verification — the track's
     signatures from several frames are matched against the enrolled
     registry (`starling_perception.registry`); a confident, unambiguous
     match turns that observation into a FACE_ANCHOR claim for the
     employee's id. One anchor per pass through the gate.

Local track ids are node-scoped and never identities (CLAUDE.md rule 5):
cross-camera identity is still only ever the resolver's output over the
merged, gossiped claim set.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import cv2
import numpy as np
from shapely.geometry import Point
from shapely.prepared import prep
from starling_geometry.calibration import CameraCalibration, bbox_floor_point
from starling_net.logging import get_logger
from starling_node.config import PerceptionConfig, WorldNodeConfig

from starling_perception.appearance import appearance_descriptor, crop_quality
from starling_perception.registry import EmployeeRegistry

PERSON_CLASS_ID = 0
_log = get_logger(__name__)
# A track not updated for this long (media s) is forgotten.
_TRACK_FORGET_S = 20.0
# A smoothed position that jumps further than this restarts from the raw one.
_SMOOTH_RESET_M = 1.5
# Gate decisions use at most this many of the track's latest signatures.
_GATE_WINDOW = 8
_PREVIEW_W, _PREVIEW_H = 640, 360


def foreground_mask(
    small: np.ndarray,
    bg_small: Optional[np.ndarray],
    box_small: tuple[int, int, int, int],
    threshold: float,
) -> Optional[np.ndarray]:
    """The person's own pixels inside `box_small`: where the half-resolution
    frame differs from this static camera's background model."""
    if bg_small is None:
        return None
    x1, y1, x2, y2 = box_small
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    diff = np.abs(small[y1:y2, x1:x2].astype(np.float32) - bg_small[y1:y2, x1:x2]).sum(axis=2)
    return diff > threshold


def person_descriptor(
    frame: np.ndarray,
    small: np.ndarray,
    bg_small: Optional[np.ndarray],
    bbox: tuple[int, int, int, int],
    fg_threshold: float,
) -> np.ndarray:
    """Appearance signature of the person in `bbox` — the one function both a
    live node and the offline enrollment use, so their signatures agree."""
    x1, y1, x2, y2 = bbox
    mask = foreground_mask(small, bg_small, (x1 // 2, y1 // 2, x2 // 2, y2 // 2), fg_threshold)
    return appearance_descriptor(frame[y1:y2, x1:x2], mask)


def floor_from_head(
    calib: CameraCalibration, bbox: tuple[int, int, int, int], top_height_m: float
) -> Optional[tuple[float, float]]:
    """Floor position from the TOP of a person's box: the ray through the
    head pixel meets the plane z = `top_height_m`. Needs the camera's full
    pose (R, t), which a calibrated world camera has; None otherwise."""
    if calib.R is None or calib.t is None:
        return None
    u, v = (bbox[0] + bbox[2]) / 2.0, float(bbox[1])
    r = np.asarray(calib.R, dtype=float)
    centre = -r.T @ np.asarray(calib.t, dtype=float).ravel()
    ray = r.T @ (np.linalg.inv(np.asarray(calib.K, dtype=float)) @ np.array([u, v, 1.0]))
    if ray[2] >= -1e-6 or centre[2] <= top_height_m:
        return None
    s_ = (top_height_m - centre[2]) / ray[2]
    return float(centre[0] + s_ * ray[0]), float(centre[1] + s_ * ray[1])


def expected_box_height_px(
    calib: CameraCalibration, x: float, y: float, top_height_m: float
) -> Optional[float]:
    """Pixel height a standing person at floor (x, y) would have in this
    camera (foot to top of head), from its full pose; None without one."""
    if calib.R is None or calib.t is None:
        return None
    r = np.asarray(calib.R, dtype=float)
    t = np.asarray(calib.t, dtype=float).ravel()
    k = np.asarray(calib.K, dtype=float)
    vs = []
    for z in (0.0, top_height_m):
        pc = r @ np.array([x, y, z]) + t
        if pc[2] <= 1e-6:
            return None
        vs.append((k @ (pc / pc[2]))[1])
    return float(vs[0] - vs[1])


def locate_person(
    calib: CameraCalibration,
    bbox: tuple[int, int, int, int],
    frame_h: int,
    top_height_m: float,
    min_height_ratio: float,
) -> tuple[tuple[float, float], float, bool]:
    """(floor position, sigma, feet_hidden) of a detected person. Normally the
    foot point through the floor homography. But when the feet are hidden (a
    pallet, a table, the frame edge) the box ends at the knees — it is
    clearly SHORTER than a standing person at its foot point would be — and
    its foot point lies too far away; then the head-based position is used
    and sigma widens by the disagreement."""
    foot = calib.image_to_floor(*bbox_floor_point(bbox))
    sigma = float(calib.position_sigma(bbox))
    expected = expected_box_height_px(calib, foot[0], foot[1], top_height_m)
    cut = bbox[3] >= frame_h - 2
    short = (
        expected is not None and expected > 0 and (bbox[3] - bbox[1]) < min_height_ratio * expected
    )
    if not (cut or short):
        return foot, sigma, False
    head = floor_from_head(calib, bbox, top_height_m)
    if head is None:
        return foot, sigma, False
    gap = math.hypot(head[0] - foot[0], head[1] - foot[1])
    return head, max(sigma, gap / 2.0), True


def half(frame: np.ndarray) -> np.ndarray:
    return cv2.resize(
        frame, (frame.shape[1] // 2, frame.shape[0] // 2), interpolation=cv2.INTER_AREA
    )


@dataclass
class WorldObservation:
    """Duck-types `starling_perception.pipeline.Observation` for
    `LocalStore.append_local_observation` and the coverage assessor."""

    local_track_id: int
    bbox: tuple[int, int, int, int]
    conf: float
    embedding: np.ndarray
    quality: float
    t_media: float
    world_pos: tuple[float, float]
    pos_sigma: float
    anchor_identity: Optional[str] = None
    class_id: int = PERSON_CLASS_ID
    claimable: bool = True


@dataclass
class _Track:
    pos: Optional[tuple[float, float]] = None
    last_t: float = 0.0
    gate_descs: deque = field(default_factory=lambda: deque(maxlen=_GATE_WINDOW))
    gate_frames: int = 0
    gate_state: str = "none"  # none | checking | verified | unverified
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    score: float = 0.0
    second: float = 0.0
    best_id: Optional[str] = None
    recent_descs: deque = field(default_factory=lambda: deque(maxlen=_GATE_WINDOW))
    last_recognised_t: float = -1e9


class WorldPerception:
    def __init__(
        self,
        cfg: PerceptionConfig,
        world: WorldNodeConfig,
        calib: CameraCalibration,
        node_id: int,
        zone_geom: Any = None,  # this camera's zone (shapely); None = no claim-area limit
        floor_bounds: Optional[tuple[float, float, float, float]] = None,
        registry: Optional[EmployeeRegistry] = None,
        model: Any = None,
    ) -> None:
        self.cfg = cfg
        self.world = world
        self.calib = calib
        self.node_id = node_id
        self.registry = registry
        self.floor_bounds = floor_bounds
        self._claim_area = (
            prep(zone_geom.buffer(world.claim_zone_margin_m))
            if zone_geom is not None and not zone_geom.is_empty
            else None
        )
        self._zone_geom = zone_geom
        if model is None:
            import torch
            from ultralytics import YOLO

            torch.set_num_threads(max(1, world.torch_threads))
            model = YOLO(cfg.yolo_model)
        self.model = model
        self.tracks: dict[int, _Track] = {}
        self._bg: Optional[np.ndarray] = None
        self._last_anchor_by_emp: dict[str, float] = {}  # any anchor (rate-limits recognition)
        self._last_checkin_by_emp: dict[str, float] = {}  # gate check-ins (one per pass)
        self.events: deque = deque(maxlen=20)
        self.frames = 0
        self.last_ms = 0.0
        self._lock = threading.Lock()
        self._last_frame: Optional[np.ndarray] = None
        self._last_obs: list[WorldObservation] = []
        self._last_t = 0.0
        self._preview_cache: tuple[int, bytes] = (-1, b"")
        self.extra_status: dict[str, Any] = {}
        self._warm_up()

    def _warm_up(self) -> None:
        """First ultralytics call builds/fuses the model lazily — do it now,
        single-threaded, not on the first real frame (see NodePerception._warm_up)."""
        self.model.predict(
            np.zeros((64, 64, 3), dtype=np.uint8), classes=[PERSON_CLASS_ID], verbose=False
        )

    # ── background model (for the person's foreground mask) ───────────

    def _update_background(
        self, small: np.ndarray, boxes_small: list[tuple[int, int, int, int]]
    ) -> None:
        f = small.astype(np.float32)
        if self._bg is None:
            self._bg = f
            return
        keep = np.ones(small.shape[:2], dtype=bool)
        for x1, y1, x2, y2 in boxes_small:
            keep[max(0, y1) : max(0, y2), max(0, x1) : max(0, x2)] = False
        a = self.world.bg_alpha
        upd = (1 - a) * self._bg + a * f
        self._bg[keep] = upd[keep]

    # ── per frame ──────────────────────────────────────────────────────

    def _in_bounds(self, xy: tuple[float, float]) -> bool:
        if self.floor_bounds is None:
            return True
        x0, y0, x1, y1 = self.floor_bounds
        return x0 <= xy[0] <= x1 and y0 <= xy[1] <= y1

    def process(self, frame: np.ndarray, t_media: float) -> list[WorldObservation]:
        t0 = time.perf_counter()
        H, W = frame.shape[:2]
        res = self.model.track(
            frame,
            persist=True,
            classes=[PERSON_CLASS_ID],
            conf=self.cfg.conf,
            imgsz=self.world.imgsz,
            tracker="bytetrack.yaml",
            verbose=False,
        )[0]
        boxes: list[tuple[int, tuple[int, int, int, int], float]] = []
        if res.boxes is not None and res.boxes.id is not None:
            for b, tid, c in zip(
                res.boxes.xyxy.cpu().numpy(),
                res.boxes.id.cpu().numpy(),
                res.boxes.conf.cpu().numpy(),
            ):
                x1, y1, x2, y2 = (int(round(v)) for v in b)
                boxes.append((int(tid), (max(0, x1), max(0, y1), min(W, x2), min(H, y2)), float(c)))

        small = half(frame)
        observations: list[WorldObservation] = []
        for tid, bbox, conf in boxes:
            x1, y1, x2, y2 = bbox
            if y2 - y1 < self.world.min_person_px:
                continue
            raw, sigma, _feet_hidden = locate_person(
                self.calib, bbox, H, self.world.person_top_height_m, self.world.min_box_height_ratio
            )
            if not self._in_bounds(raw):
                continue
            tr = self.tracks.setdefault(tid, _Track())
            if (
                tr.pos is None
                or math.hypot(raw[0] - tr.pos[0], raw[1] - tr.pos[1]) > _SMOOTH_RESET_M
            ):
                pos = raw
            else:
                a = self.world.pos_smoothing_alpha
                pos = (a * raw[0] + (1 - a) * tr.pos[0], a * raw[1] + (1 - a) * tr.pos[1])
            tr.pos, tr.last_t = pos, t_media

            desc = person_descriptor(frame, small, self._bg, bbox, self.world.fg_threshold)
            q = crop_quality(bbox, frame.shape, ref_height_px=self.world.quality_ref_px)
            obs = WorldObservation(
                local_track_id=tid,
                bbox=bbox,
                conf=conf,
                embedding=desc,
                quality=q,
                t_media=t_media,
                world_pos=(float(pos[0]), float(pos[1])),
                pos_sigma=sigma,
                claimable=self._claim_area is None or self._claim_area.contains(Point(*pos)),
            )
            self._identify_step(tr, tid, obs, desc, q, t_media)
            observations.append(obs)

        self._update_background(
            small, [(b[1][0] // 2, b[1][1] // 2, b[1][2] // 2, b[1][3] // 2) for b in boxes]
        )
        for tid in [k for k, v in self.tracks.items() if t_media - v.last_t > _TRACK_FORGET_S]:
            del self.tracks[tid]
        self.frames += 1
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        with self._lock:
            self._last_frame = frame
            self._last_obs = observations
            self._last_t = t_media
        return observations

    def _identify_step(
        self, tr: _Track, tid: int, obs: WorldObservation, desc: np.ndarray, q: float, t: float
    ) -> None:
        """Gate check-in (the formal verification) when the person is at the
        gate; elsewhere, recognition of enrolled employees with a stricter
        bar. Either may turn THIS observation into a FACE_ANCHOR claim."""
        if self.registry is None:
            return
        if q >= self.world.identify_min_quality:
            tr.recent_descs.append(desc)
        g = self.world.gate
        at_gate = (
            g is not None
            and math.hypot(obs.world_pos[0] - g.x, obs.world_pos[1] - g.y) <= g.radius_m
        )
        if at_gate and tr.gate_state not in ("verified", "unverified"):
            self._gate_step(tr, tid, obs, desc, t)
        elif self.world.recognise and not at_gate and obs.claimable:
            self._recognise_step(tr, tid, obs, t)

    def _recognise_step(self, tr: _Track, tid: int, obs: WorldObservation, t: float) -> None:
        w = self.world
        due = tr.employee_id is None or t - tr.last_recognised_t >= w.reanchor_interval_s
        if not due or len(tr.recent_descs) < w.recognise_min_frames:
            return
        v = self.registry.verify(
            list(tr.recent_descs)[-w.recognise_min_frames :],
            w.recognise_threshold,
            w.recognise_margin,
        )
        tr.last_recognised_t = t
        if not v.verified:
            return
        if tr.employee_id is not None and tr.employee_id != v.employee_id:
            # The local tracker may have swapped two people: trust neither
            # label until this track's signatures agree again.
            tr.employee_id = tr.employee_name = None
            tr.recent_descs.clear()
            return
        first = tr.employee_id is None
        tr.employee_id, tr.employee_name, tr.score, tr.second, tr.best_id = (
            v.employee_id,
            v.name,
            v.score,
            v.second_score,
            v.best_id,
        )
        last = self._last_anchor_by_emp.get(v.employee_id)
        if last is None or t - last >= w.reanchor_interval_s:
            obs.anchor_identity = v.employee_id
            self._last_anchor_by_emp[v.employee_id] = t
        if first:
            self.events.append(
                {
                    "t": round(t, 1),
                    "kind": "recognised",
                    "track": tid,
                    "employee_id": v.employee_id,
                    "name": v.name,
                    "score": round(v.score, 3),
                    "second": round(v.second_score, 3),
                    "anchored": obs.anchor_identity is not None,
                }
            )

    def _gate_step(
        self, tr: _Track, tid: int, obs: WorldObservation, desc: np.ndarray, t: float
    ) -> None:
        g = self.world.gate
        if g is None:
            return
        tr.gate_state = "checking"
        tr.gate_frames += 1
        tr.gate_descs.append(desc)
        if len(tr.gate_descs) < self.world.gate_min_frames:
            return
        v = self.registry.verify(
            list(tr.gate_descs), self.world.verify_threshold, self.world.verify_margin
        )
        _log.info("gate_check", node_id=self.node_id, track=tid, frames=tr.gate_frames,
                  best=v.best_id, score=round(v.score, 3), second=round(v.second_score, 3))
        tr.score, tr.second, tr.best_id = v.score, v.second_score, v.best_id
        if v.verified:
            tr.gate_state, tr.employee_id, tr.employee_name = "verified", v.employee_id, v.name
            # A check-in is its own event: a recognition a moment earlier (on
            # the walk from the door) does not suppress it.
            last = self._last_checkin_by_emp.get(v.employee_id)
            if (last is None or t - last >= self.world.anchor_cooldown_s) and obs.claimable:
                obs.anchor_identity = v.employee_id
                self._last_checkin_by_emp[v.employee_id] = t
                self._last_anchor_by_emp[v.employee_id] = t
            self.events.append(
                {
                    "t": round(t, 1),
                    "kind": "verified",
                    "track": tid,
                    "employee_id": v.employee_id,
                    "name": v.name,
                    "score": round(v.score, 3),
                    "second": round(v.second_score, 3),
                    "anchored": obs.anchor_identity is not None,
                }
            )
        elif tr.gate_frames >= self.world.gate_max_frames:
            tr.gate_state = "unverified"
            self.events.append(
                {
                    "t": round(t, 1),
                    "kind": "unverified",
                    "track": tid,
                    "best_id": v.best_id,
                    "score": round(v.score, 3),
                    "second": round(v.second_score, 3),
                }
            )

    # ── operator diagnostics (node control endpoint) ──────────────────

    def status(self) -> dict[str, Any]:
        with self._lock:
            obs = list(self._last_obs)
            t = self._last_t
            frame = self._last_frame
        h, w = frame.shape[:2] if frame is not None else (1, 1)
        dets = []
        for o in obs:
            tr = self.tracks.get(o.local_track_id)
            dets.append(
                {
                    "track": o.local_track_id,
                    "conf": round(o.conf, 3),
                    "quality": round(o.quality, 2),
                    "bbox_norm": [
                        round(o.bbox[0] / w, 4),
                        round(o.bbox[1] / h, 4),
                        round(o.bbox[2] / w, 4),
                        round(o.bbox[3] / h, 4),
                    ],
                    "x": round(o.world_pos[0], 2),
                    "y": round(o.world_pos[1], 2),
                    "pos_sigma": round(o.pos_sigma, 2),
                    "claimed": o.claimable,
                    "anchor": o.anchor_identity,
                    "gate_state": tr.gate_state if tr else "none",
                    "employee_id": tr.employee_id if tr else None,
                    "employee_name": tr.employee_name if tr else None,
                    "score": round(tr.score, 3) if tr else None,
                }
            )
        return {
            "node_id": self.node_id,
            "t_media": round(t, 2),
            "frames": self.frames,
            "process_ms": round(self.last_ms, 1),
            "detections": dets,
            "events": list(self.events)[-10:],
            "registry_size": len(self.registry.employees) if self.registry else 0,
            "gate": None if self.world.gate is None else self.world.gate.model_dump(),
            **self.extra_status,
        }

    def preview_jpeg(self) -> bytes:
        """This node's last processed frame with what it made of it drawn on
        top — its own maintenance view, served on its own control endpoint."""
        with self._lock:
            frame, obs, n = self._last_frame, list(self._last_obs), self.frames
        if frame is None:
            return b""
        if self._preview_cache[0] == n:
            return self._preview_cache[1]
        sx, sy = _PREVIEW_W / frame.shape[1], _PREVIEW_H / frame.shape[0]
        img = cv2.resize(frame, (_PREVIEW_W, _PREVIEW_H), interpolation=cv2.INTER_AREA)
        self._draw_floor_overlays(img, sx, sy)
        for o in obs:
            tr = self.tracks.get(o.local_track_id)
            x1, y1, x2, y2 = (
                int(o.bbox[0] * sx),
                int(o.bbox[1] * sy),
                int(o.bbox[2] * sx),
                int(o.bbox[3] * sy),
            )
            colour = (
                (80, 200, 120)
                if (tr and tr.employee_id)
                else (0, 170, 255)
                if o.claimable
                else (150, 150, 150)
            )
            if tr and tr.gate_state == "unverified":
                colour = (60, 60, 230)
            cv2.rectangle(img, (x1, y1), (x2, y2), colour, 2)
            fx, fy = int((o.bbox[0] + o.bbox[2]) / 2 * sx), int(o.bbox[3] * sy)
            cv2.circle(img, (fx, fy), 3, colour, -1)
            label = f"#{o.local_track_id} {o.conf:.2f} ({o.world_pos[0]:.1f},{o.world_pos[1]:.1f})"
            _text(img, label, (x1, max(12, y1 - 4)), colour)
            tag = None
            if tr and tr.gate_state in ("verified", "checking", "unverified"):
                tag = {
                    "verified": f"VERIFIED {tr.employee_id} {tr.score:.2f}",
                    "checking": "checking against registry...",
                    "unverified": f"NOT VERIFIED (best {tr.best_id} {tr.score:.2f})",
                }[tr.gate_state]
            elif tr and tr.employee_id:
                tag = f"recognised {tr.employee_id} {tr.score:.2f}"
            if tag:
                _text(img, tag, (x1, min(_PREVIEW_H - 4, y2 + 14)), colour)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 78])
        data = buf.tobytes() if ok else b""
        self._preview_cache = (n, data)
        return data

    def _draw_floor_overlays(self, img: np.ndarray, sx: float, sy: float) -> None:
        def poly_px(coords):
            pts = []
            for x, y in coords:
                u, v = self.calib.floor_to_image(x, y)
                pts.append((int(u * sx), int(v * sy)))
            return np.array(pts, dtype=np.int32)

        if self._zone_geom is not None and not self._zone_geom.is_empty:
            geoms = (
                [self._zone_geom]
                if self._zone_geom.geom_type == "Polygon"
                else list(self._zone_geom.geoms)
            )
            for gm in geoms:
                coords = list(gm.exterior.coords)
                if all(self._in_front(x, y) for x, y in coords):
                    cv2.polylines(img, [poly_px(coords)], True, (255, 200, 60), 1, cv2.LINE_AA)
        g = self.world.gate
        if g is not None:
            ring = [
                (g.x + g.radius_m * math.cos(a), g.y + g.radius_m * math.sin(a))
                for a in np.linspace(0, 2 * math.pi, 40)
            ]
            if all(self._in_front(x, y) for x, y in ring):
                cv2.polylines(img, [poly_px(ring)], True, (90, 220, 90), 2, cv2.LINE_AA)
                u, v = self.calib.floor_to_image(g.x, g.y)
                _text(img, "GATE", (int(u * sx) - 14, int(v * sy)), (90, 220, 90))

    def _in_front(self, x: float, y: float) -> bool:
        if self.calib.R is None or self.calib.t is None:
            return True
        pc = self.calib.R @ np.array([x, y, 0.0]) + self.calib.t.ravel()
        return bool(pc[2] > 0.2)


def _text(img: np.ndarray, s: str, org: tuple[int, int], colour: tuple[int, int, int]) -> None:
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, 0.38, colour, 1, cv2.LINE_AA)
