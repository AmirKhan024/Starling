"""Tests for starling_crdt.resolver (WP-06 Part 2)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import numpy as np

from starling_crdt import resolver
from starling_crdt.claims import ClaimSet
from starling_crdt.resolver import assert_deterministic, resolve
from starling_node.config import MatchConfig
from starling_store.identity_store import LocalStore


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

    assignment = resolve(cs, geometry=geometry, reputation=None, topology=None, cfg=MatchConfig())

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

    assignment = resolve(cs, geometry=geometry, reputation=None, topology=None, cfg=MatchConfig())

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

    assignment = resolve(cs, geometry=None, reputation=None, topology=None, cfg=MatchConfig())

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

    assignment = resolve(cs, geometry=None, reputation=None, topology=None, cfg=MatchConfig())

    assert len(assignment.identity_of) == 2
