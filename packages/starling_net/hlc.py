"""starling_net/hlc.py
-----------------------
Hybrid Logical Clocks (Kulkarni et al., "Logical Physical Clocks", 2014).

An HLC timestamp is both physically meaningful (needed for reachability
and lost-threshold reasoning) and causally consistent (needed for
deterministic merge ordering across nodes with no coordinator). This is
what STARLING_BUILD_STATE.md §4.2's "same claim set -> same assignment"
guarantee is built on: if every node computes claim order the same
deterministic way, two replicas holding the same claims always compute the
same result, with no negotiation.

`physical_ms` passed into `now()`/`update()` ALWAYS comes from media time
(starling_net.timebase.MediaClock), never from `time.time()` — that is the
D-03 fix's whole point, and an HLC seeded from wall-clock reads would
silently reintroduce it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_PACK_FMT = "!QII"  # physical_ms (8B unsigned), logical (4B), node_id (4B) = 16 bytes


@dataclass(frozen=True)
class HLC:
    physical_ms: int
    logical: int
    node_id: int

    def pack(self) -> bytes:
        return struct.pack(_PACK_FMT, self.physical_ms, self.logical, self.node_id)

    @classmethod
    def unpack(cls, data: bytes) -> "HLC":
        physical_ms, logical, node_id = struct.unpack(_PACK_FMT, data)
        return cls(physical_ms=physical_ms, logical=logical, node_id=node_id)


class HLCClock:
    """One node's HLC generator. Not thread-safe by design — a node's
    identity path is single-threaded per CLAUDE.md rule 1 (one process, one
    replica); do not share an HLCClock across threads without a lock.
    """

    def __init__(self, node_id: int) -> None:
        self.node_id = node_id
        self._last = HLC(physical_ms=0, logical=0, node_id=node_id)

    def now(self, physical_ms: int) -> HLC:
        """Generate a new local HLC event (e.g. a claim this node observed)."""
        last = self._last
        if physical_ms > last.physical_ms:
            # The physical clock has genuinely advanced past our last
            # timestamp: reset the logical counter, physical time alone
            # disambiguates this event from the last one.
            new = HLC(physical_ms=physical_ms, logical=0, node_id=self.node_id)
        else:
            # physical_ms <= last.physical_ms: either the physical clock
            # hasn't advanced (same millisecond) or went backwards (clock
            # skew/replay). Either way, physical time alone can't
            # disambiguate consecutive events, so keep the last physical
            # time and bump the logical counter — this is what keeps HLC
            # monotonic even when the underlying clock isn't.
            new = HLC(physical_ms=last.physical_ms, logical=last.logical + 1, node_id=self.node_id)
        self._last = new
        return new

    def update(self, remote: HLC, physical_ms: int) -> HLC:
        """Merge a remote HLC (received with a message) with this node's
        clock on receipt, producing a new local HLC that is causally after
        both the remote event and everything this node has seen locally.
        """
        last = self._last
        pt = max(last.physical_ms, remote.physical_ms, physical_ms)

        if pt == last.physical_ms and pt == remote.physical_ms:
            # Our physical time ties with both our own last event and the
            # remote's: neither physical time wins, so take the larger of
            # the two logical counters and bump it past both.
            logical = max(last.logical, remote.logical) + 1
        elif pt == last.physical_ms:
            # Our own last physical time is the maximum (ahead of both the
            # remote's timestamp and our current physical reading): only
            # our own logical counter needs to advance.
            logical = last.logical + 1
        elif pt == remote.physical_ms:
            # The remote's physical time is the maximum: this event is
            # causally just after the remote's, so advance its logical
            # counter, not ours (which is now stale relative to pt).
            logical = remote.logical + 1
        else:
            # The fresh physical reading exceeds both prior physical times:
            # physical time alone disambiguates, so reset to zero.
            logical = 0

        new = HLC(physical_ms=pt, logical=logical, node_id=self.node_id)
        self._last = new
        return new


def claim_order_key(claim) -> tuple:
    """Deterministic total order for claims (STARLING_BUILD_STATE.md
    Appendix A.1): `(t_start.physical_ms, t_start.logical, node_id, seq)`.

    `(node_id, seq)` is globally unique (each node's `seq` is a strictly
    monotonic per-node counter), so this ordering never has ties. No RNG,
    no dict-iteration order, and no wall-clock read may ever influence it —
    that guarantee is exactly what makes "same claim set -> same
    assignment" true, which is what gives strong eventual consistency with
    no coordinator (the resolver built in a later work package relies on
    this).

    `claim` is duck-typed: anything with `.t_start` (an HLC), `.node_id`,
    and `.seq` works — no `starling_crdt.Claim` type exists yet.
    """
    return (claim.t_start.physical_ms, claim.t_start.logical, claim.node_id, claim.seq)
