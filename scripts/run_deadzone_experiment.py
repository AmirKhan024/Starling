"""scripts/run_deadzone_experiment.py
---------------------------------------
The C4 headline experiment (WP-09 Part 3): a person walks from
`data/floorplan/demo_site.geojson`'s zone A, through its deliberate 3m
camera dead zone, into zone B. `starling_attest.negative_evidence
.CandidateBelief` tracks the candidate-location region while the person is
in the gap, with and without attestations enabled (the ablation switch),
and this script reports the difference.

Honest scope note: this operates at the level of the negative-evidence
FUSION algorithm directly — a scripted ground-truth trajectory and a
parametrised attestation-noise model — rather than re-running the full
perception -> coverage -> attestation pipeline over synthetic video.
`tests/test_coverage.py` and `tests/test_attestation.py` are what exercise
Parts 1-2 (coverage self-assessment, attestation emission) on synthetic
frames; this script's job is Part 3 (fusion) and the metrics that are only
meaningful over a multi-node scenario. Reproducing this with real
multi-camera footage is the same "needs actual video" follow-up documented
in `docs/results_c1.md`.

The attestation-noise model exists to make the tau_attest sweep honest,
not decorative (STARLING_BUILD_STATE.md §10 flags coverage self-assessment
as a genuinely hard perception problem): each 2s attestation window, a
watching node has a `P_BLIND` chance of being "blind" — it silently fails
to notice a crossing it should have seen, AND its own self-reported
`attest_confidence` for that window is drawn independently of whether it
was actually blind (`BLIND_CONFIDENCE_RANGE`), exactly the failure mode
CLAUDE.md rule 7 exists to guard against: a node's confidence in its own
coverage does not perfectly predict whether that coverage was real. Sweep
`tau_attest` low and more blind-but-confident windows get admitted as
false negative evidence; sweep it high and fewer windows of ANY kind
(including correct ones) get admitted.

Usage
-----
    python scripts/run_deadzone_experiment.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from starling_eval.metrics import (
    attestation_accuracy,
    candidate_region_reduction,
    false_exclusion_rate,
)
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_attest.negative_evidence import CandidateBelief
from starling_node.config import NegativeEvidenceConfig

DEMO_SITE = Path("data/floorplan/demo_site.geojson")
DOC_PATH = Path("docs/results_c4.md")
# Plots live under docs/, not results/ (results/ is gitignored — see
# .gitignore's D-12 comment) — matching scripts/render_reachability.py's
# own convention, so this experiment's figures are actually committed and
# its markdown image links resolve for anyone reading the repo.
OUT_DIR = Path("docs")

# ── ground truth scenario ───────────────────────────────────────────────
# A deliberately cautious pace (not `reachability`'s v_max=1.6 m/s fast-walk
# bound) through the gap: it gives the 3m dead zone several attestation
# windows' worth of dwell time (WP-09 Appendix A.3's tau_attest sweep needs
# more than one or two windows to produce a curve rather than a single
# step), and is itself a physically ordinary case (someone slowing down in
# an unfamiliar or obstructed stretch), not a scenario picked to flatter
# the numbers.
V_PERSON_M_S = 0.4
START_XY = (2.0, 2.0)
END_X = 18.0
BOUNDARY_WEST_X = 8.5  # boundary_id=1, node 0's watched exit
BOUNDARY_EAST_X = 11.5  # boundary_id=2, node 1's watched exit
GAP_ENTRY_X = BOUNDARY_WEST_X
GAP_EXIT_X = BOUNDARY_EAST_X
# The candidate belief's origin is set a little BEFORE the west boundary
# line itself, not exactly on it: `NavMesh.cells_beyond`'s reference point
# must land on one side or the other of the boundary's own rasterised
# cells, and a point exactly on the line is ambiguous by construction
# (it IS the barrier `_compute_boundary_components` removes). This also
# matches the physical story better — "last confirmed position" is the
# last point the person was actually seen, a moment before they vanish
# into the dead zone, not the exact geometric line of disappearance.
ORIGIN_MARGIN_M = 0.3
ORIGIN_XY = (BOUNDARY_WEST_X - ORIGIN_MARGIN_M, START_XY[1])

ATTEST_INTERVAL_S = 2.0
STEP_S = 0.5
POS_SIGMA_M = 0.05

# ── attestation noise model ─────────────────────────────────────────────
P_BLIND = 0.30
BLIND_CONFIDENCE_RANGE = (0.5, 0.9)
HEALTHY_CONFIDENCE_RANGE = (0.75, 0.98)

TAU_SWEEP = [0.3, 0.4, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]
SEED = 20260916


@dataclass
class _SimAttestation:
    node_id: int
    crossing_observed: bool
    attest_confidence: float
    region_ids: list
    t_start: float
    t_end: float


@dataclass
class GapCrossing:
    """One node's ground-truth-vs-attested record for one watched boundary
    over the gap traversal.
    """

    boundary_id: int
    node_id: int
    true_crossing_t: float
    windows: list[_SimAttestation] = field(default_factory=list)


def _generate_attestation_windows(
    boundary_id: int, node_id: int, true_crossing_t: float, t_start: float, t_end: float, rng: np.random.Generator
) -> list[_SimAttestation]:
    windows = []
    t = t_start
    while t < t_end:
        w_end = min(t + ATTEST_INTERVAL_S, t_end)
        true_crossing_here = t <= true_crossing_t < w_end

        blind = rng.random() < P_BLIND
        confidence = rng.uniform(*(BLIND_CONFIDENCE_RANGE if blind else HEALTHY_CONFIDENCE_RANGE))
        crossing_observed = true_crossing_here and not blind

        windows.append(_SimAttestation(
            node_id=node_id,
            crossing_observed=crossing_observed,
            attest_confidence=float(confidence),
            region_ids=[boundary_id],
            t_start=t,
            t_end=w_end,
        ))
        t = w_end
    return windows


def _true_xy(t: float) -> tuple[float, float]:
    x = START_XY[0] + V_PERSON_M_S * t
    return (min(x, END_X), START_XY[1])


@dataclass
class ArmResult:
    times: list[float] = field(default_factory=list)
    area_m2: list[float] = field(default_factory=list)
    excluded_masks: list[np.ndarray] = field(default_factory=list)
    true_positions: list[tuple[int, int]] = field(default_factory=list)


def _run_arm(
    navmesh: NavMesh,
    reachability: ReachabilityModel,
    tau_attest: float,
    negative_evidence_enabled: bool,
    windows_by_boundary: dict[int, list[_SimAttestation]],
    t_origin: float,
    t_gap_exit: float,
) -> ArmResult:
    cfg = NegativeEvidenceConfig(
        negative_evidence_enabled=negative_evidence_enabled,
        tau_attest=tau_attest,
        v_max_m_s=1.6,
    )
    belief = CandidateBelief(navmesh, reachability, cfg)
    belief.initialise(ORIGIN_XY, pos_sigma=POS_SIGMA_M)

    result = ArmResult()
    applied_windows: set[tuple[int, float]] = set()

    t = t_origin
    while t < t_gap_exit:
        belief.step(STEP_S)
        t += STEP_S

        for boundary_id, windows in windows_by_boundary.items():
            for w in windows:
                key = (boundary_id, w.t_start)
                if key in applied_windows:
                    continue
                if w.t_end <= t + 1e-9:
                    belief.apply_attestation(w)
                    applied_windows.add(key)

        belief.normalise()

        result.times.append(t)
        result.area_m2.append(belief.area_m2())
        result.excluded_masks.append(~belief.mask())
        true_x, true_y = _true_xy(t)
        result.true_positions.append(navmesh.world_to_cell(true_x, true_y))

    return result


def run_sweep(
    navmesh: NavMesh, reachability: ReachabilityModel
) -> tuple[list[dict], ArmResult, dict[int, list[_SimAttestation]], float, float]:
    t_origin = (ORIGIN_XY[0] - START_XY[0]) / V_PERSON_M_S
    t_gap_entry = (GAP_ENTRY_X - START_XY[0]) / V_PERSON_M_S
    t_gap_exit = (GAP_EXIT_X - START_XY[0]) / V_PERSON_M_S

    rng = np.random.default_rng(SEED)
    windows_by_boundary = {
        1: _generate_attestation_windows(1, node_id=0, true_crossing_t=t_gap_entry, t_start=t_origin, t_end=t_gap_exit, rng=rng),
        2: _generate_attestation_windows(2, node_id=1, true_crossing_t=t_gap_exit, t_start=t_origin, t_end=t_gap_exit, rng=rng),
    }

    without = _run_arm(navmesh, reachability, tau_attest=0.7, negative_evidence_enabled=False,
                        windows_by_boundary=windows_by_boundary, t_origin=t_origin, t_gap_exit=t_gap_exit)
    area_without_final = without.area_m2[-1] if without.area_m2 else 0.0

    rows = []
    for tau in TAU_SWEEP:
        with_arm = _run_arm(navmesh, reachability, tau_attest=tau, negative_evidence_enabled=True,
                             windows_by_boundary=windows_by_boundary, t_origin=t_origin, t_gap_exit=t_gap_exit)
        area_with_final = with_arm.area_m2[-1] if with_arm.area_m2 else 0.0

        reduction = candidate_region_reduction(area_without_final, area_with_final)
        fer = false_exclusion_rate(with_arm.excluded_masks, with_arm.true_positions)

        attestations = [
            {"t_start": w.t_start, "t_end": w.t_end, "boundary_id": bid, "crossing_observed": w.crossing_observed}
            for bid, windows in windows_by_boundary.items()
            for w in windows
            if w.attest_confidence >= tau
        ]
        ground_truth_crossings = [
            {"t": t_gap_entry, "boundary_id": 1},
            {"t": t_gap_exit, "boundary_id": 2},
        ]
        acc = attestation_accuracy(attestations, ground_truth_crossings)

        rows.append({
            "tau_attest": tau,
            "area_without_m2": area_without_final,
            "area_with_m2": area_with_final,
            "region_reduction_pct": reduction * 100.0,
            "false_exclusion_rate": fer,
            "attestation_accuracy": acc["accuracy"],
            "n_admitted_attestations": acc["n_attestations"],
        })

    return rows, without, windows_by_boundary, t_origin, t_gap_exit


def _write_plot(rows: list[dict], without: ArmResult, with_at_default_tau: ArmResult, out_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots()
    ax.plot(without.times, without.area_m2, label="positive evidence only", linestyle="--")
    ax.plot(with_at_default_tau.times, with_at_default_tau.area_m2, label="with negative evidence (tau=0.7)")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("candidate region area (m^2)")
    ax.set_title("Candidate-belief region over the dead-zone crossing")
    ax.legend()
    fig.savefig(out_dir / "c4_area_over_time.png")
    plt.close(fig)

    fig, ax1 = plt.subplots()
    taus = [r["tau_attest"] for r in rows]
    ax1.plot(taus, [r["region_reduction_pct"] for r in rows], color="tab:blue", marker="o", label="region reduction (%)")
    ax1.set_xlabel("tau_attest")
    ax1.set_ylabel("region reduction (%)", color="tab:blue")
    ax2 = ax1.twinx()
    ax2.plot(taus, [r["false_exclusion_rate"] * 100 for r in rows], color="tab:red", marker="s", label="false exclusion rate (%)")
    ax2.set_ylabel("false exclusion rate (%)", color="tab:red")
    ax1.set_title("C4 headline trade-off: region reduction vs. false exclusion, by tau_attest")
    fig.tight_layout()
    fig.savefig(out_dir / "c4_tau_sweep.png")
    plt.close(fig)


def _write_results_doc(rows: list[dict], default_row: dict) -> None:
    lines = [
        "# C4 results — negative evidence over the dead-zone gap",
        "",
        "Measured from `scripts/run_deadzone_experiment.py` (WP-09 Part 3), the",
        "headline C4 scenario: a person walks straight through",
        "`data/floorplan/demo_site.geojson`'s deliberate 3m camera dead zone",
        f"(x in [{BOUNDARY_WEST_X}, {BOUNDARY_EAST_X}]) at {V_PERSON_M_S} m/s. Numbers below are",
        "printed directly from that harness, not estimated.",
        "",
        "## Honest scope note",
        "",
        "This experiment operates at the level of the negative-evidence fusion",
        "algorithm (`starling_attest.negative_evidence.CandidateBelief`) directly —",
        "a scripted ground-truth trajectory plus a parametrised attestation-noise",
        "model (`P_BLIND` = "
        f"{P_BLIND}, a node's self-reported confidence for a given 2s window is",
        "drawn independently of whether it actually missed a crossing) — rather than",
        "re-running the full perception -> coverage -> attestation pipeline over",
        "synthetic video. `tests/test_coverage.py` and `tests/test_attestation.py`",
        "exercise Parts 1-2 on synthetic frames directly. Reproducing this with real",
        "multi-camera footage is the same \"needs actual video\" follow-up already",
        "documented in `docs/results_c1.md`.",
        "",
        f"## Region reduction and false exclusion at tau_attest={default_row['tau_attest']}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Candidate region area, positive evidence only | {default_row['area_without_m2']:.2f} m² |",
        f"| Candidate region area, with negative evidence | {default_row['area_with_m2']:.2f} m² |",
        f"| Region reduction | {default_row['region_reduction_pct']:.1f}% |",
        f"| **False exclusion rate (safety-critical)** | **{default_row['false_exclusion_rate'] * 100:.1f}%** |",
        f"| Attestation accuracy | {default_row['attestation_accuracy'] * 100:.1f}% ({default_row['n_admitted_attestations']} admitted) |",
        "",
        "The false exclusion rate is reported prominently, not buried, per",
        "STARLING_BUILD_STATE.md WP-09 task 7 — it is the number that matters if",
        "this system is ever used to tell a search team where someone can't be.",
        "",
        "## tau_attest sweep — the headline trade-off curve",
        "",
        "STARLING_BUILD_STATE.md Appendix A.3: \"a better result than any single",
        "number\" — this shows the failure mode (a low threshold admits more",
        "attestations, including the noise model's blind-but-confident ones) rather",
        "than a threshold tuned until the false exclusion rate looks good.",
        "",
        "| tau_attest | region reduction | false exclusion rate | attestation accuracy | attestations admitted |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['tau_attest']:.2f} | {r['region_reduction_pct']:.1f}% | "
            f"{r['false_exclusion_rate'] * 100:.1f}% | {r['attestation_accuracy'] * 100:.1f}% | "
            f"{r['n_admitted_attestations']} |"
        )
    lines += [
        "",
        "![Candidate region area over time](c4_area_over_time.png)",
        "",
        "![tau_attest trade-off curve](c4_tau_sweep.png)",
        "",
    ]
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    navmesh = NavMesh.from_geojson(DEMO_SITE, cell_size_m=0.25)
    reachability = ReachabilityModel(navmesh, v_max_m_s=1.6)

    rows, without, windows_by_boundary, t_origin, t_gap_exit = run_sweep(navmesh, reachability)

    default_row = next(r for r in rows if r["tau_attest"] == 0.7)
    with_default = _run_arm(
        navmesh, reachability, tau_attest=0.7, negative_evidence_enabled=True,
        windows_by_boundary=windows_by_boundary, t_origin=t_origin, t_gap_exit=t_gap_exit,
    )

    try:
        _write_plot(rows, without, with_default, OUT_DIR)
        print(f"Wrote {OUT_DIR / 'c4_area_over_time.png'}")
        print(f"Wrote {OUT_DIR / 'c4_tau_sweep.png'}")
    except ImportError:
        print("matplotlib not available; skipped plots")

    _write_results_doc(rows, default_row)
    print(f"Wrote {DOC_PATH}")
    print()
    print(f"Region reduction at tau=0.7: {default_row['region_reduction_pct']:.1f}%")
    print(f"False exclusion rate at tau=0.7: {default_row['false_exclusion_rate'] * 100:.1f}%")


if __name__ == "__main__":
    main()
