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

import numpy as np

from starling_sim.identity import noisy_embedding
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
    world: World, node_id: int, cfg: PerceptionSimConfig, rng: np.random.Generator
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
    for worker in world.workers_in_zone(node_id):
        if rng.random() < cfg.detection_miss_prob:
            continue

        noisy_pos = (
            worker.pos[0] + float(rng.normal(scale=cfg.pos_noise_sigma_m)),
            worker.pos[1] + float(rng.normal(scale=cfg.pos_noise_sigma_m)),
        )
        embedding = noisy_embedding(worker.identity_vector, cfg.embedding_noise_sigma, rng)
        obs = SimObservation(
            local_track_id=worker.worker_id,
            conf=float(rng.uniform(cfg.conf_min, cfg.conf_max)),
            embedding=embedding,
            quality=float(rng.uniform(cfg.quality_min, cfg.quality_max)),
            t_media=world.t_media,
        )
        results.append((obs, noisy_pos, cfg.pos_noise_sigma_m))
    return results


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
    )
    return obs, (d["world_x"], d["world_y"]), d["pos_sigma"]
