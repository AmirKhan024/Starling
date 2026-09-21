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
import signal
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from starling_geometry.navmesh import NavMesh
from starling_sim.config import SimulatorConfig, load_simulator_config
from starling_sim.coverage import compute_boundary_crossings, coverage_state_for_node
from starling_sim.messages import GROUND_TRUTH_TOPIC, node_topic
from starling_sim.perception import PerceptionSimConfig, obs_to_dict, observe_zone
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
        self._prev_positions = self.world.positions()
        self.tick_count = 0

    def tick_once(self) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
        dt = 1.0 / self.cfg.tick_hz
        self.world.tick(dt)
        cur_positions = self.world.positions()
        crossings = compute_boundary_crossings(self.navmesh, self._prev_positions, cur_positions)
        self._prev_positions = cur_positions
        self.tick_count += 1

        per_node: dict[int, dict[str, Any]] = {}
        for node_id in self.world.zones:
            observations = observe_zone(self.world, node_id, self.perception_cfg, self._rng)
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
        try:
            while not shutdown["requested"]:
                per_node, ground_truth = self.tick_once()
                for node_id, payload in per_node.items():
                    publisher.publish(node_topic(node_id), payload)
                publisher.publish(GROUND_TRUTH_TOPIC, ground_truth)
                time.sleep(wall_dt)
        finally:
            publisher.close()


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Starling simulator process")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--speed", type=float, default=None)
    args = parser.parse_args(argv)

    cfg = load_simulator_config(args.config)
    if args.speed is not None:
        cfg.speed = args.speed

    SimulatorRunner(cfg).run()


if __name__ == "__main__":
    main()
