"""Tests for starling_sim.world."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point

from starling_geometry.navmesh import NavMesh
from starling_sim.scenario import Scenario, ScenarioOcclusion, ScenarioWorker
from starling_sim.world import Worker, World, load_camera_zones

WAREHOUSE_DEMO = (
    Path(__file__).resolve().parent.parent / "data" / "floorplan" / "warehouse_demo.geojson"
)


def test_load_camera_zones_returns_all_four_node_polygons():
    zones = load_camera_zones(WAREHOUSE_DEMO)
    assert set(zones.keys()) == {0, 1, 2, 3}
    assert zones[0].contains(Point(4, 12))


def test_worker_moves_at_configured_speed_along_a_straight_route():
    rng = np.random.default_rng(0)
    worker = Worker(
        worker_id=0, name="w0", route=[(0.0, 0.0), (10.0, 0.0)],
        speed_m_s=2.0, identity_vector=np.zeros(4), loop=False,
    )
    for _ in range(10):  # 10 ticks x 1s x 2m/s = 20m of travel, path is 10m
        worker.tick(1.0, rng)
    assert worker.pos == pytest.approx((10.0, 0.0))  # clamped at the end, non-looping


def test_worker_reaches_expected_position_partway_along_route():
    rng = np.random.default_rng(0)
    worker = Worker(
        worker_id=0, name="w0", route=[(0.0, 0.0), (10.0, 0.0)],
        speed_m_s=1.0, identity_vector=np.zeros(4), loop=False,
    )
    worker.tick(4.0, rng)
    assert worker.pos == pytest.approx((4.0, 0.0))


def test_looping_worker_wraps_back_toward_the_start():
    rng = np.random.default_rng(0)
    # loop=True with a two-point route auto-closes back to the start, so
    # the full loop length is 2 x 10m = 20m.
    worker = Worker(
        worker_id=0, name="w0", route=[(0.0, 0.0), (10.0, 0.0)],
        speed_m_s=1.0, identity_vector=np.zeros(4), loop=True,
    )
    worker.tick(25.0, rng)  # 25m traveled, 25 % 20 = 5m into the loop
    assert worker.pos == pytest.approx((5.0, 0.0))


def test_worker_pauses_and_does_not_move_while_paused():
    rng = np.random.default_rng(0)
    worker = Worker(
        worker_id=0, name="w0", route=[(0.0, 0.0), (10.0, 0.0)],
        speed_m_s=1.0, identity_vector=np.zeros(4), loop=False,
    )
    worker._pause_remaining_s = 3.0
    worker.tick(1.0, rng)
    assert worker.pos == pytest.approx((0.0, 0.0))
    assert worker._pause_remaining_s == pytest.approx(2.0)


def _scenario() -> Scenario:
    return Scenario(
        name="test",
        workers=[
            ScenarioWorker(worker_id=0, name="w0", route=[(4.0, 12.0), (15.0, 12.0)], loop=True),
        ],
        occlusions=[ScenarioOcclusion(node_id=1, start_s=5.0, duration_s=10.0)],
    )


def test_world_tick_advances_media_time_and_worker_positions():
    navmesh = NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)
    zones = load_camera_zones(WAREHOUSE_DEMO)
    world = World(navmesh=navmesh, zones=zones, scenario=_scenario(), embed_dim=8, seed=1)

    world.tick(1.0)
    assert world.t_media == pytest.approx(1.0)
    assert world.workers[0].pos != (4.0, 12.0)


def test_workers_in_zone_only_returns_workers_physically_inside_it():
    navmesh = NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)
    zones = load_camera_zones(WAREHOUSE_DEMO)
    world = World(navmesh=navmesh, zones=zones, scenario=_scenario(), embed_dim=8, seed=1)

    assert [w.worker_id for w in world.workers_in_zone(0)] == [0]  # starts at (4, 12), zone 0
    assert world.workers_in_zone(1) == []  # not yet in zone 1
    assert world.workers_in_zone(2) == []


def test_active_occlusion_only_within_its_scripted_window():
    navmesh = NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)
    zones = load_camera_zones(WAREHOUSE_DEMO)
    world = World(navmesh=navmesh, zones=zones, scenario=_scenario(), embed_dim=8, seed=1)

    assert world.active_occlusion(1) is None  # t_media=0, event starts at 5s
    world.t_media = 7.0
    assert world.active_occlusion(1) is not None
    world.t_media = 20.0
    assert world.active_occlusion(1) is None
    assert world.active_occlusion(0) is None  # event is scoped to node 1 only
