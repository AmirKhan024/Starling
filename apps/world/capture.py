"""apps/world/capture.py
------------------------
Offline renderer for enrollment and calibration: serves the world's 3D
pages from a throw-away local HTTP server (no simulation, no ZMQ — it can
run alongside a live demo) and drives apps/world/static/capture.html in a
headless browser to render chosen people at chosen poses through a chosen
camera, with exactly the camera rig's renderer settings.

    with WorldCapture(cfg) as cap:
        img = cap.render(0, [{"id": "EMP-1041", "x": 3.0, "y": 4.6, "heading": 1.57}])
"""

from __future__ import annotations

import base64
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from starling_world.config import WorldConfig

from apps.world.server import build_meta

_STATIC = Path(__file__).parent / "static"


class _Handler(SimpleHTTPRequestHandler):
    meta_json: bytes = b"{}"

    def log_message(self, *a: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/world"):
            body = self.meta_json
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/capture"):
            self.path = "/capture.html"
        elif self.path.startswith("/static/"):
            self.path = self.path[len("/static") :]
        super().do_GET()


class WorldCapture:
    def __init__(self, cfg: WorldConfig, gpu: bool = True) -> None:
        self.cfg = cfg
        self.gpu = gpu
        self._srv: Optional[ThreadingHTTPServer] = None
        self._pw: Any = None
        self._browser: Any = None
        self.page: Any = None

    def __enter__(self) -> "WorldCapture":
        handler = type(
            "H", (_Handler,), {"meta_json": json.dumps(build_meta(self.cfg)).encode("utf-8")}
        )
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(_STATIC)))
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        args = ["--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist"] if self.gpu else []
        self._browser = self._pw.chromium.launch(
            headless=True, args=args + ["--enable-unsafe-swiftshader"]
        )
        self.page = self._browser.new_page(viewport={"width": 320, "height": 200})
        port = self._srv.server_address[1]
        self.page.goto(f"http://127.0.0.1:{port}/capture", wait_until="load")
        self.page.wait_for_function("window.ready === true", timeout=60000)
        return self

    def render(self, node_id: int, people: list[dict[str, Any]]) -> np.ndarray:
        url = self.page.evaluate("([n, p]) => window.capture(n, p)", [node_id, people])
        raw = base64.b64decode(url.split(",", 1)[1])
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def __exit__(self, *exc: Any) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()
        if self._srv is not None:
            self._srv.shutdown()


def labelled_samples(
    cap: WorldCapture,
    model: Any,
    node_id: int,
    people: list[dict[str, Any]],
    background_small: np.ndarray,
    calib: Any,
    fg_threshold: float,
    conf: float = 0.3,
    imgsz: int = 640,
    match_radius_m: float = 0.9,
) -> list[dict[str, Any]]:
    """Render `people` through camera `node_id`, run the person detector,
    and label each detection with the person standing nearest its foot
    point (ground truth, offline only). Returns one dict per labelled
    detection with the node pipeline's own appearance signature."""
    from starling_node.config import WorldNodeConfig
    from starling_perception.appearance import crop_quality
    from starling_perception.world_pipeline import half, locate_person, person_descriptor

    wcfg = WorldNodeConfig()

    img = cap.render(node_id, people)
    res = model.predict(img, classes=[0], conf=conf, imgsz=imgsz, verbose=False)[0]
    small = half(img)
    out: list[dict[str, Any]] = []
    taken: set[str] = set()
    H, W = img.shape[:2]
    for b, c in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy()):
        x1, y1, x2, y2 = (int(round(v)) for v in b)
        bbox = (max(0, x1), max(0, y1), min(W, x2), min(H, y2))
        (fx, fy), _sigma, _hidden = locate_person(
            calib, bbox, H, wcfg.person_top_height_m, wcfg.min_box_height_ratio
        )
        best, best_d = None, match_radius_m
        for p in people:
            d = float(np.hypot(p["x"] - fx, p["y"] - fy))
            if d < best_d and p["id"] not in taken:
                best, best_d = p["id"], d
        if best is None:
            continue
        taken.add(best)
        out.append(
            {
                "id": best,
                "node_id": node_id,
                "conf": float(c),
                "bbox": bbox,
                "floor": (fx, fy),
                "err_m": best_d,
                "quality": crop_quality(bbox, img.shape, ref_height_px=wcfg.quality_ref_px),
                "desc": person_descriptor(img, small, background_small, bbox, fg_threshold),
            }
        )
    return out
