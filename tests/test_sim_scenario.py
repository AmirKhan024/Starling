"""Tests for starling_sim.scenario, including the shipped default demo
scenario (configs/sim/scenarios/warehouse_demo.yaml)."""

from __future__ import annotations

from pathlib import Path

from starling_sim.scenario import load_scenario

DEFAULT_SCENARIO = (
    Path(__file__).resolve().parent.parent
    / "configs" / "sim" / "scenarios" / "warehouse_demo.yaml"
)


def test_default_scenario_loads_nine_workers_actors_and_scripts():
    scenario = load_scenario(DEFAULT_SCENARIO)

    assert scenario.name == "warehouse_demo"
    assert {w.worker_id for w in scenario.workers} == {0, 1, 2, 3, 4, 5, 6, 7, 8}
    assert {w.worker_id for w in scenario.workers if not w.active} == {2, 5, 6, 7, 8}
    assert {"dead_zone_healthy", "dead_zone_occluded", "conflict_ambiguous", "conflict_resolvable"} <= set(scenario.scripts)
    assert scenario.auto and len(scenario.anchors) == 2


def test_dead_zone_script_route_goes_through_the_blind_block():
    scenario = load_scenario(DEFAULT_SCENARIO)
    route = scenario.scripts["dead_zone_healthy"][0]["assign"]["route"]
    assert any(14.5 < x < 25.5 and 9.5 < y < 15.5 for x, y in route)
    assert route[0][0] < 14.0 and any(x > 26.0 for x, _ in route)  # in from the west door, out to the east
    assert route[0] == route[-1]  # a closed circuit: a re-run continues the same person


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
