# STARLING — Build State & Roadmap to 60–70%

**Status document. Source of truth for all future changes.**

| Field | Value |
|---|---|
| Spec version | Starling V3 specification, July 2026 |
| Codebase audited | `multicam-reid-master` (V1), 20 files, 1,783 LOC Python |
| Audit date | 13 September 2026 |
| Current completion vs. Starling V3 | **≈ 12 %** (see §3 rubric) |
| Target for professor checkpoint | **60 % floor / 71 % stretch** |
| Estimated effort to floor | 9–11 weeks, 1 person, focused |

---

## §0. How to use this document

This file is the *single* place where project state is recorded. The rules:

1. **Before starting work**, find the work package (§6) you're about to do. Read its acceptance criteria. Do not start work that isn't in a WP — if it isn't here, either add it here first or don't do it.
2. **After finishing work**, tick the box in §11 and update the "Actual" column in the §3 rubric. The rubric number is what you report to your professor.
3. **When you want to cut scope**, use the cut order in §10. Never cut C1, C2, or C4 (spec §4).
4. **When something in V1 breaks a Starling requirement**, it's listed in §2 with a defect ID (`D-nn`). Fixes reference those IDs.
5. Sections §4 (target architecture), §5 (data contracts), and Appendix A (algorithms) are *design commitments*. Changing them means updating this file, not just the code.

Terminology note: throughout this document **"node"** means a Starling camera node (an OS process with its own replica and no shared state), **not** a thread. V1 has no nodes in this sense. That distinction is the entire project.

---

## §1. V1 audit — what actually exists

### 1.1 File inventory

| Path | LOC | What it is | Verdict |
|---|---|---|---|
| `pipeline.py` | 157 | CLI entry point, argparse, banner, summary print | **Rewrite** — becomes a node launcher, not a monolith |
| `tracker/global_tracker.py` | 393 | `CameraWorker` (per-stream detect/track/embed) + `GlobalTracker` (orchestrator) | **Split** — `CameraWorker` mostly salvageable, `GlobalTracker` must be deleted |
| `reid/feature_extractor.py` | 104 | MobileNetV3-Small + 512-d head, cosine-ready L2-normalised output | **Keep interface, fix model** (see D-01) |
| `database/identity_store.py` | 445 | SQLite persons/sightings/events, `match_or_create`, lost promotion, operator actions | **Keep as node-local store, remove global matching** |
| `dashboard/app.py` | 684 | Streamlit: Overview, Active, Lost Registry, Search, Person Detail + timeline | **Keep and extend** — genuinely useful, biggest single reusable asset |
| `eval/__init__.py` | 0 | Empty | **Missing** — README claims `eval/metrics.py` with MOTA/IDF1/MOTP. It does not exist. |
| `utils/__init__.py` | 0 | Empty | Unused |
| `database/identities.db` | — | SQLite file, **0 persons, 0 sightings, 0 events** | Never populated. No results have been produced from this codebase yet. |
| `requirements.txt` | — | torch, torchvision, ultralytics, opencv, streamlit, pandas | Insufficient for Starling (no networking, serialization, protobuf, pytest) |
| `README.md` | — | Detailed, well written, **partly inaccurate** (see D-02, D-06) | Rewrite after WP-00 |

### 1.2 What V1 does, honestly stated

```
for each video source (sequentially, one after the other):
    for each frame:
        YOLOv8 + ByteTrack  ->  boxes + local track_ids
        crop each box       ->  MobileNetV3 -> 512-d L2-normalised vector
        for each detection:
            brute-force cosine compare against EVERY row in the persons table
            best_sim >= 0.60 ?  -> reuse that GID, blend embedding 0.9/0.1
                                -> if that GID was 'lost', log a reappearance
            else                -> INSERT a new GID
            INSERT a sightings row
        every 30 frames: mark any person unseen for 120 s as 'lost'
```

Plus a Streamlit dashboard reading the same SQLite file.

### 1.3 Mapping V1 onto the Starling spec

| Starling component (spec §5) | V1 status |
|---|---|
| Node-local detection | ✅ Present (YOLOv8) |
| Node-local MOT | ✅ Present (ByteTrack via ultralytics) |
| Appearance embedding | ⚠️ Present but **untrained head** (D-01) |
| Face embedding at chokepoints | ❌ Absent |
| Coverage self-assessment | ❌ Absent |
| Local identity store (CRDT replica) | ⚠️ A store exists, but it is **shared and centralized**, and is not a CRDT |
| Gossip of identity claims | ❌ Absent |
| Coverage attestations | ❌ Absent |
| Reputation updates | ❌ Absent |
| CRDT merge | ❌ Absent |
| Partition detection / reconciliation | ❌ Absent |
| Capability tokens / scoped query | ❌ Absent |
| Calibrated NL response | ❌ Absent |
| Raw video never leaves node | ⚠️ Vacuously true (single process), but not *structurally* enforced |

| Starling contribution | V1 coverage |
|---|---|
| C1 CRDT partition-tolerant identity | 0 % |
| C2 Byzantine-robust attestation | 0 % |
| C3 Geometry-constrained gap bridging | 0 % |
| C4 Negative evidence | 0 % |
| C5 Calibrated NL query | ~3 % (`search_by_time` + dashboard search — structured only, no NL, no uncertainty) |
| C6 Self-healing topology | 0 % |
| C7 Uniform-invariant ReID | 0 % |

**The honest summary:** V1 is a competent *centralized* multi-camera ReID pipeline with an unusually good operator dashboard. It is the **baseline that Starling's evaluation is supposed to beat** (spec §10: "Centralized BoT-SORT plus re-identification"). That is genuinely valuable — you already have the control condition built. But zero percent of the seven research contributions exists, because every one of them lives in the layer V1 doesn't have.

---

## §2. Defect register — things in V1 that are wrong or that block Starling

Severity: **B** = blocks a contribution, **C** = correctness bug, **H** = hygiene.

| ID | Sev | Defect | Evidence | Fix in |
|---|---|---|---|---|
| **D-01** | **C** | ~~**The ReID embedding head is randomly initialised and never trained.** `ReIDNet` loads ImageNet MobileNetV3-Small features, then applies `Linear(576→512) + BatchNorm1d` whose weights are random. `pretrained=(weights_path is None)` only controls the *backbone*. Output is therefore a random linear projection of ImageNet features, and `BatchNorm1d` in `.eval()` mode uses untrained running stats (mean 0, var 1). Cosine similarity on this is close to meaningless, and the 0.60 threshold is arbitrary. **This is the most serious bug in the repo.**~~ | `reid/feature_extractor.py:57-70` | **FIXED** `5b6f8fd` — `starling_perception/embedder.py` rewritten with selectable `osnet`/`pooled`/`v1_broken` backends; `v1_broken` preserved verbatim, warns loudly, and is used only by `apps/baseline.py` and the Market-1501 benchmark to quantify the defect (WP-01) |
| **D-02** | **C** | ~~**Resolved persons are still matched against**, contradicting the README's "Resolved persons are excluded from future matching". `match_or_create` selects `SELECT global_id, embedding, status FROM persons` with no status filter.~~ | `identity_store.py:150-153` | **FIXED** `98aa48f` — query now filters `WHERE status != 'resolved'` (WP-01) |
| **D-03** | **B** | ~~**Timestamps are processing wall-clock, not media time.** Every sighting is stamped `time.time()` at the moment the frame was *processed*. In `run_files` cameras are processed sequentially, so cam-1's timestamps are all *later* than cam-0's regardless of when events happened. Every temporal inference in Starling (transit time, reachability window, partition interval, lost threshold) is therefore impossible on this data.~~ | `identity_store.py:135`, `global_tracker.py:365-369` | **FIXED** `9e0f57f` — `starling_net.timebase.MediaClock` + `NodeConfig.stream_epoch`; `identity_store.py`'s write path takes explicit `t`/`now` params instead of reading `time.time()` internally (WP-02) |
| **D-04** | **B** | ~~**`GlobalTracker` is a coordinator.** One `IdentityStore`, one `sqlite3` connection, one `threading.Lock`, shared by all workers. All identity decisions are serialized through a single mutex. This is architecturally the exact thing Starling exists to eliminate.~~ | `global_tracker.py:300-345` | **FIXED (new node path)** `4d02404` — `apps/node.py`: one process, one camera, one `LocalStore`, no coordinator, no shared lock across cameras. `GlobalTracker` itself is intentionally **not deleted**: Prompt 3 (this session) overrides WP-03's original "delete it" task — `apps/baseline.py` keeps it, since baseline must stay the centralized control condition. `tests/test_no_coordinator.py` guards `GlobalTracker` from being referenced anywhere else (WP-03) |
| **D-05** | **B** | ~~**`run_files` processes cameras sequentially, not concurrently.** Camera 0 is fully consumed before camera 1 starts. No cross-camera handoff, gap, or conflict can occur in offline mode.~~ | `global_tracker.py:352-361` | **FIXED (new node path)** `b0b47a6` — `starling_perception.source.PacedSource` paces frames to real (media) time so independent node processes replaying different videos process the same media instant at the same wall-clock instant. Deliberately **not** wired into `apps/baseline.py`, which stays sequential by design (WP-02, WP-03) |
| **D-06** | **C** | ~~**EMA constants disagree with documentation.** README says `0.7 × old + 0.3 × new`; code does `0.9 × old + 0.1 × new`. Also the blended vector is stored **without re-normalising**, so the stored "embedding" gradually loses unit norm and `_cosine_sim` silently compensates.~~ | `identity_store.py:186-190` vs README | **FIXED** `98aa48f` — EMA blend now reads `ema_alpha` from config (default 0.10) and re-normalises before storing; test asserts stored norm holds at 1.0 ± 1e-5 after 100 updates (WP-01) |
| **D-07** | **C** | ~~**`_next_global_id` uses `COUNT(*)`.** If any row is ever deleted, or two processes insert concurrently, IDs collide and the `PRIMARY KEY` insert raises. Guaranteed to break the moment nodes become separate processes.~~ | `identity_store.py:47-50` | **FIXED** `4d02404` — `_next_global_id()` returns a locally-generated ULID (`python-ulid`); node claims use the same scheme, with a per-node `seq` counter persisted in a `node_meta` table so it survives restart (WP-03) |
| **D-08** | **B** | ~~**Identity is a single mean vector.** No multi-modal gallery, no per-observation retention, no confidence, no anchor, no decay. Starling's identity lifecycle (spec §3: anchor → propagate → decay → re-anchor) cannot be expressed on this representation, and neither can a CRDT — you cannot merge two means and recover what was merged.~~ | `identity_store.py` schema | **FIXED** — `starling_crdt.resolver`: the identity prototype is a small gallery of recent embeddings (`MatchConfig.gallery_size`, default 5) derived from the merged claim set each `resolve()` call, scored by best-match cosine — never a single stored mean (WP-06) |
| **D-09** | **B** | ~~**No world coordinates.** Bounding boxes are pixels. No intrinsics, no extrinsics, no floor homography, no floor plan. C3, C4, and C2's plausibility check all require metric positions and have nothing to stand on.~~ | Whole repo | **FIXED** — `starling_geometry.calibration.CameraCalibration` (image_to_floor/floor_to_image/position_sigma) + `starling_geometry.navmesh.NavMesh` (GeoJSON → free-space grid + boundaries) + `starling_geometry.reachability.ReachabilityModel` (Appendix A.2 exactly); `apps/node.py` computes `world_pos`/`pos_sigma` from calibration when configured and warns loudly, never silently, when it isn't (WP-05) |
| **D-10** | **C** | ~~**O(N) brute-force match per detection, reloading the whole table each time.** At 200 people × 25 fps × 4 cameras this reads and deserialises 200 blobs 100×/second. Will not run in real time; will hard-fail the "20 simulated nodes" scaling claim.~~ | `identity_store.py:148-165` | **FIXED** — `LocalStore.claims_since` (used by both `ClaimSet.delta_since` and WP-04's anti-entropy) is now a per-`node_id` range query against the `(node_id, seq)` index instead of a full-table scan; `resolver.resolve_incremental` additionally sweeps only a `resolve_window_s`-bounded window (an indexed `t_media` range query) during normal operation, with a full retention-window recompute only on `PARTITION_HEALED` (WP-06) |
| **D-11** | **H** | ~~**`eval/metrics.py` does not exist** despite being documented. No metric has ever been computed from this codebase.~~ | `eval/` | **FIXED** — `starling_eval/metrics.py`: tracking (HOTA/MOTA/IDF1/IDSW via TrackEval), plus hand-computed-tested functions for C1/C2/C3/C4/C6/system metrics, and an extended-MOTChallenge ground-truth format (identity + per-node visibility columns) (WP-11) |
| **D-12** | **H** | **`.gitignore` excludes the files Starling needs version-controlled**: `*.json`, `*.csv`, `*.xml`, `database/`. Your calibration YAMLs are fine but GeoJSON navmeshes, MOTChallenge ground truth, and scenario definitions would be silently untracked. Spec §7 explicitly requires these under version control. | `.gitignore` | WP-00 |
| **D-13** | **H** | No config files (everything is CLI flags), no logging (bare `print`), no tests, no Docker, no type checking, no CI. None of this is optional once there are 4–20 processes gossiping. | Whole repo | WP-00 |
| **D-14** | **C** | `save_crops=True` by default writes a JPEG **per detection per frame** to disk. On a 10-minute 4-camera run with 5 people that's ~180k files. Also a privacy problem you'd have to defend in the viva (spec §13). | `global_tracker.py:170-176` | WP-00 |
| **D-15** | **C** | ~~`promote_lost()` is called from every worker thread and from `run_live`'s loop, each acquiring the global lock; combined with per-detection matching under the same lock, throughput collapses as person count rises.~~ | `global_tracker.py:238-240, 380-384` | **FIXED (new node path)** `4d02404` — no cross-node locks exist any more by construction: one node = one camera = one process, so there is no other thread to contend with `LocalStore`'s lock. `apps/baseline.py` is unchanged (it still has this problem, deliberately — it's the centralized control condition the decentralized architecture is compared against) (WP-03) |

---

## §3. What "60 %" means — the completion rubric

Percentage-of-project is meaningless unless you define the denominator. This rubric is the denominator. Weights are assigned by *effort × contribution to the seven claims*, not by lines of code.

| # | Area | Weight | V1 now | 60 % floor | 71 % stretch |
|---|---|---:|---:|---:|---:|
| A | Perception: detect, track, embed, benchmark | 10 | 7 | 9 | 10 |
| B | Node runtime: process isolation, config, Docker | 8 | 1 | 7 | 8 |
| C | Transport: gossip, anti-entropy, partition harness | 8 | 0 | 7 | 7 |
| D | **C1** CRDT identity representation + merge | 15 | 11 | 11 | 12 |
| E | **C2** Reputation, plausibility, Byzantine defense | 12 | 0 | 7 | 8 |
| F | **C4** Coverage attestation + negative evidence | 12 | 6 | 6 | 8 |
| G | **C3** Calibration, navmesh, reachability | 10 | 0 | 6 | 7 |
| H | **C6** Topology learning | 5 | 0 | 3 | 4 |
| I | **C5** Query layer | 6 | 1 | 1 | 2 |
| J | **C7** Uniform-invariant ReID | 4 | 0 | 0 | 0 |
| K | Evaluation harness, metrics, ground truth | 7 | 0 | 4 | 4 |
| L | Demo + dashboard | 3 | 2 | 3 | 3 |
| | **TOTAL** | **100** | **28** | **64** | **73** |

**Read this carefully:** the floor column deliberately gives **zero** to C7 and **near-zero** to C5. That is correct and intentional. Spec §4 puts C7 first in the cut order and §15 warns explicitly against treating the query interface as the project. You reach 60 % by going *deep* on C1/C2/C4, not by touching all seven shallowly.

**What you tell your professor at the checkpoint:**
> "Sixty percent means the distributed core is real: identity is a genuinely replicated CRDT object, nodes are separate processes with no shared state, the network can be partitioned on demand and the system reconverges, a lying node is detected and down-weighted by its neighbours with no coordinator, and attested absence measurably shrinks the candidate region. It is demonstrated against the centralized baseline, which is the V1 system, and the failure-mode comparison is measured, not asserted."

That sentence is defensible. "We added seven features partially" is not.

---

## §4. Target architecture at the 60 % milestone

### 4.1 The one structural change everything else follows from

```
V1 (now)                              STARLING (target)
─────────────────────────             ──────────────────────────────────
                                      node-0 process
GlobalTracker (1 process)               ├ camera source
 ├ CameraWorker 0 ─┐                    ├ detect/track/embed
 ├ CameraWorker 1 ─┼→ ONE SQLite        ├ coverage self-assessment
 ├ CameraWorker 2 ─┤   + ONE lock       ├ own CRDT replica (own SQLite)
 └ CameraWorker 3 ─┘   = coordinator    └ gossip socket ──┐
                                                          │
                                      node-1 process ─────┼── gossip mesh
                                      node-2 process ─────┤   (netem between)
                                      node-3 process ─────┘

                                      dashboard: read-only observer,
                                      subscribes to gossip, owns nothing
```

**The rule to enforce mechanically:** no module under `starling_node/` may import from another node's store. If you can delete the network and the system still works, you built the wrong thing.

### 4.2 The core design idea (write this down; it is your paper's mechanism)

> **Replicate the evidence, derive the decision.**

Do not replicate identity *assignments* — those conflict and force you to pick a winner. Replicate the **set of signed observation claims**, which is a grow-only set and therefore trivially a CRDT (union is commutative, associative, idempotent). Then make the identity assignment a **pure deterministic function** of the merged claim set.

Consequences, all of which you get for free:
- Any two replicas holding the same claim set compute the same assignment → strong eventual consistency, no coordinator.
- A partition is just two replicas with different subsets. Merge = set union. No reconciliation protocol needed.
- A conflict is not a merge failure; it's the resolver observing two mutually-exclusive claim chains for one identity, and emitting an **`IdentityFork`** object instead of guessing (spec §6 Scene 5).
- Byzantine defense composes cleanly: reputation weights are inputs to the resolver, not to the replication layer.
- Reproducibility for the paper: given a claim log, the assignment is replayable exactly.

This is defensible, novel in the CV context, and — importantly — it is *implementable by one student*, unlike inventing a bespoke probabilistic CRDT from scratch.

### 4.3 Target repository layout

```
starling/
├── packages/
│   ├── starling_perception/      ← from V1 reid/ + CameraWorker detect+track
│   │   ├── detector.py
│   │   ├── tracker.py
│   │   ├── embedder.py           ← fixed ReIDNet (D-01)
│   │   ├── face.py               ← SCRFD + AdaFace, chokepoint only
│   │   └── coverage.py           ← C4 self-assessment
│   ├── starling_geometry/        ← C3
│   │   ├── calibration.py        ← intrinsics/extrinsics/homography, OpenCV
│   │   ├── navmesh.py            ← floor polygon → occupancy grid
│   │   └── reachability.py       ← speed-bounded reachable set
│   ├── starling_crdt/            ← C1
│   │   ├── claims.py             ← ClaimSet (G-Set), version vectors
│   │   ├── resolver.py           ← deterministic assignment function
│   │   ├── forks.py              ← IdentityFork lifecycle
│   │   └── merge.py              ← delta sync / anti-entropy
│   ├── starling_consensus/       ← C2
│   │   ├── reputation.py
│   │   ├── plausibility.py
│   │   ├── aggregate.py          ← reputation-weighted, trimmed mean, Krum
│   │   └── attacks.py            ← fabricate / suppress / replay injectors
│   ├── starling_attest/          ← C4
│   │   ├── attestation.py
│   │   └── negative_evidence.py  ← candidate-region belief update
│   ├── starling_topology/        ← C6
│   ├── starling_query/           ← C5 (skeleton only at 60 %)
│   ├── starling_net/             ← gossip transport, HLC clock, signing
│   ├── starling_proto/           ← message schemas (protobuf)
│   └── starling_eval/            ← metrics, scenario runner, TrackEval bridge
├── apps/
│   ├── node.py                   ← ONE node process (replaces pipeline.py)
│   ├── baseline.py               ← V1 centralized, preserved as control
│   └── dashboard/                ← extended Streamlit (from V1)
├── deploy/
│   ├── docker-compose.yml        ← N node containers
│   └── netem/                    ← partition scripts
├── configs/
│   ├── nodes/node-00.yaml …      ← per-node config
│   └── calib/cam-00.yaml …       ← OpenCV YAML per physical camera
├── scenarios/                    ← declarative YAML experiments
├── data/
│   ├── floorplan/site.geojson
│   └── gt/                       ← MOTChallenge + identity + visibility cols
├── tests/
└── STARLING_BUILD_STATE.md       ← this file
```

---

## §5. Data contracts — freeze these on day one

Spec §7 says standardise formats immediately. These are the schemas. Put them in `starling_proto/` as `.proto` and generate Python; do not hand-roll dicts.

### 5.1 IdentityClaim — 1–4 KB, the main wire object

```protobuf
message IdentityClaim {
  bytes    claim_id       = 1;  // 16B: hash(node_id, seq)
  uint32   node_id        = 2;
  uint64   seq            = 3;  // per-node monotonic; (node_id,seq) is the CRDT key
  HLC      t_start        = 4;  // hybrid logical clock, media time
  HLC      t_end          = 5;
  uint32   local_track_id = 6;  // node-scoped ONLY. never global.
  bytes    embedding      = 7;  // 512 × int8, scale factor separate = 516 B
  float    embed_scale    = 8;
  Point2D  world_pos      = 9;  // metres, floor frame, from homography
  float    pos_sigma      = 10; // metres, 1σ
  AnchorType anchor       = 11; // FACE_ANCHOR | PROPAGATED | UNANCHORED
  string   identity_ref   = 12; // set only when anchor == FACE_ANCHOR
  HLC      last_anchor_t  = 13;
  float    confidence     = 14; // [0,1], per §Appendix A.4
  float    quality        = 15; // crop quality: blur, size, truncation
  bytes    signature      = 16; // ed25519 over all above
}
```

Hard rules:
- `local_track_id` is **never** interpreted by another node. Cross-node identity exists only as a resolver output.
- `world_pos` is **mandatory**. A claim without it is unverifiable and must be rejected — this is what makes C2's plausibility check possible.
- Claims are **immutable and append-only**. Never update a claim; supersede it with a new one.

### 5.2 CoverageAttestation — < 200 B, the C4 object

```protobuf
message CoverageAttestation {
  uint32 node_id            = 1;
  HLC    t_start            = 2;
  HLC    t_end              = 3;
  repeated uint32 region_ids = 4;  // navmesh regions / boundary segments claimed covered
  float  occlusion_ratio    = 5;   // [0,1] fraction of ROI obscured
  float  illumination_score = 6;   // [0,1]
  float  detector_health    = 7;   // [0,1]
  bool   crossing_observed  = 8;   // false = the negative-evidence assertion
  float  attest_confidence  = 9;   // = min(1-occl, illum, health)
  bytes  signature          = 10;
}
```

An attestation with `crossing_observed = false` and `attest_confidence ≥ τ_attest` is the **only** admissible form of negative evidence. Silence is never evidence. This single rule is C4.

### 5.3 ReputationUpdate (< 100 B) and TopologyObservation (< 500 B)

```protobuf
message ReputationUpdate {
  uint32 from_node = 1;  uint32 about_node = 2;
  HLC window_start = 3;  HLC window_end = 4;
  float score = 5;                        // observer's local [0,1] assessment
  repeated bytes evidence_claim_ids = 6;  // ≤ 3, for auditability
  bytes signature = 7;
}
message TopologyObservation {
  uint32 node_a = 1; uint32 node_b = 2;
  float transit_secs = 3; float handoff_confidence = 4;
  bytes signature = 5;
}
```

### 5.4 Non-negotiable wire invariant

`starling_proto` defines **no message containing image data**. Enforce it with a test that asserts no field of any message exceeds 8 KB and that no `bytes` field is ever assigned an encoded image. Then show `iftop`/`tcpdump` during the demo (spec §11). Your privacy claim becomes a measurement rather than a promise.

---

## §6. Work packages

Effort is in **focused days** for one person. Dependencies are hard.

---

### WP-00 — Repo restructure and engineering hygiene
**Weight contribution:** enables everything · **Effort:** 3 d · **Depends on:** nothing

Goal: the repo stops being a script collection and becomes something 4–20 processes can be launched from reproducibly.

Tasks:
1. Create the §4.3 layout. Move V1 code into `packages/starling_perception/` and `apps/baseline.py`. **Preserve V1 verbatim as `apps/baseline.py`** — it is your centralized control condition for every experiment in spec §10. Tag the current commit `v1-baseline` before touching anything.
2. Fix `.gitignore` (D-12): remove blanket `*.json`, `*.csv`, `*.xml`, `database/`. Add targeted ignores (`data/videos/`, `results/`, `*.db`) and explicitly un-ignore `configs/`, `scenarios/`, `data/floorplan/`, `data/gt/`.
3. Replace all `print` with `structlog` JSON logging tagged with `node_id`. Non-negotiable: with 20 processes, interleaved prints are unreadable, and you need machine-parseable logs for §8's metric collection.
4. Pydantic config models loaded from `configs/nodes/node-NN.yaml`. Every threshold in the codebase (`0.60`, `0.35`, `120`, `30`) becomes a config field with a documented default.
5. `pytest` + `hypothesis` scaffolding, `ruff`, `mypy` on `starling_crdt` and `starling_consensus` at minimum.
6. Fix D-14: `save_crops` defaults to `False`; when enabled, save at most one crop per identity per N seconds, into a per-node directory.

**Acceptance:** `pytest` runs green (even with 2 trivial tests); `python apps/baseline.py --videos a.mp4 b.mp4` reproduces exact V1 behaviour; `ruff check` clean.

---

### WP-01 — Fix and benchmark the perception layer
**Weight:** A: 7 → 9 · **Effort:** 5 d · **Depends on:** WP-00

This is the highest-value bug fix in the project. Everything downstream assumes embeddings are meaningful. Right now they are not (D-01).

Tasks:
1. **Fix the embedder.** Choose one, in preference order:
   - **(a) Recommended:** replace `ReIDNet` with a properly trained ReID model. `torchreid`'s OSNet weights, or FastReID's `market_bot_R50`, or `osnet_x0_25` ONNX weights (small enough for a Jetson Orin Nano, spec §8). Keep the exact `FeatureExtractor.extract(crops) -> (N,512)` interface so nothing else changes.
   - **(b) Fallback if install pain:** delete the untrained head entirely, use L2-normalised pooled backbone features (576-d) directly. Worse than (a) but *correct*, unlike the current state.
   - **(c) Only if you have GPU time:** train the head on Market-1501 with cross-entropy + triplet.
2. **Benchmark it.** Report Rank-1 and mAP on Market-1501 and MSMT17. This is spec Phase 1's exit criterion and you have not met it yet. Also **run the benchmark on the current V1 embedder and report both numbers** — the delta is a genuinely useful figure for your report and quantifies D-01.
3. Fix D-02 (exclude `resolved` from matching), D-06 (re-normalise after EMA; reconcile constants with docs).
4. Calibrate `sim_threshold` from data instead of guessing: sweep it, plot the ROC on a held-out multi-camera pair, pick the operating point, record it in config with the justification.
5. Split `CameraWorker._process_frame` into `detector.py` / `tracker.py` / `embedder.py` with clean interfaces. Add a `quality` score per crop (blur variance, pixel height, truncation) — WP-09 needs it.

**Acceptance:** a table in `docs/perception_baseline.md` with Rank-1/mAP for old vs. new embedder on Market-1501; threshold chosen from a plotted ROC; unit test asserting embeddings are unit-norm and that two crops of the same person score higher than two crops of different people on a fixture.

---

### WP-02 — The time model (fix D-03, D-05)
**Weight:** B · **Effort:** 3 d · **Depends on:** WP-00

Nothing distributed works until all nodes agree what time it is. Spec §8 flags this explicitly and §15 warns most of your hours go here.

Tasks:
1. **Media time, not processing time.** Every frame carries `t_media = stream_epoch + frame_idx / fps` for files, or the RTSP RTP timestamp for live. Replace every `time.time()` in the identity path with the frame's media time.
2. **Hybrid Logical Clocks.** Implement `HLC` in `starling_net/clock.py`: `(physical_ms, logical_counter, node_id)`. Update rule on send/receive per Kulkarni et al. This gives you timestamps that are both physically meaningful (needed for reachability) and causally consistent (needed for deterministic merge ordering). ~80 lines.
3. **Deterministic total order** for the resolver: sort claims by `(hlc.physical, hlc.logical, node_id, seq)`. This is what makes §4.2's "same claim set → same assignment" literally true. Write a property test for it.
4. NTP on all machines; add `scripts/measure_drift.py` that logs pairwise offset every minute. Record measured drift in your report — reviewers ask.
5. **Concurrent playback.** Replace sequential `run_files` (D-05) with a paced reader per node that plays back at wall-clock-aligned media time, so cam-0 t=30 s and cam-1 t=30 s are processed at the same real moment. Add a `--speed` multiplier for fast experiments.

**Acceptance:** two nodes fed two synchronised videos produce claims whose media timestamps align within one frame period; property test proves the total order is a strict total order and is permutation-invariant; measured NTP drift documented.

---

### WP-03 — Node process isolation (fix D-04, D-05, D-07, D-15)
**Weight:** B: 1 → 7 · **Effort:** 4 d · **Depends on:** WP-00, WP-02

Goal: delete the coordinator.

Tasks:
1. Write `apps/node.py`: one process = one camera = one `IdentityStore` at `data/nodes/node-NN/local.db` = one gossip socket. Takes `--config configs/nodes/node-NN.yaml`.
2. **Delete `GlobalTracker`.** Not refactor — delete. Its only legitimate remaining function (launching N processes) belongs to Docker Compose.
3. Fix D-07: global IDs become `ULID` or `uuid4`, generated locally, never derived from a table count. Node-scoped `local_track_id` stays an int.
4. Fix D-15: no cross-node locks exist any more by construction. Within a node, the store lock stays but now protects one camera's worth of writes.
5. Refactor `IdentityStore`: strip `match_or_create`'s global search. It becomes `append_claim()` + `local_view()`. Matching moves to `starling_crdt/resolver.py` where it belongs.
6. `deploy/docker-compose.yml` bringing up N node containers + 1 dashboard on a user-defined bridge network. Each node mounts one video file.

**Acceptance:** `docker compose up` starts 4 nodes; `docker stop node-2` leaves the other three running and producing claims; grep proves no module imports another node's DB path; each node writes only to its own directory.

---

### WP-04 — Gossip transport and the partition harness
**Weight:** C: 0 → 7 · **Effort:** 5 d · **Depends on:** WP-03

Tasks:
1. **Transport:** ZeroMQ PUB/SUB mesh (`pyzmq`) is the pragmatic choice — every node PUBs to its own port and SUBs to its configured neighbours. Spec §9 offers ROS 2 / Cyclone DDS or libp2p; **do not use ROS 2 unless you already know it**, the learning cost is a week you don't have. Note the choice and rationale in your report; reviewers accept ZeroMQ if you justify it.
2. **Neighbour set from config**, not broadcast-to-all. Starling's whole framing (§Cover: "each bird tracks only its handful of nearest neighbours") requires a partial mesh. A full mesh is a hidden coordinator.
3. **Anti-entropy / delta sync:** each node keeps a version vector `{node_id: max_seq}`. Periodically (2 s) it gossips its VV to a random neighbour; the neighbour replies with claims the sender is missing. This is what makes reconnection-after-partition converge without a special protocol. ~150 lines.
4. **Signing:** ed25519 keypair per node (`pynacl`), keys enrolled in config. Verify every inbound message; drop and log unsigned/invalid. Required for C2 to mean anything (otherwise a liar can just forge another node's identity, and Sybil resistance is out of scope — state that assumption explicitly in your threat model).
5. **Partition harness:** `scenarios/*.yaml` → `deploy/netem/apply.py`. Declarative:
   ```yaml
   name: east_wing_drop
   duration_s: 600
   events:
     - t: 120, action: partition, groups: [[0,1],[2,3]]
     - t: 300, action: heal
     - t: 400, action: degrade, nodes: [2], loss_pct: 30, latency_ms: 200
   ```
   Implement with `tc netem` inside containers (needs `NET_ADMIN` cap) or iptables DROP rules between container IPs. iptables is simpler and more reliable for hard partitions; netem for loss/latency. Use both.
6. **Byte accounting:** every node counts bytes sent/received by message type. This directly produces the "bytes per node-hour" metric in spec §10 and the privacy visual in §11.

**Acceptance:** 4 nodes exchange claims; `scenarios/east_wing_drop.yaml` splits them into two groups at t=120 and heals at t=300, verified by the byte counters going to zero across the cut and recovering; after heal, both sides' claim sets are identical (assert set equality of `claim_id`s); bytes/node-hour reported.

---

### WP-05 — Calibration, floor plan, navmesh, reachability (C3 foundation)
**Weight:** G: 0 → 6 · **Effort:** 5 d · **Depends on:** WP-00

Spec §7 is blunt about this: three of seven contributions rest on a two-hour task that is easy to do badly. Budget more than two hours.

Tasks:
1. **Intrinsics:** OpenCV checkerboard, per camera, output `configs/calib/cam-NN.yaml`. **Assert reprojection error < 0.5 px** in a test and fail loudly above 1.0 px.
2. **Floor homography:** four or more measured floor points per camera → `cv2.findHomography`. Map each detection's **bottom-centre of bbox** to floor metres. Validate empirically: walk a measured 10 m line and check the reconstructed length is within 0.3 m.
3. **Floor plan → navmesh:** hand-draw your actual test space (a corridor, two rooms, whatever your rig is) as a GeoJSON polygon with obstacle holes. Rasterise to a 0.25 m occupancy grid. **Take the 2D fallback now, not later** — spec §4 and §14 both pre-commit to it and §15 calls 3D the highest-risk lowest-value component. Decide once, here, and never revisit.
4. **Reachability:** multi-source Dijkstra on the grid with 8-connectivity, edge cost = distance. `reachable_set(origin, Δt, v_max=1.6 m/s) → boolean mask`. Precompute geodesic distance fields from each camera FOV exit point so runtime queries are a threshold, not a search. See Appendix A.2.
5. `pos_sigma` estimation: propagate homography uncertainty + bbox jitter to a metres-scale 1σ. Rough is fine; having *a* number matters because the plausibility check needs a tolerance.

**Acceptance:** `pytest tests/test_calibration.py` asserts reprojection error bounds; the 10 m walk test documented with measured error; `reachable_set` unit-tested against hand-computed cases (open corridor, blocked by obstacle, Δt=0); a rendered PNG of the reachable set at Δt = 5/15/60 s in `docs/`.

---

### WP-06 — C1: the CRDT identity layer ⭐ CORE
**Weight:** D: 1 → 11 · **Effort:** 10 d · **Depends on:** WP-02, WP-03, WP-04, WP-05

The largest single package. Spec §4 says never cut it. Budget the three weeks of distributed-systems reading (spec §14 risk table) *before* starting, or in parallel with WP-04.

Tasks:
1. **`ClaimSet`** — a grow-only set keyed by `(node_id, seq)`, backed by the node's SQLite. Operations: `add`, `merge(other) = union`, `version_vector()`, `delta_since(vv)`. Add **time-bounded pruning** (drop claims older than the retention window) — this doubles as spec §13's "short retention" privacy measure. Note honestly in your report that pruning weakens the pure-CRDT guarantee to *eventual consistency within the retention window*; that's a defensible engineering choice and stating it is better than hiding it.
2. **Property tests with `hypothesis`** — this is cheap credibility and reviewers love it:
   - commutativity: `merge(a,b) == merge(b,a)`
   - associativity: `merge(merge(a,b),c) == merge(a,merge(b,c))`
   - idempotence: `merge(a,a) == a`
   - **convergence:** for random claim sets and *all* delivery orderings, final state is identical.
3. **The resolver** (`resolver.py`) — pure function `ClaimSet × Reputation × Geometry → (Assignment, ForkSet)`:
   - sort claims into the deterministic total order (WP-02)
   - sweep forward, maintaining per-identity trajectory hypotheses
   - for each claim, candidate identities = those whose last confirmed position **passes the reachability gate** (WP-05) for the elapsed Δt
   - among gated candidates, score by appearance cosine × topology prior (WP-07) × source reputation (WP-10)
   - assign if the best score clears threshold **and** the margin over second-best clears a separation threshold; otherwise leave unassigned
   - **must be deterministic**: no dict-iteration-order dependence, no RNG, no wall-clock reads. Test by running it twice on shuffled input and asserting byte-identical output.
4. **`IdentityFork`** — when two claim chains bind one `identity_ref` to spatially incompatible trajectories:
   - if reachability rejects one branch → record the resolution *and its reason* (this is spec §6 Scene 5)
   - if both remain reachable → **the fork stays open**, both branches are retained, and it is surfaced to the operator as an ambiguity. Do not resolve by score. This behaviour is a *feature you demo*, not a bug.
   - forks close only on a re-anchor (face at a chokepoint) or explicit operator action.
5. **Partition awareness:** each node tracks per-neighbour liveness (missed gossip rounds). Local state carries a `coverage_completeness` flag = fraction of expected neighbours currently reachable. Every answer the node gives is annotated with it.
6. **Recompute strategy:** re-running the full resolver on every claim is O(n²) and will not hold. Implement incremental resolution over a sliding window (e.g. last 5 minutes of claims), with full recompute triggered on merge-after-partition. Measure and report **time-to-reconverge** — it's a spec §10 metric.

**Acceptance:**
- all four property tests pass on 1000 hypothesis cases
- scripted partition (WP-04): two nodes diverge for 3 min, reconnect, and both replicas reach byte-identical assignments; time-to-reconverge logged
- a scenario deliberately constructed so both branches are reachable leaves a fork **open** (asserted in a test)
- a scenario where one branch is unreachable closes with the reachability reason recorded
- unresolved-fork rate reported over a full run

---

### WP-07 — C6: topology learning
**Weight:** H: 0 → 3 · **Effort:** 3 d · **Depends on:** WP-06

Cheap, and it supplies priors that C3 and C4 need (spec §4: "Why include it").

Tasks:
1. Collect `TopologyObservation` from high-confidence handoffs (margin above a threshold, and preferably anchored within the last T seconds).
2. Per node-pair, fit a transit-time distribution — log-normal is a good default for pedestrian transit. Maintain online (Welford for μ/σ of log-transit).
3. Edge exists if observation count > `k_min` **and** the fitted distribution is tighter than the null (a spurious pair produces a near-uniform spread). Reject weak edges.
4. Expose `topology_prior(node_a, node_b, Δt) → [0,1]` consumed by the resolver.
5. Change detection: CUSUM or a windowed KS test on transit times. A shift flags "environment changed or node misbehaving" — feed it into WP-10 as a weak reputation signal.
6. Evaluate: graph edit distance to a hand-labelled ground-truth topology; re-convergence time after you physically move a camera (or swap two video streams in simulation, which is the free version).

**Acceptance:** GED vs. ground truth reported; a plot of learned transit distribution vs. true transit for at least one pair; re-convergence time after a simulated camera move.

---

### WP-08 — C3: reachability gating in the resolver
**Weight:** G: 6 → 6 (co-delivered with WP-05) · **Effort:** 2 d · **Depends on:** WP-05, WP-06

Tasks:
1. Wire `reachable_set` into the resolver as a **hard gate**: candidates outside the reachable region are rejected regardless of appearance similarity (spec §4 C3 claim, stated exactly this way).
2. Ablation switch in config: `gate: {none | time_prior | reachability}` so you can produce the three-way comparison the evaluation plan demands (appearance-only / hand-tuned time prior / Starling).
3. Evaluate: cross-gap ReID accuracy versus gap duration (2 s, 5 s, 15 s, 30 s, 60 s, 120 s). This plot is spec Phase 6's exit criterion and is one of your strongest figures.

**Acceptance:** accuracy-vs-gap-duration plot with three curves; a test proving a geometrically impossible match is rejected even at cosine similarity 0.99.

---

### WP-09 — C4: coverage attestation and negative evidence ⭐ FLAGSHIP
**Weight:** F: 0 → 6 · **Effort:** 7 d · **Depends on:** WP-05, WP-06

Spec §4 calls this the strongest new idea and the least likely to be scooped, with the highest value per hour. Spec §15 also flags it as genuinely uncertain — coverage self-assessment is itself a hard perception problem. Both are true. Build the honest version.

Tasks:
1. **Occlusion estimation.** Per node, define the ROI polygon(s) it claims to cover (projected onto the floor via the homography). Estimate the obscured fraction:
   - static occupancy from a median-filtered background model
   - dynamic occluders: run the detector for `truck`/`car` classes as forklift proxies, plus large unexplained foreground blobs
   - `occlusion_ratio` = fraction of the ROI's floor projection covered
2. **Illumination quality.** Mean luma in the ROI, fraction of clipped pixels (<10 or >245), and local contrast. Map to `[0,1]` with a documented curve. Test it by physically dimming the lights and checking the score drops.
3. **Detector health.** Achieved FPS / target FPS, dropped-frame ratio, and drift in the detection-confidence distribution vs. a rolling baseline (a KS statistic works). Blend to `[0,1]`.
4. **The attestation rule.** `attest_confidence = min(1 − occlusion_ratio, illumination_score, detector_health)`. Emit `crossing_observed = false` only when `attest_confidence ≥ τ_attest`. **When below threshold, emit nothing.** Silence must never be readable as absence — that's the three-way ambiguity in spec §4 C4 and getting it wrong is the whole failure mode.
5. **Negative-evidence fusion.** Maintain a candidate-belief mask over the navmesh grid per unlocated identity:
   - initialise from last confirmed position
   - each timestep, dilate by `v_max · Δt` (geodesic, obstacles respected)
   - for each admissible attestation covering a boundary segment with `crossing_observed=false`, **zero the belief beyond that boundary**
   - renormalise; report `candidate_region_area_m²`
   See Appendix A.3.
6. **Composition with C2.** A node that attests healthy coverage during an interval in which ≥2 other nodes corroborate a crossing it should have seen loses reputation. This is "lying by omission becomes detectable" (spec §4 C4), and it is the sentence that makes C4 and C2 one contribution rather than two.
7. **Metrics:** candidate region reduction (% area vs. positive-evidence-only), **false exclusion rate** (how often you excluded the region the person was actually in — this is the safety-critical number and must be reported prominently), and attestation accuracy (attested-healthy intervals where a corroborated event was in fact missed).

**Acceptance:** a scenario where a person enters a dead zone and the candidate region shrinks measurably when attestations are enabled vs. disabled; false exclusion rate reported with a confidence interval; a test where a node with `occlusion_ratio=0.6` emits no attestation and the candidate region correctly does *not* shrink.

---

### WP-10 — C2: reputation and Byzantine robustness ⭐ CORE
**Weight:** E: 0 → 7 · **Effort:** 7 d · **Depends on:** WP-05, WP-06

Tasks:
1. **Write the threat model down first**, in `docs/threat_model.md`, before coding. Spec §4 C2 demands it stated explicitly. Contents:
   - up to `f` of `n` nodes arbitrarily faulty
   - attack classes: **fabricate** (claims for people who aren't there), **suppress** (withhold real observations, incl. false attestations), **replay** (re-emit stale claims with new timestamps)
   - **out of scope, stated:** Sybil attacks (node keys are enrolled at commissioning), physical camera tampering, collusion above f. Saying what you don't defend against is a strength.
2. **Plausibility check** (`plausibility.py`): given a claim and the corroborated recent state, score:
   - reachability: is `world_pos` inside the reachable set from the last corroborated position over Δt? (hard fail if not)
   - kinematics: implied speed vs. `v_max`
   - corroboration: do neighbours with overlapping coverage report a consistent position?
   - freshness: HLC vs. local clock, replay-window rejection
3. **Reputation** (`reputation.py`): `R_j ← clip((1−α)·R_j + α·s_j, R_min, 1.0)`, `α ≈ 0.05`, `R_min ≈ 0.05` so a node can recover. Reputation is **local per observer** and gossiped as opinions, never as a global scalar — a global reputation value would be a coordinator by the back door. Aggregate others' opinions with a median (itself Byzantine-robust). See Appendix A.5.
4. **Robust aggregation** (`aggregate.py`): reputation-weighted position fusion, plus trimmed mean and Krum as the comparison arms. Spec §9 lists all three; implementing them is ~60 lines each and gives you a real ablation.
5. **Attack injection** (`attacks.py`): a node config flag turns any node malicious at runtime with a chosen attack class and intensity. Must be **switchable live** — this is the demo's "Make node 3 lie" button (spec §11 segment 5).
6. **The headline experiment:** accuracy vs. fraction of malicious nodes, sweeping `f/n` from 0 to 0.5, for each attack class, against an unweighted-consensus baseline. **Report where the scheme breaks**, as the spec explicitly instructs. A curve that degrades gracefully to a stated breaking point is a much better result than a claim of universal robustness.

**Acceptance:** the accuracy-vs-`f/n` curve exists for all three attack classes with the unweighted baseline overlaid; false-claim rejection rate reported; a fabricating node's reputation demonstrably decays within a bounded number of claims; `docs/threat_model.md` complete.

---

### WP-11 — Evaluation harness and metrics (fix D-11)
**Weight:** K: 0 → 4 · **Effort:** 6 d · **Depends on:** WP-04

You currently have **zero** measured numbers. Fix this early — build the harness by week 4, not week 9, because every WP after it needs to report into it.

Tasks:
1. **Ground truth.** MOTChallenge format extended with two columns per spec §7: identity, and per-node visibility (needed to evaluate C4). Sources, in order of cost:
   - **free & exact:** synthetic. Isaac Sim if you can run it; otherwise **MultiviewX** (synthetic, calibrated, has GT) or **WILDTRACK** (real, calibrated, has GT) get you multi-camera data with calibration already solved. They're overlapping-view datasets, so *simulate the dead zone by masking a region of each view* — a legitimate and reproducible way to manufacture a gap.
   - **cheap:** your own 2-camera rig, ~20 minutes annotated (spec §7 rates this "High" pain — it is).
   - Partitions and Byzantine behaviour are **always** injected, never annotated, so they cost nothing.
2. **Metrics module** (`starling_eval/metrics.py`) — actually write the file the README has been claiming exists:
   - tracking: IDF1, MOTA, HOTA, ID switches. **Use `TrackEval` rather than hand-rolling** — hand-rolled HOTA is a week of subtle bugs.
   - C1: identity consistency after merge, time-to-reconverge, unresolved fork rate
   - C2: accuracy vs. malicious fraction, false-claim rejection rate
   - C3: cross-gap accuracy vs. gap duration
   - C4: candidate region reduction, false exclusion rate, attestation accuracy
   - C6: graph edit distance, re-convergence time
   - system: bytes per node-hour, end-to-end claim latency
3. **Scenario runner** (`starling_eval/runner.py`): YAML in → compose up → netem schedule → run → collect per-node logs → merge into one timeline → compute metrics → write JSON + push to Weights & Biases. One command, fully reproducible. This is what makes your ablations cheap enough to actually run.
4. **The three-way experiment** from spec §10, as a first-class scenario: (i) centralized baseline `apps/baseline.py`, (ii) Starling healthy, (iii) Starling partitioned + 1 Byzantine node. Same input, same GT, one table. Spec calls this the single experiment most likely to convince a reviewer. Make it `scenarios/headline.yaml`.

**Acceptance:** `python -m starling_eval.runner scenarios/headline.yaml` runs end to end and emits a results JSON plus a markdown table; the centralized baseline visibly fails during the partition segment while Starling degrades.

---

### WP-12 — Chokepoint anchoring and the confidence model
**Weight:** A/D · **Effort:** 4 d · **Depends on:** WP-01, WP-06

Spec §3 makes an explicit design-honesty commitment here: face recognition only at chokepoints, body ReID everywhere else, confidence decay as the consequence of taking that seriously. Implement the honesty, not just the face model.

Tasks:
1. `face.py`: SCRFD detect + AdaFace embed (spec §9 prefers AdaFace over ArcFace for low-quality imagery). Runs **only** on nodes flagged `is_chokepoint: true` in config.
2. Enrollment: 10–20 images per person, captured at the chokepoint camera under its real lighting (spec §7 — not from a phone). **Team members with signed consent only.** Start ethics paperwork now if you haven't (spec §13, §14 — listed as the most common cause of a stalled biometric project).
3. Confidence decay model (Appendix A.4): `c(t) = c_anchor · exp(−(t − t_anchor)/τ) · Π_i q_i`, where `q_i` is per-handoff quality from the resolver's score margin, crowding, and occlusion. Monotonically non-increasing between anchors, restored on re-anchor.
4. Re-anchor retroactively validates or corrects the intervening track (spec §3) — on a face anchor, re-run the resolver over the window since the last anchor with the anchor as a hard constraint, and record any corrections as events.
5. **Privacy:** store face templates only in protected form (spec §13). At minimum, a keyed random projection / bio-hashing scheme so a leaked template isn't invertible, with the key held per node. Document it; it is a listed privacy-by-design measure that doubles as research value.

**Acceptance:** a track anchored at a chokepoint shows monotonic confidence decay across handoffs and a step restoration at re-anchor, plotted; a retroactive correction demonstrated on at least one scenario; template protection documented.

---

### WP-13 — Dashboard V2
**Weight:** L: 2 → 3 · **Effort:** 4 d · **Depends on:** WP-04, WP-09, WP-10

V1's dashboard is your best reusable asset. It needs to stop reading one shared DB and start being a **read-only gossip observer** that owns nothing.

Tasks:
1. Subscribe to gossip as a passive node. It must have no privileged access — if the dashboard can see everything, you've rebuilt the central database and a reviewer will say so.
2. Floor-plan view: navmesh, camera FOVs, live positions, and **the candidate-belief region rendered as a shrinking heatmap** (spec §11 segment 3 calls this your best visual).
3. Per-node health strip: online/partitioned, reputation bar, attestation confidence, bytes/s.
4. Fork panel: open identity forks surfaced as ambiguities requiring operator attention.
5. **"Make node N lie"** control (spec §11 segment 5) — a big obvious button a judge can press.
6. Live byte counter by message type, with a "raw video: 0 bytes" line (spec §11).
7. Keep V1's Lost Registry, Search, Person Detail and event timeline — they're good and they cost nothing to retain.

**Acceptance:** dashboard runs with zero DB access, driven purely by gossip; candidate region animates during a dead-zone scenario; the lie button flips a node's behaviour live and its reputation bar visibly drops.

---

### WP-14 — C5 query layer (skeleton only)
**Weight:** I: 1 → 1 · **Effort:** 2 d · **Depends on:** WP-06

**Deliberately minimal at 60 %.** Spec §15 explicitly warns that treating the query interface as the project is a failure mode, and §4 says a rough CLI over a system that survives partitions beats a polished chat interface over one that doesn't. Do not exceed this scope before the checkpoint.

Tasks:
1. A CLI: `starling query "where is P-003"` that propagates over gossip with a hop budget, collects partial answers, and prints a **structured** result — confirmed vs. inferred, last anchor time, which nodes were unreachable during the window.
2. **No LLM yet.** Template the response. The template *already* demonstrates the property that matters: separating confirmed from inferred and stating the extent of its own blindness.
3. Build the **unanswerable-query benchmark** file now, even without a model to run it against — 30–50 queries where refusal is the correct answer. Cheap to write, and it's the harness the LLM work slots into later.
4. Stub capability tokens: a signed token scoping purpose/area/time-window, verified by each node before answering. ~50 lines, and it demonstrates the decentralized authorization idea without the threshold-approval machinery.

**Acceptance:** a CLI query returns a structured answer that explicitly names unreachable nodes; a query about a partitioned region returns "incomplete" rather than a confident answer; benchmark file exists with ≥30 entries.

---

## §7. Schedule to the 60 % checkpoint

10 weeks, assuming ~5 focused days/week. Compress by dropping WP-07 and WP-12 first (they cost ~7 days and ~7 rubric points, landing you at ~57 — so only do this if the deadline is hard).

| Week | Work packages | Milestone |
|---|---|---|
| 1 | WP-00, start WP-01 | Repo restructured, V1 preserved as tagged baseline, tests run |
| 2 | WP-01, WP-02 | **First real numbers ever produced by this project**: Market-1501 Rank-1/mAP. Media-time + HLC landed |
| 3 | WP-03, start WP-05 | 4 separate node processes in Docker, no shared state. Calibration session done |
| 4 | WP-04, WP-05 | Gossip mesh working; partition scriptable and verified; navmesh + reachability tested |
| 5 | WP-11 | Evaluation harness live. Everything after this reports numbers automatically |
| 6–7 | **WP-06** | **C1 delivered.** Partition → diverge → reconnect → identical replicas. Forks stay open when they should |
| 8 | WP-08, WP-09 | C3 gate wired; C4 attestation emitting; candidate region shrinks measurably |
| 9 | **WP-10** | **C2 delivered.** Accuracy-vs-malicious-fraction curve exists |
| 10 | WP-13, WP-14, WP-07 if time | Dashboard V2, query CLI stub, headline three-way experiment run and written up |

**Two scheduling rules learned from the spec's own risk table:**
- Spend weeks 1–4 reading CRDTs and Byzantine consensus *in parallel* with the engineering WPs. Spec §14 budgets three weeks for this and calls it out as not-CV-coursework. If you arrive at week 6 without having read Shapiro et al. on CRDTs and something on reputation systems, WP-06 will take 15 days instead of 10.
- Start ethics clearance in **week 1** regardless of everything else (spec §13, §14, §15 all say this independently). It gates WP-12 and nothing else can unblock it.

---

## §8. What you actually show at the checkpoint

A working live demo of spec §11 segments **1 through 5** (skip 6 and 7 — the query and the full numbers slide are post-60 %):

1. **Side-by-side**: `apps/baseline.py` (V1, centralized) on the left, Starling on the right, same input. Both work. Boring on purpose.
2. **Normal handoff**: person walks camera A → camera B. Both track.
3. **The dead zone**: person walks into the gap. Baseline: track ends. Starling: candidate region shrinks live on the floor plan as reachability and attested absence rule out territory.
4. **The unplug**: physically pull a cable (or `docker network disconnect`). Baseline dies. Starling continues, annotated "partitioned, reduced coverage". Reconnect; show the merge and a fork being resolved — or left open, which is the more interesting outcome.
5. **The liar**: press the button. False claim rejected on geometric grounds; reputation bar drops.

Plus a two-page results appendix: Market-1501 baseline, time-to-reconverge, accuracy vs. malicious fraction, candidate region reduction, bytes/node-hour vs. centralized video streaming.

If you can do those five segments live and hand over those five numbers, "60 %" is not a claim anyone will argue with.

---

## §9. Things V1 does that you must consciously *keep*

Not everything needs replacing. Protect these:

- **The Streamlit dashboard.** 684 lines of genuinely useful operator UI. Extend it (WP-13), don't rewrite it.
- **The event-log pattern.** `events` table with `first_seen | lost | reappeared | resolved | note` is exactly the right shape for the tamper-evident audit log spec §13 wants. Add signatures and it becomes a contribution.
- **The lost-person registry concept.** Maps cleanly onto Starling's unlocated-identity + candidate-region reasoning. Keep the operator affordances (resolve / reactivate / note).
- **`apps/baseline.py`.** Your control condition. Every experiment needs it. Never let it rot — run it in CI on a fixture video.
- **The clean `FeatureExtractor` interface.** `extract(crops) -> (N,512)` is the right abstraction; only the model behind it is wrong.

---

## §10. Risks and the cut order

**Cut order (from spec §4, enforced at every phase boundary):**
> C7 first → then the 3D component of C3 (already pre-cut to 2D in WP-05) → then C6 (WP-07).
> **Never cut C1 (WP-06), C2 (WP-10), or C4 (WP-09).**

| Risk | Sev | Mitigation |
|---|---|---|
| WP-06 (CRDT) overruns; probabilistic identity doesn't fit standard types | **High** | §4.2's "replicate evidence, derive decision" is specifically chosen to avoid inventing a bespoke probabilistic CRDT. If it still overruns, ship the G-Set + deterministic resolver *without* incremental recomputation (full recompute over a window) — slower but correct, and correctness is what's evaluated |
| Calibration done badly, silently breaking C2/C3/C4 | **High** | WP-05 asserts reprojection error in a test. Re-verify after any camera moves. Spec §14 flags this as three contributions resting on a two-hour task |
| Coverage self-assessment (C4) is unreliable → attested absence untrustworthy | **High** | Spec §15 admits this openly. Mitigation is honesty: report attestation accuracy as a first-class metric and set `τ_attest` conservatively. **A well-measured partial result here is publishable; an overclaimed one is not** |
| No ground truth → no metrics → no checkpoint evidence | **High** | WP-11 in week 5, before the hard WPs. Start with MultiviewX/WILDTRACK so calibration and GT are free |
| Ethics clearance blocks face data | **High** | Week 1. Build against public datasets and synthetic in parallel; C1/C2/C4 need no face data at all |
| Distributed-systems learning curve | **Med** | Read in weeks 1–4 in parallel. Don't start WP-06 cold |
| Docker networking eats days | **Med** | Spec §15 predicts exactly this. Use iptables for hard partitions (simple, reliable) and netem only for loss/latency |
| Scope creep across seven contributions | **High** | This file is the mechanism. If it isn't a WP, it isn't work |
| A competing decentralized system publishes first | **Med** | Lead with C4 (WP-09); spec §14 rates it least likely to be duplicated |

---

## §11. Progress tracker

Update this as you go. The rubric in §3 is derived from these.

### Perception & foundations
- [x] WP-00 Repo restructure, gitignore fix, logging, config, tests scaffold
- [x] WP-01 ReID embedder fixed (D-01) and benchmark harness written (Rank-1/Rank-5/mAP on Market-1501; running it against real data and filling in numbers is the user's follow-up, not part of this session)
- [x] WP-01 `sim_threshold` calibration harness (`threshold_sweep.py`) chooses from a plotted ROC at FPR=0.01, not a guess — running it against real data to pick the final number is the user's follow-up
- [x] WP-02 Media timestamps replace `time.time()` everywhere (D-03) — node path only; `apps/baseline.py` passes `time.time()` explicitly at its own call sites, unchanged behaviour
- [x] WP-02 HLC implemented; deterministic total order property-tested
- [x] WP-02 Concurrent playback replaces sequential `run_files` (D-05) — new `PacedSource`, not wired into frozen `apps/baseline.py`
- [x] WP-05 Intrinsics + extrinsics + floor homography, reprojection error asserted — `from_yaml` refuses >1.0px; scripts are interactive and untested this session (real checkerboard/click sessions against physical cameras are explicitly the user's follow-up)
- [ ] WP-05 10 m walk validation < 0.3 m error — `scripts/validate_calibration.py` exists and is ready; running it against a real camera/video is the user's follow-up, not exercised this session
- [x] WP-05 GeoJSON floor plan → occupancy grid navmesh — `data/floorplan/demo_site.geojson`, two zones + 3m gap + two labelled boundaries
- [x] WP-05 `reachable_set()` implemented and unit-tested — hand-computed cases (open-corridor radius, enclosed pocket, wall detour, dt-monotonicity, precompute-consistency)

### Distributed core
- [x] WP-03 `apps/node.py` (D-04) — `GlobalTracker` intentionally kept in `apps/baseline.py` only (this session's rule 2 overrides WP-03's original "delete it": baseline must stay centralized); `tests/test_no_coordinator.py` guards it from appearing anywhere else
- [x] WP-03 Per-node SQLite; ULID global/claim IDs (D-07)
- [x] WP-03 `docker compose config` validates 4 isolated nodes + dashboard, per-node volumes verified to never cross-mount (`tests/test_docker_compose.py`); `docker compose up` itself not run in this session
- [x] WP-04 ZeroMQ gossip mesh with configured neighbour sets — verified live with 4 local `GossipNode`s over the real ring topology in `configs/nodes/local/`: each node received exactly its 2 ring neighbours' claims, zero drops
- [x] WP-04 Version-vector anti-entropy / delta sync — `tests/test_anti_entropy.py`, no real transport needed (on_digest/on_delta are pure)
- [x] WP-04 ed25519 signing on all messages — every `Envelope` payload type (including `VVDigest`/`VVDelta`, a WP-04 addition) carries a `signature` field verified by `GossipNode`; unsigned/malformed/unenrolled-sender messages are dropped and counted
- [x] WP-04 Declarative partition scenarios via iptables/netem — `scenarios/{healthy,east_wing_drop,lossy}.yaml`; `deploy/netem/apply.py --dry-run` verified; real execution needs a running `docker compose up`, not exercised this session
- [x] WP-04 Per-message-type byte accounting — `GossipNode.stats()`, confirmed increasing in the live 4-node smoke test above

### C1 — CRDT identity ⭐
- [x] WP-06 `ClaimSet` G-Set with delta sync and retention pruning
- [x] WP-06 Hypothesis property tests: commutativity, associativity, idempotence, convergence
- [x] WP-06 Deterministic resolver (reachability-gated assignment)
- [x] WP-06 `IdentityFork` — stays open when both branches reachable
- [x] WP-06 Partition → reconnect → byte-identical replicas
- [x] WP-06 Time-to-reconverge measured; unresolved fork rate reported — from the synthetic-claim-stream integration test (`docs/results_c1.md`); `scenarios/east_wing_drop.yaml`'s own numbers need real multi-camera video, which doesn't exist in this repo yet — the user's follow-up

### C2 — Byzantine ⭐
- [ ] WP-10 `docs/threat_model.md` written (incl. explicit out-of-scope)
- [ ] WP-10 Plausibility check (reachability, kinematics, corroboration, freshness)
- [ ] WP-10 Local reputation with EWMA + recovery floor
- [ ] WP-10 Robust aggregation: weighted / trimmed mean / Krum
- [ ] WP-10 Attack injection: fabricate, suppress, replay — switchable live
- [ ] WP-10 Accuracy vs. `f/n` curve, all attack classes, breaking point stated

### C4 — Negative evidence ⭐
- [x] WP-09 Occlusion ratio estimation — `starling_perception/coverage.py`: static background model + occluder-class detections + unexplained-foreground blobs, unioned in floor space
- [x] WP-09 Illumination quality score — documented exposure/clip/contrast blend, all weights in `CoverageConfig`
- [x] WP-09 Detector health self-diagnostic — FPS ratio, dropped-frame ratio, KS drift on the detection-confidence distribution
- [x] WP-09 Attestation emission rule (silence ≠ absence) — `starling_attest/attestation.py::Attestor.tick`; below `tau_attest` emits `None`, never a low-score attestation
- [x] WP-09 Candidate-belief region with geodesic dilation + boundary zeroing — `starling_attest/negative_evidence.py::CandidateBelief`; `NavMesh.cells_beyond` (new WP-05 addition) precomputes per-boundary side components
- [x] WP-09 Composition with C2: false attestation costs reputation — `detect_omission()` emits the signal; WP-10 (Prompt 8) is what will consume it into an actual reputation update
- [x] WP-09 Region reduction, **false exclusion rate**, attestation accuracy reported — `scripts/run_deadzone_experiment.py` → `docs/results_c4.md`, incl. the `tau_attest` trade-off curve

### C3 / C6 / C5 / support
- [ ] WP-08 Reachability as a hard gate in the resolver, with ablation switch
- [ ] WP-08 Accuracy vs. gap-duration plot (3 curves)
- [ ] WP-07 Topology learning + GED vs. ground truth
- [ ] WP-12 Chokepoint face anchoring (SCRFD + AdaFace)
- [ ] WP-12 Confidence decay model, plotted
- [ ] WP-12 Protected biometric templates
- [ ] WP-14 Query CLI with structured, uncertainty-annotated output
- [ ] WP-14 Unanswerable-query benchmark (≥30 entries)
- [ ] WP-14 Capability token stub

### Evaluation & demo
- [x] WP-11 Ground truth in extended MOTChallenge format — `ExtendedGTRow`/`write_extended_mot_gt`/`read_extended_mot_gt`
- [x] WP-11 `starling_eval/metrics.py` exists (fixes D-11) with TrackEval bridge
- [x] WP-11 Scenario runner, one command, W&B logging — `--local` verified end to end (real subprocess nodes, results.json/results.md/timeline.jsonl written); Docker mode and `--compare baseline` implemented but not exercised this session; W&B push is a no-op unless `WANDB_API_KEY` is set, never fails the run
- [ ] WP-11 **Headline three-way experiment** run: baseline / healthy / partitioned+Byzantine — needs WP-06 (CRDT) and WP-10 (Byzantine) first; out of scope for this session
- [ ] WP-13 Dashboard as read-only gossip observer
- [ ] WP-13 Candidate-region heatmap
- [ ] WP-13 "Make node N lie" button
- [ ] Demo segments 1–5 rehearsed ≥10 times

### Compliance
- [ ] Ethics clearance submitted (week 1)
- [ ] Consent forms for all enrolled team members
- [ ] `docs/privacy_design.md` mapping spec §13 measures to implemented code

---

## §12. Do not do these

Explicit anti-goals. Each one has cost previous projects a semester.

1. **Do not build the LLM query interface before week 10.** Spec §15 names this as a failure mode. It demos well and contributes nothing unless evaluated.
2. **Do not attempt 3D Gaussian reconstruction.** Pre-committed to 2D navmesh in WP-05. Spec §4, §9, §14, and §15 all independently say this.
3. **Do not buy hardware to unblock research.** Spec §8: Tier 0 (existing PC + Docker + netem + synthetic video) delivers C1, C2, C4, C5, C6 fully. Four cheap cameras and one spare laptop is the whole shopping list.
4. **Do not let the dashboard read a shared database.** The moment it does, you have a central store and the reviewer's first question destroys the claim.
5. **Do not make gossip a full mesh.** Neighbours only. A full mesh is a coordinator wearing a costume.
6. **Do not implement C7.** First in the cut order. Zero weight in the 60 % target.
7. **Do not hand-roll HOTA.** Use TrackEval.
8. **Do not resolve identity forks by picking the higher score.** Leaving the fork open *is* the contribution. Spec §11's Q&A table has a prepared answer for exactly this question.
9. **Do not report a metric you haven't measured.** V1's README already claims an `eval/metrics.py` that doesn't exist (D-11). Do not let that pattern continue into the report — it is the fastest way to lose a viva.

---

## Appendix A — Algorithm specifications

### A.1 Deterministic claim ordering (WP-02)
```python
def claim_order_key(c: IdentityClaim) -> tuple:
    return (c.t_start.physical_ms, c.t_start.logical, c.node_id, c.seq)
```
`(node_id, seq)` is globally unique, so the order is total. No ties, no RNG, no dict order. Test: shuffle then sort → identical sequence, 1000 trials.

### A.2 Speed-bounded reachable set (WP-05)
```
precompute (once, per FOV exit point e):
    D_e = geodesic distance field over the free-space grid via multi-source Dijkstra
          (8-connected, diagonal cost √2 · cell, obstacles impassable)

query reachable_set(e, dt, v_max=1.6):
    return D_e <= v_max * dt          # boolean mask, O(1) threshold
```
Tolerance: add `pos_sigma` and one cell of grid slack to the radius. Being slightly permissive is far safer than a false exclusion.

### A.3 Negative-evidence belief update (WP-09)
```
B_0        = δ(last confirmed position), over the free-space grid
each step:
  B ← geodesic_dilate(B, v_max · Δt)                       # where could they have gone
  for each admissible attestation a (attest_conf ≥ τ_attest, crossing_observed == False):
      B[cells beyond boundary(a)] ← 0                      # they did not pass here
  for each positive observation o:
      B ← B · likelihood(o)                                # standard positive evidence
  B ← B / sum(B)
report: area(B > ε) in m²
```
`τ_attest` is a tuned parameter — sweep it and report the region-reduction / false-exclusion trade-off curve. That curve is a better result than any single number.

### A.4 Confidence decay (WP-12)
```
c(t) = c_anchor · exp(−(t − t_anchor) / τ) · Π_i q_i

q_i = handoff quality ∈ (0,1] for the i-th handoff since the anchor
    = w1·margin_norm  +  w2·(1 − crowding)  +  w3·(1 − occlusion)
margin_norm = (best_score − second_best_score) clipped to [0,1]
τ ≈ 300 s  (tune; report the value used)
```
Monotonically non-increasing between anchors. Reset to `c_anchor` on face re-anchor.

### A.5 Reputation (WP-10)
```
per observer i, about node j:
    s_ij(claim) = 1  if plausibility passes
                = 0  if it fails
    R_ij ← clip((1 − α)·R_ij + α·s_ij,  R_min, 1.0)      α=0.05, R_min=0.05

aggregate opinion about j, used by the resolver:
    R_j = median over i of gossiped R_ij        # median = Byzantine-robust
claim weight in aggregation: w = R_j · claim.confidence · claim.quality
```
Never compute or store a single global reputation scalar. Each node holds its own view; the median is taken locally at use time.

---

## Appendix B — Reading list before WP-06

Budget these into weeks 1–4 (spec §14 allocates three weeks; it is not padding).

- Shapiro, Preguiça, Baquero, Zawirski — *A Comprehensive Study of Convergent and Commutative Replicated Data Types* (2011). The foundational CRDT reference. Read the G-Set / OR-Set sections closely.
- Almeida, Shoker, Baquero — *Delta State Replicated Data Types* (2018). This is how you implement anti-entropy efficiently in WP-04.
- Kulkarni et al. — *Logical Physical Clocks* (2014). HLC, ~10 pages, directly implementable.
- Blanchard, El Mhamdi, Guerraoui, Stainer — *Krum* (NIPS 2017). Byzantine-robust aggregation; the ideas transfer from gradients to position claims.
- Yin et al. — *Byzantine-Robust Distributed Learning: trimmed mean / median* (ICML 2018).
- Coko-SLAM (2026) and MAGS-SLAM (2026), from the spec's §1.2 post-mortem — read them to be able to state precisely why Starling is not in their space when a reviewer asks.

---

*Document version 1.0 — 13 September 2026. Audited against `multicam-reid-master` (20 files, 1,783 LOC) and Starling V3 specification (July 2026). Update the §3 rubric and §11 tracker with every merged change; treat everything else as a design commitment requiring a deliberate revision.*
