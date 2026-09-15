"""starling_crdt/resolver.py
------------------------------
The deterministic identity resolver (WP-06 Part 2): a PURE function from a
merged `ClaimSet` (plus optional geometry / reputation / topology priors)
to an `Assignment`. This is the "derive the decision" half of C1's
mechanism (STARLING_BUILD_STATE.md §4.2) — no identity assignment is ever
replicated or stored; every replica recomputes it independently from the
same claim set and gets the same answer, by construction.

Scope note (this session's rule 2): Part 2 implements NO fork logic. When
a face-anchored claim conflicts with an identity's existing trajectory,
this module currently just binds it anyway (a hard constraint always
wins) — `starling_crdt.forks` (Part 3) is what turns that specific
conflict into an `IdentityFork` instead of a silent overwrite, and Part 3
extends `resolve()`'s return type to `tuple[Assignment, ForkSet]`. Until
then `resolve()` returns `Assignment` alone.

Determinism requirements (STARLING_BUILD_STATE.md WP-06 Part 2 — not
stylistic preferences, the correctness condition for the whole
contribution):
  - no random number generation
  - no reliance on dict or set iteration order anywhere: every collection
    this module iterates over some existing state (`state.keys()`, a
    gallery, a scored candidate list) is sorted explicitly first, or was
    built by appending to a list in the deterministic claim sweep order
    (never a set)
  - no wall-clock reads: every time value comes from a claim's own
    `t_media` (media time), never `time.time()`
  - float operations in a fixed order: `_score()` always multiplies its
    four factors in the same literal order, and every "best candidate"
    comparison sorts a list rather than folding over dict/set iteration
    order
`assert_deterministic()` below is the check for all of this: it runs
`resolve()` on the same claim pool inserted into a `ClaimSet` in several
independently-shuffled orders and asserts every run's canonical output is
byte-identical — this is meaningful specifically because
`ClaimSet.ordered()` (Part 1) already guarantees the same total order
regardless of insertion order, so any divergence here is a bug in this
module, not in Part 1.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol

import numpy as np

from starling_crdt.claims import ClaimSet
from starling_geometry.reachability import ReachabilityModel
from starling_net.logging import get_logger
from starling_node.config import MatchConfig
from starling_store.identity_store import LocalStore

logger = get_logger(__name__)

_NEG_INF = float("-inf")
# New identity hypotheses are seeded deterministically from the claim_id
# of the claim that spawned them — never a fresh ULID/UUID at resolve()
# time, since resolve() must be a pure function of the input claim set
# alone (two replicas resolving the same claims must invent the same
# provisional identity_ref). Prefixed to keep this namespace visibly
# distinct from operator/face-anchor-assigned identity_refs (e.g. "P-003").
_AUTO_IDENTITY_PREFIX = "AUTO-"


class TopologyPrior(Protocol):
    """Duck-typed interface for WP-07's (not built this session) learned
    inter-node transit-time prior. `resolve()` only ever calls
    `.prior(...)`; passing `topology=None` disables it (prior = 1.0).
    """

    def prior(self, from_node: int, to_node: int, dt_s: float) -> float: ...


@dataclass(frozen=True)
class Assignment:
    identity_of: dict[str, Optional[str]]  # claim_id -> identity_ref
    trajectories: dict[str, list[str]]  # identity_ref -> [claim_id], in claim order
    confidence: dict[str, float]  # identity_ref -> confidence of its most recent binding


@dataclass
class _Hypothesis:
    """One identity's working state during the forward sweep. Internal —
    never exposed outside `resolve()`.
    """

    identity_ref: str
    last_position: Optional[tuple[float, float]]
    last_t_media: float
    last_node_id: int
    gallery: list[np.ndarray] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)


def _decode_embedding(claim: dict[str, Any]) -> Optional[np.ndarray]:
    blob = claim.get("embedding")
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32) * float(claim.get("embed_scale", 1.0) or 1.0)


def _world_pos(claim: dict[str, Any]) -> Optional[tuple[float, float]]:
    x, y = claim.get("world_x"), claim.get("world_y")
    if x is None or y is None:
        return None
    return (float(x), float(y))


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _gallery_score(emb: Optional[np.ndarray], gallery: list[np.ndarray]) -> float:
    """D-08 fix: the identity prototype is a small GALLERY of recent
    high-quality embeddings (never a single stored mean, which cannot
    express anchor -> propagate -> decay -> re-anchor and cannot be
    merged). Scored as the best match against any gallery member — the
    gallery is a list built in deterministic append order, so iterating
    it is not a dict/set-iteration-order hazard.
    """
    if emb is None or not gallery:
        return 0.0
    return max(_cosine(emb, g) for g in gallery)


def _gate_pass(
    hyp: _Hypothesis,
    claim: dict[str, Any],
    claim_pos: Optional[tuple[float, float]],
    geometry: ReachabilityModel,
) -> bool:
    """C3's hard reachability gate (STARLING_BUILD_STATE.md §4/Appendix
    A.2): reject a candidate outright if it is not reachable, regardless
    of appearance similarity. A candidate or claim with no known world
    position cannot be verified and is rejected rather than assumed safe.
    """
    if hyp.last_position is None or claim_pos is None:
        return False
    dt_s = max(0.0, claim["t_media"] - hyp.last_t_media)
    pos_sigma = claim.get("pos_sigma") or 0.0
    return geometry.is_reachable(hyp.last_position, claim_pos, dt_s, pos_sigma)


def _score(
    hyp: _Hypothesis,
    claim: dict[str, Any],
    emb: Optional[np.ndarray],
    reputation: Optional[Mapping[int, float]],
    topology: Optional[TopologyPrior],
) -> float:
    proto_score = _gallery_score(emb, hyp.gallery)
    dt_s = max(0.0, claim["t_media"] - hyp.last_t_media)
    topo = 1.0 if topology is None else topology.prior(hyp.last_node_id, claim["node_id"], dt_s)
    rep = 1.0 if reputation is None else reputation.get(claim["node_id"], 1.0)
    quality = claim["quality"]
    # Fixed multiplication order every call — required for determinism
    # (see module docstring); do not reorder or fold over a set.
    return proto_score * topo * rep * quality


def _extend(hyp: _Hypothesis, claim: dict[str, Any], emb: Optional[np.ndarray],
            claim_pos: Optional[tuple[float, float]], cfg: MatchConfig) -> None:
    hyp.claim_ids.append(claim["claim_id"])
    if claim_pos is not None:
        hyp.last_position = claim_pos
    hyp.last_t_media = claim["t_media"]
    hyp.last_node_id = claim["node_id"]
    if emb is not None:
        hyp.gallery.append(emb)
        if len(hyp.gallery) > cfg.gallery_size:
            hyp.gallery.pop(0)


def resolve(
    claims: ClaimSet,
    geometry: Optional[ReachabilityModel],
    reputation: Optional[Mapping[int, float]],
    topology: Optional[TopologyPrior],
    cfg: MatchConfig,
) -> Assignment:
    """Sweep the merged claim set, in its one canonical order, deriving a
    pure-function `Assignment`. See STARLING_BUILD_STATE.md WP-06 Part 2
    for the algorithm this implements exactly.
    """
    claims_sorted = claims.ordered()
    state: dict[str, _Hypothesis] = {}
    identity_of: dict[str, Optional[str]] = {}
    confidence: dict[str, float] = {}
    geometry_disabled_logged = False

    for claim in claims_sorted:
        claim_id = claim["claim_id"]
        emb = _decode_embedding(claim)
        claim_pos = _world_pos(claim)

        if claim.get("anchor_type") == "FACE_ANCHOR" and claim.get("identity_ref"):
            # Hard constraint (algorithm step 6): binds unconditionally,
            # overriding appearance scoring. A conflict with this
            # identity's existing trajectory is exactly what Part 3's
            # IdentityFork detects instead of this silent overwrite.
            ref = claim["identity_ref"]
            hyp = state.get(ref)
            if hyp is None:
                hyp = _Hypothesis(ref, claim_pos, claim["t_media"], claim["node_id"])
                state[ref] = hyp
            _extend(hyp, claim, emb, claim_pos, cfg)
            identity_of[claim_id] = ref
            confidence[ref] = 1.0
            continue

        if geometry is None:
            candidates = sorted(state.keys())
            if not geometry_disabled_logged:
                logger.warning(
                    "c3_reachability_gate_disabled",
                    reason="geometry is None; reachability gating skipped for this resolve() call",
                )
                geometry_disabled_logged = True
        else:
            candidates = sorted(
                ref for ref, hyp in state.items() if _gate_pass(hyp, claim, claim_pos, geometry)
            )

        if not candidates:
            # No known identity even passed the gate: an honest first
            # sighting, not an ambiguity, so a new hypothesis is spawned.
            ref = f"{_AUTO_IDENTITY_PREFIX}{claim_id}"
            hyp = _Hypothesis(ref, claim_pos, claim["t_media"], claim["node_id"])
            state[ref] = hyp
            _extend(hyp, claim, emb, claim_pos, cfg)
            identity_of[claim_id] = ref
            confidence[ref] = claim["confidence"]
            continue

        # Deterministic tie-break (score desc, identity_ref asc) so exact
        # score ties never depend on incidental list order.
        scored = sorted(
            ((ref, _score(state[ref], claim, emb, reputation, topology)) for ref in candidates),
            key=lambda item: (-item[1], item[0]),
        )
        best_ref, best_score = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else _NEG_INF

        if best_score >= cfg.sim_threshold and (best_score - second_score) >= cfg.margin_threshold:
            hyp = state[best_ref]
            _extend(hyp, claim, emb, claim_pos, cfg)
            identity_of[claim_id] = best_ref
            confidence[best_ref] = best_score
        else:
            # Ambiguous (or below threshold) among KNOWN candidates: left
            # unassigned. Deliberately does NOT spawn a new identity here
            # — that would silently fork an already-known candidate
            # instead of surfacing the ambiguity honestly. "Ambiguity
            # must not be resolved by a thin margin."
            identity_of[claim_id] = None

    trajectories = {ref: list(hyp.claim_ids) for ref, hyp in state.items()}
    return Assignment(identity_of=identity_of, trajectories=trajectories, confidence=confidence)


def _canonical_assignment(assignment: Assignment) -> tuple:
    return (
        tuple(sorted(assignment.identity_of.items())),
        tuple(sorted((ref, tuple(ids)) for ref, ids in assignment.trajectories.items())),
        tuple(sorted(assignment.confidence.items())),
    )


def assert_deterministic(
    claims: list[dict[str, Any]],
    geometry: Optional[ReachabilityModel] = None,
    reputation: Optional[Mapping[int, float]] = None,
    topology: Optional[TopologyPrior] = None,
    cfg: Optional[MatchConfig] = None,
    trials: int = 5,
    seed: int = 0,
) -> None:
    """Runs `resolve()` `trials` times, each on a fresh `ClaimSet` built
    by inserting `claims` in an independently-shuffled order, and asserts
    every run's canonical output is identical. `seed` makes the shuffle
    itself reproducible — this function is a determinism CHECK, not a
    source of nondeterminism inside `resolve()` itself, which never uses
    `random` at all.
    """
    cfg = cfg or MatchConfig()
    rng = random.Random(seed)
    canonical: Optional[tuple] = None

    for trial in range(trials):
        order = list(claims)
        rng.shuffle(order)
        store = LocalStore(db_path=":memory:", node_id=-1)
        claim_set = ClaimSet(store)
        for c in order:
            claim_set.add(c)

        assignment = resolve(claim_set, geometry, reputation, topology, cfg)
        this_run = _canonical_assignment(assignment)
        if canonical is None:
            canonical = this_run
        else:
            assert this_run == canonical, f"resolve() was nondeterministic on trial {trial}"
