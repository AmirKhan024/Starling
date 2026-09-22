"""Tests for starling_sim.coverage."""

from __future__ import annotations

from pathlib import Path

from starling_geometry.navmesh import NavMesh
from starling_net.keys import generate_keypair, load_keys
from starling_sim.coverage import (
    CoverageState,
    SimAttestor,
    compute_boundary_crossings,
    coverage_state_for_node,
)
from starling_sim.scenario import Scenario, ScenarioOcclusion, ScenarioWorker
from starling_sim.world import World, load_camera_zones

WAREHOUSE_DEMO = (
    Path(__file__).resolve().parent.parent / "data" / "floorplan" / "warehouse_demo.geojson"
)


def _world() -> World:
    navmesh = NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)
    zones = load_camera_zones(WAREHOUSE_DEMO)
    scenario = Scenario(
        name="test",
        workers=[ScenarioWorker(worker_id=0, name="w0", route=[(4.0, 12.0), (15.0, 12.0)], loop=True)],
        occlusions=[ScenarioOcclusion(node_id=1, start_s=5.0, duration_s=10.0, occlusion_ratio=0.9, detector_health=0.3)],
    )
    return World(navmesh=navmesh, zones=zones, scenario=scenario, embed_dim=8, seed=1)


def test_coverage_state_healthy_with_no_active_occlusion():
    world = _world()
    state = coverage_state_for_node(world, node_id=0)
    assert state == CoverageState(occlusion_ratio=0.0, illumination_score=1.0, detector_health=1.0)


def test_coverage_state_degraded_during_a_scripted_occlusion():
    world = _world()
    world.t_media = 8.0  # inside the node-1 occlusion window (5..15)
    state = coverage_state_for_node(world, node_id=1)
    assert state.occlusion_ratio == 0.9
    assert state.detector_health == 0.3


def test_floor_plan_has_no_boundary_lines_so_no_crossings_are_computed():
    world = _world()
    assert compute_boundary_crossings(world.navmesh, {0: (4.0, 12.0)}, {0: (9.0, 12.0)}) == {}


def test_sim_attestor_emits_nothing_before_tick_interval_elapses():
    attestor = SimAttestor(node_id=0, watched_boundary_ids=[1], tau_attest=0.7, tick_interval_s=2.0)
    healthy = CoverageState(occlusion_ratio=0.0, illumination_score=1.0, detector_health=1.0)

    assert attestor.tick(0.0, healthy) is None
    assert attestor.tick(1.0, healthy) is None  # < 2.0s since interval start


def test_sim_attestor_emits_after_tick_interval_when_confidence_clears_threshold():
    attestor = SimAttestor(node_id=0, watched_boundary_ids=[1], tau_attest=0.7, tick_interval_s=2.0)
    healthy = CoverageState(occlusion_ratio=0.0, illumination_score=1.0, detector_health=1.0)

    attestor.tick(0.0, healthy)
    att = attestor.tick(2.5, healthy)

    assert att is not None
    assert att.node_id == 0
    assert att.crossing_observed is False
    assert att.attest_confidence == 1.0


def test_sim_attestor_stays_silent_below_threshold_with_no_crossing():
    attestor = SimAttestor(node_id=0, watched_boundary_ids=[1], tau_attest=0.7, tick_interval_s=2.0)
    degraded = CoverageState(occlusion_ratio=0.9, illumination_score=1.0, detector_health=0.3)

    attestor.tick(0.0, degraded)
    att = attestor.tick(2.5, degraded)

    assert att is None  # silence, never a false "confirmed empty"


def test_sim_attestor_still_reports_an_observed_crossing_even_when_confidence_is_low():
    attestor = SimAttestor(node_id=0, watched_boundary_ids=[1], tau_attest=0.7, tick_interval_s=2.0)
    degraded = CoverageState(occlusion_ratio=0.9, illumination_score=1.0, detector_health=0.3)

    attestor.tick(0.0, degraded)
    attestor.observe_tick({"1": True})  # boundary 1 crossed this tick
    att = attestor.tick(2.5, degraded)

    assert att is not None
    assert att.crossing_observed is True
    assert att.attest_confidence < 0.7


def test_sim_attestor_ignores_crossings_on_boundaries_it_does_not_watch():
    attestor = SimAttestor(node_id=0, watched_boundary_ids=[1], tau_attest=0.7, tick_interval_s=2.0)
    degraded = CoverageState(occlusion_ratio=0.9, illumination_score=1.0, detector_health=0.3)

    attestor.tick(0.0, degraded)
    attestor.observe_tick({"2": True})  # boundary 2, not watched by this node
    att = attestor.tick(2.5, degraded)

    assert att is None


def test_sim_attestor_signs_when_given_keys(tmp_path):
    keys_dir = tmp_path / "keys"
    generate_keypair(0, keys_dir=keys_dir)
    keys = load_keys(0, keys_dir=keys_dir)

    attestor = SimAttestor(node_id=0, watched_boundary_ids=[1], tau_attest=0.7, tick_interval_s=2.0, keys=keys)
    healthy = CoverageState(occlusion_ratio=0.0, illumination_score=1.0, detector_health=1.0)
    attestor.tick(0.0, healthy)
    att = attestor.tick(2.5, healthy)

    assert att is not None
    assert len(att.signature) > 0

    signature = att.signature
    att.signature = b""
    payload = att.SerializeToString()
    assert keys.verify(0, payload, signature)
