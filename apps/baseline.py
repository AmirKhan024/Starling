"""
apps/baseline.py
-----------------
FROZEN CONTROL CONDITION. This is the original V1 centralized multi-camera
tracking & re-identification pipeline, unchanged in algorithm, merged from
the former pipeline.py (CLI) and tracker/global_tracker.py (CameraWorker,
GlobalTracker) into a single entry point during the WP-00 repo restructure.

It is the experimental control condition for every measurement in the
Starling project (see docs/V1_BASELINE.md and STARLING_BUILD_STATE.md §9).
Never change its algorithm. The one behavioural change ever permitted here
is the D-14 crop-volume fix below: save_crops defaults to False, and when
enabled, at most one crop per identity per crop_interval_s is written,
instead of one crop per detection per frame (~180k files on a 10 min /
4 cam / 5 person run, and a privacy problem besides).

Usage — video files
-------------------
  python apps/baseline.py --videos cam0.mp4 cam1.mp4 --output results/

Usage — live RTSP streams
-------------------------
  python apps/baseline.py --live \
    --sources rtsp://192.168.1.10/stream1 rtsp://192.168.1.11/stream2 \
    --output results/

Usage — mixed (file + webcam)
------------------------------
  python apps/baseline.py --live --sources cam0.mp4 0 --output results/

Then open the dashboard in a separate terminal:
  streamlit run apps/dashboard/app.py

Key flags
---------
  --lost-threshold   seconds absent before person → LOST   [120]
  --sim-threshold    cosine similarity for identity match  [0.60]
  --reentry-timeout  alias for lost-threshold (same value)
"""

import argparse
import time
import threading
from pathlib import Path
from typing import Optional, Dict, List

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from starling_perception.embedder import FeatureExtractor
from starling_store.identity_store import IdentityStore


PERSON_CLASS = 0


def _color(global_id: str) -> tuple:
    """Deterministic BGR colour from a GID string."""
    h = abs(hash(global_id)) % (2**31)
    np.random.seed(h % (2**32 - 1))
    r, g, b = np.random.randint(80, 230, 3)
    return (int(b), int(g), int(r))


class CameraWorker:
    """
    Processes a single camera stream (file or RTSP/webcam URL).
    Runs detection + tracking + embedding extraction each frame.
    Writes results to the shared IdentityStore.
    Can run in its own thread for live multi-camera setups.

    Parameters
    ----------
    source      : video file path, RTSP URL, or webcam index (int)
    camera_id   : integer label for this camera
    store       : shared IdentityStore instance
    extractor   : shared FeatureExtractor instance
    yolo_model  : YOLO instance (shared across workers)
    output_dir  : where to write output video + crops
    conf        : detection confidence threshold
    promote_every_n : call store.promote_lost() every N frames
    save_video  : write annotated output .mp4
    save_crops  : save person crop images to disk
    """

    def __init__(
        self,
        source,
        camera_id: int,
        store: IdentityStore,
        extractor: FeatureExtractor,
        yolo_model: YOLO,
        output_dir: str,
        conf: float         = 0.35,
        promote_every_n: int = 30,
        save_video: bool    = True,
        save_crops: bool    = False,  # D-14: was True
        crop_interval_s: float = 10.0,  # D-14: min seconds between crops per identity
        device: str         = "cpu",
    ):
        self.source      = source
        self.camera_id   = camera_id
        self.store       = store
        self.extractor   = extractor
        self.model       = yolo_model
        self.output_dir  = Path(output_dir)
        self.conf        = conf
        self.promote_every = promote_every_n
        self.save_video  = save_video
        self.save_crops  = save_crops
        self.crop_interval_s = crop_interval_s
        self.device      = device
        self._last_crop_at: Dict[str, float] = {}  # D-14: global_id -> last crop wall time

        self.crops_dir = self.output_dir / "crops" / f"cam{camera_id}"
        if save_crops:
            self.crops_dir.mkdir(parents=True, exist_ok=True)

        # Live stats
        self.frame_idx    = 0
        self.running      = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def run_sync(self) -> Dict[int, List[dict]]:
        """Process video synchronously (for file-based offline use)."""
        self.running = True
        all_tracks = {}
        cap, writer = self._open_source()

        print(f"[Cam {self.camera_id}] Starting  source={self.source}")
        while self.running:
            ret, frame = cap.read()
            if not ret:
                break
            result = self._process_frame(frame, writer)
            all_tracks[self.frame_idx - 1] = result

        cap.release()
        if writer:
            writer.release()
        self.running = False
        print(f"[Cam {self.camera_id}] Done  ({self.frame_idx} frames)")
        return all_tracks

    def run_threaded(self):
        """Start processing in a background thread (for live streams)."""
        self._thread = threading.Thread(
            target=self.run_sync, daemon=True, name=f"cam{self.camera_id}"
        )
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Per-frame processing
    # ------------------------------------------------------------------

    def _process_frame(self, frame: np.ndarray, writer) -> List[dict]:
        h, w = frame.shape[:2]

        # ── Step 1: YOLOv8 + ByteTrack ────────────────────────────────
        results = self.model.track(
            frame,
            persist=True,
            classes=[PERSON_CLASS],
            conf=self.conf,
            tracker="bytetrack.yaml",
            verbose=False,
            device=self.device,
        )

        frame_dets = []
        r = results[0]

        if r.boxes is not None and r.boxes.id is not None:
            boxes     = r.boxes.xyxy.cpu().numpy().astype(int)
            track_ids = r.boxes.id.cpu().numpy().astype(int)
            confs     = r.boxes.conf.cpu().numpy()

            # ── Step 2: batch-extract embeddings ──────────────────────
            crops = []
            valid = []
            for box, tid, conf in zip(boxes, track_ids, confs):
                x1, y1, x2, y2 = (
                    max(0, int(box[0])), max(0, int(box[1])),
                    min(w, int(box[2])), min(h, int(box[3]))
                )
                crop = frame[y1:y2, x1:x2]
                if crop.size > 100:
                    crops.append(crop)
                    valid.append((tid, conf, [x1, y1, x2, y2], crop))

            if crops:
                embeddings = self.extractor.extract(crops)  # (N, 512)
            else:
                embeddings = []

            # ── Step 3: resolve against global identity store ─────────
            for i, (tid, conf, bbox, crop) in enumerate(valid):
                emb = embeddings[i] if i < len(embeddings) else None
                if emb is None:
                    continue

                # Match or create in global DB
                global_id, is_new, was_lost = self.store.match_or_create(
                    embedding=emb,
                    camera_id=self.camera_id,
                    frame_idx=self.frame_idx,
                    bbox=bbox,
                    conf=float(conf),
                    crop_path=None,
                )

                # Save crop — D-14: at most one crop per global_id per
                # crop_interval_s seconds, instead of one per detection
                # per frame (was ~180k files on a 10 min / 4 cam / 5
                # person run, and a privacy problem besides).
                crop_path = None
                if self.save_crops:
                    now = time.time()
                    last = self._last_crop_at.get(global_id, 0.0)
                    if now - last >= self.crop_interval_s:
                        self.crops_dir.mkdir(parents=True, exist_ok=True)
                        crop_path = str(
                            self.crops_dir / f"{global_id}_f{self.frame_idx:06d}.jpg"
                        )
                        cv2.imwrite(crop_path, crop)
                        self._last_crop_at[global_id] = now

                if is_new:
                    print(f"  [Cam {self.camera_id}] 🆕 New:        {global_id}"
                          f"  f={self.frame_idx}")
                elif was_lost:
                    print(f"  [Cam {self.camera_id}] 🔄 Reappeared: {global_id}"
                          f"  f={self.frame_idx}  (was LOST → now ACTIVE)")

                frame_dets.append({
                    "track_id"  : int(tid),
                    "global_id" : global_id,
                    "bbox"      : bbox,
                    "conf"      : float(conf),
                    "crop_path" : crop_path,
                    "camera_id" : self.camera_id,
                    "frame_idx" : self.frame_idx,
                    "is_new"    : is_new,
                    "was_lost"  : was_lost,
                })

        # ── Step 4: annotate + write frame ────────────────────────────
        if writer:
            ann = self._annotate(frame.copy(), frame_dets)
            writer.write(ann)

        # ── Step 5: periodic lost-person promotion ────────────────────
        if self.frame_idx % self.promote_every == 0:
            self.store.promote_lost()

        self.frame_idx += 1
        return frame_dets

    # ------------------------------------------------------------------
    # Annotation
    # ------------------------------------------------------------------

    def _annotate(self, frame: np.ndarray, dets: List[dict]) -> np.ndarray:
        for det in dets:
            x1, y1, x2, y2 = det["bbox"]
            gid   = det["global_id"]
            conf  = det["conf"]
            color = _color(gid)

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            label = f"{gid}  {conf:.2f}"
            (tw, th), _ = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2
            )
            cv2.rectangle(frame, (x1, y1-th-10), (x1+tw+6, y1), color, -1)
            cv2.putText(frame, label, (x1+3, y1-4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,255), 2)

        stats = self.store.stats()
        bar   = (f"CAM {self.camera_id}  |  f{self.frame_idx:05d}"
                 f"  |  active={stats['active']}"
                 f"  lost={stats['lost']}"
                 f"  resolved={stats['resolved']}")
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 36), (0,0,0), -1)
        cv2.putText(frame, bar, (8, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,220,255), 2)
        return frame

    # ------------------------------------------------------------------
    # Open source (file or RTSP)
    # ------------------------------------------------------------------

    def _open_source(self):
        cap = cv2.VideoCapture(
            int(self.source) if str(self.source).isdigit() else str(self.source)
        )
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open source: {self.source}")

        fps    = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        writer = None
        if self.save_video:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.output_dir / f"cam{self.camera_id}_tracked.mp4"
            fourcc   = cv2.VideoWriter_fourcc(*"mp4v")
            writer   = cv2.VideoWriter(str(out_path), fourcc, fps, (width, height))
        return cap, writer


# ---------------------------------------------------------------------------
# GlobalTracker: orchestrates all cameras
# ---------------------------------------------------------------------------

class GlobalTracker:
    """
    Top-level orchestrator for multi-camera tracking.

    Parameters
    ----------
    sources         : list of video paths / RTSP URLs / webcam indices
    output_dir      : root output directory
    db_path         : SQLite database path
    reid_weights    : optional fine-tuned ReID checkpoint
    yolo_model      : YOLOv8 model name
    conf            : detection confidence
    sim_threshold   : identity match threshold (global DB lookup)
    lost_threshold  : seconds before marking person as lost
    device          : 'cpu', 'cuda', or 'auto'
    save_crops      : save person crop images to disk (D-14: default False)
    crop_interval_s : min seconds between saved crops per identity (D-14)
    """

    def __init__(
        self,
        sources: List,
        output_dir: str          = "results",
        db_path: str             = "database/identities.db",
        reid_weights: str        = None,
        yolo_model: str          = "yolov8n.pt",
        conf: float              = 0.35,
        sim_threshold: float     = 0.60,
        lost_threshold: float    = 120.0,
        device: str              = "auto",
        save_crops: bool         = False,  # D-14: was True
        crop_interval_s: float   = 10.0,   # D-14
    ):
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device  = device
        self.sources = sources

        print(f"\n[GlobalTracker] Initialising  cameras={len(sources)}"
              f"  device={device}")

        # Shared components
        self.store = IdentityStore(
            db_path=db_path,
            lost_threshold_secs=lost_threshold,
            similarity_threshold=sim_threshold,
        )
        self.extractor = FeatureExtractor(
            weights_path=reid_weights,
            device=device,
            batch_size=8,
        )
        print(f"[GlobalTracker] Loading {yolo_model} ...")
        self.yolo = YOLO(yolo_model)

        # One CameraWorker per source
        self.workers: List[CameraWorker] = []
        for cam_id, src in enumerate(sources):
            self.workers.append(CameraWorker(
                source=src,
                camera_id=cam_id,
                store=self.store,
                extractor=self.extractor,
                yolo_model=self.yolo,
                output_dir=output_dir,
                conf=conf,
                device=device,
                save_crops=save_crops,
                crop_interval_s=crop_interval_s,
            ))

    def run_files(self) -> Dict[int, dict]:
        """
        Process all file-based sources sequentially.
        Returns {cam_id: {frame_idx: [dets]}}
        """
        all_tracks = {}
        for worker in self.workers:
            all_tracks[worker.camera_id] = worker.run_sync()
        # Final lost check
        self.store.promote_lost()
        return all_tracks

    def run_live(self):
        """
        Launch all cameras in parallel threads (for live RTSP/webcam).
        Block until all stopped or KeyboardInterrupt.
        """
        print(f"[GlobalTracker] Starting {len(self.workers)} live camera threads")
        for w in self.workers:
            w.run_threaded()
        try:
            while any(w.running for w in self.workers):
                time.sleep(1)
                self.store.promote_lost()
        except KeyboardInterrupt:
            print("\n[GlobalTracker] Stopping ...")
            for w in self.workers:
                w.stop()


# ---------------------------------------------------------------------------
# CLI entry point (from former pipeline.py)
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Multi-Camera Person Tracking & Re-Identification (V1 baseline)"
    )

    # Sources
    source_group = p.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--videos", nargs="+",
        help="Video file paths (offline processing)"
    )
    source_group.add_argument(
        "--live", action="store_true",
        help="Live mode — use --sources for RTSP URLs or webcam indices"
    )
    p.add_argument(
        "--sources", nargs="+",
        help="For --live mode: RTSP URLs or webcam indices (e.g. 0 1)"
    )

    # Output
    p.add_argument("--output",          default="results",
                   help="Output directory  [results]")
    p.add_argument("--db",              default="database/identities.db",
                   help="SQLite database path")

    # Model
    p.add_argument("--yolo-model",      default="yolov8n.pt",
                   help="YOLOv8 variant: n/s/m/l/x.pt  [yolov8n.pt]")
    p.add_argument("--reid-weights",    default=None,
                   help="Optional fine-tuned ReID .pth")

    # Thresholds
    p.add_argument("--conf",            type=float, default=0.35,
                   help="Detection confidence  [0.35]")
    p.add_argument("--sim-threshold",   type=float, default=0.60,
                   help="Identity match cosine threshold  [0.60]")
    p.add_argument("--lost-threshold",  type=float, default=120.0,
                   help="Seconds absent → LOST status  [120]")

    # System
    p.add_argument("--device",          default="auto",
                   choices=["auto", "cuda", "cpu"])
    p.add_argument("--no-video",        action="store_true",
                   help="Don't save output videos (faster)")

    # D-14: crop saving is opt-in and rate-limited per identity
    p.add_argument("--save-crops",      action="store_true",
                   help="Save person crop images to disk (off by default, D-14)")
    p.add_argument("--crop-interval",   type=float, default=10.0,
                   help="Min seconds between saved crops per identity  [10.0]")

    args = p.parse_args()

    # Resolve sources
    if args.videos:
        sources = args.videos
        live = False
    else:
        if not args.sources:
            p.error("--live requires --sources")
        # Convert numeric strings to ints (webcam indices)
        sources = [int(s) if s.isdigit() else s for s in args.sources]
        live = True

    _banner(sources, args.output, args.device,
            args.sim_threshold, args.lost_threshold)

    tracker = GlobalTracker(
        sources=sources,
        output_dir=args.output,
        db_path=args.db,
        reid_weights=args.reid_weights,
        yolo_model=args.yolo_model,
        conf=args.conf,
        sim_threshold=args.sim_threshold,
        lost_threshold=args.lost_threshold,
        device=args.device,
        save_crops=args.save_crops,
        crop_interval_s=args.crop_interval,
    )

    if live:
        print("\n🎥  Live mode — press Ctrl+C to stop\n")
        tracker.run_live()
    else:
        print("\n📹  Processing video files ...\n")
        t0 = time.time()
        all_tracks = tracker.run_files()
        elapsed = time.time() - t0

        # Print summary
        stats = tracker.store.stats()
        print("\n" + "═" * 55)
        print("  PIPELINE COMPLETE")
        print("═" * 55)
        for cam_id, cam_data in all_tracks.items():
            n_frames  = len(cam_data)
            n_gids    = len({d["global_id"]
                             for fd in cam_data.values() for d in fd})
            print(f"  Camera {cam_id}: {n_frames} frames | {n_gids} unique persons")
        print(f"\n  DB stats:")
        print(f"    Active   : {stats['active']}")
        print(f"    Lost     : {stats['lost']}")
        print(f"    Resolved : {stats['resolved']}")
        print(f"    Sightings: {stats['sightings']}")
        print(f"\n  Time: {elapsed:.1f}s")
        print("═" * 55)
        print(f"\n  Results  → {args.output}/")
        print(f"  Database → {args.db}")
        print(f"\n  Open dashboard:  streamlit run apps/dashboard/app.py\n")


def _banner(sources, out, device, sim_thr, lost_thr):
    print("\n" + "═" * 55)
    print("  Multi-Camera Tracking & Re-Id  (V1 baseline)")
    print("═" * 55)
    print(f"  Sources          : {len(sources)} camera(s)")
    for i, s in enumerate(sources):
        print(f"    [{i}] {s}")
    print(f"  Output           : {out}")
    print(f"  Device           : {device}")
    print(f"  Sim threshold    : {sim_thr}  (identity match)")
    print(f"  Lost threshold   : {lost_thr}s  (absent → LOST)")
    print("═" * 55)


if __name__ == "__main__":
    main()
