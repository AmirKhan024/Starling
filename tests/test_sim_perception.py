"""Tests for starling_sim.perception."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from starling_geometry.navmesh import NavMesh
from starling_sim.perception import PerceptionSimConfig, dict_to_obs, obs_to_dict, observe_zone
from starling_sim.scenario import Scenario, ScenarioWorker
from starling_sim.world import World, load_camera_zones

WAREHOUSE_DEMO = (
    Path(__file__).resolve().parent.parent / "data" / "floorplan" / "warehouse_demo.geojson"
)


def _world_with_workers(routes: dict[int, list[tuple[float, float]]]) -> World:
    navmesh = NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)
    zones = load_camera_zones(WAREHOUSE_DEMO)
    scenario = Scenario(
        name="test",
        workers=[
            ScenarioWorker(worker_id=wid, name=f"w{wid}", route=route, loop=False)
            for wid, route in routes.items()
        ],
    )
    return World(navmesh=navmesh, zones=zones, scenario=scenario, embed_dim=8, seed=1)


def test_observe_zone_only_returns_workers_physically_inside_that_zone():
    world = _world_with_workers({0: [(4.0, 12.0)], 1: [(15.0, 12.0)]})
    cfg = PerceptionSimConfig(detection_miss_prob=0.0)
    rng = np.random.default_rng(0)

    zone0_obs = observe_zone(world, node_id=0, cfg=cfg, rng=rng)
    zone1_obs = observe_zone(world, node_id=1, cfg=cfg, rng=rng)

    assert [o.local_track_id for o, _, _ in zone0_obs] == [0]
    assert [o.local_track_id for o, _, _ in zone1_obs] == [1]


def test_observe_zone_worker_in_the_blind_gap_is_seen_by_no_zone():
    world = _world_with_workers({2: [(9.5, 12.5)]})  # inside the blind aisle
    cfg = PerceptionSimConfig(detection_miss_prob=0.0)
    rng = np.random.default_rng(0)

    for node_id in (0, 1, 2, 3):
        assert observe_zone(world, node_id=node_id, cfg=cfg, rng=rng) == []


def test_detection_miss_probability_of_one_never_emits_an_observation():
    world = _world_with_workers({0: [(4.0, 12.0)]})
    cfg = PerceptionSimConfig(detection_miss_prob=1.0)
    rng = np.random.default_rng(0)

    assert observe_zone(world, node_id=0, cfg=cfg, rng=rng) == []


def test_observed_position_is_noisy_around_the_true_position():
    world = _world_with_workers({0: [(4.0, 12.0)]})
    cfg = PerceptionSimConfig(detection_miss_prob=0.0, pos_noise_sigma_m=0.2)
    rng = np.random.default_rng(0)

    (obs, world_pos, pos_sigma), = observe_zone(world, node_id=0, cfg=cfg, rng=rng)

    assert pos_sigma == pytest.approx(0.2)
    assert world_pos != (4.0, 12.0)
    assert abs(world_pos[0] - 4.0) < 2.0  # sane bound, not a stray outlier
    assert abs(world_pos[1] - 12.0) < 2.0


def test_obs_to_dict_and_dict_to_obs_round_trip():
    world = _world_with_workers({0: [(4.0, 12.0)]})
    cfg = PerceptionSimConfig(detection_miss_prob=0.0)
    rng = np.random.default_rng(0)

    (obs, world_pos, pos_sigma), = observe_zone(world, node_id=0, cfg=cfg, rng=rng)
    d = obs_to_dict(obs, world_pos, pos_sigma)

    restored_obs, restored_pos, restored_sigma = dict_to_obs(d)

    assert restored_obs.local_track_id == obs.local_track_id
    assert restored_obs.conf == pytest.approx(obs.conf)
    assert restored_obs.quality == pytest.approx(obs.quality)
    assert restored_obs.t_media == pytest.approx(obs.t_media)
    assert np.allclose(restored_obs.embedding, obs.embedding, atol=1e-5)
    assert restored_pos == pytest.approx(world_pos)
    assert restored_sigma == pytest.approx(pos_sigma)
