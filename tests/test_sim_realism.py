"""Tests for starling_sim.realism: the camera-imperfection profiles that make
the simulated identity problem as hard as a real one.

The two properties that matter most:
  * `demo` must be a genuine no-op, so every existing scenario, test and review
    moment behaves exactly as it did before this module existed;
  * `realistic` must be calibrated to published multi-camera re-ID separability
    — if the same/different appearance distributions do not overlap, the
    resolver's matching logic is never actually tested by the demo.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from starling_sim.identity import make_identity_vectors
from starling_sim.perception import PerceptionSimConfig, observe_zone
from starling_sim.realism import (
    PROFILES,
    build_camera_models,
    get_profile,
    zone_mount_points,
    zone_reach,
)
from starling_sim.scenario import Scenario, ScenarioWorker
from starling_sim.world import World, load_camera_zones
from starling_geometry.navmesh import NavMesh

REPO = Path(__file__).resolve().parent.parent
FLOORPLAN = REPO / "data" / "floorplan" / "warehouse_demo.geojson"
EMBED_DIM = 64


@pytest.fixture(scope="module")
def zones():
    return load_camera_zones(FLOORPLAN)


def _cams(zones, profile_name: str):
    return build_camera_models(zones, get_profile(profile_name), EMBED_DIM, seed=1234)


# ── profiles ──────────────────────────────────────────────────────────────


def test_demo_profile_is_a_no_op():
    p = get_profile("demo")
    assert p.camera_bias == 0.0
    assert p.uniform_similarity == 0.0
    assert p.pos_noise_per_m == 0.0
    assert p.track_break_prob == 0.0 and p.track_swap_prob == 0.0
    assert p.false_positive_prob == 0.0
    assert p.miss_run_ticks == (1, 1)


def test_unknown_profile_is_rejected_by_name():
    with pytest.raises(ValueError, match="unknown realism profile"):
        get_profile("nonsense")
    assert {"demo", "realistic", "harsh"} <= set(PROFILES)


# ── appearance: the headline property ─────────────────────────────────────


def _separability(zones, profile_name: str, samples: int = 1200):
    profile = get_profile(profile_name)
    cams = _cams(zones, profile_name)
    ids = sorted(cams)
    vecs = make_identity_vectors(6, EMBED_DIM, seed=1234, uniform_similarity=profile.uniform_similarity)
    rng = np.random.default_rng(7)
    same, diff = [], []
    for _ in range(samples):
        a, b = rng.choice(6, size=2, replace=False)
        ca, cb = rng.choice(ids, size=2, replace=False)
        da, db = float(rng.uniform(1, 8)), float(rng.uniform(1, 8))
        ea = cams[ca].observed_embedding(vecs[a], da, 0.05)
        same.append(float(ea @ cams[cb].observed_embedding(vecs[a], db, 0.05)))
        diff.append(float(ea @ cams[cb].observed_embedding(vecs[b], db, 0.05)))
    return np.array(same), np.array(diff)


def test_demo_appearance_is_perfectly_separable_which_is_the_problem(zones):
    """Documents the baseline this module exists to fix: under `demo` the two
    distributions do not overlap at all, so any threshold works and the
    resolver's appearance matching is never under pressure."""
    same, diff = _separability(zones, "demo")
    assert same.mean() - diff.mean() > 0.7
    assert diff.max() < same.min()  # zero overlap


def test_realistic_appearance_matches_published_reid_separability(zones):
    """same/different cosine gap inside the published multi-camera re-ID range
    (~0.15-0.25) WITH substantial overlap — i.e. genuinely confusable."""
    same, diff = _separability(zones, "realistic")
    gap = same.mean() - diff.mean()
    assert 0.15 <= gap <= 0.30, f"gap {gap:.3f} outside the published range"
    assert 0.40 <= same.mean() <= 0.75, f"same-person {same.mean():.3f} outside published range"
    assert 0.20 <= diff.mean() <= 0.55, f"different-people {diff.mean():.3f} outside published range"
    assert (diff > same.min()).mean() > 0.20, "distributions must genuinely overlap"


def test_same_camera_is_easier_than_cross_camera(zones):
    """The core real-world effect: a person looks more like themselves to the
    SAME camera than across two cameras with different viewpoints."""
    cams = _cams(zones, "realistic")
    vecs = make_identity_vectors(4, EMBED_DIM, seed=99, uniform_similarity=0.5)
    rng = np.random.default_rng(3)
    intra, cross = [], []
    for _ in range(600):
        a = int(rng.integers(0, 4))
        e0 = cams[0].observed_embedding(vecs[a], 3.0, 0.05)
        intra.append(float(e0 @ cams[0].observed_embedding(vecs[a], 3.0, 0.05)))
        cross.append(float(e0 @ cams[2].observed_embedding(vecs[a], 3.0, 0.05)))
    assert np.mean(intra) > np.mean(cross) + 0.03


# ── geometry ──────────────────────────────────────────────────────────────


def test_position_error_grows_with_distance_from_the_camera(zones):
    cam = _cams(zones, "realistic")[0]
    mx, my = cam.mount_xy
    near = [cam.observed_position((mx + 1.0, my), 0.08)[1] for _ in range(20)]
    far = [cam.observed_position((mx + 9.0, my), 0.08)[1] for _ in range(20)]
    assert np.mean(far) > np.mean(near) * 1.5
    # and the sigma handed to the node reflects the range, not the realisation
    assert all(s > 0 for s in near + far)


def test_demo_position_error_is_flat_with_distance(zones):
    cam = _cams(zones, "demo")[0]
    mx, my = cam.mount_xy
    near = cam.observed_position((mx + 1.0, my), 0.08)[1]
    far = cam.observed_position((mx + 9.0, my), 0.08)[1]
    assert near == far == 0.08


def test_confidence_falls_off_toward_the_edge_of_a_zone(zones):
    reach = zone_reach(zones)
    cam = _cams(zones, "realistic")[0]
    assert cam.confidence_scale(0.0, reach[0]) == 1.0
    assert cam.confidence_scale(reach[0], reach[0]) < 0.8
    demo_cam = _cams(zones, "demo")[0]
    assert demo_cam.confidence_scale(reach[0], reach[0]) == 1.0


def test_mount_points_are_inside_their_own_zone(zones):
    from shapely.geometry import Point

    for node_id, (x, y) in zone_mount_points(zones).items():
        assert zones[node_id].contains(Point(x, y)), f"camera {node_id} mount outside its zone"


# ── detection ─────────────────────────────────────────────────────────────


def test_misses_come_in_runs_not_independent_coin_flips(zones):
    """A person behind racking is missed for several consecutive frames."""
    cam = _cams(zones, "realistic")[0]
    missed = [cam.should_miss(0, t, base_miss_prob=0.05) for t in range(600)]
    runs, cur = [], 0
    for m in missed:
        if m:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    assert runs, "no misses at all in 600 ticks"
    assert max(runs) >= 2, "misses never clustered — that is the demo behaviour, not realistic"


def _miss_runs(cam, base_miss_prob: float, ticks: int) -> list[int]:
    runs, cur = [], 0
    for t in range(ticks):
        if cam.should_miss(0, t, base_miss_prob):
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    return runs


def test_demo_misses_stay_independent_while_realistic_ones_cluster(zones):
    """`demo` re-rolls every tick (so runs are just the geometric tail of
    independent flips); `realistic` commits to an occlusion lasting several
    ticks. Compared at the same base rate, realistic runs are clearly longer."""
    rate = 0.03  # the shipped detection_miss_prob
    demo_runs = _miss_runs(_cams(zones, "demo")[0], rate, 4000)
    real_runs = _miss_runs(_cams(zones, "realistic")[0], rate, 4000)
    assert demo_runs and real_runs
    assert np.mean(demo_runs) < 1.3, "demo misses should almost always be single ticks"
    assert np.mean(real_runs) > 2.5 * np.mean(demo_runs)


# ── local tracker ─────────────────────────────────────────────────────────


def test_demo_keeps_the_worker_id_as_the_local_track_id(zones):
    cam = _cams(zones, "demo")[0]
    assert [cam.track_id_for(4) for _ in range(50)] == [4] * 50


def test_realistic_tracker_breaks_tracks_and_never_reuses_the_worker_id(zones):
    cam = _cams(zones, "realistic")[0]
    ids = {cam.track_id_for(4) for _ in range(800)}
    assert len(ids) > 1, "the tracker never fragmented"
    assert 4 not in ids, "a local track id must not leak the simulator's worker id"


def test_local_track_ids_are_disjoint_between_cameras(zones):
    cams = _cams(zones, "realistic")
    seen: set[int] = set()
    for cam in cams.values():
        ids = {cam.track_id_for(w) for w in range(5) for _ in range(40)}
        assert not (ids & seen), "two cameras produced the same local track id"
        seen |= ids


def test_tracker_swaps_ids_when_two_people_are_close(zones):
    cam = _cams(zones, "realistic")[0]
    close = {0: (5.0, 5.0), 1: (5.4, 5.0)}
    swaps = sum(len(cam.maybe_swap_tracks(close)) for _ in range(300))
    assert swaps > 0
    apart = {0: (2.0, 2.0), 1: (12.0, 20.0)}
    assert sum(len(cam.maybe_swap_tracks(apart)) for _ in range(300)) == 0


# ── end to end through observe_zone ───────────────────────────────────────


def _world(positions: dict[int, tuple[float, float]]):
    navmesh = NavMesh.from_geojson(FLOORPLAN, cell_size_m=0.25)
    zones = load_camera_zones(FLOORPLAN)
    scenario = Scenario(
        name="t",
        workers=[
            ScenarioWorker(worker_id=w, name=f"w{w}", route=[p, p], speed_m_s=0.0, loop=False)
            for w, p in positions.items()
        ],
    )
    return World(navmesh=navmesh, zones=zones, scenario=scenario, embed_dim=EMBED_DIM, seed=5)


def test_observe_zone_without_a_camera_model_is_unchanged(zones):
    """The historical call signature still works and still yields worker-id
    track ids — this is what keeps every pre-existing test valid."""
    world = _world({0: (5.0, 12.0)})
    cfg = PerceptionSimConfig(detection_miss_prob=0.0)
    obs = observe_zone(world, 0, cfg, np.random.default_rng(0))
    assert len(obs) == 1
    assert obs[0][0].local_track_id == 0
    assert obs[0][2] == cfg.pos_noise_sigma_m


def test_observe_zone_with_a_realistic_camera_degrades_the_observation(zones):
    world = _world({0: (5.0, 12.0)})
    cfg = PerceptionSimConfig(detection_miss_prob=0.0)
    cam = _cams(zones, "realistic")[0]
    obs = observe_zone(world, 0, cfg, np.random.default_rng(0), camera=cam, tick=0, zone_reach_m=zone_reach(zones)[0])
    real = [o for o in obs if o[0].local_track_id != 0]
    assert real, "expected a realistic (non-worker-id) track id"
    o, pos, sigma = real[0]
    assert sigma > cfg.pos_noise_sigma_m  # distance-dependent
    assert 0.0 < o.conf <= 1.0 and 0.0 < o.quality <= 1.0


def test_false_positives_appear_only_under_a_realistic_profile(zones):
    world = _world({0: (5.0, 12.0)})
    cfg = PerceptionSimConfig(detection_miss_prob=0.0)
    reach = zone_reach(zones)[0]
    harsh_cam = _cams(zones, "harsh")[0]
    counts = [
        len(observe_zone(world, 0, cfg, np.random.default_rng(t), camera=harsh_cam, tick=t, zone_reach_m=reach))
        for t in range(400)
    ]
    assert max(counts) >= 2, "a phantom detection never appeared under `harsh`"

    demo_cam = _cams(zones, "demo")[0]
    demo_counts = [
        len(observe_zone(world, 0, cfg, np.random.default_rng(t), camera=demo_cam, tick=t, zone_reach_m=reach))
        for t in range(400)
    ]
    assert max(demo_counts) == 1, "`demo` must never invent a detection"
