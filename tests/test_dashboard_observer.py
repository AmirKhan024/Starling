"""Tests for apps.dashboard.observer.GossipObserver (WP-13).

Loopback-only, no Docker required — same convention as tests/test_gossip.py.
"""

from __future__ import annotations

import re
import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps"))

from dashboard.observer import GossipObserver  # noqa: E402

from starling_net.gossip import GossipNode
from starling_net.keys import generate_keypair, load_keys
from starling_proto.generated import starling_pb2

APPS_DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "apps" / "dashboard"


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


def _make_claim(node_id: int, seq: int, claim_id: bytes) -> starling_pb2.IdentityClaim:
    claim = starling_pb2.IdentityClaim(
        claim_id=claim_id,
        node_id=node_id,
        seq=seq,
        embedding=bytes(64),
        embed_scale=1.0,
        confidence=0.9,
        quality=1.0,
    )
    claim.t_start.physical_ms = 1_750_000_000_000 + seq
    claim.t_start.node_id = node_id
    return claim


def test_observer_receives_claims_from_two_gossip_nodes_and_builds_a_claimset(keys_dir):
    port_a, port_b = _free_port(), _free_port()
    keys_a = load_keys(0, keys_dir=keys_dir)
    keys_b = load_keys(1, keys_dir=keys_dir)

    # A dummy (unreachable) neighbour, not the dashboard observer: GossipNode
    # .publish() deliberately no-ops when `neighbours` is empty ("nothing this
    # node's gossip could reach" -- see its own docstring). A real node in
    # production always has configured neighbours, so this never happens
    # there; the dashboard observer itself is never a configured neighbour of
    # any node (CLAUDE.md rule 8), so this dummy address only exists to give
    # these two test publishers a reason to actually send.
    node_a = GossipNode(0, port_a, ["127.0.0.1:1"], keys_a, on_message=lambda e: None)
    node_b = GossipNode(1, port_b, ["127.0.0.1:1"], keys_b, on_message=lambda e: None)
    node_a.start()
    node_b.start()

    observer = GossipObserver(peers={0: f"127.0.0.1:{port_a}", 1: f"127.0.0.1:{port_b}"}, keys_dir=keys_dir)
    observer.start()
    try:
        time.sleep(0.3)  # slow-joiner problem, same as test_gossip.py

        env_a = starling_pb2.Envelope(msg_id=bytes(16), sender_node_id=0)
        env_a.claim.CopyFrom(_make_claim(0, seq=1, claim_id=bytes(16)))
        env_b = starling_pb2.Envelope(msg_id=bytes(16), sender_node_id=1)
        env_b.claim.CopyFrom(_make_claim(1, seq=1, claim_id=bytes(bytearray([1] * 16))))

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and len(observer.claims) < 2:
            node_a.publish(env_a)
            node_b.publish(env_b)
            time.sleep(0.05)

        assert len(observer.claims) == 2
        node_ids = {c["node_id"] for c in observer.claims.ordered()}
        assert node_ids == {0, 1}

        assert observer.liveness(stale_after_s=5.0) == {0: True, 1: True}
        stats = observer.stats()
        assert stats["claim"]["recv"] == 2
        assert stats["claim"]["recv_bytes"] > 0
    finally:
        observer.stop()
        node_a.stop()
        node_b.stop()


def test_observer_drops_unsigned_and_tampered_messages(keys_dir):
    import zmq

    attacker_port = _free_port()
    observer = GossipObserver(peers={99: f"127.0.0.1:{attacker_port}"}, keys_dir=keys_dir)

    ctx = zmq.Context.instance()
    attacker_pub = ctx.socket(zmq.PUB)
    attacker_pub.bind(f"tcp://*:{attacker_port}")
    observer.start()
    try:
        time.sleep(0.3)
        env = starling_pb2.Envelope(msg_id=bytes(16), sender_node_id=99)
        env.claim.CopyFrom(_make_claim(99, seq=1, claim_id=bytes(16)))  # never signed

        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            attacker_pub.send(env.SerializeToString())
            time.sleep(0.05)

        assert len(observer.claims) == 0
        assert observer.stats()["_dropped"] > 0
        assert observer.liveness(stale_after_s=5.0) == {99: False}
    finally:
        observer.stop()
        attacker_pub.close(linger=0)


def test_observer_ingests_reputation_updates(keys_dir):
    port_a = _free_port()
    keys_a = load_keys(0, keys_dir=keys_dir)
    node_a = GossipNode(0, port_a, ["127.0.0.1:1"], keys_a, on_message=lambda e: None)
    node_a.start()

    observer = GossipObserver(peers={0: f"127.0.0.1:{port_a}"}, keys_dir=keys_dir)
    observer.start()
    try:
        time.sleep(0.3)
        env = starling_pb2.Envelope(msg_id=bytes(16), sender_node_id=0)
        env.reputation.from_node = 0
        env.reputation.about_node = 2
        env.reputation.score = 0.3

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and observer.reputation.aggregate(2) == observer.reputation.cfg.r_initial:
            node_a.publish(env)
            time.sleep(0.05)

        # aggregate() takes the median of [this observer's own (neutral,
        # never-observed) local opinion, r_initial=1.0] + [the one gossiped
        # opinion, 0.3] -- with two values, median is their average.
        assert observer.reputation.aggregate(2) == pytest.approx(0.65)
        assert 2 in observer.reputation._gossiped
        assert observer.reputation._gossiped[2][0] == pytest.approx(0.3)
    finally:
        observer.stop()
        node_a.stop()


def test_coverage_completeness_reflects_offline_peers(keys_dir):
    observer = GossipObserver(peers={0: "127.0.0.1:1", 1: "127.0.0.1:2"}, keys_dir=keys_dir)
    # Never started / never heard from either peer -> fully blind, not "fully healthy".
    assert observer.coverage_completeness(stale_after_s=5.0) == 0.0


def test_dashboard_has_no_sqlite_connection_to_a_node_database():
    """CLAUDE.md rule 8 / WP-13 stop condition: the dashboard must never
    gain database access. Grep every file under apps/dashboard/ for a
    direct sqlite3 connection or a starling_store.LocalStore/IdentityStore
    pointed at anything other than this process's own ':memory:' scratch
    space.
    """
    offending = []
    for path in APPS_DASHBOARD_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bsqlite3\.connect\s*\(", text):
            offending.append((path, "sqlite3.connect"))
        for match in re.finditer(r"(LocalStore|IdentityStore)\s*\(\s*db_path\s*=\s*([^,)\n]+)", text):
            db_path_arg = match.group(2).strip()
            if db_path_arg not in ('":memory:"', "':memory:'"):
                offending.append((path, f"{match.group(1)}(db_path={db_path_arg})"))
    assert not offending, f"apps/dashboard/ must never open a real database: {offending}"


def test_dashboard_has_no_filesystem_read_of_node_data_directories():
    """Same rule, the other half: no direct read of data/nodes/ anywhere
    under apps/dashboard/ — that directory tree is exactly the per-node
    private state CLAUDE.md rule 2 forbids any other module from touching.
    """
    offending = []
    for path in APPS_DASHBOARD_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"data[/\\]nodes[/\\]", text):
            offending.append(path)
    assert not offending, f"apps/dashboard/ must never reference data/nodes/ paths: {offending}"
