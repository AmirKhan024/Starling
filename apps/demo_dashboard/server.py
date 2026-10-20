"""apps/demo_dashboard/server.py
---------------------------------
FastAPI wrapper: serves the single-page dashboard and a small JSON API over
`DashboardEngine`. Run:  python -m apps.demo_dashboard.server --config configs/demo_dashboard.yaml

Why FastAPI + one HTML/SVG page rather than Streamlit (recorded in
STATUS.md Decisions): the live floor-plan map, ~1 s smooth refresh without
full-page reruns, and stable `data-testid` selectors for the automated
review are all direct in plain HTML/SVG and clunky in Streamlit.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from apps.demo_dashboard.config import DemoDashboardConfig, load_demo_config
from apps.demo_dashboard.engine import DashboardEngine
from starling_net.logging import get_logger, setup_logging

_STATIC = Path(__file__).parent / "static"
_REPO = Path(__file__).resolve().parents[2]


class LieBody(BaseModel):
    node_id: int


class StopLieBody(BaseModel):
    node_id: Optional[int] = None


class ScriptBody(BaseModel):
    name: str


class ConflictBody(BaseModel):
    variant: str


class WorldBody(BaseModel):
    node_id: Optional[int] = None
    employee_id: Optional[str] = None
    duration_s: Optional[float] = None


class QueryBody(BaseModel):
    text: str
    purpose: str = "safety"


def create_app(cfg: DemoDashboardConfig) -> FastAPI:
    engine = DashboardEngine(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine.start()
        yield
        engine.stop()

    app = FastAPI(title="Starling demo dashboard", lifespan=lifespan)
    # Shared stylesheet, script and icons for every page.
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
    app.state.engine = engine

    world = cfg.mode == "world"

    @app.get("/")
    def index() -> FileResponse:
        """The operator view: what a warehouse manager needs, in plain words."""
        return FileResponse(_STATIC / ("world_manager.html" if world else "index.html"), headers={"Cache-Control": "no-store"})

    @app.get("/engineer")
    def engineer() -> FileResponse:
        """The full technical view: claim counts, gaps, reputation, forks,
        convergence, partition state. This is what the automated review reads."""
        return FileResponse(_STATIC / ("world_tech.html" if world else "engineer.html"), headers={"Cache-Control": "no-store"})

    @app.get("/api/node/{node_id}/preview.jpg")
    def node_preview(node_id: int) -> Response:
        """A camera node's own annotated maintenance view (its last frame and
        what it made of it), read from that node's local operator endpoint.
        Raw frames never travel over gossip."""
        code, body, ctype = engine.node_get(node_id, "/preview.jpg")
        return Response(body, status_code=code if body else 204, media_type=ctype, headers={"Cache-Control": "no-store"})

    @app.get("/api/node/{node_id}/perception")
    def node_perception(node_id: int) -> Response:
        code, body, ctype = engine.node_get(node_id, "/perception")
        return Response(body or b"{}", status_code=code, media_type="application/json", headers={"Cache-Control": "no-store"})

    @app.post("/api/world/block")
    def world_block(body: WorldBody) -> dict:
        return engine.world_post("/api/control/block", {"node_id": body.node_id, "duration_s": body.duration_s})

    @app.post("/api/world/unblock")
    def world_unblock(body: WorldBody) -> dict:
        return engine.world_post("/api/control/unblock", {"node_id": body.node_id})

    @app.post("/api/world/break")
    def world_break(body: WorldBody) -> dict:
        return engine.world_post("/api/control/break", {"employee_id": body.employee_id})

    @app.get("/inside")
    @app.get("/network")
    def network_page() -> FileResponse:
        """Behind the scenes, for an audience: the camera network itself — gossip,
        every camera's own answer, and the centralised design side by side."""
        return FileResponse(_STATIC / "world_inside.html", headers={"Cache-Control": "no-store"})

    @app.get("/tour")
    def tour_page() -> FileResponse:
        """The guided demo: one chapter per idea, each with a live action and a live proof."""
        return FileResponse(_STATIC / "world_tour.html", headers={"Cache-Control": "no-store"})

    @app.get("/compare")
    def compare_page() -> FileResponse:
        """Traditional central system vs Starling: two live maps, same cameras, same moment."""
        return FileResponse(_STATIC / "world_compare.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/compare")
    def compare() -> dict:
        if engine.showcase is None:
            return {}
        return engine.showcase.compare()

    @app.get("/how")
    def how_page() -> FileResponse:
        """How Starling works, in plain words and pictures (and how it scales)."""
        return FileResponse(_STATIC / "world_how.html", headers={"Cache-Control": "no-store"})

    @app.post("/api/ask")
    def ask(body: QueryBody) -> dict:
        """Ask Starling in plain English (manager view)."""
        if engine.showcase is None:
            return engine.query(body.text, body.purpose)
        return engine.showcase.answer(body.text, body.purpose)

    @app.get("/api/rollcall")
    def rollcall() -> dict:
        if engine.showcase is None:
            return {"status": "refused", "headline": "Roll call needs the live world demo."}
        return engine.showcase.roll_call()

    @app.get("/api/ask_cameras")
    def ask_cameras() -> dict:
        """The same question put to every camera node directly; each answers
        from its own replica."""
        if engine.showcase is None:
            return {"nodes": [], "agree": False}
        return engine.showcase.ask_cameras()

    @app.post("/api/node/{node_id}/kill")
    def node_kill(node_id: int) -> dict:
        return engine.kill_node(node_id)

    @app.post("/api/node/{node_id}/restart")
    def node_restart(node_id: int) -> dict:
        return engine.restart_node(node_id)

    @app.post("/api/world/visitor")
    def world_visitor(body: WorldBody) -> dict:
        return engine.world_post("/api/control/visitor", {"visitor_id": body.employee_id} if body.employee_id else {})

    @app.get("/api/gossip_feed")
    def gossip_feed(since: int = 0) -> JSONResponse:
        """Envelopes the dashboard overheard since `since` (live network animation)."""
        feed = engine.observer.feed_since(since)
        if since == 0:
            feed["events"] = feed["events"][-50:]
        return JSONResponse(feed, headers={"Cache-Control": "no-store"})

    @app.get("/api/sample_claim")
    def sample_claim() -> dict:
        """The newest claim overheard on gossip, field by field — what actually
        crosses the wire instead of video."""
        return engine.sample_claim()

    @app.get("/api/scale")
    def scale() -> Response:
        """The measured scalability experiment (scripts/run_scale_experiment.py)."""
        p = _REPO / "docs" / "results_scale.json"
        return Response(p.read_bytes() if p.exists() else b"{}", media_type="application/json")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/config")
    def config() -> dict:
        return {
            "refresh_ms": 1000,
            "floorplan": engine.floorplan,
            "node_ids": engine.node_ids,
            "partition_groups": cfg.partition_groups,
            "converge_tolerance": cfg.converge_tolerance_claims,
            "mode": cfg.mode,
            "topology_edges": cfg.topology_edges,
            "world_url": cfg.world_url,
            "replica_settle_s": cfg.replica_settle_s,
            # the navmesh grid the candidate-region "runs" are expressed in
            "grid": {"origin": list(engine.navmesh.origin), "cell": engine.navmesh.cell_size},
            # static site description (configs/world/warehouse.yaml) for drawing the floor
            "world": engine.world_view.site() if engine.world_view is not None else None,
        }

    @app.get("/api/state")
    def state() -> JSONResponse:
        return JSONResponse(engine.snapshot(), headers={"Cache-Control": "no-store"})

    @app.post("/api/script")
    def script(body: ScriptBody) -> dict:
        return engine.run_script(body.name)

    @app.post("/api/conflict")
    def conflict(body: ConflictBody) -> dict:
        return engine.run_conflict(body.variant)

    @app.post("/api/central/kill")
    def central_kill() -> dict:
        return engine.kill_central()

    @app.post("/api/central/restart")
    def central_restart() -> dict:
        return engine.restart_central()

    @app.post("/api/partition")
    def partition() -> dict:
        return engine.partition()

    @app.post("/api/heal")
    def heal() -> dict:
        return engine.heal()

    @app.post("/api/lie")
    def lie(body: LieBody) -> dict:
        return engine.lie(body.node_id)

    @app.post("/api/stop_lie")
    def stop_lie(body: StopLieBody) -> dict:
        return engine.stop_lying(body.node_id)

    @app.post("/api/reset")
    def reset() -> dict:
        return engine.reset()

    @app.post("/api/query")
    def query(body: QueryBody) -> dict:
        return engine.query(body.text, body.purpose)

    return app


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Starling demo dashboard (read-only gossip observer)")
    parser.add_argument("--config", type=Path, default=Path("configs/demo_dashboard.yaml"))
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    cfg = load_demo_config(args.config)
    if args.port is not None:
        cfg.http_port = args.port
    setup_logging(-1)
    get_logger(__name__).info("dashboard_starting", url=f"http://{cfg.http_host}:{cfg.http_port}")
    print(f"Starling dashboard: http://{cfg.http_host}:{cfg.http_port}", file=sys.stderr, flush=True)  # CLI banner
    uvicorn.run(create_app(cfg), host=cfg.http_host, port=cfg.http_port, log_level="warning")


if __name__ == "__main__":
    main()
