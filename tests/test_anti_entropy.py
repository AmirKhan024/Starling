"""Tests for starling_net.anti_entropy (WP-04 Part 3): pure convergence
logic, no real transport — on_digest/on_delta are plain functions over
LocalStore, exactly so this is testable without sockets.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from starling_net.anti_entropy import AntiEntropy, VersionVector
from starling_store.identity_store import LocalStore


class _FakeObs:
    def __init__(self, t_media: float, local_track_id: int = 1) -> None:
        self.local_track_id = local_track_id
        self.embedding = np.ones(8, dtype=np.float32) / np.sqrt(8)
        self.conf = 0.9
        self.quality = 0.8
        self.t_media = t_media


def _populate(store: LocalStore, n: int) -> None:
    for i in range(n):
        store.append_local_observation(_FakeObs(t_media=float(i)))


def _all_claim_ids(store: LocalStore) -> set[str]:
    return {c["claim_id"] for c in store.claims_since(VersionVector({}))}


def test_two_stores_converge_in_expected_round_count(tmp_path: Path):
    store_a = LocalStore(db_path=str(tmp_path / "a.db"), node_id=0)
    store_b = LocalStore(db_path=str(tmp_path / "b.db"), node_id=1)
    _populate(store_a, 500)

    max_delta = 100
    ae_a = AntiEntropy(store_a, max_delta=max_delta)
    ae_b = AntiEntropy(store_b, max_delta=max_delta)

    rounds = 0
    while _all_claim_ids(store_b) != _all_claim_ids(store_a):
        # store_b initiates: sends its own (smaller) version vector; store_a
        # replies with whatever store_b is missing, up to max_delta.
        b_vv = VersionVector(store_b.claim_version_vector())
        delta = ae_a.on_digest(b_vv)
        assert len(delta) <= max_delta
        ae_b.on_delta(delta)
        rounds += 1
        assert rounds <= 100  # guard against an infinite loop on a real bug

    assert rounds == math.ceil(500 / max_delta)
    assert _all_claim_ids(store_a) == _all_claim_ids(store_b)


def test_duplicate_delivery_of_the_same_delta_is_idempotent(tmp_path: Path):
    store_a = LocalStore(db_path=str(tmp_path / "a.db"), node_id=0)
    store_b = LocalStore(db_path=str(tmp_path / "b.db"), node_id=1)
    _populate(store_a, 50)

    ae_a = AntiEntropy(store_a, max_delta=1000)
    ae_b = AntiEntropy(store_b, max_delta=1000)

    delta = ae_a.on_digest(VersionVector({}))
    assert len(delta) == 50

    first = ae_b.on_delta(delta)
    second = ae_b.on_delta(delta)  # re-deliver the identical delta

    assert first == 50
    assert second == 0
    assert _all_claim_ids(store_b) == _all_claim_ids(store_a)


def test_reversed_delivery_order_gives_the_same_final_state(tmp_path: Path):
    store_a = LocalStore(db_path=str(tmp_path / "a.db"), node_id=0)
    _populate(store_a, 20)

    ae_a = AntiEntropy(store_a, max_delta=1000)
    full_delta = ae_a.on_digest(VersionVector({}))
    assert len(full_delta) == 20

    half = len(full_delta) // 2
    chunk1, chunk2 = full_delta[:half], full_delta[half:]

    store_forward = LocalStore(db_path=str(tmp_path / "forward.db"), node_id=2)
    AntiEntropy(store_forward).on_delta(chunk1)
    AntiEntropy(store_forward).on_delta(chunk2)

    store_reversed = LocalStore(db_path=str(tmp_path / "reversed.db"), node_id=3)
    AntiEntropy(store_reversed).on_delta(chunk2)
    AntiEntropy(store_reversed).on_delta(chunk1)

    assert store_forward.claim_version_vector() == store_reversed.claim_version_vector()
    assert _all_claim_ids(store_forward) == _all_claim_ids(store_reversed)


def test_version_vector_pack_unpack_roundtrips():
    vv = VersionVector({0: 10, 3: 500, 7: 0})
    restored = VersionVector.unpack(vv.pack())
    assert restored == vv


def test_version_vector_dominates_and_missing_from():
    ahead = VersionVector({0: 10, 1: 5})
    behind = VersionVector({0: 3, 1: 5})

    assert ahead.dominates(behind)
    assert not behind.dominates(ahead)
    assert ahead.missing_from(behind) == {0: 7}
