"""C4 (negative evidence) on the blind-block floor plan: a camera that has
gossiped a HEALTHY coverage attestation and saw nobody rules its zone out of a
missing person's candidate region; a camera that is silent or unhealthy rules
out nothing (silence is never evidence).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from starling_attest.negative_evidence import ZONE_REGION_BASE, CandidateBelief, healthy_zone_mask
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_node.config import NegativeEvidenceConfig
from starling_proto.generated import starling_pb2

FLOORPLAN = Path(__file__).resolve().parent.parent / "data" / "floorplan" / "warehouse_demo.geojson"
GRID = None


@pytest.fixture(scope="module")
def world():
    nm = NavMesh.from_geojson(FLOORPLAN, cell_size_m=0.25)
    return nm, ReachabilityModel(nm), nm.zone_masks(FLOORPLAN)


def _att(node: int, end_s: float, conf: float = 0.9) -> starling_pb2.CoverageAttestation:
    a = starling_pb2.CoverageAttestation(
        node_id=node, region_ids=[ZONE_REGION_BASE + node], crossing_observed=False, attest_confidence=conf
    )
    a.t_start.physical_ms = int((end_s - 2) * 1000)
    a.t_end.physical_ms = int(end_s * 1000)
    return a


def _belief(world, origin):
    nm, rm, _ = world
    b = CandidateBelief(nm, rm, NegativeEvidenceConfig())
    b.initialise(origin)
    return b


def _healthy(world, atts, now=10.0):
    nm, _, zones = world
    return healthy_zone_mask(atts, zones, now, 0.7, 4.0, nm.grid.shape)


def _in(mask, zone):
    return bool((mask & zone).any())


def test_zone_masks_cover_the_four_zones_and_leave_the_block_uncovered(world):
    nm, _, zones = world
    assert set(zones) == {0, 1, 2, 3}
    ci, cj = nm.world_to_cell(16.0, 12.0)  # inside the blind block
    assert not any(z[cj, ci] for z in zones.values())
    blind_free = nm.grid & ~np.any(list(zones.values()), axis=0)
    assert 60 < nm.area_m2(blind_free) < 84  # ~12x7 m minus its racking


def test_healthy_attested_zone_is_excluded_from_the_region(world):
    nm, _, zones = world
    b = _belief(world, (15.0, 8.0))  # just inside the north zone (node 1), beside the block
    b.set_forbidden(_healthy(world, [_att(1, 9.0)]))
    b.step(10.0)
    assert not _in(b.mask(), zones[1])  # nobody can be in the healthy camera's zone
    assert b.area_m2() > 0  # ...but the region did not vanish: the blind block remains


def test_silent_or_low_confidence_zone_is_not_excluded(world):
    nm, _, zones = world
    for atts in ([], [_att(1, 9.0, conf=0.2)], [_att(1, 2.0)]):  # none / occluded / stale
        b = _belief(world, (15.0, 10.0))  # in the block, next to the north zone
        b.set_forbidden(_healthy(world, atts))
        b.step(8.0)
        assert _in(b.mask(), zones[1]), f"silence must not be counted as evidence: {atts}"


def test_region_stays_confined_to_the_blind_block_when_every_exit_is_watched(world):
    nm, _, zones = world
    all_healthy = [_att(n, 9.0) for n in range(4)]
    b = _belief(world, (19.0, 12.7))
    b.set_forbidden(_healthy(world, all_healthy))
    areas = []
    for _ in range(12):  # 60 s of hiding
        b.step(5.0)
        areas.append(b.area_m2())
    covered = np.any(list(zones.values()), axis=0)
    assert not (b.mask() & covered).any(), "region leaked into a camera-covered cell"
    blind_free = nm.area_m2(nm.grid & ~covered)
    assert max(areas) <= blind_free + 1e-6
    assert areas[-1] == pytest.approx(areas[-2])  # saturated: it does not grow beyond the block


def test_occluded_exit_lets_the_region_leak_into_only_that_zone(world):
    nm, _, zones = world
    atts = [_att(0, 9.0), _att(2, 9.0), _att(3, 9.0)]  # node 1 (north exit) is silent
    b = _belief(world, (19.0, 12.7))
    b.set_forbidden(_healthy(world, atts))
    for _ in range(12):
        b.step(5.0)
    assert _in(b.mask(), zones[1])
    for n in (0, 2, 3):
        assert not _in(b.mask(), zones[n])


def test_origin_inside_a_covered_zone_reseeds_at_the_nearest_uncovered_cells(world):
    nm, _, zones = world
    b = _belief(world, (13.5, 12.5))  # last seen in node 0's zone, beside the block
    b.set_forbidden(_healthy(world, [_att(0, 9.0)]))
    assert b.area_m2() > 0
    assert not _in(b.mask(), zones[0])
