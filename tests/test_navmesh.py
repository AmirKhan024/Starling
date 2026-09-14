"""Tests for starling_geometry.navmesh (WP-05 Part 2)."""

from __future__ import annotations

from pathlib import Path

from starling_geometry.navmesh import NavMesh

DEMO_SITE = Path(__file__).resolve().parent.parent / "data" / "floorplan" / "demo_site.geojson"

# 20m x 4m corridor minus two 2x1.5m obstacle blocks (see the geojson's own
# scale note): 80 - 3 - 3 = 74 sq metres of true free space.
EXPECTED_FREE_AREA_M2 = 74.0


def test_demo_site_loads_with_plausible_free_cell_count():
    mesh = NavMesh.from_geojson(DEMO_SITE, cell_size_m=0.25)
    total_cells = mesh.grid.size
    free_cells = int(mesh.grid.sum())

    assert total_cells > 0
    # Free space should be the majority of the bounding box (obstacles are
    # a small fraction of the 80 sq m corridor) but not literally everything.
    assert 0.5 < (free_cells / total_cells) < 1.0


def test_is_free_true_in_corridor_false_inside_obstacle():
    mesh = NavMesh.from_geojson(DEMO_SITE, cell_size_m=0.25)

    assert mesh.is_free(10.0, 2.0) is True  # mid-corridor, inside the gap
    assert mesh.is_free(4.0, 0.5) is False  # inside racking_zone_a
    assert mesh.is_free(16.0, 3.5) is False  # inside racking_zone_b
    assert mesh.is_free(-5.0, -5.0) is False  # outside the grid entirely


def test_world_to_cell_cell_to_world_round_trip_within_half_a_cell():
    mesh = NavMesh.from_geojson(DEMO_SITE, cell_size_m=0.25)

    for x, y in [(1.0, 1.0), (10.3, 2.1), (18.9, 3.9)]:
        i, j = mesh.world_to_cell(x, y)
        wx, wy = mesh.cell_to_world(i, j)
        assert abs(wx - x) <= mesh.cell_size / 2 + 1e-9
        assert abs(wy - y) <= mesh.cell_size / 2 + 1e-9


def test_area_m2_matches_polygon_area_within_5_percent():
    mesh = NavMesh.from_geojson(DEMO_SITE, cell_size_m=0.1)  # finer grid, less quantisation error
    area = mesh.area_m2()

    assert abs(area - EXPECTED_FREE_AREA_M2) / EXPECTED_FREE_AREA_M2 < 0.05


def test_both_labelled_boundaries_rasterise_to_nonempty_cell_lists():
    mesh = NavMesh.from_geojson(DEMO_SITE, cell_size_m=0.25)

    assert set(mesh.boundaries.keys()) == {1, 2}
    for boundary_id, cells in mesh.boundaries.items():
        assert len(cells) > 0, f"boundary {boundary_id} rasterised to no cells"


def test_render_returns_an_image_of_the_grid_shape():
    mesh = NavMesh.from_geojson(DEMO_SITE, cell_size_m=0.25)
    img = mesh.render()
    height, width = mesh.grid.shape
    assert img.size == (width, height)
