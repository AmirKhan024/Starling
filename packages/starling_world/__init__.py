"""starling_world — the live 3D virtual warehouse that stands in for the
physical building, its four employees and its four cameras.

Special status (the same as `starling_sim`'s): the world is physical
reality, so it knows ground truth. What it hands a node is exactly what a
real camera would: JPEG frames rendered from that node's own camera pose,
on that node's own topic, and nothing else — no positions, no identities,
no embeddings. Everything a node knows about a person it has to work out
from pixels (person detector, tracker, appearance signature, floor
homography), exactly as on the video path.

Modules:
  config    — Pydantic models for configs/world/warehouse.yaml
  layout    — obstacles, floor polygon, camera zones, GeoJSON export
  camera    — the pinhole camera model shared by the renderer and calibration
  pathing   — A* over the navmesh grid, with line-of-sight smoothing
  sim       — workers (routines, gate, breaks), AGVs, camera obstructions
  frames    — the per-camera JPEG frame topic (world server -> one node)
"""
