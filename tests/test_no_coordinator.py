"""Permanent architectural guardrail (CLAUDE.md rules 1 & 2, WP-03).

The decentralized node path must never:
  - import GlobalTracker outside apps/baseline.py (the frozen, deliberately
    centralized control condition)
  - hardcode a reference to another node's db_path pattern
  - instantiate more than one LocalStore per process inside apps/node.py

This file is deliberately dumb (regex/text search, not AST analysis) so it
stays cheap to run on every change and easy to reason about — the point is
to catch an accidental regression toward centralization, not to be a
general-purpose linter.
"""

from __future__ import annotations

import re

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES_DIR = REPO_ROOT / "packages"
NODE_APP = REPO_ROOT / "apps" / "node.py"
BASELINE_APP = REPO_ROOT / "apps" / "baseline.py"

_GLOBALTRACKER_RE = re.compile(r"\bGlobalTracker\b")
_OTHER_NODE_DB_PATH_RE = re.compile(r"""data[/\\]nodes[/\\]node-\d+""")


def _all_py_files() -> list[Path]:
    files = sorted(PACKAGES_DIR.rglob("*.py"))
    if NODE_APP.exists():
        files.append(NODE_APP)
    return files


def test_globaltracker_is_never_referenced_outside_baseline():
    offenders = [str(p) for p in _all_py_files() if _GLOBALTRACKER_RE.search(p.read_text(encoding="utf-8"))]
    assert not offenders, (
        f"GlobalTracker (the centralized coordinator) referenced outside "
        f"apps/baseline.py: {offenders}"
    )
    # Sanity check the guardrail itself isn't vacuous: baseline.py really
    # does define GlobalTracker, so the regex is capable of matching.
    assert _GLOBALTRACKER_RE.search(BASELINE_APP.read_text(encoding="utf-8"))


def test_no_hardcoded_reference_to_another_nodes_db_path():
    offenders = [str(p) for p in _all_py_files() if _OTHER_NODE_DB_PATH_RE.search(p.read_text(encoding="utf-8"))]
    assert not offenders, f"hardcoded node db_path pattern found in: {offenders}"


def test_node_py_instantiates_local_store_at_most_once():
    assert NODE_APP.exists(), "apps/node.py must exist (WP-03 Part 4)"
    text = NODE_APP.read_text(encoding="utf-8")
    count = len(re.findall(r"\bLocalStore\s*\(", text))
    assert count <= 1, f"apps/node.py instantiates LocalStore {count} times — must be at most one per process"
    assert count == 1, "apps/node.py should instantiate exactly one LocalStore"
