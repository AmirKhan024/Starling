"""Tests for starling_sim.scenario, including the shipped default demo
scenario (configs/sim/scenarios/warehouse_demo.yaml)."""

from __future__ import annotations

from pathlib import Path

from starling_sim.scenario import load_scenario

DEFAULT_SCENARIO = (
    Path(__file__).resolve().parent.parent
    / "configs" / "sim" / "scenarios" / "warehouse_demo.yaml"
)


def test_default_scenario_loads_five_workers_and_at_least_one_occlusion():
    scenario = load_scenario(DEFAULT_SCENARIO)

    assert scenario.name == "warehouse_demo"
    assert len(scenario.workers) == 5
    assert {w.worker_id for w in scenario.workers} == {0, 1, 2, 3, 4}
    assert len(scenario.occlusions) >= 1


def test_default_scenario_has_a_worker_whose_route_crosses_the_blind_aisle():
    scenario = load_scenario(DEFAULT_SCENARIO)
    # The blind aisle is x in [8, 11] (data/floorplan/warehouse_demo.geojson).
    # At least one worker's route must have waypoints on both sides of it.
    crosses = any(
        any(x < 8.0 for x, _ in w.route) and any(x > 11.0 for x, _ in w.route)
        for w in scenario.workers
    )
    assert crosses


def test_scenario_round_trips_worker_fields(tmp_path):
    yaml_path = tmp_path / "scenario.yaml"
    yaml_path.write_text(
        """
name: test_scenario
workers:
  - worker_id: 0
    name: alice
    route: [[1.0, 2.0], [3.0, 4.0]]
    speed_m_s: 0.9
    pause_prob_per_tick: 0.1
    pause_duration_s: [2.0, 4.0]
    loop: false
occlusions:
  - node_id: 2
    start_s: 10.0
    duration_s: 5.0
    occlusion_ratio: 0.8
    detector_health: 0.4
""",
        encoding="utf-8",
    )

    scenario = load_scenario(yaml_path)

    assert scenario.name == "test_scenario"
    worker = scenario.workers[0]
    assert worker.name == "alice"
    assert worker.route == [(1.0, 2.0), (3.0, 4.0)]
    assert worker.speed_m_s == 0.9
    assert worker.pause_prob_per_tick == 0.1
    assert worker.pause_duration_s == (2.0, 4.0)
    assert worker.loop is False

    occlusion = scenario.occlusions[0]
    assert occlusion.node_id == 2
    assert occlusion.start_s == 10.0
    assert occlusion.duration_s == 5.0
    assert occlusion.occlusion_ratio == 0.8
    assert occlusion.detector_health == 0.4
