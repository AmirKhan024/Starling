"""Tests for starling_crdt.forks (WP-06 Part 3). Scenarios are constructed
by hand, not from real video — this module's data structures and
resolution priority rules are exactly what's under test, independent of
how starling_crdt.resolver happens to wire them in (see
tests/test_resolver.py and tests/test_partition_integration.py for the
end-to-end path).
"""

from __future__ import annotations

import numpy as np
import pytest

from starling_crdt.forks import (
    Branch,
    ForkStatus,
    ForkSet,
    compute_fork_id,
    evaluate_reachability,
    make_fork,
)
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_net.hlc import HLC


def _open_room(cell_size: float = 0.5, size_m: float = 200.0) -> NavMesh:
    n = int(size_m / cell_size)
    return NavMesh(grid=np.ones((n, n), dtype=bool), origin=(0.0, 0.0), cell_size=cell_size)


def _hlc(physical_ms: int) -> HLC:
    return HLC(physical_ms=physical_ms, logical=0, node_id=0)


def _branch(claim_ids: tuple[str, ...], position: tuple[float, float], t_ms: int) -> Branch:
    return Branch(claim_ids=claim_ids, last_position=position, hlc_span=(_hlc(t_ms), _hlc(t_ms)))


def test_one_geometrically_impossible_branch_closes_on_reachability_with_named_speed():
    geometry = ReachabilityModel(_open_room(), v_max_m_s=1.6)
    reference_position = (20.0, 20.0)
    reference_ms = 0

    plausible = _branch(("C-0",), position=(21.0, 20.0), t_ms=1000)  # 1 m/s over 1s: fine
    impossible = _branch(("C-1",), position=(100.0, 20.0), t_ms=1000)  # 80 m/s over 1s: impossible

    fork = make_fork("P-001", (plausible, impossible), opened_at=_hlc(1000))
    outcome = evaluate_reachability(fork, geometry, reference_position, reference_ms)

    assert outcome is not None
    winner, reason = outcome
    assert winner == 0
    assert "branch 1" in reason
    assert "m/s" in reason
    assert "1.6" in reason  # names v_max, the specific geometric fact


def test_two_reachable_branches_leaves_the_fork_open():
    """THE most important test in this file (STARLING_BUILD_STATE.md
    WP-06 Part 3): when both branches remain physically plausible, the
    fork stays open. Both branches are retained, both are reported, and
    the system does not guess by picking the higher-scoring one — there
    is no score anywhere in this test's inputs at all, by design.
    """
    geometry = ReachabilityModel(_open_room(), v_max_m_s=1.6)
    reference_position = (20.0, 20.0)
    reference_ms = 0

    branch_a = _branch(("C-A",), position=(21.0, 20.0), t_ms=1000)  # 1 m/s: fine
    branch_b = _branch(("C-B",), position=(20.0, 21.0), t_ms=1000)  # 1 m/s: also fine

    fork = make_fork("P-002", (branch_a, branch_b), opened_at=_hlc(1000))
    outcome = evaluate_reachability(fork, geometry, reference_position, reference_ms)

    assert outcome is None  # never close a fork by comparing scores

    forks = ForkSet()
    forks.add(fork)
    open_forks = forks.open_forks()
    assert len(open_forks) == 1
    assert open_forks[0].status == ForkStatus.OPEN
    assert set(b.claim_ids[0] for b in open_forks[0].branches) == {"C-A", "C-B"}


def test_face_anchor_closes_an_open_fork_on_the_correct_branch():
    branch_a = _branch(("C-A",), position=(21.0, 20.0), t_ms=1000)
    branch_b = _branch(("C-B",), position=(20.0, 21.0), t_ms=1000)
    fork = make_fork("P-003", (branch_a, branch_b), opened_at=_hlc(1000))

    forks = ForkSet()
    forks.add(fork)

    forks.resolve(
        fork.fork_id, branch=1, reason="closed by face anchor C-anchor-2", status=ForkStatus.RESOLVED_ANCHOR
    )

    resolved = forks.get(fork.fork_id)
    assert resolved.status == ForkStatus.RESOLVED_ANCHOR
    assert resolved.resolved_branch == 1
    assert forks.open_forks() == []


def test_same_fork_on_two_replicas_has_identical_fork_id():
    branch_a = _branch(("C-A",), position=(21.0, 20.0), t_ms=1000)
    branch_b = _branch(("C-B",), position=(20.0, 21.0), t_ms=1000)

    # Two "replicas" build the fork from the branches in different order —
    # convergence requires the fork_id not to depend on that order.
    fork_replica_1 = make_fork("P-004", (branch_a, branch_b), opened_at=_hlc(1000))
    fork_replica_2 = make_fork("P-004", (branch_b, branch_a), opened_at=_hlc(1000))

    assert fork_replica_1.fork_id == fork_replica_2.fork_id
    assert fork_replica_1.fork_id == compute_fork_id("P-004", (branch_a, branch_b))


def test_resolving_a_fork_is_idempotent():
    branch_a = _branch(("C-A",), position=(21.0, 20.0), t_ms=1000)
    branch_b = _branch(("C-B",), position=(100.0, 20.0), t_ms=1000)
    fork = make_fork("P-005", (branch_a, branch_b), opened_at=_hlc(1000))

    forks = ForkSet()
    forks.add(fork)

    forks.resolve(fork.fork_id, branch=0, reason="reason", status=ForkStatus.RESOLVED_REACHABILITY)
    first = forks.get(fork.fork_id)

    forks.resolve(fork.fork_id, branch=0, reason="reason", status=ForkStatus.RESOLVED_REACHABILITY)
    second = forks.get(fork.fork_id)

    assert first == second


def test_resolve_rejects_open_status_and_unknown_fork_id():
    branch_a = _branch(("C-A",), position=(21.0, 20.0), t_ms=1000)
    fork = make_fork("P-006", (branch_a,), opened_at=_hlc(1000))
    forks = ForkSet()
    forks.add(fork)

    with pytest.raises(ValueError):
        forks.resolve(fork.fork_id, branch=0, reason="x", status=ForkStatus.OPEN)

    with pytest.raises(KeyError):
        forks.resolve("nonexistent", branch=0, reason="x", status=ForkStatus.RESOLVED_OPERATOR)
