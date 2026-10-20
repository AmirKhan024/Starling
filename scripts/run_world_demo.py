"""scripts/run_world_demo.py
-----------------------------
One-command launcher for the LIVE 3D WORLD demo. Starts, each as its own OS
process:

  1. the world server   (apps/world/server.py)  — the virtual warehouse: four
     employees, two AGVs, the simulation clock, the cameras' frame topics;
  2. the camera rig     (apps/world/rig.py)     — a headless browser that
     renders every camera's view (real JPEG frames) for the world server;
  3. four camera nodes  (apps/node.py, source "world") — each receives ONLY
     its own camera's frames and runs real perception on them (person
     detector, tracker, floor homography, appearance signature, employee
     verification), then signs and gossips claims to its ring neighbours;
  4. the dashboard      (apps/demo_dashboard, world mode) — a read-only
     gossip observer with the manager view and the technical view.

First run only: builds the floor plan / calibrations if missing, fetches the
detector weights, and enrolls the employees (scripts/enroll_employees.py).

    python scripts/run_world_demo.py              # opens the 3D world, manager and technical views
    python scripts/run_world_demo.py --headless   # print the URLs only
    python scripts/run_world_demo.py --fast       # lighter detector for slower machines

Ctrl+C stops everything.
"""

from __future__ import annotations

import argparse
import json
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
import yaml

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from starling_net.keys import generate_keypair  # noqa: E402
from starling_world.config import load_world_config  # noqa: E402

from apps.demo_dashboard.config import load_demo_config  # noqa: E402
from apps.demo_dashboard.tokens import issue_demo_tokens  # noqa: E402

NODE_IDS = (0, 1, 2, 3)
WORLD_CONFIG = REPO / "configs" / "world" / "warehouse.yaml"
NODE_CONFIG = REPO / "configs" / "nodes" / "world" / "node-{:02d}.yaml"
DASHBOARD_CONFIG = REPO / "configs" / "world" / "dashboard.yaml"
REGISTRY = REPO / "data" / "world" / "employee_registry.json"
KEYS_DIR = REPO / "configs" / "keys"
NODE_DB_DIR = REPO / "data" / "nodes" / "world"
RUN_DIR = REPO / "data" / "demo" / "world"
LOG_DIR = RUN_DIR / "logs"
STOP_GRACE_S = 5.0
FAST_DETECTOR = "yolo11n.pt"
CENTRAL_PORT = 7010
# Processes the operator may power off and on from the dashboard: their exit
# is part of the demo, not a reason to stop everything.
RESTARTABLE = ("node-", "central")
MANIFEST = RUN_DIR / "launch.json"
# Below this much free memory at start, warn: four camera nodes need ~0.5 GB of
# working memory each plus torch's own, and paging collapses their frame rate.
LOW_MEMORY_WARN_GB = 4.0
# --light: cameras deliver this many frames per second instead of the world
# config's. A camera node that cannot keep up drops frames, its detector-health
# score falls, it stops vouching for its area (C4) and can miss the few seconds
# someone spends at the gate; at a rate the machine sustains, none of that happens.
LIGHT_FPS = 2.0


class WorldDemoLauncher:
    def __init__(
        self,
        speed: Optional[float] = None,
        detector: Optional[str] = None,
        software_gl: bool = False,
        fps: Optional[float] = None,
    ) -> None:
        self.speed = speed
        self.detector = detector
        self.software_gl = software_gl
        self.fps = fps
        self.world_cfg = load_world_config(WORLD_CONFIG)
        self.dash_cfg = load_demo_config(DASHBOARD_CONFIG)
        self.procs: dict[str, subprocess.Popen] = {}
        self._logs: dict[str, object] = {}

    @property
    def world_url(self) -> str:
        e = self.world_cfg.endpoints
        return f"http://{e.http_host}:{e.http_port}"

    @property
    def dash_url(self) -> str:
        return f"http://{self.dash_cfg.http_host}:{self.dash_cfg.http_port}"

    # -- setup ---------------------------------------------------------------

    def _run_step(self, what: str, args: list[str]) -> None:
        print(f"  {what} …", flush=True)  # CLI banner
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO), str(REPO / "packages")]))
        subprocess.run([sys.executable, *args], cwd=REPO, env=env, check=True)

    def node_config_path(self, n: int) -> Path:
        """The committed node config, or — with a detector or frame-rate
        override — a copy of it under data/demo/world/ that changes only that."""
        src = Path(str(NODE_CONFIG).format(n))
        if not self.detector and not self.fps:
            return src
        data = yaml.safe_load(src.read_text(encoding="utf-8"))
        if self.detector:
            data["perception"]["yolo_model"] = self.detector
        if self.fps:
            data["world"]["fps"] = self.fps
        out = RUN_DIR / "nodes" / src.name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return out

    def world_config_path(self) -> Path:
        """The world config, or a copy whose cameras deliver `fps` frames/s."""
        if not self.fps:
            return WORLD_CONFIG
        data = yaml.safe_load(WORLD_CONFIG.read_text(encoding="utf-8"))
        data["camera_frames"]["fps"] = self.fps
        out = RUN_DIR / "warehouse.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return out

    def prepare(self) -> None:
        print("Preparing the live world demo:")  # CLI banner
        try:
            import psutil

            free_gb = psutil.virtual_memory().available / 2**30
            if free_gb < LOW_MEMORY_WARN_GB and not self.fps:
                print(
                    f"  WARNING: only {free_gb:.1f} GB of memory is free. The four camera nodes need about "
                    f"{LOW_MEMORY_WARN_GB:.0f} GB; with less, Windows pages them out, every camera's frame "
                    "rate collapses and people can be missed at the gate. Close other apps (browsers, editors) "
                    "or run with --fast.",
                    flush=True,
                )  # CLI banner
        except ImportError:
            pass
        if not (REPO / self.world_cfg.floorplan_path).exists() or not all(
            (REPO / "configs" / "calib" / "world" / f"node-{n:02d}.yaml").exists() for n in NODE_IDS
        ):
            self._run_step(
                "building the floor plan, camera zones and calibrations",
                ["scripts/build_world_floorplan.py", "--no-png"],
            )
        if not all((KEYS_DIR / f"node-{n:02d}.key").exists() for n in NODE_IDS):
            KEYS_DIR.mkdir(parents=True, exist_ok=True)
            for n in NODE_IDS:
                generate_keypair(n, keys_dir=KEYS_DIR)
            print(f"  generated ed25519 keys for nodes {list(NODE_IDS)}")  # CLI banner
        detectors = {
            yaml.safe_load(self.node_config_path(n).read_text(encoding="utf-8"))["perception"][
                "yolo_model"
            ]
            for n in NODE_IDS
        }
        for d in sorted(detectors):
            if not (REPO / d).exists():
                print(f"  fetching detector weights {d} …", flush=True)  # CLI banner
                from ultralytics import YOLO

                YOLO(d)  # ultralytics downloads into the working directory
        if not REGISTRY.exists():
            self._run_step(
                "enrolling the employees (rendering onboarding views)",
                ["scripts/enroll_employees.py"],
            )
        # Fresh replicas every run: stale claims from an earlier run would
        # belong to a different day's world.
        shutil.rmtree(NODE_DB_DIR, ignore_errors=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        for old in LOG_DIR.glob("*.log"):
            old.unlink(missing_ok=True)
        issue_demo_tokens(KEYS_DIR, REPO / self.dash_cfg.token_dir)

    # -- processes ---------------------------------------------------------------

    def _spawn(self, name: str, args: list[str]) -> None:
        log = open(LOG_DIR / f"{name}.log", "ab", buffering=0)
        self._logs[name] = log
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        env = dict(
            os.environ,
            PYTHONPATH=os.pathsep.join([str(REPO), str(REPO / "packages")]),
            PYTHONUNBUFFERED="1",
        )
        # numpy's OpenBLAS would otherwise reserve a buffer per CPU core in every
        # process (~740 MB each, unused): see apps/node.py.
        env.setdefault("OPENBLAS_NUM_THREADS", "1")
        self.procs[name] = subprocess.Popen(
            [sys.executable, *args],
            cwd=REPO,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            **kwargs,
        )

    def _wait(self, what: str, url: str, timeout_s: float, check=lambda r: r.ok) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_s:
            try:
                r = requests.get(url, timeout=1.0)
                if check(r):
                    return True
            except Exception:
                pass
            dead = [n for n, p in self.procs.items() if p.poll() is not None]
            if dead:
                raise RuntimeError(
                    f"{', '.join(dead)} exited while waiting for {what} — see {LOG_DIR}"
                )
            time.sleep(0.5)
        return False

    def start(self) -> None:
        world_args = ["-m", "apps.world.server", "--config", str(self.world_config_path()), "--hold"]
        if self.speed is not None:
            world_args += ["--speed", str(self.speed)]
        self._spawn("world", world_args)
        if not self._wait("the world server", self.world_url + "/api/health", 30):
            raise RuntimeError("world server did not start")
        rig_args = ["-m", "apps.world.rig", "--url", self.world_url] + (
            ["--software"] if self.software_gl else []
        )
        self._spawn("rig", rig_args)
        if not self._wait(
            "the camera rig",
            self.world_url + "/api/status",
            60,
            check=lambda r: r.ok and r.json()["rig"]["connected"],
        ):
            raise RuntimeError("camera rig did not connect")
        # The centralised comparison (NOT Starling): ingests every camera's video.
        central_args = ["-m", "apps.world.central_ingest", "--config", str(WORLD_CONFIG), "--port", str(CENTRAL_PORT)]
        self._spawn("central", central_args)
        manifest: dict = {"central": central_args, "nodes": {}}
        # Nodes start one after another, each once the previous one's detector
        # is loaded: four simultaneous torch imports spike memory and CPU.
        for n in NODE_IDS:
            node_args = ["apps/node.py", "--config", str(self.node_config_path(n))]
            manifest["nodes"][str(n)] = node_args
            MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
            self._spawn(f"node-{n:02d}", node_args)
            port = 5555 + n + self.dash_cfg.control_port_offset
            if not self._wait(
                f"node {n}",
                f"http://127.0.0.1:{port}/perception",
                180,
                check=lambda r: r.ok and "node_id" in r.json(),
            ):
                raise RuntimeError(f"node {n} did not come up")
            print(f"  node {n} ready", flush=True)  # CLI banner
        self._spawn(
            "dashboard", ["-m", "apps.demo_dashboard.server", "--config", str(DASHBOARD_CONFIG)]
        )
        if not self._wait("the dashboard", self.dash_url + "/api/health", 60):
            raise RuntimeError("dashboard did not start")
        # Only now does the shift start: nobody arrives before every camera is watching.
        requests.post(self.world_url + "/api/control/start", json={}, timeout=3)

    def stop(self) -> None:
        for name in reversed(list(self.procs)):
            p = self.procs[name]
            if p.poll() is not None:
                continue
            try:
                if os.name == "nt":
                    p.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    p.send_signal(signal.SIGINT)
            except Exception:
                pass
        deadline = time.monotonic() + STOP_GRACE_S
        for p in self.procs.values():
            try:
                p.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                p.kill()
        for log in self._logs.values():
            log.close()


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Starling live 3D world demo")
    ap.add_argument("--headless", action="store_true", help="do not open a browser")
    ap.add_argument(
        "--speed", type=float, default=None, help="world clock speed multiplier (default 1.0)"
    )
    ap.add_argument(
        "--fast",
        action="store_true",
        help=f"use the lighter {FAST_DETECTOR} detector (slower machines)",
    )
    ap.add_argument("--detector", default=None, help="override every node's detector weights")
    ap.add_argument("--software-gl", action="store_true", help="render the cameras without a GPU")
    ap.add_argument(
        "--light",
        action="store_true",
        help=f"cameras at {LIGHT_FPS:g} frames/s: for a crowded laptop (chosen automatically when memory is low)",
    )
    ap.add_argument("--full", action="store_true", help="never switch to --light automatically")
    args = ap.parse_args(argv)

    light = args.light
    if not light and not args.full:
        try:
            import psutil

            free_gb = psutil.virtual_memory().available / 2**30
            if free_gb < LOW_MEMORY_WARN_GB:
                light = True
                print(
                    f"Only {free_gb:.1f} GB of memory is free: starting in --light mode (cameras at "
                    f"{LIGHT_FPS:g} frames/s) so every camera keeps up. Use --full to override.",
                    flush=True,
                )  # CLI banner
        except ImportError:
            pass
    launcher = WorldDemoLauncher(
        args.speed,
        args.detector or (FAST_DETECTOR if args.fast else None),
        args.software_gl,
        fps=LIGHT_FPS if light else None,
    )
    launcher.prepare()
    print(
        "Starting the world, the camera rig, four camera nodes and the dashboard …", flush=True
    )  # CLI banner
    try:
        launcher.start()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)  # CLI banner
        launcher.stop()
        return 1
    print(
        f"""
  Present (start here) : {launcher.dash_url}/tour
  Live monitor         : {launcher.dash_url}/
  Inside the system    : {launcher.dash_url}/inside
  What if              : {launcher.dash_url}/compare
  How it works         : {launcher.dash_url}/how
  3D warehouse         : {launcher.world_url}
  Engineer view        : {launcher.dash_url}/engineer
  Logs                 : {LOG_DIR}

The shift starts now: the four employees arrive one by one and are verified
at the entrance gate. Press Ctrl+C to stop everything.
""",
        flush=True,
    )  # CLI banner
    if not args.headless:
        # One tab: the presentation embeds the other pages (and the 3D world) itself.
        webbrowser.open(launcher.dash_url + "/tour")
    try:
        while True:
            time.sleep(1.0)
            dead = [
                n for n, p in launcher.procs.items()
                if p.poll() is not None and not n.startswith(RESTARTABLE)
            ]
            if dead:
                print(f"process(es) exited: {dead} — see {LOG_DIR}", file=sys.stderr)  # CLI banner
                break
    except KeyboardInterrupt:
        pass
    finally:
        print("stopping …", flush=True)  # CLI banner
        launcher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
