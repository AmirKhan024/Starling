"""starling_sim/messages.py
----------------------------
Topic names for the simulator's ZMQ PUB socket (starling_sim.transport).
Every sim-mode node subscribes to exactly one `node_topic(its own id)` —
never any other node's topic (the simulator's "only ever send a node its
own zone" rule). The dashboard subscribes only to `GROUND_TRUTH_TOPIC`, for
its faint "true position" overlay layer.
"""

from __future__ import annotations

GROUND_TRUTH_TOPIC = "ground_truth"


def node_topic(node_id: int) -> str:
    return f"node:{node_id}"
