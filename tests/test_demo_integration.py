"""Headless end-to-end test of the whole demo (STATUS.md Step 6): the real
launcher starts the simulator, four sim-mode node processes and the
dashboard, and everything is observed through the dashboard's API (which
itself only knows what it heard over gossip).

Checks the three properties the demo stands on:
  1. claims flow and all four nodes are live;
  2. partition then heal ends with gap-free, equal-size replicas;
  3. a lying node's reputation, as reported by its peers, drops while the
     honest nodes stay trusted.

Marked `@pytest.mark.integration`: real subprocesses and sockets, about a
minute. Run with:  python -m pytest -m integration tests/test_demo_integration.py
"""

from __future__ import annotations

import time
from typing import Any, Callable

import pytest
import requests

from scripts.run_demo import DemoLauncher

pytestmark = pytest.mark.integration


def _wait(cond: Callable[[], Any], timeout_s: float, what: str, every_s: float = 0.5) -> Any:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            last = cond()
        except requests.RequestException:
            last = None
        if last:
            return last
        time.sleep(every_s)
    raise AssertionError(f"timed out after {timeout_s}s waiting for: {what} (last={last!r})")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    launcher = DemoLauncher(log_dir=tmp_path_factory.mktemp("demo_logs"))
    launcher.prepare()
    launcher.start()
    try:
        assert launcher.wait_for_dashboard(), "dashboard never came up"
        yield launcher
    finally:
        status = launcher.stop()
        crashed = {n: s for n, s in status.items() if not s["was_running_at_shutdown"]}
        assert not crashed, f"processes had already died before shutdown: {crashed}"


def _state(demo: DemoLauncher) -> dict:
    s = requests.get(f"{demo.url}/api/state", timeout=3).json()
    return s if s.get("ready") else {}


def test_claims_flow_and_all_nodes_live(demo):
    s = _wait(lambda: (lambda st: st if st and st["nodes_live"] == 4 and st["claims_total"] > 100 else None)(_state(demo)),
              60, "4 live nodes and >100 claims heard")
    assert all(n["claims"] and n["claims"] > 0 for n in s["nodes"])
    assert s["identities"], "no identities resolved from gossiped claims"


def test_partition_then_heal_ends_gap_free_and_equal(demo):
    assert requests.post(f"{demo.url}/api/partition", timeout=5).json()["ok"]
    _wait(lambda: all(n["partitioned"] for n in _state(demo)["nodes"]), 15, "every node reports partitioned")
    time.sleep(6)  # let the two sides diverge
    assert requests.post(f"{demo.url}/api/heal", timeout=5).json()["ok"]
    s = _wait(lambda: (lambda st: st if st and st["convergence"]["converged"] else None)(_state(demo)),
              30, "converged after heal (no gaps, equal claim counts)")
    assert s["convergence"]["holes_total"] == 0
    assert s["convergence"]["spread"] <= s["convergence"]["tolerance"]
    assert not any(n["partitioned"] for n in s["nodes"])


def test_lying_node_reputation_drops_as_seen_by_honest_peers(demo):
    honest_before = {n["id"]: n["reputation"] for n in _state(demo)["nodes"]}
    assert requests.post(f"{demo.url}/api/lie", json={"node_id": 2}, timeout=5).json()["ok"]

    def dropped():
        st = _state(demo)
        liar = next(n for n in st["nodes"] if n["id"] == 2)
        return st if liar["reputation"] is not None and liar["reputation"] < 0.7 else None

    s = _wait(dropped, 60, "node 2's peer-reported reputation below 0.7")
    liar = next(n for n in s["nodes"] if n["id"] == 2)
    assert liar["lying"] and liar["rejected"] > 0
    for n in s["nodes"]:
        if n["id"] != 2:
            assert n["reputation"] is None or n["reputation"] > 0.8, f"honest node {n['id']} lost trust: {n}"
    assert honest_before[2] is None or honest_before[2] > 0.8
    requests.post(f"{demo.url}/api/stop_lie", json={}, timeout=5)
