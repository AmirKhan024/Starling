"""starling_sim/realism.py
---------------------------
How much like a real camera should a simulated camera behave?

The simulator's default (`demo`) profile is deliberately clean: every worker
looks completely unlike every other worker, every detection lands within a few
centimetres of the truth, and each camera tracks each person perfectly forever.
That is useful for a presentation, but it makes the identity problem far easier
than it is in reality — measurably so. With `demo` settings the cosine
similarity between two observations of the SAME person is ~0.86 while two
DIFFERENT people sit at ~-0.07: a gap of 0.93 with literally zero overlap, so
any threshold at all separates them perfectly. Published multi-camera re-ID
(Market-1501 / DukeMTMC family) separates same-person from different-person by
roughly 0.15-0.25 WITH substantial overlap — that overlap is the entire reason
cross-camera re-identification is a research problem.

This module adds the effects that close that gap, as a selectable profile so
the clean behaviour stays available:

  demo       what the simulator has always done (default; nothing changes)
  realistic  calibrated to the published separability range
  harsh      a deliberately hostile site (poor lighting, heavy occlusion)

The effects, each modelling something specific and real:

  * PER-CAMERA APPEARANCE BIAS - the single biggest missing piece. A real
    camera sees a person from its own angle, under its own lighting, so the
    SAME person yields systematically different embeddings at different
    cameras. Without this, cross-camera matching is free.
  * UNIFORM SIMILARITY - warehouse staff dress alike, so different people are
    genuinely confusable (`SimulatorConfig.uniform_similarity`, wired here).
  * DISTANCE-DEPENDENT QUALITY - detections far from the camera are noisier in
    both position and appearance, and lower-confidence.
  * PROJECTION BIAS - floor position from a bounding box is not zero-mean; the
    error grows with distance and pushes systematically away from the camera.
  * GROSS OUTLIERS - occasionally a bad box puts someone metres away.
  * CLUSTERED MISSES - people vanish behind racking for a RUN of frames, not
    by independent per-frame coin flips.
  * FALSE POSITIVES - a pallet or a shadow is briefly detected as a person.
  * TRACKER FRAGMENTATION AND ID SWITCHES - real local trackers lose a track
    and restart it under a new id, and swap ids when two people cross. The
    default simulator instead uses `local_track_id = worker_id` forever, which
    hands the system a perfect within-camera tracker for free.

Everything here is per-camera state, so it lives in `CameraModel`, one per
node, owned by `starling_sim.runner.SimulatorRunner`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


@dataclass
class RealismProfile:
    """Every knob that separates a simulated camera from a real one. All
    defaults are the `demo` (no-op) values, so constructing a bare
    `RealismProfile()` reproduces the simulator's historical behaviour
    exactly."""

    name: str = "demo"

    # -- appearance -----------------------------------------------------
    # How far each camera's own viewpoint/lighting shifts the embeddings it
    # produces (0 = every camera sees identical features; the unrealistic case).
    camera_bias: float = 0.0
    # How alike different people look (same uniform). 0 = maximally distinct.
    uniform_similarity: float = 0.0
    # Extra embedding noise added per metre of distance from the camera.
    embedding_noise_per_m: float = 0.0

    # -- geometry -------------------------------------------------------
    # Position error added per metre of distance from the camera.
    pos_noise_per_m: float = 0.0
    # Systematic outward (away-from-camera) projection bias, per metre.
    projection_bias_per_m: float = 0.0
    # Chance per detection of a gross box failure, and how far it throws it.
    outlier_prob: float = 0.0
    outlier_sigma_m: float = 3.0

    # -- detection ------------------------------------------------------
    # Once a worker is missed, keep missing them for this many ticks
    # (occlusion behind racking), sampled uniformly in [lo, hi].
    miss_run_ticks: tuple[int, int] = (1, 1)
    # Chance per camera per tick of inventing a person who is not there.
    false_positive_prob: float = 0.0
    # Confidence/quality penalty applied at the far edge of a zone.
    far_confidence_penalty: float = 0.0

    # -- local tracker --------------------------------------------------
    # Chance per worker per tick that the camera's own tracker drops the
    # track and restarts it under a brand-new local id.
    track_break_prob: float = 0.0
    # Two workers closer than this may have their local track ids swapped...
    swap_distance_m: float = 1.5
    # ...with this chance per tick while they are that close.
    track_swap_prob: float = 0.0


PROFILES: dict[str, RealismProfile] = {
    # Historical behaviour. Nothing is added; every effect above is off.
    "demo": RealismProfile(name="demo"),
    # Calibrated so same-person / different-person cosine separation lands in
    # the published multi-camera re-ID range, with real overlap. See
    # scripts/measure_sim_realism.py, which reports the achieved numbers.
    "realistic": RealismProfile(
        name="realistic",
        camera_bias=0.25,
        uniform_similarity=0.50,
        embedding_noise_per_m=0.010,
        pos_noise_per_m=0.045,
        projection_bias_per_m=0.012,
        outlier_prob=0.004,
        outlier_sigma_m=2.5,
        miss_run_ticks=(2, 9),
        false_positive_prob=0.010,
        far_confidence_penalty=0.25,
        track_break_prob=0.006,
        swap_distance_m=1.5,
        track_swap_prob=0.030,
    ),
    # A bad site: dim, cluttered, cameras mounted badly.
    "harsh": RealismProfile(
        name="harsh",
        camera_bias=0.35,
        uniform_similarity=0.65,
        embedding_noise_per_m=0.015,
        pos_noise_per_m=0.080,
        projection_bias_per_m=0.025,
        outlier_prob=0.012,
        outlier_sigma_m=3.5,
        miss_run_ticks=(3, 16),
        false_positive_prob=0.025,
        far_confidence_penalty=0.40,
        track_break_prob=0.015,
        swap_distance_m=2.0,
        track_swap_prob=0.070,
    ),
}


def get_profile(name: str) -> RealismProfile:
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown realism profile {name!r}; choose one of {sorted(PROFILES)}") from None


@dataclass
class CameraModel:
    """One simulated camera's own imperfections, persistent across ticks.

    `mount_xy` is where the camera is taken to be mounted (the centroid of its
    own zone — an overhead warehouse camera), which is what distance-dependent
    error is measured from.
    """

    node_id: int
    mount_xy: tuple[float, float]
    profile: RealismProfile
    embed_dim: int
    seed: int

    _bias_vec: np.ndarray = field(init=False, repr=False)
    _track_of: dict[int, int] = field(default_factory=dict, init=False, repr=False)
    _miss_until: dict[int, int] = field(default_factory=dict, init=False, repr=False)
    _next_track: int = field(default=0, init=False, repr=False)
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Each camera's own fixed viewpoint/lighting direction in embedding
        # space, stable for the camera's lifetime (it is a property of where
        # the camera is bolted, not of any one frame).
        rng = np.random.default_rng(self.seed + 9001 * (self.node_id + 1))
        v = rng.normal(size=self.embed_dim)
        self._bias_vec = (v / np.linalg.norm(v)).astype(np.float32)
        self._rng = np.random.default_rng(self.seed + 7717 * (self.node_id + 1))
        # Local track ids start well apart per camera so a reader can never
        # accidentally match two cameras' tracks by id alone.
        self._next_track = 1000 * (self.node_id + 1)

    # -- appearance -----------------------------------------------------

    def observed_embedding(self, identity_vector: np.ndarray, distance_m: float, base_noise: float) -> np.ndarray:
        """This camera's view of a person: their identity, pulled toward this
        camera's own viewpoint bias, plus noise that grows with distance."""
        p = self.profile
        v = identity_vector.astype(np.float32)
        if p.camera_bias > 0:
            v = (1.0 - p.camera_bias) * v + p.camera_bias * self._bias_vec
        sigma = base_noise + p.embedding_noise_per_m * distance_m
        v = v + self._rng.normal(scale=sigma, size=v.shape)
        n = np.linalg.norm(v)
        return (v / n).astype(np.float32) if n > 0 else v.astype(np.float32)

    # -- geometry -------------------------------------------------------

    def observed_position(self, true_xy: tuple[float, float], base_sigma: float) -> tuple[tuple[float, float], float]:
        """A noisy floor position and the sigma the node should be told. Error
        grows with distance and is biased outward (a real bounding-box floor
        point lands beyond the person as they get further from the camera)."""
        p = self.profile
        dx, dy = true_xy[0] - self.mount_xy[0], true_xy[1] - self.mount_xy[1]
        dist = float(np.hypot(dx, dy))
        sigma = base_sigma + p.pos_noise_per_m * dist

        x = true_xy[0] + float(self._rng.normal(scale=sigma))
        y = true_xy[1] + float(self._rng.normal(scale=sigma))

        if p.projection_bias_per_m > 0 and dist > 1e-6:
            bias = p.projection_bias_per_m * dist
            x += bias * dx / dist
            y += bias * dy / dist

        if p.outlier_prob > 0 and self._rng.random() < p.outlier_prob:
            x += float(self._rng.normal(scale=p.outlier_sigma_m))
            y += float(self._rng.normal(scale=p.outlier_sigma_m))

        # The node is told the nominal sigma for this range — a real system
        # knows its own calibration curve, not the realisation of the error.
        return (x, y), sigma

    def distance_to(self, xy: tuple[float, float]) -> float:
        return float(np.hypot(xy[0] - self.mount_xy[0], xy[1] - self.mount_xy[1]))

    def confidence_scale(self, distance_m: float, zone_reach_m: float) -> float:
        """1.0 directly under the camera, falling to (1 - penalty) at the far
        edge of its zone."""
        p = self.profile
        if p.far_confidence_penalty <= 0 or zone_reach_m <= 0:
            return 1.0
        frac = min(1.0, distance_m / zone_reach_m)
        return 1.0 - p.far_confidence_penalty * frac

    # -- detection ------------------------------------------------------

    def should_miss(self, worker_id: int, tick: int, base_miss_prob: float) -> bool:
        """Misses come in runs: once a person is lost behind racking they stay
        lost for several consecutive frames, which is what actually creates
        track fragmentation in a real deployment."""
        until = self._miss_until.get(worker_id)
        if until is not None and tick < until:
            return True
        if self._rng.random() < base_miss_prob:
            lo, hi = self.profile.miss_run_ticks
            self._miss_until[worker_id] = tick + int(self._rng.integers(lo, hi + 1))
            return True
        return False

    def maybe_false_positive(self) -> bool:
        return self.profile.false_positive_prob > 0 and self._rng.random() < self.profile.false_positive_prob

    def random_embedding(self) -> np.ndarray:
        v = self._rng.normal(size=self.embed_dim)
        return (v / np.linalg.norm(v)).astype(np.float32)

    def new_track_id(self) -> int:
        self._next_track += 1
        return self._next_track

    # -- local tracker --------------------------------------------------

    def track_id_for(self, worker_id: int) -> int:
        """This camera's own id for a person. Stable until the tracker breaks
        it. NOTE the `demo` profile keeps the historical behaviour of using the
        worker's own id, so existing tests and scenarios are unaffected."""
        if self.profile.track_break_prob <= 0 and self.profile.track_swap_prob <= 0:
            return worker_id
        tid = self._track_of.get(worker_id)
        if tid is None or self._rng.random() < self.profile.track_break_prob:
            tid = self.new_track_id()
            self._track_of[worker_id] = tid
        return tid

    def maybe_swap_tracks(self, positions: dict[int, tuple[float, float]]) -> list[tuple[int, int]]:
        """Swap the local ids of two people who are close enough to be
        confused. Returns the pairs swapped, for logging/tests."""
        p = self.profile
        if p.track_swap_prob <= 0:
            return []
        swapped: list[tuple[int, int]] = []
        ids = sorted(positions)
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                ax, ay = positions[a]
                bx, by = positions[b]
                if np.hypot(ax - bx, ay - by) > p.swap_distance_m:
                    continue
                if self._rng.random() >= p.track_swap_prob:
                    continue
                ta, tb = self.track_id_for(a), self.track_id_for(b)
                self._track_of[a], self._track_of[b] = tb, ta
                swapped.append((a, b))
        return swapped


def zone_mount_points(zones: dict[int, Any]) -> dict[int, tuple[float, float]]:
    """Where each camera is taken to be: the centroid of its own zone, i.e.
    an overhead camera in the middle of the area it covers."""
    out: dict[int, tuple[float, float]] = {}
    for node_id, poly in zones.items():
        c = poly.centroid
        out[node_id] = (float(c.x), float(c.y))
    return out


def zone_reach(zones: dict[int, Any]) -> dict[int, float]:
    """Half the diagonal of each zone's bounding box — the distance from the
    mount point to the furthest corner it has to cover."""
    out: dict[int, float] = {}
    for node_id, poly in zones.items():
        minx, miny, maxx, maxy = poly.bounds
        out[node_id] = 0.5 * float(np.hypot(maxx - minx, maxy - miny))
    return out


def build_camera_models(
    zones: dict[int, Any], profile: RealismProfile, embed_dim: int, seed: int
) -> dict[int, CameraModel]:
    mounts = zone_mount_points(zones)
    return {
        node_id: CameraModel(
            node_id=node_id, mount_xy=mounts[node_id], profile=profile, embed_dim=embed_dim, seed=seed
        )
        for node_id in zones
    }


def optional_false_positive_point(poly: Any, rng: np.random.Generator) -> Optional[tuple[float, float]]:
    """A random point inside a zone, for a phantom detection."""
    minx, miny, maxx, maxy = poly.bounds
    for _ in range(12):
        x = float(rng.uniform(minx, maxx))
        y = float(rng.uniform(miny, maxy))
        from shapely.geometry import Point

        if poly.contains(Point(x, y)):
            return (x, y)
    return None
