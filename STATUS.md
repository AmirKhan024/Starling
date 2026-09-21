# Starling — Status

Read this file completely before doing anything else in a new session. It is
the memory of this project across sessions. Section 6 ("Current status") says
exactly what to do next.

## 1. Project in one paragraph

Starling is a decentralized multi-camera identity network for warehouses.
Each camera is an independent node (its own OS process, its own SQLite
replica, its own gossip socket). Nodes never send video — they gossip small
signed "identity claims" to neighbouring nodes only, and every node
independently derives the same answer to "who is where" from the claims it
has merged, with no central server. The system keeps working when the
network partitions and stays robust when a node lies.

## 2. History so far

- **Origin**: the repo began as `multicam-reid`, an open-source centralized
  person re-identification system from Kunal Gaikwad's MSc dissertation
  (MIT licence). `apps/baseline.py` is that original system, frozen as the
  experimental control condition — never modify its behaviour.
- **Sept 13–17 2026**: a teammate converted the project into Starling over
  48 commits, building the distributed core: `starling_crdt` (C1 — claims as
  a grow-only CRDT, deterministic resolver, forks that stay open),
  `starling_net` (signed ZeroMQ gossip, anti-entropy, HLC, partition
  tracking), `starling_consensus` (C2 — plausibility checking, reputation,
  attack injection), `starling_attest` (C4 — coverage attestation, negative
  evidence / `CandidateBelief`), `starling_geometry` (C3 — navmesh,
  reachability, calibration), `starling_topology` (C6), `starling_query`
  (C5), `starling_store` (`LocalStore`), `starling_proto` (wire schema).
  This work was never run end-to-end: every node config points at
  `data/videos/cam0..3.mp4`, and those files were never provided.
- **Sept 21 2026**: an independent review (recorded in
  `STARLING_BUILD_STATE.md`) found 243/244 non-GPU tests passing, most
  results docs still scaffolds, and integration gaps in `apps/node.py`
  (no anti-entropy in the live loop, no reputation/resolver running inside
  a node, calibration+navmesh+real-frame required for any position at all).
  Decision made: stop chasing evaluation numbers and build a
  simulator-driven visual demo first, so the distributed core can actually
  be seen working. Evaluation, the Byzantine sweep, and the headline
  experiment are deferred (see §10).
- **Session log**:
  - **2026-09-21, session 1**: Extracted the handed-over zip (which
    contained the teammate's repo with `.git` history intact) into the
    working directory. Confirmed no prior `STATUS.md` existed — this is
    session 1. Added `origin` remote
    (`https://github.com/AmirKhan024/Starling.git`, no prior origin was
    configured). Completed Step 1 (setup/baseline health): fixed the
    `test_to_yaml_from_yaml_round_trips` calibration bug, fixed a
    pre-existing test-collection failure (see Decisions), added
    `requirements-sim.txt`. Full non-integration suite now passes
    (253 passed, 4 deselected — see §7 for the exact command). Started
    Step 2 (warehouse floor plan).

## 3. Current goal

Build a working, visual, simulator-driven demo (no real cameras, no YOLO,
no GPU) that runs on an ordinary laptop and can perform five moments live
on a dashboard:

1. **Normal walk** — 3–5 virtual workers keep a consistent identity as they
   cross camera zones.
2. **Dead zone** — a worker walks into a blind gap between zones; instead
   of the track vanishing, a shaded "could be here" region appears and
   shrinks as attested absence and reachability rule out area.
3. **Partition and heal** — cut nodes {2,3} off from {0,1}; both sides keep
   tracking; on heal, replicas reconverge (equal claim counts); a genuine
   identity conflict shows as an open fork, never silently resolved.
4. **Lying node** — a node fabricates sightings; peers reject implausible
   claims and its reputation (as seen by peers) visibly drops.
5. **Query and refusal** — a text query ("where is worker 2?") gets an
   answer that separates confirmed from inferred fact and names
   unreachable nodes; an unanswerable query gets a clear refusal + reason.

Full detail: see the original task prompt (not re-copied here — this file
tracks decisions and status, not the spec). The five moments above are the
complete acceptance criteria.

## 4. How we're doing it

```
 ┌─────────────┐   per-zone ZMQ topic    ┌──────────────┐
 │  Simulator   │ ───────────────────▶   │  Node 0..3   │──┐  signed gossip
 │ (world model,│   (only that node's    │ (sim source, │  │  (PUB/SUB,
 │  ground      │    own observations)   │  real CRDT/  │◀─┘  neighbours
 │  truth)      │                        │  consensus/  │     only)
 │              │ ── ground truth topic ─▶│  attest code)│
 └──────────────┘   (dashboard only)     └──────┬───────┘
                                                  │ SUB-only,
                                                  │ read-only
                                           ┌──────▼───────┐
                                           │  Dashboard   │
                                           │ (map, nodes, │
                                           │  forks,      │
                                           │  controls,   │
                                           │  query box)  │
                                           └──────────────┘
```

- The simulator stands in for the physical world *and* the cameras. It is
  allowed to know ground truth (the real world "knows" where people are),
  but it only ever hands each node the observations that node's own camera
  zone would produce — never another zone's data, never a node's database.
- Sim-mode nodes (`source: "sim"`) run the exact same downstream code as
  video nodes: `store.append_local_observation`, the attack injector,
  gossip publish. Only the observation source changes.
- The live node gains: periodic anti-entropy (recovers claims missed during
  a partition), periodic resolver/plausibility/reputation passes over its
  own merged claim set, and gossiped `ReputationUpdate`s so peers can see
  reputation.
- Partitioning is simulated at the application level (a control endpoint
  tells a node to drop traffic to/from specific node ids) — not real
  netem/Docker packet loss.
- The dashboard stays a read-only gossip + ground-truth observer, as today.

## 5. Step checklist

- [x] **Step 1 — Setup and baseline health** — commit `<pending, see git log
      after next commit>`
  - [x] Fixed `test_to_yaml_from_yaml_round_trips` (dist array flattened on
        YAML load)
  - [x] Fixed a pre-existing test-collection blocker unrelated to this task
        (see Decisions) — full suite now collects and runs
  - [x] Added `requirements-sim.txt`
  - [ ] Lazy torch/ultralytics imports in `apps/node.py` — deferred to
        Step 4, where the `source: "sim"` branch is actually added (see
        Decisions: doing it now would be a throwaway partial refactor)
  - [x] Confirmed non-torch tests pass (253 passed, 4 deselected — exact
        command in §7)
  - [ ] mypy — not touched yet (deferred to Step 7 per the brief)
- [ ] **Step 2 — Warehouse floor plan** — in progress
- [ ] **Step 3 — The simulator (`packages/starling_sim/`)** — not started
- [ ] **Step 4 — Sim mode in the node (`apps/node.py`)** — not started
- [ ] **Step 5 — Dashboard for the demo** — not started
- [ ] **Step 6 — One-command launcher and run guide** — not started
- [ ] **Step 7 — Polish** — not started (only after 1–6)

## 6. Current status

**What works right now**: the pre-existing distributed core, unchanged and
tested (253/253 non-integration tests passing). The calibration YAML
round-trip bug is fixed. Test collection is fixed. `requirements-sim.txt`
exists but nothing yet uses it in anger (the sim package doesn't exist).

**What's half-done**: nothing mid-flight — Step 1 is fully committed
before this checkpoint.

**Exact next action**: build `data/floorplan/warehouse_demo.geojson`
(Step 2) — see the layout spec in the original task prompt (roughly 40m x
25m, racking obstacles, 4 camera zones that don't cover everything, one
deliberate blind aisle with both exits covered). Then add a small test
next to `tests/test_navmesh.py`/`tests/test_reachability.py` confirming it
loads via `NavMesh.from_geojson` and that reachability works across the
blind aisle's two boundary exits. After that, move to Step 3 (the
simulator package) — that's the largest remaining chunk of work.

## 7. How to run

Install (sim path, no torch needed once Step 4 lands; right now the repo
still has the full `requirements.txt` — torch/ultralytics — installed in
this dev environment, since the video path isn't being removed):

```
pip install -e ".[dev]"
```

Run tests (exact command, exact result as of this session):

```
python -m pytest -q -m "not integration"
# 253 passed, 4 deselected
```

There is no `scripts/run_demo.py` yet — nothing end-to-end to run yet.

## 8. Decisions

- **Repo root on `sys.path` for tests via pytest's `pythonpath` ini
  option** (`pyproject.toml`), instead of relying on a `PYTHONPATH` env
  var, because this dev machine has a stray, unrelated `scripts` package
  already sitting in the global `site-packages` (not installed via `pip`
  per `pip show scripts` — an environment landmine on this machine) that
  was shadowing the repo's own `scripts/` directory and breaking
  `tests/test_deadzone_experiment.py`'s `import scripts.run_deadzone_experiment`
  at collection time, aborting the *entire* test run. Also added
  `scripts/__init__.py` (repo's `scripts/` was an implicit namespace
  package; Python's import system lets a same-named *regular* package
  found later on `sys.path` win over an earlier namespace-package
  portion — giving `scripts/` a real `__init__.py`, like `apps/` already
  has, makes it win outright as soon as it's found). Both changes are
  self-contained to this repo and don't depend on the host machine's
  global environment being clean.
- **Deferred the torch/ultralytics lazy-import refactor in `apps/node.py`
  to Step 4** instead of doing it now, because the natural way to make it
  lazy is to only import `NodePerception`/`PacedSource` inside the
  `cfg.source != "sim"` branch — and that branch doesn't exist until
  Step 4 builds the sim source. Doing a standalone deferral now would be
  redone anyway.
- **`origin` remote**: none was configured in the handed-over repo, so
  `origin` was added directly as `https://github.com/AmirKhan024/Starling.git`
  (no `teammate` rename was needed — see the git rules in the task prompt).
- **Work branch**: `sim-demo`, per the task's git workflow. `main` gets a
  base push at the start and the final merge at the end of Step 6.

## 9. Known issues and limitations

- The video/YOLO path (`apps/node.py` with a real `source:` video file) has
  never run end-to-end — no `data/videos/*.mp4` exist. Out of scope to fix;
  the simulator is being added as an alternative input, not a replacement.
- mypy still reports ~15 errors in `starling_crdt`/`starling_consensus`
  (not yet touched — Step 7).
- `README.md` is still the original centralized-project description
  (rewrite is Step 6).
- (Will be updated as the simulator/partition/reputation-in-node work
  lands: application-level partition ≠ real netem packet loss; simulated
  perception ≠ real cameras — both by design, see the task brief's
  "Simulator's special status" section.)

## 10. Deferred work (not now)

- **Evaluation / results docs** (`docs/results_*.md`): would need real
  recorded video or a much more elaborate simulated-perception pipeline
  producing MOTChallenge-format ground truth to compute HOTA/MOTA/IDF1
  against; out of scope for a demo.
- **Byzantine sweep experiment**: exists in `starling_eval` already for
  the video path; re-running it against the simulator would need the sim
  to support the sweep's attack-intensity parameter grid.
- **Headline three-way experiment**: same blocker — needs real or
  simulated recorded runs across conditions, not a live interactive demo.
- **Docker/netem partition**: `deploy/netem/apply.py` and
  `starling_eval/netem_plan.py` already do real OS-level partition
  simulation for the Docker deployment; wiring the demo to use that
  instead of the application-level partition control would need the demo
  to run inside `deploy/docker-compose.yml` rather than as bare local
  processes (loses "works on Windows without Docker").
- **Real cameras / YOLO / torch**: the existing video path already does
  this; not being extended or fixed as part of the sim demo.
- **Face anchoring at chokepoints**: exists as a stub concept in configs
  (`is_chokepoint`) but has no implementation; would need a face model.
- **LLM query layer**: `starling_query` stays a structured CLI; adding an
  LLM in front of it is explicitly out of scope per CLAUDE.md.
- **C7 uniform-invariant re-ID**: cut per CLAUDE.md, not being built.

## 11. Key files map

- `apps/baseline.py` — original centralized system, frozen, do not modify.
- `apps/node.py` — one node process; video-only today; gains `source: "sim"`
  in Step 4.
- `apps/dashboard/app.py`, `apps/dashboard/observer.py` — read-only
  Streamlit dashboard and its SUB-only gossip observer.
- `packages/starling_crdt/` — `ClaimSet`, `resolver.resolve`, `forks`.
- `packages/starling_net/` — `gossip.GossipNode`, `anti_entropy.AntiEntropy`
  (built, tested, **not yet wired into `apps/node.py`**),
  `partition.PartitionTracker`, `timebase.MediaClock`, `keys`.
- `packages/starling_consensus/` — `plausibility.check`,
  `reputation.ReputationTable`, `aggregate.aggregate_position`,
  `attacks.AttackInjector` + `ControlServer` (plain HTTP, `POST /attack`,
  `GET /status`).
- `packages/starling_attest/` — `attestation.Attestor`,
  `negative_evidence.CandidateBelief` + `detect_omission`.
- `packages/starling_geometry/` — `calibration.CameraCalibration`,
  `navmesh.NavMesh`, `reachability.ReachabilityModel`.
- `packages/starling_store/identity_store.py` — `LocalStore`, the only
  thing allowed to touch a node's SQLite file.
- `packages/starling_proto/` — wire schema (`Envelope` oneof: `claim`,
  `attestation`, `reputation`, `topology`, `vv_digest`, `vv_delta`) and
  `convert.py` helpers (no `make_reputation_envelope`/
  `make_topology_envelope` exist yet — needed for Step 4).
  `starling_query/` — C5 CLI (`cli.run_query`), capability tokens
  (`capability.issue`/`verify`, purposes `{safety, incident, audit}`).
- `packages/starling_node/config.py` — `NodeConfig` pydantic schema;
  `source` is a free-form string today (video path/RTSP/webcam index);
  `source: "sim"` will be a new convention, not a schema enum change.
- `data/floorplan/demo_site.geojson` — existing 2-zone corridor rig
  (roles: `floor`, `camera_zone`+`node_id`, `obstacle`, `boundary`
  +`boundary_id`) — the schema `warehouse_demo.geojson` (Step 2) follows.
- `packages/starling_sim/` — **does not exist yet** (Step 3).
- `scripts/run_demo.py` — **does not exist yet** (Step 6).
