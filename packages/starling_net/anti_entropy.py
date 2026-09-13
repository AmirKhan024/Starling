"""starling_net/anti_entropy.py
---------------------------------
Version-vector anti-entropy delta sync. Without this, a partition never
heals: gossip alone only propagates a claim forward through whoever
happens to be listening at broadcast time, and delivers nothing to a node
that reconnects after missing some window of messages. Anti-entropy
periodically compares two nodes' version vectors and fills the gap.

Deliberately NOT a Merkle tree: a full-table version-vector diff is plenty
at this project's scale (a handful of nodes, bounded claim volume) and is
far simpler to defend in a viva than a Merkle-tree sync protocol would be.

`on_digest`/`on_delta` are pure with respect to the network — they take
already-received data and return/apply results — so the convergence logic
below is fully testable without any real transport (tests/test_anti_entropy
.py never opens a socket). `tick()` is the only method that touches
`gossip` directly, since it's the one that actually sends something.
"""

from __future__ import annotations

import random
from typing import Any, Optional

from starling_net.gossip import GossipNode
from starling_net.logging import get_logger
from starling_proto.generated import starling_pb2

logger = get_logger(__name__)

DEFAULT_MAX_DELTA = 200


class VersionVector:
    """`{node_id: highest seq seen from that node}`. A node_id absent from
    the vector is equivalent to seq=-1 (nothing seen from it yet).
    """

    def __init__(self, seqs: Optional[dict[int, int]] = None) -> None:
        self._seqs: dict[int, int] = dict(seqs or {})

    def get(self, node_id: int, default: int = -1) -> int:
        return self._seqs.get(node_id, default)

    def as_dict(self) -> dict[int, int]:
        return dict(self._seqs)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, VersionVector) and self._seqs == other._seqs

    def __repr__(self) -> str:
        return f"VersionVector({self._seqs!r})"

    def merge(self, other: "VersionVector") -> "VersionVector":
        merged = dict(self._seqs)
        for node_id, seq in other._seqs.items():
            merged[node_id] = max(merged.get(node_id, -1), seq)
        return VersionVector(merged)

    def dominates(self, other: "VersionVector") -> bool:
        """True iff self has seen everything `other` has (self >= other,
        component-wise across every node_id `other` knows about).
        """
        return all(self.get(node_id) >= seq for node_id, seq in other._seqs.items())

    def missing_from(self, other: "VersionVector") -> dict[int, int]:
        """`{node_id: count}` of claims `other` is missing relative to
        self, for each node_id where self is ahead of `other`.
        """
        result: dict[int, int] = {}
        for node_id, seq in self._seqs.items():
            their_seq = other.get(node_id)
            if seq > their_seq:
                result[node_id] = seq - their_seq
        return result

    def pack(self) -> bytes:
        msg = starling_pb2.VVDigest()
        for node_id, seq in self._seqs.items():
            msg.seq_by_node[node_id] = seq
        return msg.SerializeToString()

    @classmethod
    def unpack(cls, data: bytes) -> "VersionVector":
        msg = starling_pb2.VVDigest()
        msg.ParseFromString(data)
        return cls(dict(msg.seq_by_node))


class AntiEntropy:
    def __init__(
        self,
        local_store,
        gossip: Optional[GossipNode] = None,
        interval_s: float = 2.0,
        max_delta: int = DEFAULT_MAX_DELTA,
    ) -> None:
        self.local_store = local_store
        self.gossip = gossip
        self.interval_s = interval_s
        self.max_delta = max_delta

    def tick(self) -> None:
        """Pick ONE random neighbour and gossip our version vector to it.

        The underlying transport (starling_net.gossip.GossipNode) is
        PUB/SUB, which delivers to every subscribed neighbour, not a
        single addressed one — there is no point-to-point primitive in
        this project's transport layer, and building one is out of scope
        for "roughly 200 lines". Picking one neighbour still rate-limits
        how often this node initiates a round (one digest broadcast per
        tick, not one per neighbour per tick); any neighbour that
        overhears it can reply, which only speeds up convergence since
        `on_delta` is idempotent regardless of who sends what.
        """
        if self.gossip is None or not self.gossip.neighbours:
            return

        peer = random.choice(self.gossip.neighbours)
        vv = VersionVector(self.local_store.claim_version_vector())

        envelope = starling_pb2.Envelope(sender_node_id=self.local_store.node_id)
        envelope.vv_digest.ParseFromString(vv.pack())

        logger.info("anti_entropy_tick", peer=peer, vv=vv.as_dict())
        self.gossip.publish(envelope)

    def on_digest(self, their_vv: VersionVector) -> list[dict[str, Any]]:
        """Given a peer's version vector, return up to `max_delta` claims
        (this node's own store) they are missing, ordered by (node_id,
        seq) so a long partition heals over several bounded rounds rather
        than one enormous message.
        """
        return self.local_store.claims_since(their_vv)[: self.max_delta]

    def on_delta(self, claims: list[dict[str, Any]]) -> int:
        """Append received claims locally. Idempotent — re-delivery is a
        no-op (`LocalStore.append_remote_claims`), which is exactly what
        makes the claim set a CRDT.
        """
        if not claims:
            return 0
        return self.local_store.append_remote_claims(claims)
