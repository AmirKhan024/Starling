"""The live world's simulation: routines on navmesh paths, the gate, breaks,
AGV safety stops, lens faults (starling_world.sim / .pathing)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from starling_geometry.navmesh import NavMesh
from starling_world.config import load_world_config
from starling_world.pathing import PathPlanner
from starling_world.sim import WorldSim

REPO = Path(__file__).resolve().parents[1]
CFG = load_world_config(REPO / "configs" / "world" / "warehouse.yaml")


@pytest.fixture(scope="module")
def navmesh() -> NavMesh:
    return NavMesh.from_geojson(REPO / CFG.floorplan_path, cell_size_m=CFG.navmesh_cell_m)


def _run(sim: WorldSim, seconds: float, check=None) -> None:
    dt = 1.0 / CFG.sim.tick_hz
    for _ in range(int(seconds / dt)):
        sim.tick(dt)
        if check:
            check(sim)


def test_paths_only_cross_free_space(navmesh):
    planner = PathPlanner(navmesh)
    pts = planner.plan(tuple(CFG.pois["pack_1"]), tuple(CFG.pois["dock_2"]))
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        for k in range(21):
            t = k / 20
            assert navmesh.is_free(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)


def test_everyone_arrives_through_the_gate_and_never_walks_through_obstacles(navmesh):
    sim = WorldSim(CFG, navmesh)
    passed_gate: set[str] = set()

    def check(s: WorldSim) -> None:
        for w in s.workers:
            if w.inside:
                assert navmesh.is_free(w.m.x, w.m.y), (
                    f"{w.emp.name} inside an obstacle at {(w.m.x, w.m.y)}"
                )
            if w.state == "at_gate":
                passed_gate.add(w.emp.id)

    _run(sim, 150, check)
    assert passed_gate == {e.id for e in CFG.employees}
    assert all(w.state == "working" for w in sim.workers if not w.visitor)
    assert all(w.state == "offsite" for w in sim.visitors())  # never sent in


def test_simulation_is_deterministic(navmesh):
    a, b = WorldSim(CFG, navmesh), WorldSim(CFG, navmesh)
    _run(a, 60)
    _run(b, 60)
    assert a.snapshot() == b.snapshot()


def test_a_break_takes_the_worker_out_and_back_through_the_gate(navmesh):
    sim = WorldSim(CFG, navmesh)
    _run(sim, 80)
    emp = CFG.employees[1].id
    w = next(x for x in sim.workers if x.emp.id == emp)
    assert sim.request_break(emp)
    states = set()
    _run(sim, 60 + CFG.walk.break_outside_s, lambda s: states.add(w.state))
    assert {"leaving", "offsite", "arriving", "at_gate"} <= states
    assert w.entries == 2


def test_agv_stops_for_a_person_in_front(navmesh):
    sim = WorldSim(CFG, navmesh)
    agv = sim.agvs[0]
    agv.dwell_left = 0.0
    w = sim.workers[0]
    w.state = "working"
    w.m.x, w.m.y = agv.m.x + math.sin(agv.m.heading), agv.m.y + math.cos(agv.m.heading)
    w.action, w.action_left = "idle", 1e9
    x0 = agv.m.x
    agv.tick(0.5)
    assert agv.safety_stop and agv.m.x == x0


def test_lens_fault_shows_in_ground_truth(navmesh):
    sim = WorldSim(CFG, navmesh)
    sim.block_camera(1, duration_s=5)
    assert sim.ground_truth()["occluded_nodes"] == [1]
    _run(sim, 6)
    assert sim.ground_truth()["occluded_nodes"] == []


# -- the unknown person (a visitor: not an employee) -------------------------


def _visitor_run(navmesh, warmup_s: float = 40.0):
    sim = WorldSim(CFG, navmesh)
    _run(sim, warmup_s)
    v = sim.visitors()[0]
    return sim, v


def test_visitor_is_never_an_employee():
    assert CFG.visitors, "warehouse.yaml should define at least one visitor"
    employee_ids = {e.id for e in CFG.employees}
    for vis in CFG.visitors:
        assert vis.id not in employee_ids
        assert not hasattr(vis, "arrive_at_s")
    assert CFG.visitors[0].dock_index == 1


def test_visitor_stays_offsite_until_sent(navmesh):
    sim, v = _visitor_run(navmesh, warmup_s=60)
    assert v.state == "offsite" and not v.inside
    assert v.idx == len(CFG.employees)
    assert all(g["employee_id"] != v.emp.id for g in sim.ground_truth()["workers"])
    assert not sim.request_break(v.emp.id)  # breaks are for employees only
    assert not sim.send_visitor("NOBODY")


def test_send_visitor_walks_in_through_the_dock_and_never_stops_at_the_gate(navmesh):
    sim, v = _visitor_run(navmesh)
    assert sim.send_visitor(v.emp.id)
    assert not sim.send_visitor(v.emp.id)  # already on site
    assert v.snapshot()["present"] and v.snapshot()["visitor"] is True
    _run(sim, 5)
    assert v.inside and v.state == "working"
    dock_y = CFG.dock_doors[CFG.visitors[0].dock_index].y
    assert any("dock door 2" in e["text"] for e in sim.events)
    states: set[str] = set()

    def check(s: WorldSim) -> None:
        states.add(v.state)
        if v.inside:
            assert navmesh.is_free(v.m.x, v.m.y), f"visitor inside an obstacle at {(v.m.x, v.m.y)}"
            gt = {g["employee_id"]: g for g in s.ground_truth()["workers"]}
            assert gt[v.emp.id]["visitor"] is True

    _run(sim, 150, check)
    assert "at_gate" not in states
    assert v.state == "offsite" and not v.inside
    assert v.m.x > CFG.building.width_m and v.m.y == pytest.approx(dock_y)  # out the same door
    assert all(g["employee_id"] != v.emp.id for g in sim.ground_truth()["workers"])
    assert any("has left the building" in e["text"] and "unknown" in e["text"] for e in sim.events)
    # gone for good: nobody brings them back
    _run(sim, 120)
    assert v.state == "offsite" and v.entries == 1
    # ...unless the operator sends them in again
    assert sim.send_visitor()
    _run(sim, 5)
    assert v.inside and v.entries == 2


def test_visitor_route_reaches_a_camera_less_aisle(navmesh):
    sim, v = _visitor_run(navmesh)
    sim.send_visitor()
    racks = sorted(CFG.racks, key=lambda r: r.y0)
    in_aisle = []

    def check(s: WorldSim) -> None:
        x, y = v.m.x, v.m.y
        if racks[0].x0 < x < racks[0].x1 and racks[0].y1 < y < racks[-1].y0:
            in_aisle.append(s.t)

    _run(sim, 150, check)
    assert in_aisle


def test_agv_stops_for_a_visitor(navmesh):
    sim = WorldSim(CFG, navmesh)
    agv = sim.agvs[0]
    agv.dwell_left = 0.0
    v = sim.visitors()[0]
    v.state = "working"
    v.m.x, v.m.y = agv.m.x + math.sin(agv.m.heading), agv.m.y + math.cos(agv.m.heading)
    v.action, v.action_left = "idle", 1e9
    assert v.inside
    x0 = agv.m.x
    agv.tick(0.5)
    assert agv.safety_stop and agv.m.x == x0
