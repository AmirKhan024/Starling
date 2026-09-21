"""Tests for starling_sim.transport: a real ZMQ PUB/SUB round trip over
loopback. Uses a wildcard port ("tcp://127.0.0.1:*") so tests never
collide on a fixed port, and a short settle delay after connecting to
cover ZMQ's well-known "slow joiner" startup race (a SUB that starts
receiving a moment after it connects, not instantly).
"""

from __future__ import annotations

import time

from starling_sim.messages import GROUND_TRUTH_TOPIC, node_topic
from starling_sim.transport import SimPublisher, SimSubscriber


def test_subscriber_receives_only_its_own_topic():
    pub = SimPublisher("tcp://127.0.0.1:*")
    sub0 = SimSubscriber(pub.endpoint, node_topic(0))
    sub1 = SimSubscriber(pub.endpoint, node_topic(1))
    time.sleep(0.2)  # let SUB sockets finish subscribing before the first publish

    try:
        pub.publish(node_topic(0), {"hello": "node0"})
        pub.publish(node_topic(1), {"hello": "node1"})

        msg0 = sub0.recv(timeout_ms=2000)
        msg1 = sub1.recv(timeout_ms=2000)

        assert msg0 == {"hello": "node0"}
        assert msg1 == {"hello": "node1"}

        # Neither subscriber should ever see the other's topic.
        assert sub0.recv(timeout_ms=200) is None
        assert sub1.recv(timeout_ms=200) is None
    finally:
        pub.close()
        sub0.close()
        sub1.close()


def test_recv_times_out_with_none_when_nothing_is_published():
    pub = SimPublisher("tcp://127.0.0.1:*")
    sub = SimSubscriber(pub.endpoint, node_topic(2))
    try:
        assert sub.recv(timeout_ms=200) is None
    finally:
        pub.close()
        sub.close()


def test_ground_truth_topic_is_independent_of_node_topics():
    pub = SimPublisher("tcp://127.0.0.1:*")
    gt_sub = SimSubscriber(pub.endpoint, GROUND_TRUTH_TOPIC)
    node_sub = SimSubscriber(pub.endpoint, node_topic(0))
    time.sleep(0.2)

    try:
        pub.publish(GROUND_TRUTH_TOPIC, {"workers": []})
        pub.publish(node_topic(0), {"observations": []})

        assert gt_sub.recv(timeout_ms=2000) == {"workers": []}
        assert node_sub.recv(timeout_ms=2000) == {"observations": []}
    finally:
        pub.close()
        gt_sub.close()
        node_sub.close()
