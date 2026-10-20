"""apps/demo_dashboard/world_view.py
------------------------------------
The live-3D-world half of the dashboard: turns the resolver's output (what
the dashboard overheard on gossip, resolved by the same pure function every
node runs) into what a warehouse manager asks — who is on site, verified,
where, and what needs attention.

Where its knowledge comes from:
  * an employee's NAME comes from the identity's label, and the label is an
    employee id only because a camera node made a signed FACE_ANCHOR claim
    for that id at the entrance gate (gossiped like any other claim). The
    employee list itself (names, roles, colours) is static site data from
    configs/world/warehouse.yaml, like the floor plan.
  * the simulator's ground truth is used for ONE thing: the technical view's
    "error vs truth" metric. Nothing a manager sees is derived from it.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Optional

from shapely.geometry import Point, shape
from shapely.prepared import prep
from starling_world.config import load_world_config

from apps.demo_dashboard.config import DemoDashboardConfig


def camera_position(camera_name: str) -> str:
    """'North-west · Entrance' -> 'north-west'."""
    return camera_name.split("·")[0].strip().lower() if "·" in camera_name else camera_name


def area_name(camera_name: str) -> str:
    """'North-west · Entrance' -> 'Entrance'."""
    return camera_name.split("·")[-1].strip() if "·" in camera_name else camera_name


class WorldView:
    def __init__(self, cfg: DemoDashboardConfig, floorplan: dict) -> None:
        self.cfg = cfg
        self.world = load_world_config(Path(cfg.world_config_path))
        self.employees = {e.id: e for e in self.world.employees}
        self.camera_names = {c.node_id: c.name for c in self.world.cameras}
        self._zones = []
        blind = []
        for f in floorplan["features"]:
            p = f.get("properties") or {}
            if p.get("role") == "camera_zone":
                self._zones.append((int(p["node_id"]), prep(shape(f["geometry"]))))
            elif p.get("role") == "blind":
                blind.append(prep(shape(f["geometry"])))
        self._blind = blind
        e = self.world.entrance
        self.door_inside = (0.0, e.door_y)  # where the staff door meets the floor
        self.gate = (e.gate.x, e.gate.y)
        self.state: dict[str, dict[str, Any]] = {}
        self.verifications: list[dict[str, Any]] = []  # gate check-ins
        self.recognitions: list[dict[str, Any]] = []  # re-recognitions elsewhere
        self._seen_anchor_ids: set[str] = set()
        self._unknown_numbers: dict[str, int] = {}
        # number -> (x, y, media t) where that unknown person was last listed
        self._unknown_last: dict[int, tuple[float, float, float]] = {}

    def site(self) -> dict[str, Any]:
        """Static site data the pages draw (no live state)."""
        w = self.world
        return {
            "company": w.company.model_dump(),
            "building": w.building.model_dump(),
            "entrance": w.entrance.model_dump(),
            "dock_doors": [d.model_dump() for d in w.dock_doors],
            "racks": [r.model_dump() for r in w.racks],
            "areas": [a.model_dump() for a in w.areas],
            "cameras": [
                {
                    "node_id": c.node_id,
                    "name": c.name,
                    "area": area_name(c.name),
                    "mount": list(c.mount),
                }
                for c in w.cameras
            ],
            "employees": [
                {"id": e.id, "name": e.name, "role": e.role, "colour": e.look.vest or e.look.shirt}
                for e in w.employees
            ],
        }

    # ── geography ────────────────────────────────────────────────────────

    def where(self, x: float, y: float) -> dict[str, Any]:
        """The named floor area (configs/world/warehouse.yaml `areas`) and the
        camera zone a point lies in."""
        p = Point(x, y)
        node = next((n for n, z in self._zones if z.contains(p)), None)
        area = next((a.name for a in self.world.areas if a.contains(x, y)), None)
        if area is None:
            area = "Blind corner" if any(b.contains(p) for b in self._blind) else "Warehouse floor"
        return {"area": area, "node": node}

    def is_employee(self, label: str) -> bool:
        return label in self.employees

    def employee_name(self, label: str) -> Optional[str]:
        e = self.employees.get(label)
        return e.name if e else None

    def resolve_person(self, text: str) -> Optional[str]:
        """'where is priya' / 'EMP-1041' / 'marcus bell' -> employee id."""
        t = text.lower()
        for e in self.world.employees:
            if e.id.lower() in t:
                return e.id
        for e in self.world.employees:
            parts = e.name.lower().split()
            if e.name.lower() in t or any(
                len(p) > 2 and p in re.findall(r"[a-z0-9-]+", t) for p in parts
            ):
                return e.id
        return None

    def clock(self, t_media: float) -> str:
        h, m = (int(v) for v in self.world.company.shift_start_clock.split(":"))
        s = int(h * 3600 + m * 60 + max(0.0, t_media))
        return f"{(s // 3600) % 24:02d}:{(s // 60) % 60:02d}:{s % 60:02d}"

    # ── per compute ──────────────────────────────────────────────────────

    def ingest_anchors(self, records: list[dict[str, Any]]) -> None:
        """Every FACE_ANCHOR claim overheard on gossip. One made by the gate
        camera at the gate is a CHECK-IN (the formal verification); any
        other is a re-recognition by a camera elsewhere (kept for the
        technical view)."""
        g = self.world.entrance.gate
        for r in records:
            if r.get("anchor_type") != "FACE_ANCHOR" or r["claim_id"] in self._seen_anchor_ids:
                continue
            emp = r.get("identity_ref")
            if emp not in self.employees:
                continue
            self._seen_anchor_ids.add(r["claim_id"])
            at_gate = (
                r["node_id"] == g.node_id
                and r.get("world_x") is not None
                and math.hypot(r["world_x"] - g.x, r["world_y"] - g.y)
                <= g.radius_m + self.cfg.gate_match_slack_m
            )
            v = {
                "employee_id": emp,
                "name": self.employees[emp].name,
                "t_media": round(r["t_media"], 1),
                "clock": self.clock(r["t_media"]),
                "node": r["node_id"],
                "kind": "check-in" if at_gate else "recognised",
                "camera": self.camera_names.get(r["node_id"], f"Camera {r['node_id']}"),
            }
            st = self.state.setdefault(emp, {})
            if at_gate:
                self.verifications.append(v)
                st.setdefault("first_verified", v)
                st["last_verified"] = v
            else:
                st["last_recognised"] = v
                self.recognitions.append(v)
        self.verifications = self.verifications[-40:]
        self.recognitions = self.recognitions[-60:]

    def compute(
        self,
        identities: list[dict],
        regions: list[dict],
        nodes: list[dict],
        gt: Optional[dict],
        now_t: float,
        cut_groups: Optional[list[list[int]]],
        gt_at: Any = None,
    ) -> dict[str, Any]:
        cfg = self.cfg
        regions_by_id = {r["id"]: r for r in regions}
        by_emp = {}
        for ident in identities:
            if ident["id"] in self.employees:
                by_emp[ident["id"]] = ident

        people = []
        for e in self.world.employees:
            st = self.state.setdefault(e.id, {})
            ident = by_emp.get(e.id)
            if ident is not None and ident["status"] == "seen":
                st.update(
                    last_seen_t=ident["t_media"],
                    last_pos=(ident["x"], ident["y"]),
                    last_node=ident["node"],
                )
            item: dict[str, Any] = {
                "id": e.id,
                "name": e.name,
                "role": e.role,
                "colour": e.look.vest or e.look.shirt,
                "hat": e.look.hat,
                "verified": st.get("first_verified"),
                "last_verified": st.get("last_verified"),
                "last_recognised": st.get("last_recognised"),
            }
            last_t = st.get("last_seen_t")
            unseen_for = None if last_t is None else max(0.0, now_t - last_t)
            pos = st.get("last_pos")
            near_door = (
                pos is not None
                and math.hypot(pos[0] - self.door_inside[0], pos[1] - self.door_inside[1])
                <= cfg.door_exit_radius_m
            )
            if ident is None and last_t is None:
                status = "not_arrived"
            elif ident is not None and ident["status"] == "forked":
                status = "conflict"
            elif ident is not None and ident["status"] == "seen":
                status = "visible"
            elif near_door and unseen_for is not None and unseen_for >= cfg.left_after_s:
                status = "left"
            elif unseen_for is not None and unseen_for > cfg.lost_after_s:
                status = "lost"
            elif unseen_for is not None and unseen_for < cfg.manager_unseen_grace_s:
                status = "visible"  # a blink between frames is not news for a manager
            else:
                status = "out_of_view"
            item["status"] = status
            item["unseen_for_s"] = None if unseen_for is None else round(unseen_for, 1)
            if pos is not None:
                item.update(x=round(pos[0], 2), y=round(pos[1], 2), **self.where(*pos))
                item["camera"] = (
                    None if st.get("last_node") is None else self.camera_names.get(st["last_node"])
                )
            if ident is not None:
                item["identity"] = {
                    k: ident.get(k) for k in ("n_claims", "confidence", "node", "age_s", "error_m")
                }
                reg = regions_by_id.get(e.id)
                if reg is not None:
                    # Measured against the named aisles (not every camera-less patch: a
                    # blind corner by a dock door is not "the aisles").
                    in_aisles = reg.get("aisles_area_m2")
                    if in_aisles is None:
                        in_aisles = reg["blind_block_area_m2"]
                    blind_frac = min(1.0, in_aisles / reg["area_m2"]) if reg["area_m2"] > 0 else 0.0
                    item["search"] = {
                        "area_m2": reg["area_m2"],
                        "reachable_m2": reg["reachable_area_m2"],
                        "in_aisles_fraction": round(blind_frac, 2),
                        "healthy": reg["healthy_nodes"],
                        "silent": reg["silent_nodes"],
                    }
            if gt_at is not None and pos is not None and status == "visible" and last_t is not None:
                g = gt_at(last_t).get(e.id)
                if g is not None:
                    item["truth_error_m"] = round(math.hypot(g[0] - pos[0], g[1] - pos[1]), 2)
            item["summary"] = self._summary(item)
            people.append(item)

        unverified = []
        self._listed_now: set[str] = set()
        untrusted = {
            n["id"] for n in nodes
            if n.get("reputation") is not None and n["reputation"] < cfg.lying_reputation_alert
        }
        named_now = [
            (ident["x"], ident["y"], ident["t_media"])
            for ident in identities
            if ident["id"] in self.employees
        ]
        for i in identities:
            if i["id"] in self.employees or (i["status"] != "seen" and i["age_s"] > cfg.unknown_keep_s):
                continue
            reg = regions_by_id.get(i["id"])
            if i["status"] != "seen" and (reg is None or reg["area_m2"] < cfg.unknown_min_region_m2):
                # Every place it could be is attested empty (or it was never located): a stale
                # duplicate fragment, or a stranger who has left through an unwatched door.
                continue
            # A stranger already on the list stays on it while their track lives — even
            # standing next to an employee at work. The filters below are for NEW tracks.
            if i.get("cameras") and set(i["cameras"]) <= untrusted:
                continue  # only an untrusted (contradicted) camera reports this "person"
            if i["id"] not in self._unknown_numbers:
                reforming = self._inherit_candidate(i, cfg) is not None
                min_claims = cfg.unknown_reform_min_claims if reforming else cfg.unverified_min_claims
                if i["n_claims"] < min_claims or i["status"] != "seen":
                    continue
                if any(
                    math.hypot(x - i["x"], y - i["y"]) <= cfg.unknown_split_radius_m
                    and abs(t - i["t_media"]) <= cfg.unknown_split_window_s
                    for x, y, t in named_now
                ):
                    continue  # the same body as a named employee at the same moment: a split track
                if math.hypot(i["x"] - self.gate[0], i["y"] - self.gate[1]) <= cfg.gate_approach_radius_m:
                    continue  # at the entrance gate: about to be verified, not a stranger (yet)
            num = self._unknown_number(i, cfg)
            unverified.append({
                "id": i["id"],
                "label": f"Unknown #{num}",
                "x": i["x"],
                "y": i["y"],
                **self.where(i["x"], i["y"]),
                "n_claims": i["n_claims"],
                "status": "visible" if i["status"] == "seen" else "out_of_view",
                "unseen_for_s": round(i["age_s"], 1),
                "cameras": i.get("cameras", []),
                "trail": i.get("trail", []),
                "search": None if reg is None else {"area_m2": reg["area_m2"], "reachable_m2": reg["reachable_area_m2"]},
            })
        alerts = self._alerts(people, unverified, nodes, cut_groups)
        on_site = [p for p in people if p["status"] not in ("not_arrived", "left")]
        return {
            "company": self.world.company.model_dump(),
            "clock": self.clock(now_t),
            "people": people,
            "unverified": unverified,
            "alerts": alerts,
            "verifications": list(reversed(self.verifications[-12:])),
            "recognitions": list(reversed(self.recognitions[-15:])),
            "counts": {
                "employees": len(people),
                "on_site": len(on_site),
                "verified_on_site": sum(1 for p in on_site if p["verified"]),
                "visible": sum(1 for p in people if p["status"] == "visible"),
                "unverified": len(unverified),
                "out_of_view": sum(1 for p in people if p["status"] == "out_of_view"),
                "cameras_ok": sum(1 for n in nodes if n["live"] and n["coverage_healthy"]),
                "cameras": len(nodes),
            },
            "camera_names": {str(k): v for k, v in self.camera_names.items()},
        }

    def _inherit_candidate(self, ident: dict[str, Any], cfg: DemoDashboardConfig) -> Optional[int]:
        """The number of a recently-listed unknown person this new track could be
        (last listed within `unknown_inherit_s`, within walking distance), if any."""
        listed = getattr(self, "_listed_now", set())
        for n, (x, y, t) in sorted(self._unknown_last.items()):
            dt = ident["t_media"] - t
            if (
                0 <= dt <= cfg.unknown_inherit_s
                and math.hypot(ident["x"] - x, ident["y"] - y)
                <= cfg.unknown_inherit_slack_m + cfg.unknown_walk_speed_m_s * dt
                and not any(v == n and k != ident["id"] and k in listed for k, v in self._unknown_numbers.items())
            ):
                return n
        return None

    def _unknown_number(self, ident: dict[str, Any], cfg: DemoDashboardConfig) -> int:
        """A stable, human number for each unknown person ("Unknown #1"). A
        track that breaks and re-forms under a new identity, where the old one
        was last listed recently and close enough to walk from, keeps its number."""
        num = self._unknown_numbers.get(ident["id"])
        if num is None:
            taken = set(self._unknown_numbers.values())
            num = self._inherit_candidate(ident, cfg)
            if num is None:
                num = max(taken | set(self._unknown_last), default=0) + 1
            self._unknown_numbers[ident["id"]] = num
        self._listed_now.add(ident["id"])
        self._unknown_last[num] = (ident["x"], ident["y"], ident["t_media"])
        return num

    def _summary(self, p: dict[str, Any]) -> str:
        first = p["name"].split()[0]
        s = p["status"]
        if s == "not_arrived":
            return "Not on site yet"
        if s == "visible":
            return f"In {p.get('area', 'the warehouse')}" + (
                f" · seen by the {camera_position(p['camera'])} camera" if p.get("camera") else ""
            )
        if s == "left":
            return f"Left through the staff entrance {int(p['unseen_for_s'])} s ago"
        if s == "lost":
            mins, secs = int(p["unseen_for_s"] // 60), int(p["unseen_for_s"] % 60)
            return f"Not seen for {mins} min {secs} s — last in {p.get('area', '?')}"
        if s == "conflict":
            return "Conflicting sightings — needs a human check"
        search = p.get("search")
        if search and search["in_aisles_fraction"] >= 0.6:
            return (
                f"In the storage aisles (no cameras there) · {first} must still be inside: "
                f"every camera around the aisles is working and none has seen {first} come out"
            )
        if search and search["area_m2"] >= self.cfg.unknown_min_region_m2:
            near = f" near {p['area']}" if p.get("area") else ""
            return (
                f"Out of camera view{near} for {int(p['unseen_for_s'])} s · "
                f"must be within a {search['area_m2']:.0f} m² search area"
            )
        return f"Out of camera view for {int(p['unseen_for_s'] or 0)} s"

    def _alerts(
        self,
        people: list[dict],
        unverified: list[dict],
        nodes: list[dict],
        cut_groups: Optional[list[list[int]]],
    ) -> list[dict[str, Any]]:
        out = []
        for n in nodes:
            name = area_name(self.camera_names.get(n["id"], f"Camera {n['id']}"))
            if not n["live"]:
                out.append(
                    {
                        "level": "bad",
                        "kind": "camera_offline",
                        "text": f"{name} camera is offline — its area is not being watched.",
                    }
                )
            elif not n["coverage_healthy"]:
                out.append(
                    {
                        "level": "warn",
                        "kind": "camera_degraded",
                        "text": (
                            f"{name} camera cannot vouch for its area (view blocked or degraded). "
                            "Anyone there may be missed; the system will not assume the area is "
                            "empty."
                        ),
                    }
                )
            if (
                n.get("reputation") is not None
                and n["reputation"] < self.cfg.lying_reputation_alert
            ):
                out.append(
                    {
                        "level": "bad",
                        "kind": "camera_untrusted",
                        "text": (
                            f"{name} camera is reporting sightings the other cameras contradict. "
                            "Its reports are being discounted."
                        ),
                    }
                )
        if any(n["partitioned"] for n in nodes):
            groups = cut_groups or []
            names = [
                " + ".join(area_name(self.camera_names.get(i, str(i))) for i in g) for g in groups
            ]
            out.append(
                {
                    "level": "warn",
                    "kind": "network_split",
                    "text": (
                        "Network split between "
                        f"{' and '.join(names) if names else 'camera groups'}. "
                        "Each side keeps tracking on its own; the views merge automatically "
                        "when the link returns."
                    ),
                }
            )
        for p in people:
            if p["status"] == "lost":
                out.append(
                    {
                        "level": "bad",
                        "kind": "employee_lost",
                        "text": (
                            f"{p['name']} has not been seen for over "
                            f"{int(p['unseen_for_s'] // 60)} min (last seen in "
                            f"{p.get('area', '?')})."
                        ),
                    }
                )
            elif p["status"] == "conflict":
                out.append(
                    {
                        "level": "warn",
                        "kind": "employee_conflict",
                        "text": (
                            f"{p['name']} was verified in two places that cannot both be true. "
                            "A human should check."
                        ),
                    }
                )
        for u in unverified:
            cams = len(u.get("cameras", []))
            seen_by = f" Followed across {cams} cameras." if cams > 1 else ""
            out.append(
                {
                    "level": "bad",
                    "kind": "unverified_person",
                    "text": (
                        f"{u['label']}: unrecognised person in {u['area']} — not verified at the entrance.{seen_by}"
                        if u["status"] == "visible"
                        else f"{u['label']}: unrecognised person, out of camera view for {int(u['unseen_for_s'])} s "
                        f"(last in {u['area']})."
                    ),
                }
            )
        return out
