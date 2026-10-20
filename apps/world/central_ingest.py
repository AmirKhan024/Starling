"""apps/world/central_ingest.py
-------------------------------
THE CENTRALISED COMPARISON for the live 3D world — deliberately NOT part of
Starling.

A conventional multi-camera system streams every camera's video to one
server room, which does all the detection and identity work. This process
is that server's INGEST: it subscribes to all four cameras' JPEG streams
(the same frames the camera nodes receive) and measures what such a server
has to swallow — frames and bytes per second per camera. It does no
tracking of its own; its job in the demo is to make two facts measurable
side by side with Starling:

  * bandwidth — the central design moves every camera's video; Starling
    moves only signed claims (the dashboard measures those from gossip);
  * a single point of failure — `POST /shutdown` kills this process and
    with it every camera's feed, and `POST /partition {"cut_cameras": [2, 3]}`
    makes the cameras on the far side of a network split unreachable
    (the server sits on the {0, 1} side, as in the 2D demo).

    python -m apps.world.central_ingest --config configs/world/warehouse.yaml --port 7010
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import zmq
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from starling_net.logging import get_logger, setup_logging
from starling_world.config import load_world_config
from starling_world.frames import camera_topic

log = get_logger(__name__)


class CentralIngestConfig(BaseModel):
    # Bytes/frames per second are averaged over this many wall seconds.
    rate_window_s: float = 10.0
    # A camera with no frame for this long is reported as not streaming.
    stale_after_s: float = 3.0
    poll_timeout_ms: int = 200


class CentralIngest:
    def __init__(self, endpoint: str, node_ids: list[int], cfg: CentralIngestConfig) -> None:
        self.cfg = cfg
        self.node_ids = node_ids
        self.cut: set[int] = set()
        self._lock = threading.Lock()
        self._arrivals: dict[int, deque[tuple[float, int]]] = {n: deque() for n in node_ids}
        self._last: dict[int, float] = {}
        self._total_bytes: dict[int, int] = {n: 0 for n in node_ids}
        self._started = time.monotonic()
        self._stop = threading.Event()
        ctx = zmq.Context.instance()
        self._sock = ctx.socket(zmq.SUB)
        self._sock.setsockopt(zmq.RCVHWM, 64)
        self._sock.connect(endpoint)
        for n in node_ids:
            self._sock.setsockopt(zmq.SUBSCRIBE, camera_topic(n))
        self._thread = threading.Thread(target=self._loop, daemon=True, name="central-ingest")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._sock.close(linger=0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._sock.poll(self.cfg.poll_timeout_ms, zmq.POLLIN) == 0:
                continue
            parts = self._sock.recv_multipart()
            if len(parts) != 3:
                continue
            header = json.loads(parts[1].decode("utf-8"))
            n = int(header["node_id"])
            with self._lock:
                if n in self.cut:
                    continue  # that camera's uplink cannot reach the server room
                now = time.monotonic()
                size = len(parts[1]) + len(parts[2])
                self._arrivals[n].append((now, size))
                self._last[n] = now
                self._total_bytes[n] += size

    def state(self) -> dict[str, Any]:
        now = time.monotonic()
        cams = {}
        with self._lock:
            for n in self.node_ids:
                q = self._arrivals[n]
                while q and now - q[0][0] > self.cfg.rate_window_s:
                    q.popleft()
                span = min(self.cfg.rate_window_s, now - self._started) or 1.0
                last = self._last.get(n)
                streaming = (
                    last is not None and now - last <= self.cfg.stale_after_s and n not in self.cut
                )
                cams[str(n)] = {
                    "streaming": streaming,
                    "cut": n in self.cut,
                    "fps": round(len(q) / span, 2),
                    "bytes_per_s": round(sum(s for _, s in q) / span, 1),
                    "bytes_total": self._total_bytes[n],
                }
        return {
            "status": "UP",
            "uptime_s": round(now - self._started, 1),
            "cameras": cams,
            "streams_up": sum(1 for c in cams.values() if c["streaming"]),
            "bytes_per_s": round(sum(c["bytes_per_s"] for c in cams.values()), 1),
            "cut_cameras": sorted(self.cut),
        }


def _handler(ingest: CentralIngest, shutdown: threading.Event) -> type:
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def _json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/state":
                self._json(200, ingest.state())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            n = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if self.path == "/partition":
                with ingest._lock:
                    ingest.cut = {int(c) for c in body.get("cut_cameras", [])}
                self._json(200, ingest.state())
            elif self.path == "/shutdown":
                self._json(200, {"ok": True})
                shutdown.set()
            else:
                self._json(404, {"error": "not found"})

    return H


def main(argv: list | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Centralised video-ingest server (comparison only, NOT Starling)"
    )
    ap.add_argument("--config", type=Path, default=REPO / "configs" / "world" / "warehouse.yaml")
    ap.add_argument("--port", type=int, default=7010)
    args = ap.parse_args(argv)
    setup_logging(-2)
    world = load_world_config(args.config)
    ingest = CentralIngest(
        world.endpoints.frames_bind.replace("*", "127.0.0.1"),
        [c.node_id for c in world.cameras],
        CentralIngestConfig(),
    )
    ingest.start()
    shutdown = threading.Event()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _handler(ingest, shutdown))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("central_ingest_started", port=args.port)
    try:
        while not shutdown.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        ingest.stop()
        log.info("central_ingest_stopped")


if __name__ == "__main__":
    main()
