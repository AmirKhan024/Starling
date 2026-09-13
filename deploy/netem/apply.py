"""deploy/netem/apply.py
--------------------------
Executes a scenario timeline (starling_eval.scenario.Scenario) against
running Docker containers (deploy/docker-compose.yml). All the actual
command PLANNING lives in starling_eval.netem_plan, which is pure and
independently unit-tested (tests/test_scenario.py) without Docker; this
script is the thin, Docker-dependent executor on top of it.

A cleanup handler always runs on exit — including SIGINT — that flushes
every rule this script could have installed, idempotently. A leftover
iptables rule silently ruins every subsequent experiment and is
maddening to debug (STARLING_BUILD_STATE.md §15's own risk table calls
this out), so cleanup is unconditional rather than trusting a clean exit
path.

Usage
-----
    python deploy/netem/apply.py scenarios/east_wing_drop.yaml --dry-run
    python deploy/netem/apply.py scenarios/east_wing_drop.yaml
"""

from __future__ import annotations

import argparse
import atexit
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from starling_eval.netem_plan import build_timeline, plan_heal
from starling_eval.scenario import Scenario, load_scenario


def _print_timeline(timeline: list[tuple[float, list[list[str]]]]) -> None:
    for t, commands in timeline:
        for cmd in commands:
            print(f"t={t:>7.1f}s  {' '.join(cmd)}")


def _run_commands(commands: list[list[str]]) -> None:
    for cmd in commands:
        subprocess.run(cmd, check=False)


def _cleanup(scenario: Scenario) -> None:
    print("[apply] cleanup: flushing all iptables/netem rules", file=sys.stderr)
    _run_commands(plan_heal(scenario.nodes))


def run(scenario: Scenario, dry_run: bool = False) -> None:
    timeline = build_timeline(scenario)

    if dry_run:
        _print_timeline(timeline)
        return

    atexit.register(_cleanup, scenario)

    def _on_sigint(signum, frame) -> None:
        _cleanup(scenario)
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_sigint)

    start = time.monotonic()
    for t, commands in timeline:
        wait_s = t - (time.monotonic() - start)
        if wait_s > 0:
            time.sleep(wait_s)
        _run_commands(commands)

    remaining_s = scenario.duration_s - (time.monotonic() - start)
    if remaining_s > 0:
        time.sleep(remaining_s)


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Apply a Starling partition/degradation scenario to running node containers"
    )
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="print the command timeline, execute nothing")
    args = parser.parse_args(argv)

    scenario = load_scenario(args.scenario)
    run(scenario, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
