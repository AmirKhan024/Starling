"""The live 3D world's camera model, calibration, zones and person
localisation (starling_world.camera / .layout, starling_perception.world_pipeline)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from starling_geometry.calibration import CameraCalibration, bbox_floor_point
from starling_geometry.navmesh import NavMesh
from starling_perception.world_pipeline import (
    expected_box_height_px,
    floor_from_head,
    locate_person,
)
from starling_world.camera import PinholeCamera, segment_hits_box
from starling_world.config import load_world_config
from starling_world.layout import obstacles

REPO = Path(__file__).resolve().parents[1]
CFG = load_world_config(REPO / "configs" / "world" / "warehouse.yaml")


def _cam(n: int = 0) -> PinholeCamera:
    return PinholeCamera.from_config(CFG.camera(n), CFG.camera_frames)


def test_calibration_homography_reprojects_floor_points_exactly():
    cam = _cam(0)
    cal = cam.calibration()
    assert cal.reprojection_error < 1e-6
    for x, y in [(5.0, 7.0), (12.0, 15.0), (20.0, 4.0)]:
        ((u, v),) = cam.project(np.array([[x, y, 0.0]]))[0]
        fx, fy = cal.image_to_floor(u, v)
        assert abs(fx - x) < 1e-6 and abs(fy - y) < 1e-6


def test_committed_calibrations_match_the_world_config():
    for c in CFG.cameras:
        cal = CameraCalibration.from_yaml(
            REPO / "configs" / "calib" / "world" / f"node-{c.node_id:02d}.yaml"
        )
        expected = _cam(c.node_id).calibration()
        assert np.allclose(cal.H / cal.H[2, 2], expected.H / expected.H[2, 2], atol=1e-6), (
            f"node-{c.node_id:02d} calibration is stale: run scripts/build_world_floorplan.py"
        )


def test_head_based_localisation_recovers_a_person_whose_feet_are_hidden():
    cam = _cam(2)
    cal = cam.calibration()
    x, y, top = 8.0, 12.0, 1.80
    (uf, vf), (uh, vh) = cam.project(np.array([[x, y, 0.0], [x, y, top]]))[0]
    # a box from the head down to the knees only (legs hidden behind a pallet)
    knee_v = cam.project(np.array([[x, y, 0.55]]))[0][0][1]
    bbox = (int(uh) - 15, int(vh), int(uh) + 15, int(knee_v))
    foot_only = cal.image_to_floor(*bbox_floor_point(bbox))
    assert np.hypot(foot_only[0] - x, foot_only[1] - y) > 1.0  # the naive foot point is badly off
    (px, py), sigma, hidden = locate_person(cal, bbox, cam.height, top, 0.82)
    assert hidden
    assert np.hypot(px - x, py - y) < 0.15
    assert sigma >= 0.5
    head = floor_from_head(cal, bbox, top)
    assert head is not None


def test_a_fully_visible_person_keeps_the_foot_point():
    cam = _cam(1)
    cal = cam.calibration()
    x, y = 22.0, 6.0
    (uf, vf), (uh, vh) = cam.project(np.array([[x, y, 0.0], [x, y, 1.8]]))[0]
    bbox = (int(uf) - 15, int(vh), int(uf) + 15, int(round(vf)))
    exp = expected_box_height_px(cal, x, y, 1.8)
    assert exp is not None and abs(exp - (vf - vh)) < 1.0
    (px, py), _, hidden = locate_person(cal, bbox, cam.height, 1.8, 0.82)
    assert not hidden
    assert np.hypot(px - x, py - y) < 0.1


def test_segment_box_intersection():
    lo, hi = np.array([0.0, 0.0, 0.0]), np.array([1.0, 1.0, 1.0])
    assert segment_hits_box(np.array([-1, 0.5, 0.5]), np.array([2, 0.5, 0.5]), lo, hi)
    assert not segment_hits_box(np.array([-1, 0.5, 2.0]), np.array([2, 0.5, 2.0]), lo, hi)


def _zones() -> tuple[dict, NavMesh]:
    nm = NavMesh.from_geojson(REPO / CFG.floorplan_path, cell_size_m=CFG.navmesh_cell_m)
    return nm.zone_masks(REPO / CFG.floorplan_path), nm


def test_zones_are_disjoint_and_leave_the_aisle_cores_blind():
    zones, nm = _zones()
    assert sorted(zones) == [0, 1, 2, 3]
    stack = np.stack(list(zones.values()))
    assert (stack.sum(axis=0) <= 1).all(), "a floor cell may belong to at most one camera's zone"
    for name in ("aisle1_a", "aisle1_b", "aisle2_a", "aisle2_b"):
        x, y = CFG.pois[name]
        i, j = nm.world_to_cell(x, y)
        assert not stack[:, j, i].any(), f"{name} must not be covered by any camera"


def test_the_gate_is_inside_the_gate_cameras_zone():
    zones, nm = _zones()
    g = CFG.entrance.gate
    i, j = nm.world_to_cell(g.x, g.y)
    assert zones[g.node_id][j, i]


def test_every_obstacle_is_cut_out_of_the_walkable_floor():
    nm = NavMesh.from_geojson(REPO / CFG.floorplan_path, cell_size_m=CFG.navmesh_cell_m)
    for ob in obstacles(CFG):
        assert not nm.is_free((ob.x0 + ob.x1) / 2, (ob.y0 + ob.y1) / 2)


@pytest.mark.parametrize("node", [0, 1, 2, 3])
def test_generated_node_config_matches(node):
    from starling_node.config import load_node_config

    c = load_node_config(REPO / "configs" / "nodes" / "world" / f"node-{node:02d}.yaml")
    assert c.source == "world"
    assert c.perception.embed_dim == 96
    assert (c.world.gate is not None) == (node == CFG.entrance.gate.node_id)
    assert len(c.net.neighbours) == 2  # a ring, never a full mesh
