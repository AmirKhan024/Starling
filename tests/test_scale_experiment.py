"""Tests for the scalability experiment (scripts/run_scale_experiment.py,
apps/bench_node.py).

The topology builder and the latency maths are pure and tested directly.
`test_n4_replicas_converge` is marked integration: it spawns four real
bench-node OS processes on real sockets for a few seconds.
"""

from __future__ import annotations

import itertools
import json
import socket
from pathlib import Path

import pytest

from scripts.run_scale_experiment import (
    ExperimentConfig,
    build_topology,
    circulant,
    diameter,
    is_connected,
    percentile,
    propagation,
    run_scaling,
)


@pytest.mark.parametrize("n", [6, 7, 8, 12, 16, 24, 32, 48, 64])
def test_topology_degree_four_connected_not_full_mesh(n: int) -> None:
    adj, offsets = build_topology(n, degree=4)
    assert len(offsets) == 2 and offsets[0] == 1
    assert all(len(v) == 4 for v in adj.values())
    assert all(i not in v for i, v in adj.items())
    assert all(i in adj[j] for i, v in adj.items() for j in v)  # symmetric
    assert is_connected(adj)
    assert any(len(v) < n - 1 for v in adj.values())  # never a full mesh for N > 5


@pytest.mark.parametrize("n", [3, 4, 5])
def test_small_n_uses_ring(n: int) -> None:
    adj, offsets = build_topology(n, degree=4)
    assert offsets == [1]
    assert adj == circulant(n, [1])
    if n == 4:
        assert adj[0] == [1, 3] and diameter(adj) == 2


def test_chord_choice_minimises_diameter() -> None:
    adj, _offsets = build_topology(16, degree=4)
    best = min(diameter(circulant(16, [1, k])) for k in range(2, 8))
    assert diameter(adj) == best
    assert diameter(adj) < diameter(circulant(16, [1]))  # chords beat the plain ring (8)


def test_diameter_known_graphs() -> None:
    assert diameter(circulant(10, [1])) == 5
    path = {0: [1], 1: [0, 2], 2: [1, 3], 3: [2]}
    assert diameter(path) == 3
    with pytest.raises(ValueError):
        diameter({0: [1], 1: [0], 2: [3], 3: [2]})
    assert not is_connected({0: [1], 1: [0], 2: []})


def test_config_rejects_odd_degree() -> None:
    with pytest.raises(ValueError):
        ExperimentConfig(degree=3)


def test_percentile_and_propagation() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)
    assert percentile([5.0], 95) == 5.0
    seen = {
        0: {"a": (0, 10.0), "b": (1, 10.6)},
        1: {"a": (0, 10.2), "b": (1, 10.5)},
        2: {"a": (0, 10.9)},  # never got "b"
    }
    p = propagation(seen)
    assert p["latencies_s"] == [pytest.approx(0.9)]
    assert p["missing"] == 1


def _free_block(size: int, start: int = 7300, stop: int = 7590) -> int:
    for base in range(start, stop - size):
        ok = True
        for port in range(base, base + size):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                except OSError:
                    ok = False
                    break
        if ok:
            return base
    pytest.skip("no free port block")


@pytest.mark.integration
def test_n4_replicas_converge(tmp_path: Path) -> None:
    cfg = ExperimentConfig(ns=[4], warmup_s=2.0, produce_s=4.0, settle_timeout_s=30.0, ready_timeout_s=60.0)
    run_dir = tmp_path / "n004"
    result = run_scaling(cfg, 4, run_dir, _free_block(4))
    assert result["replicas_identical"] is True
    assert result["claims_missing_somewhere"] == 0
    assert result["claims_total"] > 0
    assert result["per_node_bytes_in_per_s"]["mean"] > 0
    assert result["latency_ms"]["p50"] > 0
    assert result["diameter"] == 2
    for i in range(4):
        stats = json.loads((run_dir / f"node-{i:02d}.stats.json").read_text(encoding="utf-8"))
        assert stats["final"] is True and stats["gossip"]
        seen = json.loads((run_dir / f"node-{i:02d}.seen.json").read_text(encoding="utf-8"))
        assert len(seen["first_seen"]) == result["claims_total"]
    # every node only ever listened to its two ring neighbours
    cfgs = [json.loads((run_dir / f"node-{i:02d}.json").read_text(encoding="utf-8")) for i in range(4)]
    for a, b in itertools.combinations(range(4), 2):
        linked = any(str(cfgs[b]["listen_port"]) in x for x in cfgs[a]["neighbours"])
        assert linked == ((b - a) % 4 in (1, 3))
