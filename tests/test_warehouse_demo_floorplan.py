"""Tests for data/floorplan/warehouse_demo.geojson (STATUS.md Step 2): the
4-zone warehouse floor the sim-driven demo runs on. Mirrors
tests/test_navmesh.py's pattern for demo_site.geojson, plus a reachability
check across the deliberate blind aisle (boundary_id 1/2) that the C4
negative-evidence demo moment depends on.
"""

from __future__ import annotations

from pathlib import Path

from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel

WAREHOUSE_DEMO = (
    Path(__file__).resolve().parent.parent / "data" / "floorplan" / "warehouse_demo.geojson"
)


def test_warehouse_demo_loads_with_plausible_free_cell_count():
    mesh = NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)
    total_cells = mesh.grid.size
    free_cells = int(mesh.grid.sum())

    assert total_cells > 0
    assert 0.5 < (free_cells / total_cells) < 1.0


def test_is_free_in_each_zone_the_blind_aisle_and_the_uncovered_strip():
    mesh = NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)

    assert mesh.is_free(4.0, 12.0) is True  # node 0's zone, clear of racking
    assert mesh.is_free(2.7, 5.0) is False  # inside racking_node0_a
    assert mesh.is_free(9.5, 12.5) is True  # inside the blind aisle itself
    assert mesh.is_free(15.0, 12.0) is True  # node 1's zone
    assert mesh.is_free(21.0, 12.0) is True  # uncovered strip between zone 1 and zone 2
    assert mesh.is_free(28.0, 12.0) is True  # node 2's zone
    assert mesh.is_free(37.0, 12.0) is False  # inside racking_node3
    assert mesh.is_free(-5.0, -5.0) is False  # outside the grid entirely


def test_both_blind_aisle_boundaries_rasterise_to_nonempty_cell_lists():
    mesh = NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)

    assert set(mesh.boundaries.keys()) == {1, 2}
    for boundary_id, cells in mesh.boundaries.items():
        assert len(cells) > 0, f"boundary {boundary_id} rasterised to no cells"


def test_blind_aisle_boundary_splits_floor_into_two_components():
    mesh = NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)

    # A point in node 0's zone is "beyond" the west exit boundary from the
    # gap's perspective, and a point deep in node 0's zone is not beyond
    # its own boundary from itself.
    beyond_from_gap = mesh.cells_beyond(1, (9.5, 12.5))
    ni, nj = mesh.world_to_cell(4.0, 12.0)  # a cell inside node 0's zone
    assert beyond_from_gap[nj, ni]

    beyond_from_zone0 = mesh.cells_beyond(1, (4.0, 12.0))
    gi, gj = mesh.world_to_cell(9.5, 12.5)
    assert beyond_from_zone0[gj, gi]


def test_worker_can_walk_from_zone0_across_the_blind_aisle_into_zone1():
    mesh = NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)
    model = ReachabilityModel(mesh, v_max_m_s=1.4)

    origin = (4.0, 12.0)  # inside node 0's zone
    into_gap = (9.5, 12.5)  # inside the blind aisle
    across_gap = (15.0, 12.0)  # inside node 1's zone, on the far side

    assert model.is_reachable(origin, into_gap, dt_s=5.0)
    assert model.is_reachable(origin, across_gap, dt_s=30.0)

    # But not instantly — the two zones are genuinely separated by the aisle.
    assert not model.is_reachable(origin, across_gap, dt_s=1.0, pos_sigma=0.0)
