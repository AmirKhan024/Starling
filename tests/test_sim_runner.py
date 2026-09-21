"""Tests for starling_sim.runner.SimulatorRunner's pure, socket-free core
(`tick_once`), plus a smoke test of the shipped default config/scenario.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from starling_sim.config import SimulatorConfig, load_simulator_config
from starling_sim.runner import SimulatorRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SIM_CONFIG = REPO_ROOT / "configs" / "sim" / "warehouse.yaml"


def _tiny_runner(tmp_path: Path) -> SimulatorRunner:
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(
        """
name: tiny
workers:
  - worker_id: 0
    name: w0
    route: [[4.0, 12.0], [15.0, 12.0]]
    speed_m_s: 1.3
    loop: true
occlusions: []
""",
        encoding="utf-8",
    )
    cfg = SimulatorConfig(
        floorplan_path=str(REPO_ROOT / "data" / "floorplan" / "warehouse_demo.geojson"),
        scenario_path=str(scenario_path),
        tick_hz=5.0,
        embed_dim=8,
        seed=1,
    )
    return SimulatorRunner(cfg)


def test_tick_once_advances_media_time_and_returns_one_payload_per_zone(tmp_path):
    runner = _tiny_runner(tmp_path)
    per_node, ground_truth = runner.tick_once()

    assert set(per_node.keys()) == {0, 1, 2, 3}
    assert per_node[0]["t_media"] == pytest.approx(0.2)  # 1 / tick_hz
    assert ground_truth["workers"][0]["worker_id"] == 0
    assert runner.tick_count == 1


def test_tick_once_is_deterministic_given_the_same_seed(tmp_path):
    runner_a = _tiny_runner(tmp_path)
    runner_b = _tiny_runner(tmp_path)

    for _ in range(20):
        per_node_a, gt_a = runner_a.tick_once()
        per_node_b, gt_b = runner_b.tick_once()

    assert gt_a["workers"] == gt_b["workers"]
    assert per_node_a[0]["observations"] == per_node_b[0]["observations"]


def test_worker_shuttling_through_the_blind_aisle_is_invisible_to_every_zone_while_inside_it(tmp_path):
    runner = _tiny_runner(tmp_path)
    saw_the_gap = False
    for _ in range(30):  # a few seconds, enough for the shuttle worker to enter the gap
        per_node, ground_truth = runner.tick_once()
        worker_x = ground_truth["workers"][0]["x"]
        if 8.0 < worker_x < 11.0:
            saw_the_gap = True
            assert all(payload["observations"] == [] for payload in per_node.values())

    assert saw_the_gap, "test's own tick budget never put the shuttle worker inside the gap"


def test_boundary_crossing_is_reported_when_the_shuttle_worker_crosses_it(tmp_path):
    runner = _tiny_runner(tmp_path)
    any_crossing_seen = False
    for _ in range(30):
        per_node, _ = runner.tick_once()
        if any(payload["boundary_crossings"]["1"] for payload in per_node.values()):
            any_crossing_seen = True
            break
    assert any_crossing_seen


def test_default_shipped_config_and_scenario_load_and_run_one_tick():
    cfg = load_simulator_config(DEFAULT_SIM_CONFIG)
    runner = SimulatorRunner(cfg)
    per_node, ground_truth = runner.tick_once()

    assert set(per_node.keys()) == {0, 1, 2, 3}
    assert len(ground_truth["workers"]) == 5
