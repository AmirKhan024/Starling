"""starling_consensus/contradiction.py
--------------------------------------
Where C2 meets C4: a claim contradicted by ATTESTED ABSENCE.

A node claims "someone stood at p at time t". If p lies inside ANOTHER
camera's zone, and that camera was attesting — with a confidence above
`tau_attest` — that its zone was covered and healthy at t, and yet that
camera made no claim anywhere near p around t, then the claim contradicts
a confident, signed statement of absence. The claim is then implausible
(a hard failure in the reputation pass), exactly like a teleport.

What this deliberately does NOT do (CLAUDE.md rule 7): treat a camera's
silence as evidence. If the other camera did not attest confidently for
that moment — occluded, unhealthy, partitioned away, or simply not heard
from — there is no contradiction and the claim is graded as before.

Zones are static site geometry (the floor plan every node is deployed
with); attestations and claims are what the evaluating replica has merged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from shapely.geometry import Point, shape
from shapely.prepared import prep

# starling_sim.coverage.ZONE_REGION_BASE, duplicated so this package does not
# import the simulator: a zone attestation names region ZONE_REGION_BASE + node.
ZONE_REGION_BASE = 1000


@dataclass(frozen=True)
class Contradiction:
    by_node: int
    reason: str


class AttestedAbsenceCheck:
    def __init__(
        self,
        zones: dict[
            int, Any
        ],  # node_id -> prepared shapely geometry of its zone (inset by the caller)
        attestations: Callable[[], Iterable[Any]],  # CoverageAttestation protos merged so far
        tau_attest: float,
        radius_m: float,
        window_s: float,
        sigma_k: float = 0.0,
    ) -> None:
        self.zones = zones
        self.attestations = attestations
        self.tau_attest = tau_attest
        self.radius_m = radius_m
        self.window_s = window_s
        self.sigma_k = sigma_k

    def _attested_healthy(self, node: int, t: float) -> bool:
        region = ZONE_REGION_BASE + node
        for a in self.attestations():
            if (
                a.node_id != node
                or region not in a.region_ids
                or a.attest_confidence < self.tau_attest
            ):
                continue
            t0, t1 = a.t_start.physical_ms / 1000.0, a.t_end.physical_ms / 1000.0
            if t0 - 1e-6 <= t <= t1 + 1e-6:
                return True
        return False

    def check(
        self, claim: dict[str, Any], nearby_claims: list[dict[str, Any]]
    ) -> Optional[Contradiction]:
        """`nearby_claims`: claims (any node) within `window_s` of the
        claim's media time — the caller's existing time index."""
        x, y = claim.get("world_x"), claim.get("world_y")
        if x is None or y is None:
            return None
        p = Point(x, y)
        src, t = claim["node_id"], claim["t_media"]
        sigma = claim.get("pos_sigma") or 0.0
        for node in sorted(self.zones):
            if node == src or not self.zones[node].contains(p):
                continue
            if not self._attested_healthy(node, t):
                continue  # silence is never evidence
            seen_there = any(
                c["node_id"] == node
                and c.get("world_x") is not None
                and abs(c["t_media"] - t) <= self.window_s
                and math.hypot(c["world_x"] - x, c["world_y"] - y)
                <= self.radius_m + self.sigma_k * (sigma + (c.get("pos_sigma") or 0.0))
                for c in nearby_claims
            )
            if not seen_there:
                return Contradiction(
                    by_node=node,
                    reason=(
                        f"({x:.1f}, {y:.1f}) is in node {node}'s zone, which node {node} attested "
                        f"covered and healthy at t={t:.1f}, and it saw nobody there"
                    ),
                )
        return None


def load_inset_zones(floorplan_path: Any, inset_m: float) -> dict[int, Any]:
    """Every camera zone of a floor-plan GeoJSON, shrunk by `inset_m` and
    prepared for fast point tests."""
    import json

    with open(floorplan_path, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    out: dict[int, Any] = {}
    for feat in feats:
        props = feat.get("properties") or {}
        if props.get("role") == "camera_zone" and "node_id" in props:
            g = shape(feat["geometry"]).buffer(-inset_m)
            if not g.is_empty:
                out[int(props["node_id"])] = prep(g)
    return out
