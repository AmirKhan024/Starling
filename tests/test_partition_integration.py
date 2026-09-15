"""tests/test_partition_integration.py
----------------------------------------
The headline C1 test (STARLING_BUILD_STATE.md WP-06 Part 4c): four
in-process nodes, partitioned and healed, reach byte-identical claim sets
and Assignments with no coordinator — and a genuinely ambiguous identity
binding created across the partition is surfaced as an OPEN fork after
healing, not silently resolved.

Runs locally, no Docker: four real `starling_net.gossip.GossipNode`
instances on loopback (a ring topology — 0-1-2-3-0 — the same shape
`configs/nodes/local/*.yaml` uses, per CLAUDE.md rule 4: a configured
neighbour set, never a full mesh), wired through a small `_Mesh` harness
with a controllable "drop everything between group A ([0,1]) and group B
([2,3])" switch.

Scope note on transport (CLAUDE.md ambiguity-resolution rule, since the
WP-06 prompt names real GossipNodes first): the four `GossipNode`s above
are real sockets and carry every claim published during the test, with
the partition switch enforced at the (real, signature-verified)
`on_message` handler. Convergence itself, though, is additionally driven
by direct calls into each store's `starling_net.anti_entropy.AntiEntropy`
(`on_digest`/`on_delta` — pure functions, already proven correct in
tests/test_anti_entropy.py) rather than by also wiring a full
digest/reply protocol over PUB/SUB in this test. PUB/SUB has no
replay/persistence (a message published before a subscriber's slow-joiner
connection settles is simply lost forever), so pure forward gossip alone
cannot guarantee convergence even without a partition; real deployments
close that gap with periodic anti-entropy rounds (WP-04), and calling
that mechanism directly here is what makes "byte-identical after heal" a
reliable assertion instead of a timing-dependent one, without redoing
WP-04's own transport-wiring work inside a WP-06 test.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path

import numpy as np
import pytest
from ulid import ULID

from starling_crdt.claims import ClaimSet
from starling_crdt.forks import ForkStatus
from starling_crdt.resolver import resolve
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_net.anti_entropy import AntiEntropy, VersionVector
from starling_net.gossip import GossipNode
from starling_net.keys import generate_keypair, load_keys
from starling_node.config import MatchConfig
from starling_proto.convert import claim_proto_to_record, make_claim_envelope, record_to_claim_proto
from starling_store.identity_store import LocalStore

# Ring topology: 0-1-2-3-0. Partitioning [0,1] vs [2,3] cuts exactly the
# two edges crossing the group boundary (1-2 and 3-0); 0-1 and 2-3 stay
# intact within each group.
_RING = {0: [1, 3], 1: [0, 2], 2: [1, 3], 3: [0, 2]}
_GROUP = {0: "A", 1: "A", 2: "B", 3: "B"}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _open_room(cell_size: float = 0.5, size_m: float = 200.0) -> NavMesh:
    n = int(size_m / cell_size)
    return NavMesh(grid=np.ones((n, n), dtype=bool), origin=(0.0, 0.0), cell_size=cell_size)


def _claim(node_id, seq, t_media, embedding, world_xy=None, pos_sigma=0.0,
           anchor_type="UNANCHORED", identity_ref=None):
    # A real ULID, not a readable "C-{node_id}-{seq}" string: these claims
    # are published over the real wire (starling_proto.convert), which
    # encodes claim_id as a 16-byte ULID.
    return {
        "claim_id": str(ULID()),
        "node_id": node_id,
        "seq": seq,
        "hlc_physical_ms": int(t_media * 1000),
        "hlc_logical": 0,
        "local_track_id": 1,
        "t_media": t_media,
        "embedding": np.array(embedding, dtype=np.float32).tobytes(),
        "embed_scale": 1.0,
        "world_x": world_xy[0] if world_xy is not None else None,
        "world_y": world_xy[1] if world_xy is not None else None,
        "pos_sigma": pos_sigma,
        "anchor_type": anchor_type,
        "identity_ref": identity_ref,
        "confidence": 0.9,
        "quality": 0.8,
    }


def _cluster(i: int) -> tuple[float, float, float, float]:
    vecs = [(1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)]
    return vecs[i % len(vecs)]


class _Mesh:
    """Four real, signed, loopback GossipNodes plus each node's own
    LocalStore/AntiEntropy pair. See module docstring for the convergence
    scope note.
    """

    def __init__(self, tmp_path: Path) -> None:
        keys_dir = tmp_path / "keys"
        for i in range(4):
            generate_keypair(i, keys_dir=keys_dir)

        self.partitioned = False
        self.stores = {i: LocalStore(db_path=":memory:", node_id=i) for i in range(4)}
        self.ae = {i: AntiEntropy(self.stores[i], max_delta=10_000) for i in range(4)}

        ports = {i: _free_port() for i in range(4)}
        self.nodes: dict[int, GossipNode] = {}
        for i in range(4):
            neighbour_addrs = [f"127.0.0.1:{ports[j]}" for j in _RING[i]]
            keys = load_keys(i, keys_dir=keys_dir)
            self.nodes[i] = GossipNode(
                i, ports[i], neighbour_addrs, keys, on_message=self._make_handler(i)
            )
        for node in self.nodes.values():
            node.start()
        time.sleep(0.3)  # let PUB/SUB connections establish (slow-joiner problem)

    def _make_handler(self, i: int):
        def handler(envelope) -> None:
            sender = envelope.sender_node_id
            if self.partitioned and _GROUP[sender] != _GROUP[i]:
                return  # dropped: the other side of the current partition
            if envelope.WhichOneof("payload") == "claim":
                record = claim_proto_to_record(envelope.claim)
                self.stores[i].append_remote_claims([record])

        return handler

    def publish_claim(self, node_id: int, record: dict) -> None:
        self.stores[node_id].append_remote_claims([record])
        claim = record_to_claim_proto(record)
        envelope = make_claim_envelope(claim, sender_node_id=node_id)
        self.nodes[node_id].publish(envelope)

    def anti_entropy_round(self) -> int:
        """One pairwise anti-entropy pass over every currently-connected
        ring edge (both directions, since the outer loop visits each
        node's own neighbour list). Respects the current partition.
        """
        total = 0
        for i in range(4):
            for j in _RING[i]:
                if self.partitioned and _GROUP[i] != _GROUP[j]:
                    continue
                their_vv = VersionVector(self.stores[j].claim_version_vector())
                delta = self.ae[i].on_digest(their_vv)
                total += self.ae[j].on_delta(delta)
        return total

    def converge_within_current_partition(self, max_rounds: int = 20) -> int:
        rounds = 0
        for rounds in range(1, max_rounds + 1):
            if self.anti_entropy_round() == 0:
                break
        return rounds

    def claim_ids(self, node_id: int) -> set[str]:
        return {r["claim_id"] for r in self.stores[node_id].claims_since(VersionVector({}))}

    def stop(self) -> None:
        for node in self.nodes.values():
            node.stop()


@pytest.fixture
def mesh(tmp_path: Path):
    m = _Mesh(tmp_path)
    yield m
    m.stop()


def test_partition_then_heal_converges_to_byte_identical_replicas(mesh):
    t = 0.0
    next_seq = {0: 0, 1: 0, 2: 0, 3: 0}

    def emit(node_id: int) -> None:
        nonlocal t
        record = _claim(node_id, seq=next_seq[node_id], t_media=t, embedding=_cluster(node_id % 2))
        next_seq[node_id] += 1
        mesh.publish_claim(node_id, record)
        t += 1.0

    # Pre-partition: everyone converges normally.
    for i in range(4):
        emit(i)
    mesh.converge_within_current_partition()
    assert mesh.claim_ids(0) == mesh.claim_ids(1) == mesh.claim_ids(2) == mesh.claim_ids(3)

    # Partition [0,1] vs [2,3]. Both sides keep accepting and gossiping
    # claims independently.
    mesh.partitioned = True
    for _ in range(3):
        for i in range(4):
            emit(i)
    mesh.converge_within_current_partition()  # only heals WITHIN each side

    ids_a = mesh.claim_ids(0)
    ids_b = mesh.claim_ids(2)
    assert ids_a == mesh.claim_ids(1)
    assert ids_b == mesh.claim_ids(3)
    assert ids_a != ids_b, "the two sides should have genuinely diverged during the partition"

    # Heal.
    heal_started = time.monotonic()
    mesh.partitioned = False
    rounds_to_converge = mesh.converge_within_current_partition(max_rounds=20)
    time_to_reconverge_s = time.monotonic() - heal_started

    final_ids = [mesh.claim_ids(i) for i in range(4)]
    assert final_ids[0] == final_ids[1] == final_ids[2] == final_ids[3]

    cfg = MatchConfig()
    assignments = []
    for i in range(4):
        assignment, _ = resolve(
            ClaimSet(mesh.stores[i]), geometry=None, reputation=None, topology=None, cfg=cfg
        )
        assignments.append(assignment)
    for other in assignments[1:]:
        assert other.identity_of == assignments[0].identity_of
        assert other.trajectories == assignments[0].trajectories

    assert 1 <= rounds_to_converge <= 20
    assert time_to_reconverge_s < 10.0, "time-to-reconverge must be finite/bounded, not hung"


def test_partition_creates_genuinely_ambiguous_binding_fork_stays_open_after_heal(mesh):
    embedding = _cluster(0)

    anchor_a = _claim(
        node_id=0, seq=0, t_media=0.0, embedding=embedding,
        world_xy=(20.0, 20.0), pos_sigma=0.0, anchor_type="FACE_ANCHOR", identity_ref="P-100",
    )
    mesh.publish_claim(0, anchor_a)
    propagate_a = _claim(
        node_id=0, seq=1, t_media=1.0, embedding=embedding, world_xy=(21.0, 20.0), pos_sigma=0.0,
    )
    mesh.publish_claim(0, propagate_a)
    mesh.converge_within_current_partition()

    # While partitioned, group B independently anchors the SAME
    # identity_ref to a position that will turn out to be simultaneously
    # plausible with group A's trajectory once merged (same numbers
    # verified in tests/test_resolver.py's stays-open scenario).
    mesh.partitioned = True
    anchor_b = _claim(
        node_id=2, seq=0, t_media=2.0, embedding=embedding,
        world_xy=(23.5, 20.0), pos_sigma=0.0, anchor_type="FACE_ANCHOR", identity_ref="P-100",
    )
    mesh.publish_claim(2, anchor_b)
    mesh.converge_within_current_partition()

    mesh.partitioned = False
    mesh.converge_within_current_partition(max_rounds=20)
    assert mesh.claim_ids(0) == mesh.claim_ids(2)  # fully merged before resolving

    geometry = ReachabilityModel(_open_room(), v_max_m_s=1.6)
    cfg = MatchConfig()
    assignment, forks = resolve(
        ClaimSet(mesh.stores[0]), geometry=geometry, reputation=None, topology=None, cfg=cfg
    )

    open_forks = forks.open_forks()
    assert len(open_forks) == 1
    assert open_forks[0].identity_ref == "P-100"
    assert open_forks[0].status == ForkStatus.OPEN
    branch_claim_ids = {b.claim_ids for b in open_forks[0].branches}
    assert branch_claim_ids == {
        (anchor_a["claim_id"], propagate_a["claim_id"]),
        (anchor_b["claim_id"],),
    }
    # Both branches retained in the assignment — the ambiguity is
    # reported, not silently resolved.
    assert assignment.identity_of[anchor_b["claim_id"]] == "P-100"
