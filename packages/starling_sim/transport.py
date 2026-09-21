"""starling_sim/transport.py
-----------------------------
The simulator process's delivery mechanism: a single ZMQ PUB socket,
topic-filtered per node (`starling_sim.messages.node_topic`) plus one
ground-truth topic for the dashboard. Chosen over "each node replays its
own copy of the deterministic world" (the task brief's other acceptable
option) because the demo also needs a real, separate simulator OS process
publishing ground truth for the dashboard's overlay — with a live PUB
socket already required for that, reusing it for per-node delivery avoids
building and keeping two delivery mechanisms in sync.

This is NOT the signed gossip transport (`starling_net.gossip`) — it is a
local, unsigned, JSON-over-ZMQ side channel between the simulator process
and sim-mode node processes on the same machine, standing in for "a camera
handing a frame to its own node's perception pipeline". Nothing on this
socket ever reaches another node or the wider gossip mesh directly; a
sim-mode node still signs and gossips its own claims/attestations exactly
as the video path does.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import zmq

_ctx = zmq.Context.instance()


class SimPublisher:
    def __init__(self, bind_endpoint: str) -> None:
        self._sock = _ctx.socket(zmq.PUB)
        self._sock.bind(bind_endpoint)
        # Resolves a wildcard port ("tcp://127.0.0.1:*") to the actual
        # bound endpoint — needed by tests, and useful for logging the
        # real address when a config asks for an ephemeral port.
        self.endpoint = self._sock.getsockopt_string(zmq.LAST_ENDPOINT)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self._sock.send_multipart([topic.encode("utf-8"), json.dumps(payload).encode("utf-8")])

    def close(self) -> None:
        self._sock.close(linger=0)


class SimSubscriber:
    def __init__(self, connect_endpoint: str, topic: str) -> None:
        self._sock = _ctx.socket(zmq.SUB)
        self._sock.connect(connect_endpoint)
        self._sock.setsockopt_string(zmq.SUBSCRIBE, topic)

    def recv(self, timeout_ms: int = 1000) -> Optional[dict[str, Any]]:
        """One decoded message, or `None` if nothing arrived within
        `timeout_ms` — never blocks indefinitely, so a caller's shutdown
        signal check always gets a turn.
        """
        if self._sock.poll(timeout_ms, zmq.POLLIN) == 0:
            return None
        _topic, payload = self._sock.recv_multipart()
        return json.loads(payload.decode("utf-8"))

    def close(self) -> None:
        self._sock.close(linger=0)
