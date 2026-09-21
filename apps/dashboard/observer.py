"""apps/dashboard/observer.py
------------------------------
`GossipObserver`: the dashboard's ONLY channel onto the mesh (WP-13, C4/L
panel "Node health" + "Network" + the floor-plan candidate region). A
passive, SUB-only gossip participant: it never binds a PUB socket, never
signs or sends a message, and connects only to the node addresses it is
explicitly configured with. It therefore sees exactly the claims,
attestations, and reputation opinions that were actually gossiped between
real nodes — the same view any node in its position would have, never
more (CLAUDE.md rule 8: "the dashboard is a read-only gossip observer with
no privileged access").

Deliberately NOT a `starling_net.gossip.GossipNode`: that class always
binds its own PUB port in `start()` (see its own module docstring). Giving
the dashboard one would either force it to itself become a publishing
gossip peer — a structural privilege it must never have — or bind a real
port that does nothing. This module re-implements only the SUB half of
that class's poll loop, purpose-built for a node that only ever listens.

No sqlite3 connection to any node's database, and no filesystem read of
any node's own per-node data directory anywhere in this module or the
rest of `apps/dashboard/` (enforced by `tests/test_dashboard_observer.py`'s
grep test). The one
`LocalStore` instance held here is `:memory:` — an ephemeral scratch space
this process owns for itself, needed only because `ClaimSet` is defined in
terms of that interface; it is never written to disk and never points at
a node's own `db_path`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import zmq
from nacl.signing import SigningKey

from starling_consensus.attacks import SYNTHETIC_SEQ_BASE
from starling_crdt.claims import ClaimSet
from starling_consensus.reputation import ReputationTable
from starling_net.anti_entropy import VersionVector
from starling_net.keys import NodeKeys, load_peer_pubkeys
from starling_net.logging import get_logger
from starling_node.config import ReputationConfig
from starling_proto.convert import claim_proto_to_record
from starling_proto.generated import starling_pb2
from starling_store.identity_store import LocalStore

logger = get_logger(__name__)

_POLL_TIMEOUT_MS = 200
_MAX_ATTESTATIONS = 5000  # bounded buffer — an observer that ran for days must not grow unboundedly
_OBSERVER_NODE_ID = -1  # never enrolled as a real peer; used only as this process's own label


@dataclass
class _TypeStats:
    recv: int = 0
    recv_bytes: int = 0


class GossipObserver:
    """`peers`: `{node_id: "host:port"}` for every node's own gossip PUB
    address (WP-13's config, see `apps/dashboard/config.py`). Verification
    uses every peer's enrolled public key from `keys_dir`; this process
    generates a throwaway, never-enrolled signing key purely to satisfy
    `NodeKeys`'s constructor — it is never used to sign anything, since
    this observer never publishes.
    """

    def __init__(self, peers: dict[int, str], keys_dir: Path) -> None:
        self.peers = dict(peers)
        peer_pubkeys = load_peer_pubkeys(keys_dir)
        self._keys = NodeKeys(node_id=_OBSERVER_NODE_ID, signing_key=SigningKey.generate(), peer_pubkeys=peer_pubkeys)

        self.store = LocalStore(db_path=":memory:", node_id=_OBSERVER_NODE_ID)
        self.claims = ClaimSet(self.store)
        self.reputation = ReputationTable(node_id=_OBSERVER_NODE_ID, cfg=ReputationConfig())
        self.attestations: list[starling_pb2.CoverageAttestation] = []

        self._ctx = zmq.Context.instance()
        self._subs: list[zmq.Socket] = []
        self._poller = zmq.Poller()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._lock = threading.Lock()
        self._stats: dict[str, _TypeStats] = {}
        # Per-sender byte counts, kept SEPARATELY from `_stats`'s per-kind
        # breakdown — the Node Health panel's "bytes/s" column needs bytes
        # by WHICH node sent them, something neither the wire schema nor
        # `starling_net.gossip.GossipNode.stats()` tracks (that one only
        # ever counts its own send/recv, never broken out by peer). This
        # is a purely additive, read-only tally over what already arrives.
        self._bytes_by_sender: dict[int, int] = {}
        self._dropped = 0
        # Latest gap-aware version vector each node itself gossiped in its
        # anti-entropy digest — how the dashboard learns "how many claims
        # does node N hold" from gossip alone, never from a node's DB.
        self._digests: dict[int, VersionVector] = {}
        self.catchup_ids: set[str] = set()  # claims that arrived in anti-entropy deltas
        self._last_seen: dict[int, float] = {}
        self._start_time: Optional[float] = None

    def start(self) -> None:
        for node_id, addr in self.peers.items():
            sub = self._ctx.socket(zmq.SUB)
            sub.connect(f"tcp://{addr}")
            sub.setsockopt(zmq.SUBSCRIBE, b"")
            self._subs.append(sub)
            self._poller.register(sub, zmq.POLLIN)

        self._start_time = time.monotonic()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="dashboard-observer")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        for sub in self._subs:
            sub.close(linger=0)
        self._subs = []

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                socks = dict(self._poller.poll(timeout=_POLL_TIMEOUT_MS))
            except zmq.ZMQError:
                return
            for sub in self._subs:
                if socks.get(sub) == zmq.POLLIN:
                    try:
                        raw = sub.recv(zmq.NOBLOCK)
                    except zmq.Again:
                        continue
                    self._handle_raw(raw)

    def _handle_raw(self, raw: bytes) -> None:
        envelope = starling_pb2.Envelope()
        try:
            envelope.ParseFromString(raw)
        except Exception:
            self._dropped += 1
            return

        payload_kind = envelope.WhichOneof("payload")
        if payload_kind is None:
            self._dropped += 1
            return

        inner = getattr(envelope, payload_kind)
        sig = getattr(inner, "signature", b"")
        if not sig:
            logger.warning("dashboard_observer_drop_unsigned", sender=envelope.sender_node_id)
            self._dropped += 1
            return

        unsigned = type(inner)()
        unsigned.CopyFrom(inner)
        unsigned.signature = b""
        if not self._keys.verify(envelope.sender_node_id, unsigned.SerializeToString(deterministic=True), sig):
            logger.warning("dashboard_observer_drop_bad_signature", sender=envelope.sender_node_id)
            self._dropped += 1
            return

        with self._lock:
            self._last_seen[envelope.sender_node_id] = time.monotonic()
            stats = self._stats.setdefault(payload_kind, _TypeStats())
            stats.recv += 1
            stats.recv_bytes += len(raw)
            self._bytes_by_sender[envelope.sender_node_id] = (
                self._bytes_by_sender.get(envelope.sender_node_id, 0) + len(raw)
            )

        if payload_kind == "claim":
            self.claims.add(claim_proto_to_record(envelope.claim))
        elif payload_kind == "attestation":
            self.attestations.append(envelope.attestation)
            if len(self.attestations) > _MAX_ATTESTATIONS:
                self.attestations.pop(0)
        elif payload_kind == "reputation":
            self.reputation.ingest_gossiped(envelope.reputation)
        elif payload_kind == "vv_digest":
            with self._lock:
                self._digests[envelope.sender_node_id] = VersionVector.from_proto(envelope.vv_digest)
        elif payload_kind == "vv_delta":
            # Claims a peer sent another peer to fill a gap: overheard like
            # any other gossip, and merged into the same grow-only set.
            for c in envelope.vv_delta.claims:
                rec = claim_proto_to_record(c)
                self.claims.add(rec)
                self.catchup_ids.add(rec["claim_id"])
        # topology is not consumed here; this observer never participates
        # in anti-entropy itself (it has nothing of its own to offer a
        # peer; see module docstring) — it only reads digests and deltas.

    def node_claim_counts(self) -> dict[int, int]:
        """`{node_id: claims that node held as of its latest digest}`,
        summed from the gap-aware ranges the node itself gossiped (capped
        at `MAX_RUNS_PER_NODE` runs per origin, so a hugely fragmented
        replica under-reports rather than over-reports).
        """
        with self._lock:
            digests = dict(self._digests)
        out: dict[int, int] = {}
        for node_id, vv in digests.items():
            ranges = vv.ranges
            if ranges is None:
                out[node_id] = sum(s + 1 for s in vv.as_dict().values())
            else:
                out[node_id] = sum(hi - lo + 1 for runs in ranges.values() for lo, hi in runs)
        return out

    def node_holes(self) -> dict[int, int]:
        """`{node_id: number of claims that node's own latest digest reports
        as missing BELOW its highest seq per origin}` — the exact "still has
        gaps" signal (0 = gap-free), as gossiped by the node itself.
        """
        with self._lock:
            digests = dict(self._digests)
        # Runs at/above SYNTHETIC_SEQ_BASE are attack-injected claims (a
        # separate seq space, see AttackInjector), so the "gap" between the
        # honest sequence and that space is not a hole in the honest set.
        base = SYNTHETIC_SEQ_BASE
        return {
            node_id: sum(
                hi - lo + 1
                for holes in vv.gaps().values()
                for lo, hi in holes
                if hi < base
            )
            for node_id, vv in digests.items()
        }

    def stats(self) -> dict:
        """Same shape as `starling_net.gossip.GossipNode.stats()` (recv
        side only, since this observer never sends) — the Network panel's
        "bytes by message type" source.
        """
        with self._lock:
            out = {kind: vars(s).copy() for kind, s in self._stats.items()}
        out["_dropped"] = self._dropped
        out["_uptime_s"] = (time.monotonic() - self._start_time) if self._start_time else 0.0
        return out

    def bytes_per_node_since_start(self) -> dict[int, float]:
        """Total bytes received attributed to each sender node_id since
        `start()` — the Node Health panel's raw material for a bytes/s
        column (divide by uptime at display time; kept as a total here so
        callers can choose their own averaging window).
        """
        with self._lock:
            return dict(self._bytes_by_sender)

    def liveness(self, stale_after_s: float) -> dict[int, bool]:
        """`{node_id: online}` for every configured peer. A node this
        observer has never heard a signed message from at all is offline,
        the same honest-blindness posture as one that has gone stale.
        """
        now = time.monotonic()
        with self._lock:
            last_seen = dict(self._last_seen)
        return {node_id: (node_id in last_seen and now - last_seen[node_id] < stale_after_s) for node_id in self.peers}

    def coverage_completeness(self, stale_after_s: float) -> float:
        """Fraction of configured peers currently live — mirrors
        `starling_net.partition.PartitionTracker.coverage_completeness`'s
        definition, computed independently here since the observer is not
        itself a mesh participant `PartitionTracker` could attach to.
        """
        if not self.peers:
            return 1.0
        online = self.liveness(stale_after_s)
        return sum(1 for v in online.values() if v) / len(online)
