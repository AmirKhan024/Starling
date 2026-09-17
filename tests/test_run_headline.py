"""Tests for scripts/run_headline.py (WP-14 Part 4). This session verifies
the script with --dry-run only -- these tests match that scope: they
never invoke apps/baseline.py, --local, or docker compose.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_headline import ARM_DESCRIPTIONS, main, planned_arms  # noqa: E402

from starling_eval.scenario import load_scenario


def test_headline_scenario_parses_with_partition_and_lie_events():
    scenario = load_scenario(Path("scenarios/headline.yaml"))
    assert scenario.name == "headline"
    actions = [e.action for e in scenario.events]
    assert actions == ["partition", "lie", "heal"]
    lie_event = scenario.events[1]
    assert lie_event.node == 2
    assert lie_event.attack == "fabricate"
    assert lie_event.intensity == 0.4


def test_planned_arms_lists_all_three_arms_at_every_repeat_count():
    for repeat in (1, 5):
        plan = planned_arms(repeat)
        assert len(plan) == 3 * repeat
        arms_seen = {arm for arm, _, _ in plan}
        assert arms_seen == set(ARM_DESCRIPTIONS)


def test_dry_run_executes_nothing_and_lists_all_three_arms(capsys):
    main(["--dry-run", "--repeat", "5"])
    out = capsys.readouterr().out
    for description in ARM_DESCRIPTIONS.values():
        assert description in out
    assert "15 planned runs total" in out
