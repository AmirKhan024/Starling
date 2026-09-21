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
    (253 passed, 4 deselected — see §7 for the exact command). Completed
    Step 2 (warehouse floor plan): `data/floorplan/warehouse_demo.geojson`
    (40x25m, 4 camera zones, 7 racking obstacles, one deliberate 3m blind
    aisle with both exits labelled as boundaries) plus
    `tests/test_warehouse_demo_floorplan.py` (5 new tests). Full suite now
    258 passed, 4 deselected. Completed Step 3 (the simulator package):
    built `packages/starling_sim/` end-to-end (world/worker movement,
    per-worker identity embeddings, per-zone noisy observation
    generation, ground-truth boundary-crossing detection, a node-side
    `SimAttestor` that signs its own coverage attestations, ZMQ PUB/SUB
    transport, a `SimulatorConfig`-driven runner, and the default
    5-worker/2-occlusion demo scenario), with 38 new tests and a manual
    check that no `starling_sim` module ever imports torch/ultralytics.
    Full suite now 296 passed, 4 deselected. Completed Step 4 (wiring
    the simulator into `apps/node.py`): added `NodeConfig.sim`, rewrote
    `apps/node.py` to branch `_run_video`/`_run_sim`, wired
    `starling_net.anti_entropy.AntiEntropy` into the node loop for the
    first time ever (it existed and was tested but no app dispatched to
    it before this), added application-level `PartitionControl` +
    `ControlServer`'s `POST /partition`, and added `_ReputationLoop` (an
    in-node periodic plausibility pass that gossips
    `ReputationUpdate`s). Manual end-to-end multi-process testing (4 sim
    nodes + the simulator) surfaced and fixed three real, non-obvious
    bugs along the way — see Decisions and Known issues for the full
    story of each: (1) a `VVDelta` reply carrying more than ~3 claims
    exceeded the wire-safety byte cap and silently killed a node's
    gossip receive thread (fixed: chunked replies); (2) comparing every
    claim against the immediately-prior one made the reachability check
    fire on ordinary position noise / grid quantization alone, crashing
    an honest node's reputation with no attack running (fixed: a
    minimum baseline-refresh interval); (3) a claim delivered late via
    anti-entropy catch-up could be graded against an already-advanced
    baseline, giving `dt_s≈0` (fixed: skip the baseline when it's not
    chronologically before the claim). Also found, and left as a
    documented (not fixed — pre-existing, shared-code) limitation: exact
    reconvergence after a partition heal isn't always 100% within a
    bounded window, because `LocalStore.claim_version_vector` is a bare
    per-node MAX(seq) with no gap-awareness, and ZMQ PUB/SUB doesn't
    guarantee ordered delivery. Added `tests/test_node_reputation_loop.py`,
    `tests/test_sim_node_integration.py`, and 4 new tests in
    `tests/test_attacks.py`. Full suite: see §7 for the exact command
    and latest result. Starting Step 5 (the dashboard).

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

- [x] **Step 1 — Setup and baseline health** — commit `5306ab2`
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
- [x] **Step 2 — Warehouse floor plan** — commit `0287e04`
  - [x] `data/floorplan/warehouse_demo.geojson` (4 zones, 7 racking
        obstacles, one deliberate blind aisle with both exits labelled)
  - [x] Loads via `NavMesh.from_geojson`; reachability verified across
        the blind aisle
  - [x] `tests/test_warehouse_demo_floorplan.py` (5 tests, all passing)
- [x] **Step 3 — The simulator (`packages/starling_sim/`)** — commit
      `<pending, see git log after next commit>`
  - [x] `identity.py` — per-worker unit-vector embeddings + noisy
        per-observation re-noising, with a `uniform_similarity` knob
  - [x] `world.py` — `Worker` (waypoint-loop walking with random
        pausing), `World` (positions, zone membership, scripted
        `OcclusionEvent`s), `load_camera_zones` (reads `camera_zone`
        polygons straight from the floor plan GeoJSON)
  - [x] `scenario.py` — YAML scenario loader (`ScenarioWorker`,
        `ScenarioOcclusion`); default scenario ships at
        `configs/sim/scenarios/warehouse_demo.yaml` (5 workers, one
        shuttling through the blind aisle, 2 occlusion events on node 1)
  - [x] `perception.py` — `observe_zone` (per-node, zone-filtered, noisy
        detections — the simulator-side replacement for
        `NodePerception.process()` + calibration); JSON encode/decode
  - [x] `coverage.py` — ground-truth `coverage_state_for_node` +
        `compute_boundary_crossings` (simulator side); `SimAttestor`
        (**node-side** — signs its own attestations, mirrors
        `Attestor.tick`'s admission rule exactly, silence preserved)
  - [x] `transport.py` — `SimPublisher`/`SimSubscriber`, ZMQ PUB/SUB,
        per-node topics + one ground-truth topic
        (`starling_sim.messages`)
  - [x] `config.py` — `SimulatorConfig` (+ loader); `SimNodeConfig` is
        NOT here (see Step 4's note — it ended up defined directly in
        `starling_node.config` instead, matching that file's existing
        convention)
  - [x] `runner.py` — `SimulatorRunner` (`tick_once()` pure/testable,
        `run()` the real-time publish loop), `python -m
        starling_sim.runner --config ...` CLI
  - [x] `node_client.py` — `SimNodeSource` + decode helpers, the
        node-side counterpart Step 4 will call from `apps/node.py`
  - [x] `configs/sim/warehouse.yaml` (`SimulatorConfig`) +
        `configs/sim/scenarios/warehouse_demo.yaml` (default scenario)
  - [x] 38 new tests across 7 test files (identity, world, scenario,
        perception, coverage, transport, runner), all passing; verified
        by hand that importing any `starling_sim` module never imports
        torch/ultralytics
- [x] **Step 4 — Sim mode in the node (`apps/node.py`)** — commit
      `<pending, see git log after next commit>`
  - [x] `NodeConfig.sim: SimNodeConfig` (new field, `starling_node/config.py`)
  - [x] `apps/node.py` rewritten: `_run_video`/`_run_sim` split (video
        path unchanged in behaviour; sim path uses
        `starling_sim.node_client.SimNodeSource` +
        `starling_sim.coverage.SimAttestor`, never imports torch)
  - [x] `AntiEntropy` wired for real: `vv_digest`/`vv_delta` dispatched
        in `_on_gossip_message`, `.tick()` called every housekeeping
        round (previously dead code from the app's perspective)
  - [x] `PartitionControl` (new, `starling_consensus/attacks.py`) +
        `ControlServer`'s new `POST /partition` endpoint — application-
        level partition, receive-side filtering
  - [x] `_ReputationLoop` (new, `apps/node.py`) — periodic in-node
        plausibility pass over the merged claim set +
        `ReputationTable.observe`, gossiped via new
        `make_reputation_envelope` (`starling_proto/convert.py`)
  - [x] `configs/nodes/sim/node-0{0..3}.yaml` — 4 sim node configs, ring
        topology, node 0/1 watch the blind aisle's two boundaries
  - [x] 3 real, non-obvious bugs found and fixed while wiring this up
        live (see Decisions and Known issues): an oversized-envelope
        crash that silently killed a node's gossip receive thread, a
        false-positive reachability check on honest claims, and a
        late-anti-entropy-delivery false positive
  - [x] `tests/test_node_reputation_loop.py` (8 tests: honest-claims
        regression, fabricate-drops-reputation, chunk-size-under-cap,
        etc.) and `tests/test_sim_node_integration.py` (1
        `@pytest.mark.integration` test: two real node processes + a
        real simulator, claims flow, partition cuts merging, heal
        resumes it) — plus 4 new tests in `tests/test_attacks.py` for
        `PartitionControl`
  - [x] Manually verified end-to-end with 4 real sim-mode node
        processes + the simulator: claims replicate, attestations flow,
        reputation gossips, and a live fabricate attack visibly drops
        the lying node's reputation as seen by an honest peer
- [ ] **Step 5 — Dashboard for the demo** — not started
- [ ] **Step 6 — One-command launcher and run guide** — not started
- [ ] **Step 7 — Polish** — not started (only after 1–6)

## 6. Current status

**What works right now**: the full distributed core, plus a working
simulator-driven node mesh. Verified live, multiple times, with 4 real
`apps/node.py` sim-mode processes + the simulator running together:
claims replicate and merge across the ring; a worker shuttling through
the blind aisle produces no observations from any zone while inside the
gap; coverage attestations flow (including during a scripted occlusion);
`POST /partition` demonstrably stops a node from merging a cut peer's
claims and `POST /partition {"drop_node_ids": []}` resumes it; a live
`POST /attack {"attack": "fabricate", ...}` visibly drives an honest
peer's in-node opinion of the lying node down (from ~1.0 toward ~0.5,
see Known issues for why it's not closer to `r_min` and why an honest
node isn't pinned at a perfect 1.0 either). `apps/dashboard/` is
**still completely unchanged** — nothing in it knows the simulator or
sim-mode nodes exist yet; it would today only work against the
video-path node configs it already supports.

**What's half-done**: nothing mid-flight — Steps 1-4 are fully committed
before this checkpoint.

**Exact next action**: Step 5 — the dashboard. Concretely:
1. `apps/dashboard/config.py`'s `DashboardConfig.peers` already points
   at gossip addresses — point it at the 4 sim node configs'
   `net.listen_port`s (`configs/nodes/sim/node-0{0..3}.yaml`, ports
   5555-5558) instead of (or alongside) the video-path ones. No change
   needed to `GossipObserver` itself — it's SUB-only against real
   `GossipNode` PUB sockets, which sim-mode nodes still run unchanged.
2. New: a ground-truth SUB client for the simulator's OWN
   `starling_sim.messages.GROUND_TRUTH_TOPIC` (`starling_sim.transport
   .SimSubscriber` — already exists, built in Step 3) so the dashboard
   can render faint "true position" markers alongside the network's
   resolved belief. This is new code the dashboard doesn't have any
   equivalent of today.
3. Floor plan tab: switch from `demo_site.geojson` to
   `warehouse_demo.geojson` (or make it configurable); render the 4
   zones, 7 obstacles, blind aisle; overlay resolved identities (from
   `GossipObserver.claims` + `starling_crdt.resolver.resolve`, which the
   dashboard already calls) in one colour per identity; overlay a
   `CandidateBelief` region (`starling_attest.negative_evidence`,
   already used elsewhere per the Appendix) for any identity currently
   unseen, fed by `GossipObserver.attestations`.
4. Controls tab: add "Partition {2,3} vs {0,1}" / "Heal" buttons — each
   is 4 `requests.post(f"http://127.0.0.1:{control_port}/partition",
   json={"drop_node_ids": [...]})` calls (`control_port = gossip_port +
   1000`, per node — see `AttackConfig`/`ControlServer`). Remember:
   partition control is receive-side only (Decisions) — both sides of
   the intended split must be told to drop the other for it to actually
   behave like a cut.
5. Node panel: reputation is no longer only the dashboard's own
   locally-computed opinion — nodes now gossip `ReputationUpdate`s
   themselves (Step 4), so `GossipObserver.reputation` (already a
   `ReputationTable`, already fed via `ingest_gossiped` per the
   Appendix) should already reflect this once pointed at sim-mode node
   addresses; verify it rather than assuming.
6. Query box: wire up `starling_query.cli.run_query` (or the lower-level
   `answer_query`) against the sim node mesh — needs a capability token
   (`starling_query.capability.issue`, purpose `"safety"`) and a peers
   config pointing at the sim ports.
7. Streamlit vs. FastAPI+HTML: try Streamlit first (existing dashboard
   is already Streamlit); only fall back per the task brief's own
   allowance if the live map proves too clunky. Record the choice here
   either way.

See §11/Appendix for exact signatures (`GossipObserver`, `DashboardConfig`,
`CandidateBelief`, `resolve`, `starling_query`) and the new
`starling_sim.transport`/`starling_sim.messages` API from Step 3.

## 7. How to run

Install (this dev environment has the full `requirements.txt` —
torch/ultralytics included — installed; a from-scratch sim-only machine
would use `pip install -r requirements-sim.txt` plus `pip install -e .
--no-deps` or equivalent, not yet actually verified on a clean machine —
that verification is part of Step 6):

```
pip install -e ".[dev]"
```

Run tests (exact command, exact result as of this session):

```
python -m pytest -q -m "not integration"
# 304 passed, 5 deselected
```

Generate keys (once; `configs/keys/` is gitignored):

```
python -m starling_net.keys --generate 4
```

Manually run the sim demo mesh (no launcher script yet — that's Step 6),
each in its own terminal from the repo root:

```
python -m starling_sim.runner --config configs/sim/warehouse.yaml
python apps/node.py --config configs/nodes/sim/node-00.yaml
python apps/node.py --config configs/nodes/sim/node-01.yaml
python apps/node.py --config configs/nodes/sim/node-02.yaml
python apps/node.py --config configs/nodes/sim/node-03.yaml
```

Try the partition/lie controls by hand while that's running (control port
= gossip port + 1000, e.g. node 0's gossip port 5555 -> control port
6555):

```
curl -X POST http://127.0.0.1:6557/partition -d "{\"drop_node_ids\": [0,1]}"
curl -X POST http://127.0.0.1:6557/attack -d "{\"attack\": \"fabricate\", \"intensity\": 0.9}"
```

`apps/dashboard/` is unchanged and not yet wired to any of this — Step 5.

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
- **Sim delivery via per-node ZMQ topics on a real ZMQ PUB socket**
  (`starling_sim.transport`), not "each node replays its own copy of the
  deterministic world" (the task brief's other acceptable option),
  because the demo also needs a genuinely separate simulator OS process
  publishing ground truth for the dashboard's overlay layer — with a live
  PUB socket already required for that, reusing it for per-node delivery
  avoids building and keeping two delivery mechanisms in sync. Topics are
  plain strings (`node:0`..`node:3`, `ground_truth`); payloads are JSON,
  not protobuf — this is a local, unsigned side channel standing in for
  "a camera handing a frame to its own node's perception pipeline", not
  part of the signed gossip mesh, so it doesn't need the wire schema's
  size/signature discipline.
- **The simulator computes noisy per-zone observations itself and sends
  already-noised, already-filtered data to each node** (rather than
  sending raw ground truth and having the node add its own noise/zone
  filter), because the task brief's own wording ("send each node what
  that node's own camera would see") describes the simulator as the
  thing doing the sensing, mirroring how `apps/node.py`'s video path
  already receives already-detected `Observation`s from
  `NodePerception.process()` rather than raw pixels.
- **Coverage attestation signing stays entirely node-side**
  (`starling_sim.coverage.SimAttestor`, not something the simulator
  builds and hands over pre-signed): the simulator sends only raw
  ground-truth coverage facts (occlusion_ratio/illumination_score/
  detector_health per node, plus a shared boundary-crossing-this-tick
  dict sent to every node); each node's own `SimAttestor` decides
  admission (mirrors `Attestor.tick`'s `tau_attest` gate exactly) and
  signs with its own private key — consistent with CLAUDE.md rule 1/2:
  nothing outside a node ever touches its keys or makes its claims for
  it.
- **Worker routes are hand-placed waypoint loops, not auto-pathfound.**
  `ReachabilityModel.distance_field` could drive real A*-style routing,
  but the floor plan's open rectangular zones make hand-placed waypoints
  trivial to keep obstacle-free and are much easier to reason about for
  scripting specific demo moments (e.g. "worker 2 shuttles through the
  blind aisle") than a pathfinder's emergent routes would be.
- **Worker pausing is a per-tick random chance** (`pause_prob_per_tick` +
  a sampled duration), not a fixed pause scripted at specific waypoints,
  because it reads as natural movement without needing segment-boundary
  detection logic in `Worker.tick`.
- **`starling_sim` duplicates two small pieces of logic instead of
  importing them**: the boundary-crossing segment-sampling check
  (`starling_attest.attestation._crosses_boundary`'s equivalent, in
  `starling_sim.coverage._segment_crosses_boundary`) and the attestation
  HLC-timestamp builder (`_hlc_proto`). Both are ~10 lines. Importing the
  originals would pull `starling_attest.attestation` in transitively via
  `starling_perception.coverage`/`starling_geometry.calibration` (cv2)
  and keep `starling_sim` coupled to the real-camera stack's dependency
  footprint — the whole point of this package is to be the lightweight,
  torch-free alternative.
- **`NodeConfig.sim: SimNodeConfig` is defined directly in
  `starling_node/config.py`**, not imported from `starling_sim.config`
  (which is where the task brief's own Step 3 wording implied it might
  live). Every other node config concern (`PerceptionConfig`,
  `MatchConfig`, `NetConfig`, ...) is already defined this same way —
  once in `starling_node`, regardless of which package consumes the
  field — so this keeps the established pattern instead of making
  `starling_node` depend on `starling_sim`.
- **Anti-entropy delta replies are chunked to 3 claims per envelope**
  (`apps/node.py`'s `_ANTI_ENTROPY_CHUNK_SIZE`), found necessary the hard
  way: this project's claim embeddings are raw float32 (not the
  int8-quantized form the wire schema's own comments describe), so one
  `IdentityClaim` is ~2.2KB and a `VVDelta` carrying more than ~3 of them
  already exceeds `starling_proto.limits.MAX_MESSAGE_BYTES` (8192B).
  `GossipNode.publish` raising inside `_on_gossip_message` — itself
  called from `GossipNode`'s own background poll thread, with no
  exception handling around that call — silently killed the node's
  ability to receive ANY further gossip (the thread just dies; the rest
  of the process keeps running normally, which made this very
  non-obvious to diagnose from the node's own logs). A short
  `time.sleep(0.01)` between chunks was also added after observing that
  a tight back-to-back publish burst could still lose a fraction of a
  large chunk sequence in practice (ZMQ PUB/SUB has no delivery
  guarantee, and the receiver's ed25519 signature verification happens
  synchronously on its single poll thread).
- **`_ReputationLoop` refreshes its corroborated-position baseline at
  most once every `_MIN_BASELINE_REFRESH_S` (2.0s), not on every
  claim.** Found via a fast, deterministic single-process repro
  (packages under test called directly, no sockets) that an HONEST
  node's reputation crashed to `r_min` with no attack running at all,
  purely from comparing consecutive ~0.2s-apart sim-tick claims: the
  reachability check's implied-speed math divides by `dt_s`, and at
  that timescale ordinary position noise
  (`SimulatorConfig.pos_noise_sigma_m`) and `ReachabilityModel`'s own
  grid-quantized geodesic distance (`NavMesh.cell_size`) are both
  large enough, relative to the true per-tick displacement, to
  occasionally exceed `PlausibilityConfig.v_max_m_s` on their own. A
  fabricated claim's actual (tens-of-metres) jump still fails by a wide
  margin at any `dt_s`, so this costs nothing in detection power.
- **`_ReputationLoop` also refuses to compare a claim against a baseline
  that is not strictly BEFORE it in time** (`usable_baseline` in
  `run_pass`). Anti-entropy catch-up can deliver a claim "late" (after
  the baseline has already advanced past its timestamp from other,
  more-promptly-delivered claims); without this guard, `dt_s` computes
  to ~0 and produces the same false-positive failure mode as above, for
  a claim that was never actually implausible — it just arrived out of
  order. Found the same way, via the fast single-process repro.
- **Partition control is receive-side only, on both ends of a cut
  symmetrically** (documented on `PartitionControl` itself): `apps/node
  .py` never gates what it SENDS on `partition_control` — `GossipNode
  .publish` has no per-peer send in this project's PUB/SUB transport
  layer to gate in the first place. The dashboard's partition button
  (Step 5) must call `POST /partition` on every node on BOTH sides of
  the intended split, not just one, for it to actually behave like a
  cut link.
- **`_ReputationLoop` lives directly in `apps/node.py`**, not as a new
  package, because it is pure orchestration glue over existing
  `starling_consensus`/`starling_crdt` primitives (`plausibility.check`,
  `ReputationTable`, `ClaimSet`) — there was no new algorithm to give its
  own module, only a policy for what to feed those functions and when.

## 9. Known issues and limitations

- The video/YOLO path (`apps/node.py` with a real `source:` video file) has
  never run end-to-end — no `data/videos/*.mp4` exist. Out of scope to fix;
  the simulator is being added as an alternative input, not a replacement.
  Also observed this session (info, not a Step 4 regression): a manual
  run of `tests/test_node_process.py::test_node_process_writes_only_its_own_db`
  (the one real video-path integration test, guarded by
  `@pytest.mark.integration`, excluded from the suite this project tracks)
  took over 3 minutes and needed to be killed on this dev machine — the
  code's own docstring already documents YOLO/torch cold-start thread
  contention costing "over 80 seconds" on this project's dev machine; not
  investigated further, since the video/YOLO path is explicitly
  deprioritized for this work.
- **`LocalStore.claim_version_vector` is a bare per-node `MAX(seq)`, not
  gap-aware** (`starling_store/identity_store.py`) — a real, pre-existing
  limitation of the shared anti-entropy design, surfaced (not introduced)
  by Step 4 being the first thing to actually stress it under realistic
  message volume. ZMQ PUB/SUB does not guarantee ordered or loss-free
  delivery; if a node merges a HIGH seq from a peer before a handful of
  LOWER ones (plausible under load, e.g. right after many nodes' claims
  all arrive in a burst following a partition heal), its version vector
  reports "caught up to N" even though specific claims below N are still
  missing — and no future digest/delta exchange has any way to notice
  that hole, since the comparison is a single per-node integer, not a
  bitmap or explicit gap list. `tests/test_sim_node_integration.py`'s own
  heal-reconvergence check tolerates this (asserts ≥50% of a frozen
  pre-heal snapshot propagates, not 100%) with a full explanation inline.
  A proper fix (a gap-aware version vector, or reliable delivery) is a
  real chunk of work in shared, well-tested code and out of scope here —
  worth flagging clearly for anyone extending anti-entropy further.
- **A healthy, honest node's in-node reputation opinion of another honest
  node isn't perfectly pinned at 1.0** — small residual noise-sensitivity
  remains even after the two false-positive fixes above (observed in
  live multi-process testing hovering around 0.83-0.95, never crashing
  toward `r_min` the way the pre-fix bug did). `tests
  /test_node_reputation_loop.py::test_honest_claims_alone_never_drag_reputation_down`
  asserts `> 0.6` — a bar chosen to clearly separate "healthy" from
  "broken," not to claim this is perfectly tuned. Worth another pass in
  Step 7 if the demo's reputation bars look noisier than desired for an
  UNATTACKED node.
- mypy still reports ~15 errors in `starling_crdt`/`starling_consensus`
  (not yet touched — Step 7).
- `README.md` is still the original centralized-project description
  (rewrite is Step 6).
- A scripted occlusion event (`ScenarioOcclusion`) currently only degrades
  a node's attestation confidence (`occlusion_ratio`/`detector_health`
  fed to `SimAttestor`) — it does NOT also raise `observe_zone`'s
  detection-miss probability for that node. A real partially-occluded
  camera would plausibly miss more detections too, not just attest with
  lower confidence. Simple to add later (Step 7 polish: pass the active
  `OcclusionEvent` into `observe_zone` and scale `detection_miss_prob`);
  left out for now since it wasn't required for any of the five demo
  moments to work.
- Application-level partition (Step 4, not yet built) will simulate a cut
  link by having a node ignore inbound gossip/anti-entropy from specific
  peer ids — not real packet loss/delay the way `deploy/netem` does for
  the Docker deployment. By design; see §10's Docker/netem entry.
- Simulated perception (this session's Step 3) stands in for real
  cameras entirely — by design; see the task brief's "Simulator's special
  status" section, reproduced in §4 above.

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
- `apps/node.py` — one node process. `run()` builds shared infra (store,
  tracker, keys, gossip, `AntiEntropy`, `ReputationTable` +
  `_ReputationLoop`, `AttackInjector`, `PartitionControl`,
  `ControlServer`) then branches to `_run_video` (unchanged behaviour,
  torch imported lazily inside it only) or `_run_sim` (Step 4, uses
  `starling_sim.node_client`/`starling_sim.coverage.SimAttestor`).
  `_on_gossip_message` now dispatches all 6 `Envelope` payload kinds,
  including `vv_digest`/`vv_delta` (chunked replies —
  `_ANTI_ENTROPY_CHUNK_SIZE` — see Decisions) and `reputation`.
- `apps/dashboard/app.py`, `apps/dashboard/observer.py` — read-only
  Streamlit dashboard and its SUB-only gossip observer. **Still
  completely unchanged** — Step 5.
- `packages/starling_crdt/` — `ClaimSet`, `resolver.resolve`, `forks`.
- `packages/starling_net/` — `gossip.GossipNode`, `anti_entropy.AntiEntropy`
  (built in an earlier session, tested, **wired into `apps/node.py` for
  real as of Step 4** — see its Known issues entry on version-vector
  gaps), `partition.PartitionTracker`, `timebase.MediaClock`, `keys`.
- `packages/starling_consensus/` — `plausibility.check`,
  `reputation.ReputationTable`, `aggregate.aggregate_position`,
  `attacks.AttackInjector` + `ControlServer` (plain HTTP, `POST /attack`,
  `POST /partition` (Step 4), `GET /status`), `attacks.PartitionControl`
  (Step 4, application-level, receive-side only — see Decisions).
- `packages/starling_attest/` — `attestation.Attestor` (video path only),
  `negative_evidence.CandidateBelief` + `detect_omission`.
- `packages/starling_geometry/` — `calibration.CameraCalibration`,
  `navmesh.NavMesh`, `reachability.ReachabilityModel`.
- `packages/starling_store/identity_store.py` — `LocalStore`, the only
  thing allowed to touch a node's SQLite file. `claim_version_vector` /
  `claims_since` — see the Known issues entry on their gap-blindness.
- `packages/starling_proto/` — wire schema (`Envelope` oneof: `claim`,
  `attestation`, `reputation`, `topology`, `vv_digest`, `vv_delta`) and
  `convert.py` helpers, now including `make_reputation_envelope` (Step
  4, mirrors `make_attestation_envelope`; `make_topology_envelope` still
  doesn't exist — nothing gossips `TopologyObservation` yet).
  `starling_query/` — C5 CLI (`cli.run_query`), capability tokens
  (`capability.issue`/`verify`, purposes `{safety, incident, audit}`).
- `packages/starling_node/config.py` — `NodeConfig` pydantic schema;
  `source` is a free-form string (video path/RTSP/webcam index, or the
  literal `"sim"`). `SimNodeConfig` (Step 4) is defined here too, as
  `NodeConfig.sim` — see Decisions for why it isn't imported from
  `starling_sim.config` instead.
- `data/floorplan/demo_site.geojson` — existing 2-zone corridor rig
  (roles: `floor`, `camera_zone`+`node_id`, `obstacle`, `boundary`
  +`boundary_id`) — the schema `warehouse_demo.geojson` (Step 2) follows.
- `data/floorplan/warehouse_demo.geojson` — the sim demo's 40x25m floor
  plan (4 zones, 7 racking obstacles, one blind aisle) — Step 2.
- `packages/starling_sim/` — the simulator package (Step 3), torch-free:
  - `identity.py` — worker identity embeddings
  - `world.py` — `Worker`/`World`/`OcclusionEvent`/`load_camera_zones`
  - `scenario.py` — YAML scenario loader
  - `perception.py` — per-zone noisy observation generation + JSON codec
  - `coverage.py` — ground-truth coverage/crossing facts (simulator
    side) + `SimAttestor` (**node-side** signing, Step 4 will call this)
  - `transport.py` — `SimPublisher`/`SimSubscriber` (ZMQ PUB/SUB)
  - `messages.py` — topic name helpers
  - `config.py` — `SimulatorConfig` only (`SimNodeConfig` ended up in
    `starling_node.config` instead — see Decisions)
  - `runner.py` — `SimulatorRunner` (`tick_once`/`run`), CLI entrypoint
  - `node_client.py` — `SimNodeSource` + decode helpers (used by
    `apps/node.py::_run_sim` since Step 4)
- `configs/sim/warehouse.yaml` — the shipped `SimulatorConfig`.
- `configs/sim/scenarios/warehouse_demo.yaml` — the shipped default
  scenario (5 workers, 2 occlusion events on node 1).
- `configs/nodes/sim/node-0{0..3}.yaml` — the 4 sim-mode node configs
  (Step 4), ring topology, ports 5555-5558 (same convention as
  `configs/nodes/local/`); nodes 0/1 watch the blind aisle's boundary
  1/2 respectively, 2/3 watch nothing.
- `tests/test_node_reputation_loop.py` — `_ReputationLoop` unit tests +
  the anti-entropy chunk-size wire-safety regression test (Step 4).
- `tests/test_sim_node_integration.py` — the one `@pytest.mark.integration`
  end-to-end test: real simulator + 2 real sim-mode node processes,
  claims flow, partition cuts merging, heal resumes it (Step 4).
- `scripts/run_demo.py` — **does not exist yet** (Step 6).

## Appendix — API reference for Step 3+ (from a session-1 codebase survey)

Exact signatures, so Step 3/4/5 don't need to re-derive them by reading
source again. Import paths are exact.

**`starling_net.anti_entropy`**
```python
AntiEntropy(local_store, gossip: Optional[GossipNode] = None, interval_s: float = 2.0, max_delta: int = 200)
  .tick() -> None                                   # publishes this node's VV as Envelope(vv_digest=...) to gossip.neighbours
  .on_digest(their_vv: VersionVector) -> list[dict]  # claims the peer is missing (local_store.claims_since)
  .on_delta(claims: list[dict]) -> int               # local_store.append_remote_claims(claims); idempotent
VersionVector(seqs: Optional[dict[int,int]] = None)
  .get(node_id, default=-1) / .as_dict() / .merge() / .dominates() / .missing_from()
  .pack() -> bytes / .unpack(bytes)
```
**Not wired into `apps/node.py` today** — no handling of `vv_digest`/`vv_delta` envelopes exists in `apps/`, nothing calls `.tick()` in the node loop. Fully tested (`tests/test_anti_entropy.py`) but dead code from the app's perspective. Step 4 must dispatch on `envelope.WhichOneof("payload")` for these two kinds and call `.tick()` periodically (like `tracker.tick()` already is, every `_HOUSEKEEPING_EVERY_N_FRAMES`).

**`starling_net.gossip.GossipNode`**
```python
GossipNode(node_id, listen_port, neighbours: list[str], keys: NodeKeys, on_message: Callable[[Envelope], None])
  .start() / .stop() / .publish(envelope) / .stats() -> dict / .neighbours: list[str]
```
Pure PUB/SUB broadcast to configured neighbours, no relay/forwarding, no point-to-point primitive. `sender_node_id` on a received envelope is always the direct peer.

**`starling_net.partition.PartitionTracker`** — already used in `apps/node.py`:
```python
PartitionTracker(neighbour_node_ids: list[int], stale_after_rounds: int = 3)
  .on_message(sender_node_id) / .tick() / .reachable_neighbours() -> list[int]
  .coverage_completeness() -> float / .check_partition_event() -> Optional[str]  # "PARTITION_DETECTED"|"PARTITION_HEALED"|None
```
No ping/heartbeat exists anywhere — purely inferred from gossip traffic.

**`starling_consensus.attacks`**
```python
AttackInjector(node_id, attack="none", intensity=0.0, cfg: Optional[AttackConfig]=None, seed=None)
  .set_attack(attack, intensity) / .status() -> dict / .apply_to_claims(...) / .apply_to_attestations(...)
AttackInjector.SYNTHETIC_SEQ_BASE = 10**15   # fabricated/replayed claim seqs live above this
ControlServer(injector, port, host="127.0.0.1")   # plain stdlib HTTP (ThreadingHTTPServer)
  POST /attack {"attack": "...", "intensity": 0.5} -> 200 {status}
  GET  /status -> 200 {status}
```
**No drop-traffic / partition-simulation capability exists anywhere in `starling_net`/`starling_consensus`.** `PartitionTracker` only *observes*; nothing drops packets. `deploy/netem/apply.py` + `starling_eval/netem_plan.py` do real OS-level netem for Docker — the only existing partition mechanism, and it's the wrong shape for this demo (needs Docker). Step 4's partition control is new: sibling to `ControlServer`, e.g. `POST /partition {"drop_node_ids": [2,3]}` that makes the node's own message dispatch silently drop envelopes to/from those ids (simplest: filter in `_on_gossip_message` and skip `gossip.publish` to specific peers — but `GossipNode.publish` broadcasts to all neighbours at once, so dropping outbound to a subset means the drop has to happen understanding "traffic to node X" means "the specific PUB/SUB connection whose peer is X", which requires either (a) per-neighbour publish sockets already used inside `GossipNode`, or (b) a receive-side drop only (drop `on_message` calls whose `sender_node_id` is in the blocked set) plus refuse to `.tick()` anti-entropy toward blocked peers. Receive-side + anti-entropy-skip is simplest and sufficient for the demo's visible behaviour (each side stops seeing the other).

**`starling_consensus.plausibility` / `.reputation` / `.aggregate`**
```python
check(claim: dict, corroborated_state: CorroboratedState, geometry: Optional[ReachabilityModel], cfg: PlausibilityConfig) -> PlausibilityResult
# PlausibilityResult(passed: bool, score: float, failures: list[str], details: dict)
CorroboratedState(last_position=None, last_t_media=None, corroborating_claims=[], now_physical_ms=None)

ReputationTable(node_id, cfg: ReputationConfig, keys: Optional[NodeKeys]=None)
  .observe(about_node, plausibility_result) / .penalise_omission(about_node, weight) / .penalise_topology_shift(about_node, weight)
  .local_opinion(node_id) -> float / .aggregate(node_id) -> float   # median over local + gossiped
  .ingest_gossiped(update: ReputationUpdate) / .to_updates() -> list[ReputationUpdate]

aggregate_position(claims, reputation, method: "unweighted"|"reputation"|"trimmed_mean"|"krum", cfg: AggregateConfig) -> AggregateResult
```
Step 4's periodic in-node loop: `plausibility.check(...)` per incoming claim -> `reputation_table.observe(...)`, then gossip `reputation_table.to_updates()` — needs a new `make_reputation_envelope` in `starling_proto/convert.py` (mirror `make_attestation_envelope` exactly: `env.reputation.CopyFrom(update)`).

**`starling_proto`** — `Envelope` oneof `payload` values: `claim`, `attestation`, `reputation`, `topology`, `vv_digest`, `vv_delta`. `convert.py` has `record_to_claim_proto`, `claim_proto_to_record`, `make_claim_envelope`, `make_attestation_envelope` only — no reputation/topology envelope helpers exist yet (build them, same pattern).

**`starling_attest.attestation.Attestor`**
```python
Attestor(node_id, coverage_assessor: CoverageAssessor, cfg: AttestConfig, keys: Optional[NodeKeys]=None)
  .tick(t_media, frame, detections, stats: DetectorStats) -> Optional[CoverageAttestation]
```
Fires at most once per `cfg.tick_interval_s` of *media time*; returns `None` below `tau_attest` confidence unless a crossing was observed.

**`starling_attest.negative_evidence.CandidateBelief`** (not in `attestation.py`):
```python
CandidateBelief(navmesh: NavMesh, reachability: ReachabilityModel, cfg: NegativeEvidenceConfig)
  .initialise(last_confirmed_xy, pos_sigma=0.0)   # raises if not in free space
  .step(dt_s) / .apply_attestation(att: Optional[CoverageAttestation]) / .apply_observation(obs) / .normalise()
  .mask() -> np.ndarray / .area_m2(eps=1e-6) -> float / .render()
detect_omission(att, corroborating_claims, cfg) -> bool   # feeds reputation_table.penalise_omission
```
Standard loop per tick: `step(dt_s)` -> apply any new attestations (dedupe by `(node_id, t_start.physical_ms)`) -> `normalise()`.

**`starling_crdt`**
```python
ClaimSet(store: LocalStore)
  .add(claim) / .merge(other) -> int / .version_vector() / .delta_since(vv) / .ordered() -> list[dict] / .prune(before_hlc)
resolve(claims: ClaimSet, geometry, reputation, topology, cfg: MatchConfig) -> tuple[Assignment, ForkSet]
# Assignment(identity_of: dict[claim_id,Optional[str]], trajectories: dict[str,list[claim_id]], confidence: dict[str,float])
Branch(claim_ids, last_position, hlc_span) / IdentityFork(fork_id, identity_ref, branches, opened_at, status=OPEN, ...)
ForkSet: .add(fork) / .get(fork_id) / .open_forks() -> list[IdentityFork] / .all_forks() / .resolve(fork_id, branch, reason, status)
```
Forks never auto-resolve by score (CLAUDE.md rule 6); `fork_id` is a deterministic hash so replicas agree without coordination.

**`starling_store.identity_store.LocalStore`**
```python
LocalStore(db_path="database/identities.db", lost_threshold_secs=120.0, similarity_threshold=0.60, ema_alpha=0.10, node_id=0)
  .append_local_observation(obs, world_pos=None, pos_sigma=None) -> dict
  .append_remote_claims(claims: list[dict]) -> int   # idempotent INSERT OR IGNORE on (node_id,seq) — the CRDT merge
  .claim_version_vector() -> dict[int,int] / .claims_since(vv) -> list[dict] / .count_claims() / .has_claim(claim_id)
  .prune_claims(before_physical_ms) / .stats() -> dict / .close()
```
`db_path=":memory:"` is the standard pattern for an ephemeral store (dashboard, query CLI use it) — fine for sim nodes too, or a real path under `data/nodes/node-NN/` if "identical claim sets after heal" needs to survive process restarts (it won't, in-process is fine for a live demo).
Claim record dict shape: `claim_id, node_id, seq, hlc_physical_ms, hlc_logical, local_track_id, t_media, embedding, embed_scale, world_x, world_y, pos_sigma, anchor_type, identity_ref, last_anchor_t, confidence, quality, signature`.
For "identical claim sets after heal": compare `ClaimSet.ordered()` (canonical total order) across nodes.

**`starling_query`**
```python
run_query(query_text, token_path: Path, peers_config_path: Path, hop_budget=3, area=(), window_s=600.0, stale_after_s=10.0) -> tuple[int, str]
CapabilityToken(purpose, area=(), t_start=0.0, t_end=0.0, issued_by=0, signature=b"")
issue(purpose, area, t_start, t_end, keys: NodeKeys) -> CapabilityToken
verify(token, query, keys, now=None) -> tuple[bool, str]
ALLOWED_PURPOSES = {"safety", "incident", "audit"}
```
Refusal reasons seen in the code: "subject was never enrolled", "no claims within window", "OPEN unresolved fork", "unreachable for entire window — partitioned wing, not an absence", "no coverage/attestation for region".

**`apps/dashboard/app.py` + `observer.py`** — Streamlit, 8 tabs (Floor Plan, Node Health, Forks, Network, Unlocated, Search, Identity Detail, Controls). `GossipObserver(peers: dict[int,str], keys_dir)` is a hand-rolled SUB-only poll loop (not a `GossipNode`) — `:memory:` `LocalStore`, `.claims: ClaimSet`, `.reputation: ReputationTable`, `.attestations: list[CoverageAttestation]` (bounded 5000), `.stats()`, `.bytes_per_node_since_start()`, `.liveness(stale_after_s)`, `.coverage_completeness(stale_after_s)`. Config: `configs/dashboard.local.yaml` (`DashboardConfig`: `peers`, `keys_dir`, `navmesh_path`, `match`, `geometry`, `lost_threshold_s`, `stale_after_s`, `control_port_offset=1000`). Controls tab does direct `requests.post` to each node's `ControlServer`. **Implication for Step 5**: sim nodes must run real `GossipNode`s with real ZMQ PUB sockets so the existing `GossipObserver` needs zero changes — don't build a parallel in-process-only transport for sim nodes, or the dashboard can't observe them.

**`starling_node.config.NodeConfig`** — `source` is a free-form string (video path/RTSP/webcam index), not an enum; `source: "sim"` is a new convention to branch on in `apps/node.py`, not a schema change. Add a new `sim: SimConfig` sub-model (default-factory'd) following the existing one-`BaseModel`-per-concern pattern (`match`, `net`, `geometry`, `coverage`, `attest`, `attack`, ... are all separate sub-models already). `net.neighbours: list[str]` is the literal mesh edge list — populate it the same ring/line-topology way the existing `configs/nodes/node-NN.yaml` files do.

**`starling_geometry.navmesh.NavMesh` / `.reachability.ReachabilityModel`**
```python
NavMesh.from_geojson(path, cell_size_m=0.25) -> NavMesh
  .world_to_cell(x,y) / .cell_to_world(i,j) / .is_free(x,y) / .area_m2(mask=None) / .cells_beyond(boundary_id, reference_xy) / .render(mask=None)
ReachabilityModel(navmesh, v_max_m_s=1.6)
  .distance_field(origin_xy) -> np.ndarray   # geodesic Dijkstra, cached per origin cell — use directly for waypoint path planning
  .reachable_set(origin_xy, dt_s, extra_slack_m=0.0) -> np.ndarray(bool)
  .is_reachable(origin_xy, target_xy, dt_s, pos_sigma=0.0) -> bool
  .precompute(origin_points: list[tuple]) -> None
```

**Relevant existing tests to mirror patterns from**: `test_anti_entropy.py`, `test_gossip.py`, `test_partition_tracker.py`, `test_partition_integration.py`, `test_attacks.py`, `test_plausibility.py`, `test_reputation.py`, `test_aggregate.py`, `test_claimset.py`, `test_forks.py`, `test_resolver.py`, `test_query.py`, `test_dashboard_observer.py`, `test_config.py`, `test_navmesh.py`, `test_reachability.py`, `test_node_process.py`, `test_no_coordinator.py` (enforces node-isolation — a sim node must also respect this), `test_docker_compose.py`, `test_smoke.py`.
