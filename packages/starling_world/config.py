"""starling_world/config.py
----------------------------
Pydantic models for configs/world/warehouse.yaml — the single source of
truth for the virtual warehouse (see that file's header). Every number the
world simulation, the renderer and the calibration generator use comes
from here (CLAUDE.md: no magic numbers in logic).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class CompanyConfig(BaseModel):
    name: str = "Kestrel Logistics"
    site: str = "Fulfilment Centre"
    shift_name: str = "Shift"
    shift_start_clock: str = "07:00"


class BuildingConfig(BaseModel):
    width_m: float = 30.0
    depth_m: float = 20.0
    wall_height_m: float = 7.5


class GateConfig(BaseModel):
    node_id: int = 0
    x: float
    y: float
    radius_m: float = 1.5


class EntranceConfig(BaseModel):
    door_y: float
    door_width_m: float = 2.2
    outside_spawn: tuple[float, float]
    gate: GateConfig


class BoxSpec(BaseModel):
    """An axis-aligned floor footprint with a height."""

    x0: float
    y0: float
    x1: float
    y1: float
    height_m: float

    def polygon(self) -> list[tuple[float, float]]:
        return [(self.x0, self.y0), (self.x1, self.y0), (self.x1, self.y1), (self.x0, self.y1)]


class RackConfig(BoxSpec):
    name: str = "Rack"
    levels: int = 3


class PropConfig(BoxSpec):
    kind: str = "pallet"


class DockDoorConfig(BaseModel):
    y: float
    width_m: float = 3.0
    container: str = "#8c2f2f"


class CameraConfig(BaseModel):
    node_id: int
    name: str
    mount: tuple[float, float, float]  # floor x, floor y, height z
    look_at: tuple[float, float, float]
    hfov_deg: float = 100.0


class CameraFramesConfig(BaseModel):
    width_px: int = 1280
    height_px: int = 720
    fps: float = 5.0
    jpeg_quality: float = 0.86
    min_person_px: float = 56.0
    max_depression_deg: float = 90.0
    person_height_m: float = 1.75


class AreaConfig(BaseModel):
    name: str
    x0: float
    y0: float
    x1: float
    y1: float

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


class RoutineStep(BaseModel):
    go: str  # a POI name
    act: Optional[str] = None  # pick | work | scan | idle, performed on arrival
    dur: tuple[float, float] = (0.0, 0.0)
    carry: bool = False  # carrying a tote while walking to `go`


class LookConfig(BaseModel):
    height_m: float = 1.75
    build: str = "male"
    skin: str = "#c68642"
    hair: str = "#151010"
    hair_style: str = "short"
    shirt: str = "#3b5b92"
    vest: Optional[str] = None
    trousers: str = "#222222"
    shoes: str = "#1a1a1a"
    hat: Optional[str] = None


class PersonConfig(BaseModel):
    """Anyone who can walk around the world: an employee or a visitor."""

    id: str
    name: str
    role: str
    look: LookConfig = Field(default_factory=LookConfig)
    routine: list[RoutineStep] = Field(default_factory=list)


class EmployeeConfig(PersonConfig):
    arrive_at_s: float = 0.0


class VisitorConfig(PersonConfig):
    """Someone who is NOT an employee (an intruder, an unregistered
    visitor). Never enrolled, never verified at the gate, and only ever
    sent in on demand by the operator (no arrival time). They walk their
    routine once, then leave through the door they came in by."""

    # "staff": through the staff door, straight past the gate without
    # stopping (a tailgater). "dock:N": through dock door N (index into
    # `dock_doors`) from outside the east wall.
    entry: str = "staff"

    @field_validator("entry")
    @classmethod
    def _check_entry(cls, v: str) -> str:
        if v == "staff":
            return v
        kind, _, idx = v.partition(":")
        if kind != "dock" or not idx.isdigit():
            raise ValueError(f"visitor entry must be 'staff' or 'dock:N', got {v!r}")
        return v

    @property
    def dock_index(self) -> Optional[int]:
        """The dock door index for a "dock:N" entry, else None."""
        if self.entry.startswith("dock:"):
            return int(self.entry.split(":", 1)[1])
        return None


class AgvConfig(BaseModel):
    id: str
    colour: str = "#f2b705"
    stops: list[tuple[float, float]]
    speed_m_s: float = 1.3
    dwell_s: float = 7.0
    start_offset_s: float = 0.0


class AgvSafetyConfig(BaseModel):
    stop_distance_m: float = 2.2
    stop_half_angle_deg: float = 55.0


class WalkConfig(BaseModel):
    speed_m_s: tuple[float, float] = (1.05, 1.3)
    gate_dwell_s: float = 2.5
    break_outside_s: float = 45.0
    # A dock-door visitor appears this far outside the east wall (in front
    # of the container backed up to the door) and steps this far inside it
    # before planning a path across the floor.
    dock_outside_m: float = 1.5
    dock_inside_m: float = 0.7


class SimConfig(BaseModel):
    tick_hz: float = 20.0
    speed: float = 1.0
    seed: int = 7


class EndpointsConfig(BaseModel):
    http_host: str = "127.0.0.1"
    http_port: int = 8770
    frames_bind: str = "tcp://127.0.0.1:5570"


class WorldConfig(BaseModel):
    company: CompanyConfig = Field(default_factory=CompanyConfig)
    building: BuildingConfig = Field(default_factory=BuildingConfig)
    floorplan_path: str = "data/floorplan/warehouse_world.geojson"
    navmesh_cell_m: float = 0.25
    entrance: EntranceConfig
    racks: list[RackConfig] = Field(default_factory=list)
    props: list[PropConfig] = Field(default_factory=list)
    dock_doors: list[DockDoorConfig] = Field(default_factory=list)
    cameras: list[CameraConfig] = Field(default_factory=list)
    camera_frames: CameraFramesConfig = Field(default_factory=CameraFramesConfig)
    areas: list[AreaConfig] = Field(default_factory=list)
    pois: dict[str, tuple[float, float]] = Field(default_factory=dict)
    employees: list[EmployeeConfig] = Field(default_factory=list)
    # Not employees: never enrolled (scripts/enroll_employees.py reads only
    # `employees`), only sent into the building on the operator's demand.
    visitors: list[VisitorConfig] = Field(default_factory=list)
    agvs: list[AgvConfig] = Field(default_factory=list)
    agv_safety: AgvSafetyConfig = Field(default_factory=AgvSafetyConfig)
    walk: WalkConfig = Field(default_factory=WalkConfig)
    sim: SimConfig = Field(default_factory=SimConfig)
    endpoints: EndpointsConfig = Field(default_factory=EndpointsConfig)

    def camera(self, node_id: int) -> CameraConfig:
        for cam in self.cameras:
            if cam.node_id == node_id:
                return cam
        raise KeyError(f"no camera for node {node_id}")

    def employee(self, employee_id: str) -> EmployeeConfig:
        for emp in self.employees:
            if emp.id == employee_id:
                return emp
        raise KeyError(employee_id)

    def visitor(self, visitor_id: str) -> VisitorConfig:
        for vis in self.visitors:
            if vis.id == visitor_id:
                return vis
        raise KeyError(visitor_id)

    @model_validator(mode="after")
    def _check_people(self) -> "WorldConfig":
        ids = [p.id for p in self.employees] + [p.id for p in self.visitors]
        if len(ids) != len(set(ids)):
            raise ValueError("employee and visitor ids must all be distinct")
        for vis in self.visitors:
            k = vis.dock_index
            if k is not None and not 0 <= k < len(self.dock_doors):
                raise ValueError(f"visitor {vis.id}: no dock door {k}")
        return self


def load_world_config(path: Union[str, Path]) -> WorldConfig:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return WorldConfig.model_validate(data)
