"""scripts/evaluate_world_run.py
---------------------------------
Grades a live-world run against ground truth, offline.

The world simulation is deterministic (fixed seed, fixed media-time step),
so the true position of every employee at any media time can be recomputed
by replaying it — as long as the run used no operator events that change
where people go (breaks). Each claim in a node's replica is labelled with
the employee standing nearest its reported position at its media time,
then the resolver is run over the merged claim set exactly as a node does.

Reports:
  * claim localisation error vs the labelled person;
  * claims with no person within reach (false detections);
  * identity purity — for each resolved identity, the share of its claims
    that belong to its majority person (1.0 = never mixes people up);
  * naming accuracy — for identities named by an employee anchor, whether
    the majority person is that employee;
  * fragmentation — how many identities each person was split into.

Usage:
    python scripts/evaluate_world_run.py [--db data/nodes/world/node-00/local.db] [--window 60]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))

import numpy as np  # noqa: E402
from starling_crdt.claims import claim_order_key  # noqa: E402
from starling_crdt.resolver import resolve  # noqa: E402
from starling_geometry.navmesh import NavMesh  # noqa: E402
from starling_geometry.reachability import ReachabilityModel  # noqa: E402
from starling_node.config import load_node_config  # noqa: E402
from starling_world.config import load_world_config  # noqa: E402
from starling_world.sim import WorldSim  # noqa: E402

_LABEL_RADIUS_M = 1.5


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def ordered(self):
        return self._rows


def truth_track(cfg, navmesh, t_end: float) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    sim = WorldSim(cfg, navmesh)
    dt = 1.0 / cfg.sim.tick_hz
    ts, pos = [], defaultdict(list)
    while sim.t < t_end + 1.0:
        sim.tick(dt)
        ts.append(sim.t)
        for w in sim.workers:
            pos[w.emp.id].append((w.m.x, w.m.y) if w.inside else (np.nan, np.nan))
    return np.array(ts), {k: np.array(v) for k, v in pos.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--db", type=Path, default=REPO / "data" / "nodes" / "world" / "node-00" / "local.db"
    )
    ap.add_argument(
        "--node-config", type=Path, default=REPO / "configs" / "nodes" / "world" / "node-00.yaml"
    )
    ap.add_argument("--world", type=Path, default=REPO / "configs" / "world" / "warehouse.yaml")
    ap.add_argument(
        "--window",
        type=float,
        default=60.0,
        help="resolve in windows of this many seconds, like the dashboard (0 = all at once)",
    )
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    cfg = load_world_config(args.world)
    ncfg = load_node_config(args.node_config)
    navmesh = NavMesh.from_geojson(REPO / cfg.floorplan_path, cell_size_m=cfg.navmesh_cell_m)
    con = sqlite3.connect(str(args.db))
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM claims")]
    rows.sort(key=claim_order_key)
    if not rows:
        print("no claims")  # CLI banner
        return 1
    t_end = max(r["t_media"] for r in rows)
    ts, truth = truth_track(cfg, navmesh, t_end)

    label: dict[str, str | None] = {}
    errs = []
    for r in rows:
        if r["world_x"] is None:
            label[r["claim_id"]] = None
            continue
        i = int(np.clip(np.searchsorted(ts, r["t_media"]), 0, len(ts) - 1))
        best, bd = None, _LABEL_RADIUS_M
        for emp, p in truth.items():
            x, y = p[i]
            if np.isnan(x):
                continue
            d = float(np.hypot(x - r["world_x"], y - r["world_y"]))
            if d < bd:
                best, bd = emp, d
        label[r["claim_id"]] = best
        if best is not None:
            errs.append(bd)

    geometry = ReachabilityModel(navmesh)
    windows = (
        [(t_end - 1e9, t_end + 1)]
        if args.window <= 0
        else [
            (s, s + args.window)
            for s in np.arange(min(r["t_media"] for r in rows), t_end, args.window / 2)
        ]
    )
    purity_hits = purity_tot = 0
    named_ok = named_bad = 0
    named_bad_examples = []
    frag = defaultdict(list)
    unassigned = assigned = 0
    for lo, hi in windows:
        win = [r for r in rows if lo <= r["t_media"] < hi]
        if not win:
            continue
        assignment, forks = resolve(_Rows(win), geometry, None, None, ncfg.match)
        per_person = defaultdict(set)
        for ref, cids in assignment.trajectories.items():
            labs = Counter(label[c] for c in cids if label.get(c))
            if not labs:
                continue
            maj, n = labs.most_common(1)[0]
            tot = sum(labs.values())
            purity_hits += n
            purity_tot += tot
            per_person[maj].add(ref)
            if not ref.startswith("AUTO-"):
                if ref == maj:
                    named_ok += 1
                else:
                    named_bad += 1
                    named_bad_examples.append((round(lo), ref, dict(labs)))
        for c, ref in assignment.identity_of.items():
            if ref is None:
                unassigned += 1
            else:
                assigned += 1
        for p, refs in per_person.items():
            frag[p].append(len(refs))

    res = {
        "claims": len(rows),
        "claims_from_node": dict(Counter(r["node_id"] for r in rows)),
        "anchors": dict(
            Counter(r["identity_ref"] for r in rows if r["anchor_type"] == "FACE_ANCHOR")
        ),
        "media_s": round(t_end, 1),
        "false_detections": sum(1 for r in rows if label[r["claim_id"]] is None),
        "localisation_error_m": {
            "median": round(float(np.median(errs)), 3),
            "p90": round(float(np.percentile(errs, 90)), 3),
        },
        "identity_purity": round(purity_hits / max(1, purity_tot), 4),
        "named_windows_correct": named_ok,
        "named_windows_wrong": named_bad,
        "named_wrong_examples": named_bad_examples[:8],
        "identities_per_person_per_window": {
            p: round(float(np.mean(v)), 2) for p, v in frag.items()
        },
        "unassigned_claim_fraction": round(unassigned / max(1, unassigned + assigned), 3),
    }
    print(json.dumps(res, indent=1))  # CLI banner
    if args.json:
        args.json.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
