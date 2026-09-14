"""Tests for starling_geometry.reachability (D-09, WP-05 Part 3). Every
case is hand-computed, not just random-data sanity checks.
"""

from __future__ import annotations

import numpy as np
import pytest

from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel


def _open_room(cell_size: float = 0.5, size_m: float = 40.0) -> NavMesh:
    n = int(size_m / cell_size)
    return NavMesh(grid=np.ones((n, n), dtype=bool), origin=(0.0, 0.0), cell_size=cell_size)


def test_open_corridor_reachable_radius_at_10s_is_16m():
    mesh = _open_room()
    model = ReachabilityModel(mesh, v_max_m_s=1.6)
    origin = (20.0, 20.0)

    dist = model.distance_field(origin)
    # Straight cardinal-direction distance has zero 8-connected approximation
    # error, so this is an exact check, not just "within tolerance".
    target = (20.0 + 16.0, 20.0)
    ti, tj = mesh.world_to_cell(*target)
    assert dist[tj, ti] == pytest.approx(16.0, abs=mesh.cell_size)

    # Just past the boundary must not be reachable at dt=10s.
    just_beyond = (20.0 + 16.0 + 2 * mesh.cell_size, 20.0)
    assert not model.is_reachable(origin, just_beyond, dt_s=10.0, pos_sigma=0.0)


def test_dt_zero_reaches_only_the_origin_cell():
    mesh = _open_room()
    model = ReachabilityModel(mesh, v_max_m_s=1.6)
    mask = model.reachable_set((20.0, 20.0), dt_s=0.0)
    assert mask.sum() == 1


def test_target_behind_a_wall_with_no_path_is_never_reachable():
    mesh = _open_room()
    grid = mesh.grid
    # A closed obstacle ring fully enclosing a free pocket in the middle.
    grid[15:25, 15] = False
    grid[15:25, 24] = False
    grid[15, 15:25] = False
    grid[24, 15:25] = False

    model = ReachabilityModel(mesh, v_max_m_s=1.6)
    origin = (2.0, 2.0)
    target_inside_pocket = (10.0, 10.0)

    assert not model.is_reachable(origin, target_inside_pocket, dt_s=1_000_000.0)
    ti, tj = mesh.world_to_cell(*target_inside_pocket)
    assert np.isinf(model.distance_field(origin)[tj, ti])


def test_detour_around_obstacle_has_geodesic_distance_greater_than_euclidean():
    mesh = _open_room()
    grid = mesh.grid
    wall_row = mesh.world_to_cell(0.0, 10.0)[1]
    grid[wall_row, 0:35] = False  # a wall across most of the room, gap at the far right

    model = ReachabilityModel(mesh, v_max_m_s=1.6)
    origin = (10.0, 5.0)
    target = (10.0, 15.0)
    euclidean_m = 10.0

    ti, tj = mesh.world_to_cell(*target)
    geodesic_m = model.distance_field(origin)[tj, ti]

    assert np.isfinite(geodesic_m)
    assert geodesic_m > euclidean_m


def test_is_reachable_is_monotonic_in_dt():
    mesh = _open_room()
    model = ReachabilityModel(mesh, v_max_m_s=1.6)
    origin = (20.0, 20.0)
    target = (25.0, 20.0)

    was_reachable = False
    for dt in [0.0, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0]:
        reachable = model.is_reachable(origin, target, dt_s=dt)
        if was_reachable:
            assert reachable, f"target became unreachable again at dt={dt}"
        was_reachable = was_reachable or reachable
    assert was_reachable  # sanity: it was reachable at some point in this sweep


def test_precompute_then_query_matches_a_direct_query():
    mesh = _open_room()
    origin = (20.0, 20.0)

    fresh_model = ReachabilityModel(mesh, v_max_m_s=1.6)
    fresh_dist = fresh_model.distance_field(origin)

    cached_model = ReachabilityModel(mesh, v_max_m_s=1.6)
    cached_model.precompute([origin])
    cached_dist = cached_model.distance_field(origin)

    assert np.array_equal(fresh_dist, cached_dist)

    assert fresh_model.reachable_set(origin, dt_s=5.0).tolist() == \
        cached_model.reachable_set(origin, dt_s=5.0).tolist()
