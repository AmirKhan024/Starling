"""Headless end-to-end test of the two scripted identity conflicts (Part B):
the real simulator, four node processes and the real resolver.

  * "ambiguous": both twin trajectories are physically possible -> after the
    network heals, ONE fork appears and STAYS OPEN with two branches far apart;
  * "resolvable": one branch is physically impossible -> after healing the fork
    appears and is RESOLVED by reachability, naming the impossible speed.

While partitioned there must be NO fork (the two halves have not merged yet).
Run with:  python -m pytest -m integration tests/test_demo_conflicts.py
"""

from __future__ import annotations

import time

import pytest
import requests

from scripts.run_demo import DemoLauncher

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    launcher = DemoLauncher(log_dir=tmp_path_factory.mktemp("conflict_logs"), auto=False)
    launcher.prepare()
    launcher.start()
    try:
        assert launcher.wait_for_dashboard(), "dashboard never came up"
        yield launcher
    finally:
        launcher.stop()


def _state(demo):
    s = requests.get(f"{demo.url}/api/state", timeout=3).json()
    return s if s.get("ready") else {}


def _run(demo, variant, timeout_s=90):
    requests.post(f"{demo.url}/api/reset", timeout=10)
    time.sleep(2)
    assert requests.post(f"{demo.url}/api/conflict", json={"variant": variant}, timeout=5).json()["ok"]
    saw_fork_while_partitioned = False
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        s = _state(demo)
        if s:
            phase = s["conflict"].get("phase")
            if phase == "partitioned" and s["forks"]:
                saw_fork_while_partitioned = True
            if phase == "healed" and s["forks"]:
                return s, saw_fork_while_partitioned
        time.sleep(1.0)
    raise AssertionError(f"no fork appeared after healing ({variant})")


def test_ambiguous_conflict_opens_a_fork_that_stays_open(demo):
    s, early = _run(demo, "ambiguous")
    assert not early, "a fork appeared before the partition healed"
    fork = s["forks"][0]
    assert fork["status"] == "OPEN"
    assert len(fork["branches"]) == 2
    b0, b1 = fork["branches"]
    assert abs(b0["x"] - b1["x"]) > 20.0  # the two candidate positions are on opposite sides of the warehouse
    time.sleep(6)  # still open a few seconds later: never resolved by score
    assert _state(demo)["forks_open"] >= 1
    assert "does NOT pick one" in fork["explanation"]


def test_resolvable_conflict_is_resolved_by_reachability_with_a_reason(demo):
    s, early = _run(demo, "resolvable")
    assert not early
    fork = s["forks"][0]
    assert fork["status"] == "RESOLVED_REACHABILITY"
    assert "exceeds v_max" in fork["reason"] and "m/s" in fork["reason"]
    assert fork["resolved_branch"] == 0  # the twin who really was near the gate is kept
