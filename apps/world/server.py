"""apps/world/server.py
-----------------------
The live 3D world's server process: physical reality for the demo.

  * runs the world simulation (starling_world.sim) in media time, paced to
    the wall clock;
  * streams the world state to every 3D viewer page (WebSocket /ws/view);
  * drives the CAMERA RIG — a headless browser page (apps/world/rig.py)
    that renders each camera's view with three.js and sends back JPEGs
    (WebSocket /ws/rig) — and publishes each camera's frames on that
    camera's own topic, where only its own node listens
    (starling_world.frames);
  * publishes ground truth for the dashboard's comparison overlay;
  * exposes the operator's physical-world controls (cover a camera lens,
    send someone on a break, send an unknown person in);
  * counts the video bytes each camera publishes (what a central server
    would have to ingest — Starling's nodes keep it local).

It never talks to a node, never reads a node's state, and sends nodes
nothing but pixels.

Run:  python -m apps.world.server --config configs/world/warehouse.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starling_geometry.navmesh import NavMesh
from starling_net.logging import get_logger, setup_logging
from starling_sim.messages import GROUND_TRUTH_TOPIC
from starling_world.camera import PinholeCamera
from starling_world.config import WorldConfig, load_world_config
from starling_world.frames import Frame, FramePublisher
from starling_world.sim import WorldSim

_STATIC = Path(__file__).parent / "static"
_REPO = Path(__file__).resolve().parents[2]
# Viewer pages get the world state this often (wall seconds); they interpolate between.
_VIEW_PUSH_EVERY_N_TICKS = 2
_GT_EVERY_N_TICKS = 4
# A render request the rig has not answered in this long is abandoned.
_RIG_STALE_S = 3.0
# Video bandwidth (what a central server would have to ingest) is averaged
# over this many wall seconds.
_VIDEO_RATE_WINDOW_S = 10.0

log = get_logger(__name__)


class BlockBody(BaseModel):
    node_id: int
    duration_s: Optional[float] = None


class UnblockBody(BaseModel):
    node_id: Optional[int] = None


class BreakBody(BaseModel):
    employee_id: str


class VisitorBody(BaseModel):
    visitor_id: Optional[str] = None  # None = the first configured visitor


def build_meta(cfg: WorldConfig) -> dict[str, Any]:
    """Static description of the world for the 3D pages (viewer, rig,
    enrollment capture): everything scene.js needs to build the building."""
    floorplan = json.loads((_REPO / cfg.floorplan_path).read_text(encoding="utf-8"))
    zones = [
        f
        for f in floorplan["features"]
        if (f.get("properties") or {}).get("role") in ("camera_zone", "blind")
    ]
    cams = []
    for c in cfg.cameras:
        pc = PinholeCamera.from_config(c, cfg.camera_frames)
        cams.append({**c.model_dump(), "vfov_deg": pc.vfov_deg})
    return {
        "company": cfg.company.model_dump(),
        "building": cfg.building.model_dump(),
        "entrance": cfg.entrance.model_dump(),
        "racks": [r.model_dump() for r in cfg.racks],
        "props": [p.model_dump() for p in cfg.props],
        "dock_doors": [d.model_dump() for d in cfg.dock_doors],
        "cameras": cams,
        "camera_frames": cfg.camera_frames.model_dump(),
        "employees": [
            {"id": e.id, "name": e.name, "role": e.role, "look": e.look.model_dump()}
            for e in cfg.employees
        ],
        # Not employees — a separate key so nothing that enrols or verifies
        # employees (capture.html, scripts/enroll_employees.py) ever sees them.
        "visitors": [
            {
                "id": v.id,
                "name": v.name,
                "role": v.role,
                "look": v.look.model_dump(),
                "entry": v.entry,
            }
            for v in cfg.visitors
        ],
        "agvs": [a.model_dump() for a in cfg.agvs],
        "pois": cfg.pois,
        "zones": zones,
    }


class WorldServer:
    def __init__(self, cfg: WorldConfig, speed: Optional[float] = None, hold: bool = False) -> None:
        self.cfg = cfg
        self.speed = cfg.sim.speed if speed is None else speed
        # Held = the world is frozen at t=0 (nobody has arrived) until the
        # launcher says every camera node is ready: POST /api/control/start.
        self.running = not hold
        self.navmesh = NavMesh.from_geojson(
            _REPO / cfg.floorplan_path, cell_size_m=cfg.navmesh_cell_m
        )
        self.sim = WorldSim(cfg, self.navmesh)
        self.publisher: Optional[FramePublisher] = None
        self.viewers: set[WebSocket] = set()
        self.rig: Optional[WebSocket] = None
        self.rig_busy_since: Optional[float] = None
        self.frame_idx = 0
        self.next_frame_t = 0.0
        self.latest_jpeg: dict[int, bytes] = {}
        self.frames_published: dict[int, int] = {c.node_id: 0 for c in cfg.cameras}
        # JPEG bytes published per camera: running total, and (wall time,
        # bytes) samples within the rate window.
        self.bytes_published: dict[int, int] = {c.node_id: 0 for c in cfg.cameras}
        self._byte_samples: dict[int, deque[tuple[float, int]]] = {
            c.node_id: deque() for c in cfg.cameras
        }
        self._first_frame_wall: Optional[float] = None
        self.frames_requested = 0
        self.frames_skipped_busy = 0
        self.render_ms: Optional[float] = None
        self.started_wall = time.monotonic()
        self._task: Optional[asyncio.Task] = None
        self.meta = build_meta(cfg)

    # -- simulation loop --------------------------------------------------------

    async def run(self) -> None:
        dt = 1.0 / self.cfg.sim.tick_hz
        frame_period = 1.0 / self.cfg.camera_frames.fps
        wall_next = time.monotonic()
        while True:
            if not self.running:
                if self.viewers:
                    await self._push_view()
                await asyncio.sleep(0.25)
                wall_next = time.monotonic()
                continue
            self.sim.tick(dt)
            if self.sim.tick_count % _GT_EVERY_N_TICKS == 0 and self.publisher is not None:
                self.publisher.publish_json(GROUND_TRUTH_TOPIC, self.sim.ground_truth())
            if self.sim.t + 1e-9 >= self.next_frame_t:
                self.next_frame_t += frame_period
                await self._request_render()
            if self.sim.tick_count % _VIEW_PUSH_EVERY_N_TICKS == 0 and self.viewers:
                await self._push_view()
            wall_next += dt / max(self.speed, 1e-6)
            delay = wall_next - time.monotonic()
            if delay < -1.0:  # fell far behind (machine stalled): do not burst to catch up
                wall_next = time.monotonic()
                delay = 0
            await asyncio.sleep(max(0.0, delay))

    async def _request_render(self) -> None:
        self.frame_idx += 1
        if self.rig is None:
            return
        now = time.monotonic()
        if self.rig_busy_since is not None and now - self.rig_busy_since < _RIG_STALE_S:
            # The rig is still rendering the previous frame: this frame is
            # simply never captured (a node sees it as a dropped frame).
            self.frames_skipped_busy += 1
            return
        self.rig_busy_since = now
        self.frames_requested += 1
        msg = {
            "type": "render",
            "frame_idx": self.frame_idx,
            "t": self.sim.t,
            "state": self.sim.snapshot(),
        }
        try:
            await self.rig.send_text(json.dumps(msg))
        except Exception:
            self.rig = None
            self.rig_busy_since = None

    async def _push_view(self) -> None:
        payload = json.dumps(
            {
                "type": "state",
                **self.sim.snapshot(),
                "events": self.sim.events[-8:],
                "rig": self.rig_status(),
                "running": self.running,
            }
        )
        dead = []
        for ws in list(self.viewers):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.viewers.discard(ws)

    def on_rig_frame(self, data: bytes) -> None:
        (hlen,) = struct.unpack(">I", data[:4])
        header = json.loads(data[4 : 4 + hlen].decode("utf-8"))
        jpeg = data[4 + hlen :]
        n = int(header["node_id"])
        self.latest_jpeg[n] = jpeg
        self.frames_published[n] = self.frames_published.get(n, 0) + 1
        now = time.monotonic()
        if self._first_frame_wall is None:
            self._first_frame_wall = now
        self.bytes_published[n] = self.bytes_published.get(n, 0) + len(jpeg)
        self._byte_samples.setdefault(n, deque()).append((now, len(jpeg)))
        if self.publisher is not None:
            self.publisher.publish_frame(
                Frame(
                    node_id=n,
                    frame_idx=int(header["frame_idx"]),
                    t_media=float(header["t"]),
                    jpeg=jpeg,
                    width=self.cfg.camera_frames.width_px,
                    height=self.cfg.camera_frames.height_px,
                )
            )

    def video_bytes_per_s(self) -> dict[int, float]:
        """JPEG bytes/s each camera published over the last
        `_VIDEO_RATE_WINDOW_S` wall seconds (or since the first frame, if
        that is more recent)."""
        now = time.monotonic()
        cutoff = now - _VIDEO_RATE_WINDOW_S
        span = _VIDEO_RATE_WINDOW_S
        if self._first_frame_wall is not None:
            span = min(span, max(now - self._first_frame_wall, 1.0))
        rates: dict[int, float] = {}
        for n, samples in self._byte_samples.items():
            while samples and samples[0][0] < cutoff:
                samples.popleft()
            rates[n] = sum(b for _, b in samples) / span
        return rates

    def rig_status(self) -> dict[str, Any]:
        rates = self.video_bytes_per_s()
        return {
            "connected": self.rig is not None,
            "render_ms": None if self.render_ms is None else round(self.render_ms, 1),
            "frames_requested": self.frames_requested,
            "frames_skipped_busy": self.frames_skipped_busy,
            "frames_published": {str(k): v for k, v in self.frames_published.items()},
            "bytes_published": {str(k): v for k, v in self.bytes_published.items()},
            "video_bytes_per_s": {str(k): round(v, 1) for k, v in rates.items()},
            "video_bytes_per_s_total": round(sum(rates.values()), 1),
        }

    def status(self) -> dict[str, Any]:
        return {
            "t_media": round(self.sim.t, 2),
            "speed": self.speed,
            "running": self.running,
            "rig": self.rig_status(),
            "blocked_cameras": self.sim.blocked_cameras(),
            "events": self.sim.events[-20:],
            "workers": [w.snapshot() for w in self.sim.workers],
            "viewers": len(self.viewers),
        }


def create_app(cfg: WorldConfig, speed: Optional[float] = None, hold: bool = False) -> FastAPI:
    world = WorldServer(cfg, speed, hold)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        world.publisher = FramePublisher(cfg.endpoints.frames_bind)
        world._task = asyncio.create_task(world.run())
        yield
        world._task.cancel()
        world.publisher.close()

    app = FastAPI(title="Starling live world", lifespan=lifespan)
    app.state.world = world
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    def _page(name: str) -> FileResponse:
        return FileResponse(_STATIC / name, headers={"Cache-Control": "no-store"})

    @app.get("/")
    def viewer() -> FileResponse:
        return _page("world.html")

    @app.get("/rig")
    def rig_page() -> FileResponse:
        return _page("rig.html")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/world")
    def meta() -> JSONResponse:
        return JSONResponse(world.meta)

    @app.get("/api/status")
    def status() -> JSONResponse:
        return JSONResponse(world.status(), headers={"Cache-Control": "no-store"})

    @app.get("/api/camera/{node_id}/latest.jpg")
    def camera_tap(node_id: int) -> Response:
        """The camera's own live output (a CCTV monitor tap) — the exact JPEG
        last sent to that camera's node. Not part of the Starling network."""
        jpeg = world.latest_jpeg.get(node_id)
        if jpeg is None:
            return Response(status_code=404)
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/control/start")
    def start() -> dict:
        if not world.running:
            world.running = True
            world.sim._event("Shift started")
        return {"ok": True}

    @app.post("/api/control/block")
    def block(body: BlockBody) -> dict:
        world.sim.block_camera(body.node_id, body.duration_s)
        return {"ok": True, "blocked": world.sim.blocked_cameras()}

    @app.post("/api/control/unblock")
    def unblock(body: UnblockBody) -> dict:
        world.sim.unblock_camera(body.node_id)
        return {"ok": True, "blocked": world.sim.blocked_cameras()}

    @app.post("/api/control/break")
    def take_break(body: BreakBody) -> dict:
        return {"ok": world.sim.request_break(body.employee_id)}

    @app.post("/api/control/visitor")
    def send_visitor(body: Optional[VisitorBody] = None) -> dict:
        """Send an unknown person (default: the first configured visitor)
        into the building. ok=False if unknown or already on site."""
        vid = body.visitor_id if body is not None else None
        return {"ok": world.sim.send_visitor(vid)}

    @app.websocket("/ws/view")
    async def ws_view(ws: WebSocket) -> None:
        await ws.accept()
        world.viewers.add(ws)
        try:
            while True:
                await ws.receive_text()  # viewers only listen; this just detects disconnect
        except WebSocketDisconnect:
            pass
        finally:
            world.viewers.discard(ws)

    @app.websocket("/ws/rig")
    async def ws_rig(ws: WebSocket) -> None:
        await ws.accept()
        if world.rig is not None:
            try:
                await world.rig.close()
            except Exception:
                pass
        world.rig = ws
        world.rig_busy_since = None
        log.info("rig_connected")
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    world.on_rig_frame(msg["bytes"])
                elif msg.get("text") is not None:
                    m = json.loads(msg["text"])
                    if m.get("type") == "done":
                        world.render_ms = float(m.get("render_ms", 0.0))
                        world.rig_busy_since = None
        except WebSocketDisconnect:
            pass
        finally:
            if world.rig is ws:
                world.rig = None
                world.rig_busy_since = None
            log.info("rig_disconnected")

    return app


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Starling live 3D world server")
    parser.add_argument(
        "--config", type=Path, default=_REPO / "configs" / "world" / "warehouse.yaml"
    )
    parser.add_argument("--speed", type=float, default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--hold", action="store_true", help="freeze the world at t=0 until POST /api/control/start"
    )
    args = parser.parse_args(argv)
    cfg = load_world_config(args.config)
    if args.port is not None:
        cfg.endpoints.http_port = args.port
    setup_logging(-1)
    url = f"http://{cfg.endpoints.http_host}:{cfg.endpoints.http_port}"
    log.info("world_server_starting", url=url)
    print(f"Starling live world: {url}", file=sys.stderr, flush=True)  # CLI banner
    uvicorn.run(
        create_app(cfg, args.speed, args.hold),
        host=cfg.endpoints.http_host,
        port=cfg.endpoints.http_port,
        log_level="warning",
        ws_max_size=32 * 1024 * 1024,
    )


if __name__ == "__main__":
    main()
