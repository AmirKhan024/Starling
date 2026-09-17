"""scripts/evaluate_topology.py
---------------------------------
WP-07 (C6) evaluation: graph edit distance of the learned topology against
`data/gt/topology.json`'s hand-labelled ground truth, plus re-convergence
time after a simulated camera move (two nodes' video sources swapped
mid-run — STARLING_BUILD_STATE.md WP-07 task 6's "free version" of
physically moving a camera). Writes `docs/results_c6.md` with a plot of
learned versus true transit distribution for one node-pair.

Honest scope note, same shape as `scripts/run_deadzone_experiment.py`'s:
this operates directly on `starling_topology.learner.TopologyLearner` with
a scripted stream of synthetic handoff observations sampled from
`data/gt/topology.json`'s illustrative log-normal parameters, not real
multi-camera footage or a live resolver run (`tests/test_topology.py`
exercises the learner's own algorithm correctness; this script's job is
the evaluation-harness metrics WP-07 asks for). Reproducing this against
real video is the same "needs actual video" follow-up already noted in
`docs/results_c1.md` and `docs/results_c4.md`.

Usage
-----
    python scripts/evaluate_topology.py
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from starling_eval.metrics import graph_edit_distance, topology_reconvergence_time
from starling_node.config import TopologyConfig
from starling_topology.learner import TopologyLearner

GT_PATH = Path("data/gt/topology.json")
DOC_PATH = Path("docs/results_c6.md")
OUT_DIR = Path("docs")

ROUND_INTERVAL_S = 3.0  # simulated seconds between handoff rounds
# 150 rounds: fewer (e.g. 40) is not consistently enough for the tightest
# ground-truth edges' fitted sigma to separate cleanly from the uniform
# null at every RNG seed (verified numerically: ratio 0.85 is comfortably
# clear of the true ~0.5-0.75 range by n=150, but individual edges can sit
# above the null_sigma_ratio=0.85 threshold by chance at n=40).
PHASE1_ROUNDS = 150  # rounds observing the ORIGINAL topology
PHASE2_ROUNDS = 150  # rounds observing the topology AFTER the camera move
HANDOFF_CONFIDENCE = 0.9
SEED = 20260917

# The simulated camera move: node-01's and node-02's video sources are
# swapped mid-run. Physically, the corridor that used to be walked between
# node-00 and node-01 is now walked between node-00 and node-02 (node-02
# now sits where node-01's camera used to be), and the corridor that used
# to be between node-02 and node-03 is now between node-01 and node-03.
# The edge between node-01 and node-02 itself, and the one between node-03
# and node-00, are physically untouched by swapping those two cameras.
SWAPPED_NODES = (1, 2)


@dataclass
class GroundTruthEdge:
    a: int
    b: int
    mean_transit_s: float
    sigma_log: float

    def sample(self, rng: np.random.Generator) -> float:
        return float(rng.lognormal(mean=math.log(self.mean_transit_s), sigma=self.sigma_log))


def load_ground_truth(path: Path = GT_PATH) -> list[GroundTruthEdge]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [GroundTruthEdge(**e) for e in data["edges"]]


def adjacency_of(edges: list[GroundTruthEdge]) -> dict[int, set[int]]:
    adj: dict[int, set[int]] = {}
    for e in edges:
        adj.setdefault(e.a, set()).add(e.b)
        adj.setdefault(e.b, set()).add(e.a)
    return adj


def swap_edge_labels(edges: list[GroundTruthEdge], swap: tuple[int, int]) -> list[GroundTruthEdge]:
    """Relabel each edge's endpoints under swapping the two given node ids
    — the ground truth AFTER the simulated camera move. Same physical
    corridor, same transit-time parameters; only which logical node id
    walks it changes.
    """
    x, y = swap

    def relabel(n: int) -> int:
        if n == x:
            return y
        if n == y:
            return x
        return n

    return [GroundTruthEdge(a=relabel(e.a), b=relabel(e.b), mean_transit_s=e.mean_transit_s, sigma_log=e.sigma_log) for e in edges]


def run_phase(learner: TopologyLearner, edges: list[GroundTruthEdge], rounds: int, rng: np.random.Generator, t0: float) -> float:
    """Feeds `rounds` handoff observations for every edge into `learner`,
    one round advancing simulated time by `ROUND_INTERVAL_S`. Returns the
    simulated time after the last round.
    """
    t = t0
    for _ in range(rounds):
        t += ROUND_INTERVAL_S
        for e in edges:
            transit_s = e.sample(rng)
            learner.observe_handoff(e.a, e.b, transit_s, confidence=HANDOFF_CONFIDENCE)
    return t


def run_phase_tracking_convergence(
    learner: TopologyLearner,
    edges: list[GroundTruthEdge],
    rounds: int,
    rng: np.random.Generator,
    t0: float,
    new_edge_keys: set[tuple[int, int]],
) -> tuple[float, list[dict]]:
    """Same as `run_phase`, but also watches `learner.edges()` after every
    round and records a `topology_converged` event log entry the first
    round every edge in `new_edge_keys` qualifies (WP-07 task 6's
    re-convergence-time measurement).
    """
    t = t0
    events: list[dict] = []
    converged = False
    for _ in range(rounds):
        t += ROUND_INTERVAL_S
        for e in edges:
            transit_s = e.sample(rng)
            learner.observe_handoff(e.a, e.b, transit_s, confidence=HANDOFF_CONFIDENCE)
        if not converged and new_edge_keys.issubset(learner.edges().keys()):
            events.append({"t": t, "event": "topology_converged"})
            converged = True
    return t, events


def _write_plot(learner: TopologyLearner, pair: tuple[int, int], true_edge: GroundTruthEdge, out_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    dist = learner._edges[pair]  # internal, evaluation-only access to plot the raw fitted distribution

    xs = np.linspace(0.5, true_edge.mean_transit_s * 4, 300)
    true_pdf = [
        math.exp(-((math.log(x) - math.log(true_edge.mean_transit_s)) ** 2) / (2 * true_edge.sigma_log ** 2))
        / (x * true_edge.sigma_log * math.sqrt(2 * math.pi))
        for x in xs
    ]
    learned_pdf = [dist.pdf(x) for x in xs]

    fig, ax = plt.subplots()
    ax.hist(list(dist.history), bins=20, density=True, alpha=0.3, label="observed handoffs (recent window)")
    ax.plot(xs, true_pdf, label="true distribution", linestyle="--")
    ax.plot(xs, learned_pdf, label="learned (fitted) distribution")
    ax.set_xlabel("transit time (s)")
    ax.set_ylabel("density")
    ax.set_title(f"Learned vs. true transit distribution, node {pair[0]}<->node {pair[1]}")
    ax.legend()
    fig.savefig(out_dir / "c6_transit_distribution.png")
    plt.close(fig)


def main() -> None:
    gt_edges = load_ground_truth()
    true_adj_before = adjacency_of(gt_edges)

    rng = np.random.default_rng(SEED)
    learner = TopologyLearner(TopologyConfig())

    t = run_phase(learner, gt_edges, PHASE1_ROUNDS, rng, t0=0.0)
    learned_before = learner.to_graph()
    learned_adj_before = {n: set(neigh) for n, neigh in learned_before["adjacency"].items()}
    ged_before = graph_edit_distance(learned_adj_before, true_adj_before)

    event_log = [{"t": t, "event": "topology_change"}]

    gt_edges_after = swap_edge_labels(gt_edges, SWAPPED_NODES)
    true_adj_after = adjacency_of(gt_edges_after)
    new_edges = {(e.a, e.b) if e.a <= e.b else (e.b, e.a) for e in gt_edges_after} - {
        (e.a, e.b) if e.a <= e.b else (e.b, e.a) for e in gt_edges
    }

    t_final, converge_events = run_phase_tracking_convergence(
        learner, gt_edges_after, PHASE2_ROUNDS, rng, t0=t, new_edge_keys=new_edges
    )
    event_log.extend(converge_events)
    reconvergence_time_s = topology_reconvergence_time(event_log)

    learned_after = learner.to_graph()
    learned_adj_after = {n: set(neigh) for n, neigh in learned_after["adjacency"].items()}
    ged_after = graph_edit_distance(learned_adj_after, true_adj_after)

    plot_pair = (1, 2)  # unaffected by the swap -- has continuous data across both phases
    plot_written = False
    try:
        _write_plot(learner, plot_pair, next(e for e in gt_edges if {e.a, e.b} == set(plot_pair)), OUT_DIR)
        plot_written = True
        print(f"Wrote {OUT_DIR / 'c6_transit_distribution.png'}")
    except ImportError:
        print("matplotlib not available; skipped plot")

    lines = [
        "# C6 results — self-healing topology discovery",
        "",
        "Measured from `scripts/evaluate_topology.py` (WP-07) against the",
        "hand-labelled ground truth in `data/gt/topology.json`. Numbers below are",
        "printed directly from that harness over synthetic handoff observations,",
        "not estimated.",
        "",
        "## Honest scope note",
        "",
        "This operates directly on `starling_topology.learner.TopologyLearner`",
        "with a scripted stream of synthetic handoffs sampled from",
        "`data/gt/topology.json`'s illustrative log-normal parameters, not real",
        "multi-camera footage or a live resolver run. Reproducing this with real",
        "video is the same \"needs actual video\" follow-up already documented in",
        "`docs/results_c1.md` and `docs/results_c4.md`.",
        "",
        "## Graph edit distance vs. ground truth",
        "",
        "| Stage | GED |",
        "|---|---|",
        f"| Before the simulated camera move | {ged_before} |",
        f"| After the simulated camera move (`{PHASE2_ROUNDS}` rounds of new-topology handoffs) | {ged_after} |",
        "",
        "## Re-convergence time after a simulated camera move",
        "",
        f"Simulated camera move: node-{SWAPPED_NODES[0]:02d}'s and node-{SWAPPED_NODES[1]:02d}'s video",
        "sources are swapped mid-run (STARLING_BUILD_STATE.md WP-07 task 6's",
        "\"free version\" of physically moving a camera). This changes which node",
        "id walks which physical corridor for the two edges touching the swapped",
        "pair; the edge between the swapped pair itself, and the edge untouched",
        "by the swap, keep their original parameters.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Time for the new corridor edges to qualify (GT edge acquisition) | {reconvergence_time_s:.1f} s |",
        "",
        "**Known limitation (stated, not hidden):** `TopologyLearner` currently",
        "only ever ACQUIRES new edges — it has no decay/expiry mechanism to",
        "forget an edge that has stopped receiving observations. This is why",
        "`ged_after` above is nonzero even once the new edges have qualified: the",
        "two edges that existed before the move remain in `to_graph()`'s output",
        "indefinitely alongside the new ones. A full self-healing implementation",
        "would age out or down-weight edges with no recent observations; that is",
        "not implemented this session and is listed here rather than silently",
        "worked around.",
        "",
        "![Learned vs. true transit distribution](c6_transit_distribution.png)" if plot_written else "",
        "",
    ]
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {DOC_PATH}")
    print()
    print(f"GED before move: {ged_before}")
    print(f"GED after move: {ged_after}")
    print(f"Re-convergence time: {reconvergence_time_s:.1f}s")


if __name__ == "__main__":
    main()
