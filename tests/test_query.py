"""Tests for starling_query (WP-14, C5): capability tokens and the
scoped query CLI's refusal behaviour.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from starling_crdt.forks import Branch, ForkSet, make_fork
from starling_crdt.resolver import Assignment
from starling_net.hlc import HLC
from starling_net.keys import generate_keypair, load_keys
from starling_query.answer import answer_query
from starling_query.capability import CapabilityToken, Query, issue, verify
from starling_query.cli import run_query

GT_PATH = Path(__file__).resolve().parent.parent / "data" / "gt" / "unanswerable_queries.json"

NOW_T_MEDIA = 100_000.0
RETENTION_WINDOW_S = 3600.0


# ── Shared synthetic environment (no live gossip needed — same "test the
# algorithm directly" pattern as scripts/run_deadzone_experiment.py) ──────

def _claim(claim_id: str, node_id: int, t_media: float, anchor_type: str = "UNANCHORED", confidence: float = 0.9) -> dict:
    return {
        "claim_id": claim_id, "node_id": node_id, "t_media": t_media,
        "confidence": confidence, "anchor_type": anchor_type,
        "world_x": 1.0, "world_y": 1.0, "quality": 1.0,
    }


def _environment():
    claims = {
        "c-p001-1": _claim("c-p001-1", 0, NOW_T_MEDIA - 500, anchor_type="FACE_ANCHOR"),
        "c-p001-2": _claim("c-p001-2", 1, NOW_T_MEDIA - 100),
        "c-p002-1": _claim("c-p002-1", 2, NOW_T_MEDIA - 200),  # node 2 is offline in `liveness` below
        "c-p003-1": _claim("c-p003-1", 0, NOW_T_MEDIA - 300, anchor_type="FACE_ANCHOR"),
        "c-p003-2": _claim("c-p003-2", 1, NOW_T_MEDIA - 300, anchor_type="FACE_ANCHOR"),
        "c-p004-1": _claim("c-p004-1", 0, NOW_T_MEDIA - 200),
    }

    assignment = Assignment(
        identity_of={cid: None for cid in claims},
        trajectories={
            "P-001": ["c-p001-1", "c-p001-2"],
            "P-002": ["c-p002-1"],
            "P-003": ["c-p003-1", "c-p003-2"],
            "P-004": ["c-p004-1"],
        },
        confidence={"P-001": 0.9, "P-002": 0.8, "P-003": 0.9, "P-004": 0.85},
    )

    branch_a = Branch(claim_ids=("c-p003-1",), last_position=(1.0, 1.0), hlc_span=(HLC(0, 0, 0), HLC(0, 0, 0)))
    branch_b = Branch(claim_ids=("c-p003-2",), last_position=(50.0, 50.0), hlc_span=(HLC(0, 0, 1), HLC(0, 0, 1)))
    fork = make_fork("P-003", (branch_a, branch_b), opened_at=HLC(int((NOW_T_MEDIA - 300) * 1000), 0, 0))
    forks = ForkSet()
    forks.add(fork)

    liveness = {0: True, 1: True, 2: False, 3: True}
    attested_region_ids = frozenset({1, 2})  # region 77 is never attested by anyone

    return assignment, claims, forks, liveness, attested_region_ids


def _query_for_category(category: str, subject: str) -> Query:
    if category == "before_retention_horizon":
        return Query(subject=subject, area=(), t_start=0.0, t_end=100.0)  # << NOW_T_MEDIA - RETENTION_WINDOW_S
    if category == "no_coverage_region":
        return Query(subject="P-004", area=(77,), t_start=NOW_T_MEDIA - 600, t_end=NOW_T_MEDIA)
    if category == "subject_partitioned_wing":
        return Query(subject="P-002", area=(), t_start=NOW_T_MEDIA - 600, t_end=NOW_T_MEDIA)
    if category == "fusion_across_fork":
        return Query(subject="P-003", area=(), t_start=NOW_T_MEDIA - 600, t_end=NOW_T_MEDIA)
    return Query(subject=subject, area=(), t_start=NOW_T_MEDIA - 600, t_end=NOW_T_MEDIA)  # never_enrolled


# ── answer_query() direct tests ──────────────────────────────────────────

def test_partitioned_region_query_names_the_unreachable_node():
    assignment, claims, forks, liveness, attested = _environment()
    result = answer_query(
        Query(subject="P-002", t_start=NOW_T_MEDIA - 600, t_end=NOW_T_MEDIA),
        assignment, claims, forks, liveness, NOW_T_MEDIA, RETENTION_WINDOW_S, attested,
    )
    assert result.refused
    assert "node 2" in result.refusal_reason


def test_unenrolled_subject_refuses():
    assignment, claims, forks, liveness, attested = _environment()
    result = answer_query(
        Query(subject="P-999", t_start=NOW_T_MEDIA - 600, t_end=NOW_T_MEDIA),
        assignment, claims, forks, liveness, NOW_T_MEDIA, RETENTION_WINDOW_S, attested,
    )
    assert result.refused
    assert "never enrolled" in result.refusal_reason


def test_before_retention_horizon_refuses():
    assignment, claims, forks, liveness, attested = _environment()
    result = answer_query(
        Query(subject="P-001", t_start=0.0, t_end=100.0),
        assignment, claims, forks, liveness, NOW_T_MEDIA, RETENTION_WINDOW_S, attested,
    )
    assert result.refused
    assert "retention horizon" in result.refusal_reason


def test_open_fork_refuses_fusion():
    assignment, claims, forks, liveness, attested = _environment()
    result = answer_query(
        Query(subject="P-003", t_start=NOW_T_MEDIA - 600, t_end=NOW_T_MEDIA),
        assignment, claims, forks, liveness, NOW_T_MEDIA, RETENTION_WINDOW_S, attested,
    )
    assert result.refused
    assert "fork" in result.refusal_reason


def test_no_coverage_region_refuses():
    assignment, claims, forks, liveness, attested = _environment()
    result = answer_query(
        Query(subject="P-004", area=(77,), t_start=NOW_T_MEDIA - 600, t_end=NOW_T_MEDIA),
        assignment, claims, forks, liveness, NOW_T_MEDIA, RETENTION_WINDOW_S, attested,
    )
    assert result.refused
    assert "coverage" in result.refusal_reason


def test_answerable_query_succeeds_and_is_not_refused():
    assignment, claims, forks, liveness, attested = _environment()
    result = answer_query(
        Query(subject="P-001", t_start=NOW_T_MEDIA - 600, t_end=NOW_T_MEDIA),
        assignment, claims, forks, liveness, NOW_T_MEDIA, RETENTION_WINDOW_S, attested,
    )
    assert not result.refused
    assert result.last_confirmed is not None
    assert result.nodes_responded == 3
    assert result.nodes_total == 4


def test_every_entry_in_unanswerable_queries_json_is_refused():
    entries = json.loads(GT_PATH.read_text(encoding="utf-8"))
    assert 30 <= len(entries) <= 50
    assignment, claims, forks, liveness, attested = _environment()

    for entry in entries:
        query = _query_for_category(entry["category"], subject=entry["query"].split()[-1])
        result = answer_query(query, assignment, claims, forks, liveness, NOW_T_MEDIA, RETENTION_WINDOW_S, attested)
        assert result.refused, f"expected a refusal for entry {entry!r}"


# ── capability token tests ────────────────────────────────────────────────

@pytest.fixture
def keys_dir(tmp_path: Path) -> Path:
    d = tmp_path / "keys"
    for node_id in range(2):
        generate_keypair(node_id, keys_dir=d)
    return d


def test_valid_token_is_allowed(keys_dir):
    keys = load_keys(0, keys_dir=keys_dir)
    token = issue("safety", area=(1, 2), t_start=0.0, t_end=time.time() + 3600, keys=keys)
    allowed, reason = verify(token, Query(subject="P-001", area=(1,), t_start=0, t_end=1), keys, now=time.time())
    assert allowed, reason


def test_productivity_purpose_is_rejected(keys_dir):
    keys = load_keys(0, keys_dir=keys_dir)
    token = issue("productivity", area=(), t_start=0.0, t_end=time.time() + 3600, keys=keys)
    allowed, reason = verify(token, Query(subject="P-001"), keys, now=time.time())
    assert not allowed
    assert "not authorised" in reason


def test_out_of_scope_area_is_denied_with_a_reason(keys_dir):
    keys = load_keys(0, keys_dir=keys_dir)
    token = issue("incident", area=(1, 2), t_start=0.0, t_end=time.time() + 3600, keys=keys)
    allowed, reason = verify(token, Query(subject="P-001", area=(9,), t_start=0, t_end=1), keys, now=time.time())
    assert not allowed
    assert "outside this token" in reason


def test_expired_token_is_denied(keys_dir):
    keys = load_keys(0, keys_dir=keys_dir)
    token = issue("audit", area=(), t_start=0.0, t_end=100.0, keys=keys)
    allowed, reason = verify(token, Query(subject="P-001"), keys, now=200.0)
    assert not allowed
    assert "expired" in reason


def test_tampered_token_signature_is_denied(keys_dir):
    keys = load_keys(0, keys_dir=keys_dir)
    token = issue("safety", area=(), t_start=0.0, t_end=time.time() + 3600, keys=keys)
    tampered = CapabilityToken(purpose="safety", area=(), t_start=0.0, t_end=token.t_end, issued_by=0, signature=b"\x00" * 64)
    allowed, reason = verify(tampered, Query(subject="P-001"), keys, now=time.time())
    assert not allowed
    assert "signature" in reason


def test_token_json_round_trip(keys_dir):
    keys = load_keys(0, keys_dir=keys_dir)
    token = issue("safety", area=(1, 2, 3), t_start=1.0, t_end=2.0, keys=keys)
    restored = CapabilityToken.from_dict(json.loads(json.dumps(token.to_dict())))
    allowed, _ = verify(restored, Query(subject="P-001", area=(1,), t_start=0, t_end=1), keys, now=1.5)
    assert allowed


# ── end-to-end CLI plumbing (no gossip data needed for a refusal) ────────

def test_cli_run_query_refuses_unenrolled_subject_end_to_end(tmp_path, keys_dir):
    node0_keys = load_keys(0, keys_dir=keys_dir)
    token = issue("safety", area=(), t_start=0.0, t_end=time.time() + 3600, keys=node0_keys)
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps(token.to_dict()), encoding="utf-8")

    peers_config = tmp_path / "peers.yaml"
    peers_config.write_text(
        f"peers:\n  0: \"127.0.0.1:1\"\n"  # unreachable on purpose -- no node needs to actually run
        f"keys_dir: \"{keys_dir.as_posix()}\"\n"
        f"navmesh_path: null\n",
        encoding="utf-8",
    )

    exit_code, message = run_query(
        "where is P-999", token_path, peers_config, hop_budget=0, window_s=600.0,
    )
    assert exit_code != 0
    assert message.startswith("Cannot answer:")
    assert "never enrolled" in message
