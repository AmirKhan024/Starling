"""Tests for the node config system (WP-00 Part 4a/4b)."""

from pathlib import Path

from starling_node.config import NodeConfig, load_node_config

NODE_CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs" / "nodes"


def test_template_round_trips_through_yaml(tmp_path):
    path = tmp_path / "node-00.yaml"
    NodeConfig.write_template(path, node_id=0)

    cfg = load_node_config(path)

    assert cfg.node_id == 0
    assert cfg.net.listen_port == 5555
    assert cfg.match.threshold_source == "UNCALIBRATED-GUESS"


def test_node_00_loads_with_expected_id():
    cfg = load_node_config(NODE_CONFIGS_DIR / "node-00.yaml")
    assert cfg.node_id == 0


def test_ring_topology_is_symmetric():
    """Node N's neighbours are (N-1)%4 and (N+1)%4 — a ring, not a full mesh.

    CLAUDE.md rule 4: gossip goes to a configured neighbour set, never a
    full mesh. Verify the four generated configs form a symmetric ring:
    if A lists B as a neighbour, B must list A.
    """
    configs = {
        n: load_node_config(NODE_CONFIGS_DIR / f"node-{n:02d}.yaml")
        for n in range(4)
    }
    port_to_node = {cfg.net.listen_port: n for n, cfg in configs.items()}

    def neighbour_node_ids(cfg: NodeConfig) -> set[int]:
        ids = set()
        for addr in cfg.net.neighbours:
            port = int(addr.rsplit(":", 1)[1])
            ids.add(port_to_node[port])
        return ids

    neighbour_sets = {n: neighbour_node_ids(cfg) for n, cfg in configs.items()}

    # Ring, not full mesh: exactly two neighbours each
    for n, neighbours in neighbour_sets.items():
        assert len(neighbours) == 2, f"node {n} is not ring-degree-2: {neighbours}"

    # Symmetric: A lists B iff B lists A
    for a, neighbours_a in neighbour_sets.items():
        for b in neighbours_a:
            assert a in neighbour_sets[b], f"{a} lists {b} but not vice versa"
