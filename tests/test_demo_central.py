"""Headless end-to-end test of the side-by-side centralised comparison (Part C).

The central server (apps/central_server_sim.py) is deliberately centralised and
is NOT part of Starling. Checks: under a partition the central system loses the
cut-off cameras' workers while Starling keeps tracking all of them; with the
central server process killed, Starling nodes keep producing and merging claims;
a restarted central server tracks again.
Run with:  python -m pytest -m integration tests/test_demo_central.py
"""

from __future__ import annotations

import time

import pytest
import requests

from scripts.run_demo import DemoLauncher

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    launcher = DemoLauncher(log_dir=tmp_path_factory.mktemp("central_logs"), auto=False)
    launcher.prepare()
    launcher.start()
    try:
        assert launcher.wait_for_dashboard()
        yield launcher
    finally:
        launcher.stop()


def _state(demo):
    s = requests.get(f"{demo.url}/api/state", timeout=3).json()
    return s if s.get("ready") else {}


def _wait(demo, cond, timeout_s, what):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = _state(demo)
        if last and cond(last):
            return last
        time.sleep(0.7)
    raise AssertionError(f"timed out waiting for {what}: {last and last.get('central')}")


def test_partition_loses_the_cut_off_side_for_central_but_not_for_starling(demo):
    _wait(demo, lambda s: s["central"]["status"] == "HEALTHY" and s["central"]["tracked_now"] >= 4, 60, "central healthy, 4 tracked")
    assert requests.post(f"{demo.url}/api/partition", timeout=5).json()["ok"]
    s = _wait(demo, lambda s: s["central"]["status"] == "PARTIAL" and s["central"]["tracked_now"] <= 2, 30, "central PARTIAL, cut side lost")
    assert s["central"]["cut_cameras"] == [2, 3]
    assert s["central"]["starling_tracked_now"] >= 4  # both halves of Starling keep tracking
    requests.post(f"{demo.url}/api/heal", timeout=5)
    _wait(demo, lambda s: s["central"]["status"] == "HEALTHY" and s["central"]["tracked_now"] >= 4, 30, "central back to 4 after heal")


def test_killing_the_central_server_does_not_affect_starling(demo):
    before = _state(demo)
    demo.kill_central()
    s = _wait(demo, lambda s: s["central"]["status"] == "DOWN", 15, "central DOWN")
    assert s["central"]["tracked_now"] == 0
    claims0 = s["claims_total"]
    time.sleep(6)
    s = _state(demo)
    assert s["nodes_live"] == before["nodes_live"] == 4
    assert s["claims_total"] > claims0 + 20, "Starling stopped producing/merging claims without the central server"
    assert s["convergence"]["holes_total"] == 0
    assert s["central"]["starling_tracked_now"] >= 4


def test_restarted_central_server_tracks_again_from_empty_state(demo):
    assert requests.post(f"{demo.url}/api/central/restart", timeout=5).json()["ok"]
    s = _wait(demo, lambda s: s["central"]["status"] == "HEALTHY" and s["central"]["tracked_now"] >= 4, 40, "central tracking again")
    assert s["central"]["identities_total"] >= 4
