"""Tests for starling_consensus.attacks (WP-10 Part 3)."""

from __future__ import annotations

import json
import socket
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from starling_consensus.attacks import AttackInjector, ControlServer, PartitionControl
from starling_consensus.plausibility import CorroboratedState, check
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_net.keys import generate_keypair, load_keys
from starling_node.config import AttackConfig, PlausibilityConfig
from starling_proto.convert import record_to_claim_proto


def _open_navmesh(height: int = 100, width: int = 100, cell_size: float = 0.5) -> NavMesh:
    return NavMesh(grid=np.ones((height, width), dtype=bool), origin=(0.0, 0.0), cell_size=cell_size)


def _real_claim(node_id: int = 0, seq: int = 1, t_media: float = 10.0) -> dict[str, Any]:
    return {
        "claim_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "node_id": node_id,
        "seq": seq,
        "hlc_physical_ms": int(t_media * 1000),
        "hlc_logical": 0,
        "local_track_id": 1,
        "t_media": t_media,
        "embedding": np.zeros(512, dtype=np.float32).tobytes(),
        "embed_scale": 1.0,
        "world_x": 1.0,
        "world_y": 1.0,
        "pos_sigma": 0.3,
        "anchor_type": "UNANCHORED",
        "identity_ref": None,
        "last_anchor_t": None,
        "confidence": 0.9,
        "quality": 0.8,
        "signature": None,
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── none / off ────────────────────────────────────────────────────────────

def test_none_attack_is_a_pure_pass_through():
    injector = AttackInjector(node_id=0, attack="none", intensity=1.0)
    claims = [_real_claim(seq=i) for i in range(5)]
    assert injector.apply_to_claims(claims, t_media=10.0, navmesh=_open_navmesh()) == claims


def test_zero_intensity_is_a_pure_pass_through_regardless_of_attack():
    injector = AttackInjector(node_id=0, attack="fabricate", intensity=0.0)
    claims = [_real_claim(seq=i) for i in range(5)]
    assert injector.apply_to_claims(claims, t_media=10.0, navmesh=_open_navmesh()) == claims


# ── fabricate ────────────────────────────────────────────────────────────

def test_fabricate_at_intensity_1_produces_claims_plausibility_rejects_on_reachability():
    navmesh = _open_navmesh(height=100, width=100, cell_size=0.5)  # 50m x 50m room
    injector = AttackInjector(node_id=0, attack="fabricate", intensity=1.0, seed=1234)

    out = injector.apply_to_claims([], t_media=10.0, navmesh=navmesh)

    assert len(out) == 1
    fabricated = out[0]
    assert fabricated["node_id"] == 0

    geometry = ReachabilityModel(navmesh, v_max_m_s=1.6)
    cfg = PlausibilityConfig()
    # A tiny dt so the reachable radius (v_max*dt + slack) is far smaller
    # than the navmesh's 50x50m extent: only a cell essentially on top of
    # the origin could pass, which a uniformly-sampled free cell over a
    # 10,000-cell room overwhelmingly will not be.
    state = CorroboratedState(last_position=(0.0, 0.0), last_t_media=10.0 - 1e-6)

    result = check(fabricated, state, geometry, cfg)

    assert result.passed is False
    assert "reachability" in result.failures


def test_fabricate_is_a_noop_without_a_navmesh():
    injector = AttackInjector(node_id=0, attack="fabricate", intensity=1.0, seed=1)
    claims = [_real_claim()]
    assert injector.apply_to_claims(claims, t_media=10.0, navmesh=None) == claims


# ── suppress ─────────────────────────────────────────────────────────────

def test_suppress_drops_approximately_the_right_fraction():
    injector = AttackInjector(node_id=0, attack="suppress", intensity=0.5, seed=42)
    claims = [_real_claim(seq=i) for i in range(2000)]

    kept = injector.apply_to_claims(claims, t_media=10.0, navmesh=None)

    kept_fraction = len(kept) / len(claims)
    assert 0.45 < kept_fraction < 0.55


def test_suppress_at_intensity_1_drops_everything():
    injector = AttackInjector(node_id=0, attack="suppress", intensity=1.0, seed=1)
    claims = [_real_claim(seq=i) for i in range(50)]
    assert injector.apply_to_claims(claims, t_media=10.0, navmesh=None) == []


def test_suppress_still_lets_attestations_through_unaltered():
    """The lying-by-omission case: claims vanish, but the attestation
    stream stays exactly as healthy as it would honestly be.
    """
    injector = AttackInjector(node_id=0, attack="suppress", intensity=1.0, seed=1)
    attestation = object()  # duck-typed stand-in; apply_to_attestations never inspects it
    assert injector.apply_to_attestations([attestation]) == [attestation]


# ── replay ───────────────────────────────────────────────────────────────

def test_replay_produces_claims_whose_original_hlc_is_outside_the_freshness_window():
    cfg = AttackConfig(replay_age_s=30.0)
    injector = AttackInjector(node_id=0, attack="replay", intensity=1.0, cfg=cfg, seed=7)
    t_media = 100.0
    claims = [_real_claim(seq=1, t_media=t_media)]

    out = injector.apply_to_claims(claims, t_media=t_media, navmesh=None)

    # The genuine claim passes through unchanged, plus one replayed one.
    assert len(out) == 2
    genuine, replayed = out
    assert genuine["hlc_physical_ms"] == int(t_media * 1000)
    assert replayed["hlc_physical_ms"] == int((t_media - 30.0) * 1000)
    assert replayed["claim_id"] != genuine["claim_id"]

    plausibility_cfg = PlausibilityConfig(replay_window_s=10.0)
    state = CorroboratedState(now_physical_ms=int(t_media * 1000))
    result = check(replayed, state, geometry=None, cfg=plausibility_cfg)
    assert "freshness" in result.failures
    assert result.details["claim_age_s"] == pytest.approx(30.0)


# ── mixed ────────────────────────────────────────────────────────────────

def test_mixed_applies_all_three_attacks():
    navmesh = _open_navmesh()
    injector = AttackInjector(node_id=0, attack="mixed", intensity=1.0, seed=3)
    claims = [_real_claim(seq=1, t_media=10.0)]

    out = injector.apply_to_claims(claims, t_media=10.0, navmesh=navmesh)

    # suppress(1.0) drops the one genuine claim entirely, replay has
    # nothing left to duplicate, fabricate still injects one.
    assert len(out) == 1
    assert out[0]["node_id"] == 0


# ── every injected claim verifies against the node's real key ───────────

def test_injected_claims_verify_against_the_nodes_real_public_key(tmp_path: Path):
    keys_dir = tmp_path / "keys"
    generate_keypair(0, keys_dir=keys_dir)
    keys = load_keys(0, keys_dir=keys_dir)

    navmesh = _open_navmesh()
    # A lower intensity than the "mixed" test above, so suppress does not
    # remove the one genuine claim before replay/fabricate get a chance to
    # add their own — the point here is coverage of every injected shape.
    injector = AttackInjector(node_id=0, attack="mixed", intensity=0.5, seed=5)
    claims = [_real_claim(seq=1, t_media=10.0)]
    out = injector.apply_to_claims(claims, t_media=10.0, navmesh=navmesh)
    assert len(out) >= 1

    for record in out:
        claim_proto = record_to_claim_proto(record)
        # Mirrors starling_net.gossip.GossipNode.publish()'s own signing
        # step exactly — the real transport-level signing path, not
        # something AttackInjector does itself (see module docstring).
        claim_proto.signature = b""
        claim_proto.signature = keys.sign(claim_proto.SerializeToString())

        # Verify exactly as starling_net.gossip._handle_raw does on
        # receipt: clear the signature field, then check against the
        # unsigned bytes.
        check_copy = type(claim_proto)()
        check_copy.CopyFrom(claim_proto)
        check_copy.signature = b""
        assert keys.verify(0, check_copy.SerializeToString(), claim_proto.signature)


# ── control endpoint ──────────────────────────────────────────────────────

def test_control_endpoint_flips_attack_live_and_status_reflects_it():
    injector = AttackInjector(node_id=0, attack="none", intensity=0.0)
    server = ControlServer(injector, port=_free_port())
    server.start()
    try:
        url = f"http://127.0.0.1:{server.port}"

        with urllib.request.urlopen(f"{url}/status", timeout=5) as resp:
            status = json.loads(resp.read())
        assert status == {"node_id": 0, "attack": "none", "intensity": 0.0}

        body = json.dumps({"attack": "fabricate", "intensity": 0.5}).encode("utf-8")
        req = urllib.request.Request(
            f"{url}/attack", data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            posted = json.loads(resp.read())
        assert posted == {"node_id": 0, "attack": "fabricate", "intensity": 0.5}

        assert injector.attack == "fabricate"
        assert injector.intensity == 0.5

        with urllib.request.urlopen(f"{url}/status", timeout=5) as resp:
            status_after = json.loads(resp.read())
        assert status_after == {"node_id": 0, "attack": "fabricate", "intensity": 0.5}
    finally:
        server.stop()


def test_control_server_binds_to_localhost_only():
    injector = AttackInjector(node_id=0)
    server = ControlServer(injector, port=_free_port())
    server.start()  # .stop() calls serve_forever's shutdown(), which only
    # returns once serve_forever is actually running — must start first.
    try:
        assert server._server.server_address[0] == "127.0.0.1"
    finally:
        server.stop()


# ── partition control (STATUS.md Step 4) ───────────────────────────────────

def test_partition_control_defaults_to_nothing_dropped():
    partition = PartitionControl()
    assert partition.status() == {"dropped_node_ids": []}
    assert partition.is_dropped(2) is False


def test_partition_control_set_dropped_then_cleared():
    partition = PartitionControl()
    partition.set_dropped([2, 3])
    assert partition.is_dropped(2) is True
    assert partition.is_dropped(3) is True
    assert partition.is_dropped(0) is False
    assert partition.status() == {"dropped_node_ids": [2, 3]}

    partition.set_dropped([])
    assert partition.is_dropped(2) is False


def test_control_server_without_partition_control_status_is_unchanged():
    """A ControlServer built the pre-Step-4 way (no `partition=`) must keep
    returning exactly injector.status() — backward compatibility for every
    caller that predates PartitionControl.
    """
    injector = AttackInjector(node_id=0, attack="none", intensity=0.0)
    server = ControlServer(injector, port=_free_port())
    server.start()
    try:
        url = f"http://127.0.0.1:{server.port}"
        with urllib.request.urlopen(f"{url}/status", timeout=5) as resp:
            status = json.loads(resp.read())
        assert status == {"node_id": 0, "attack": "none", "intensity": 0.0}
    finally:
        server.stop()


def test_control_server_partition_endpoint_updates_live_and_status_reflects_it():
    injector = AttackInjector(node_id=0)
    partition = PartitionControl()
    server = ControlServer(injector, port=_free_port(), partition=partition)
    server.start()
    try:
        url = f"http://127.0.0.1:{server.port}"

        body = json.dumps({"drop_node_ids": [2, 3]}).encode("utf-8")
        req = urllib.request.Request(
            f"{url}/partition", data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            posted = json.loads(resp.read())
        assert posted["partition"] == {"dropped_node_ids": [2, 3]}
        assert partition.is_dropped(2) is True

        with urllib.request.urlopen(f"{url}/status", timeout=5) as resp:
            status = json.loads(resp.read())
        assert status["partition"] == {"dropped_node_ids": [2, 3]}
    finally:
        server.stop()
