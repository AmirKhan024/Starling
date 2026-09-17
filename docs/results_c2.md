# C2 results — Byzantine robustness (WP-10)

**Status: scaffold, not yet populated with real numbers.** Per the WP-10
Part 4 prompt this session builds and verifies
`scripts/run_byzantine_sweep.py` but deliberately does not run the full
sweep (`--repeat 5` across the full `f/n` x attack x method grid is a long
run — `python scripts/run_byzantine_sweep.py --dry-run` lists all 880
planned points at `--repeat 5`). Whoever runs it for real next fills each
`TBD` below in from that run's `results.json`, and replaces this notice.

A small-scale correctness check (a handful of `f/n`/attack/method points,
a tiny navmesh, one seed — not a result, just a sanity check that the
mechanism behaves in the expected direction before committing to a long
real run) showed the qualitatively expected shape: at `f/n=0.3` under
`fabricate`, `unweighted`'s mean position error was roughly 5-6x worse
than `trimmed_mean`'s and `krum`'s, with `reputation` in between — i.e.
the baseline that should lose, lost. That is not a substitute for the real
sweep and no number from it appears below.

## How to fill this in

```
python scripts/run_byzantine_sweep.py --repeat 5 --out results/byzantine_sweep_c2
```

Then, from `results/byzantine_sweep_c2/results.json`:

## Accuracy vs. f/n, one panel per attack class, one line per method

TBD — plot `mean_position_error_m` (mean +/- std over the 5 repeats) against
`f_over_n`, one subplot per `attack` in `{fabricate, suppress, replay,
mixed}`, one line per `method` in `{unweighted, reputation, trimmed_mean,
krum}`.

## False-claim rejection rate and false-rejection rate

TBD — both together, per attack/method/f-over-n, from
`false_claim_rejection_rate` and `false_rejection_rate` in each run
record. **Known, expected, non-bug result:** `suppress` will show
`false_claim_rejection_rate = NaN` at every point — this harness's claim-
level plausibility checking has nothing to reject when the attack's whole
mechanism is that a claim is never sent. `suppress` is caught by
`starling_attest.negative_evidence.detect_omission` (WP-09), exercised in
`tests/test_negative_evidence.py`, not by this sweep — say this plainly in
whatever report is built from this data rather than letting a blank
`suppress` row read as a defect in the sweep.

## A fabricating node's reputation decaying over time

TBD — plot `final_malicious_reputation` against `f_over_n` for the
`fabricate` (and `mixed`) rows; cross-reference against
`tests/test_reputation.py`'s exact-14-claims decay assertion for the
underlying per-claim mechanism, which this plot shows aggregated over a
whole run instead of a single node's claim-by-claim trace.

## Where the scheme breaks

TBD — the required statement, not optional (WP-10 Part 4 / this project's
own §5 pre-commitment in `docs/threat_model.md`): the `f/n` at which
`reputation`-weighted aggregation's mean error stops beating
`unweighted`'s, averaged across attack classes.
`scripts/run_byzantine_sweep.py`'s own `_breaking_point()` computes this
number directly from `results.json` and prints it at the end of a real
(non-dry-run) invocation — copy that number here, or state plainly if it
never lost (also a valid, reportable outcome, not one to have to
manufacture a caveat for).
