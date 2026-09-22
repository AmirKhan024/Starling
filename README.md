# Starling — a decentralised multi-camera identity network

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Tests](https://img.shields.io/badge/tests-360%2B%20passing-brightgreen)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

Starling is a network of independent camera nodes that agree on **who is where**
in a building **without any central server**. Each camera is its own OS process
with its own database. Nodes never send video: they gossip small, signed
*identity claims* to their neighbours, and every node independently derives the
same answer from the claims it has merged. The network keeps working when it is
cut in two, keeps reasoning about people it cannot currently see, and stays
robust when one node lies.

This repository ships a **simulator-driven demo** (no cameras, no GPU, no
PyTorch) that runs on an ordinary laptop and shows all of this live on a
dashboard.

## What is new here (the research ideas the demo shows)

| | Idea | Where you see it |
|---|---|---|
| C1 | Identity as a partition-tolerant CRDT: signed observation *claims* are a grow-only set; the identity assignment is a pure function of the merged claims and is **never** replicated. Conflicts stay open as forks. | Moments 1 and 3 |
| C2 | Byzantine-robust attestation with reputation: implausible claims are rejected and the lying node's reputation, as reported by its peers, falls. | Moment 4 |
| C3 | Geometry-constrained gap bridging over a 2D navmesh: a person cannot teleport, so an identity can cross a blind gap. | Moments 1 and 2 |
| C4 | **Negative evidence** — reasoning from *attested* absence. Silence is never evidence of absence; only a confident attestation shrinks the "could be here" region. | Moment 2 |
| C5 | Calibrated, capability-scoped query that separates confirmed from inferred and names unreachable nodes. | Moment 5 |

## Install (demo)

Needs Python 3.10 or newer. The demo needs no GPU and no PyTorch.

```bash
git clone https://github.com/AmirKhan024/Starling.git
cd Starling
python -m venv .venv
# Windows:  .venv\Scripts\activate        Linux/macOS:  source .venv/bin/activate
pip install -r requirements-sim.txt
```

That is all the demo needs: `scripts/run_demo.py` puts the repo's `packages/` on
the path itself. (To run the test suite as well:
`pip install -e . --no-deps pytest hypothesis`.) Node keys are generated
automatically on first run (`configs/keys/`, git-ignored).

## Run

```bash
python scripts/run_demo.py            # opens the dashboard in your browser
python scripts/run_demo.py --headless # print the URL only (no browser)
python scripts/run_demo.py --speed 2  # simulator at 2x real time
python scripts/run_demo.py --presenter # no automatic episodes: drive it from the Demo script panel
```

The launcher starts, each as a separate OS process: the simulator, four sim-mode
camera nodes, and the dashboard (default `http://127.0.0.1:8765`). It waits
until the dashboard answers, prints the URL, and stops everything cleanly on
**Ctrl+C**. Per-process logs are written to `data/demo/logs/`.

## Demo script — the moments

Open the dashboard. The map is the warehouse floor: **solid coloured dots** are
where the network *believes* each worker is (one colour per resolved identity);
**faint dashed rings** are the simulator's ground truth, for comparison only. Four
camera zones (green outline = the camera is sending healthy coverage attestations,
amber = silent) surround a 12x7 m **uncovered block** in the middle. The **"Demo
script"** panel at the top right lists every moment in order with one button each
(start the demo with `--presenter` to stop the automatic dead-zone episodes and
drive everything by hand).

1. **Normal walk.** Watch: four workers patrol; identities keep their colour.
2. **Dead zone — healthy exits.** Worker-2 walks into the uncovered block and stays
   hidden ~27 s. A "could be here: N m²" region appears and stays **inside the
   block**; the faint grey area is what plain reachability would allow without
   negative evidence (typically 8-10x larger). Every camera around the block is
   healthy and saw nobody leave, so their zones are ruled out.
3. **Dead zone — occluded camera.** Same walk, but camera 1 (north) is occluded and
   sends no healthy attestation. Its silence is *not* counted as evidence, so the
   region visibly leaks into that camera's zone — and only that one. The card under
   the map says why, in plain English.
4. **Partition and heal.** Cut {2,3} from {0,1}: both halves keep tracking (and the
   centralized panel loses the cut-off side). Heal: claim counts equalise, gaps 0.
5. **Lying node.** Make node 2 lie: its reputation (as its peers see it) falls and
   its rejected-claims counter climbs; stop it and it recovers.
6. **Query and refusal.** `where is worker 2` (safety token) gives a structured
   answer with *Confirmed*, *Inferred* (candidate region while hidden) and
   unreachable nodes; `where is worker 9` and the `productivity` purpose are refused
   with their reasons.
7. **Conflict — resolvable.** The network splits and each side face-anchors a
   look-alike as the *same* identity. After healing a fork appears and is resolved by
   reachability ("branch 1 requires 7.4 m/s over 3.8 s, exceeds v_max 1.6 m/s").
8. **Conflict — ambiguous.** Same set-up but both branches are physically possible:
   the fork stays **open** with both candidate positions drawn. Nobody guesses.
9. **Centralized comparison.** The panel beside the map is an ordinary
   single-server system (the original project's matcher; *not* Starling). Under a
   partition it loses the cut-off cameras; **Kill central server** and it is DOWN
   while Starling carries on.

## How it is built

```
 simulator ──per-zone topic──▶ node 0..3 ══ signed gossip (neighbours only) ══▶ each other
     │                          (own process, own SQLite replica)
     └── ground-truth topic ──▶ dashboard  ◀── passive, read-only gossip observer
```

* `packages/starling_crdt` — claims as a grow-only CRDT, deterministic resolver, forks
* `packages/starling_net` — signed ZeroMQ gossip, gap-aware anti-entropy, hybrid clocks
* `packages/starling_consensus` — plausibility checks, reputation, attack injection
* `packages/starling_attest` — coverage attestations and negative evidence
* `packages/starling_geometry` — navmesh and reachability
* `packages/starling_query` — capability tokens and the query layer
* `packages/starling_sim` — the simulator (workers, noisy per-zone perception)
* `apps/node.py` — one node process; `apps/demo_dashboard/` — the dashboard
* `apps/central_server_sim.py` — the deliberately centralized comparison server (not part of Starling)

Architectural rules (see `CLAUDE.md`): a node is an OS process and never shares a
database; raw video never crosses the wire; gossip goes to a configured
neighbour set, never a full mesh; identity assignments are never replicated;
forks are never resolved by picking a higher score; silence is never evidence;
the dashboard is a read-only observer.

## Tests

```bash
python -m pytest -q -m "not integration"                # unit + property tests
python -m pytest -q -m integration tests/test_demo_integration.py   # headless end-to-end (~1 min)
```

## Automated visual review

`python scripts/review_demo.py` (needs `pip install -r requirements-review.txt`
and `playwright install chromium`) runs the real demo headlessly in Chromium,
drives every moment, and writes `review/review.html` (self-contained, with
screenshots and measured values), `review/review_summary.md` and
`review/screenshots/`.

## What is simulated

Perception is simulated (no cameras); the network partition is an
application-level receive filter, not packet loss (`deploy/netem` does the real
thing under Docker). See `STATUS.md` for the full list of limitations.

## Credits and provenance

* **Baseline.** This repository began as **`multicam-reid`**, an open-source
  centralised multi-camera person re-identification system by **Kunal Gaikwad**
  (MIT licence), based on his MSc dissertation *Multi-Camera Multi-People
  Tracking and Re-Identification* (Sheffield Hallam University, supervisor
  Dr. Jing Wang). It is preserved unchanged as `apps/baseline.py` and is the
  experimental control condition for the project. The dissertation's reference
  implementation is
  [samihormi/Multi-Camera-Person-Tracking-and-Re-Identification](https://github.com/samihormi/Multi-Camera-Person-Tracking-and-Re-Identification);
  none of its code is used here.
* **Starling conversion.** The decentralised core — CRDT claims, signed gossip,
  consensus, attestation/negative evidence, navmesh geometry, topology learning
  and the query layer — was built by teammate **Bilal Baddi**
  ([@Bilalbaddi](https://github.com/Bilalbaddi)) over 48 commits.
* **Simulator, demo dashboard, launcher, gap-aware anti-entropy and the
  automated review** were added on top by **Amir Khan**
  ([@AmirKhan024](https://github.com/AmirKhan024)).

## Baseline system (unchanged)

The original centralised pipeline (YOLOv8 + ByteTrack + a MobileNetV3 re-ID
backbone + SQLite identity store + Streamlit operator dashboard with a Lost
Person Registry) still lives in `apps/baseline.py` and `apps/dashboard/` and
needs the full `requirements.txt` (PyTorch). See the git history of this file
for its original documentation.

## License

MIT — Copyright © 2025 Kunal Gaikwad. See `LICENSE`.
