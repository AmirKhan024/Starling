"""Tests for data/floorplan/warehouse_demo.geojson: the 4-zone warehouse floor
the sim-driven demo runs on, with a 12x7 m UNCOVERED block (with three short
racking aisles) in the middle whose every exit borders a camera zone.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel

WAREHOUSE_DEMO = Path(__file__).resolve().parent.parent / "data" / "floorplan" / "warehouse_demo.geojson"


def _mesh() -> NavMesh:
    return NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)


def test_warehouse_demo_loads_with_plausible_free_cell_count():
    mesh = _mesh()
    assert 0.5 < mesh.grid.sum() / mesh.grid.size < 1.0


def test_is_free_in_each_zone_the_blind_block_and_its_racking():
    mesh = _mesh()
    assert mesh.is_free(5.0, 12.0)  # node 0 (west)
    assert mesh.is_free(20.0, 6.0)  # node 1 (north)
    assert mesh.is_free(20.0, 18.0)  # node 2 (south)
    assert mesh.is_free(33.0, 12.0)  # node 3 (east)
    assert mesh.is_free(19.0, 14.5)  # inside the blind block, in an aisle
    assert not mesh.is_free(2.7, 5.0)  # zone racking
    assert not mesh.is_free(17.0, 11.0)  # block racking A
    assert not mesh.is_free(-5.0, -5.0)


def test_blind_block_is_uncovered_and_about_12_by_7_metres():
    mesh = _mesh()
    zones = mesh.zone_masks(WAREHOUSE_DEMO)
    assert set(zones) == {0, 1, 2, 3}
    covered = np.any(list(zones.values()), axis=0)
    blind = mesh.grid & ~covered
    assert 60 < mesh.area_m2(blind) < 84
    ci, cj = mesh.world_to_cell(19.0, 12.5)
    assert blind[cj, ci]
    ys, xs = np.nonzero(blind)
    assert 11.5 <= (xs.max() - xs.min()) * mesh.cell_size <= 12.5
    assert 6.5 <= (ys.max() - ys.min()) * mesh.cell_size <= 7.5


def test_every_exit_of_the_blind_block_borders_a_camera_zone():
    mesh = _mesh()
    zones = mesh.zone_masks(WAREHOUSE_DEMO)
    covered = np.any(list(zones.values()), axis=0)
    blind = mesh.grid & ~covered
    # Dilate the blind block by one cell: every free neighbour must be covered.
    grown = blind.copy()
    grown[1:, :] |= blind[:-1, :]
    grown[:-1, :] |= blind[1:, :]
    grown[:, 1:] |= blind[:, :-1]
    grown[:, :-1] |= blind[:, 1:]
    ring = grown & mesh.grid & ~blind
    assert ring.any() and (ring & covered).sum() == ring.sum()


def test_a_worker_can_walk_from_zone_0_through_the_block_into_zone_3():
    mesh = _mesh()
    model = ReachabilityModel(mesh, v_max_m_s=1.4)
    assert model.is_reachable((5.0, 14.5), (19.0, 14.5), dt_s=15.0)
    assert model.is_reachable((5.0, 14.5), (33.0, 12.0), dt_s=40.0)
    assert not model.is_reachable((5.0, 14.5), (33.0, 12.0), dt_s=5.0)
