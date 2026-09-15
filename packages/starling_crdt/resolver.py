"""starling_crdt/resolver.py
------------------------------
The deterministic identity resolver (WP-06 Parts 2 & 3): a PURE function
from a merged `ClaimSet` (plus optional geometry / reputation / topology
priors) to an `Assignment` and a `ForkSet`. This is the "derive the
decision" half of C1's mechanism (STARLING_BUILD_STATE.md §4.2) — no
identity assignment (and no fork) is ever replicated or stored; every
replica recomputes both independently from the same claim set and gets
the same answer, by construction.

Fork model (Part 3; CLAUDE.md rule 6): only FACE_ANCHOR claims carry an
explicit `identity_ref`, so they are the only place a genuine conflict
("two claim chains bind one identity_ref to spatially incompatible
trajectories") can be detected without inventing one. Each identity keeps
one "live" branch that ordinary (appearance-matched) claims extend, plus
a `last_confirmed_position`/`_t_media` — the position/time of its most
recent anchor. A new face anchor is checked in two stages:
  1. TRIGGER: is it reachable from the live branch's current TIP within
     the elapsed time? If yes, it is an ordinary continuation — extend
     the live branch, no fork.
  2. If not, is it reachable from the identity's LAST CONFIRMED position
     (a strictly earlier point, hence a strictly larger time budget and
     admissible radius)? Because a chain of individually-valid
     propagation hops always stays within `v_max * elapsed` of its
     starting point (the triangle inequality on the geodesic distances
     `ReachabilityModel` computes), the live branch's tip is ALWAYS
     reachable from the last confirmed position. So this second,
     looser check is where genuine ambiguity can surface: if the new
     anchor is ALSO reachable from the same confirmed point, both
     branches are simultaneously plausible relative to the last thing
     we were actually sure of, and `starling_crdt.forks.
     evaluate_reachability` leaves the fork OPEN. If the new anchor
     fails even that looser check, it is the one ruled out.
Ordinary (non-anchor) claims only ever extend an identity's live branch
(the most recently-extended one) — a dormant branch is only reactivated
by a face anchor that reaches it, per the fork resolution priority.

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
independently-shuffled orders and asserts every run's canonical output
(Assignment AND ForkSet) is byte-identical — this is meaningful
specifically because `ClaimSet.ordered()` (Part 1) already guarantees the
same total order regardless of insertion order, so any divergence here is
a bug in this module, not in Part 1.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol

import numpy as np

from starling_crdt.claims import ClaimSet
from starling_crdt.forks import Branch, ForkSet, ForkStatus, IdentityFork, evaluate_reachability, make_fork
from starling_geometry.reachability import ReachabilityModel
from starling_net.hlc import HLC
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
    trajectories: dict[str, list[str]]  # identity_ref -> [claim_id], chronological, ALL branches
    confidence: dict[str, float]  # identity_ref -> confidence of its most recent binding


@dataclass
class _Branch:
    """One identity's working trajectory during the forward sweep.
    Internal — never exposed outside `resolve()` (the public,
    immutable counterpart is `starling_crdt.forks.Branch`).
    """

    idx: int
    last_position: Optional[tuple[float, float]]
    last_t_media: float
    last_node_id: int
    first_hlc: HLC
    last_hlc: HLC
    gallery: list[np.ndarray] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)


@dataclass
class _Hypothesis:
    """One identity's working state: one or more branches (more than one
    only once a fork has opened), plus the position/time of its most
    recent face anchor (`None` until the first one, or if that anchor
    lacked a verified position).
    """

    identity_ref: str
    branches: list[_Branch]
    last_confirmed_position: Optional[tuple[float, float]]
    last_confirmed_t_media: Optional[float]


def _hlc_of(claim: dict[str, Any]) -> HLC:
    return HLC(
        physical_ms=claim["hlc_physical_ms"], logical=claim["hlc_logical"], node_id=claim["node_id"]
    )


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


def _live_branch(hyp: _Hypothesis) -> _Branch:
    """The most recently-extended branch — the only one ordinary
    (non-anchor) claims are matched against. A dormant branch (from an
    open fork) is only ever reactivated by a face anchor that reaches it.
    """
    return max(hyp.branches, key=lambda b: b.last_t_media)


def _gate_pass(
    branch: _Branch,
    claim: dict[str, Any],
    claim_pos: Optional[tuple[float, float]],
    geometry: ReachabilityModel,
) -> bool:
    """C3's hard reachability gate (STARLING_BUILD_STATE.md §4/Appendix
    A.2): reject a candidate outright if it is not reachable, regardless
    of appearance similarity. A candidate or claim with no known world
    position cannot be verified and is rejected rather than assumed safe.
    """
    if branch.last_position is None or claim_pos is None:
        return False
    dt_s = max(0.0, claim["t_media"] - branch.last_t_media)
    pos_sigma = claim.get("pos_sigma") or 0.0
    return geometry.is_reachable(branch.last_position, claim_pos, dt_s, pos_sigma)


def _score(
    branch: _Branch,
    claim: dict[str, Any],
    emb: Optional[np.ndarray],
    reputation: Optional[Mapping[int, float]],
    topology: Optional[TopologyPrior],
) -> float:
    proto_score = _gallery_score(emb, branch.gallery)
    dt_s = max(0.0, claim["t_media"] - branch.last_t_media)
    topo = 1.0 if topology is None else topology.prior(branch.last_node_id, claim["node_id"], dt_s)
    rep = 1.0 if reputation is None else reputation.get(claim["node_id"], 1.0)
    quality = claim["quality"]
    # Fixed multiplication order every call — required for determinism
    # (see module docstring); do not reorder or fold over a set.
    return proto_score * topo * rep * quality


def _extend_branch(
    branch: _Branch,
    claim: dict[str, Any],
    emb: Optional[np.ndarray],
    claim_pos: Optional[tuple[float, float]],
    cfg: MatchConfig,
) -> None:
    branch.claim_ids.append(claim["claim_id"])
    if claim_pos is not None:
        branch.last_position = claim_pos
    branch.last_t_media = claim["t_media"]
    branch.last_node_id = claim["node_id"]
    branch.last_hlc = _hlc_of(claim)
    if emb is not None:
        branch.gallery.append(emb)
        if len(branch.gallery) > cfg.gallery_size:
            branch.gallery.pop(0)


def _new_branch(idx: int, claim: dict[str, Any], claim_pos: Optional[tuple[float, float]]) -> _Branch:
    hlc = _hlc_of(claim)
    return _Branch(
        idx=idx,
        last_position=claim_pos,
        last_t_media=claim["t_media"],
        last_node_id=claim["node_id"],
        first_hlc=hlc,
        last_hlc=hlc,
    )


def _public_branches(hyp: _Hypothesis) -> tuple[Branch, ...]:
    return tuple(
        Branch(claim_ids=tuple(b.claim_ids), last_position=b.last_position, hlc_span=(b.first_hlc, b.last_hlc))
        for b in hyp.branches
    )


def resolve(
    claims: ClaimSet,
    geometry: Optional[ReachabilityModel],
    reputation: Optional[Mapping[int, float]],
    topology: Optional[TopologyPrior],
    cfg: MatchConfig,
) -> tuple[Assignment, ForkSet]:
    """Sweep the merged claim set, in its one canonical order, deriving a
    pure-function `Assignment` and `ForkSet`. See STARLING_BUILD_STATE.md
    WP-06 Parts 2 and 3 for the algorithm this implements.
    """
    claims_sorted = claims.ordered()
    order_index = {c["claim_id"]: i for i, c in enumerate(claims_sorted)}
    state: dict[str, _Hypothesis] = {}
    identity_of: dict[str, Optional[str]] = {}
    confidence: dict[str, float] = {}
    forks = ForkSet()
    open_fork_by_identity: dict[str, IdentityFork] = {}
    geometry_disabled_logged = False

    for claim in claims_sorted:
        claim_id = claim["claim_id"]
        emb = _decode_embedding(claim)
        claim_pos = _world_pos(claim)

        if claim.get("anchor_type") == "FACE_ANCHOR" and claim.get("identity_ref"):
            ref = claim["identity_ref"]
            hyp = state.get(ref)

            if hyp is None:
                branch = _new_branch(0, claim, claim_pos)
                _extend_branch(branch, claim, emb, claim_pos, cfg)
                state[ref] = _Hypothesis(ref, [branch], claim_pos, claim["t_media"])
                identity_of[claim_id] = ref
                confidence[ref] = 1.0
                continue

            if geometry is None or claim_pos is None:
                # Fork detection needs a verified position on both sides.
                # Without one, bind to the live branch unconditionally
                # rather than opening a fork over unverifiable data — same
                # "C3 disabled" precedent as the appearance-based gate
                # below, sharing its "log once" flag.
                if not geometry_disabled_logged:
                    logger.warning(
                        "c3_reachability_gate_disabled",
                        reason="geometry is None or claim has no world_pos; fork detection skipped",
                    )
                    geometry_disabled_logged = True
                branch = _live_branch(hyp)
                _extend_branch(branch, claim, emb, claim_pos, cfg)
                if claim_pos is not None:
                    hyp.last_confirmed_position = claim_pos
                    hyp.last_confirmed_t_media = claim["t_media"]
                identity_of[claim_id] = ref
                confidence[ref] = 1.0
                continue

            live = _live_branch(hyp)
            pos_sigma = claim.get("pos_sigma") or 0.0
            dt_from_tip = max(0.0, claim["t_media"] - live.last_t_media)
            continues_live = live.last_position is not None and geometry.is_reachable(
                live.last_position, claim_pos, dt_from_tip, pos_sigma
            )

            if continues_live:
                _extend_branch(live, claim, emb, claim_pos, cfg)
                hyp.last_confirmed_position = claim_pos
                hyp.last_confirmed_t_media = claim["t_media"]
                identity_of[claim_id] = ref
                confidence[ref] = 1.0

                open_fork = open_fork_by_identity.pop(ref, None)
                if open_fork is not None:
                    # ANCHOR resolution priority: a subsequent face anchor
                    # that reaches this branch closes the fork on it.
                    forks.add(
                        IdentityFork(
                            fork_id=open_fork.fork_id,
                            identity_ref=open_fork.identity_ref,
                            branches=open_fork.branches,
                            opened_at=open_fork.opened_at,
                            status=ForkStatus.RESOLVED_ANCHOR,
                            resolution_reason=f"closed by face anchor {claim_id}",
                            resolved_branch=live.idx,
                        )
                    )
                continue

            # Not explainable as a continuation of the live branch: two
            # claim chains now bind identity_ref to spatially incompatible
            # trajectories. Emit a fork instead of choosing (CLAUDE.md
            # rule 6 / STARLING_BUILD_STATE.md §4.2) — this is a
            # demonstrated feature, not a bug; see
            # starling_crdt.forks.evaluate_reachability for where "stays
            # open" is decided and why it must never be by score.
            new_idx = len(hyp.branches)
            new_branch = _new_branch(new_idx, claim, claim_pos)
            _extend_branch(new_branch, claim, emb, claim_pos, cfg)
            hyp.branches.append(new_branch)
            identity_of[claim_id] = ref
            confidence[ref] = 1.0

            fork = make_fork(ref, _public_branches(hyp), opened_at=_hlc_of(claim))
            reference_pos = hyp.last_confirmed_position
            if reference_pos is not None:
                reference_ms = int((hyp.last_confirmed_t_media or 0.0) * 1000)
                outcome = evaluate_reachability(fork, geometry, reference_pos, reference_ms)
                if outcome is not None:
                    winner, reason = outcome
                    fork = IdentityFork(
                        fork_id=fork.fork_id,
                        identity_ref=fork.identity_ref,
                        branches=fork.branches,
                        opened_at=fork.opened_at,
                        status=ForkStatus.RESOLVED_REACHABILITY,
                        resolution_reason=reason,
                        resolved_branch=winner,
                    )
            forks.add(fork)
            if fork.status == ForkStatus.OPEN:
                open_fork_by_identity[ref] = fork
            else:
                open_fork_by_identity.pop(ref, None)
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
                ref
                for ref, hyp in state.items()
                if _gate_pass(_live_branch(hyp), claim, claim_pos, geometry)
            )

        if not candidates:
            # No known identity even passed the gate: an honest first
            # sighting, not an ambiguity, so a new hypothesis is spawned.
            ref = f"{_AUTO_IDENTITY_PREFIX}{claim_id}"
            branch = _new_branch(0, claim, claim_pos)
            _extend_branch(branch, claim, emb, claim_pos, cfg)
            state[ref] = _Hypothesis(ref, [branch], last_confirmed_position=None, last_confirmed_t_media=None)
            identity_of[claim_id] = ref
            confidence[ref] = claim["confidence"]
            continue

        # Deterministic tie-break (score desc, identity_ref asc) so exact
        # score ties never depend on incidental list order.
        scored = sorted(
            (
                (ref, _score(_live_branch(state[ref]), claim, emb, reputation, topology))
                for ref in candidates
            ),
            key=lambda item: (-item[1], item[0]),
        )
        best_ref, best_score = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else _NEG_INF

        if best_score >= cfg.sim_threshold and (best_score - second_score) >= cfg.margin_threshold:
            branch = _live_branch(state[best_ref])
            _extend_branch(branch, claim, emb, claim_pos, cfg)
            identity_of[claim_id] = best_ref
            confidence[best_ref] = best_score
        else:
            # Ambiguous (or below threshold) among KNOWN candidates: left
            # unassigned. Deliberately does NOT spawn a new identity here
            # — that would silently fork an already-known candidate
            # instead of surfacing the ambiguity honestly. "Ambiguity
            # must not be resolved by a thin margin."
            identity_of[claim_id] = None

    trajectories: dict[str, list[str]] = {}
    for ref, hyp in state.items():
        all_ids = [cid for branch in hyp.branches for cid in branch.claim_ids]
        all_ids.sort(key=lambda cid: order_index[cid])
        trajectories[ref] = all_ids

    return Assignment(identity_of=identity_of, trajectories=trajectories, confidence=confidence), forks


def _canonical_assignment(assignment: Assignment) -> tuple:
    return (
        tuple(sorted(assignment.identity_of.items())),
        tuple(sorted((ref, tuple(ids)) for ref, ids in assignment.trajectories.items())),
        tuple(sorted(assignment.confidence.items())),
    )


def _canonical_forks(forks: ForkSet) -> tuple:
    return tuple(
        (
            f.fork_id,
            f.identity_ref,
            f.status.value,
            f.resolution_reason,
            f.resolved_branch,
            tuple((b.claim_ids, b.last_position) for b in f.branches),
        )
        for f in forks.all_forks()
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
    every run's canonical output (Assignment AND ForkSet) is identical.
    `seed` makes the shuffle itself reproducible — this function is a
    determinism CHECK, not a source of nondeterminism inside `resolve()`
    itself, which never uses `random` at all.
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

        assignment, forks = resolve(claim_set, geometry, reputation, topology, cfg)
        this_run = (_canonical_assignment(assignment), _canonical_forks(forks))
        if canonical is None:
            canonical = this_run
        else:
            assert this_run == canonical, f"resolve() was nondeterministic on trial {trial}"
