"""starling_attest/negative_evidence.py
------------------------------------------
Negative-evidence belief fusion (WP-09 Part 3, C4 flagship — the sentence
that makes C4 and C2 one contribution rather than two: lying by omission
becomes detectable). Implements STARLING_BUILD_STATE.md Appendix A.3
exactly:

    B_0 = delta(last confirmed position), over the free-space grid
    each step:
      B <- geodesic_dilate(B, v_max * dt)
      for each admissible attestation a (attest_conf >= tau_attest,
              crossing_observed == False):
          B[cells beyond boundary(a)] <- 0
      for each positive observation o:
          B <- B * likelihood(o)
      B <- B / sum(B)
    report: area(B > eps) in m^2

Ambiguous-choice notes (CLAUDE.md: take the first option, comment,
continue) — both resolved the same way, in favour of the simplest
mechanically well-defined reading that still matches the physical intent:

1. "Beyond the boundary" (WP-09 Part 3's own prompt: "Precompute, per
   boundary segment, which side of it each free cell lies on, by a flood
   fill from the node's own ROI"). `CandidateBelief` has no reason to hold
   a registry of every node's ROI, and the physically relevant reference
   point is available anyway: the belief's own confirmed origin (the last
   place the missing identity was actually seen) is exactly the point that
   determines which side of a boundary counts as "near" — a boundary the
   person would have had to cross to leave that side. `NavMesh.cells_beyond`
   (WP-05/WP-09 addition) takes that origin as its reference, not a
   per-node ROI.
2. Dilation and mass. `B` is treated as a soft INDICATOR over the current
   candidate support set, not a fine-grained spatial density: each `step`
   assigns uniform mass to every cell within the dilation radius of ANY
   currently-supported cell, rather than convolving a detailed density
   forward (an unspecified, much more expensive operation Appendix A.3
   does not define). This is sufficient for every metric this module
   reports — `area_m2`, `false_exclusion_rate` (via `mask`) — which depend
   only on the support set, not on relative density values within it.
"""

from __future__ import annotations

import heapq
import math
from typing import Any, Optional

import numpy as np

from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_node.config import NegativeEvidenceConfig
from starling_proto.generated import starling_pb2

_SQRT2 = math.sqrt(2.0)
_NEIGHBOUR_OFFSETS = [
    (-1, -1, _SQRT2), (0, -1, 1.0), (1, -1, _SQRT2),
    (-1, 0, 1.0), (1, 0, 1.0),
    (-1, 1, _SQRT2), (0, 1, 1.0), (1, 1, _SQRT2),
]


def _field(obj: Any, name: str) -> Any:
    """`obj[name]` for a claim-record dict (`starling_store.LocalStore`'s
    shape), `getattr(obj, name)` otherwise — `apply_observation`'s `obs`
    is duck-typed the same way the rest of this project's claim handling
    is (see `starling_crdt.claims`).
    """
    return obj[name] if isinstance(obj, dict) else getattr(obj, name)


def _field_or(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class CandidateBelief:
    """A soft candidate-location mask for ONE currently-unlocated identity,
    over one shared `NavMesh`. Not thread-safe; not shared across
    identities (CLAUDE.md rule 1's node-isolation spirit applies at this
    smaller scope too — one belief per missing person, never a merged one).
    """

    def __init__(self, navmesh: NavMesh, reachability: ReachabilityModel, cfg: NegativeEvidenceConfig) -> None:
        self.navmesh = navmesh
        self.reachability = reachability
        self.cfg = cfg
        self._B = np.zeros(navmesh.grid.shape, dtype=np.float64)
        self._origin_xy: Optional[tuple[float, float]] = None
        self._origin_pos_sigma = 0.0

    def initialise(self, last_confirmed_xy: tuple[float, float], pos_sigma: float = 0.0) -> None:
        """`B_0 = delta(last_confirmed_xy)`. `pos_sigma` is stored (not
        expanded into a Gaussian prior) — Appendix A.3 is explicit that
        `B_0` is a delta, not a distribution; a future work package that
        wants a softer prior has where to plug it in without changing this
        method's contract.
        """
        i, j = self.navmesh.world_to_cell(*last_confirmed_xy)
        height, width = self._B.shape
        if not (0 <= i < width and 0 <= j < height) or not self.navmesh.grid[j, i]:
            raise ValueError(f"last_confirmed_xy={last_confirmed_xy} is not in free space")

        self._B = np.zeros((height, width), dtype=np.float64)
        self._B[j, i] = 1.0
        self._origin_xy = last_confirmed_xy
        self._origin_pos_sigma = pos_sigma

    def step(self, dt_s: float) -> None:
        """`B <- geodesic_dilate(B, v_max * dt_s)` — see module docstring
        note 2 for what "dilate" means for this soft-indicator `B`. A
        multi-source Dijkstra from every currently-supported cell, never
        stepping onto a non-free cell, so the dilated support never
        crosses an obstacle regardless of how large `dt_s` is.
        """
        support = self._B > self.cfg.eps
        if not support.any():
            return

        dist = self._multi_source_distance(support)
        radius = self.cfg.v_max_m_s * dt_s
        new_support = dist <= radius

        new_B = np.zeros_like(self._B)
        new_B[new_support] = 1.0
        self._B = new_B

    def _multi_source_distance(self, support: np.ndarray) -> np.ndarray:
        grid = self.navmesh.grid
        height, width = grid.shape
        cell_size = self.navmesh.cell_size

        dist = np.full((height, width), np.inf, dtype=np.float64)
        heap: list[tuple[float, int, int]] = []
        for j, i in zip(*np.nonzero(support)):
            i, j = int(i), int(j)
            if grid[j, i]:
                dist[j, i] = 0.0
                heap.append((0.0, i, j))
        heapq.heapify(heap)

        while heap:
            d, i, j = heapq.heappop(heap)
            if d > dist[j, i]:
                continue
            for di, dj, step_cost in _NEIGHBOUR_OFFSETS:
                ni, nj = i + di, j + dj
                if not (0 <= ni < width and 0 <= nj < height) or not grid[nj, ni]:
                    continue
                nd = d + step_cost * cell_size
                if nd < dist[nj, ni]:
                    dist[nj, ni] = nd
                    heapq.heappush(heap, (nd, ni, nj))
        return dist

    def apply_attestation(self, att: Optional["starling_pb2.CoverageAttestation"]) -> None:
        """`for each admissible attestation a (attest_conf >= tau_attest,
        crossing_observed == False): B[cells beyond boundary(a)] <- 0`.

        This class re-derives "admissible" itself from exactly the two
        conditions Appendix A.3 states (confidence floor + no crossing),
        independent of whatever a gossip-layer admission check
        (`starling_attest.admission.admissible`, which additionally checks
        signature/staleness/reputation) may already have applied upstream —
        the safety property this session's own acceptance test targets
        ("an inadmissible attestation does NOT shrink the area") must hold
        here, at the point mass actually gets zeroed, not only earlier in
        the pipeline.
        """
        if not self.cfg.negative_evidence_enabled or att is None:
            return
        if att.crossing_observed:
            return
        if att.attest_confidence < self.cfg.tau_attest:
            return
        if self._origin_xy is None:
            return

        for boundary_id in att.region_ids:
            beyond = self.navmesh.cells_beyond(boundary_id, self._origin_xy)
            self._B[beyond] = 0.0

    def apply_observation(self, obs: Any) -> None:
        """`B <- B * likelihood(o)`: a Gaussian kernel in floor metres,
        centred on `obs`'s world position, with sigma taken from `obs`'s
        own `pos_sigma` when present and positive, else
        `cfg.likelihood_sigma_m`. `obs` is duck-typed like a
        `starling_store.LocalStore` claim record (`world_x`/`world_y`/
        `pos_sigma`) or any object with those attributes.
        """
        x = _field_or(obs, "world_x")
        y = _field_or(obs, "world_y")
        if x is None or y is None:
            return

        sigma = _field_or(obs, "pos_sigma")
        if not sigma or sigma <= 0:
            sigma = self.cfg.likelihood_sigma_m

        height, width = self._B.shape
        jj, ii = np.mgrid[0:height, 0:width]
        xs = self.navmesh.origin[0] + (ii + 0.5) * self.navmesh.cell_size
        ys = self.navmesh.origin[1] + (jj + 0.5) * self.navmesh.cell_size
        d2 = (xs - x) ** 2 + (ys - y) ** 2
        likelihood = np.exp(-0.5 * d2 / (sigma ** 2))

        self._B = self._B * likelihood

    def normalise(self) -> None:
        """`B <- B / sum(B)`. A belief that has been zeroed to nothing
        (every candidate cell excluded — the false-exclusion failure mode
        this session's metrics exist to measure) is left as all-zero
        rather than raising or renormalising nonsense: `area_m2()` reports
        `0.0` for it, which is the honest, measurable signal that
        something upstream over-excluded, not a value to hide behind a
        division-by-zero guard that silently reinflates it.
        """
        total = float(self._B.sum())
        if total > 0:
            self._B = self._B / total

    def mask(self) -> np.ndarray:
        return self._B > self.cfg.eps

    def area_m2(self, eps: float = 1e-6) -> float:
        return self.navmesh.area_m2(self._B > eps)

    def render(self):
        """PIL image via `NavMesh.render` — the dashboard's (WP-13) shrinking
        candidate-region heatmap, and this session's own experiment plots.
        """
        return self.navmesh.render(mask=self.mask())


def detect_omission(
    att: Optional["starling_pb2.CoverageAttestation"],
    corroborating_claims: list[Any],
    cfg: NegativeEvidenceConfig,
) -> bool:
    """WP-09 Part 3 task 6 — the signal reputation (WP-10, not built this
    session) will consume, making lying by omission detectable: a node
    that attests healthy coverage with no crossing observed, while
    `cfg.min_omission_corroborators` or more OTHER nodes' claims jointly
    corroborate a crossing during the same window, should have seen it and
    didn't report it.

    `corroborating_claims`: claim records/objects each carrying a
    `node_id` (duck-typed, matching `apply_observation`'s convention).
    Only the *distinct* corroborating node_ids count — CLAUDE.md rule 6's
    spirit applies here too: one node's repeated say-so is not
    corroboration.
    """
    if att is None or att.crossing_observed:
        return False
    if att.attest_confidence < cfg.tau_attest:
        return False  # already inadmissible on its own; nothing to contradict

    corroborating_node_ids = {_field(c, "node_id") for c in corroborating_claims}
    corroborating_node_ids.discard(att.node_id)
    return len(corroborating_node_ids) >= cfg.min_omission_corroborators
