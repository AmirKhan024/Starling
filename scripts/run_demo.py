"""scripts/run_demo.py
-----------------------
One-command launcher for the Starling simulator demo. Starts, each as its
own OS process: the simulator, four sim-mode nodes, and the dashboard;
prints the dashboard URL; waits until it answers; and shuts everything down
cleanly on Ctrl+C. Works on Windows and Linux.

    python scripts/run_demo.py                 # opens the dashboard in your browser
    python scripts/run_demo.py --headless      # no browser (CI / automated review)
    python scripts/run_demo.py --speed 2       # simulator at 2x real time

`DemoLauncher` is importable so tests / the review script drive the same
start/stop logic (`kill_node` / `restart_node` for the robustness check).
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

import requests

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from apps.demo_dashboard.config import load_demo_config  # noqa: E402
from apps.demo_dashboard.tokens import issue_demo_tokens  # noqa: E402
from starling_net.keys import generate_keypair  # noqa: E402

NODE_IDS = (0, 1, 2, 3)
SIM_CONFIG = REPO / "configs" / "sim" / "warehouse.yaml"
NODE_CONFIG = REPO / "configs" / "nodes" / "sim" / "node-{:02d}.yaml"
DASHBOARD_CONFIG = REPO / "configs" / "demo_dashboard.yaml"
KEYS_DIR = REPO / "configs" / "keys"
NODE_DB_DIR = REPO / "data" / "nodes" / "sim"
DEFAULT_LOG_DIR = REPO / "data" / "demo" / "logs"
STOP_GRACE_S = 4.0


class DemoLauncher:
    def __init__(self, speed: Optional[float] = None, port: Optional[int] = None, log_dir: Path = DEFAULT_LOG_DIR) -> None:
        self.speed = speed
        self.dash_cfg = load_demo_config(DASHBOARD_CONFIG)
        if port is not None:
            self.dash_cfg.http_port = port
        self.log_dir = log_dir
        self.procs: dict[str, subprocess.Popen] = {}
        self._logs: dict[str, object] = {}
        self.started_wall: Optional[float] = None
        self.exit_status: dict[str, dict] = {}

    @property
    def url(self) -> str:
        return f"http://{self.dash_cfg.http_host}:{self.dash_cfg.http_port}"

    # -- setup ---------------------------------------------------------

    def prepare(self) -> None:
        """Keys if missing, fresh per-node replicas, capability tokens."""
        if not all((KEYS_DIR / f"node-{n:02d}.key").exists() for n in NODE_IDS):
            KEYS_DIR.mkdir(parents=True, exist_ok=True)
            for n in NODE_IDS:
                generate_keypair(n, keys_dir=KEYS_DIR)
            print(f"generated ed25519 keys for nodes {list(NODE_IDS)} in {KEYS_DIR}")
        # A demo starts from empty replicas (stale claims from an earlier run
        # would swamp the first heal); the DBs are generated, gitignored data.
        shutil.rmtree(NODE_DB_DIR, ignore_errors=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for old in self.log_dir.glob("*.log"):
            old.unlink(missing_ok=True)
        issue_demo_tokens(KEYS_DIR, REPO / self.dash_cfg.token_dir)

    # -- processes -----------------------------------------------------

    def _spawn(self, name: str, args: list) -> None:
        log = open(self.log_dir / f"{name}.log", "ab", buffering=0)
        self._logs[name] = log
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO), str(REPO / "packages")]), PYTHONUNBUFFERED="1")
        self.procs[name] = subprocess.Popen(
            [sys.executable, *args], cwd=REPO, stdout=log, stderr=subprocess.STDOUT, env=env, **kwargs
        )

    def _node_args(self, n: int) -> list:
        return [str(REPO / "apps" / "node.py"), "--config", str(Path(str(NODE_CONFIG).format(n)))]

    def start(self) -> None:
        self.started_wall = time.monotonic()
        sim_args = ["-m", "starling_sim.runner", "--config", str(SIM_CONFIG)]
        if self.speed is not None:
            sim_args += ["--speed", str(self.speed)]
        self._spawn("simulator", sim_args)
        for n in NODE_IDS:
            self._spawn(f"node-{n}", self._node_args(n))
        self._spawn(
            "dashboard",
            ["-m", "apps.demo_dashboard.server", "--config", str(DASHBOARD_CONFIG), "--port", str(self.dash_cfg.http_port)],
        )

    def wait_for_dashboard(self, timeout_s: float = 90.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.procs["dashboard"].poll() is not None:
                return False
            try:
                if requests.get(f"{self.url}/api/health", timeout=1).ok:
                    return True
            except requests.RequestException:
                pass
            time.sleep(0.3)
        return False

    def alive(self) -> dict:
        return {n: p.poll() is None for n, p in self.procs.items()}

    def kill_node(self, n: int) -> None:
        """Hard-terminate one node process (not via any dashboard control)."""
        p = self.procs[f"node-{n}"]
        p.kill()
        p.wait(timeout=5)

    def restart_node(self, n: int) -> None:
        old = self._logs.get(f"node-{n}")
        if old:
            old.close()  # type: ignore[attr-defined]
        self._spawn(f"node-{n}", self._node_args(n))

    def _stop_one(self, name: str, p: subprocess.Popen) -> dict:
        was_running = p.poll() is None
        if was_running:
            try:
                if os.name == "nt":
                    p.terminate()
                else:
                    os.killpg(p.pid, signal.SIGINT)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                p.wait(timeout=STOP_GRACE_S)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
        return {"exit_code": p.returncode, "was_running_at_shutdown": was_running}

    def stop(self) -> dict:
        """Stop everything (dashboard first, simulator last) and record each
        process's exit status."""
        order = ["dashboard"] + [f"node-{n}" for n in NODE_IDS] + ["simulator"]
        for name in order:
            if name in self.procs:
                self.exit_status[name] = self._stop_one(name, self.procs[name])
        for f in self._logs.values():
            try:
                f.close()  # type: ignore[attr-defined]
            except Exception:
                pass
        return self.exit_status


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Run the Starling simulator demo (simulator + 4 nodes + dashboard)")
    ap.add_argument("--headless", action="store_true", help="do not open a browser")
    ap.add_argument("--speed", type=float, default=None, help="simulator speed multiplier (1.0 = real time)")
    ap.add_argument("--port", type=int, default=None, help="dashboard HTTP port (default from configs/demo_dashboard.yaml)")
    args = ap.parse_args(argv)

    launcher = DemoLauncher(speed=args.speed, port=args.port)
    launcher.prepare()
    print("starting simulator, 4 nodes and the dashboard ...", flush=True)
    launcher.start()
    try:
        if not launcher.wait_for_dashboard():
            print(f"dashboard did not come up; see logs in {launcher.log_dir}", file=sys.stderr)
            return 1
        print(f"\nStarling dashboard ready: {launcher.url}\n(logs: {launcher.log_dir}; Ctrl+C to stop)\n")
        if not args.headless:
            webbrowser.open(launcher.url)
        reported: set = set()
        while True:
            time.sleep(1.0)
            for name, up in launcher.alive().items():
                if not up and name not in reported:
                    reported.add(name)
                    print(f"warning: {name} exited (code {launcher.procs[name].returncode}); see its log", file=sys.stderr)
            if not launcher.alive()["dashboard"]:
                return 1
    except KeyboardInterrupt:
        print("\nstopping ...")
    finally:
        status = launcher.stop()
        for name, st in status.items():
            print(f"  {name}: exit code {st['exit_code']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
