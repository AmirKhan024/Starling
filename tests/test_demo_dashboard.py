"""Tests for the simulator demo dashboard (apps/demo_dashboard): observer
isolation (CLAUDE.md rules 2 and 8), the testability contract the automated
review relies on, and the candidate-region logic — none of it needs a running
mesh.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from apps.demo_dashboard.config import DemoDashboardConfig
from apps.demo_dashboard.engine import DashboardEngine, _Belief
import numpy as np

from starling_attest.negative_evidence import ZONE_REGION_BASE, CandidateBelief
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
    html = (DASH_DIR / "static" / "engineer.html").read_text(encoding="utf-8")
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


def _att(node: int, end_s: float, conf: float = 0.9):
    a = starling_pb2.CoverageAttestation(
        node_id=node, region_ids=[ZONE_REGION_BASE + node], crossing_observed=False, attest_confidence=conf
    )
    a.t_start.physical_ms = int((end_s - 2.0) * 1000)
    a.t_end.physical_ms = int(end_s * 1000)
    return a


def _belief(engine, origin=(19.0, 12.7)):
    ne = engine.cfg.negative_evidence
    cb = CandidateBelief(engine.navmesh, engine.reachability, ne)
    cb.initialise(origin)
    rb = CandidateBelief(engine.navmesh, engine.reachability, ne.model_copy(update={"negative_evidence_enabled": False}))
    rb.initialise(origin)
    return _Belief(cb, rb, last_seen_t=0.0, origin=origin)


def test_healthy_cameras_shrink_the_region_below_plain_reachability(engine):
    b = _belief(engine)
    atts = [_att(n, 9.0) for n in range(4)]
    engine._advance_belief(b, now_t=9.0, attestations=atts)
    assert sorted(b.healthy_nodes) == [0, 1, 2, 3]
    assert b.belief.area_m2() < 0.4 * b.reach.area_m2()  # negative evidence removed most of the reachable floor
    covered = np.any(list(engine.zone_masks.values()), axis=0)
    assert not (b.belief.mask() & covered).any()


def test_silent_camera_is_not_subtracted_and_the_region_leaks_into_its_zone(engine):
    b = _belief(engine)
    engine._advance_belief(b, now_t=9.0, attestations=[_att(0, 9.0), _att(2, 9.0), _att(3, 9.0)])  # node 1 silent
    assert 1 not in b.healthy_nodes
    assert (b.belief.mask() & engine.zone_masks[1]).any()
    for n in (0, 2, 3):
        assert not (b.belief.mask() & engine.zone_masks[n]).any()


def test_mask_runs_round_trip(engine):
    import numpy as np

    mask = np.zeros((4, 10), dtype=bool)
    mask[1, 2:5] = True
    mask[3, 0:2] = True
    mask[3, 7:10] = True
    assert engine._mask_runs(mask) == [[1, 2, 4], [3, 0, 1], [3, 7, 9]]


# ── the operator (manager) view ───────────────────────────────────────────

MANAGER_TEST_IDS = [
    "sys-status", "kpi-people", "kpi-cameras", "alerts", "people-list", "camera-list",
    "find-input", "find-go", "clear-spotlight", "zoom-in", "zoom-out", "zoom-fit",
    "map", "engineer-link", "last-update",
]


@pytest.mark.parametrize("test_id", MANAGER_TEST_IDS)
def test_operator_view_exposes_stable_test_id(test_id):
    html = (DASH_DIR / "static" / "index.html").read_text(encoding="utf-8")
    assert f'data-testid="{test_id}' in html


def test_operator_view_hides_the_technical_vocabulary():
    """A warehouse manager reads this screen. Words that only mean something to
    an engineer belong in the technical view or the browser console, not here."""
    html = (DASH_DIR / "static" / "index.html").read_text(encoding="utf-8")
    # strip the <script> block: console.debug() legitimately names these fields
    body = re.sub(r"<script>.*?</script>", "", html, flags=re.S)
    for jargon in [
        "claim", "CRDT", "gossip", "anti-entropy", "reputation", "plausibility",
        "convergence", "partition", "fork", "attestation", "node-", "quorum", "replica",
    ]:
        assert jargon.lower() not in body.lower(), f"operator view shows engineer jargon: {jargon!r}"


def test_operator_view_links_to_the_technical_view():
    html = (DASH_DIR / "static" / "index.html").read_text(encoding="utf-8")
    assert 'href="/engineer"' in html


def test_server_serves_both_views():
    server = (DASH_DIR / "server.py").read_text(encoding="utf-8")
    assert '"index.html"' in server and '"engineer.html"' in server
    assert '@app.get("/engineer")' in server
