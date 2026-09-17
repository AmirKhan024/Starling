# Starling threat model (C2, WP-10)

This document is written before any of WP-10's code, per this session's own
rule: stating the threat model explicitly is what stops the Byzantine-
robustness implementation drifting into defending against whatever happens
to be easy to code, instead of what the spec actually asks for.

Stakes framing (from the WP-10 prompt, worth repeating because it drives
every design choice below): in collaborative mapping, a faulty node
produces a blurry wall. In an identity system a faulty node produces **a
false claim about a person** — a false alibi, a false presence record, a
misattribution during an investigation, or a search team sent away from an
injured worker. The problem WP-10 defends against is different in kind
from ordinary distributed-systems fault tolerance, not just in degree.

## 1. System model

- `n` nodes, partial mesh (CLAUDE.md rule 4: a configured neighbour set,
  never a full mesh), asynchronous network with unbounded but finite
  message delay.
- Failure modes: crash-recovery (a node stops and later rejoins with its
  local SQLite replica intact) and network partitions (`starling_net.partition`,
  WP-04 Part 4). Neither is Byzantine on its own — a crashed or partitioned
  node is silent, not lying; §2 below is what adds adversarial behaviour on
  top of this base model.
- Each node has an enrolled ed25519 keypair (`starling_net.keys`),
  distributed at commissioning — generated once, out of band, before the
  node ever joins the mesh. This is the assumption §3's Sybil exclusion
  rests on.
- Clocks are loosely synchronised via NTP-style measurement
  (`scripts/measure_drift.py`, a stdlib four-timestamp UDP exchange run
  between real node hosts). **Measured drift: TBD.** This script has not
  yet been run against real deployed node hosts as of this document — only
  estimating a number here would be exactly the kind of unstated assumption
  this document exists to prevent. Whoever runs the real multi-host
  deployment must run `scripts/measure_drift.py` between the actual hosts
  and replace this line with the measured mean/max absolute offset before
  `cfg.replay_window_s` (`packages/starling_node/config.py`,
  `PlausibilityConfig`) is tuned from it.

## 2. Adversary

Up to **f of n** nodes may be arbitrarily faulty: they may fabricate,
suppress, replay, or combine these, in any order, for as long as they
remain enrolled. A faulty node retains its real, enrolled signing key —
this single fact is why signatures alone cannot be the whole defence (see
§4's fifth bullet, and the docstring on
`starling_consensus.attacks.AttackInjector`, which signs every injected
claim through the same code path a genuine claim takes).

| Attack | Definition | Harm | Detection |
|---|---|---|---|
| **FABRICATE** | Claims for people who are not there — plausible-looking positions injected into the claim stream by a node that never observed anyone at that location. | False alibi, false presence record, misdirected emergency response. | Geometric plausibility against corroborated positions: `starling_consensus.plausibility.check`'s REACHABILITY hard-fail rejects a claim not inside the reachable set from the last corroborated position; KINEMATICS grades the implied speed even on claims that pass the hard gate. |
| **SUPPRESS** | Withholding real observations — including the specific "lying by omission" case of emitting a healthy coverage attestation (`crossing_observed=False`, `attest_confidence` above `tau_attest`) while actually omitting a crossing it should have seen. | A person is believed absent from where they actually are — the exact failure mode C4's negative-evidence fusion (`starling_attest.negative_evidence`) is built to reason about, so a suppressing node corrupts *that* reasoning specifically, not just the positive-evidence trail. | `starling_attest.negative_evidence.detect_omission` (built in WP-09/Prompt 7) flags a healthy attestation contradicted by `cfg.min_omission_corroborators` or more other nodes' claims; WP-10's `starling_consensus.reputation.ReputationTable.penalise_omission` is the new hook that turns that signal into an actual reputation cost. This is the composition point that makes C2 and C4 one contribution rather than two. |
| **REPLAY** | Re-emitting stale claims with fresh gossip timestamps — the claim's own embedded HLC (`t_start`) is old, but it is re-published now, as if freshly observed. | A person appears to be somewhere they have actually already left. | `starling_consensus.plausibility.check`'s FRESHNESS grading: a claim whose embedded HLC is older than `cfg.replay_window_s` relative to the admitting node's current time is flagged as a replay candidate and scored down. |

## 3. Out of scope — stated explicitly

This section is a strength, not a weakness. Saying what Starling does not
defend against is what makes the rest of this document credible; a scheme
that claims to defend against everything defends against nothing
verifiably.

- **Sybil attacks.** Node keys are enrolled at commissioning
  (`starling_net.keys` module docstring states this assumption directly);
  an adversary who cannot forge or steal an enrolled private key cannot
  mint new node identities to inflate its influence over corroboration
  counts, median reputation aggregation, or Krum's neighbour count.
- **Physical camera tampering and adversarial patches on clothing.** A
  camera can be tampered with, or a person's appearance adversarially
  perturbed, in ways that fool the *perception* pipeline before a claim is
  ever formed. WP-10 defends the claim/attestation/reputation layer, not
  the pixels a claim is derived from.
- **Collusion by more than `f` nodes.** Median-based reputation
  aggregation and Krum are both Byzantine-robust only up to a stated
  fraction of corrupted inputs; beyond that fraction, colluding faulty
  nodes can outvote honest ones in both the reputation median and Krum's
  neighbour-distance ranking. §5 below states the fraction observed to
  work.
- **Side channels, including traffic analysis of gossip volume.** An
  adversary who can observe *how much* a node gossips, or *when*, without
  reading the (signed but unencrypted) payload content, is not defended
  against here.
- **Compromise of the enrollment process itself.** If an attacker can
  inject a key into `configs/keys/` before or during commissioning, every
  guarantee in this document that rests on "the signing key is really
  held by the node it claims to be" is void. Enrollment security is
  physical/procedural, not a property of the gossip protocol.

## 4. Security goals — each falsifiable

- A fabricated claim inconsistent with the reachability model is rejected
  with probability approaching 1, given at least `k` honest corroborators
  — measured directly by `scripts/run_byzantine_sweep.py`'s false-claim
  rejection rate at low `f/n`.
- A node persistently emitting implausible claims has its reputation decay
  below the admission threshold (`AttestConfig.min_reputation`,
  `packages/starling_node/config.py`) within a bounded number of claims —
  `tests/test_reputation.py` asserts the exact claim count for
  `alpha=0.05` (the fixed point under all-failing observations is
  `R_min=0.05`; the decay crosses `0.5` at claim 14, computed in that
  test's own comment and re-derived, not hand-waved, from the EWMA
  recurrence).
- No single compromised node can cause a false identity assignment to
  persist after merge with honest replicas — CLAUDE.md rule 6 (forks stay
  open under genuine ambiguity) already prevents a *single* claim from
  silently overwriting an honest trajectory; WP-10 adds that the
  compromised node's own future claims carry falling weight
  (`w = R_j * claim.confidence * claim.quality`, Appendix A.5) in whichever
  `starling_consensus.aggregate` method or `starling_crdt.resolver.resolve`
  scoring consumes them, so its influence over any subsequent binding decays
  even where a fork does not literally open.
- The system **never** converts an unverifiable claim into a confident
  answer: an uncalibrated node's claims carry no `world_pos` and are
  already excluded from the reachability gate (`apps/node.py`'s
  `_load_calibration` warning, and `starling_crdt.resolver._gate_pass`'s
  "no known position → reject" rule); WP-10 extends the same posture to
  plausibility scoring, where a claim with no corroborated prior position
  to compare against skips the hard-fail gate rather than being scored as
  if it had passed it (`starling_consensus.plausibility.check`, "no prior
  corroborated position" branch).

## 5. What we expect to fail

This document commits, in advance of running the sweep, to reporting where
the scheme breaks rather than claiming universal robustness — the
evaluation in `docs/results_c2.md` (populated by a full
`scripts/run_byzantine_sweep.py --repeat 5` run, outside this session) must
state the `f/n` at which reputation-weighted aggregation stops beating the
unweighted-mean baseline, not merely show a curve that looks good at low
`f/n`. Median- and reputation-based defences are well known to degrade,
not fail catastrophically, as the malicious fraction approaches 0.5 — a
curve that degrades gracefully to a stated breaking point is a stronger,
more falsifiable result than a claim of robustness at every `f/n`, and is
what this project reports.

Mechanism-to-file cross-reference (files below did not exist at the time
this document was written — Part 1 is documentation only, per this
session's own rule):

| Mechanism | File |
|---|---|
| Plausibility checking (reachability/kinematics/corroboration/freshness) | `packages/starling_consensus/plausibility.py` |
| Local, per-observer reputation with EWMA update + recovery floor + median aggregation | `packages/starling_consensus/reputation.py` |
| Byzantine attack injection (fabricate/suppress/replay/mixed), live-switchable | `packages/starling_consensus/attacks.py` |
| Robust aggregation (unweighted baseline, reputation-weighted, trimmed mean, Krum) | `packages/starling_consensus/aggregate.py` |
| Headline `f/n` sweep experiment | `scripts/run_byzantine_sweep.py` |
