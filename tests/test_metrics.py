"""Tests for starling_eval.metrics (D-11). Every function gets a
hand-computed case with a known answer, not just random-data sanity checks.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from starling_eval.metrics import (
    ExtendedGTRow,
    accuracy_vs_gap_duration,
    accuracy_vs_malicious_fraction,
    attestation_accuracy,
    bytes_per_node_hour,
    candidate_region_reduction,
    end_to_end_latency,
    evaluate_tracking,
    false_claim_rejection_rate,
    false_exclusion_rate,
    graph_edit_distance,
    identity_consistency_after_merge,
    read_extended_mot_gt,
    time_to_reconverge,
    topology_reconvergence_time,
    unresolved_fork_rate,
    write_extended_mot_gt,
)


# ── Tracking (TrackEval) ─────────────────────────────────────────────────────

def test_evaluate_tracking_perfect_match_gives_perfect_scores(tmp_path: Path):
    gt_lines, pred_lines = [], []
    for frame in range(1, 4):
        gt_lines.append(f"{frame},1,{10 + frame},20,30,60,1,1,1.0")
        gt_lines.append(f"{frame},2,50,{20 + frame},30,60,1,1,1.0")
        pred_lines.append(f"{frame},1,{10 + frame},20,30,60,1")
        pred_lines.append(f"{frame},2,50,{20 + frame},30,60,1")

    gt_path = tmp_path / "gt.txt"
    pred_path = tmp_path / "pred.txt"
    gt_path.write_text("\n".join(gt_lines), encoding="utf-8")
    pred_path.write_text("\n".join(pred_lines), encoding="utf-8")

    result = evaluate_tracking(gt_path, pred_path)

    assert result["HOTA"] == pytest.approx(1.0)
    assert result["MOTA"] == pytest.approx(1.0)
    assert result["IDF1"] == pytest.approx(1.0)
    assert result["IDSW"] == 0


def test_evaluate_tracking_detects_an_id_switch(tmp_path: Path):
    # Same two tracks as above, but the tracker swaps ids 1<->2 on frame 3.
    gt_lines = [
        "1,1,10,20,30,60,1,1,1.0", "1,2,50,20,30,60,1,1,1.0",
        "2,1,11,20,30,60,1,1,1.0", "2,2,50,21,30,60,1,1,1.0",
        "3,1,12,20,30,60,1,1,1.0", "3,2,50,22,30,60,1,1,1.0",
    ]
    pred_lines = [
        "1,1,10,20,30,60,1", "1,2,50,20,30,60,1",
        "2,1,11,20,30,60,1", "2,2,50,21,30,60,1",
        "3,2,12,20,30,60,1", "3,1,50,22,30,60,1",  # ids swapped on frame 3
    ]
    gt_path = tmp_path / "gt.txt"
    pred_path = tmp_path / "pred.txt"
    gt_path.write_text("\n".join(gt_lines), encoding="utf-8")
    pred_path.write_text("\n".join(pred_lines), encoding="utf-8")

    result = evaluate_tracking(gt_path, pred_path)
    assert result["IDSW"] >= 1


# ── C1 ────────────────────────────────────────────────────────────────────────

def test_identity_consistency_after_merge_hand_computed():
    replica_states = [
        {"c1": "P1", "c2": "P2"},
        {"c1": "P1", "c2": "P2"},
        {"c1": "P1", "c2": "P3"},  # disagrees on c2
    ]
    assert identity_consistency_after_merge(replica_states) == pytest.approx(0.5)


def test_identity_consistency_after_merge_full_agreement_is_1():
    replica_states = [{"c1": "P1"}, {"c1": "P1"}]
    assert identity_consistency_after_merge(replica_states) == pytest.approx(1.0)


def test_time_to_reconverge_hand_computed():
    event_log = [
        {"t": 0, "event": "start"},
        {"t": 10, "event": "heal"},
        {"t": 10, "event": "other"},
        {"t": 25, "event": "converged"},
    ]
    assert time_to_reconverge(event_log) == pytest.approx(15.0)


def test_time_to_reconverge_is_inf_when_never_converges():
    assert time_to_reconverge([{"t": 0, "event": "heal"}]) == float("inf")


def test_unresolved_fork_rate_hand_computed():
    assignment = {
        "id1": {"forked": True},
        "id2": {"forked": False},
        "id3": {"forked": True},
    }
    assert unresolved_fork_rate(assignment, total_identities=5) == pytest.approx(0.4)


# ── C2 ────────────────────────────────────────────────────────────────────────

def test_accuracy_vs_malicious_fraction_averages_repeats():
    runs = [
        {"malicious_fraction": 0.0, "accuracy": 1.0},
        {"malicious_fraction": 0.0, "accuracy": 0.9},
        {"malicious_fraction": 0.2, "accuracy": 0.8},
    ]
    assert accuracy_vs_malicious_fraction(runs) == [(0.0, pytest.approx(0.95)), (0.2, pytest.approx(0.8))]


def test_false_claim_rejection_rate_hand_computed():
    claims = [
        {"claim_id": "a", "rejected": True},
        {"claim_id": "b", "rejected": True},
        {"claim_id": "c", "rejected": False},
        {"claim_id": "d", "rejected": False},
    ]
    result = false_claim_rejection_rate(claims, ground_truth_malicious={"a", "d"})

    assert result["rejection_rate"] == pytest.approx(0.5)
    assert result["precision"] == pytest.approx(0.5)
    assert result["recall"] == pytest.approx(0.5)
    assert result["n_rejected"] == 2
    assert result["n_malicious"] == 2
    assert result["n_total"] == 4


# ── C3 ────────────────────────────────────────────────────────────────────────

def test_accuracy_vs_gap_duration_hand_computed():
    matches = [
        {"gap_s": 1.0, "correct": True},
        {"gap_s": 4.0, "correct": True},
        {"gap_s": 4.5, "correct": False},
        {"gap_s": 100.0, "correct": True},
    ]
    result = accuracy_vs_gap_duration(matches, gap_buckets=[2, 5, 15, 30, 60, 120])
    assert result == [(2, pytest.approx(1.0)), (5, pytest.approx(0.5)), (120, pytest.approx(1.0))]


# ── C4 ────────────────────────────────────────────────────────────────────────

def test_candidate_region_reduction_hand_computed():
    assert candidate_region_reduction(area_without=100.0, area_with=40.0) == pytest.approx(0.6)
    assert candidate_region_reduction(area_without=0.0, area_with=0.0) == 0.0


def test_false_exclusion_rate_exactly_0_2_over_10_masks_with_2_wrong():
    true_position = (2, 2)  # (col, row)
    masks = []
    for i in range(10):
        mask = np.zeros((5, 5), dtype=bool)
        if i < 2:
            mask[2, 2] = True  # wrongly excludes the true position
        masks.append(mask)
    positions = [true_position] * 10

    assert false_exclusion_rate(masks, positions) == pytest.approx(0.2)


def test_attestation_accuracy_hand_computed():
    attestations = [
        {"t_start": 0, "t_end": 10, "boundary_id": 1, "crossing_observed": False},   # correct
        {"t_start": 10, "t_end": 20, "boundary_id": 1, "crossing_observed": False},  # incorrect
        {"t_start": 0, "t_end": 5, "boundary_id": 2, "crossing_observed": True},     # not counted
    ]
    ground_truth_crossings = [{"t": 15, "boundary_id": 1}]

    result = attestation_accuracy(attestations, ground_truth_crossings)
    assert result == {"accuracy": pytest.approx(0.5), "correct": 1, "incorrect": 1, "n_attestations": 2}


# ── C6 ────────────────────────────────────────────────────────────────────────

def test_graph_edit_distance_hand_computed():
    learned_adj = {0: {1, 2}, 1: {0}, 2: {0}}
    true_adj = {0: {1}, 1: {0, 2}, 2: {1}}
    assert graph_edit_distance(learned_adj, true_adj) == 2


def test_graph_edit_distance_zero_for_identical_graphs():
    adj = {0: {1}, 1: {0}}
    assert graph_edit_distance(adj, adj) == 0


def test_topology_reconvergence_time_hand_computed():
    event_log = [
        {"t": 5, "event": "topology_change"},
        {"t": 5, "event": "noise"},
        {"t": 30, "event": "topology_converged"},
    ]
    assert topology_reconvergence_time(event_log) == pytest.approx(25.0)


# ── System ────────────────────────────────────────────────────────────────────

def test_bytes_per_node_hour_hand_computed():
    stats = [
        {"claim": {"sent": 10, "sent_bytes": 1000, "recv": 5, "recv_bytes": 500}, "_dropped": 0, "_uptime_s": 3600},
        {"claim": {"sent": 10, "sent_bytes": 1000, "recv": 5, "recv_bytes": 500}, "_dropped": 0, "_uptime_s": 3600},
    ]
    assert bytes_per_node_hour(stats, uptime_s=3600.0) == pytest.approx(1500.0)


def test_end_to_end_latency_percentiles_hand_computed():
    claim_log = [
        {"t_observed": 0, "t_delivered": 40},
        {"t_observed": 0, "t_delivered": 10},
        {"t_observed": 0, "t_delivered": 30},
        {"t_observed": 0, "t_delivered": 50},
        {"t_observed": 0, "t_delivered": 20},
    ]
    result = end_to_end_latency(claim_log)
    assert result == {"p50": pytest.approx(30.0), "p95": pytest.approx(50.0), "p99": pytest.approx(50.0), "n": 5}


def test_end_to_end_latency_empty_log():
    assert end_to_end_latency([]) == {"p50": 0.0, "p95": 0.0, "p99": 0.0, "n": 0}


# ── Ground-truth format ──────────────────────────────────────────────────────

def test_extended_mot_gt_round_trips(tmp_path: Path):
    rows = [
        ExtendedGTRow(
            frame=1, track_id=1, bb_left=10.0, bb_top=20.0, bb_width=30.0, bb_height=60.0,
            conf=1.0, cls=1, visibility=0.9, identity="P-0001",
            node_visibility={0: True, 1: False, 2: True},
        ),
        ExtendedGTRow(
            frame=1, track_id=2, bb_left=50.0, bb_top=20.0, bb_width=30.0, bb_height=60.0,
            conf=1.0, cls=1, visibility=1.0, identity="P-0002",
            node_visibility={0: False, 1: True},
        ),
    ]
    path = tmp_path / "extended_gt.txt"
    write_extended_mot_gt(path, rows)
    restored = read_extended_mot_gt(path)

    assert restored == rows
