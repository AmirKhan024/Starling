"""starling_net/gossip.py
--------------------------
Signed ZeroMQ gossip transport for the Starling node mesh.

Why ZeroMQ and not ROS 2 (STARLING_BUILD_STATE.md WP-04): ROS 2 / Cyclone
DDS is the spec's other suggested option, but its learning curve is a week
this project doesn't have, and its discovery protocol defaults to a full
mesh that would then need deliberately restricting — more moving parts for
no benefit at this scale. `pyzmq` is a small, well-understood, pure
dependency: one PUB socket per node, one SUB socket per configured
neighbour, no daemon, no broker. That shape is directly CLAUDE.md rule 4
("gossip goes to a configured neighbour set, never a full mesh") — the
neighbour list defines the mesh's edges by construction, not by policy on
top of a fuller substrate.

CLAUDE.md rule 4 enforced in code: this node's own outgoing publish always
goes out on its own bound PUB socket; `neighbours` controls only which
peers' PUB sockets THIS node's SUB sockets connect to (a pull model — who
listens to whom is symmetric-by-configuration across the mesh, never a
push to an arbitrary destination list). There is no broadcast-to-all
code path anywhere in this module: the only loops here are over
`self._subs` (this node's own configured neighbours) and `self._stats`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import zmq

from starling_net.keys import NodeKeys
from starling_net.logging import get_logger
from starling_proto.generated import starling_pb2
from starling_proto.limits import assert_wire_safe

logger = get_logger(__name__)

_POLL_TIMEOUT_MS = 200


@dataclass
class _TypeStats:
    sent: int = 0
    sent_bytes: int = 0
    recv: int = 0
    recv_bytes: int = 0


class GossipNode:
    def __init__(
        self,
        node_id: int,
        listen_port: int,
        neighbours: list[str],
        keys: NodeKeys,
        on_message: Callable[["starling_pb2.Envelope"], None],
    ) -> None:
        self.node_id = node_id
        self.listen_port = listen_port
        self.neighbours = list(neighbours)
        self.keys = keys
        self.on_message = on_message

        self._ctx = zmq.Context.instance()
        self._pub: Optional[zmq.Socket] = None
        self._subs: list[zmq.Socket] = []
        self._poller = zmq.Poller()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stats: dict[str, _TypeStats] = {}
        self._stats_lock = threading.Lock()
        # A ZeroMQ socket must never be used from two threads at once. publish()
        # is called from a node's main loop AND from its gossip-receive thread
        # (anti-entropy replies), so sends are serialised; without this, heavy
        # anti-entropy traffic crashed a node with a libzmq assertion.
        self._pub_lock = threading.Lock()
        self._dropped = 0
        self._start_time: Optional[float] = None

        if not self.neighbours:
            logger.warning("gossip_node_isolated_by_configuration", node_id=node_id)

    def start(self) -> None:
        self._pub = self._ctx.socket(zmq.PUB)
        self._pub.bind(f"tcp://*:{self.listen_port}")

        for addr in self.neighbours:
            sub = self._ctx.socket(zmq.SUB)
            sub.connect(f"tcp://{addr}")
            sub.setsockopt(zmq.SUBSCRIBE, b"")
            self._subs.append(sub)
            self._poller.register(sub, zmq.POLLIN)

        self._start_time = time.monotonic()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name=f"gossip-{self.node_id}"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._pub:
            self._pub.close(linger=0)
            self._pub = None
        for sub in self._subs:
            sub.close(linger=0)
        self._subs = []

    def publish(self, envelope: "starling_pb2.Envelope") -> None:
        """Signs the payload with this node's own key and sends on this
        node's own PUB socket ONLY. If this node has no configured
        neighbours it is isolated by configuration (logged at
        construction) and publish() is a deliberate no-op — there is
        nothing this node's gossip could reach, so it does not fabricate a
        send.
        """
        if not self.neighbours:
            return

        payload_kind = envelope.WhichOneof("payload")
        if payload_kind is None:
            raise ValueError("Envelope has no payload set")

        inner = getattr(envelope, payload_kind)
        inner.signature = b""
        inner.signature = self.keys.sign(inner.SerializeToString(deterministic=True))

        assert_wire_safe(envelope)
        raw = envelope.SerializeToString()
        with self._pub_lock:
            self._pub.send(raw)
        self._record(payload_kind, len(raw), sent=True)

    def stats(self) -> dict:
        with self._stats_lock:
            out = {kind: vars(s).copy() for kind, s in self._stats.items()}
        out["_dropped"] = self._dropped
        out["_uptime_s"] = (time.monotonic() - self._start_time) if self._start_time else 0.0
        return out

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
            logger.warning("gossip_drop_malformed", node_id=self.node_id)
            self._dropped += 1
            return

        payload_kind = envelope.WhichOneof("payload")
        if payload_kind is None:
            logger.warning("gossip_drop_no_payload", node_id=self.node_id)
            self._dropped += 1
            return

        inner = getattr(envelope, payload_kind)
        sig = inner.signature
        if not sig:
            logger.warning(
                "gossip_drop_unsigned", node_id=self.node_id, sender=envelope.sender_node_id
            )
            self._dropped += 1
            return

        unsigned = type(inner)()
        unsigned.CopyFrom(inner)
        unsigned.signature = b""
        if not self.keys.verify(envelope.sender_node_id, unsigned.SerializeToString(deterministic=True), sig):
            logger.warning(
                "gossip_drop_bad_signature",
                node_id=self.node_id,
                sender=envelope.sender_node_id,
            )
            self._dropped += 1
            return

        self._record(payload_kind, len(raw), sent=False)
        self.on_message(envelope)

    def _record(self, kind: str, size: int, sent: bool) -> None:
        with self._stats_lock:
            stats = self._stats.setdefault(kind, _TypeStats())
            if sent:
                stats.sent += 1
                stats.sent_bytes += size
            else:
                stats.recv += 1
                stats.recv_bytes += size
