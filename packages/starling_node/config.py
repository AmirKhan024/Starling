"""Pydantic config models for a Starling node.

Every threshold that was hardcoded in V1 (0.60, 0.35, 120, 30, ...) is a
documented field here instead. Nothing in the identity/perception path may
read a magic number directly — it comes from one of these models, loaded
from configs/nodes/node-NN.yaml.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class PerceptionConfig(BaseModel):
    yolo_model: str = "yolov8n.pt"
    conf: float = 0.35
    embed_dim: int = 512
    batch_size: int = 8
    device: str = "auto"
    save_crops: bool = False
    crop_interval_s: float = 10.0
    # D-01 fix: selectable ReID backend. "osnet" (Market-1501-trained, falls
    # back to "pooled" if weights/torchreid are unavailable) is the only
    # backend permitted in a production node config. "v1_broken" is the
    # preserved untrained head, for starling_eval.reid_benchmark only.
    backend: str = "osnet"
    weights_path: str | None = None


class MatchConfig(BaseModel):
    sim_threshold: float = 0.60
    margin_threshold: float = 0.10
    lost_threshold_s: float = 120.0
    ema_alpha: float = 0.10
    # Deliberately not a real value yet — Prompt 2 (WP-01) replaces this
    # with a threshold chosen from a plotted ROC curve. Until then the
    # config says out loud that 0.60 above was a guess, not a measurement.
    threshold_source: str = "UNCALIBRATED-GUESS"


class NetConfig(BaseModel):
    listen_port: int = 5555
    neighbours: list[str] = Field(default_factory=list)  # "host:port"
    gossip_interval_s: float = 2.0


class NodeConfig(BaseModel):
    node_id: int
    name: str
    source: str
    is_chokepoint: bool = False
    db_path: str
    calib_path: str | None = None
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    match: MatchConfig = Field(default_factory=MatchConfig)
    net: NetConfig = Field(default_factory=NetConfig)

    @staticmethod
    def write_template(path: Path, node_id: int) -> None:
        """Write a fully commented default YAML config for one node."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        template = f"""\
# Starling node config — node-{node_id:02d}
# Every threshold below has a documented default in
# packages/starling_node/config.py. Edit here, not in code.

node_id: {node_id}
name: "node-{node_id:02d}"

# Video source: file path, RTSP URL, or webcam index (as a string)
source: "data/videos/cam{node_id}.mp4"

# Set true only for a node whose FOV covers a chokepoint (WP-12: face
# recognition runs there and nowhere else).
is_chokepoint: false

# Per-node SQLite replica. Never shared with another node (CLAUDE.md rule 1).
db_path: "data/nodes/node-{node_id:02d}/local.db"

# Path to this camera's intrinsics/extrinsics YAML (WP-05). Null until
# calibration is done.
calib_path: null

perception:
  yolo_model: "yolov8n.pt"   # YOLOv8 variant: n/s/m/l/x.pt
  conf: 0.35                 # detection confidence threshold
  embed_dim: 512             # ReID embedding dimensionality
  batch_size: 8              # embedding extraction batch size
  device: "auto"             # auto | cuda | cpu
  save_crops: false          # D-14: off by default, privacy + disk usage
  crop_interval_s: 10.0      # min seconds between saved crops per identity
  backend: "osnet"           # osnet (falls back to pooled) | pooled | v1_broken
  weights_path: null         # Market-1501-trained OSNet weights (D-01 fix)

match:
  sim_threshold: 0.60        # cosine similarity cutoff for identity match
  margin_threshold: 0.10     # required separation over the second-best match
  lost_threshold_s: 120.0    # seconds absent before a person is marked LOST
  ema_alpha: 0.10            # embedding running-average blend weight
  # "UNCALIBRATED-GUESS" until Prompt 2 (WP-01) picks sim_threshold from a
  # plotted ROC curve. Do not treat 0.60 above as measured until this changes.
  threshold_source: "UNCALIBRATED-GUESS"

net:
  listen_port: {5555 + node_id}          # this node's gossip PUB port
  neighbours: []               # "host:port" list — configured, never full-mesh
  gossip_interval_s: 2.0       # anti-entropy gossip round interval
"""
        path.write_text(template, encoding="utf-8")


def load_node_config(path: Path) -> NodeConfig:
    """Load and validate a NodeConfig from a YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return NodeConfig.model_validate(data)
