"""Smoke test for scripts/run_deadzone_experiment.py (WP-09 Part 3's
headline experiment). Runs the real sweep over the real demo floor plan —
deterministic (seeded RNG) and fast — and checks the numbers it produces
are internally sane, without regenerating plots/docs (that's `main()`'s
job, exercised by actually running the script, not by this test).
"""

from __future__ import annotations

import scripts.run_deadzone_experiment as dz
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel


def test_sweep_is_internally_consistent():
    navmesh = NavMesh.from_geojson(dz.DEMO_SITE, cell_size_m=0.25)
    reachability = ReachabilityModel(navmesh, v_max_m_s=1.6)

    rows, without, _windows, _t_origin, _t_gap_exit = dz.run_sweep(navmesh, reachability)

    assert without.area_m2, "positive-evidence-only arm produced no data"
    assert len(rows) == len(dz.TAU_SWEEP)

    for row in rows:
        assert 0.0 <= row["region_reduction_pct"] <= 100.0
        assert 0.0 <= row["false_exclusion_rate"] <= 1.0
        assert 0.0 <= row["attestation_accuracy"] <= 1.0
        assert row["area_with_m2"] <= row["area_without_m2"] + 1e-9

    # A low tau admits at least as many windows as a high tau — the sweep
    # is over the same fixed set of generated attestations each time.
    admitted = [row["n_admitted_attestations"] for row in rows]
    assert admitted == sorted(admitted, reverse=True)


def test_negative_evidence_reduces_area_at_the_default_threshold():
    navmesh = NavMesh.from_geojson(dz.DEMO_SITE, cell_size_m=0.25)
    reachability = ReachabilityModel(navmesh, v_max_m_s=1.6)

    rows, _without, _windows, _t_origin, _t_gap_exit = dz.run_sweep(navmesh, reachability)
    default_row = next(r for r in rows if r["tau_attest"] == 0.7)

    assert default_row["region_reduction_pct"] > 0.0
