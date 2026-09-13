"""Tests for starling_net.gossip (WP-04 Part 2): loopback-only, no Docker
or real network required.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path

import pytest
import zmq

from starling_net.gossip import GossipNode
from starling_net.keys import NodeKeys, generate_keypair, load_keys
from starling_proto.generated import starling_pb2


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def keys_dir(tmp_path: Path) -> Path:
    d = tmp_path / "keys"
    for node_id in range(4):
        generate_keypair(node_id, keys_dir=d)
    return d


def _make_claim_envelope(sender_node_id: int, seq: int = 1) -> starling_pb2.Envelope:
    env = starling_pb2.Envelope(msg_id=bytes(16), sender_node_id=sender_node_id)
    env.sent_hlc.physical_ms = 1_750_000_000_000
    env.claim.node_id = sender_node_id
    env.claim.seq = seq
    env.claim.claim_id = bytes(16)
    env.claim.embedding = bytes(64)
    env.claim.embed_scale = 1.0
    return env


def test_two_nodes_exchange_a_claim_within_2_seconds(keys_dir):
    port_a, port_b = _free_port(), _free_port()
    keys_a = load_keys(0, keys_dir=keys_dir)
    keys_b = load_keys(1, keys_dir=keys_dir)

    received = []
    node_a = GossipNode(0, port_a, [f"127.0.0.1:{port_b}"], keys_a, on_message=lambda e: None)
    node_b = GossipNode(1, port_b, [f"127.0.0.1:{port_a}"], keys_b, on_message=received.append)

    node_a.start()
    node_b.start()
    try:
        time.sleep(0.3)  # let PUB/SUB connections establish (slow-joiner problem)

        env = _make_claim_envelope(sender_node_id=0)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not received:
            node_a.publish(env)
            time.sleep(0.05)

        assert received, "node_b never received node_a's claim within 2s"
        assert received[0].claim.node_id == 0
    finally:
        node_a.stop()
        node_b.stop()


def test_tampered_payload_is_dropped_and_counted(keys_dir):
    attacker_port = _free_port()
    port_b = _free_port()
    keys_a = load_keys(0, keys_dir=keys_dir)
    keys_b = load_keys(1, keys_dir=keys_dir)

    env = _make_claim_envelope(sender_node_id=0)
    env.claim.signature = keys_a.sign(env.claim.SerializeToString())
    raw = bytearray(env.SerializeToString())
    raw[0] ^= 0xFF  # tamper after signing: signature no longer matches
    tampered_bytes = bytes(raw)

    received = []
    node_b = GossipNode(1, port_b, [f"127.0.0.1:{attacker_port}"], keys_b, on_message=received.append)
    node_b.start()
    ctx = zmq.Context.instance()
    attacker_pub = ctx.socket(zmq.PUB)
    try:
        attacker_pub.bind(f"tcp://*:{attacker_port}")
        time.sleep(0.3)

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and node_b.stats()["_dropped"] == 0:
            attacker_pub.send(tampered_bytes)
            time.sleep(0.05)

        assert not received
        assert node_b.stats()["_dropped"] > 0
    finally:
        attacker_pub.close(linger=0)
        node_b.stop()


def test_message_from_unenrolled_key_is_dropped(tmp_path):
    keys_dir = tmp_path / "keys"
    generate_keypair(1, keys_dir=keys_dir)
    generate_keypair(5, keys_dir=keys_dir)
    keys_5 = load_keys(5, keys_dir=keys_dir)

    # node_b (id=1) only ever enrolled its own key — node 5's key exists
    # somewhere but was never distributed to node_b, simulating an
    # unenrolled sender.
    keys_b_full = load_keys(1, keys_dir=keys_dir)
    keys_b = NodeKeys(
        node_id=1,
        signing_key=keys_b_full.signing_key,
        peer_pubkeys={1: keys_b_full.peer_pubkeys[1]},
    )

    attacker_port = _free_port()
    port_b = _free_port()

    env = _make_claim_envelope(sender_node_id=5)
    env.claim.signature = keys_5.sign(env.claim.SerializeToString())
    raw = env.SerializeToString()

    received = []
    node_b = GossipNode(1, port_b, [f"127.0.0.1:{attacker_port}"], keys_b, on_message=received.append)
    node_b.start()
    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    try:
        pub.bind(f"tcp://*:{attacker_port}")
        time.sleep(0.3)

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and node_b.stats()["_dropped"] == 0:
            pub.send(raw)
            time.sleep(0.05)

        assert not received
        assert node_b.stats()["_dropped"] > 0
    finally:
        pub.close(linger=0)
        node_b.stop()


def test_byte_counters_increase_by_serialised_size(keys_dir):
    port_a, port_b = _free_port(), _free_port()
    keys_a = load_keys(0, keys_dir=keys_dir)
    keys_b = load_keys(1, keys_dir=keys_dir)

    received = []
    node_a = GossipNode(0, port_a, [f"127.0.0.1:{port_b}"], keys_a, on_message=lambda e: None)
    node_b = GossipNode(1, port_b, [f"127.0.0.1:{port_a}"], keys_b, on_message=received.append)
    node_a.start()
    node_b.start()
    try:
        time.sleep(0.3)
        env = _make_claim_envelope(sender_node_id=0)

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not received:
            node_a.publish(env)
            time.sleep(0.05)
        assert received

        a_stats = node_a.stats()["claim"]
        b_stats = node_b.stats()["claim"]
        assert a_stats["sent"] >= 1
        assert a_stats["sent_bytes"] > 0
        assert b_stats["recv"] >= 1
        assert b_stats["recv_bytes"] > 0
        assert b_stats["recv_bytes"] == a_stats["sent_bytes"] * (b_stats["recv"] / a_stats["sent"])
    finally:
        node_a.stop()
        node_b.stop()


def test_empty_neighbour_list_sends_nothing(keys_dir):
    port = _free_port()
    keys_a = load_keys(0, keys_dir=keys_dir)
    node = GossipNode(0, port, [], keys_a, on_message=lambda e: None)
    node.start()
    try:
        env = _make_claim_envelope(sender_node_id=0)
        node.publish(env)
        node.publish(env)

        stats = node.stats()
        assert stats.get("claim", {"sent": 0})["sent"] == 0
    finally:
        node.stop()
