"""starling_crdt/forks.py
---------------------------
IdentityFork: the behaviour that distinguishes Starling from a tracking
system (STARLING_BUILD_STATE.md §4.2, CLAUDE.md rule 6). When two claim
chains bind one identity_ref to spatially incompatible trajectories and
BOTH remain reachable, the fork STAYS OPEN. Never resolved by picking the
higher score — the spec's prepared viva answer for exactly this question
is "the fork stays open and is surfaced as an ambiguity; the system does
not guess," and that is implemented here, not asserted.

Resolution priority (STARLING_BUILD_STATE.md WP-06 Part 3), in this exact
order:
  1. REACHABILITY — `evaluate_reachability()`: if exactly one branch is
     reachable from a reference position/time, close on it and record
     the specific geometric fact that ruled the other branch(es) out
     (the implied speed), never a bare "rejected".
  2. ANCHOR — a subsequent face anchor closes the fork on the branch it
     actually extends (wired in `starling_crdt.resolver`).
  3. OPERATOR — explicit human action via `ForkSet.resolve()`, called
     from outside this module (e.g. a future dashboard/operator UI;
     out of scope this session).
  4. Otherwise the fork STAYS OPEN — see the explicit comment at
     `evaluate_reachability`'s `return None`.

`ForkSet` is a pure OUTPUT of `starling_crdt.resolver.resolve()`: like
`Assignment`, it is freshly recomputed from the current claim set on
every call, never itself replicated or carried as mutable state across
calls (only the underlying claims are CRDT-replicated). `fork_id` is a
deterministic hash of the sorted branch claim_id tuples, so two replicas
holding the same claim set compute the identical fork_id for the same
conflict — this is what makes forks mergeable/comparable with no
coordinator, the same way `Assignment` is.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from starling_geometry.reachability import ReachabilityModel
from starling_net.hlc import HLC


class ForkStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_REACHABILITY = "RESOLVED_REACHABILITY"
    RESOLVED_ANCHOR = "RESOLVED_ANCHOR"
    RESOLVED_OPERATOR = "RESOLVED_OPERATOR"


@dataclass(frozen=True)
class Branch:
    claim_ids: tuple[str, ...]
    last_position: tuple[float, float]
    hlc_span: tuple[HLC, HLC]  # (earliest, latest) HLC among claim_ids


@dataclass(frozen=True)
class IdentityFork:
    fork_id: str
    identity_ref: str
    branches: tuple[Branch, ...]
    opened_at: HLC
    status: ForkStatus = ForkStatus.OPEN
    resolution_reason: Optional[str] = None
    resolved_branch: Optional[int] = None


def compute_fork_id(identity_ref: str, branches: tuple[Branch, ...]) -> str:
    """Hash of `identity_ref` plus the sorted branch claim_id tuples —
    deterministic regardless of the order `branches` is passed in, and
    identical on any two replicas holding the same claims for this
    identity (STARLING_BUILD_STATE.md WP-06 Part 3: "the same fork
    produced on two replicas has an identical fork_id").
    """
    canonical = sorted(branch.claim_ids for branch in branches)
    digest_input = identity_ref + "|" + "|".join(",".join(ids) for ids in canonical)
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]


def make_fork(identity_ref: str, branches: tuple[Branch, ...], opened_at: HLC) -> IdentityFork:
    """Build a freshly OPEN fork. Resolution (if any) is applied
    separately via `ForkSet.resolve()` or by constructing a replacement
    `IdentityFork` with an updated `status`/`resolution_reason`.
    """
    return IdentityFork(
        fork_id=compute_fork_id(identity_ref, branches),
        identity_ref=identity_ref,
        branches=branches,
        opened_at=opened_at,
        status=ForkStatus.OPEN,
        resolution_reason=None,
        resolved_branch=None,
    )


def evaluate_reachability(
    fork: IdentityFork,
    geometry: ReachabilityModel,
    reference_position: tuple[float, float],
    reference_physical_ms: int,
) -> Optional[tuple[int, str]]:
    """REACHABILITY resolution rule. `reference_position`/
    `reference_physical_ms` is the identity's LAST CONFIRMED position —
    the point before the branches diverged — supplied by the caller (not
    inferred from the fork itself, which keeps this function a plain,
    hand-testable pure function).

    Checks every branch's reachability from that one reference point. If
    EXACTLY ONE branch is reachable, returns `(branch_index, reason)`
    where `reason` names the specific geometric fact that ruled the
    other branch(es) out (the implied speed each one would require —
    never a bare "rejected"). Returns `None` if zero or more than one
    branch is reachable: the ambiguity is genuine and the fork MUST stay
    open — this is the intended behaviour and a demonstrated feature of
    the system, not a bug (CLAUDE.md rule 6): never close a fork by
    comparing scores, and an unresolved ambiguity is an honest output.
    """
    reachable: list[int] = []
    rejection_reasons: dict[int, str] = {}

    for idx, branch in enumerate(fork.branches):
        dt_s = max(0.0, (branch.hlc_span[1].physical_ms - reference_physical_ms) / 1000.0)
        if geometry.is_reachable(reference_position, branch.last_position, dt_s, pos_sigma=0.0):
            reachable.append(idx)
        else:
            dist_field = geometry.distance_field(reference_position)
            ti, tj = geometry.navmesh.world_to_cell(*branch.last_position)
            height, width = dist_field.shape
            distance_m = (
                float(dist_field[tj, ti]) if (0 <= ti < width and 0 <= tj < height) else float("inf")
            )
            implied_speed = distance_m / dt_s if dt_s > 0 else float("inf")
            rejection_reasons[idx] = (
                f"branch {idx} requires {implied_speed:.1f} m/s over {dt_s:.1f} s, "
                f"exceeds v_max {geometry.v_max_m_s:.1f} m/s"
            )

    if len(reachable) == 1:
        winner = reachable[0]
        reason = "; ".join(rejection_reasons[idx] for idx in sorted(rejection_reasons))
        return winner, reason

    # Zero branches reachable (a data/config problem, not an ambiguity to
    # surface as-is — treated the same as "stays open" here, since there
    # is no winner to pick) OR more than one branch reachable (genuine,
    # simultaneous physical plausibility): in both cases this function
    # deliberately returns None and the fork stays OPEN. See module
    # docstring: this is a demonstrated feature, not a bug.
    return None


class ForkSet:
    """All identity forks known from one `resolve()` run."""

    def __init__(self) -> None:
        self._forks: dict[str, IdentityFork] = {}

    def add(self, fork: IdentityFork) -> None:
        self._forks[fork.fork_id] = fork

    def get(self, fork_id: str) -> Optional[IdentityFork]:
        return self._forks.get(fork_id)

    def open_forks(self) -> list[IdentityFork]:
        return sorted(
            (f for f in self._forks.values() if f.status == ForkStatus.OPEN),
            key=lambda f: f.fork_id,
        )

    def all_forks(self) -> list[IdentityFork]:
        """Every fork known to this set (open or resolved), for reporting
        (e.g. `docs/results_c1.md`'s unresolved-fork-rate) and for
        `resolver.assert_deterministic`'s canonical comparison.
        """
        return sorted(self._forks.values(), key=lambda f: f.fork_id)

    def resolve(self, fork_id: str, branch: int, reason: str, status: ForkStatus) -> None:
        """Record a resolution. Idempotent: calling this again with the
        same `(branch, reason, status)` on an already-resolved fork
        leaves it unchanged. `status` must not be `ForkStatus.OPEN` (use
        this to CLOSE a fork, not to reopen one).
        """
        if status == ForkStatus.OPEN:
            raise ValueError("resolve() closes a fork; pass a RESOLVED_* status")
        existing = self._forks.get(fork_id)
        if existing is None:
            raise KeyError(f"no fork with id {fork_id!r}")
        self._forks[fork_id] = IdentityFork(
            fork_id=existing.fork_id,
            identity_ref=existing.identity_ref,
            branches=existing.branches,
            opened_at=existing.opened_at,
            status=status,
            resolution_reason=reason,
            resolved_branch=branch,
        )
