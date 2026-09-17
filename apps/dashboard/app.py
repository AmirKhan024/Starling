"""apps/dashboard/app.py
-------------------------
Starling dashboard V2 (WP-13): a READ-ONLY gossip observer, not a database
reader. CLAUDE.md rule 8 / STARLING_BUILD_STATE.md stop condition: this
file must never gain sqlite3 access to a node's database or read any
node's own per-node data directory. Everything shown here is derived, live, from
`apps.dashboard.observer.GossipObserver` — the exact claims, attestations,
and reputation opinions a passive peer in the dashboard's position would
have seen, nothing more (`tests/test_dashboard_observer.py` greps this
directory to enforce it).

V1's Lost Registry / Search / Person Detail / event-timeline UX
(STARLING_BUILD_STATE.md §9: "the largest reusable asset in the repo") is
kept as a set of CONCEPTS, not literal code: V1's version was built
entirely on per-sighting crops and a shared `IdentityStore` schema that
cannot exist in a gossip-only world (CLAUDE.md rule 3: raw video/frames/
crops never cross the wire, so there is nothing here to show a crop
image). The re-interpretation: "person" -> the resolver's derived
`identity_ref`; "sightings" -> that identity's claim trajectory; "lost" ->
no claim newer than `cfg.lost_threshold_s`, with a live candidate-belief
region taking the place of a static "last known camera" field; "resolve /
reactivate / note" -> kept as ephemeral, per-viewer UI conveniences
(`st.session_state`), never persisted anywhere shared (this process owns
nothing -- CLAUDE.md rule 8).

Ambiguous-choice note (CLAUDE.md: take the first reasonable option,
comment, continue): the Floor Plan panel's "camera FOV polygons" are not
representable from gossip alone -- a node's ROI polygon is its own local
config, never gossiped (`CoverageAttestation` carries only boundary
`region_ids`, not the polygon). Rather than have the dashboard read
another process's config file to reconstruct it, the floor plan instead
shows WHICH boundary ids each node is currently attesting healthy
coverage of -- a strictly gossip-derived proxy for "what this node
claims to be watching."
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import requests
import streamlit as st

from dashboard.config import DashboardConfig, load_dashboard_config
from dashboard.observer import GossipObserver

from starling_attest.negative_evidence import CandidateBelief
from starling_crdt.resolver import Assignment, resolve
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_node.config import MatchConfig, NegativeEvidenceConfig
from starling_proto.generated import starling_pb2

# ── Page config ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Starling  |  Gossip Observer",
    page_icon="🐦",
    layout="wide",
    initial_sidebar_state="expanded",
)

CONFIG_PATH = Path(os.environ.get("STARLING_DASHBOARD_CONFIG", "configs/dashboard.local.yaml"))
# Literally never incremented anywhere in this codebase -- there is no
# code path that could put frame/crop bytes into a gossip message
# (starling_proto.limits.assert_wire_safe rejects any oversized `bytes`
# field before a claim/attestation is ever sent). Shown, not asserted.
RAW_VIDEO_BYTES = 0


# ── Cached resources (created once per Streamlit session process) ────────

@st.cache_resource
def get_config() -> DashboardConfig:
    return load_dashboard_config(CONFIG_PATH)


@st.cache_resource
def get_observer() -> GossipObserver:
    cfg = get_config()
    observer = GossipObserver(peers=cfg.peers, keys_dir=Path(cfg.keys_dir))
    observer.start()
    return observer


@st.cache_resource
def get_navmesh() -> Optional[NavMesh]:
    cfg = get_config()
    if not cfg.navmesh_path:
        return None
    path = Path(cfg.navmesh_path)
    if not path.exists():
        return None
    return NavMesh.from_geojson(path, cell_size_m=cfg.geometry.cell_size_m)


@st.cache_resource
def get_reachability() -> Optional[ReachabilityModel]:
    navmesh = get_navmesh()
    return ReachabilityModel(navmesh) if navmesh is not None else None


# ── Helpers ────────────────────────────────────────────────────────────

def fmt_dt(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def latest_t_media(observer: GossipObserver) -> float:
    """The dashboard's own reference "now" -- the newest media timestamp
    it has actually seen, never `time.time()` (this is the identity path:
    CLAUDE.md's "no wall-clock reads" applies to reasoning about WHEN a
    claim happened, not to this process's own liveness bookkeeping, which
    legitimately uses monotonic wall time in `observer.liveness()`).
    """
    claims = observer.claims.ordered()
    return max((c["t_media"] for c in claims), default=0.0)


def compute_assignment(observer: GossipObserver, reachability: Optional[ReachabilityModel]) -> tuple[Assignment, object]:
    cfg = get_config()
    reputation_snapshot = {node_id: observer.reputation.aggregate(node_id) for node_id in cfg.peers}
    return resolve(observer.claims, reachability, reputation_snapshot, topology=None, cfg=MatchConfig())


def latest_attestation_by_node(observer: GossipObserver) -> dict[int, "starling_pb2.CoverageAttestation"]:
    latest: dict[int, starling_pb2.CoverageAttestation] = {}
    for att in observer.attestations:
        latest[att.node_id] = att  # append order -> last write wins -> most recent
    return latest


def status_badge(online: bool) -> str:
    return "🟢 ONLINE" if online else "🔴 PARTITIONED"


# ── Sidebar ───────────────────────────────────────────────────────────────

cfg = get_config()
observer = get_observer()
navmesh = get_navmesh()
reachability = get_reachability()

with st.sidebar:
    st.title("🐦 Starling")
    st.caption("Read-only gossip observer — no database, no privileged view.")
    st.markdown("---")

    if st.button("🔄 Refresh", use_container_width=True, type="primary"):
        st.rerun()

    now_t_media = latest_t_media(observer)
    liveness = observer.liveness(stale_after_s=cfg.stale_after_s)
    online_count = sum(1 for v in liveness.values() if v)
    st.metric("Nodes online", f"{online_count} / {len(cfg.peers)}")

    coverage = observer.coverage_completeness(cfg.stale_after_s)
    if coverage < 1.0:
        st.warning(
            f"This view is INCOMPLETE: {len(cfg.peers) - online_count} of "
            f"{len(cfg.peers)} nodes unreachable from here. Showing what is "
            "known, not presenting it as the whole picture."
        )

    assignment, forks = compute_assignment(observer, reachability)
    open_forks = forks.open_forks() if hasattr(forks, "open_forks") else []
    st.metric("Identities tracked", len(assignment.trajectories))
    st.metric("Open forks", len(open_forks))

    total_bytes = sum(v.get("recv_bytes", 0) for k, v in observer.stats().items() if not k.startswith("_"))
    st.metric("Gossip bytes seen", f"{total_bytes:,}")
    st.caption(f"raw video bytes: {RAW_VIDEO_BYTES}")
    st.caption(f"Config: `{CONFIG_PATH}`")


# ── Tabs ──────────────────────────────────────────────────────────────────

tab_floor, tab_health, tab_forks, tab_network, tab_lost, tab_search, tab_detail, tab_controls = st.tabs([
    "🗺️ Floor Plan",
    "🩺 Node Health",
    "🔀 Forks",
    "📡 Network",
    "🔴 Unlocated",
    "🔍 Search",
    "👤 Identity Detail",
    "🎛️ Controls",
])

claims_by_id = {c["claim_id"]: c for c in observer.claims.ordered()}


def _last_claim_of(identity_ref: str) -> Optional[dict]:
    claim_ids = assignment.trajectories.get(identity_ref, [])
    for cid in reversed(claim_ids):
        record = claims_by_id.get(cid)
        if record is not None:
            return record
    return None


# Shared across tabs: which identities count as "unlocated" (no navmesh
# needed for this part — only the Floor Plan tab's belief RENDERING does).
unlocated_refs: list[tuple[str, dict, float]] = []
for _ref in sorted(assignment.trajectories):
    _last = _last_claim_of(_ref)
    if _last is None:
        continue
    _age = now_t_media - _last["t_media"]
    if _age >= cfg.lost_threshold_s:
        unlocated_refs.append((_ref, _last, _age))

latest_att = latest_attestation_by_node(observer)


# ══════════════════════════════════════════════════════════════════════
# FLOOR PLAN (main view)
# ══════════════════════════════════════════════════════════════════════

with tab_floor:
    if navmesh is None:
        st.info("No navmesh configured (`dashboard.navmesh_path`) — floor plan unavailable.")
    else:
        st.subheader("Candidate belief region — unlocated identities")

        beliefs: dict[str, dict] = st.session_state.setdefault("beliefs", {})
        ne_cfg = NegativeEvidenceConfig()

        # Drop beliefs for identities that are no longer unlocated (found again).
        for ref in list(beliefs.keys()):
            if ref not in {r for r, _, _ in unlocated_refs}:
                del beliefs[ref]

        for ref, last, age in unlocated_refs:
            state = beliefs.get(ref)
            if state is None:
                belief = CandidateBelief(navmesh, reachability, ne_cfg)
                origin = (last.get("world_x"), last.get("world_y"))
                if origin[0] is not None and origin[1] is not None:
                    belief.initialise(origin, pos_sigma=last.get("pos_sigma") or 0.0)
                state = {"belief": belief, "last_t_media": last["t_media"], "applied": set()}
                beliefs[ref] = state
            else:
                belief = state["belief"]
                dt_s = max(0.0, now_t_media - state["last_t_media"])
                if dt_s > 0:
                    belief.step(dt_s)
                    state["last_t_media"] = now_t_media

            for att in observer.attestations:
                key = (att.node_id, att.t_start.physical_ms)
                if key in state["applied"]:
                    continue
                belief.apply_attestation(att)
                state["applied"].add(key)
            belief.normalise()

        if unlocated_refs:
            options = [r for r, _, _ in unlocated_refs]
            selected_ref = st.selectbox("Show candidate region for", options)
            mask = beliefs[selected_ref]["belief"].mask()
            area = beliefs[selected_ref]["belief"].area_m2()
            st.metric("Candidate region area", f"{area:.1f} m²")
        else:
            st.success("No unlocated identities — nothing to shrink.")
            mask = None

        st.image(navmesh.render(mask=mask), use_column_width=True, caption="White = free space, dark = obstacle, red = candidate belief region")

        st.markdown("##### Coverage currently attested (per node)")
        if latest_att:
            st.dataframe(pd.DataFrame([
                {
                    "Node": node_id,
                    "Region ids watched": list(att.region_ids),
                    "Crossing observed": att.crossing_observed,
                    "attest_confidence": round(att.attest_confidence, 2),
                }
                for node_id, att in sorted(latest_att.items())
            ]), use_container_width=True)
        else:
            st.caption("No attestations observed yet.")


# ══════════════════════════════════════════════════════════════════════
# NODE HEALTH
# ══════════════════════════════════════════════════════════════════════

with tab_health:
    st.subheader("Per-node health")
    bytes_by_node = observer.bytes_per_node_since_start()
    uptime_s = max(observer.stats().get("_uptime_s", 0.0), 1e-6)

    rows = []
    for node_id in sorted(cfg.peers):
        online = liveness.get(node_id, False)
        reputation = observer.reputation.aggregate(node_id)
        att = latest_att.get(node_id)
        rows.append({
            "Node": node_id,
            "Status": status_badge(online),
            "Reputation": reputation,
            "attest_confidence": round(att.attest_confidence, 2) if att is not None else "—",
            "bytes/s (since start)": round(bytes_by_node.get(node_id, 0) / uptime_s, 1),
        })

    df = pd.DataFrame(rows)
    for _, row in df.iterrows():
        cols = st.columns([1, 2, 3, 2, 2])
        cols[0].markdown(f"**node-{row['Node']:02d}**")
        cols[1].markdown(row["Status"])
        cols[2].progress(max(0.0, min(1.0, float(row["Reputation"]))), text=f"reputation {row['Reputation']:.2f}")
        cols[3].markdown(f"attest_confidence: {row['attest_confidence']}")
        cols[4].markdown(f"{row['bytes/s (since start)']} B/s")

    st.caption(
        "coverage_completeness is a NODE's own self-assessment of its neighbour "
        "liveness — it is never gossiped (see starling_net.partition.PartitionTracker), "
        "so it cannot be shown here without giving the dashboard a privilege no "
        "other peer has. attest_confidence (gossiped, wire-visible) is shown instead."
    )


# ══════════════════════════════════════════════════════════════════════
# FORKS
# ══════════════════════════════════════════════════════════════════════

with tab_forks:
    st.subheader("Open identity forks")
    st.caption(
        "An open fork means two claim chains bind one identity to spatially "
        "incompatible trajectories and BOTH remain reachable. This is surfaced "
        "as an ambiguity for a human to resolve with real information (e.g. a "
        "face re-anchor) — there is deliberately no button here that picks a "
        "branch by score (CLAUDE.md rule 6)."
    )

    if not open_forks:
        st.success("No open forks.")
    else:
        for fork in open_forks:
            with st.expander(f"🔀 {fork.identity_ref}  —  fork {fork.fork_id}", expanded=True):
                cols = st.columns(len(fork.branches))
                for i, branch in enumerate(fork.branches):
                    with cols[i]:
                        st.markdown(f"**Branch {i}**")
                        st.markdown(f"{len(branch.claim_ids)} claim(s)")
                        st.markdown(f"Last position: {branch.last_position}")
                st.caption(
                    "Resolution requires a face re-anchor or explicit operator "
                    "action recorded elsewhere — not a score comparison here."
                )


# ══════════════════════════════════════════════════════════════════════
# NETWORK
# ══════════════════════════════════════════════════════════════════════

with tab_network:
    st.subheader("Gossip traffic by message type")
    stats = observer.stats()
    kind_rows = [
        {"Message type": kind, "Messages": v["recv"], "Bytes": v["recv_bytes"]}
        for kind, v in stats.items()
        if not kind.startswith("_")
    ]
    if kind_rows:
        st.dataframe(pd.DataFrame(kind_rows), use_container_width=True)
    else:
        st.caption("No gossip observed yet.")
    st.metric("raw video bytes", RAW_VIDEO_BYTES, help="Never incremented anywhere in this codebase — claims/attestations cannot carry frame data (starling_proto.limits.assert_wire_safe).")
    st.metric("Dropped (unsigned/tampered) messages", stats.get("_dropped", 0))


# ══════════════════════════════════════════════════════════════════════
# UNLOCATED (V1's "Lost Registry", re-interpreted)
# ══════════════════════════════════════════════════════════════════════

with tab_lost:
    st.subheader("Unlocated identities")
    st.info(
        "An identity with no claim in the last "
        f"{cfg.lost_threshold_s:.0f}s of media time. Not automatically "
        "deleted; it stays here until a new claim (or, in a real deployment, "
        "operator action recorded elsewhere) restores it."
    )
    notes: dict[str, str] = st.session_state.setdefault("notes", {})  # ephemeral, per-viewer only

    if not unlocated_refs:
        st.success("Nothing currently unlocated.")
    for ref, last, age in unlocated_refs:
        with st.expander(f"🔴 {ref} — missing for {fmt_dt(age)}"):
            st.markdown(f"**Last node:** node-{last['node_id']:02d}")
            st.markdown(f"**Last confidence:** {last['confidence']:.2f}")
            note = st.text_input("Note (this browser session only)", value=notes.get(ref, ""), key=f"note_{ref}")
            if note:
                notes[ref] = note


# ══════════════════════════════════════════════════════════════════════
# SEARCH
# ══════════════════════════════════════════════════════════════════════

with tab_search:
    st.subheader("Search")
    mode = st.radio("Search by", ["Identity", "Node", "Time window"], horizontal=True)
    results: list[str] = []

    if mode == "Identity":
        query = st.text_input("Identity ref (e.g. AUTO-... or P-003)")
        if query:
            results = [r for r in assignment.trajectories if query.strip().upper() in r.upper()]
    elif mode == "Node":
        node_id = st.number_input("Node id", min_value=0, value=0, step=1)
        results = [
            ref for ref, ids in assignment.trajectories.items()
            if any(claims_by_id.get(cid, {}).get("node_id") == node_id for cid in ids)
        ]
    else:
        hrs = st.slider("Look back (hours of media time)", 1, 24, 1)
        since = now_t_media - hrs * 3600
        results = [
            ref for ref, ids in assignment.trajectories.items()
            if any(claims_by_id.get(cid, {}).get("t_media", 0) >= since for cid in ids)
        ]

    if results:
        st.success(f"{len(results)} result(s)")
        st.dataframe(pd.DataFrame([
            {
                "Identity": ref,
                "Claims": len(assignment.trajectories[ref]),
                "Confidence": round(assignment.confidence.get(ref, 0.0), 2),
                "Last node": (_last_claim_of(ref) or {}).get("node_id"),
            }
            for ref in results
        ]), use_container_width=True)


# ══════════════════════════════════════════════════════════════════════
# IDENTITY DETAIL (V1's "Person Detail", re-interpreted)
# ══════════════════════════════════════════════════════════════════════

with tab_detail:
    st.subheader("Identity detail")
    refs = sorted(assignment.trajectories)
    if not refs:
        st.info("No identities tracked yet.")
    else:
        selected = st.selectbox("Select identity", refs)
        claim_ids = assignment.trajectories[selected]
        records = [claims_by_id[cid] for cid in claim_ids if cid in claims_by_id]

        st.markdown(f"**Confidence:** {assignment.confidence.get(selected, 0.0):.2f}")
        st.markdown(f"**Total claims:** {len(records)}")
        is_forked = any(f.identity_ref == selected for f in open_forks)
        if is_forked:
            st.warning("This identity currently has an OPEN fork — see the Forks tab.")

        st.markdown("##### Event timeline (derived from its claim trajectory)")
        prev_node = None
        for r in records:
            if prev_node is None:
                st.markdown(f"`{r['t_media']:.1f}` 🆕 first seen — node-{r['node_id']:02d}")
            elif r["node_id"] != prev_node:
                st.markdown(f"`{r['t_media']:.1f}` 🔄 handoff — node-{prev_node:02d} → node-{r['node_id']:02d}")
            prev_node = r["node_id"]

        st.markdown("##### Full claim log")
        st.dataframe(pd.DataFrame([
            {"Node": r["node_id"], "t_media": round(r["t_media"], 2), "Confidence": round(r["confidence"], 2), "Anchor": r["anchor_type"]}
            for r in records
        ]), use_container_width=True)


# ══════════════════════════════════════════════════════════════════════
# CONTROLS — "Make node N lie"
# ══════════════════════════════════════════════════════════════════════

with tab_controls:
    st.subheader("🎛️ Attack injection (demo)")
    st.caption(
        "POSTs directly to that node's own control endpoint "
        "(starling_consensus.attacks.ControlServer) — the dashboard does not "
        "relay this through gossip, it is a direct operator action against "
        "one node's own process, same as pressing a physical switch on it."
    )

    for node_id, addr in sorted(cfg.peers.items()):
        host = addr.split(":")[0]
        gossip_port = int(addr.split(":")[1])
        control_port = gossip_port + cfg.control_port_offset

        cols = st.columns([1, 2, 2, 2])
        cols[0].markdown(f"**node-{node_id:02d}**")
        attack = cols[1].selectbox(
            "Attack", ["none", "fabricate", "suppress", "replay", "mixed"],
            key=f"attack_type_{node_id}", label_visibility="collapsed",
        )
        intensity = cols[2].slider("Intensity", 0.0, 1.0, 0.5, key=f"attack_intensity_{node_id}", label_visibility="collapsed")
        if cols[3].button(f"Make node {node_id} lie", key=f"attack_btn_{node_id}"):
            try:
                resp = requests.post(
                    f"http://{host}:{control_port}/attack",
                    json={"attack": attack, "intensity": intensity},
                    timeout=2.0,
                )
                if resp.ok:
                    st.success(f"node-{node_id:02d} now running attack={attack} intensity={intensity}")
                else:
                    st.error(f"node-{node_id:02d} refused: HTTP {resp.status_code}")
            except requests.RequestException as e:
                st.error(f"Could not reach node-{node_id:02d}'s control endpoint at {host}:{control_port}: {e}")
