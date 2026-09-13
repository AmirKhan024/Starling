"""Tests for starling_eval.scenario / starling_eval.netem_plan (WP-04 Part
4). Tests the PLANNER, not the execution — no Docker required, per this
session's own instruction.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from starling_eval.netem_plan import build_timeline
from starling_eval.scenario import Scenario, load_scenario

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"


@pytest.mark.parametrize("filename", ["healthy.yaml", "east_wing_drop.yaml", "lossy.yaml"])
def test_scenario_yaml_parses(filename):
    scenario = load_scenario(SCENARIOS_DIR / filename)
    assert scenario.nodes == [0, 1, 2, 3]
    assert scenario.duration_s > 0


def test_east_wing_drop_has_partition_then_heal_in_order():
    scenario = load_scenario(SCENARIOS_DIR / "east_wing_drop.yaml")
    assert [e.action for e in scenario.events] == ["partition", "heal"]
    assert scenario.events[0].t < scenario.events[1].t


def test_event_timeline_sorts_by_time_even_if_yaml_is_out_of_order():
    scenario = Scenario.model_validate({
        "name": "unsorted",
        "duration_s": 100,
        "nodes": [0, 1],
        "events": [
            {"t": 50, "action": "heal"},
            {"t": 10, "action": "partition", "groups": [[0], [1]]},
        ],
    })
    assert [e.t for e in scenario.events] == [10, 50]
    assert [e.action for e in scenario.events] == ["partition", "heal"]


def test_unknown_event_kind_raises_a_clear_error():
    with pytest.raises(ValidationError, match="teleport"):
        Scenario.model_validate({
            "name": "bad",
            "duration_s": 10,
            "nodes": [0],
            "events": [{"t": 1, "action": "teleport"}],
        })


def test_partition_timeline_generates_drop_rules_for_every_cross_group_pair():
    scenario = load_scenario(SCENARIOS_DIR / "east_wing_drop.yaml")
    timeline = build_timeline(scenario)

    partition_t, partition_cmds = timeline[0]
    assert partition_t == 120
    flat = [" ".join(cmd) for cmd in partition_cmds]
    assert any("DROP" in c for c in flat)
    # Every command in the partition step must reference the "iptables" tool.
    assert all("iptables" in c for c in flat)
    # Cross-group pairs only: node 0 (group A) talking about node 2 or 3 (group B).
    assert any("172.28.0.12" in c or "172.28.0.13" in c for c in flat)

    heal_t, heal_cmds = timeline[1]
    assert heal_t == 300
    heal_flat = [" ".join(cmd) for cmd in heal_cmds]
    assert any("iptables -F" in c for c in heal_flat)


def test_dry_run_cli_emits_iptables_at_120_and_flush_at_300():
    result = subprocess.run(
        [sys.executable, "deploy/netem/apply.py", str(SCENARIOS_DIR / "east_wing_drop.yaml"), "--dry-run"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    lines = result.stdout.splitlines()
    partition_lines = [line for line in lines if "t=  120.0s" in line]
    heal_lines = [line for line in lines if "t=  300.0s" in line]

    assert partition_lines and all("iptables" in line and "DROP" in line for line in partition_lines)
    assert heal_lines and any("iptables -F" in line for line in heal_lines)
