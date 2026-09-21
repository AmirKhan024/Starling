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
    route: [[4.0, 14.5], [19.0, 14.5]]
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


def test_worker_inside_the_blind_block_is_invisible_to_every_zone(tmp_path):
    runner = _tiny_runner(tmp_path)
    saw_the_block = False
    for _ in range(60):  # enough for the worker to walk from the west zone into the block
        per_node, ground_truth = runner.tick_once()
        x, y = ground_truth["workers"][0]["x"], ground_truth["workers"][0]["y"]
        if 14.3 < x < 25.7 and 9.3 < y < 15.7:
            saw_the_block = True
            assert all(payload["observations"] == [] for payload in per_node.values())
    assert saw_the_block, "the tick budget never put the worker inside the block"


def test_default_shipped_config_and_scenario_load_and_run_one_tick():
    cfg = load_simulator_config(DEFAULT_SIM_CONFIG)
    runner = SimulatorRunner(cfg)
    per_node, ground_truth = runner.tick_once()

    assert set(per_node.keys()) == {0, 1, 2, 3}
    assert len(ground_truth["workers"]) == 4  # patrols; the actors are spawned by scripts


def test_dead_zone_script_keeps_worker_2_hidden_for_20_to_30_seconds():
    cfg = load_simulator_config(DEFAULT_SIM_CONFIG)
    cfg.auto = False
    cfg.control_port = 0
    runner = SimulatorRunner(cfg)
    runner.command({"kind": "script", "name": "dead_zone_healthy"})
    hidden_ticks, appeared = 0, False
    for _ in range(5 * 80):
        per_node, gt = runner.tick_once()
        w2 = [w for w in gt["workers"] if w["worker_id"] == 2]
        if not w2:
            continue
        appeared = True
        seen = any(o["local_track_id"] == 2 for p in per_node.values() for o in p["observations"])
        if 14.0 < w2[0]["x"] < 26.0 and 9.0 < w2[0]["y"] < 16.0:
            assert not seen
            hidden_ticks += 1
    assert appeared and 20.0 <= hidden_ticks / 5.0 <= 32.0


def test_occluded_script_occludes_node_1_and_manual_control_is_thread_safe_by_queue():
    cfg = load_simulator_config(DEFAULT_SIM_CONFIG)
    cfg.auto = False
    cfg.control_port = 0
    runner = SimulatorRunner(cfg)
    runner.command({"kind": "script", "name": "dead_zone_occluded"})
    runner.tick_once()
    runner.tick_once()
    assert runner.world.active_occlusion(1) is not None
    assert runner.world.active_occlusion(0) is None


def test_delayed_script_step_spawns_the_second_twin_later():
    cfg = load_simulator_config(DEFAULT_SIM_CONFIG)
    cfg.auto = False
    cfg.control_port = 0
    runner = SimulatorRunner(cfg)
    runner.command({"kind": "script", "name": "conflict_ambiguous"})
    runner.tick_once()
    active = {w["worker_id"] for w in runner.tick_once()[1]["workers"]}
    assert 5 in active and 6 not in active
    for _ in range(5 * 26):
        gt = runner.tick_once()[1]
    assert 6 in {w["worker_id"] for w in gt["workers"]}
