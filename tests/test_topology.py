"""Tests for starling_topology.learner (WP-07, C6)."""

from __future__ import annotations

import math

import numpy as np

from starling_consensus.reputation import ReputationTable
from starling_eval.metrics import graph_edit_distance
from starling_node.config import ReputationConfig, TopologyConfig
from starling_topology.learner import TopologyLearner


def _learner(**overrides) -> TopologyLearner:
    return TopologyLearner(TopologyConfig(**overrides))


def test_recovers_lognormal_parameters_within_10_percent():
    rng = np.random.default_rng(0)
    true_mu, true_sigma = math.log(8.0), 0.25  # ~8s transit, tight corridor
    learner = _learner(k_min=5)

    samples = rng.lognormal(mean=true_mu, sigma=true_sigma, size=200)
    for s in samples:
        learner.observe_handoff(0, 1, float(s), confidence=0.9)

    dist = learner.edges()[(0, 1)]
    assert dist.count == 200
    assert abs(dist.mu - true_mu) / abs(true_mu) < 0.10
    assert abs(dist.sigma - true_sigma) / true_sigma < 0.10


def test_uniform_pair_does_not_become_an_edge():
    rng = np.random.default_rng(7)
    learner = _learner(k_min=5)

    for _ in range(5):
        transit = float(rng.uniform(1.0, 100.0))
        learner.observe_handoff(2, 3, transit, confidence=0.9)

    assert (2, 3) not in learner.edges()
    # A learner that has never qualified an edge must still return a
    # neutral (never penalising) prior for it.
    assert learner.prior(2, 3, dt_s=10.0) == 1.0


def test_low_confidence_handoffs_are_never_learned():
    learner = _learner(handoff_confidence_min=0.5, k_min=3)
    for _ in range(50):
        learner.observe_handoff(4, 5, 10.0, confidence=0.1)
    assert (4, 5) not in learner._edges


def test_edge_is_undirected():
    learner = _learner(k_min=3)
    for _ in range(10):
        learner.observe_handoff(1, 2, 10.0, confidence=0.9)
        learner.observe_handoff(2, 1, 10.0, confidence=0.9)
    assert learner.edges()[(1, 2)].count == 20


def test_prior_peaks_near_mean_and_falls_off_at_tails():
    rng = np.random.default_rng(11)
    true_mu = math.log(10.0)
    learner = _learner(k_min=5)
    for s in rng.lognormal(mean=true_mu, sigma=0.2, size=100):
        learner.observe_handoff(0, 1, float(s), confidence=0.9)

    at_mean = learner.prior(0, 1, dt_s=math.exp(true_mu))
    short_tail = learner.prior(0, 1, dt_s=0.5)
    long_tail = learner.prior(0, 1, dt_s=200.0)

    assert at_mean > 0.95
    assert short_tail < at_mean
    assert long_tail < at_mean
    assert 0.0 <= short_tail <= 1.0
    assert 0.0 <= long_tail <= 1.0


def test_detect_shift_fires_when_mean_doubles():
    rng = np.random.default_rng(3)
    learner = _learner(k_min=5, shift_window=15, shift_threshold_sigma=3.0)

    # A baseline bigger than the comparison window (2*shift_window), so
    # some pre-shift observations are still in the recent-history buffer
    # once the shifted batch lands alongside them.
    for s in rng.lognormal(mean=math.log(10.0), sigma=0.1, size=45):
        learner.observe_handoff(0, 1, float(s), confidence=0.9)
    assert learner.detect_shift(0, 1) is False

    for s in rng.lognormal(mean=math.log(20.0), sigma=0.1, size=15):
        learner.observe_handoff(0, 1, float(s), confidence=0.9)
    assert learner.detect_shift(0, 1) is True


def test_detect_shift_does_not_fire_on_stationary_data():
    rng = np.random.default_rng(5)
    learner = _learner(k_min=5, shift_window=15)
    for s in rng.lognormal(mean=math.log(10.0), sigma=0.15, size=60):
        learner.observe_handoff(0, 1, float(s), confidence=0.9)
    assert learner.detect_shift(0, 1) is False


def test_apply_shift_penalties_is_weak_and_symmetric():
    rng = np.random.default_rng(9)
    learner = _learner(k_min=5, shift_window=15, topology_shift_weight=1.0)  # request max, expect clamp
    rep_cfg = ReputationConfig(topology_shift_max_weight=0.15)
    table = ReputationTable(node_id=99, cfg=rep_cfg)

    for s in rng.lognormal(mean=math.log(10.0), sigma=0.1, size=45):
        learner.observe_handoff(0, 1, float(s), confidence=0.9)
    for s in rng.lognormal(mean=math.log(40.0), sigma=0.1, size=15):
        learner.observe_handoff(0, 1, float(s), confidence=0.9)

    shifted = learner.apply_shift_penalties(table)
    assert shifted == [(0, 1)]
    # A single weak-signal hit, clamped, must not come close to r_min.
    assert table.local_opinion(0) > 0.8
    assert table.local_opinion(1) > 0.8


def test_graph_edit_distance_to_identical_graph_is_zero():
    learner = _learner(k_min=3)
    for _ in range(10):
        learner.observe_handoff(0, 1, 8.0, confidence=0.9)
        learner.observe_handoff(1, 2, 12.0, confidence=0.9)

    graph = learner.to_graph()
    learned_adj = {n: set(neighbours) for n, neighbours in graph["adjacency"].items()}
    true_adj = {0: {1}, 1: {0, 2}, 2: {1}}

    assert graph_edit_distance(learned_adj, true_adj) == 0


def test_update_from_assignment_extracts_cross_node_handoffs():
    from starling_crdt.claims import ClaimSet
    from starling_crdt.resolver import Assignment
    from starling_store.identity_store import LocalStore

    store = LocalStore(db_path=":memory:", node_id=-1)
    claims = ClaimSet(store)

    def _claim(claim_id, node_id, seq, t_media, confidence=0.9):
        return {
            "claim_id": claim_id,
            "node_id": node_id,
            "seq": seq,
            "hlc_physical_ms": int(t_media * 1000),
            "hlc_logical": 0,
            "local_track_id": 1,
            "t_media": t_media,
            "embedding": b"",
            "embed_scale": 1.0,
            "world_x": None,
            "world_y": None,
            "pos_sigma": None,
            "anchor_type": "UNANCHORED",
            "identity_ref": None,
            "last_anchor_t": None,
            "confidence": confidence,
            "quality": 1.0,
            "signature": b"",
        }

    c1 = _claim("c1", node_id=0, seq=1, t_media=0.0)
    c2 = _claim("c2", node_id=1, seq=1, t_media=8.0)
    claims.add(c1)
    claims.add(c2)

    assignment = Assignment(
        identity_of={"c1": "AUTO-c1", "c2": "AUTO-c1"},
        trajectories={"AUTO-c1": ["c1", "c2"]},
        confidence={"AUTO-c1": 0.9},
    )

    learner = _learner(k_min=1)
    learner.update_from_assignment(assignment, claims)

    assert (0, 1) in learner._edges
    assert learner._edges[(0, 1)].count == 1


def test_low_confidence_pair_never_qualifies_regardless_of_count():
    learner = _learner(handoff_confidence_min=0.5, k_min=1)
    learner.observe_handoff(0, 1, 10.0, confidence=0.1)
    assert (0, 1) not in learner.edges()
