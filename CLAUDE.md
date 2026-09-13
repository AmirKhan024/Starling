# Starling — Standing Rules for Claude Code

## What this project is
Starling is a decentralized multi-camera identity network. Independent camera
nodes gossip small identity claims to neighbours and converge on one consistent
view with NO central coordinator. The research contributions are:
- C1: identity as a partition-tolerant CRDT
- C2: Byzantine-robust identity attestation with reputation
- C3: geometry-constrained gap bridging over a 2D navmesh
- C4: negative evidence — reasoning from attested absence (flagship)
- C5: calibrated natural-language query (minimal scope for now)
- C6: self-healing topology discovery
- C7: uniform-invariant re-ID (CUT — do not implement)

## Non-negotiable architectural rules
1. A "node" is an OS PROCESS with its own SQLite replica and its own gossip
   socket. Never a thread. Never sharing a database handle.
2. No module may read another node's database, filesystem directory, or
   in-memory state. If deleting the network still leaves the system working,
   the design is wrong.
3. Raw video, frames, and crops NEVER cross the wire. Only claims,
   attestations, reputation updates, topology observations, and queries.
4. Gossip goes to a CONFIGURED NEIGHBOUR SET, never a full mesh. A full mesh
   is a coordinator in disguise.
5. Identity assignments are NEVER replicated. Signed observation CLAIMS are
   replicated (a grow-only set); the assignment is a deterministic pure
   function of the merged claim set. This is the core mechanism of the project.
6. When two claim chains bind one identity to spatially incompatible
   trajectories and both remain reachable, the fork STAYS OPEN. Never resolve
   a fork by picking the higher score.
7. Silence is never evidence of absence. Only an attestation that passes the
   confidence threshold counts as negative evidence.
8. The dashboard is a read-only gossip observer with no privileged access.

## Code conventions
- Python 3.10+. Type hints on all public functions. `ruff` clean. `mypy` clean
  on starling_crdt and starling_consensus.
- Logging via structlog, JSON output, every record tagged with node_id.
  Never use bare print() outside apps/ CLI banners.
- All thresholds and constants live in Pydantic config models loaded from
  configs/. Never hardcode a magic number in logic.
- Tests with pytest. CRDT and consensus logic additionally uses hypothesis
  property tests.
- No wall-clock reads (time.time()) anywhere in the identity path. Use media
  time and hybrid logical clocks.

## Things deliberately NOT being built
- 3D Gaussian reconstruction (2D navmesh only, pre-committed)
- C7 uniform-invariant re-ID
- A full LLM query interface (a structured CLI stub only, for now)
- Any hardware beyond 4 cheap cameras and one spare machine

## Preserved baseline
apps/baseline.py is the ORIGINAL V1 centralized system. It is the experimental
control condition for every measurement in the project. Never modify its
behaviour. If you must change it to keep it running, keep the algorithm
identical and say so in the commit body.

## How to work in this repo
- The full audit, defect register (D-01..D-15), work packages (WP-00..WP-14),
  and completion rubric live in STARLING_BUILD_STATE.md. Read the relevant
  section; do not re-audit the code.
- Work only within the scope of the prompt you were given. Do not
  opportunistically refactor adjacent code.
- When a design choice is ambiguous, take the option named first in the prompt
  or in STARLING_BUILD_STATE.md, add a one-line comment recording the choice,
  and continue. Do not stop to ask.
