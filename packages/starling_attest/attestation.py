"""starling_attest/attestation.py
-----------------------------------
Coverage attestation emission (WP-09 Part 2, C4 flagship). This is what
turns Part 1's self-assessment into the wire object (§5.2
`CoverageAttestation`) that makes negative evidence sound rather than
dangerous.

The rule (CLAUDE.md rule 7 / STARLING_BUILD_STATE.md WP-09 task 4):
`crossing_observed = False` is only ever emitted when `attest_confidence`
clears `tau_attest`. Below threshold, `Attestor.tick` returns `None` — see
the comment at that branch. Downstream (`starling_attest.negative_evidence`)
must treat "no attestation" as "no evidence", never as "evidence of
absence".

`crossing_observed = True` is a different kind of claim: it says "this
node's detector actually fired on a crossing", which is self-verifying in
a way the negative claim is not, so it is never gated on `tau_attest` —
a partially-occluded node can still honestly report a crossing it did
detect, even while it cannot be trusted to assert it saw nothing.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from starling_geometry.calibration import bbox_floor_point
from starling_geometry.navmesh import NavMesh
from starling_net.hlc import HLC
from starling_net.keys import NodeKeys
from starling_node.config import AttestConfig
from starling_perception.coverage import CoverageAssessor, DetectorStats
from starling_proto.generated import starling_pb2


def _segment_cells(navmesh: NavMesh, p0: tuple[float, float], p1: tuple[float, float]) -> list[tuple[int, int]]:
    """Grid cells along the straight segment `p0 -> p1`, sampled at
    sub-cell intervals — the same sampling density
    `starling_geometry.navmesh._rasterize_line` uses for boundary
    LineStrings, so a track's path and a boundary are rasterised at
    comparable resolution and neither can "jump over" the other's cells.
    """
    import math

    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return [navmesh.world_to_cell(*p0)]
    n_samples = max(int(math.ceil(length / (navmesh.cell_size / 2))), 1)
    cells = []
    for k in range(n_samples + 1):
        frac = k / n_samples
        x = p0[0] + dx * frac
        y = p0[1] + dy * frac
        cell = navmesh.world_to_cell(x, y)
        if not cells or cells[-1] != cell:
            cells.append(cell)
    return cells


def _crosses_boundary(navmesh: NavMesh, boundary_id: int, p0: tuple[float, float], p1: tuple[float, float]) -> bool:
    """Whether the straight path `p0 -> p1` passes through any cell
    `navmesh.boundaries[boundary_id]` rasterised to. This is the crossing
    definition Part 2 uses — distinct from, and simpler than, Part 3's
    "beyond the boundary" region split (`starling_attest.negative_evidence`),
    which needs to know which SIDE a cell is on, not just whether a path
    touched the line.
    """
    boundary_cells = navmesh.boundaries.get(boundary_id)
    if not boundary_cells:
        return False
    boundary_cell_set = set(boundary_cells)
    return any(c in boundary_cell_set for c in _segment_cells(navmesh, p0, p1))


class Attestor:
    """One node's attestation-emission loop. `tick()` is called once per
    processed frame (mirroring `apps/node.py`'s per-frame loop); internally
    it only actually assesses/emits once `cfg.tick_interval_s` of MEDIA
    time (never wall-clock, per CLAUDE.md's no-`time.time()`-in-the-
    identity-path rule) has elapsed since the last emission.

    Reads `coverage_assessor.calibration` and `coverage_assessor.navmesh`
    for crossing detection rather than taking its own copies — see
    `CoverageAssessor`'s docstring for why.
    """

    def __init__(
        self,
        node_id: int,
        coverage_assessor: CoverageAssessor,
        cfg: AttestConfig,
        keys: Optional[NodeKeys] = None,
    ) -> None:
        self.node_id = node_id
        self.coverage_assessor = coverage_assessor
        self.cfg = cfg
        self.keys = keys

        self._interval_start_t_media: Optional[float] = None
        self._last_pos: dict[int, tuple[float, float]] = {}
        self._crossing_observed = False

    def _update_crossings(self, detections: Sequence[Any]) -> None:
        navmesh = self.coverage_assessor.navmesh
        calibration = self.coverage_assessor.calibration
        watched = self.coverage_assessor.cfg.watched_boundary_ids
        if navmesh is None or not watched:
            return

        for det in detections:
            local_track_id = getattr(det, "local_track_id", None)
            bbox = getattr(det, "bbox", None)
            if local_track_id is None or bbox is None:
                continue
            u, v = bbox_floor_point(bbox)
            pos = calibration.image_to_floor(u, v)
            prev = self._last_pos.get(local_track_id)
            if prev is not None:
                for boundary_id in watched:
                    if _crosses_boundary(navmesh, boundary_id, prev, pos):
                        self._crossing_observed = True
            self._last_pos[local_track_id] = pos

    def tick(
        self, t_media: float, frame, detections: Sequence[Any], stats: DetectorStats
    ) -> Optional["starling_pb2.CoverageAttestation"]:
        if self._interval_start_t_media is None:
            self._interval_start_t_media = t_media

        self._update_crossings(detections)

        if t_media - self._interval_start_t_media < self.cfg.tick_interval_s:
            return None

        state = self.coverage_assessor.assess(frame, detections, stats)
        cov_cfg = self.coverage_assessor.cfg
        interval_start = self._interval_start_t_media
        crossing_observed = self._crossing_observed

        self._interval_start_t_media = t_media
        self._crossing_observed = False

        if not crossing_observed and state.attest_confidence < cov_cfg.tau_attest:
            # Emitting nothing is correct. Downstream must treat absence of an
            # attestation as absence of evidence, never as evidence of absence.
            return None

        att = starling_pb2.CoverageAttestation(
            node_id=self.node_id,
            region_ids=list(cov_cfg.watched_boundary_ids),
            occlusion_ratio=state.occlusion_ratio,
            illumination_score=state.illumination_score,
            detector_health=state.detector_health,
            crossing_observed=crossing_observed,
            attest_confidence=state.attest_confidence,
        )
        att.t_start.CopyFrom(_hlc_proto(interval_start, self.node_id))
        att.t_end.CopyFrom(_hlc_proto(t_media, self.node_id))

        if self.keys is not None:
            att.signature = b""
            att.signature = self.keys.sign(att.SerializeToString())

        return att


def _hlc_proto(t_media: float, node_id: int) -> "starling_pb2.HLC":
    """Attestations are not part of the claim CRDT's causal-ordering
    machinery (`starling_net.hlc.HLCClock`) — they are independently
    timestamped, media-time-only instants, so `logical` is always 0 here
    rather than threading a second per-node HLCClock through this class.
    """
    hlc = HLC(physical_ms=int(t_media * 1000), logical=0, node_id=node_id)
    return starling_pb2.HLC(physical_ms=hlc.physical_ms, logical=hlc.logical, node_id=hlc.node_id)
