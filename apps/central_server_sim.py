"""apps/central_server_sim.py
------------------------------
THE CENTRALISED COMPARISON — deliberately NOT part of Starling.

A normal, single-server multi-camera re-identification system, run next to
Starling on the SAME simulated input so an audience can see why the
decentralised design matters. One process receives every camera's
observations over the network and assigns identities in ONE shared store,
using the matching logic of the original centralised system: the same
`IdentityStore.match_or_create` that `apps/baseline.py` (Kunal Gaikwad's
multicam-reid) calls — a cosine-similarity match of each new appearance
embedding against the single shared table of known people. `apps/baseline.py`
itself is not modified or imported (it pulls in torch/OpenCV for real video);
only its identity store is reused, through this adapter.

Network rules (same as Starling's partition control): the server lives on one
side of a split (with cameras {0, 1}); `POST /partition {"cut_cameras": [2, 3]}`
makes cameras on the far side unable to reach it, so their observations are
never delivered. If this process is killed nothing is tracked at all.

    python apps/central_server_sim.py --sim-endpoint tcp://127.0.0.1:5560 --port 7000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import zmq

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402

from starling_sim.messages import node_topic  # noqa: E402
from starling_store.identity_store import IdentityStore  # noqa: E402

CAMERAS = (0, 1, 2, 3)


class CentralServer:
    """One shared identity store; every delivered observation goes through it."""

    def __init__(self, sim_threshold: float = 0.60, ema_alpha: float = 0.10, stale_after_s: float = 3.0) -> None:
        # The baseline's own matcher: appearance only, one shared table.
        self.store = IdentityStore(db_path=":memory:", similarity_threshold=sim_threshold, ema_alpha=ema_alpha, node_id=-2)
        self.stale_after_s = stale_after_s
        self.cut_cameras: set[int] = set()
        self.tracks: dict[str, dict[str, Any]] = {}
        self.now_t = 0.0
        self.delivered = 0
        self.dropped = 0
        self.started = time.monotonic()
        self._lock = threading.Lock()

    def ingest(self, camera_id: int, payload: dict[str, Any]) -> None:
        with self._lock:
            if camera_id in self.cut_cameras:
                self.dropped += len(payload.get("observations", []))
                return
            self.now_t = max(self.now_t, float(payload["t_media"]))
            for o in payload.get("observations", []):
                gid, is_new, _ = self.store.match_or_create(
                    np.array(o["embedding"], dtype=np.float32), camera_id, int(payload["tick"]), [0, 0, 1, 1],
                    float(o["conf"]), float(o["t_media"]),
                )
                tr = self.tracks.setdefault(gid, {"n": 0, "first_t": o["t_media"]})
                tr.update({"x": o["world_x"], "y": o["world_y"], "t": o["t_media"], "camera": camera_id})
                tr["n"] += 1
                self.delivered += 1

    def state(self) -> dict[str, Any]:
        with self._lock:
            tracked = []
            for gid, tr in self.tracks.items():
                age = self.now_t - tr["t"]
                tracked.append({
                    "id": gid[-6:], "x": round(tr["x"], 2), "y": round(tr["y"], 2), "camera": tr["camera"],
                    "age_s": round(age, 1), "current": age < self.stale_after_s, "n": tr["n"],
                })
            cut = sorted(self.cut_cameras)
            return {
                "status": "PARTIAL" if cut else "HEALTHY",
                "cut_cameras": cut,
                "now_t_media": round(self.now_t, 1),
                "identities_total": len(self.tracks),
                "tracked_now": sum(1 for t in tracked if t["current"]),
                "delivered_observations": self.delivered,
                "dropped_observations": self.dropped,
                "pid": os.getpid(),
                "uptime_s": round(time.monotonic() - self.started, 1),
                "tracked": tracked,
            }


def _serve(server: CentralServer, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:
            pass

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/state":
                self._send(200, server.state())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/partition":
                with server._lock:
                    server.cut_cameras = {int(c) for c in body.get("cut_cameras", [])}
                self._send(200, {"ok": True, "cut_cameras": sorted(server.cut_cameras)})
            elif self.path == "/shutdown":
                self._send(200, {"ok": True})
                threading.Thread(target=lambda: (time.sleep(0.2), os._exit(0)), daemon=True).start()
            else:
                self._send(404, {"error": "not found"})

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True, name="central-http").start()
    return httpd


def main(argv: Optional[list] = None) -> None:
    ap = argparse.ArgumentParser(description="Centralised comparison server (NOT part of Starling)")
    ap.add_argument("--sim-endpoint", default="tcp://127.0.0.1:5560")
    ap.add_argument("--port", type=int, default=7000)
    ap.add_argument("--pidfile", type=Path, default=REPO / "data" / "demo" / "central.pid")
    args = ap.parse_args(argv)

    server = CentralServer()
    args.pidfile.parent.mkdir(parents=True, exist_ok=True)
    args.pidfile.write_text(str(os.getpid()))
    _serve(server, args.port)

    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.connect(args.sim_endpoint)
    for c in CAMERAS:
        sub.setsockopt_string(zmq.SUBSCRIBE, node_topic(c))
    print(f"central server (centralised comparison, NOT Starling) on http://127.0.0.1:{args.port}", flush=True)
    while True:
        if sub.poll(500, zmq.POLLIN) == 0:
            continue
        topic, raw = sub.recv_multipart()
        camera = int(topic.decode().split(":")[1])
        server.ingest(camera, json.loads(raw.decode("utf-8")))


if __name__ == "__main__":
    main()
