"""starling_eval/metrics.py
----------------------------
Fixes D-11: `eval/metrics.py` has been documented in the V1 README since
the beginning and has never existed. No metric has ever been computed from
this codebase before this module.

Every function here takes plain data structures (dicts, lists, arrays,
file paths) rather than live objects, so metrics can be computed offline
from logs — a scenario run's structlog output, a gossip stats dict, a
claim log — without needing a running node or store.

Tracking metrics delegate to TrackEval rather than hand-rolling HOTA
(CLAUDE.md / STARLING_BUILD_STATE.md §12 rule 7 — hand-rolled HOTA is a
week of subtle bugs).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union

import numpy as np

_MISSING = object()


# ── Tracking (TrackEval) ─────────────────────────────────────────────────────

def evaluate_tracking(gt_path: Union[str, Path], pred_path: Union[str, Path]) -> dict:
    """IDF1, MOTA, HOTA, IDSW for one sequence, via TrackEval.

    `gt_path`/`pred_path` are plain MOTChallenge-format text files for a
    single sequence: `frame,id,bb_left,bb_top,bb_width,bb_height,conf,
    class,visibility` for gt (class=1 is pedestrian, conf here is MOT's
    "zero_marked" keep/ignore flag), `frame,id,bb_left,bb_top,bb_width,
    bb_height,conf` for predictions.
    """
    import trackeval

    gt_path = Path(gt_path)
    pred_path = Path(pred_path)
    seq_name = "seq01"
    tracker_name = "starling"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gt_dir = tmp / "gt" / seq_name / "gt"
        gt_dir.mkdir(parents=True)
        (gt_dir / "gt.txt").write_text(gt_path.read_text(encoding="utf-8"), encoding="utf-8")

        pred_dir = tmp / "trackers" / tracker_name / "data"
        pred_dir.mkdir(parents=True)
        (pred_dir / f"{seq_name}.txt").write_text(pred_path.read_text(encoding="utf-8"), encoding="utf-8")

        seq_length = _infer_mot_seq_length(gt_path, pred_path)

        dataset = trackeval.datasets.MotChallenge2DBox({
            "GT_FOLDER": str(tmp / "gt"),
            "TRACKERS_FOLDER": str(tmp / "trackers"),
            "SEQ_INFO": {seq_name: seq_length},
            "SKIP_SPLIT_FOL": True,
            "TRACKERS_TO_EVAL": [tracker_name],
            "CLASSES_TO_EVAL": ["pedestrian"],
            "PRINT_CONFIG": False,
        })

        eval_config = trackeval.Evaluator.get_default_eval_config()
        eval_config.update({
            "PRINT_RESULTS": False, "PRINT_CONFIG": False, "DISPLAY_LESS_PROGRESS": True,
            "OUTPUT_SUMMARY": False, "OUTPUT_DETAILED": False, "OUTPUT_EMPTY_CLASSES": False,
            "TIME_PROGRESS": False, "USE_PARALLEL": False,
        })
        evaluator = trackeval.Evaluator(eval_config)

        metric_cfg = {"PRINT_CONFIG": False}
        metrics_list = [
            trackeval.metrics.HOTA(metric_cfg),
            trackeval.metrics.CLEAR(metric_cfg),
            trackeval.metrics.Identity(metric_cfg),
        ]
        results, _ = evaluator.evaluate([dataset], metrics_list)

        seq_results = results["MotChallenge2DBox"][tracker_name][seq_name]["pedestrian"]
        hota = seq_results["HOTA"]
        clear = seq_results["CLEAR"]
        identity = seq_results["Identity"]

        return {
            "HOTA": float(np.mean(hota["HOTA"])),
            "MOTA": float(clear["MOTA"]),
            "IDF1": float(identity["IDF1"]),
            "IDSW": int(clear["IDSW"]),
        }


def _infer_mot_seq_length(*paths: Path) -> int:
    max_frame = 0
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            max_frame = max(max_frame, int(line.split(",")[0]))
    return max_frame


# ── C1: CRDT identity ─────────────────────────────────────────────────────────

def identity_consistency_after_merge(replica_states: list[dict]) -> float:
    """Fraction of keys where every replica's assignment agrees, after a
    merge. STARLING_BUILD_STATE.md §4.2's core guarantee ("same claim set
    -> same assignment") means this should be 1.0 once every replica has
    actually converged to the same claim set; anything less is either a
    convergence bug or the replicas haven't finished merging yet.

    `replica_states`: one `{key: identity_label}` dict per replica.
    """
    if not replica_states:
        return 1.0
    all_keys: set = set()
    for state in replica_states:
        all_keys |= set(state.keys())
    if not all_keys:
        return 1.0
    agree = sum(
        1 for key in all_keys
        if len({state.get(key, _MISSING) for state in replica_states}) == 1
    )
    return agree / len(all_keys)


def time_to_reconverge(event_log: list[dict]) -> float:
    """Seconds from the first `heal` event to the next `converged` (or
    `replicas_equal`) event. `inf` if no heal event, or no convergence
    event after it, is found in `event_log` (each entry: `{"t": float,
    "event": str, ...}`) — an unbounded reconvergence time is the honest
    answer, not a crash.
    """
    heal_t = None
    for entry in sorted(event_log, key=lambda e: e["t"]):
        if heal_t is None:
            if entry.get("event") == "heal":
                heal_t = entry["t"]
            continue
        if entry.get("event") in ("converged", "replicas_equal"):
            return entry["t"] - heal_t
    return float("inf")


def unresolved_fork_rate(assignment: dict[Any, dict], total_identities: int) -> float:
    """Fraction of identities with an unresolved (still-open) fork.
    `assignment`: `{identity_id: {"forked": bool, ...}, ...}`. The
    denominator is `total_identities` explicitly, not `len(assignment)` —
    an identity with zero surviving claims might not appear in
    `assignment` at all but must still count in the denominator.
    """
    if total_identities <= 0:
        return 0.0
    forked = sum(1 for v in assignment.values() if v.get("forked"))
    return forked / total_identities


# ── C2: Byzantine robustness ─────────────────────────────────────────────────

def accuracy_vs_malicious_fraction(runs: list[dict]) -> list[tuple[float, float]]:
    """`[(malicious_fraction, mean_accuracy), ...]`, sorted by fraction,
    averaging over repeated runs at the same fraction — a single run of a
    distributed system is not evidence.
    `runs`: `[{"malicious_fraction": float, "accuracy": float}, ...]`.
    """
    by_fraction: dict[float, list[float]] = {}
    for run in runs:
        by_fraction.setdefault(run["malicious_fraction"], []).append(run["accuracy"])
    return sorted((f, sum(accs) / len(accs)) for f, accs in by_fraction.items())


def false_claim_rejection_rate(claims: list[dict], ground_truth_malicious: set) -> dict:
    """Precision, recall, AND the raw rejection rate for the plausibility
    gate's reject decision, against ground-truth malicious claim ids. A
    rejection rate alone is misleading: it doesn't say whether the
    rejections were actually justified (precision) or how many real
    malicious claims slipped through (recall).
    `claims`: `[{"claim_id": ..., "rejected": bool}, ...]`.
    """
    malicious = set(ground_truth_malicious)
    total = len(claims)
    rejected = [c for c in claims if c.get("rejected")]
    n_rejected = len(rejected)
    true_positive_rejections = sum(1 for c in rejected if c["claim_id"] in malicious)
    n_malicious = sum(1 for c in claims if c["claim_id"] in malicious)

    return {
        "rejection_rate": n_rejected / total if total else 0.0,
        "precision": true_positive_rejections / n_rejected if n_rejected else 0.0,
        "recall": true_positive_rejections / n_malicious if n_malicious else 0.0,
        "n_rejected": n_rejected,
        "n_malicious": n_malicious,
        "n_total": total,
    }


# ── C3: reachability gating ──────────────────────────────────────────────────

def accuracy_vs_gap_duration(
    matches: list[dict], gap_buckets: list[float]
) -> list[tuple[float, float]]:
    """`[(bucket_upper_bound_s, accuracy), ...]`. Each match's `gap_s` is
    assigned to the smallest bucket boundary it doesn't exceed (spec's own
    buckets: 2, 5, 15, 30, 60, 120 s). A bucket with no matches is omitted
    rather than reported as a misleading 0.0 or 1.0.
    `matches`: `[{"gap_s": float, "correct": bool}, ...]`.
    """
    sorted_buckets = sorted(gap_buckets)
    bucket_hits: dict[float, list[bool]] = {b: [] for b in sorted_buckets}
    for m in matches:
        gap = m["gap_s"]
        for b in sorted_buckets:
            if gap <= b:
                bucket_hits[b].append(bool(m["correct"]))
                break
    return [(b, sum(hits) / len(hits)) for b, hits in bucket_hits.items() if hits]


# ── C4: negative evidence ────────────────────────────────────────────────────

def candidate_region_reduction(area_without: float, area_with: float) -> float:
    """Fraction the candidate-belief region shrank when attestations are
    enabled vs. positive-evidence-only.
    """
    if area_without <= 0:
        return 0.0
    return max(0.0, (area_without - area_with) / area_without)


def false_exclusion_rate(
    excluded_masks: list[np.ndarray], true_positions: list[tuple[int, int]]
) -> float:
    """THE safety-critical C4 number, reported prominently, never buried:
    counts how often the system told a search team a person could NOT be
    somewhere they actually were. `excluded_masks[i]` is a boolean navmesh
    grid mask (True = "ruled out") at the instant `true_positions[i]` — a
    `(col, row)` cell — was the person's real position. A false exclusion
    is `excluded_masks[i][row, col] is True`. Example: 10 masks where
    exactly 2 wrongly exclude the true position returns exactly 0.2.
    """
    if not excluded_masks:
        return 0.0
    false_exclusions = sum(
        1 for mask, (col, row) in zip(excluded_masks, true_positions) if mask[row, col]
    )
    return false_exclusions / len(excluded_masks)


def attestation_accuracy(attestations: list[dict], ground_truth_crossings: list[dict]) -> dict:
    """For each admissible negative-evidence attestation (crossing_observed
    = False — the only kind ever emitted; silence is never evidence), was
    there actually no crossing at that boundary in `[t_start, t_end]`?
    `attestations`: `[{"t_start", "t_end", "boundary_id", "crossing_observed"}, ...]`.
    `ground_truth_crossings`: `[{"t", "boundary_id"}, ...]`.
    """
    correct = 0
    incorrect = 0
    for att in attestations:
        if att.get("crossing_observed"):
            continue
        boundary_id = att["boundary_id"]
        t_start, t_end = att["t_start"], att["t_end"]
        actually_crossed = any(
            gc["boundary_id"] == boundary_id and t_start <= gc["t"] <= t_end
            for gc in ground_truth_crossings
        )
        if actually_crossed:
            incorrect += 1
        else:
            correct += 1
    total = correct + incorrect
    return {
        "accuracy": correct / total if total else 1.0,
        "correct": correct,
        "incorrect": incorrect,
        "n_attestations": total,
    }


# ── C6: topology learning ────────────────────────────────────────────────────

def graph_edit_distance(learned_adj: dict, true_adj: dict) -> int:
    """Edge-only graph edit distance (add/remove edge, cost 1 each) for a
    fixed, known vertex set — Starling node_ids are enrolled and fixed at
    commissioning (starling_net.keys), so this is never the expensive
    general graph-isomorphism GED problem, just a symmetric edge-set
    difference.
    `learned_adj`/`true_adj`: `{node_id: set(neighbour_node_ids), ...}`.
    """
    def edge_set(adj: dict) -> set:
        return {frozenset((a, b)) for a, neighbours in adj.items() for b in neighbours}

    return len(edge_set(learned_adj) ^ edge_set(true_adj))


def topology_reconvergence_time(event_log: list[dict]) -> float:
    """Seconds from a `topology_change` event (e.g. a camera moved) to the
    next `topology_converged` event. `inf` if either is missing.
    """
    change_t = None
    for entry in sorted(event_log, key=lambda e: e["t"]):
        if change_t is None:
            if entry.get("event") == "topology_change":
                change_t = entry["t"]
            continue
        if entry.get("event") == "topology_converged":
            return entry["t"] - change_t
    return float("inf")


# ── System ────────────────────────────────────────────────────────────────────

def bytes_per_node_hour(gossip_stats: Union[dict, list[dict]], uptime_s: float) -> float:
    """Total gossip bytes (sent+recv, all message types) divided by
    (node-count * uptime in hours) — the spec's own comparison metric
    against centralized video streaming. `gossip_stats` is either one
    node's `GossipNode.stats()` dict, or a list of them (one per node);
    either way this normalises per node.
    """
    stats_list = gossip_stats if isinstance(gossip_stats, list) else [gossip_stats]
    total_bytes = 0
    for stats in stats_list:
        for kind, counters in stats.items():
            if kind.startswith("_"):
                continue
            total_bytes += counters.get("sent_bytes", 0) + counters.get("recv_bytes", 0)

    uptime_hours = uptime_s / 3600.0
    if uptime_hours <= 0 or not stats_list:
        return 0.0
    return total_bytes / (len(stats_list) * uptime_hours)


def end_to_end_latency(claim_log: list[dict]) -> dict:
    """p50/p95/p99 latency in seconds from a claim's observation time to
    its delivery/merge time elsewhere.
    `claim_log`: `[{"t_observed": float, "t_delivered": float}, ...]`.
    """
    latencies = sorted(c["t_delivered"] - c["t_observed"] for c in claim_log)
    if not latencies:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "n": 0}

    def _pct(p: float) -> float:
        idx = min(int(round(p * (len(latencies) - 1))), len(latencies) - 1)
        return latencies[idx]

    return {"p50": _pct(0.50), "p95": _pct(0.95), "p99": _pct(0.99), "n": len(latencies)}


# ── Ground-truth format: MOTChallenge + identity + per-node visibility ──────
# STARLING_BUILD_STATE.md §7: extend MOTChallenge with two columns C4 needs
# to be evaluated — the stable cross-camera identity (distinct from the
# per-sequence track id in the standard column 2), and which node(s) could
# actually see this person at this instant.

@dataclass
class ExtendedGTRow:
    frame: int
    track_id: int
    bb_left: float
    bb_top: float
    bb_width: float
    bb_height: float
    conf: float
    cls: int
    visibility: float
    identity: str
    node_visibility: dict[int, bool] = field(default_factory=dict)


def write_extended_mot_gt(path: Union[str, Path], rows: list[ExtendedGTRow]) -> None:
    lines = []
    for r in rows:
        node_vis_str = ";".join(f"{nid}={int(bool(v))}" for nid, v in sorted(r.node_visibility.items()))
        lines.append(
            f"{r.frame},{r.track_id},{r.bb_left},{r.bb_top},{r.bb_width},{r.bb_height},"
            f"{r.conf},{r.cls},{r.visibility},{r.identity},{node_vis_str}"
        )
    Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def read_extended_mot_gt(path: Union[str, Path]) -> list[ExtendedGTRow]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        node_vis_str = parts[10] if len(parts) > 10 else ""
        node_visibility = {}
        if node_vis_str:
            for pair in node_vis_str.split(";"):
                nid, v = pair.split("=")
                node_visibility[int(nid)] = bool(int(v))
        rows.append(ExtendedGTRow(
            frame=int(parts[0]), track_id=int(parts[1]),
            bb_left=float(parts[2]), bb_top=float(parts[3]),
            bb_width=float(parts[4]), bb_height=float(parts[5]),
            conf=float(parts[6]), cls=int(parts[7]), visibility=float(parts[8]),
            identity=parts[9], node_visibility=node_visibility,
        ))
    return rows
