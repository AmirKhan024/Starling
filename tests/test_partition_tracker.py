"""Tests for starling_net.partition.PartitionTracker (WP-06 Part 4a)."""

from __future__ import annotations

from starling_net.partition import PartitionTracker


def test_starts_below_full_coverage_and_reports_no_event_yet():
    tracker = PartitionTracker(neighbour_node_ids=[1, 2, 3])
    assert tracker.coverage_completeness() == 0.0
    tracker.tick()
    assert tracker.check_partition_event() is None


def test_reaching_full_coverage_for_the_first_time_fires_healed():
    tracker = PartitionTracker(neighbour_node_ids=[1, 2])
    tracker.on_message(1)
    tracker.on_message(2)
    assert tracker.coverage_completeness() == 1.0
    assert tracker.check_partition_event() == "PARTITION_HEALED"
    # No further event on a repeated check with no state change.
    assert tracker.check_partition_event() is None


def test_going_stale_after_full_coverage_fires_detected():
    tracker = PartitionTracker(neighbour_node_ids=[1, 2], stale_after_rounds=2)
    tracker.on_message(1)
    tracker.on_message(2)
    tracker.check_partition_event()  # consume the initial HEALED

    tracker.tick()
    tracker.on_message(1)  # node 1 stays fresh; node 2 goes quiet
    tracker.tick()  # node 2's rounds_since_seen now == stale_after_rounds

    assert tracker.coverage_completeness() == 0.5
    assert tracker.check_partition_event() == "PARTITION_DETECTED"


def test_recovering_after_a_detected_partition_fires_healed_again():
    tracker = PartitionTracker(neighbour_node_ids=[1, 2], stale_after_rounds=2)
    tracker.on_message(1)
    tracker.on_message(2)
    tracker.check_partition_event()

    tracker.tick()
    tracker.tick()
    assert tracker.check_partition_event() == "PARTITION_DETECTED"

    tracker.on_message(1)
    tracker.on_message(2)
    assert tracker.check_partition_event() == "PARTITION_HEALED"


def test_no_configured_neighbours_is_trivially_fully_covered():
    tracker = PartitionTracker(neighbour_node_ids=[])
    assert tracker.coverage_completeness() == 1.0
    assert tracker.reachable_neighbours() == []


def test_on_message_from_an_unconfigured_sender_is_ignored():
    tracker = PartitionTracker(neighbour_node_ids=[1])
    tracker.on_message(99)  # not a configured neighbour
    assert tracker.coverage_completeness() == 0.0
