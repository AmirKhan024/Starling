"""Gap-aware anti-entropy (Part A): a replica that holds a HIGH seq from a
peer but is missing lower ones must still get the holes filled, and four
nodes reach byte-identical claim sets after a partition heal even over a
lossy, reordering, chunked link.

Transport is simulated in-process (drop / reorder / 3-claim chunks — the
same chunk size as apps/node.py) so loss is deterministic under a seed;
the live multi-process behaviour is covered by the integration tests.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from starling_crdt.claims import ClaimSet
from starling_net.anti_entropy import AntiEntropy, VersionVector
from starling_store.identity_store import LocalStore

CHUNK = 3
RING = {0: [1, 3], 1: [0, 2], 2: [1, 3], 3: [0, 2]}
SIDE = {0: "A", 1: "A", 2: "B", 3: "B"}


class _Obs:
    def __init__(self, t: float) -> None:
        self.local_track_id = 1
        self.embedding = np.ones(8, dtype=np.float32) / np.sqrt(8)
        self.conf = 0.9
        self.quality = 0.8
        self.t_media = t


def _emit(store: LocalStore, n: int, t0: float = 0.0) -> None:
    for i in range(n):
        store.append_local_observation(_Obs(t0 + i))


def _seqs(store: LocalStore, node_id: int) -> set[int]:
    return {c["seq"] for c in store.claims_since(VersionVector({})) if c["node_id"] == node_id}


def test_claim_ranges_report_prefix_and_extras():
    src = LocalStore(db_path=":memory:", node_id=0)
    _emit(src, 10)
    dst = LocalStore(db_path=":memory:", node_id=1)
    by_seq = {c["seq"]: c for c in src.claims_since(VersionVector({}))}
    dst.append_remote_claims([by_seq[s] for s in (0, 1, 2, 7, 8, 9)])
    assert dst.claim_ranges() == {0: [(0, 2), (7, 9)]}
    assert VersionVector.from_store(dst).gaps() == {0: [(3, 6)]}


def test_gap_below_max_seq_is_filled():
    """The original limitation: max-only VV says 'caught up to 9' and the
    holes 3..6 are never requested. Gap-aware digests fix that."""
    src = LocalStore(db_path=":memory:", node_id=0)
    _emit(src, 10)
    dst = LocalStore(db_path=":memory:", node_id=1)
    by_seq = {c["seq"]: c for c in src.claims_since(VersionVector({}))}
    dst.append_remote_claims([by_seq[s] for s in (0, 1, 2, 7, 8, 9)])

    # Legacy max-only vector is blind to the hole:
    assert AntiEntropy(src).on_digest(VersionVector(dst.claim_version_vector())) == []

    ae_src, ae_dst = AntiEntropy(src), AntiEntropy(dst)
    delta = ae_src.on_digest(VersionVector.from_store(dst))
    assert [c["seq"] for c in delta] == [3, 4, 5, 6]
    ae_dst.on_delta(delta)
    assert _seqs(dst, 0) == set(range(10))
    # Idempotent: replaying changes nothing.
    assert ae_dst.on_delta(delta) == 0


def test_digest_roundtrips_over_the_wire_format():
    src = LocalStore(db_path=":memory:", node_id=0)
    _emit(src, 6)
    vv = VersionVector({0: 5}, {0: [(0, 1), (4, 5)], 2: [(3, 9)]})
    back = VersionVector.unpack(vv.pack())
    assert back.ranges == vv.ranges and back.as_dict() == vv.as_dict()


def test_prefix_gap_is_requested():
    src = LocalStore(db_path=":memory:", node_id=0)
    _emit(src, 5)
    ae = AntiEntropy(src)
    # peer holds only 3..4 of node 0's claims: missing 0..2 (a prefix hole)
    delta = ae.on_digest(VersionVector({0: 4}, {0: [(3, 4)]}))
    assert [c["seq"] for c in delta] == [0, 1, 2]


def _run_heal(seed: int, loss: float) -> int:
    rng = random.Random(seed)
    stores = {i: LocalStore(db_path=":memory:", node_id=i) for i in range(4)}
    ae = {i: AntiEntropy(stores[i], max_delta=50) for i in range(4)}
    partitioned = False

    def link_ok(i: int, j: int) -> bool:
        return not (partitioned and SIDE[i] != SIDE[j])

    def lossy_publish(i: int, claims: list[dict]) -> None:
        """Push freshly-made claims to neighbours the way plain gossip
        would: each copy independently lost with prob `loss`."""
        for j in RING[i]:
            if link_ok(i, j):
                for c in claims:
                    if rng.random() > loss:
                        stores[j].append_remote_claims([c])

    def gen(n: int) -> None:
        for i in range(4):
            before = stores[i].claim_version_vector().get(i, -1)
            _emit(stores[i], n, t0=float(before + 1))
            new = [c for c in stores[i].claims_since(VersionVector({})) if c["node_id"] == i and c["seq"] > before]
            lossy_publish(i, new)

    def ae_round() -> None:
        for i in range(4):
            digest = VersionVector.from_store(stores[i])
            for j in RING[i]:
                if not link_ok(i, j):
                    continue
                delta = ae[j].on_digest(digest)
                chunks = [delta[k : k + CHUNK] for k in range(0, len(delta), CHUNK)]
                rng.shuffle(chunks)  # out-of-order delivery
                for ch in chunks:
                    if rng.random() > loss:
                        ae[i].on_delta(ch)

    def ordered(i: int) -> list[dict]:
        return ClaimSet(stores[i]).ordered()

    gen(10)
    for _ in range(10):
        ae_round()
    partitioned = True
    gen(15)
    for _ in range(10):
        ae_round()
    assert ordered(0) == ordered(1) and ordered(2) == ordered(3)
    assert ordered(0) != ordered(2), "sides must have diverged"
    partitioned = False
    for rounds in range(1, 61):
        ae_round()
        if all(ordered(i) == ordered(0) for i in range(1, 4)):
            return rounds
    raise AssertionError("did not converge within 60 anti-entropy rounds")


@pytest.mark.parametrize("seed", range(8))
def test_four_nodes_heal_to_byte_identical_claim_sets_over_lossy_link(seed):
    rounds = _run_heal(seed, loss=0.3)
    assert rounds <= 60


def test_multi_origin_digest_signature_survives_a_wire_roundtrip(tmp_path):
    """Regression: protobuf map fields don't keep their order across a
    parse round-trip, so a digest naming >=2 origin nodes used to fail
    signature verification at every receiver (silently dropping the
    anti-entropy digests that matter most). Sign/verify is now over the
    deterministic serialisation."""
    from starling_net.keys import generate_keypair, load_keys
    from starling_proto.generated import starling_pb2

    generate_keypair(0, keys_dir=tmp_path)
    keys = load_keys(0, keys_dir=tmp_path)
    vv = VersionVector({3: 30, 0: 5, 2: 20, 1: 11}, {n: [(0, s)] for n, s in {3: 30, 0: 5, 2: 20, 1: 11}.items()})
    for _ in range(50):
        env = starling_pb2.Envelope(sender_node_id=0)
        env.vv_digest.ParseFromString(vv.pack())
        env.vv_digest.signature = b""
        env.vv_digest.signature = keys.sign(env.vv_digest.SerializeToString(deterministic=True))
        rx = starling_pb2.Envelope()
        rx.ParseFromString(env.SerializeToString())
        unsigned = starling_pb2.VVDigest()
        unsigned.CopyFrom(rx.vv_digest)
        unsigned.signature = b""
        assert keys.verify(0, unsigned.SerializeToString(deterministic=True), rx.vv_digest.signature)


def test_resolver_ignores_a_claim_with_a_mismatched_embedding_dimension():
    """A Byzantine (or misconfigured) node sending a wrong-dimension
    embedding must not crash the resolver: it is just incomparable."""
    from starling_crdt.resolver import _cosine

    assert _cosine(np.ones(64, dtype=np.float32), np.ones(512, dtype=np.float32)) == 0.0
    assert _cosine(np.ones(8, dtype=np.float32), np.ones(8, dtype=np.float32)) == pytest.approx(1.0)


def test_attack_injector_fabricates_embeddings_of_the_deployments_dimension():
    from starling_consensus.attacks import AttackInjector
    from starling_geometry.navmesh import NavMesh
    from pathlib import Path

    nm = NavMesh.from_geojson(Path(__file__).resolve().parent.parent / "data/floorplan/warehouse_demo.geojson")
    inj = AttackInjector(node_id=2, attack="fabricate", intensity=1.0, seed=1, embed_dim=64)
    out = inj.apply_to_claims([], 1.0, nm)
    assert len(out) == 1 and len(np.frombuffer(out[0]["embedding"], dtype=np.float32)) == 64
