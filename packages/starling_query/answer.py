"""starling_query/answer.py
------------------------------
Pure query-answering logic (WP-14, C5), separated from `cli.py` so it is
testable without a live gossip mesh — a test builds a `ClaimSet` and runs
`starling_crdt.resolver.resolve` on it directly, the same way
`scripts/run_deadzone_experiment.py` exercises C4 at the algorithm level
without a full pipeline run.

The refusal rule (STARLING_BUILD_STATE.md WP-14): "never emit a position
not backed by a claim in the local set." Every field of a successful
`QueryResult` traces back to a specific claim this process actually holds;
every refusal names a SPECIFIC reason, never a generic "no data".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from starling_crdt.forks import ForkSet
from starling_crdt.resolver import Assignment
from starling_query.capability import Query


@dataclass(frozen=True)
class QueryResult:
    subject: str
    refusal_reason: Optional[str] = None
    last_confirmed: Optional[dict[str, Any]] = None
    anchor: Optional[dict[str, Any]] = None
    inferred_note: Optional[str] = None
    candidate_region_m2: Optional[float] = None
    blind_spots: tuple[tuple[int, float], ...] = field(default_factory=tuple)
    nodes_responded: int = 0
    nodes_total: int = 0

    @property
    def refused(self) -> bool:
        return self.refusal_reason is not None


def answer_query(
    query: Query,
    assignment: Assignment,
    claims_by_id: dict[str, dict],
    forks: ForkSet,
    liveness: dict[int, bool],
    now_t_media: float,
    retention_window_s: float,
    attested_region_ids: frozenset[int] = frozenset(),
    unreachable_duration_s: Optional[dict[int, float]] = None,
) -> QueryResult:
    unreachable_duration_s = unreachable_duration_s or {}
    nodes_total = len(liveness)
    nodes_responded = sum(1 for online in liveness.values() if online)
    blind_spots = tuple(
        sorted((node_id, unreachable_duration_s.get(node_id, 0.0)) for node_id, online in liveness.items() if not online)
    )

    def refuse(reason: str) -> QueryResult:
        return QueryResult(
            subject=query.subject,
            refusal_reason=reason,
            blind_spots=blind_spots,
            nodes_responded=nodes_responded,
            nodes_total=nodes_total,
        )

    retention_horizon = now_t_media - retention_window_s
    if query.t_end < retention_horizon:
        return refuse(
            f"the requested window ends at t={query.t_end:.1f}, before the "
            f"retention horizon (t={retention_horizon:.1f}) — that evidence "
            "has already been pruned"
        )

    if query.subject not in assignment.trajectories:
        return refuse(f"subject '{query.subject}' was never enrolled — no claims found for this identity")

    claim_ids = assignment.trajectories[query.subject]
    records = [claims_by_id[cid] for cid in claim_ids if cid in claims_by_id]
    in_window = sorted(
        (r for r in records if query.t_start <= r["t_media"] <= query.t_end), key=lambda r: r["t_media"]
    )

    if not in_window:
        return refuse(
            f"'{query.subject}' has no claims within the requested window "
            f"[{query.t_start:.1f}, {query.t_end:.1f}]"
        )

    producing_nodes = {r["node_id"] for r in in_window}
    if producing_nodes and all(not liveness.get(node_id, False) for node_id in producing_nodes):
        node_list = ", ".join(f"node {n}" for n in sorted(producing_nodes))
        return refuse(
            f"'{query.subject}' was only observed by {node_list}, which "
            "is/are unreachable for the entire requested window — a "
            "partitioned wing, not an absence"
        )

    for fork in forks.open_forks():
        if fork.identity_ref != query.subject:
            continue
        fork_opened_t = fork.opened_at.physical_ms / 1000.0
        if fork_opened_t <= query.t_end:
            return refuse(
                f"'{query.subject}' has an OPEN, unresolved identity fork "
                f"({fork.fork_id}) spanning this window — cannot fuse "
                "across branches without resolving the ambiguity first"
            )

    if query.area:
        unattested = sorted(set(query.area) - attested_region_ids)
        if unattested:
            return refuse(
                f"no camera coverage or attestation exists for region(s) "
                f"{unattested} — the system cannot speak to that area at "
                "all, positively or negatively"
            )

    last = in_window[-1]
    last_confirmed = {
        "node_id": last["node_id"],
        "t_media": last["t_media"],
        "confidence": last["confidence"],
        "world_x": last.get("world_x"),
        "world_y": last.get("world_y"),
    }

    anchor_claims = sorted((r for r in records if r.get("anchor_type") == "FACE_ANCHOR"), key=lambda r: r["t_media"])
    anchor = None
    if anchor_claims:
        a = anchor_claims[-1]
        anchor = {"node_id": a["node_id"], "t_media": a["t_media"]}

    inferred_note = None
    if last.get("anchor_type") != "FACE_ANCHOR":
        inferred_note = "last position is appearance-matched, not anchored — treat as a hypothesis"

    return QueryResult(
        subject=query.subject,
        last_confirmed=last_confirmed,
        anchor=anchor,
        inferred_note=inferred_note,
        blind_spots=blind_spots,
        nodes_responded=nodes_responded,
        nodes_total=nodes_total,
    )


def render(result: QueryResult) -> str:
    """Structured, TEMPLATE-rendered output — not generated text
    (STARLING_BUILD_STATE.md §12 rule 1). Separates confirmed from
    inferred and states the extent of its own blindness; that property,
    not the wording, is the contribution.
    """
    lines = [f"Subject:          {result.subject}"]

    if result.last_confirmed:
        lc = result.last_confirmed
        if lc.get("world_x") is not None and lc.get("world_y") is not None:
            pos = f"({lc['world_x']:.1f}, {lc['world_y']:.1f}) m"
        else:
            pos = "position unknown (no world coordinates on this claim)"
        lines.append(
            f"Last confirmed:   {pos}, t={lc['t_media']:.1f}, "
            f"confidence {lc['confidence']:.2f}, node {lc['node_id']}"
        )

    if result.anchor:
        a = result.anchor
        lines.append(f"Anchor:           face, node {a['node_id']}, t={a['t_media']:.1f}")
    else:
        lines.append("Anchor:           none recorded")

    if result.inferred_note:
        lines.append(f"Inferred:         {result.inferred_note}")

    if result.candidate_region_m2 is not None:
        lines.append(f"Candidate region: {result.candidate_region_m2:.1f} m²")

    if result.blind_spots:
        names = " and ".join(f"node {n}" for n, _ in result.blind_spots)
        lines.append(f"Blind spots:      {names} unreachable for this window")

    lines.append(f"Completeness:     {result.nodes_responded} of {result.nodes_total} nodes responded")
    return "\n".join(lines)
