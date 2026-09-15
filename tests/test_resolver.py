"""Tests for starling_crdt.resolver (WP-06 Parts 2 & 3)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import numpy as np

from starling_crdt import resolver
from starling_crdt.claims import ClaimSet
from starling_crdt.forks import ForkStatus
from starling_crdt.resolver import assert_deterministic, resolve, resolve_incremental
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_node.config import MatchConfig
from starling_store.identity_store import LocalStore


def _open_room(cell_size: float = 0.5, size_m: float = 200.0) -> NavMesh:
    n = int(size_m / cell_size)
    return NavMesh(grid=np.ones((n, n), dtype=bool), origin=(0.0, 0.0), cell_size=cell_size)


class _FakeGeometry:
    """Controllable `ReachabilityModel` double: resolver only ever calls
    `.is_reachable(...)`, so a duck-typed fake keeps these tests focused
    on the resolver's gating logic instead of navmesh/Dijkstra specifics
    (those are starling_geometry's own tests).
    """

    def __init__(self, reachable: bool = True) -> None:
        self.reachable = reachable
        self.calls: list[tuple] = []

    def is_reachable(self, origin_xy, target_xy, dt_s, pos_sigma=0.0) -> bool:
        self.calls.append((origin_xy, target_xy, dt_s, pos_sigma))
        return self.reachable


def _emb(vec) -> bytes:
    return np.array(vec, dtype=np.float32).tobytes()


def _claim(
    node_id: int,
    seq: int,
    t_media: float,
    embedding=(1.0, 0.0, 0.0, 0.0),
    world_xy: Optional[tuple[float, float]] = None,
    pos_sigma: float = 0.5,
    confidence: float = 0.9,
    quality: float = 0.8,
    anchor_type: str = "UNANCHORED",
    identity_ref: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "claim_id": f"C-{node_id}-{seq}",
        "node_id": node_id,
        "seq": seq,
        "hlc_physical_ms": int(t_media * 1000),
        "hlc_logical": 0,
        "local_track_id": 1,
        "t_media": t_media,
        "embedding": _emb(embedding),
        "embed_scale": 1.0,
        "world_x": world_xy[0] if world_xy is not None else None,
        "world_y": world_xy[1] if world_xy is not None else None,
        "pos_sigma": pos_sigma,
        "anchor_type": anchor_type,
        "identity_ref": identity_ref,
        "confidence": confidence,
        "quality": quality,
    }


def _claim_set(claims: list[dict[str, Any]], node_id: int = 0) -> ClaimSet:
    cs = ClaimSet(LocalStore(db_path=":memory:", node_id=node_id))
    for c in claims:
        cs.add(c)
    return cs


def test_resolve_is_deterministic_across_100_shuffles():
    # One growing identity, 12 claims from several nodes over time — enough
    # surface area (gate, gallery growth, scoring, tie-break) to catch any
    # dict/set-iteration-order dependence.
    claims = [
        _claim(node_id=i % 4, seq=i, t_media=float(i), embedding=(1.0, 0.05 * i, 0.0, 0.0))
        for i in range(12)
    ]
    reputation = {0: 1.0, 1: 0.8, 2: 0.9, 3: 1.0}

    assert_deterministic(claims, reputation=reputation, trials=100)


def test_geometrically_impossible_candidate_rejected_even_at_cosine_0_99():
    anchor = _claim(
        node_id=0, seq=0, t_media=0.0, embedding=(1.0, 0.0, 0.0, 0.0),
        world_xy=(0.0, 0.0), anchor_type="FACE_ANCHOR", identity_ref="P-001",
    )
    far_but_similar = _claim(
        node_id=1, seq=0, t_media=1.0, embedding=(1.0, 0.0, 0.0, 0.0),  # cosine 1.0 vs anchor
        world_xy=(1000.0, 1000.0),  # far away in 1 second: geometrically impossible
    )
    cs = _claim_set([anchor, far_but_similar])
    geometry = _FakeGeometry(reachable=False)

    assignment, _ = resolve(cs, geometry=geometry, reputation=None, topology=None, cfg=MatchConfig())

    assert geometry.calls, "resolver never consulted the reachability gate"
    assert assignment.identity_of[far_but_similar["claim_id"]] != "P-001"
    assert assignment.trajectories["P-001"] == [anchor["claim_id"]]


def test_thin_margin_between_best_and_second_best_leaves_claim_unassigned():
    shared_embedding = (1.0, 0.0, 0.0, 0.0)
    anchor_a = _claim(
        node_id=0, seq=0, t_media=0.0, embedding=shared_embedding,
        world_xy=(0.0, 0.0), anchor_type="FACE_ANCHOR", identity_ref="P-A",
    )
    anchor_b = _claim(
        node_id=1, seq=0, t_media=0.0, embedding=shared_embedding,
        world_xy=(10.0, 10.0), anchor_type="FACE_ANCHOR", identity_ref="P-B",
    )
    ambiguous = _claim(
        node_id=2, seq=0, t_media=1.0, embedding=shared_embedding, world_xy=(5.0, 5.0),
    )
    cs = _claim_set([anchor_a, anchor_b, ambiguous])
    geometry = _FakeGeometry(reachable=True)  # both candidates pass the gate

    assignment, _ = resolve(cs, geometry=geometry, reputation=None, topology=None, cfg=MatchConfig())

    assert assignment.identity_of[ambiguous["claim_id"]] is None
    assert ambiguous["claim_id"] not in assignment.trajectories["P-A"]
    assert ambiguous["claim_id"] not in assignment.trajectories["P-B"]


def test_face_anchored_claim_binds_identity_even_when_appearance_disagrees():
    first = _claim(
        node_id=0, seq=0, t_media=0.0, embedding=(1.0, 0.0, 0.0, 0.0),
        anchor_type="FACE_ANCHOR", identity_ref="P-002",
    )
    disagreeing = _claim(
        node_id=1, seq=0, t_media=1.0, embedding=(-1.0, 0.0, 0.0, 0.0),  # cosine -1.0
        anchor_type="FACE_ANCHOR", identity_ref="P-002",
    )
    cs = _claim_set([first, disagreeing])

    assignment, _ = resolve(cs, geometry=None, reputation=None, topology=None, cfg=MatchConfig())

    assert assignment.identity_of[disagreeing["claim_id"]] == "P-002"
    assert assignment.confidence["P-002"] == 1.0
    assert assignment.trajectories["P-002"] == [first["claim_id"], disagreeing["claim_id"]]


def test_geometry_none_skips_gate_and_logs_warning_exactly_once(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        resolver, "logger", SimpleNamespace(warning=lambda *a, **k: calls.append((a, k)))
    )

    claims = [
        _claim(node_id=i, seq=0, t_media=float(i), embedding=(float(i), 0.0, 0.0, 0.0))
        for i in range(5)
    ]
    cs = _claim_set(claims)

    resolve(cs, geometry=None, reputation=None, topology=None, cfg=MatchConfig())

    assert len(calls) == 1


def test_topology_and_reputation_are_optional_and_default_to_neutral():
    """No geometry, no reputation, no topology: still resolves without error."""
    claims = [
        _claim(node_id=0, seq=0, t_media=0.0),
        _claim(node_id=1, seq=0, t_media=1.0, embedding=(1.0, 0.0, 0.0, 0.0)),
    ]
    cs = _claim_set(claims)

    assignment, forks = resolve(cs, geometry=None, reputation=None, topology=None, cfg=MatchConfig())

    assert len(assignment.identity_of) == 2
    assert forks.all_forks() == []


def test_conflicting_face_anchor_with_two_still_plausible_branches_stays_open():
    """The resolver-integration counterpart of
    tests/test_forks.py's most important test: a real conflict, detected
    from real claims through resolve() itself, that genuinely stays open.
    """
    embedding = (1.0, 0.0, 0.0, 0.0)
    geometry = ReachabilityModel(_open_room(), v_max_m_s=1.6)

    anchor1 = _claim(
        node_id=0, seq=0, t_media=0.0, embedding=embedding, world_xy=(20.0, 20.0),
        pos_sigma=0.0, anchor_type="FACE_ANCHOR", identity_ref="P-012",
    )
    # Ordinary propagation moves the live branch's tip away from the last
    # confirmed (anchor) position, so the later conflict is checked
    # against a genuinely looser (larger dt) radius than a same-instant
    # comparison would give.
    propagate1 = _claim(
        node_id=1, seq=0, t_media=1.0, embedding=embedding, world_xy=(21.0, 20.0), pos_sigma=0.0,
    )
    # Unreachable from the live tip (21,20)@t=1 within 1s (would need
    # 2.5 m/s over a 2.1 m/s-radius budget) but reachable from the
    # ORIGINAL anchor (20,20)@t=0 within the full 2s elapsed (3.5 m within
    # a 3.7 m/s-radius budget) — genuinely, simultaneously plausible.
    anchor2 = _claim(
        node_id=2, seq=0, t_media=2.0, embedding=embedding, world_xy=(23.5, 20.0),
        pos_sigma=0.0, anchor_type="FACE_ANCHOR", identity_ref="P-012",
    )
    cs = _claim_set([anchor1, propagate1, anchor2])

    assignment, forks = resolve(cs, geometry=geometry, reputation=None, topology=None, cfg=MatchConfig())

    open_forks = forks.open_forks()
    assert len(open_forks) == 1
    fork = open_forks[0]
    assert fork.identity_ref == "P-012"
    assert fork.status == ForkStatus.OPEN
    assert fork.resolution_reason is None
    branch_claim_ids = {b.claim_ids for b in fork.branches}
    assert branch_claim_ids == {
        (anchor1["claim_id"], propagate1["claim_id"]),
        (anchor2["claim_id"],),
    }
    # Both branches retained and reported, per CLAUDE.md rule 6.
    assert assignment.identity_of[anchor2["claim_id"]] == "P-012"
    assert set(assignment.trajectories["P-012"]) == {
        anchor1["claim_id"], propagate1["claim_id"], anchor2["claim_id"],
    }


def test_conflicting_face_anchor_with_one_impossible_branch_auto_resolves():
    embedding = (1.0, 0.0, 0.0, 0.0)
    geometry = ReachabilityModel(_open_room(), v_max_m_s=1.6)

    anchor1 = _claim(
        node_id=0, seq=0, t_media=0.0, embedding=embedding, world_xy=(20.0, 20.0),
        pos_sigma=0.0, anchor_type="FACE_ANCHOR", identity_ref="P-010",
    )
    impossible = _claim(
        node_id=1, seq=0, t_media=1.0, embedding=embedding, world_xy=(120.0, 20.0),
        pos_sigma=0.0, anchor_type="FACE_ANCHOR", identity_ref="P-010",
    )
    cs = _claim_set([anchor1, impossible])

    assignment, forks = resolve(cs, geometry=geometry, reputation=None, topology=None, cfg=MatchConfig())

    all_forks = forks.all_forks()
    assert len(all_forks) == 1
    fork = all_forks[0]
    assert fork.status == ForkStatus.RESOLVED_REACHABILITY
    assert fork.resolved_branch == 0
    assert "branch 1" in fork.resolution_reason
    assert "m/s" in fork.resolution_reason
    assert forks.open_forks() == []
    # Still honestly recorded as evidence bound to P-010, on the branch
    # the fork mechanism flagged as the losing one.
    assert assignment.identity_of[impossible["claim_id"]] == "P-010"


def test_subsequent_face_anchor_closes_a_previously_open_fork():
    embedding = (1.0, 0.0, 0.0, 0.0)
    geometry = ReachabilityModel(_open_room(), v_max_m_s=1.6)

    anchor1 = _claim(
        node_id=0, seq=0, t_media=0.0, embedding=embedding, world_xy=(20.0, 20.0),
        pos_sigma=0.0, anchor_type="FACE_ANCHOR", identity_ref="P-013",
    )
    propagate1 = _claim(
        node_id=1, seq=0, t_media=1.0, embedding=embedding, world_xy=(21.0, 20.0), pos_sigma=0.0,
    )
    anchor2 = _claim(
        node_id=2, seq=0, t_media=2.0, embedding=embedding, world_xy=(23.5, 20.0),
        pos_sigma=0.0, anchor_type="FACE_ANCHOR", identity_ref="P-013",
    )
    # Continues branch 1 (anchor2's branch): 0.5 m over 1 s, easily reachable.
    anchor3 = _claim(
        node_id=3, seq=0, t_media=3.0, embedding=embedding, world_xy=(24.0, 20.0),
        pos_sigma=0.0, anchor_type="FACE_ANCHOR", identity_ref="P-013",
    )
    cs = _claim_set([anchor1, propagate1, anchor2, anchor3])

    assignment, forks = resolve(cs, geometry=geometry, reputation=None, topology=None, cfg=MatchConfig())

    assert forks.open_forks() == []
    all_forks = forks.all_forks()
    assert len(all_forks) == 1
    fork = all_forks[0]
    assert fork.status == ForkStatus.RESOLVED_ANCHOR
    assert fork.resolved_branch == 1
    assert anchor3["claim_id"] in fork.resolution_reason
    assert assignment.identity_of[anchor3["claim_id"]] == "P-013"


def test_resolve_incremental_normal_operation_excludes_claims_outside_the_window():
    old = _claim(node_id=0, seq=0, t_media=0.0, embedding=(1.0, 0.0, 0.0, 0.0))
    recent = _claim(node_id=1, seq=0, t_media=1000.0, embedding=(1.0, 0.0, 0.0, 0.0))
    cs = _claim_set([old, recent])
    cfg = MatchConfig(resolve_window_s=300.0)

    assignment, _ = resolve_incremental(
        cs, geometry=None, reputation=None, topology=None, cfg=cfg, now_t_media=1000.0
    )

    assert recent["claim_id"] in assignment.identity_of
    assert old["claim_id"] not in assignment.identity_of


def test_resolve_incremental_full_recompute_includes_the_whole_retention_window():
    old = _claim(node_id=0, seq=0, t_media=0.0, embedding=(1.0, 0.0, 0.0, 0.0))
    recent = _claim(node_id=1, seq=0, t_media=1000.0, embedding=(1.0, 0.0, 0.0, 0.0))
    cs = _claim_set([old, recent])
    cfg = MatchConfig(resolve_window_s=300.0, retention_window_s=3600.0)

    assignment, _ = resolve_incremental(
        cs, geometry=None, reputation=None, topology=None, cfg=cfg,
        now_t_media=1000.0, full_recompute=True,
    )

    assert old["claim_id"] in assignment.identity_of
    assert recent["claim_id"] in assignment.identity_of


def test_resolve_incremental_matches_full_resolve_on_the_same_window():
    """D-10's incremental resolution must not change the assignment
    relative to a full recompute on the same claim set — a divergence
    here would be a correctness bug per the WP-06 stop conditions, not
    something to tune around.
    """
    claims = [
        _claim(node_id=i % 3, seq=i, t_media=float(i), embedding=(1.0, 0.05 * i, 0.0, 0.0))
        for i in range(10)
    ]
    cs = _claim_set(claims)
    cfg = MatchConfig(resolve_window_s=1000.0)  # window covers every claim here

    full_assignment, _ = resolve(cs, geometry=None, reputation=None, topology=None, cfg=cfg)
    incremental_assignment, _ = resolve_incremental(
        cs, geometry=None, reputation=None, topology=None, cfg=cfg, now_t_media=9.0
    )

    assert incremental_assignment.identity_of == full_assignment.identity_of
    assert incremental_assignment.trajectories == full_assignment.trajectories
