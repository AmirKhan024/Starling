"""Property tests for starling_net.hlc (HLC, HLCClock, claim_order_key)."""

from __future__ import annotations

import random
from dataclasses import dataclass

from hypothesis import given, settings
from hypothesis import strategies as st

from starling_net.hlc import HLC, HLCClock, claim_order_key


@dataclass(frozen=True)
class _FakeClaim:
    """Minimal duck-typed stand-in for starling_crdt.Claim (doesn't exist
    yet — claim_order_key only needs .t_start/.node_id/.seq).
    """
    t_start: HLC
    node_id: int
    seq: int


def _order_tuple(hlc: HLC) -> tuple:
    return (hlc.physical_ms, hlc.logical)


@given(st.lists(st.integers(min_value=-10_000, max_value=10_000), min_size=1, max_size=200))
@settings(max_examples=200)
def test_now_is_strictly_monotonic_under_any_physical_ms_sequence(physical_values):
    clock = HLCClock(node_id=1)
    prev = None
    for p in physical_values:
        current = clock.now(p)
        if prev is not None:
            assert _order_tuple(current) > _order_tuple(prev)
        prev = current


@given(
    p_a=st.integers(min_value=0, max_value=100_000),
    p_b=st.integers(min_value=0, max_value=100_000),
)
@settings(max_examples=200)
def test_update_preserves_causality(p_a, p_b):
    clock_a = HLCClock(node_id=1)
    clock_b = HLCClock(node_id=2)

    sent = clock_a.now(p_a)          # A sends a message stamped `sent`
    received = clock_b.update(sent, p_b)  # B receives it

    assert _order_tuple(received) > _order_tuple(sent)


def test_claim_order_key_is_a_strict_total_order():
    rng = random.Random(1234)

    claims = []
    for i in range(1000):
        claims.append(_FakeClaim(
            t_start=HLC(
                physical_ms=rng.randint(0, 50),
                logical=rng.randint(0, 5),
                node_id=rng.randint(0, 9),
            ),
            node_id=i % 10,
            seq=i,  # (node_id, seq) need not be globally unique here since
                    # seq alone already is, which is enough to prove no ties
        ))

    canonical = sorted(claims, key=claim_order_key)

    for trial in range(20):
        shuffled = claims[:]
        rng.shuffle(shuffled)
        resorted = sorted(shuffled, key=claim_order_key)
        assert resorted == canonical, f"trial {trial} produced a different order"

    # No ties: every consecutive pair in the canonical order is strictly greater.
    for a, b in zip(canonical, canonical[1:]):
        assert claim_order_key(a) < claim_order_key(b)


@given(
    physical_ms=st.integers(min_value=0, max_value=2**48),
    logical=st.integers(min_value=0, max_value=2**31 - 1),
    node_id=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=200)
def test_pack_unpack_round_trips(physical_ms, logical, node_id):
    original = HLC(physical_ms=physical_ms, logical=logical, node_id=node_id)
    packed = original.pack()
    assert len(packed) == 16
    assert HLC.unpack(packed) == original
