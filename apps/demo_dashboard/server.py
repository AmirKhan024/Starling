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
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from apps.demo_dashboard.config import DemoDashboardConfig, load_demo_config
from apps.demo_dashboard.engine import DashboardEngine
from starling_net.logging import get_logger, setup_logging

_STATIC = Path(__file__).parent / "static"


class LieBody(BaseModel):
    node_id: int


class StopLieBody(BaseModel):
    node_id: Optional[int] = None


class ScriptBody(BaseModel):
    name: str


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
    app.state.engine = engine

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html", headers={"Cache-Control": "no-store"})

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
        }

    @app.get("/api/state")
    def state() -> JSONResponse:
        return JSONResponse(engine.snapshot(), headers={"Cache-Control": "no-store"})

    @app.post("/api/script")
    def script(body: ScriptBody) -> dict:
        return engine.run_script(body.name)

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
