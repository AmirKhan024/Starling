"""starling_sim/coverage.py
----------------------------
The simulator-side half of C4 coverage attestation: ground-truth
occlusion state per node, and ground-truth boundary-crossing facts, both
computed from the world the simulator alone can see in full.

The signing/emission half (`SimAttestor`) deliberately lives here too but
runs on the NODE side, not the simulator side — a node signs its own
attestations with its own private key (CLAUDE.md rule 1/2: nothing outside
a node touches its keys), exactly like the real `starling_attest
.attestation.Attestor` does. The simulator only ever hands a node raw
coverage facts; turning that into a signed `CoverageAttestation`, gated by
`tau_attest` the same way the real Attestor gates it, is the node's own
job. `SimAttestor.tick` mirrors `Attestor.tick`'s admission rule exactly
(CLAUDE.md rule 7: silence is never evidence of absence) so the two paths
produce comparably-shaped attestations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from starling_geometry.navmesh import NavMesh
from starling_net.hlc import HLC
from starling_net.keys import NodeKeys
from starling_proto.generated import starling_pb2
from starling_sim.world import World


@dataclass
class CoverageState:
    occlusion_ratio: float
    illumination_score: float
    detector_health: float


def coverage_state_for_node(world: World, node_id: int) -> CoverageState:
    """Ground-truth coverage state for `node_id` this tick: healthy unless
    a scripted `OcclusionEvent` is currently active for it (see
    `starling_sim.scenario.ScenarioOcclusion` / `World.active_occlusion`).
    """
    event = world.active_occlusion(node_id)
    if event is None:
        return CoverageState(occlusion_ratio=0.0, illumination_score=1.0, detector_health=1.0)
    return CoverageState(
        occlusion_ratio=event.occlusion_ratio,
        illumination_score=1.0,
        detector_health=event.detector_health,
    )


def _segment_crosses_boundary(
    navmesh: NavMesh, boundary_id: int, p0: tuple[float, float], p1: tuple[float, float]
) -> bool:
    """Whether straight path `p0 -> p1` passes through any cell
    `navmesh.boundaries[boundary_id]` rasterised to — the same crossing
    definition `starling_attest.attestation._crosses_boundary` uses,
    reimplemented here rather than imported so this package never depends
    on `starling_attest`/`starling_perception` (both pull in heavier deps
    than the simulator needs — see requirements-sim.txt).
    """
    boundary_cells = navmesh.boundaries.get(boundary_id)
    if not boundary_cells:
        return False
    boundary_set = set(boundary_cells)

    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    n_samples = max(int(math.ceil(length / (navmesh.cell_size / 2))), 1) if length else 1
    for k in range(n_samples + 1):
        frac = k / n_samples if n_samples else 0.0
        x, y = p0[0] + dx * frac, p0[1] + dy * frac
        if navmesh.world_to_cell(x, y) in boundary_set:
            return True
    return False


def compute_boundary_crossings(
    navmesh: NavMesh,
    prev_positions: dict[int, tuple[float, float]],
    cur_positions: dict[int, tuple[float, float]],
) -> dict[int, bool]:
    """Ground truth: which of `navmesh.boundaries` any worker actually
    crossed between the previous tick's positions and this tick's — sent
    to EVERY node (a boundary crossing is a fact about the floor plan, not
    a secret; only `SimAttestor` filters it down to the boundaries a
    given node actually watches).
    """
    result = {boundary_id: False for boundary_id in navmesh.boundaries}
    for worker_id, p1 in cur_positions.items():
        p0 = prev_positions.get(worker_id, p1)
        for boundary_id in navmesh.boundaries:
            if not result[boundary_id] and _segment_crosses_boundary(navmesh, boundary_id, p0, p1):
                result[boundary_id] = True
    return result


def _hlc_proto(t_media: float, node_id: int) -> "starling_pb2.HLC":
    """Mirrors `starling_attest.attestation._hlc_proto` exactly: an
    attestation's timestamps are media-time-only instants, not part of
    the claim CRDT's causal-ordering HLC, so `logical` is always 0."""
    hlc = HLC(physical_ms=int(t_media * 1000), logical=0, node_id=node_id)
    return starling_pb2.HLC(physical_ms=hlc.physical_ms, logical=hlc.logical, node_id=hlc.node_id)


# An attestation's `region_ids` may name the ATTESTING NODE'S OWN CAMERA ZONE as
# ZONE_REGION_BASE + node_id: "my zone is covered and healthy for this interval".
# That, not a boundary crossing, is what lets a reader subtract the whole zone
# from a missing person's candidate region (starling_attest.negative_evidence).
ZONE_REGION_BASE = 1000


class SimAttestor:
    """A sim-mode node's attestation-emission loop — the counterpart of
    `starling_attest.attestation.Attestor`, driven by simulated
    ground-truth coverage/crossing facts instead of a frame and a
    background model. `observe_tick` is called every sim tick (to
    accumulate crossings between emission intervals, same as the real
    Attestor's `_update_crossings`); `tick` is called on whatever cadence
    the node's housekeeping loop runs at and only actually emits once
    `tick_interval_s` of media time has elapsed, exactly like
    `Attestor.tick`.
    """

    def __init__(
        self,
        node_id: int,
        watched_boundary_ids: list[int],
        tau_attest: float,
        tick_interval_s: float,
        keys: Optional[NodeKeys] = None,
    ) -> None:
        self.node_id = node_id
        self.watched_boundary_ids = list(watched_boundary_ids)
        self.tau_attest = tau_attest
        self.tick_interval_s = tick_interval_s
        self.keys = keys

        self._interval_start_t_media: Optional[float] = None
        self._crossing_observed = False

    def observe_tick(self, boundary_crossings: dict[str, bool]) -> None:
        """`boundary_crossings` as received on the wire: JSON object keys
        are always strings, so boundary ids arrive as strings here —
        compared against `str(watched_id)` rather than requiring the
        caller to convert back to int first.
        """
        watched = {str(bid) for bid in self.watched_boundary_ids}
        if any(boundary_crossings.get(bid, False) for bid in watched):
            self._crossing_observed = True

    def tick(self, t_media: float, coverage: CoverageState) -> Optional["starling_pb2.CoverageAttestation"]:
        if self._interval_start_t_media is None:
            self._interval_start_t_media = t_media

        if t_media - self._interval_start_t_media < self.tick_interval_s:
            return None

        interval_start = self._interval_start_t_media
        crossing_observed = self._crossing_observed
        self._interval_start_t_media = t_media
        self._crossing_observed = False

        attest_confidence = min(
            1.0 - coverage.occlusion_ratio, coverage.illumination_score, coverage.detector_health
        )
        if not crossing_observed and attest_confidence < self.tau_attest:
            # Silence is correct here, not a gap to fill in — downstream
            # must never read "no attestation" as "confirmed empty"
            # (CLAUDE.md rule 7).
            return None

        att = starling_pb2.CoverageAttestation(
            node_id=self.node_id,
            region_ids=[*self.watched_boundary_ids, ZONE_REGION_BASE + self.node_id],
            occlusion_ratio=coverage.occlusion_ratio,
            illumination_score=coverage.illumination_score,
            detector_health=coverage.detector_health,
            crossing_observed=crossing_observed,
            attest_confidence=attest_confidence,
        )
        att.t_start.CopyFrom(_hlc_proto(interval_start, self.node_id))
        att.t_end.CopyFrom(_hlc_proto(t_media, self.node_id))

        if self.keys is not None:
            att.signature = b""
            att.signature = self.keys.sign(att.SerializeToString())

        return att
