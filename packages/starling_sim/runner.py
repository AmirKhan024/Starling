"""starling_sim/runner.py
--------------------------
The simulator process itself. `SimulatorRunner.tick_once()` is the pure,
directly testable core — advance the world one tick and build every
payload — with no socket I/O; `.run()` is the thin publish-and-sleep loop
around it that `python -m starling_sim.runner` actually executes.

Usage
-----
    python -m starling_sim.runner --config configs/sim/warehouse.yaml [--speed N]
"""

from __future__ import annotations

import argparse
import json
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import numpy as np

from starling_geometry.navmesh import NavMesh
from starling_sim.config import SimulatorConfig, load_simulator_config
from starling_sim.coverage import compute_boundary_crossings, coverage_state_for_node
from starling_sim.messages import GROUND_TRUTH_TOPIC, node_topic
from starling_sim.perception import PerceptionSimConfig, obs_to_dict, observe_zone
from starling_sim.realism import PROFILES, build_camera_models, get_profile, zone_reach
from starling_sim.scenario import load_scenario
from starling_sim.transport import SimPublisher
from starling_sim.world import World, load_camera_zones


class SimulatorRunner:
    def __init__(self, cfg: SimulatorConfig) -> None:
        self.cfg = cfg
        self.navmesh = NavMesh.from_geojson(cfg.floorplan_path, cell_size_m=0.25)
        zones = load_camera_zones(cfg.floorplan_path)
        scenario = load_scenario(cfg.scenario_path)
        self.world = World(
            navmesh=self.navmesh,
            zones=zones,
            scenario=scenario,
            embed_dim=cfg.embed_dim,
            seed=cfg.seed,
            uniform_similarity=cfg.uniform_similarity,
        )
        self.perception_cfg = PerceptionSimConfig(
            pos_noise_sigma_m=cfg.pos_noise_sigma_m,
            embedding_noise_sigma=cfg.embedding_noise_sigma,
            detection_miss_prob=cfg.detection_miss_prob,
            conf_min=cfg.conf_min,
            conf_max=cfg.conf_max,
            quality_min=cfg.quality_min,
            quality_max=cfg.quality_max,
        )
        # Distinct from World's own RNG (worker pausing) so observation
        # noise and movement noise are independently seeded, reproducible
        # streams.
        self._rng = np.random.default_rng(cfg.seed + 1)
        # How realistically each camera behaves (see starling_sim.realism).
        # "demo" builds models whose every effect is a no-op, so the historical
        # behaviour is bit-for-bit preserved.
        self.realism = get_profile(cfg.realism)
        self.cameras = build_camera_models(zones, self.realism, cfg.embed_dim, cfg.seed)
        self._zone_reach = zone_reach(zones)
        self._prev_positions = self.world.positions()
        self.tick_count = 0
        self.auto_enabled = cfg.auto
        self._auto_rounds = 0  # how many auto_period_s cycles have completed
        self._auto_fired: set[tuple[int, int]] = set()
        self._scenario = scenario
        self._commands: list[dict[str, Any]] = []
        self._cmd_lock = threading.Lock()
        self.last_script: Optional[str] = None

    # -- control (thread-safe: applied at the start of the next tick) ----

    def command(self, cmd: dict[str, Any]) -> bool:
        with self._cmd_lock:
            self._commands.append(cmd)
        return True

    def _apply_commands(self) -> None:
        with self._cmd_lock:
            cmds, self._commands = self._commands, []
        for cmd in cmds:
            kind = cmd.get("kind")
            if kind == "script":
                if self.world.run_script(cmd["name"]):
                    self.last_script = cmd["name"]
            elif kind == "occlude":
                self.world.occlude(int(cmd["node_id"]), float(cmd.get("duration_s", 60.0)))
            elif kind == "clear_occlusions":
                self.world.clear_occlusions()
            elif kind == "auto":
                self.auto_enabled = bool(cmd["on"])

    def _run_auto(self) -> None:
        if not self.auto_enabled:
            return
        period = self._scenario.auto_period_s
        for i, item in enumerate(self._scenario.auto):
            round_no = int(max(0.0, self.world.t_media - item["at_s"]) // period) if period > 0 else 0
            due = item["at_s"] + round_no * period
            if self.world.t_media >= due and (i, round_no) not in self._auto_fired:
                self._auto_fired.add((i, round_no))
                if self.world.run_script(item["script"]):
                    self.last_script = item["script"]

    def status(self) -> dict[str, Any]:
        return {
            "t_media": self.world.t_media,
            "scripts": sorted(self.world.scripts),
            "auto": self.auto_enabled,
            "last_script": self.last_script,
            "active_workers": [w.worker_id for w in self.world.workers if w.active],
        }

    def tick_once(self) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
        dt = 1.0 / self.cfg.tick_hz
        self._apply_commands()
        self._run_auto()
        self.world.tick(dt)
        cur_positions = self.world.positions()
        crossings = compute_boundary_crossings(self.navmesh, self._prev_positions, cur_positions)
        self._prev_positions = cur_positions
        self.tick_count += 1

        per_node: dict[int, dict[str, Any]] = {}
        for node_id in self.world.zones:
            observations = observe_zone(
                self.world,
                node_id,
                self.perception_cfg,
                self._rng,
                camera=self.cameras.get(node_id),
                tick=self.tick_count,
                zone_reach_m=self._zone_reach.get(node_id, 0.0),
            )
            coverage = coverage_state_for_node(self.world, node_id)
            per_node[node_id] = {
                "type": "sim_tick",
                "tick": self.tick_count,
                "t_media": self.world.t_media,
                "observations": [obs_to_dict(o, p, s) for o, p, s in observations],
                "coverage": {
                    "occlusion_ratio": coverage.occlusion_ratio,
                    "illumination_score": coverage.illumination_score,
                    "detector_health": coverage.detector_health,
                },
                # JSON keys are always strings; boundary ids round-trip as
                # strings on the wire (starling_sim.coverage.SimAttestor
                # .observe_tick already expects that).
                "boundary_crossings": {str(k): v for k, v in crossings.items()},
            }

        ground_truth = {
            "type": "ground_truth",
            "tick": self.tick_count,
            "t_media": self.world.t_media,
            "workers": [
                {"worker_id": w.worker_id, "name": w.name, "x": w.pos[0], "y": w.pos[1]}
                for w in self.world.workers
                if w.active
            ],
            "occluded_nodes": [
                node_id
                for node_id in self.world.zones
                if self.world.active_occlusion(node_id) is not None
            ],
        }
        return per_node, ground_truth

    def run(self) -> None:
        publisher = SimPublisher(self.cfg.bind_endpoint)
        shutdown = {"requested": False}

        def _handle_signal(signum: int, frame: Any) -> None:
            shutdown["requested"] = True

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        wall_dt = (1.0 / self.cfg.tick_hz) / max(self.cfg.speed, 1e-6)
        server = self._start_control_server()
        try:
            while not shutdown["requested"]:
                per_node, ground_truth = self.tick_once()
                for node_id, payload in per_node.items():
                    publisher.publish(node_topic(node_id), payload)
                publisher.publish(GROUND_TRUTH_TOPIC, ground_truth)
                time.sleep(wall_dt)
        finally:
            publisher.close()
            if server is not None:
                server.shutdown()

    def _start_control_server(self) -> Optional[ThreadingHTTPServer]:
        if not self.cfg.control_port:
            return None
        runner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:  # silence stderr access log
                pass

            def _send(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                self._send(200 if self.path == "/status" else 404, runner.status() if self.path == "/status" else {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self._send(400, {"error": "invalid JSON"})
                if self.path == "/script":
                    if body.get("name") not in runner.world.scripts:
                        return self._send(404, {"error": "unknown script"})
                    runner.command({"kind": "script", "name": body["name"]})
                elif self.path == "/occlude":
                    runner.command({"kind": "occlude", "node_id": body["node_id"], "duration_s": body.get("duration_s", 60)})
                elif self.path == "/clear_occlusions":
                    runner.command({"kind": "clear_occlusions"})
                elif self.path == "/auto":
                    runner.command({"kind": "auto", "on": bool(body.get("on", True))})
                else:
                    return self._send(404, {"error": "not found"})
                self._send(200, {"ok": True})

        server = ThreadingHTTPServer(("127.0.0.1", self.cfg.control_port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True, name="sim-control").start()
        return server


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Starling simulator process")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--speed", type=float, default=None)
    parser.add_argument("--no-auto", action="store_true", help="do not run the scenario's automatic episodes")
    parser.add_argument("--realism", choices=sorted(PROFILES), default=None,
                        help="how realistically the cameras behave (default: the config's own value)")
    args = parser.parse_args(argv)

    cfg = load_simulator_config(args.config)
    if args.speed is not None:
        cfg.speed = args.speed
    if args.no_auto:
        cfg.auto = False
    if args.realism is not None:
        cfg.realism = args.realism

    SimulatorRunner(cfg).run()


if __name__ == "__main__":
    main()
