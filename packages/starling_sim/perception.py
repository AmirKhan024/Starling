"""starling_sim/perception.py
------------------------------
What one node's camera would have produced this tick, if it were real: a
list of noisy detections, restricted to workers physically inside that
node's own zone. This is the simulator-side replacement for
`starling_perception.pipeline.NodePerception.process()` plus the
`CameraCalibration.image_to_floor` step `apps/node.py`'s video path runs
afterwards — the simulator already knows world-frame positions, so there
is no image plane or homography involved at all.

`SimObservation` duck-types `starling_perception.pipeline.Observation`
(the fields `starling_store.identity_store.LocalStore
.append_local_observation` actually reads: local_track_id, conf,
embedding, quality, t_media) without importing that module, which would
pull in torch/ultralytics — see requirements-sim.txt and STATUS.md's
Step 1 decision about keeping the sim path torch-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from starling_sim.identity import noisy_embedding
from starling_sim.realism import CameraModel, optional_false_positive_point
from starling_sim.world import World


@dataclass
class SimObservation:
    local_track_id: int
    conf: float
    embedding: np.ndarray
    quality: float
    t_media: float
    # Never read by LocalStore.append_local_observation (bbox only matters
    # to the video path's bbox_floor_point/homography step) — present
    # purely so this duck-types Observation completely, in case future
    # code inspects it.
    bbox: tuple[int, int, int, int] = (0, 0, 1, 1)
    # Set when the worker stands at a face-recognition gate: the identity the
    # face matcher reports (a FACE_ANCHOR claim). Two people can share one.
    anchor_identity: Optional[str] = None
    # EVALUATION ONLY. Which simulated worker this detection really came from
    # (None for a false positive). Deliberately NOT included in `obs_to_dict`,
    # so it can never reach a node over the wire — it exists purely so an
    # in-process scorer (scripts/run_identity_ablation.py) can grade the
    # resolver against ground truth. Nothing in apps/ or packages/starling_*
    # outside the simulator may read it.
    true_worker_id: Optional[int] = None


@dataclass
class PerceptionSimConfig:
    pos_noise_sigma_m: float = 0.15
    embedding_noise_sigma: float = 0.05
    detection_miss_prob: float = 0.03
    conf_min: float = 0.75
    conf_max: float = 0.98
    quality_min: float = 0.5
    quality_max: float = 0.95


def observe_zone(
    world: World,
    node_id: int,
    cfg: PerceptionSimConfig,
    rng: np.random.Generator,
    camera: Optional[CameraModel] = None,
    tick: int = 0,
    zone_reach_m: float = 0.0,
) -> list[tuple[SimObservation, tuple[float, float], float]]:
    """One (`SimObservation`, `world_pos`, `pos_sigma`) triple per worker
    currently inside `node_id`'s zone — ready for
    `LocalStore.append_local_observation(obs, world_pos=.., pos_sigma=..)`
    exactly as apps/node.py's video path already calls it. Never includes
    a worker outside the zone: this function is the one place the
    simulator's "only ever send a node its own zone's evidence" rule
    (see the package docstring) is actually enforced.
    """
    results: list[tuple[SimObservation, tuple[float, float], float]] = []
    in_zone = world.workers_in_zone(node_id)

    # A real local tracker confuses two people who pass close to each other.
    if camera is not None:
        camera.maybe_swap_tracks({w.worker_id: w.pos for w in in_zone})

    for worker in in_zone:
        if camera is not None:
            if camera.should_miss(worker.worker_id, tick, cfg.detection_miss_prob):
                continue
        elif rng.random() < cfg.detection_miss_prob:
            continue

        if camera is None:
            noisy_pos = (
                worker.pos[0] + float(rng.normal(scale=cfg.pos_noise_sigma_m)),
                worker.pos[1] + float(rng.normal(scale=cfg.pos_noise_sigma_m)),
            )
            reported_sigma = cfg.pos_noise_sigma_m
            embedding = noisy_embedding(worker.identity_vector, cfg.embedding_noise_sigma, rng)
            conf_scale = 1.0
            track_id = worker.worker_id
        else:
            noisy_pos, reported_sigma = camera.observed_position(worker.pos, cfg.pos_noise_sigma_m)
            distance = camera.distance_to(worker.pos)
            embedding = camera.observed_embedding(
                worker.identity_vector, distance, cfg.embedding_noise_sigma
            )
            conf_scale = camera.confidence_scale(distance, zone_reach_m)
            track_id = camera.track_id_for(worker.worker_id)

        obs = SimObservation(
            local_track_id=track_id,
            conf=float(rng.uniform(cfg.conf_min, cfg.conf_max)) * conf_scale,
            embedding=embedding,
            quality=float(rng.uniform(cfg.quality_min, cfg.quality_max)) * conf_scale,
            t_media=world.t_media,
            anchor_identity=_anchor_identity(world, node_id, worker),
            true_worker_id=worker.worker_id,
        )
        results.append((obs, noisy_pos, reported_sigma))

    # A pallet or a shadow, briefly detected as a person.
    if camera is not None and camera.maybe_false_positive():
        poly = world.zones.get(node_id)
        point = optional_false_positive_point(poly, rng) if poly is not None else None
        if point is not None:
            ghost = SimObservation(
                local_track_id=camera.new_track_id(),
                conf=float(rng.uniform(cfg.conf_min, cfg.conf_max)) * 0.7,
                embedding=camera.random_embedding(),
                quality=float(rng.uniform(cfg.quality_min, cfg.quality_max)) * 0.6,
                t_media=world.t_media,
            )
            results.append((ghost, point, cfg.pos_noise_sigma_m * 2.0))
    return results


def _anchor_identity(world: World, node_id: int, worker) -> Optional[str]:
    if not worker.face_identity:
        return None
    for idx, a in enumerate(world.anchors):
        if a.node_id == node_id and (worker.pos[0] - a.x) ** 2 + (worker.pos[1] - a.y) ** 2 <= a.radius**2:
            last = world.last_anchor_t.get((worker.worker_id, idx))
            if last is not None and world.t_media - last < a.cooldown_s:
                return None  # already recognised at this gate on this pass
            world.last_anchor_t[(worker.worker_id, idx)] = world.t_media
            return worker.face_identity
    return None


def obs_to_dict(obs: SimObservation, world_pos: tuple[float, float], pos_sigma: float) -> dict:
    """JSON-safe wire form of one (obs, world_pos, pos_sigma) triple, sent
    over the simulator's per-node ZMQ topic (starling_sim.transport)."""
    return {
        "local_track_id": obs.local_track_id,
        "conf": obs.conf,
        "quality": obs.quality,
        "t_media": obs.t_media,
        "embedding": [float(x) for x in obs.embedding],
        "world_x": world_pos[0],
        "world_y": world_pos[1],
        "pos_sigma": pos_sigma,
        "anchor_identity": obs.anchor_identity,
    }


def dict_to_obs(d: dict) -> tuple[SimObservation, tuple[float, float], float]:
    """The inverse of `obs_to_dict` — what a sim-mode node reconstructs
    on receipt (starling_sim.node_client)."""
    obs = SimObservation(
        local_track_id=d["local_track_id"],
        conf=d["conf"],
        embedding=np.array(d["embedding"], dtype=np.float32),
        quality=d["quality"],
        t_media=d["t_media"],
        anchor_identity=d.get("anchor_identity"),
    )
    return obs, (d["world_x"], d["world_y"]), d["pos_sigma"]
