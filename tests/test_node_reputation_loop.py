"""Tests for apps/node.py's `_ReputationLoop` and the wire-safety chunking
of anti-entropy delta replies (STATUS.md Step 4).

These exist because manual multi-process smoke testing surfaced two real
bugs while wiring the simulator into apps/node.py:

1. A `VVDelta` reply carrying more than ~3 claims (this project's
   un-quantized float32 embeddings are ~2.2KB each) exceeds
   `starling_proto.limits.MAX_MESSAGE_BYTES` and made `GossipNode.publish`
   raise inside the gossip poll thread, silently killing that node's
   ability to receive ANY further gossip. Fixed by chunking in
   apps/node.py's `_on_gossip_message` (the one call site that turns
   `AntiEntropy.on_digest`'s claim list into wire envelopes).
2. Comparing every claim against the IMMEDIATELY PRIOR one (dt_s as small
   as one sim tick, ~0.2s) made the REACHABILITY hard-fail fire on
   ordinary position noise and geodesic-grid quantization alone, crashing
   an honest node's reputation to r_min with no attack running at all.
   Fixed by `_ReputationLoop` only refreshing its corroborated-position
   baseline at least `_MIN_BASELINE_REFRESH_S` apart, and refusing to use
   a baseline chronologically at-or-after the claim being evaluated (an
   anti-entropy catch-up delivering an old claim late must not be graded
   against a newer baseline that already passed it by).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from ulid import ULID

import apps.node as node_app
from starling_consensus.attacks import AttackInjector
from starling_consensus.reputation import ReputationTable
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_node.config import AttackConfig, PlausibilityConfig, ReputationConfig
from starling_proto.generated import starling_pb2
from starling_proto.limits import MAX_MESSAGE_BYTES
from starling_proto.convert import record_to_claim_proto
from starling_store.identity_store import LocalStore

WAREHOUSE_DEMO = (
    Path(__file__).resolve().parent.parent / "data" / "floorplan" / "warehouse_demo.geojson"
)


def _navmesh() -> NavMesh:
    return NavMesh.from_geojson(WAREHOUSE_DEMO, cell_size_m=0.25)


def _honest_claim(seq: int, t: float, pos: tuple[float, float], rng: np.random.Generator) -> dict:
    noisy = np.array(pos) + rng.normal(scale=0.15, size=2)
    return {
        "claim_id": f"real-{seq}", "node_id": 2, "seq": seq, "hlc_physical_ms": int(t * 1000),
        "hlc_logical": 0, "local_track_id": 0, "t_media": t,
        "world_x": float(noisy[0]), "world_y": float(noisy[1]), "pos_sigma": 0.15,
        "confidence": 0.9, "quality": 0.8, "embedding": np.zeros(4, dtype="float32").tobytes(),
        "embed_scale": 1.0, "anchor_type": "UNANCHORED", "identity_ref": None,
        "last_anchor_t": None, "signature": None,
    }


def _run_rounds(
    loop: "node_app._ReputationLoop",
    store: LocalStore,
    injector: AttackInjector,
    navmesh: NavMesh,
    n_rounds: int,
    start_seq: int = 0,
    start_t: float = 0.0,
    start_pos: tuple[float, float] = (27.0, 10.0),
    ticks_per_round: int = 5,
    dt: float = 0.2,
    seed: int = 1,
) -> tuple[int, float]:
    """5Hz-tick simulation of one housekeeping round at a time — a
    worker shuttling back and forth within node 2's own zone (matching
    the demo's real worker-3 route), with `injector` free to inject
    fabricated claims exactly as `apps/node.py`'s sim loop would forward
    them. Returns (next_seq, next_t) so a test can run honest rounds then
    switch the injector's attack mid-stream.
    """
    rng = np.random.default_rng(seed)
    seq = start_seq
    t = start_t
    pos = list(start_pos)
    direction = 1.0

    for _ in range(n_rounds):
        for _ in range(ticks_per_round):
            seq += 1
            pos[0] += direction * 1.0 * dt
            if pos[0] > 31.0:
                direction = -1.0
            if pos[0] < 25.0:
                direction = 1.0
            claim = _honest_claim(seq, t, (pos[0], pos[1]), rng)
            for outgoing in injector.apply_to_claims([claim], t, navmesh):
                store.append_remote_claims([outgoing])
            t += dt
        loop.run_pass(t)

    return seq, t


def test_honest_claims_alone_never_drag_reputation_down():
    """Regression test for the false-positive bug: a node walking a
    normal bounded route, with no attack running, must keep a healthy
    reputation — not crash toward r_min from noise/grid-quantization
    alone.
    """
    navmesh = _navmesh()
    store = LocalStore(db_path=":memory:", node_id=1)
    reputation_table = ReputationTable(node_id=1, cfg=ReputationConfig())
    loop = node_app._ReputationLoop(1, store, ReachabilityModel(navmesh, v_max_m_s=1.6), PlausibilityConfig(), reputation_table)
    injector = AttackInjector(node_id=2, attack="none", intensity=0.0, cfg=AttackConfig(), seed=7)

    _run_rounds(loop, store, injector, navmesh, n_rounds=25)

    # Some residual noise/grid-quantization sensitivity remains (STATUS.md
    # Known issues) — this threshold is chosen to clearly separate
    # "healthy" from the r_min=0.05 the pre-fix bug crashed honest nodes
    # to, not to assert a perfect, noise-free 1.0.
    assert reputation_table.local_opinion(2) > 0.6


def test_fabricated_claims_drag_reputation_down_after_attack_starts():
    """The core Moment-4 mechanism: once a node starts fabricating,
    another node's own in-process reputation opinion of it must drop
    noticeably below an honest node's — not stay pinned at full trust.
    """
    navmesh = _navmesh()
    store = LocalStore(db_path=":memory:", node_id=1)
    reputation_table = ReputationTable(node_id=1, cfg=ReputationConfig())
    loop = node_app._ReputationLoop(1, store, ReachabilityModel(navmesh, v_max_m_s=1.6), PlausibilityConfig(), reputation_table)
    injector = AttackInjector(node_id=2, attack="none", intensity=0.0, cfg=AttackConfig(), seed=7)

    # Establish a clean baseline first (matches the real demo flow: the
    # "make node N lie" button is pressed after the node has already been
    # running honestly for a while).
    seq, t = _run_rounds(loop, store, injector, navmesh, n_rounds=15)
    honest_opinion = reputation_table.local_opinion(2)
    assert honest_opinion > 0.6

    injector.set_attack("fabricate", 0.9)
    _run_rounds(loop, store, injector, navmesh, n_rounds=15, start_seq=seq, start_t=t)

    assert reputation_table.local_opinion(2) < honest_opinion - 0.2


def test_reputation_loop_never_evaluates_its_own_nodes_claims():
    navmesh = _navmesh()
    store = LocalStore(db_path=":memory:", node_id=1)
    reputation_table = ReputationTable(node_id=1, cfg=ReputationConfig())
    loop = node_app._ReputationLoop(1, store, None, PlausibilityConfig(), reputation_table)

    store.append_remote_claims([_honest_claim(1, 0.0, (5.0, 5.0), np.random.default_rng(0))])
    own_claim = _honest_claim(1, 0.0, (5.0, 5.0), np.random.default_rng(0))
    own_claim["node_id"] = 1
    own_claim["claim_id"] = "own-1"
    store.append_remote_claims([own_claim])

    loop.run_pass(now_t_media=1.0)

    assert reputation_table.local_opinion(1) == ReputationConfig().r_initial  # never touched


def test_anti_entropy_delta_chunks_stay_under_wire_safety_cap():
    """The fix for the crash (an oversized vv_delta killed a node's gossip
    receive thread): chunk_by_bytes must keep EVERY envelope under
    starling_proto.limits.MAX_MESSAGE_BYTES, at both the sim's 64-d
    embeddings and the video path's 512-d float32 ones."""
    from starling_net.anti_entropy import chunk_by_bytes

    rng = np.random.default_rng(0)
    for dim in (64, 512):
        claim_dict = _honest_claim(1, 0.0, (5.0, 5.0), rng)
        claim_dict["embedding"] = rng.normal(size=dim).astype(np.float32).tobytes()
        claim_dict["signature"] = b"s" * 64
        protos = [record_to_claim_proto(dict(claim_dict, claim_id=str(ULID()), seq=i)) for i in range(60)]
        chunks = chunk_by_bytes(protos)
        assert sum(len(c) for c in chunks) == 60
        assert len(chunks) > 1
        for chunk in chunks:
            envelope = starling_pb2.Envelope(sender_node_id=1, msg_id=b"x" * 16)
            envelope.vv_delta.CopyFrom(starling_pb2.VVDelta(claims=chunk, signature=b"s" * 64))
            assert envelope.ByteSize() <= MAX_MESSAGE_BYTES


def _two_worker_claims(store: LocalStore, injector: AttackInjector, navmesh, n_ticks: int, t0: float, seq0: int, rng):
    """One node watching TWO workers ~10 m apart, their claims interleaved
    tick by tick (what a real zone with two people looks like)."""
    seq, t = seq0, t0
    for k in range(n_ticks):
        for track, base in ((10, (29.0, 5.0)), (11, (29.0, 20.0))):
            seq += 1
            claim = _honest_claim(seq, t, (base[0] + 0.2 * k * 0.2, base[1]), rng)
            claim["local_track_id"] = track
            claim["claim_id"] = f"real2-{seq}"
            for outgoing in injector.apply_to_claims([claim], t, navmesh):
                store.append_remote_claims([outgoing])
        t += 0.2
    return seq, t


def test_two_interleaved_workers_do_not_fail_an_honest_node():
    """Regression: with ONE baseline per source node, claims from two
    simultaneous workers looked like a 10 m teleport every tick and crashed
    an honest node's reputation. Baselines are per (node, track) now."""
    navmesh = _navmesh()
    store = LocalStore(db_path=":memory:", node_id=1)
    table = ReputationTable(node_id=1, cfg=ReputationConfig())
    loop = node_app._ReputationLoop(1, store, ReachabilityModel(navmesh, v_max_m_s=1.6), PlausibilityConfig(), table)
    injector = AttackInjector(node_id=2, attack="none", intensity=0.0, cfg=AttackConfig(), seed=7)
    rng = np.random.default_rng(3)
    seq, t = 0, 0.0
    for _ in range(20):
        seq, t = _two_worker_claims(store, injector, navmesh, 5, t, seq, rng)
        loop.run_pass(t)
    assert table.local_opinion(2) > 0.8
    assert loop.rejected_by_node[2] <= 0.1 * loop.evaluated_by_node[2]


def test_fabrication_is_still_caught_while_two_workers_are_tracked():
    navmesh = _navmesh()
    store = LocalStore(db_path=":memory:", node_id=1)
    table = ReputationTable(node_id=1, cfg=ReputationConfig())
    loop = node_app._ReputationLoop(1, store, ReachabilityModel(navmesh, v_max_m_s=1.6), PlausibilityConfig(), table)
    injector = AttackInjector(node_id=2, attack="none", intensity=0.0, cfg=AttackConfig(), seed=7)
    rng = np.random.default_rng(3)
    seq, t = 0, 0.0
    for _ in range(10):
        seq, t = _two_worker_claims(store, injector, navmesh, 5, t, seq, rng)
        loop.run_pass(t)
    before = table.local_opinion(2)
    injector.set_attack("fabricate", 0.9)
    for _ in range(15):
        seq, t = _two_worker_claims(store, injector, navmesh, 5, t, seq, rng)
        loop.run_pass(t)
    assert table.local_opinion(2) < before - 0.2
    assert loop.rejected_by_node[2] > 10
