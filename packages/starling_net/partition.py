"""starling_net/partition.py
------------------------------
Per-neighbour liveness tracking (WP-06 Part 4a). A node has no way to ask
"is my neighbour still there" other than noticing it has stopped hearing
from it — there is no heartbeat/ping primitive in this project's PUB/SUB
transport (STARLING_BUILD_STATE.md WP-04), so liveness is inferred purely
from the claims a neighbour has (or hasn't) actually gossiped recently.

`GossipNode` has no relay/forwarding logic (STARLING_BUILD_STATE.md §4.1:
apps/node.py currently just logs and ignores what it receives — merging
is this work package's job), so every `Envelope` a node currently
receives was published directly by the peer named in `sender_node_id`.
That means "have I heard from node_id X recently" is exactly "is my
direct connection to X currently alive" — no address-to-node_id mapping
is needed.

"A node must always know, and always state, how blind it currently is"
(STARLING_BUILD_STATE.md WP-06 Part 4a) — `coverage_completeness` is that
number, and it is meant to be bound into every subsequent log line via
`structlog.contextvars` (see `starling_net.logging.setup_logging`), not
just returned to whoever happens to call this class's methods directly.
"""

from __future__ import annotations

from typing import Optional


class PartitionTracker:
    """Tracks, for one node, how many gossip "rounds" (caller-defined —
    typically one per housekeeping tick) have passed since each
    configured neighbour was last heard from. A neighbour not yet heard
    from at all starts already stale (not reachable) — a node that has
    exchanged nothing with anyone yet genuinely does not know its
    neighbours are up, and should not claim full coverage before it has
    any evidence of it.
    """

    def __init__(self, neighbour_node_ids: list[int], stale_after_rounds: int = 3) -> None:
        self.neighbour_node_ids = sorted(set(neighbour_node_ids))
        self.stale_after_rounds = stale_after_rounds
        self._rounds_since_seen: dict[int, int] = {
            n: stale_after_rounds for n in self.neighbour_node_ids
        }
        self._fully_covered = False  # tracks the last coverage_completeness >= 1.0 state

    def on_message(self, sender_node_id: int) -> None:
        """Call whenever a signed, verified gossip message from
        `sender_node_id` is received."""
        if sender_node_id in self._rounds_since_seen:
            self._rounds_since_seen[sender_node_id] = 0

    def tick(self) -> None:
        """Call once per gossip round (e.g. one housekeeping interval)."""
        for n in self._rounds_since_seen:
            self._rounds_since_seen[n] += 1

    def reachable_neighbours(self) -> list[int]:
        return sorted(
            n for n, rounds in self._rounds_since_seen.items() if rounds < self.stale_after_rounds
        )

    def coverage_completeness(self) -> float:
        """`reachable_neighbours / configured_neighbours`. A node with no
        configured neighbours is trivially fully covered (nothing to be
        blind to) rather than reporting a division-by-zero 0.0, which
        would misleadingly read as "totally isolated".
        """
        if not self.neighbour_node_ids:
            return 1.0
        return len(self.reachable_neighbours()) / len(self.neighbour_node_ids)

    def check_partition_event(self) -> Optional[str]:
        """Call after `tick()` (and after any `on_message()` calls for
        this round). Returns `"PARTITION_DETECTED"` or `"PARTITION_HEALED"`
        exactly when `coverage_completeness()` has just crossed the
        full/partial boundary since the last call, else `None`. A node
        that starts below full coverage (the common case — it has not yet
        exchanged anything with anyone) reports nothing until it first
        reaches full coverage, which fires `"PARTITION_HEALED"`: reaching
        full connectivity for the first time and recovering it after a
        real partition are deliberately not distinguished.
        """
        full = self.coverage_completeness() >= 1.0
        if full and not self._fully_covered:
            self._fully_covered = True
            return "PARTITION_HEALED"
        if not full and self._fully_covered:
            self._fully_covered = False
            return "PARTITION_DETECTED"
        return None
