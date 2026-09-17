# Headline results — the three-way failure-mode experiment

**Status: scaffold, not yet populated with real numbers.** Per WP-14 Part
4's own rule this session builds and verifies `scripts/run_headline.py`
and `scenarios/headline.yaml` but deliberately does not run the full
experiment (`python scripts/run_headline.py --dry-run` lists all 3
planned runs at `--repeat 1`, 15 at `--repeat 5`). Whoever runs it for
real next fills every `TBD`/`not yet measured` cell below in from that
run's `results.json`, and replaces this notice.

**A single run of a distributed system is not evidence.** Every number in
the real table must be mean +/- std over `--repeat 5`, never a lone value.

## How to fill this in

```
python scripts/run_headline.py --repeat 5 --out results/headline
```

Arm 3 (`scenarios/headline.yaml`) needs a REAL partition and a REAL live
attack switch — both require actual container network namespaces
(`deploy/netem/apply.py`), so it can only be run via `docker compose`
(`starling_eval.runner.run_docker_once`), never `--local`. This is the
same limitation `scenarios/east_wing_drop.yaml` already states for
`--local` mode, not a new one introduced here. Arm 2
(`scenarios/healthy.yaml`, no events) can use either `--local` or Docker.

## The one table

| Arm | IDF1 | MOTA | HOTA | ID switches | identity consistency after merge | time to reconverge | unresolved fork rate | candidate region area | false exclusion rate | bytes per node-hour | end-to-end p95 latency |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Arm 1: centralized baseline (`apps/baseline.py`, V1) | not yet measured | not yet measured | not yet measured | not yet measured | n/a (no CRDT) | n/a (no partitions) | n/a (no forks) | n/a (no candidate-region reasoning) | n/a | 0 (no gossip, by construction) | not yet measured |
| Arm 2: Starling, healthy network (`scenarios/healthy.yaml`) | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |
| Arm 3: Starling, partitioned + `fabricate@0.4` (`scenarios/headline.yaml`) | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |

Arm 1's `n/a` cells are structural, not missing data: the centralized
baseline has no CRDT merge, no partition-recovery concept, no identity
forks, and no candidate-region reasoning at all — those columns simply do
not apply to it, which is itself part of the comparison's point. Its
`bytes per node-hour = 0` is the same kind of structural fact (it does not
gossip; it streams raw video/frames within a single process instead —
see spec §11's privacy visual), not a favourable measurement.

## Why most cells above say "not yet measured"

`starling_eval.runner`'s existing `run_local_once`/`run_docker_once` only
ever compute SYSTEM-level numbers (bytes/node-hour, wall-clock, claim
counts) — nothing in this repo yet wires a scenario run's own claim/
resolver output into `starling_eval.metrics`'s tracking functions
(IDF1/MOTA/HOTA need a predicted-tracks file in MOTChallenge format
compared against `data/gt/`, which no scenario runner emits yet; the C1/
C4/C6 columns need the resolver's `Assignment`/`ForkSet`/candidate-belief
state captured per-run and fed to `starling_eval.metrics`'s
`identity_consistency_after_merge`/`time_to_reconverge`/
`unresolved_fork_rate`/`candidate_region_reduction`/
`false_exclusion_rate`, which also is not wired up yet). Filling in a
plausible-looking number for any of them without that pipeline would
violate STARLING_BUILD_STATE.md §12 rule 9 — so they stay "not yet
measured" here rather than being estimated. `scripts/run_headline.py`
already computes and reports `bytes_per_node_hour` (and would report
`wall_clock_s`) for Arms 2 and 3 once actually run.

## Timeline plot

TBD — a plot of per-arm activity (claims/attestations/gossip observed)
over the scenario's 600s, showing Arm 1 producing NO output at all during
the `[120, 300]s` partition window (its coordinator is unreachable), while
Arms 2 and 3 continue, Arm 3 visibly degrading (fewer/less-confident
claims, dropped/rejected fabricated ones) rather than stopping outright.
Requires a real run's merged timeline (`_merge_timeline` in
`starling_eval.runner`, plus Docker-mode log collection for Arm 3) —
neither exists yet.

## What Arm 3 does worse than Arm 2 (required, not optional)

TBD — must be filled in honestly once real numbers exist; a results table
with no cost stated is not credible and a reviewer will assume something
was hidden. Specific, not-yet-measured candidates worth checking first:

- higher end-to-end claim latency during and immediately after the
  partition (anti-entropy catch-up cost once the two halves reconnect)
- a nonzero unresolved-fork rate where Arm 2 has none
- a temporarily larger candidate-region area for identities that crossed
  through node-02 while it was fabricating and partitioned
- the extra bytes/node-hour spent reconverging after heal, on top of
  ordinary gossip traffic
- any drop in identity-consistency-after-merge if a fabricated claim
  survives plausibility checking during the window node-02 is cut off
  from corroborating neighbours

Do not skip this section once real numbers are in hand, even if the
answer turns out to be smaller than expected.
