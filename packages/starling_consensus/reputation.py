"""starling_consensus/reputation.py
------------------------------------
Local, per-observer reputation (WP-10 Part 2, C2 — Appendix A.5 /
docs/threat_model.md §4). CLAUDE.md rule 3 / STARLING_BUILD_STATE.md WP-10
task 3: reputation is never a single global scalar — that would be a
coordinator by the back door. Each `ReputationTable` instance belongs to
ONE node and holds only that node's own opinions (`R_ij`, this node's
opinion of node `j`) plus whatever other nodes' opinions it has received
over gossip (`R_kj` for `k != this node`, via `ingest_gossiped`).
`aggregate()` is the only place those opinions are ever combined, and it
combines them with a MEDIAN — itself Byzantine-robust — computed locally,
at use time, never stored back as a single value.
"""

from __future__ import annotations

import statistics
from collections import deque
from typing import Optional

from starling_consensus.plausibility import PlausibilityResult
from starling_net.keys import NodeKeys
from starling_node.config import ReputationConfig
from starling_proto.convert import claim_id_to_bytes
from starling_proto.generated import starling_pb2

_MAX_EVIDENCE_CLAIM_IDS = 3  # matches ReputationUpdate's "<= 3, for auditability" wire comment


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class ReputationTable:
    """Each node holds its OWN opinion of every other node.

    There is NO global reputation scalar — that would reintroduce a
    coordinator. Opinions are gossiped as `ReputationUpdate` messages
    (§5.3 of the wire schema); the aggregate is a MEDIAN taken locally at
    use time, because the median is itself Byzantine-robust.
    """

    def __init__(self, node_id: int, cfg: ReputationConfig, keys: Optional[NodeKeys] = None) -> None:
        self.node_id = node_id
        self.cfg = cfg
        self.keys = keys
        # This node's own R_ij, keyed by about_node.
        self._local: dict[int, float] = {}
        # Opinions gossiped from other observers: about_node -> {from_node: score}.
        self._gossiped: dict[int, dict[int, float]] = {}
        # Up to _MAX_EVIDENCE_CLAIM_IDS most recent claim_ids behind each
        # about_node's current local opinion, for to_updates()'s auditability field.
        self._evidence: dict[int, "deque[bytes]"] = {}

    def observe(self, about_node: int, plausibility_result: PlausibilityResult) -> None:
        """Update this node's own opinion of `about_node` from one claim's
        plausibility result: `s_ij = 1 if passed else 0` (Appendix A.5),
        then the EWMA update with the recovery floor.
        """
        s = 1.0 if plausibility_result.passed else 0.0
        self._ewma_update(about_node, s)

        claim_id = plausibility_result.details.get("claim_id")
        if claim_id:
            evidence_bytes = self._to_evidence_bytes(claim_id)
            if evidence_bytes is not None:
                evidence = self._evidence.setdefault(about_node, deque(maxlen=_MAX_EVIDENCE_CLAIM_IDS))
                evidence.append(evidence_bytes)

    @staticmethod
    def _to_evidence_bytes(claim_id: object) -> Optional[bytes]:
        """A production claim_id is always a real ULID (`starling_store
        .LocalStore`, `starling_consensus.attacks.AttackInjector`), so the
        common case converts cleanly. A caller exercising this table with
        some other identifier scheme — `scripts/run_byzantine_sweep.py`'s
        own synthetic simulation, for instance — should not crash the
        reputation update over an auditability nicety; evidence tracking
        is simply skipped for a claim_id that isn't ULID-shaped.
        """
        if isinstance(claim_id, bytes):
            return claim_id
        if isinstance(claim_id, str):
            try:
                return claim_id_to_bytes(claim_id)
            except ValueError:
                return None
        return None

    def penalise_omission(self, about_node: int, weight: float) -> None:
        """The hook `starling_attest.negative_evidence.detect_omission`
        (WP-09/Prompt 7) feeds into: a node that lied by omission (attested
        healthy coverage while corroborators show it missed a crossing)
        takes a reputation hit, scaled by `weight` in `[0, 1]` — the
        caller's own confidence in the omission (e.g. how many
        corroborators agreed). `weight=1.0` applies the same EWMA update as
        a fully-failed plausibility check (`s=0.0`); `weight=0.0` is a
        deliberate no-op. This is the composition point
        docs/threat_model.md calls "the sentence that makes C4 and C2 one
        contribution rather than two."
        """
        weight = _clip(weight, 0.0, 1.0)
        self._ewma_update(about_node, s=1.0 - weight)

    def penalise_topology_shift(self, about_node: int, weight: float) -> None:
        """WP-07 (C6) weak-signal hook: `starling_topology.learner
        .TopologyLearner.detect_shift` flags that a node-pair's transit-time
        distribution has moved. This must NEVER be composed as a hard
        signal: a shifted distribution is exactly as consistent with an
        innocent explanation (an aisle got re-racked, a doorway now takes
        longer to walk through) as with a misbehaving node skewing transit
        times with fabricated or replayed positions, and transit times
        alone cannot tell those two apart. Treating it like a failed
        plausibility check would let a pure environment change tank a
        node's reputation on its own — the exact "simplification" a later
        reader must be stopped from making by accident. `weight` is
        therefore clamped at `cfg.topology_shift_max_weight` (a small
        fraction of the full `[0, 1]` range `observe()`/`penalise_omission`
        can use), so a shift can only ever nudge reputation, never by
        itself drive it toward `cfg.r_min`.
        """
        weight = _clip(weight, 0.0, self.cfg.topology_shift_max_weight)
        self._ewma_update(about_node, s=1.0 - weight)

    def _ewma_update(self, about_node: int, s: float) -> None:
        prev = self.local_opinion(about_node)
        new = _clip((1.0 - self.cfg.alpha) * prev + self.cfg.alpha * s, self.cfg.r_min, 1.0)
        self._local[about_node] = new

    def local_opinion(self, node_id: int) -> float:
        """This node's own `R_ij` about `node_id` — `cfg.r_initial` (full
        trust, not suspicion) if never observed.
        """
        return self._local.get(node_id, self.cfg.r_initial)

    def aggregate(self, node_id: int) -> float:
        """`R_j = median over i of gossiped R_ij` (Appendix A.5), including
        this node's own opinion in the pool. A `node_id` with no opinions
        anywhere (never observed by this node, and nothing gossiped about
        it) returns `cfg.r_initial` — the same "unknown is not evidence of
        misbehaviour" posture `starling_attest.admission.admissible` takes
        for a `reputation` mapping's missing keys.
        """
        values = [self.local_opinion(node_id)]
        values.extend(self._gossiped.get(node_id, {}).values())
        return statistics.median(values)

    def ingest_gossiped(self, update: "starling_pb2.ReputationUpdate") -> None:
        """Record another node's opinion about `update.about_node`. A
        gossiped copy of THIS node's own opinion (re-heard via a peer) is
        dropped rather than merged into `_gossiped` — `local_opinion()`
        already is this node's opinion; storing it a second time under
        `_gossiped` would let it be counted twice in `aggregate()`'s median.
        """
        if update.from_node == self.node_id:
            return
        self._gossiped.setdefault(update.about_node, {})[update.from_node] = update.score

    def to_updates(self) -> list["starling_pb2.ReputationUpdate"]:
        """This node's own opinions, as gossip-able `ReputationUpdate`
        messages — one per node this node has ever observed. Iterates
        `sorted(self._local)` (never raw dict order) so output order is
        deterministic across calls, matching this project's determinism
        conventions elsewhere (starling_crdt.resolver).
        """
        updates = []
        for about_node in sorted(self._local):
            update = starling_pb2.ReputationUpdate(
                from_node=self.node_id,
                about_node=about_node,
                score=self._local[about_node],
            )
            for claim_id_bytes in self._evidence.get(about_node, ()):
                update.evidence_claim_ids.append(claim_id_bytes)
            if self.keys is not None:
                update.signature = b""
                update.signature = self.keys.sign(update.SerializeToString())
            updates.append(update)
        return updates
