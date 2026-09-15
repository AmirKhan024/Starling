"""Property tests for starling_crdt.claims.ClaimSet (WP-06 Part 1).

These four hypothesis properties — commutativity, associativity,
idempotence, convergence — are the mathematical core of C1
(STARLING_BUILD_STATE.md §4.2). Per CLAUDE.md / the WP-06 prompt: never
weaken one of these to make it pass.

Claim groups used by the algebraic-law tests are generated from a single
draw of globally-unique `(node_id, seq)` keys and then partitioned, so a
key never appears in two groups with different content — that isolates
the properties under test from the orthogonal (and separately correct)
question of what a store does when told about the same key twice.
"""

from __future__ import annotations

import random
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from starling_crdt.claims import ClaimSet
from starling_net.anti_entropy import VersionVector
from starling_store.identity_store import LocalStore

_N_EXAMPLES = 200


def _fresh_claimset(node_id: int = 0) -> ClaimSet:
    # `:memory:` gives every hypothesis example (and every replica within
    # one example) its own isolated SQLite database with no filesystem
    # churn — hundreds of examples would otherwise mean hundreds of tmp
    # files to create and tear down.
    return ClaimSet(LocalStore(db_path=":memory:", node_id=node_id))


def _claim(node_id: int, seq: int, physical_ms: int, logical: int) -> dict[str, Any]:
    return {
        "claim_id": f"C-{node_id}-{seq}",
        "node_id": node_id,
        "seq": seq,
        "hlc_physical_ms": physical_ms,
        "hlc_logical": logical,
        "local_track_id": 1,
        "t_media": physical_ms / 1000.0,
        "embedding": b"\x00" * 32,
        "embed_scale": 1.0,
        "confidence": 0.9,
        "quality": 0.8,
    }


def _claim_ids(claims: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(sorted(c["claim_id"] for c in claims))


def _ordered_ids(cs: ClaimSet) -> tuple[str, ...]:
    return tuple(c["claim_id"] for c in cs.ordered())


@st.composite
def _unique_claims(draw, min_size: int = 0, max_size: int = 40) -> list[dict[str, Any]]:
    keys = draw(
        st.lists(
            st.tuples(st.integers(0, 4), st.integers(0, 5000)),
            min_size=min_size,
            max_size=max_size,
            unique=True,
        )
    )
    return [
        _claim(node_id, seq, draw(st.integers(0, 100_000)), draw(st.integers(0, 5)))
        for node_id, seq in keys
    ]


@st.composite
def two_disjoint_claim_groups(draw, min_total: int = 0, max_total: int = 40):
    claims = draw(_unique_claims(min_size=min_total, max_size=max_total))
    split = draw(st.integers(0, len(claims)))
    return claims[:split], claims[split:]


@st.composite
def three_disjoint_claim_groups(draw, min_total: int = 0, max_total: int = 45):
    claims = draw(_unique_claims(min_size=min_total, max_size=max_total))
    n = len(claims)
    a = draw(st.integers(0, n))
    b = draw(st.integers(a, n))
    return claims[:a], claims[a:b], claims[b:]


def _seeded(claims: list[dict[str, Any]], node_id: int = 0) -> ClaimSet:
    cs = _fresh_claimset(node_id)
    for c in claims:
        cs.add(c)
    return cs


# ── the four algebraic properties ───────────────────────────────────────────


@given(two_disjoint_claim_groups())
@settings(max_examples=_N_EXAMPLES, deadline=None)
def test_merge_is_commutative(groups):
    claims_x, claims_y = groups

    ab = _seeded(claims_x)
    ab.merge(_seeded(claims_y))

    ba = _seeded(claims_y)
    ba.merge(_seeded(claims_x))

    assert _claim_ids(list(ab)) == _claim_ids(list(ba))
    assert _ordered_ids(ab) == _ordered_ids(ba)


@given(three_disjoint_claim_groups())
@settings(max_examples=_N_EXAMPLES, deadline=None)
def test_merge_is_associative(groups):
    claims_x, claims_y, claims_z = groups

    left = _seeded(claims_x)
    left.merge(_seeded(claims_y))
    left.merge(_seeded(claims_z))

    right = _seeded(claims_x)
    yz = _seeded(claims_y)
    yz.merge(_seeded(claims_z))
    right.merge(yz)

    assert _claim_ids(list(left)) == _claim_ids(list(right))
    assert _ordered_ids(left) == _ordered_ids(right)


@given(_unique_claims())
@settings(max_examples=_N_EXAMPLES, deadline=None)
def test_merge_is_idempotent(claims):
    a = _seeded(claims)
    ids_before = _claim_ids(list(a))
    ordered_before = _ordered_ids(a)

    a.merge(_seeded(claims))  # merge a copy of itself

    assert _claim_ids(list(a)) == ids_before
    assert _ordered_ids(a) == ordered_before
    assert len(a) == len(claims)


@given(_unique_claims(min_size=1, max_size=40), st.integers(min_value=0, max_value=2**31 - 1))
@settings(max_examples=_N_EXAMPLES, deadline=None)
def test_convergence_under_any_delivery_order(claims, seed):
    """For a fixed claim pool and ANY random delivery order to three
    replicas, all three end byte-identical (STARLING_BUILD_STATE.md
    WP-06 Part 1, the fourth and most important property test).
    """
    rng = random.Random(seed)

    replicas = [_fresh_claimset(node_id=100 + i) for i in range(3)]
    for cs in replicas:
        order = claims[:]
        rng.shuffle(order)
        for c in order:
            cs.add(c)

    reference_ids = _claim_ids(list(replicas[0]))
    reference_ordered = _ordered_ids(replicas[0])
    for cs in replicas[1:]:
        assert _claim_ids(list(cs)) == reference_ids
        assert _ordered_ids(cs) == reference_ordered


# ── concrete tests ───────────────────────────────────────────────────────────


def test_add_returns_false_on_duplicate():
    cs = _fresh_claimset()
    claim = _claim(node_id=0, seq=1, physical_ms=1000, logical=0)

    assert cs.add(claim) is True
    assert cs.add(claim) is False
    assert len(cs) == 1


def test_add_returns_false_on_same_key_different_claim_id():
    """The CRDT identity is (node_id, seq), not claim_id — a second claim
    for an already-known (node_id, seq) is a duplicate by construction
    (a node only ever writes one claim per seq).
    """
    cs = _fresh_claimset()
    first = _claim(node_id=0, seq=1, physical_ms=1000, logical=0)
    second = dict(first, claim_id="C-different")

    assert cs.add(first) is True
    assert cs.add(second) is False
    assert len(cs) == 1


def test_prune_removes_only_claims_older_than_threshold():
    cs = _fresh_claimset()
    for seq, physical_ms in enumerate([100, 500, 1000, 5000, 9000]):
        cs.add(_claim(node_id=0, seq=seq, physical_ms=physical_ms, logical=0))

    removed = cs.prune(before_hlc=1000)

    assert removed == 2  # 100 and 500
    remaining = sorted(c["hlc_physical_ms"] for c in cs)
    assert remaining == [1000, 5000, 9000]


def test_delta_since_returns_exactly_the_complement_of_a_version_vector():
    cs = _fresh_claimset()
    for node_id in range(3):
        for seq in range(5):
            cs.add(_claim(node_id=node_id, seq=seq, physical_ms=seq * 10, logical=0))

    vv = VersionVector({0: 2, 1: -1})  # node 0 has up to seq 2, node 1 nothing, node 2 absent
    delta = cs.delta_since(vv)
    delta_ids = {c["claim_id"] for c in delta}

    expected_ids = {
        c["claim_id"]
        for c in cs
        if c["seq"] > vv.get(c["node_id"], -1)
    }
    assert delta_ids == expected_ids
    # every claim from node 2 (entirely absent from vv) is included
    assert all(f"C-2-{seq}" in delta_ids for seq in range(5))
    # node 0's seq 0..2 are already known to vv, so excluded
    assert not any(f"C-0-{seq}" in delta_ids for seq in range(3))
