# C1 results — partition-tolerant identity CRDT

Measured from `tests/test_partition_integration.py` (WP-06 Part 4c/4d),
the headline C1 test: four in-process nodes, a scripted synthetic claim
stream (no video needed — per the WP-06 prompt, this is a legitimate
substitute for a full video scenario, not a placeholder for one), a
partition into `[0,1]` vs. `[2,3]`, and a heal. Numbers below are printed
directly from that harness (`_Mesh.converge_within_current_partition`),
not estimated.

## What `scenarios/east_wing_drop.yaml` would add, and why it isn't run here

`scenarios/east_wing_drop.yaml` (the scenario this session was asked to
run via `starling_eval.runner`) requires real multi-camera video at
`data/videos/cam{0..3}.mp4`; `data/videos/` is currently empty. The
runner can run end-to-end against a *synthetic* video fixture (see
`tests/test_runner.py`), but a synthetic fixture here is a plain moving
rectangle — YOLO (COCO-trained) will not detect it as a person, so the
run would produce zero claims and a meaningless (trivially instant, zero
claims) reconvergence number. Producing the real `east_wing_drop` numbers
needs actual multi-camera footage of people crossing between the two
wings; that is the user's follow-up, the same pattern already used
elsewhere in this project for anything needing real data (see e.g.
`docs/perception_baseline.md`, `STARLING_BUILD_STATE.md` §11's WP-01/WP-05
entries).

## Time-to-reconverge

Scenario: 4 claims accepted and fully converged before partitioning; then
12 more claims (3 per node) accepted independently during the partition,
converging only within each side; then heal.

| Metric | Value |
|---|---|
| Claims per replica after heal | 16 |
| Anti-entropy rounds to reconverge after heal | 2 |
| Wall-clock time to reconverge after heal | < 1 ms |
| Post-heal replica state | byte-identical `claim_id` sets **and** byte-identical `Assignment`s across all 4 replicas |

The sub-millisecond wall-clock figure reflects the pure, in-process
`AntiEntropy.on_digest`/`on_delta` calls this test drives directly (see
the test file's module docstring for why — PUB/SUB has no
replay/persistence, so pure forward gossip alone cannot guarantee
convergence even without a partition; the anti-entropy mechanism is what
does, and calling it directly makes the convergence assertion reliable
rather than timing-dependent). It is a measurement of the CRDT merge and
resolver's correctness and round count, not of real network latency —
a deployed scenario over real sockets/netem would report round-trip time
on top of this.

## Unresolved fork rate

Scenario: `tests/test_partition_integration.py::
test_partition_creates_genuinely_ambiguous_binding_fork_stays_open_after_heal`
— node 0 (group A) anchors identity `P-100` and then propagates it via
ordinary appearance-matched evidence; while partitioned, node 2 (group B),
with no visibility into group A's trajectory, anchors the *same*
identity_ref `P-100` to a position that turns out — once the claim sets
are merged after heal — to be simultaneously plausible with group A's
trajectory (both within `v_max * elapsed` of the identity's last
confirmed position; see `starling_crdt.forks.evaluate_reachability`).

| Metric | Value |
|---|---|
| Forks detected after heal | 1 |
| Forks left OPEN | 1 |
| Unresolved fork rate | 100% (1/1) |

This is a single deliberately-constructed scenario, not a sampled
population — it demonstrates the mechanism (CLAUDE.md rule 6: never
resolve a fork by picking the higher score), not a statistical claim
about how often forks occur in a real deployment. The complementary case
— `tests/test_resolver.py::
test_conflicting_face_anchor_with_one_impossible_branch_auto_resolves`
— demonstrates the other direction: when only one branch remains
physically plausible, the fork auto-resolves via `RESOLVED_REACHABILITY`
with the specific implied speed named in the reason (0 of 1 forks left
open there). A real per-deployment unresolved-fork rate needs a run over
actual multi-camera footage with genuine handoff ambiguity, which is the
same real-video dependency `east_wing_drop.yaml` has above.
