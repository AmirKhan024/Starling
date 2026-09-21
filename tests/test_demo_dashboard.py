"""Tests for the simulator demo dashboard (apps/demo_dashboard): observer
isolation (CLAUDE.md rules 2 and 8), the testability contract the automated
review relies on, and the candidate-region logic — none of it needs a running
mesh.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.demo_dashboard.config import DemoDashboardConfig
from apps.demo_dashboard.engine import DashboardEngine, _Belief
from starling_attest.negative_evidence import CandidateBelief
from starling_net.keys import generate_keypair
from starling_proto.generated import starling_pb2

REPO = Path(__file__).resolve().parent.parent
DASH_DIR = REPO / "apps" / "demo_dashboard"


def _code_facts(path: Path) -> tuple[list[str], list[str], list[str]]:
    """(imported modules, non-docstring string literals, LocalStore(...) arg sources)."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)
    }
    imports, strings, stores = [], [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            imports.append(n.module or "")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
            strings.append(n.value)
        elif isinstance(n, ast.Call) and getattr(n.func, "id", "") == "LocalStore":
            stores.append(ast.dump(n))
    return imports, strings, stores


def test_dashboard_never_reads_node_databases_or_directories():
    """Rule 8: a read-only gossip observer. No sqlite, no node data dirs,
    and any LocalStore it builds is its own in-memory scratch space."""
    for path in list(DASH_DIR.glob("*.py")) + [REPO / "apps" / "dashboard" / "observer.py"]:
        imports, strings, stores = _code_facts(path)
        assert "sqlite3" not in imports, path
        assert not any("data/nodes" in s or "data\nodes" in s for s in strings), path
        assert all("':memory:'" in st for st in stores), f"{path}: LocalStore not in-memory"


REQUIRED_TEST_IDS = [
    "map", "btn-partition", "btn-heal", "btn-reset", "btn-lie", "btn-stop-lie", "select-lie-node",
    "query-input", "query-purpose", "query-submit", "query-result", "convergence-status",
    "partition-state", "claim-spread", "forks-panel", "forks-count", "identity-table", "event-log",
    "nodes-live", "sim-time", "mean-error", "dash-status", "action-status",
    "node-card-${n.id}", "node-${n.id}-live", "node-${n.id}-partitioned", "node-${n.id}-claims",
    "node-${n.id}-lying", "node-${n.id}-rejected", "rep-value-${n.id}", "rep-bar-${n.id}",
    "candidate-region-", "region-area-label-", "candidate-area-", "gt-marker-", "marker-",
    "query-verdict", "query-reason", "query-confirmed", "query-inferred", "query-unreachable",
]


@pytest.mark.parametrize("test_id", REQUIRED_TEST_IDS)
def test_index_html_exposes_stable_test_id(test_id):
    html = (DASH_DIR / "static" / "index.html").read_text(encoding="utf-8")
    assert f'data-testid="{test_id}' in html


@pytest.fixture
def engine(tmp_path):
    keys = tmp_path / "keys"
    for n in range(4):
        generate_keypair(n, keys_dir=keys)
    cfg = DemoDashboardConfig(
        peers={n: f"127.0.0.1:{5555 + n}" for n in range(4)},
        keys_dir=str(keys),
        navmesh_path=str(REPO / "data/floorplan/warehouse_demo.geojson"),
    )
    return DashboardEngine(cfg)  # constructed, never started: no sockets


def _att(node: int, boundary: int, t_s: float, crossing: bool, conf: float = 0.9):
    a = starling_pb2.CoverageAttestation(
        node_id=node, region_ids=[boundary], crossing_observed=crossing, attest_confidence=conf
    )
    a.t_start.physical_ms = int(t_s * 1000)
    a.t_end.physical_ms = int((t_s + 2.0) * 1000)
    return a


def _belief(engine, origin=(9.5, 12.0)):
    cb = CandidateBelief(engine.navmesh, engine.reachability, engine.cfg.negative_evidence)
    cb.initialise(origin)
    return _Belief(cb, last_seen_t=0.0, origin=origin)


def test_candidate_region_grows_then_shrinks_when_a_boundary_is_attested_uncrossed(engine):
    b = _belief(engine)
    engine._advance_belief(b, now_t=3.0, attestations=[])
    before = b.belief.area_m2()
    assert before > 5.0
    # Node 0 (watching the blind aisle's west boundary, id 1) attests, with
    # confidence, that nobody crossed it: the region loses the far side.
    engine._advance_belief(b, now_t=3.0, attestations=[_att(0, 1, 1.0, crossing=False)])
    assert b.belief.area_m2() < before


def test_inadmissible_attestation_does_not_shrink_the_region(engine):
    b = _belief(engine)
    engine._advance_belief(b, now_t=3.0, attestations=[])
    before = b.belief.area_m2()
    engine._advance_belief(b, now_t=3.0, attestations=[_att(0, 1, 1.0, crossing=False, conf=0.2)])
    assert b.belief.area_m2() == pytest.approx(before)  # silence / low confidence is not evidence


def test_after_a_crossing_a_no_crossing_attestation_rules_out_the_origin_side(engine):
    """Origin (9.5, 12) is east of boundary 1 (x=8). Once a crossing of
    boundary 1 is attested, the identity is on the WEST side; a later
    "nobody crossed since" must remove the origin (east) side, not the west."""
    import numpy as np

    b = _belief(engine)
    engine._advance_belief(b, now_t=3.0, attestations=[])
    before = b.belief.area_m2()
    engine._advance_belief(
        b, now_t=3.0, attestations=[_att(0, 1, 0.5, crossing=True), _att(0, 1, 2.0, crossing=False)]
    )
    assert 1 in b.crossed
    assert b.belief.area_m2() < before
    ys, xs = np.nonzero(b.belief.mask())
    cs = engine.navmesh.cell_size
    assert xs.max() * cs <= 8.0 + 2 * cs  # nothing left east of the crossed boundary
    assert xs.min() * cs < 7.0  # the far (west) side survives


def test_mask_runs_round_trip(engine):
    import numpy as np

    mask = np.zeros((4, 10), dtype=bool)
    mask[1, 2:5] = True
    mask[3, 0:2] = True
    mask[3, 7:10] = True
    assert engine._mask_runs(mask) == [[1, 2, 4], [3, 0, 1], [3, 7, 9]]
