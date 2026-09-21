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
    258 passed, 4 deselected. Starting Step 3 (the simulator package).

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
- [x] **Step 2 — Warehouse floor plan** — commit `<pending, see git log
      after next commit>`
  - [x] `data/floorplan/warehouse_demo.geojson` (4 zones, 7 racking
        obstacles, one deliberate blind aisle with both exits labelled)
  - [x] Loads via `NavMesh.from_geojson`; reachability verified across
        the blind aisle
  - [x] `tests/test_warehouse_demo_floorplan.py` (5 tests, all passing)
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

**What's half-done**: nothing mid-flight — Steps 1 and 2 are fully
committed before this checkpoint.

**Exact next action**: build `packages/starling_sim/` (Step 3) — the
largest remaining chunk of work. Read the "Step 3" section of the original
task prompt for the full spec (worker waypoint routes over the navmesh,
per-worker identity embeddings, per-node observation delivery via
per-node ZMQ topics, coverage/occlusion events driving attestations, a
YAML scenario file). Use `data/floorplan/warehouse_demo.geojson` (Step 2)
as the floor plan and its `camera_zone`/`node_id` properties to assign
each node's zone; the blind aisle (boundary_id 1 = node 0's exit,
boundary_id 2 = node 1's exit) is the scripted route for the dead-zone
demo moment. See §11 for exact API signatures already surveyed
(`starling_net.anti_entropy.AntiEntropy`, `starling_consensus.attacks
.ControlServer`, `starling_proto` envelope kinds, `starling_attest
.negative_evidence.CandidateBelief`, `starling_store.identity_store
.LocalStore`, `starling_geometry.reachability.ReachabilityModel`) so this
isn't re-derived from scratch.

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
