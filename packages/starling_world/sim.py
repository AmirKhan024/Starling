"""starling_world/sim.py
------------------------
The virtual warehouse's ground truth, advanced one media-time tick at a
time: four employees living their shift (arrive outside, walk in through
the staff door, stop at the gate, then work their routine on navmesh
paths; optionally go on a break and come back), an unknown person the
operator can send in (through a dock door, or tailgating through the
staff door — never stopping at the gate), two driverless AGVs that stop
for people, and the physical faults an operator can inject (a tarp over
a camera lens).

Nothing here knows about Starling's nodes. The world server turns
`snapshot()` into rendered camera frames; what a node learns, it learns
from those pixels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from starling_geometry.navmesh import NavMesh

from starling_world.config import (
    AgvConfig,
    EmployeeConfig,
    PersonConfig,
    VisitorConfig,
    WorldConfig,
)
from starling_world.pathing import PathPlanner

_TURN_RATE_RAD_S = 7.0
_DOOR_INSIDE_X = 0.7
_DOOR_OUTSIDE_X = -0.6


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _lower_first(name: str) -> str:
    return name[:1].lower() + name[1:]


def _a(name: str) -> str:
    """'Unknown person' -> 'An unknown person' (event wording)."""
    art = "An" if name[:1].lower() in "aeiou" else "A"
    return f"{art} {_lower_first(name)}"


@dataclass
class _Mover:
    x: float
    y: float
    heading: float = 0.0  # radians, 0 = facing +y (south), measured towards +x
    path: list[tuple[float, float]] = field(default_factory=list)
    speed_now: float = 0.0

    def set_path(self, pts: list[tuple[float, float]]) -> None:
        self.path = [p for p in pts]
        if self.path and math.hypot(self.path[0][0] - self.x, self.path[0][1] - self.y) < 1e-6:
            self.path.pop(0)

    def advance(self, dt: float, speed: float) -> bool:
        """Walk along the path; True once it is used up."""
        remaining = speed * dt
        self.speed_now = 0.0
        while remaining > 1e-9 and self.path:
            tx, ty = self.path[0]
            dx, dy = tx - self.x, ty - self.y
            d = math.hypot(dx, dy)
            if d < 1e-6:
                self.path.pop(0)
                continue
            desired = math.atan2(dx, dy)
            diff = _wrap(desired - self.heading)
            max_turn = _TURN_RATE_RAD_S * dt
            self.heading = _wrap(self.heading + max(-max_turn, min(max_turn, diff)))
            step = min(d, remaining)
            self.x += dx / d * step
            self.y += dy / d * step
            remaining -= step
            self.speed_now = speed
            if step >= d - 1e-9:
                self.path.pop(0)
        return not self.path


class WorkerSim:
    """One employee's day: a small state machine.

    offsite -> arriving (outside, then through the door) -> at_gate (badge
    tap, `gate_dwell_s`) -> working (routine steps, forever) -> leaving
    (only on a break request) -> offsite (until `return_at`) -> arriving ...
    """

    visitor = False

    def __init__(
        self, idx: int, emp: PersonConfig, world: "WorldSim", rng: np.random.Generator
    ) -> None:
        self.idx = idx
        self.emp = emp
        self.world = world
        self.rng = rng
        lo, hi = world.cfg.walk.speed_m_s
        self.speed = float(rng.uniform(lo, hi))
        sx, sy = world.cfg.entrance.outside_spawn
        self.m = _Mover(sx, sy, heading=math.pi / 2)
        self.state = "offsite"
        self.action = "idle"
        self.action_left = 0.0
        self.carry = False
        self.step_i = 0
        self.arrive_at: Optional[float] = (
            float(emp.arrive_at_s) if isinstance(emp, EmployeeConfig) else None
        )
        self.break_requested = False
        self.entries = 0
        self.last_entry_t: Optional[float] = None

    # -- helpers ------------------------------------------------------------

    @property
    def inside(self) -> bool:
        return self.state != "offsite" and self.m.x > 0.0

    def _door_y(self) -> float:
        return self.world.cfg.entrance.door_y

    def _plan(self, goal: tuple[float, float]) -> list[tuple[float, float]]:
        return self.world.planner.plan((self.m.x, self.m.y), goal)

    def _start_step(self) -> None:
        routine = self.emp.routine
        if not routine:
            self.action, self.action_left = "idle", 1e9
            return
        step = routine[self.step_i % len(routine)]
        goal = self.world.cfg.pois[step.go]
        self.carry = step.carry
        self.action = "walk"
        self.m.set_path(self._plan(tuple(goal)))

    def _arrive(self) -> None:
        sx, sy = self.world.cfg.entrance.outside_spawn
        dy = self._door_y()
        self.m.x, self.m.y = sx, sy
        self.m.heading = math.pi / 2
        gate = (self.world.cfg.entrance.gate.x, self.world.cfg.entrance.gate.y)
        inside_part = self.world.planner.plan((_DOOR_INSIDE_X, dy), gate)
        self.m.set_path([(_DOOR_OUTSIDE_X, dy), (_DOOR_INSIDE_X, dy)] + inside_part[1:])
        self.state, self.action, self.carry = "arriving", "walk", False
        self.entries += 1
        self.last_entry_t = self.world.t

    def _leave(self) -> None:
        dy = self._door_y()
        sx, sy = self.world.cfg.entrance.outside_spawn
        to_door = self._plan((_DOOR_INSIDE_X, dy))
        self.m.set_path(to_door + [(_DOOR_OUTSIDE_X, dy), (sx, sy)])
        self.state, self.action, self.carry = "leaving", "walk", False
        self.break_requested = False

    # -- tick -----------------------------------------------------------------

    def tick(self, dt: float) -> None:
        t = self.world.t
        if self.state == "offsite":
            self.m.speed_now = 0.0
            if self.arrive_at is not None and t >= self.arrive_at:
                self.arrive_at = None
                self._arrive()
            return

        if self.state in ("arriving", "leaving"):
            done = self.m.advance(dt, self.speed)
            if done:
                if self.state == "arriving":
                    self.state, self.action = "at_gate", "scan"
                    self.action_left = self.world.cfg.walk.gate_dwell_s
                    self.m.heading = math.pi / 2  # face into the building
                else:
                    self.state, self.action = "offsite", "idle"
                    self.arrive_at = t + self.world.cfg.walk.break_outside_s
            return

        if self.state == "at_gate":
            self.m.speed_now = 0.0
            self.action_left -= dt
            if self.action_left <= 0:
                self.state = "working"
                self._start_step()
            return

        # working
        if self.action == "walk":
            if self.m.advance(dt, self.speed * (0.92 if self.carry else 1.0)):
                step = (
                    self.emp.routine[self.step_i % len(self.emp.routine)]
                    if self.emp.routine
                    else None
                )
                if step is not None and step.act:
                    self.action = step.act
                    lo, hi = step.dur
                    self.action_left = float(self.rng.uniform(lo, hi)) if hi > 0 else 0.0
                    self.m.speed_now = 0.0
                else:
                    self._next_step()
        else:
            self.m.speed_now = 0.0
            self.action_left -= dt
            if self.action_left <= 0:
                self._next_step()

    def _next_step(self) -> None:
        if self.break_requested:
            self._leave()
            return
        self.step_i += 1
        self._start_step()

    def request_break(self) -> bool:
        if self.state != "working":
            return False
        self.break_requested = True
        if self.action != "walk":
            self._leave()
        return True

    def snapshot(self) -> dict[str, Any]:
        e = self.emp
        snap: dict[str, Any] = {
            "id": e.id,
            "idx": self.idx,
            "name": e.name,
            "x": round(self.m.x, 3),
            "y": round(self.m.y, 3),
            "heading": round(self.m.heading, 3),
            "speed": round(self.m.speed_now, 3),
            "action": self.action,
            "carry": self.carry,
            "state": self.state,
            "inside": self.inside,
            "present": self.state != "offsite",
        }
        if self.visitor:
            snap["visitor"] = True
        return snap


class VisitorSim(WorkerSim):
    """Someone who is not an employee, sent in on the operator's demand.

    offsite -> arriving (outside, then through the entry door; NO gate
    stop) -> working (the routine, once) -> leaving (back out through the
    entry door) -> offsite, for good (until sent again).
    """

    visitor = True

    def __init__(
        self, idx: int, vis: VisitorConfig, world: "WorldSim", rng: np.random.Generator
    ) -> None:
        super().__init__(idx, vis, world, rng)
        self.vis = vis
        self.arrive_at = None  # only ever sent in on demand
        self.m.x, self.m.y = self._outside()

    @property
    def inside(self) -> bool:
        return self.state != "offsite" and 0.0 < self.m.x < self.world.cfg.building.width_m

    def _dock_y(self) -> float:
        k = self.vis.dock_index
        assert k is not None
        return self.world.cfg.dock_doors[k].y

    def _outside(self) -> tuple[float, float]:
        """Where the visitor first appears and finally disappears (outside)."""
        if self.vis.dock_index is None:
            sx, sy = self.world.cfg.entrance.outside_spawn
            return float(sx), float(sy)
        return self.world.cfg.building.width_m + self.world.cfg.walk.dock_outside_m, self._dock_y()

    def _door_path_in(self) -> list[tuple[float, float]]:
        """Waypoints from outside to just inside the entry door."""
        if self.vis.dock_index is None:
            dy = self._door_y()
            return [(_DOOR_OUTSIDE_X, dy), (_DOOR_INSIDE_X, dy)]
        x_in = self.world.cfg.building.width_m - self.world.cfg.walk.dock_inside_m
        return [(x_in, self._dock_y())]

    def _arrive(self) -> None:
        self.m.x, self.m.y = self._outside()
        # face into the building: east from the staff door, west from a dock
        self.m.heading = math.pi / 2 if self.vis.dock_index is None else -math.pi / 2
        self.m.set_path(self._door_path_in())
        self.state, self.action, self.carry = "arriving", "walk", False
        self.step_i = 0
        self.entries += 1
        self.last_entry_t = self.world.t

    def _leave(self) -> None:
        door_in = self._door_path_in()
        to_door = self._plan(door_in[-1])
        out = list(reversed(door_in[:-1])) + [self._outside()]
        self.m.set_path(to_door + out)
        self.state, self.action, self.carry = "leaving", "walk", False
        self.break_requested = False

    def send(self) -> bool:
        """Walk in now. False if already on site."""
        if self.state != "offsite":
            return False
        self._arrive()
        return True

    def tick(self, dt: float) -> None:
        if self.state == "arriving":
            if self.m.advance(dt, self.speed):
                # straight on to the route: a visitor never stops at the gate
                self.state = "working"
                self._start_step()
            return
        if self.state == "leaving":
            if self.m.advance(dt, self.speed):
                self.state, self.action = "offsite", "idle"
                self.arrive_at = None  # gone for good (unless sent again)
            return
        super().tick(dt)

    def _next_step(self) -> None:
        self.step_i += 1
        if self.step_i >= len(self.emp.routine):
            self._leave()  # the route is walked once, then out
            return
        self._start_step()

    def request_break(self) -> bool:
        return False


class AgvSim:
    def __init__(self, cfg: AgvConfig, world: "WorldSim") -> None:
        self.cfg = cfg
        self.world = world
        (x0, y0), (x1, y1) = cfg.stops[0], cfg.stops[1]
        self.m = _Mover(x0, y0, heading=math.atan2(x1 - x0, y1 - y0))
        self.target = 1
        self.dwell_left = float(cfg.start_offset_s)
        self.safety_stop = False

    def _blocked(self) -> bool:
        s = self.world.cfg.agv_safety
        half = math.radians(s.stop_half_angle_deg)
        for w in self.world.workers:
            if not w.inside:
                continue
            dx, dy = w.m.x - self.m.x, w.m.y - self.m.y
            d = math.hypot(dx, dy)
            if d < 0.01:
                return True
            if d <= s.stop_distance_m and abs(_wrap(math.atan2(dx, dy) - self.m.heading)) <= half:
                return True
        return False

    def tick(self, dt: float) -> None:
        if self.dwell_left > 0:
            self.dwell_left -= dt
            self.m.speed_now = 0.0
            tx, ty = self.cfg.stops[self.target]
            want = math.atan2(tx - self.m.x, ty - self.m.y)
            diff = _wrap(want - self.m.heading)
            self.m.heading = _wrap(self.m.heading + max(-0.8 * dt, min(0.8 * dt, diff)))
            return
        self.safety_stop = self._blocked()
        if self.safety_stop:
            self.m.speed_now = 0.0
            return
        if not self.m.path:
            self.m.set_path([tuple(self.cfg.stops[self.target])])
        if self.m.advance(dt, self.cfg.speed_m_s):
            self.target = 1 - self.target
            self.dwell_left = self.cfg.dwell_s

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.cfg.id,
            "x": round(self.m.x, 3),
            "y": round(self.m.y, 3),
            "heading": round(self.m.heading, 3),
            "speed": round(self.m.speed_now, 3),
            "safety_stop": self.safety_stop,
            "colour": self.cfg.colour,
        }


class WorldSim:
    def __init__(self, cfg: WorldConfig, navmesh: NavMesh) -> None:
        self.cfg = cfg
        self.navmesh = navmesh
        self.planner = PathPlanner(navmesh)
        self.t = 0.0
        self.tick_count = 0
        rng = np.random.default_rng(cfg.sim.seed)
        self.workers: list[WorkerSim] = [
            WorkerSim(i, e, self, np.random.default_rng(cfg.sim.seed * 101 + i))
            for i, e in enumerate(cfg.employees)
        ]
        # Visitors live alongside the employees (so AGVs stop for them and
        # ground truth lists them), their indices continuing after them.
        n = len(self.workers)
        self.workers += [
            VisitorSim(n + i, v, self, np.random.default_rng(cfg.sim.seed * 101 + n + i))
            for i, v in enumerate(cfg.visitors)
        ]
        self.agvs = [AgvSim(a, self) for a in cfg.agvs]
        self._rng = rng
        # camera node_id -> media time the lens obstruction ends (inf = until cleared)
        self.blocked_until: dict[int, float] = {}
        self.events: list[dict[str, Any]] = []

    # -- operator actions (the world server's control endpoints) -------------

    def block_camera(self, node_id: int, duration_s: Optional[float] = None) -> None:
        self.blocked_until[node_id] = math.inf if duration_s is None else self.t + duration_s
        self._event(f"Camera {node_id}: lens covered (a tarp was thrown over it)")

    def unblock_camera(self, node_id: Optional[int] = None) -> None:
        targets = list(self.blocked_until) if node_id is None else [node_id]
        for n in targets:
            if self.blocked_until.pop(n, None) is not None:
                self._event(f"Camera {n}: lens cleared")

    def request_break(self, employee_id: str) -> bool:
        for w in self.workers:
            if w.emp.id == employee_id and not w.visitor:
                ok = w.request_break()
                if ok:
                    self._event(f"{w.emp.name} is going on a break (leaving the building)")
                return ok
        return False

    def visitors(self) -> list[VisitorSim]:
        return [w for w in self.workers if isinstance(w, VisitorSim)]

    def send_visitor(self, visitor_id: Optional[str] = None) -> bool:
        """Send a visitor (default: the first configured one) into the
        building. False if there is no such visitor or they are on site."""
        v = next((x for x in self.visitors() if visitor_id is None or x.emp.id == visitor_id), None)
        if v is None or not v.send():
            return False
        k = v.vis.dock_index
        where = (
            "slips in through the staff door behind someone, without stopping at the gate"
            if k is None
            else f"enters through dock door {k + 1}"
        )
        self._event(f"{_a(v.emp.name)} {where}")
        return True

    def blocked_cameras(self) -> list[int]:
        return sorted(n for n, until in self.blocked_until.items() if self.t < until)

    def _event(self, text: str) -> None:
        self.events.append({"t": round(self.t, 1), "text": text})
        self.events = self.events[-50:]

    # -- tick ---------------------------------------------------------------------

    def tick(self, dt: float) -> None:
        self.t += dt
        self.tick_count += 1
        for n, until in list(self.blocked_until.items()):
            if self.t >= until:
                self.blocked_until.pop(n)
        for w in self.workers:
            before = w.state
            w.tick(dt)
            if before != w.state:
                if w.visitor:
                    if w.state == "offsite":
                        self._event(f"The {_lower_first(w.emp.name)} has left the building")
                elif w.state == "arriving":
                    self._event(f"{w.emp.name} arrives at the staff entrance")
                elif w.state == "offsite":
                    self._event(f"{w.emp.name} has left the building")
        for a in self.agvs:
            a.tick(dt)

    def snapshot(self) -> dict[str, Any]:
        return {
            "t": round(self.t, 3),
            "workers": [w.snapshot() for w in self.workers],
            "agvs": [a.snapshot() for a in self.agvs],
            "blocked_cameras": self.blocked_cameras(),
        }

    def ground_truth(self) -> dict[str, Any]:
        """The dashboard's ground-truth topic message (same shape the 2D
        simulator publishes — starling_sim.runner — plus employee ids).
        Only people inside the building are listed: outside, no camera
        could ever see them."""
        return {
            "type": "ground_truth",
            "tick": self.tick_count,
            "t_media": self.t,
            "workers": [
                {
                    "worker_id": w.idx,
                    "employee_id": w.emp.id,
                    "name": w.emp.name,
                    "x": w.m.x,
                    "y": w.m.y,
                    "state": w.state,
                    **({"visitor": True} if w.visitor else {}),
                }
                for w in self.workers
                if w.inside
            ],
            "occluded_nodes": self.blocked_cameras(),
        }
