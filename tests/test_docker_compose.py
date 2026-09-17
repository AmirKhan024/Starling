"""Validate deploy/docker-compose.yml structurally (no Docker required).

`docker compose -f deploy/docker-compose.yml config` is the authoritative
check and was run manually while authoring this file, but CI may not have
Docker available, so this test asserts the same physical-isolation
invariant (CLAUDE.md rule 2) directly from the parsed YAML: every node-NN
service mounts ONLY its own data/nodes/node-NN directory, never another
node's, and never the shared data/nodes/ parent.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

COMPOSE_PATH = Path(__file__).resolve().parent.parent / "deploy" / "docker-compose.yml"

_NODE_DATA_RE = re.compile(r"data[/\\]nodes[/\\]node-(\d+)")


def _load_compose() -> dict:
    with COMPOSE_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_compose_file_parses_as_valid_yaml():
    compose = _load_compose()
    assert "services" in compose
    assert "networks" in compose


def test_all_four_nodes_and_dashboard_are_present():
    compose = _load_compose()
    expected = {"node-00", "node-01", "node-02", "node-03", "dashboard"}
    assert expected <= set(compose["services"].keys())


def test_each_node_mounts_only_its_own_data_directory():
    compose = _load_compose()
    for n in range(4):
        name = f"node-{n:02d}"
        service = compose["services"][name]
        volumes = service.get("volumes", [])

        node_data_mounts = [v for v in volumes if _NODE_DATA_RE.search(v)]
        assert len(node_data_mounts) == 1, (
            f"{name} should mount exactly one data/nodes/node-NN volume, "
            f"found: {node_data_mounts}"
        )

        matched_n = int(_NODE_DATA_RE.search(node_data_mounts[0]).group(1))
        assert matched_n == n, (
            f"{name} mounts node-{matched_n:02d}'s data directory instead of its own"
        )

        # Never the shared parent directory.
        assert not any(
            re.search(r"data[/\\]nodes\s*:", v) or v.strip().startswith("../data/nodes:")
            for v in volumes
        )


def test_dashboard_has_no_node_data_mount():
    compose = _load_compose()
    volumes = compose["services"]["dashboard"].get("volumes", [])
    assert not any(_NODE_DATA_RE.search(v) for v in volumes)


def test_dashboard_has_no_database_mount_or_env():
    """WP-13: the dashboard is a read-only gossip observer, not a database
    reader (CLAUDE.md rule 8) -- it must mount no database directory and
    reference no database path via environment, unlike V1's dashboard.
    """
    compose = _load_compose()
    service = compose["services"]["dashboard"]
    volumes = service.get("volumes", [])
    assert not any("database" in v for v in volumes)
    env = service.get("environment", {}) or {}
    assert not any("DB_PATH" in str(k) or "database" in str(v).lower() for k, v in env.items())


def test_each_node_has_a_distinct_fixed_ip_and_net_admin():
    compose = _load_compose()
    ips = set()
    for n in range(4):
        service = compose["services"][f"node-{n:02d}"]
        assert "NET_ADMIN" in service.get("cap_add", [])
        ip = service["networks"]["starling-net"]["ipv4_address"]
        assert ip not in ips, f"duplicate fixed IP {ip}"
        ips.add(ip)
