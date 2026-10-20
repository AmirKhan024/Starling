# Scalability — Starling's gossip + CRDT layer at N = 4 … 64 nodes

Measured, not modelled: for each N, **N separate OS processes** each ran
Starling's real networking stack (`apps/bench_node.py`). Each process had
its own SQLite replica (`LocalStore`), its own signed ZeroMQ gossip socket
(`GossipNode`) on its own port, its own ed25519 key, the real gap-aware
`AntiEntropy`, and a configured neighbour set of fixed degree 4. No camera
and no perception are involved. Every node produced synthetic claims at
the live world node's measured rate, with the live world claim's byte
shape. Only the centralised comparison is computed rather than measured,
and it is labelled as such.

Raw numbers: `docs/results_scale.json` (read by the dashboard).
Figures: `docs/scale_bandwidth.png` and `docs/scale_latency.png`.

## What was run

```
python scripts/run_scale_experiment.py          # settings: configs/scale/experiment.yaml
python scripts/run_scale_experiment.py --plot-only   # redraw the PNGs from the JSON
```

- **Nodes.** `apps/bench_node.py` is `apps/node.py` with the camera and the
  perception removed. Claims are written by
  `LocalStore.append_local_observation`, built into wire messages by
  `record_to_claim_proto` + `make_claim_envelope`, and signed and sent by
  `GossipNode.publish`. Incoming claims are merged by
  `append_remote_claims`. The `vv_digest`/`vv_delta` handling is a
  line-for-line copy of `apps/node.py`'s `_on_gossip_message`
  (`on_digest`, then byte-budgeted `chunk_by_bytes` replies, then
  `on_delta`). `AntiEntropy.tick()` runs every 4/3 s, the cadence of the
  world node's housekeeping (every 4 frames at 3 fps).
- **How claims spread.** `GossipNode` does not relay. A received claim is
  merged and never re-published, so a new claim reaches only its origin's
  direct neighbours by the immediate signed push. Every node further away
  gets it only through anti-entropy. This is the real system's behaviour,
  and it is what was measured.
- **Claims.** 2.6 claims/s per node (the live world node made 965 claims
  in ~370 s; `review/world/review_summary.md`), with the gap between
  claims jittered uniformly by ±50%. Each claim carries a 96-d float32
  appearance descriptor (384 B), a floor position and sigma, a node-local
  track id, detector confidence, crop quality and, on ~2% of claims, a
  FACE_ANCHOR employee id. These are the fields `_run_world` stores. One
  signed claim envelope is **549 B** on the wire (measured mean,
  545–566 B).
- **Topology.** Ring ±1 plus one chord pair ±k, a circulant graph. k is
  chosen deterministically to minimise the diameter. Degree is 4 for
  N ≥ 6. N = 4 uses the plain ring (degree 2), as the 4-camera demo does,
  because degree 4 at N ≤ 5 would be a full mesh. The chords chosen were
  k = 2, 4, 7, 18 and 10 for N = 8, 16, 32, 48 and 64.
- **Procedure.** For each N:
  - Start all processes, wait until each reports ready, then wait 4 s more
    for the ZeroMQ connect handshakes.
  - Produce claims for 40 s. Bytes and CPU are measured over this window,
    from each node's own counters.
  - Stop producing and wait until every replica reports the same claim-set
    digest. The digest is a hash of `claim_ranges()`, i.e. of the
    (node_id, seq) CRDT keys.
  - Stop the nodes. Each node then writes its first-seen table: the wall
    time each claim first appeared in that replica. Wall time is used
    here, in the measurement harness only.
- **Latency.** Measured per claim, from its creation at the origin until it
  is in every replica. All processes share one machine clock.
- **Bytes.** Bytes are `GossipNode.stats()` envelope bytes, counted after
  signature verification. The out figure is publish bytes × the node's
  subscriber count, because a ZeroMQ PUB sends each message once per
  connected subscriber. As a check, total inbound equalled total wire
  outbound to within 0.1% in every run, so nothing was silently dropped.
- **Machine.** Windows 11, 24 logical CPUs (Intel family 6 model 191),
  16.9 GB RAM, Python 3.12.1, loopback TCP. No other Starling process was
  running: the live world demo was stopped for this run. The rest of the
  desktop (VS Code, other tools) was not idle; it measured 16–26% CPU
  just before the run (`machine.cpu_busy_pct_at_start` in the JSON).

## Results

| N | degree | diameter | per-node gossip in, mean / max (KB/s) | per-node out, mean / max (KB/s) | latency to EVERY replica, p50 / p95 / max (s) | replicas identical | claims | CPU per node, mean (%) | RSS per node (MB) |
|---|---|---|---|---|---|---|---|---|---|
| 4  | 2 (ring) | 2 | 8.7 / 8.7     | 8.7 / 8.8     | 0.68 / 1.28 / 1.35 | **yes** | 416  | 0.3 | 62 |
| 8  | 4 | 2 | 33.6 / 34.3   | 33.6 / 35.0   | 0.81 / 1.30 / 1.34 | **yes** | 820  | 0.4 | 63 |
| 16 | 4 | 3 | 61.7 / 66.3   | 61.7 / 74.0   | 0.91 / 1.48 / 1.97 | **yes** | 1651 | 0.7 | 64 |
| 32 | 4 | 4 | 127.7 / 147.7 | 127.7 / 159.7 | 1.42 / 1.98 / 2.43 | **yes** | 3359 | 2.7 | 66 |
| 48 | 4 | 5 | 193.8 / 213.1 | 193.7 / 262.3 | 1.68 / 2.27 / 2.78 | **yes** | 5015 | 4.3 | 66 |
| 64 | 4 | 6 | 249.9 / 282.3 | 249.8 / 369.2 | 2.17 / 2.98 / 4.59 | **yes** | 6574 | 6.9 | 67 |

Each run produced for 40.0–40.9 s, at a measured 2.51–2.62 claims/s per
node. In every run, every claim reached every replica (0 missing), and
every replica ended with the identical claim set. After production
stopped, the replicas became identical within 1.0, 1.5, 1.7, 2.8, 2.8 and
2.8 s respectively. There were no wire-cap rejections.

**Latency by hop distance** (N = 64, from the same run's raw first-seen
tables; p50 / p95 in ms):

| hops from origin | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| N = 64 | 3 / 20 | 268 / 946 | 648 / 1452 | 961 / 1903 | 1184 / 2144 | 1356 / 2294 |

Hop 1 is the immediate signed push and takes milliseconds. Every further
hop waits for an anti-entropy round. At N = 4 and N = 16 the 1-hop figure
is likewise 2 ms (p50).

**Where the bytes go** (all nodes' inbound bytes over the whole run):

| N | claim pushes | anti-entropy deltas | digests (mean digest size) |
|---|---|---|---|
| 4  | 32.5% | 65.3% | 2.3% (118 B) |
| 16 | 9.1%  | 89.4% | 1.5% (273 B) |
| 64 | 2.1%  | 96.6% | 1.2% (848 B) |

## Partition test (N = 16)

The graph was cut into two halves, {0..7} and {8..15}, for 15.05 s while
every node kept producing. Both halves stay internally connected under
this split. The cut is application-level: every node drops everything
from the other half, the same semantics as
`starling_consensus.attacks.PartitionControl`. After the cut was healed,
production continued for another 10 s.

| Metric | Value |
|---|---|
| Claims made during the partition | 631 |
| Claims that crossed the cut before the heal | **0** |
| Heal → every pre-heal claim in every replica | **2.52 s** |
| Replicas identical at the end | **yes** (1486 claims) |

The 2.52 s is counted from the moment the heal command was written.
Nodes poll for commands every 0.1 s, so the figure is slightly
conservative.

## Centralised comparison (computed, not measured)

A centralised design has one server ingest every camera's video. Its
ingest is N × one camera's bitrate. Two per-camera figures were used:

| Stream | Per camera | N = 4 | N = 16 | N = 64 |
|---|---|---|---|---|
| World demo: 1280×720 JPEG @ 3 fps (assumed 120 KB/frame) | 360 KB/s | 1.44 MB/s | 5.76 MB/s | 23.0 MB/s |
| Industry-typical 1080p H.264 CCTV @ 4 Mbit/s | 500 KB/s | 2.0 MB/s | 8.0 MB/s | 32.0 MB/s |
| **Starling busiest node, gossip in (measured)** | — | **8.7 KB/s** | **66.3 KB/s** | **282.3 KB/s** |

The world-demo figure is the stated 120 KB/frame assumption. The script
samples the running world server's camera tap when it is reachable, but
the demo was stopped for this run. An earlier spot check of four live
frames from that tap measured 151–167 KB each (mean 158 KB). The
assumption therefore understates the central design's ingest by about
25%, which flatters the central design rather than Starling.

The busiest Starling node receives **82× less** than the central server
under the world-demo stream, and **113× less** under H.264 at N = 64. The
same holds at every N ≥ 8 (78–87× and 108–121×). At N = 4 the ratio is
165× and 230×, because the ring's lower redundancy makes each claim
cheaper.

## Interpretation — what this does and does not show

- **Per-node load grows linearly with N.** This is inherent to a fully
  replicated CRDT: every replica holds every claim, so each node must
  receive the whole network's claim rate. Mean inbound fits
  ~4.0 KB/s per added node (busiest node ~4.5 KB/s). That equals
  N × 2.6 claims/s × ~1.43 KB per claim delivered. The 1.43 KB is ~2.6×
  the 549 B claim size. The redundancy comes from PUB/SUB anti-entropy:
  a digest goes to every neighbour, each neighbour that holds missing
  claims replies (see `AntiEntropy.tick`'s docstring), and each reply is
  overheard by all of the replier's neighbours. CPU per node also grows
  roughly linearly: 0.3% at N = 4, 6.9% at N = 64. That is per-message
  work (ed25519 verification, protobuf parsing, SQLite inserts); it was
  not profiled further. RSS stays flat at 62–67 MB, of which
  ~55 MB is the interpreter and libraries. The claim store itself is
  small in a 40 s run.
- **There is no hotspot crossover in N.** The central server's ingest is
  also linear in N (N × video). The busiest-node ratio is therefore
  roughly constant, about 80–110×, rather than shrinking. A single
  Starling node at N = 64 (282 KB/s) takes in less than one camera's
  video stream (360–500 KB/s). The constant can shrink, though. A crowded
  scene that makes more claims per camera raises Starling's cost
  proportionally, while video bitrate does not change. The per-node
  crossover is at roughly 80–110× today's claim rate, about 200–290
  claims/s per camera.
- **Total bytes do cross over.** With full replication, the network
  carries about 4.5 KB/s × N² in total (every node receives everything),
  while a central design carries N × video in total. These are equal at
  N ≈ 79 cameras (world-demo stream) or N ≈ 110 (H.264), using the
  busiest-node slope; with the mean slope, N ≈ 90 or 125. Beyond that,
  Starling moves more bytes in total. They are spread over many short
  neighbour links rather than concentrated into one server's uplink, but
  it is still more traffic. Full replication is the right design for a
  building-scale deployment of tens of cameras, which is what this
  project targets. It is not the right design for a city.
- **Latency grows with the graph diameter, not with N directly.** The
  diameter goes 2 → 6 from N = 4 to N = 64, and p50 goes 0.68 → 2.17 s.
  The first hop takes milliseconds. Each further hop costs one
  anti-entropy round, about 0.2–0.4 s at p50, because rounds run every
  4/3 s at a random phase per node and any neighbour that holds a claim
  can answer. Seconds-scale end-to-end consistency matches what the
  identity layer needs: a person walks ~1.4 m/s, and the resolver
  reasons over media-time windows of seconds.
- **Partitions heal fast and cleanly.** After 15 s apart and 631
  divergent claims, every replica held every pre-heal claim 2.5 s after
  the heal. Nothing leaked across the cut while it was open.

## Caveats

- **Single host.** All N processes ran on one 24-thread machine over
  loopback. There was no real network latency, loss or bandwidth limit,
  and up to 64 processes shared the CPU. Absolute latencies on a real LAN
  would gain round-trip times, and CPU contention would be lower.
- **Bytes measured are envelope bytes**, as counted by `GossipNode.stats()`.
  ZeroMQ framing and TCP/IP headers are not included. They are small per
  message, but nonzero.
- **Synthetic claim source.** Claim size and rate are realistic, but
  claims arrive Poisson-like rather than in camera-frame bursts. Bench
  nodes do not run the reputation, attestation or contradiction loops
  from `apps/node.py`. Those gossip `ReputationUpdate` and
  `CoverageAttestation` messages (< 200 B each), whose cost is not
  included here.
- **Logging.** Bench nodes log at WARNING. `apps/node.py` logs every
  gossip message at INFO, which costs CPU but is not network load.
- **40 s runs.** Claim stores stay small. Long-running growth is bounded
  by `prune_claims` (a retention window), which this experiment did not
  exercise.
- **First attempt failed at N = 32.** The first full run failed at
  N = 32 with "paging file is too small". numpy's OpenBLAS starts one
  thread per core in every process and commits ~816 MB per process (vs
  40 MB with one thread). The bench node and runner now pin
  `OPENBLAS_NUM_THREADS=1`; a bench node does no linear algebra. That
  smoke run, and possibly the start of that first attempt, also ran
  while the live world demo (4 YOLO nodes) was using most of the CPU. All numbers above come from
  the clean re-run (`generated` in the JSON).

## What would come next (future work — not done)

- **Geographically scoped replication.** Replicate a claim only within a
  bounded neighbourhood of cameras: the zones a person could reach before
  the claim ages out, using the C3 reachability model. Per-node load would
  then depend on local density instead of N, removing the N² total. The
  open question is how a query about a far-away identity is answered. One
  option is to forward the query rather than the data.
- **Less anti-entropy redundancy.** About 97% of bytes at N = 64 are
  anti-entropy deltas, and each replica receives each claim ~2.6×.
  Possible fixes: address a delta to the digest's sender (a ROUTER/DEALER
  reply path), let a single neighbour answer each digest, or relay a new
  claim one hop with de-duplication. Any of these would lower the
  per-claim constant. None changes the O(N) per node of full replication.
- **Larger and real-network runs.** Run multiple hosts with `deploy/netem`
  for real latency and loss, and N in the hundreds, to confirm the linear
  fit beyond 64.
