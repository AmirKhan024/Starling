# The live 3D world demo

The original demo fed nodes ready-made observations from a 2D simulator: each
"detection" already carried a world position and a random identity vector.
The live world demo replaces that with a **virtual warehouse that cameras
actually film**. Every Starling node now receives only JPEG frames from its own
camera and has to work everything out from pixels. The rest of the stack —
signed claims, ring gossip, the CRDT, the resolver, negative evidence,
reputation, the query layer — is unchanged and runs on what those cameras
really see.

```
                      configs/world/warehouse.yaml (single source of truth)
                                         │
      ┌──────────────────────────────────┼───────────────────────────────────┐
      ▼                                  ▼                                   ▼
 world server (apps/world/server.py)   camera rig (apps/world/rig.py)   3D viewer (world.html)
 simulation clock, 4 employees,  ◀──▶  headless Chromium + three.js:    what the judge watches
 2 AGVs, faults; per-camera            renders each camera's view,      (same scene code)
 JPEG topics + ground truth            returns JPEG frames
      │ cam:0 │ cam:1 │ cam:2 │ cam:3        (each node subscribes to its OWN camera only)
      ▼       ▼       ▼       ▼
   node 0  node 1  node 2  node 3      apps/node.py, source "world": YOLO11s + ByteTrack,
      ╲      │        │      ╱         appearance signature, homography, gate verification,
       ╲── signed gossip on a ring ──╱ pixel-based coverage self-assessment → signed claims
                     │                 and attestations
                     ▼
     dashboard (read-only observer): manager view  /   technical view /engineer
```

Run it:

```bash
pip install -r requirements-world.txt
python -m playwright install chromium
python scripts/run_world_demo.py          # opens the 3D world, manager and technical views
```

## What is real, what is simulated

| | Real (the actual Starling code, on real pixels) | Simulated (the "physical world") |
|---|---|---|
| People | — | Four procedurally built, animated 3D employees walking navmesh paths on daily routines (`starling_world.sim`) |
| Cameras | Calibration: the floor homography each node uses is generated from the camera pose (reprojection error ~1e-13 px) | The cameras themselves: three.js renders their views |
| Detection | YOLO11s person detector on each 1280×720 frame, ByteTrack local tracking | — |
| Position | Foot point → calibrated homography; head ray when the feet are hidden | — |
| Identity | Clothing-colour appearance signature; verification against an enrolled registry at the entrance gate; FACE_ANCHOR claims; the CRDT resolver across cameras | Enrollment images are rendered views of each employee ("badge photos") |
| Coverage (C4) | The pixel-based `CoverageAssessor` (occlusion, illumination, detector health) decides if a node may attest | Faults are physical events: a tarp over a lens |
| Network | Real processes, real signed ZeroMQ gossip on a ring, real anti-entropy | The partition button is an application-level drop (as in the 2D demo) |

Ground truth (where people really are) is used for exactly two things: drawing
faint "truth" rings on the technical view, and grading. Nothing a manager sees
comes from it. Names come only from an employee being verified at the
entrance gate — a signed claim made by node 0 from its own pixels.

## Measured performance

`scripts/calibrate_world_appearance.py` (held-out renders) →
[`results_world_perception.md`](results_world_perception.md):
detection recall per frame, localisation error, the ROC behind the resolver's
match threshold, gate-verification and recognition accuracy.

`scripts/evaluate_world_run.py` grades a whole live run offline: the world is
deterministic, so every claim in a node's replica can be labelled with the
person who was really there. On a 4-minute run (2,441 claims): identity purity
99.4% (claims attributed to the right person), every identity named by an
employee anchor named correctly (23/23 resolver windows), 1.0–1.25 identities
per person per window, 10% of claims left unassigned (ambiguous, so not
guessed), median localisation error 0.32 m against the true position.

`scripts/review_world_demo.py` drives every demo moment on the running system
and writes `review/world/review_summary.md` with screenshots.

## Things changed in the core to make real perception work

Each is off by default, so the 2D demo and its tests are unchanged:

* **Anchor adoption** (`starling_crdt.resolver._adopt_unanchored`,
  `MatchConfig.anchor_adopt_radius_m`). A person tracked for a few frames
  before being verified would otherwise exist as two near-identical
  hypotheses; every later claim then ties between them and both freeze. A
  face anchor now absorbs the one unanchored hypothesis that is plainly the
  same person (recent, co-located, appearance above threshold with margin) —
  never an ambiguous one, never across an open fork.
* **C2 × C4 contradiction** (`starling_consensus.contradiction`,
  `PlausibilityConfig.attested_absence_check`). A claim inside another
  camera's zone, which that camera confidently attested covered and saw
  nobody near, fails plausibility. Silence (no attestation, or one below
  `tau_attest`) is never evidence. Nodes now merge gossiped attestations for
  this. Two safeguards for honest cameras, both measured on live runs:
  the "someone was there" tolerance grows with both claims' stated position
  uncertainty, and repeated contradictions of the SAME track within 15 s
  count once against reputation (a neighbour that missed someone for a few
  seconds must not make an honest camera look like a liar — every fabricated
  claim carries a fresh track id, so each lie still counts). The fabricate
  attack's lies inside the liar's own zone contradict nobody, so a liar's
  reputation settles around 0.8 rather than near 0; honest cameras stay at
  ~1.0, and the manager alert fires below 0.85.
* **Node diagnostics routes** (`ControlServer(extra_get=...)`): a world node
  serves `/perception` and `/preview.jpg` (its last frame, annotated) on its
  local operator endpoint. Frames never enter gossip.

## Demo script

1. **Shift start.** The four employees arrive one by one, stop at the gate and
   are verified (manager view: *Entrance check-ins*). Technical view: the
   gate camera's own view shows `VERIFIED EMP-1041 0.97`.
2. **Tracking.** People move between the four cameras' zones; identities and
   names persist; errors vs truth are shown per identity.
3. **Dead zone (C4).** Priya picks stock in the camera-less aisles. The manager
   view says she *must still be inside*; the technical view shows her search
   area (tens of m²) against what reachability alone allows (hundreds).
4. **Cover a lens.** In the 3D world, *Cover CAM 1 lens*. Node 1 notices from
   its own pixels and stops attesting; the manager is told its area cannot be
   vouched for; any search region now leaks into that zone.
5. **Split the network** {0,1} | {2,3}, then **Heal**: both sides keep
   working; replicas reconverge.
6. **Make a node lie.** Its fabricated sightings contradict other cameras'
   attested absence; its reputation, as its peers report it, falls.
7. **Break.** Send someone on a break: they are shown as *left through the
   staff entrance*, and verified again when they come back.
8. **Query.** `where is Priya` (safety) is answered; the productivity purpose
   is refused.

## Requirements and limits

* Memory: keep ~4 GB free. Below that the launcher starts in `--light`
  mode (cameras at 2 frames/s) by itself. A node that cannot keep up stops
  attesting (detector health), so C4 and the C2 x C4 check degrade, and a
  gate check-in can be missed. The dashboard shows an "overloaded" banner
  from the nodes' own frame rates.
* CPU: four nodes each run YOLO11s at 3 frames/s (~100–250 ms per frame on a
  laptop i7). `--fast` uses YOLO11n for slower machines (lower recall).
* Memory: each node commits ~2 GB once torch is loaded; the launcher starts
  them one after another.
* GPU: the camera rig uses the GPU through ANGLE/D3D11 when available
  (`--software-gl` forces CPU rendering).
* The appearance signature is a clothing-colour descriptor: it separates
  these four uniforms well (cross-camera AUC ≈ 0.997) but is not a general
  re-identification model. The enrolled registry is per deployment.

## Showing it to an audience

Presenter playbook and answers to judges' questions: [JUDGE_DEMO.md](JUDGE_DEMO.md).

| Page | What it shows |
|---|---|
| `/tour` | Guided demo: 16 chapters, each with plain words, a "say this" line, live action buttons and live proofs that turn green |
| `/` | Manager view + **Ask Starling** (where is X / is anyone in <area> / unknown people / arrival / roll call), the **emergency roll call**, unknown-person markers and a pop-up alert |
| `/compare` | Traditional system vs Starling side by side: same detections, two architectures, "what if" buttons and a live scoreboard |
| `/network` | The camera network itself: real gossip messages animated as they are overheard, every camera answering "who is where?" from its own copy (fingerprints), bytes on the wire vs the cameras' video, and a real centralised ingest server side by side, with kill switches for it and for any camera |
| `/how` | How it works, central vs Starling, the measured scaling experiment ([results_scale.md](results_scale.md)) and honest limits |

How the new pieces stay honest:

* **Ask every camera.** `GET /replica` on a node's operator endpoint
  (`apps/node.py`, `ReplicaAnswerer`) resolves that node's own replica over a
  pinned media-time window, then returns a fingerprint of the assignment.
  Every camera answers for a moment a few seconds back, so all copies already
  hold the same sightings. Claims are resolved in their canonical wire form;
  see STATUS.md §1c for the precision bug this exposed.
* **Purpose limitation.** The node itself verifies the caller's signed
  capability token with its own keys. A productivity question is refused by
  the query layer *and* by every camera.
* **The unknown person.** `VisitorSim` (`POST /api/control/visitor`) is never
  enrolled and never passes the gate. The manager view flags an unnamed
  identity once it has enough sightings. It does not flag one that is:
  * at the entrance gate (about to be verified);
  * on top of a named employee (a split track);
  * reported only by an untrusted camera (a liar's fabrication).

  A track that breaks and re-forms nearby keeps its number.
* **The centralised server** (`apps/world/central_ingest.py`, port 7010) is
  not part of Starling. It is a real process that receives the four real
  camera streams and measures them. Killing it shows the single point of
  failure; a network split cuts the cameras on the far side off from it.
