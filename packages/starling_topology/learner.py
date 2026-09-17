"""starling_topology/learner.py
----------------------------------
C6 self-healing topology discovery (WP-07). Cheap, and it supplies the
`TopologyPrior` the resolver already accepts (`starling_crdt.resolver
.TopologyPrior`) — this module's only contract with the rest of the system
is that duck-typed `.prior(from_node, to_node, dt_s) -> float` method.

Per-node-pair transit-time distributions are fitted ONLINE (Welford, on
`log(transit_s)`) from high-confidence cross-node handoffs only:
`observe_handoff` silently drops anything below
`cfg.handoff_confidence_min` — "learning topology from low-confidence
handoffs teaches the system its own mistakes" (STARLING_BUILD_STATE.md
WP-07).

Edge existence rule (documented precisely here, since the acceptance
criteria ask for it): an edge exists only once `count >= cfg.k_min` AND
the RAW (not log-transformed) transit-time spread is tighter than a
UNIFORM NULL over the same observed `[min, max]` range. A spurious node
pair's handoffs (two cameras that never actually connect, glued together
only by a rare coincidental appearance match) look like noise scattered
roughly uniformly across whatever range got observed; a real corridor's
handoffs cluster tightly around its true transit time. For a continuous
uniform distribution on `[lo, hi]`, the standard deviation is
`(hi - lo) / sqrt(12)` — this module's null. The comparison is
deliberately done in RAW seconds, not in `log(transit_s)`: `log` of a
raw-uniform variable is itself concave and noticeably tighter than a
log-space uniform null at any realistic sample size (verified
numerically — a raw-uniform(1, 100) sample's fitted `log`-sigma sits
around 0.6-0.9x a log-space uniform null even at n=100000, which would
wrongly admit it as an edge), whereas comparing raw standard deviations
cleanly separates the two cases at every sample size tested: a genuinely
uniform raw sample's ratio sits at or above ~1.0, and a log-normal
corridor's sits at ~0.5-0.8. `sigma_raw_fitted < null_sigma_ratio *
sigma_raw_null` is the test; the log-normal `(mu, sigma)` fit above is
still what `prior()`/`pdf()` use once a pair has qualified.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from starling_net.logging import get_logger
from starling_node.config import TopologyConfig

if TYPE_CHECKING:
    from starling_consensus.reputation import ReputationTable
    from starling_crdt.claims import ClaimSet
    from starling_crdt.resolver import Assignment

logger = get_logger(__name__)

_TWO_PI = 2.0 * math.pi
_SQRT_12 = math.sqrt(12.0)


def _edge_key(a: int, b: int) -> tuple[int, int]:
    """Edges are undirected — a corridor's transit time doesn't depend on
    which direction is labelled `from`/`to` in a single `TopologyObservation`.
    """
    return (a, b) if a <= b else (b, a)


@dataclass
class TransitDistribution:
    """Online (Welford) log-normal fit over a node-pair's observed transit
    times, plus a bounded raw-observation history for `detect_shift`.
    """

    count: int = 0
    _mean_log: float = 0.0
    _m2_log: float = 0.0
    _mean_raw: float = 0.0
    _m2_raw: float = 0.0
    min_transit_s: float = float("inf")
    max_transit_s: float = float("-inf")
    # Real maxlen is chosen by TopologyLearner (it depends on
    # cfg.shift_window, not known to this dataclass's own default).
    history: "deque[float]" = field(default_factory=lambda: deque(maxlen=1))

    def update(self, transit_s: float) -> None:
        self.count += 1

        x = math.log(transit_s)
        delta = x - self._mean_log
        self._mean_log += delta / self.count
        self._m2_log += delta * (x - self._mean_log)

        delta_raw = transit_s - self._mean_raw
        self._mean_raw += delta_raw / self.count
        self._m2_raw += delta_raw * (transit_s - self._mean_raw)

        self.min_transit_s = min(self.min_transit_s, transit_s)
        self.max_transit_s = max(self.max_transit_s, transit_s)
        self.history.append(transit_s)

    @property
    def mu(self) -> float:
        """Mean of `log(transit_s)` — the log-normal location parameter."""
        return self._mean_log

    @property
    def sigma(self) -> float:
        """Sample standard deviation of `log(transit_s)`; `inf` with fewer
        than 2 observations (undefined, and must never look "tight").
        """
        if self.count < 2:
            return float("inf")
        return math.sqrt(self._m2_log / (self.count - 1))

    @property
    def raw_sigma(self) -> float:
        """Sample standard deviation of the RAW `transit_s` values (not
        log-transformed) — what the edge existence rule actually compares
        against the uniform null. See module docstring for why raw space,
        not log space.
        """
        if self.count < 2:
            return float("inf")
        return math.sqrt(self._m2_raw / (self.count - 1))

    def uniform_null_sigma_raw(self) -> float:
        """The std-dev a UNIFORM distribution over the same observed
        `[min, max]` RAW transit range would produce: `(max - min) /
        sqrt(12)`. This — not the log-space equivalent — is the null the
        edge existence rule tests `raw_sigma` against; see module docstring.
        """
        if self.count < 2 or self.max_transit_s <= self.min_transit_s:
            return 0.0
        return (self.max_transit_s - self.min_transit_s) / _SQRT_12

    def pdf(self, transit_s: float) -> float:
        """Log-normal density at `transit_s`. Used only for
        `docs/results_c6.md`'s learned-vs-true plot, not by `prior()`
        (which uses a simpler, bounded-to-[0,1] Gaussian bump in log-space).
        """
        if transit_s <= 0 or self.count < 2:
            return 0.0
        sigma = max(self.sigma, 1e-9)
        x = math.log(transit_s)
        exponent = -((x - self.mu) ** 2) / (2.0 * sigma * sigma)
        return math.exp(exponent) / (transit_s * sigma * math.sqrt(_TWO_PI))


class TopologyLearner:
    """One instance per node — like `ReputationTable`, this holds only
    what THIS node has itself derived from claim chains it has seen; it is
    never a shared/global object (CLAUDE.md rule 2).
    """

    def __init__(self, cfg: Optional[TopologyConfig] = None) -> None:
        self.cfg = cfg or TopologyConfig()
        self._edges: dict[tuple[int, int], TransitDistribution] = {}

    def observe_handoff(self, node_a: int, node_b: int, transit_s: float, confidence: float) -> None:
        """Record one cross-node handoff observation. Dropped (not just
        down-weighted) if `confidence < cfg.handoff_confidence_min`,
        `transit_s <= 0`, or `node_a == node_b` (not a handoff at all).
        """
        if node_a == node_b:
            return
        if transit_s <= 0:
            return
        if confidence < self.cfg.handoff_confidence_min:
            return
        key = _edge_key(node_a, node_b)
        dist = self._edges.get(key)
        if dist is None:
            # 4x the comparison window, not 2x: detect_shift compares the
            # OLDER vs NEWER half of the most recent `2 * shift_window`
            # observations. A history buffer sized at exactly that would
            # be entirely overwritten by a same-sized burst of new-regime
            # observations before a caller ever gets to compare it against
            # the old regime — the buffer needs headroom so the old regime
            # is still present alongside the new one.
            dist = TransitDistribution(history=deque(maxlen=self.cfg.shift_window * 4))
            self._edges[key] = dist
        dist.update(transit_s)

    def update_from_assignment(self, assignment: "Assignment", claims: "ClaimSet") -> None:
        """Extracts consecutive cross-node claim pairs for the same
        identity from one `resolve()` output and feeds each as a handoff.
        `assignment.trajectories[identity_ref]` is already chronological
        across all branches (see `starling_crdt.resolver.Assignment`); a
        handoff's confidence is the weaker of the two claims' own
        `confidence` fields, and its "reachability margin" quality is left
        to that field rather than re-derived here.
        """
        records = {c["claim_id"]: c for c in claims.ordered()}
        for claim_ids in assignment.trajectories.values():
            ordered = [records[cid] for cid in claim_ids if cid in records]
            for prev, curr in zip(ordered, ordered[1:]):
                if prev["node_id"] == curr["node_id"]:
                    continue
                transit_s = curr["t_media"] - prev["t_media"]
                confidence = min(float(prev.get("confidence", 1.0)), float(curr.get("confidence", 1.0)))
                self.observe_handoff(prev["node_id"], curr["node_id"], transit_s, confidence)

    def _passes_existence_rule(self, dist: TransitDistribution) -> bool:
        if dist.count < self.cfg.k_min:
            return False
        null_sigma = dist.uniform_null_sigma_raw()
        if null_sigma <= 0.0:
            # Degenerate range (every observation identical) — a real,
            # extremely tight corridor, not a rejection case.
            return True
        return dist.raw_sigma < self.cfg.null_sigma_ratio * null_sigma

    def edges(self) -> dict[tuple[int, int], TransitDistribution]:
        """Only node-pairs that pass the edge existence rule (see module
        docstring) — this is the learned adjacency, not every pair ever
        observed.
        """
        return {key: dist for key, dist in self._edges.items() if self._passes_existence_rule(dist)}

    def prior(self, a: int, b: int, dt_s: float) -> float:
        """`[0, 1]`, consumed by the resolver as `TopologyPrior.prior`.
        Peaks at 1.0 when `dt_s` matches the learned median transit time
        (`exp(mu)`) and falls off at both tails as a Gaussian bump in
        log-space. An unlearned or not-yet-qualifying pair returns 1.0
        (neutral — "no information", never a penalty) rather than 0.0, so
        a real corridor the learner simply hasn't seen enough of yet does
        not get penalised by its own absence of data.
        """
        dist = self._edges.get(_edge_key(a, b))
        if dist is None or not self._passes_existence_rule(dist):
            return 1.0
        dt_s = max(dt_s, 1e-6)
        z = (math.log(dt_s) - dist.mu) / max(dist.sigma, 1e-6)
        return math.exp(-0.5 * z * z)

    def detect_shift(self, a: int, b: int) -> bool:
        """Windowed mean-shift (CUSUM-style) test: compares the mean
        `log(transit_s)` of the OLDER half against the NEWER half of the
        most recent `2 * cfg.shift_window` observations. Needs at least
        that many observations in history to have two comparably-sized
        halves; returns `False` (no signal) below that, never a false
        positive from too little data.
        """
        dist = self._edges.get(_edge_key(a, b))
        if dist is None or len(dist.history) < 2 * self.cfg.shift_window:
            return False

        values = list(dist.history)[-2 * self.cfg.shift_window :]
        half = len(values) // 2
        older, newer = values[:half], values[half:]

        older_log = [math.log(v) for v in older]
        newer_log = [math.log(v) for v in newer]
        older_mean = sum(older_log) / len(older_log)
        newer_mean = sum(newer_log) / len(newer_log)

        older_var = sum((x - older_mean) ** 2 for x in older_log) / max(1, len(older_log) - 1)
        older_std = math.sqrt(older_var) if older_var > 0 else 1e-6

        z = abs(newer_mean - older_mean) / older_std
        return z > self.cfg.shift_threshold_sigma

    def apply_shift_penalties(self, reputation: "ReputationTable") -> list[tuple[int, int]]:
        """Wires `detect_shift` into `ReputationTable` as a WEAK signal
        ONLY (CLAUDE.md rule for this session: an environment change and a
        misbehaving node look identical from transit times alone, so a
        shift must never on its own tank a reputation). Call this
        periodically (e.g. from a node's housekeeping tick, alongside
        `PartitionTracker.tick()`); returns the `(node_a, node_b)` pairs
        that fired this call, purely for logging. Both endpoints of a
        shifted edge take the SAME small hit — a transit-time shift alone
        cannot say which node (if either) is at fault, only that something
        about that corridor changed. `ReputationTable.
        penalise_topology_shift` re-clamps the weight again independently,
        so this is deliberately not the only place that ceiling is enforced.
        """
        shifted = []
        for a, b in sorted(self._edges.keys()):
            if self.detect_shift(a, b):
                reputation.penalise_topology_shift(a, self.cfg.topology_shift_weight)
                reputation.penalise_topology_shift(b, self.cfg.topology_shift_weight)
                shifted.append((a, b))
                logger.info("topology_shift_detected", node_a=a, node_b=b)
        return shifted

    def to_graph(self) -> dict:
        """Learned topology as plain data — for `scripts/evaluate_topology
        .py` (graph edit distance, rendering) and any future dashboard
        panel. Never a live object graph — matches every other module's
        "gossip the evidence, derive everything else" convention.
        """
        edges = self.edges()
        nodes = sorted({n for pair in edges for n in pair})
        adjacency: dict[int, list[int]] = {n: [] for n in nodes}
        for a, b in edges:
            adjacency[a].append(b)
            adjacency[b].append(a)
        for n in adjacency:
            adjacency[n].sort()
        return {
            "nodes": nodes,
            "adjacency": adjacency,
            "edges": [
                {
                    "a": a,
                    "b": b,
                    "count": dist.count,
                    "mu_log": dist.mu,
                    "sigma_log": dist.sigma,
                    "mean_transit_s": math.exp(dist.mu),
                }
                for (a, b), dist in sorted(edges.items())
            ],
        }
