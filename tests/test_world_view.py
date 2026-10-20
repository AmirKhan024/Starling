"""The dashboard's live-world logic (apps/demo_dashboard/world_view.py):
names only from gate verification, statuses, alerts."""

from __future__ import annotations

import json
from pathlib import Path

from apps.demo_dashboard.config import load_demo_config
from apps.demo_dashboard.world_view import WorldView

REPO = Path(__file__).resolve().parents[1]


def _view() -> WorldView:
    cfg = load_demo_config(REPO / "configs" / "world" / "dashboard.yaml")
    fp = json.loads((REPO / cfg.navmesh_path).read_text(encoding="utf-8"))
    return WorldView(cfg, fp)


def _anchor(cid: str, emp: str, node: int, x: float, y: float, t: float) -> dict:
    return {
        "claim_id": cid,
        "anchor_type": "FACE_ANCHOR",
        "identity_ref": emp,
        "node_id": node,
        "world_x": x,
        "world_y": y,
        "t_media": t,
    }


def _node(n: int, **kw) -> dict:
    return {
        "id": n,
        "live": True,
        "coverage_healthy": True,
        "partitioned": False,
        "reputation": 1.0,
        **kw,
    }


def _ident(emp: str, x: float, y: float, t: float, status: str = "seen") -> dict:
    return {
        "id": emp,
        "x": x,
        "y": y,
        "t_media": t,
        "status": status,
        "node": 0,
        "n_claims": 50,
        "confidence": 0.9,
        "age_s": 0.0,
        "error_m": None,
    }


def test_gate_anchor_is_a_check_in_and_elsewhere_a_recognition():
    v = _view()
    g = v.world.entrance.gate
    v.ingest_anchors(
        [
            _anchor("a", "EMP-1041", g.node_id, g.x, g.y, 12.0),
            _anchor("b", "EMP-1027", 3, 25.0, 15.0, 30.0),
        ]
    )
    assert [x["employee_id"] for x in v.verifications] == ["EMP-1041"]
    assert v.state["EMP-1041"]["first_verified"]["kind"] == "check-in"
    assert "first_verified" not in v.state["EMP-1027"]
    assert v.state["EMP-1027"]["last_recognised"]["camera"].endswith("Outbound")


def test_statuses_and_counts():
    v = _view()
    g = v.world.entrance.gate
    v.ingest_anchors([_anchor("a", "EMP-1041", g.node_id, g.x, g.y, 5.0)])
    nodes = [_node(n) for n in range(4)]
    w = v.compute([_ident("EMP-1041", 6.0, 9.0, 40.0)], [], nodes, None, 40.0, None)
    by = {p["id"]: p for p in w["people"]}
    assert by["EMP-1041"]["status"] == "visible" and by["EMP-1041"]["verified"]["clock"].startswith(
        "07:00:05"
    )
    assert by["EMP-1027"]["status"] == "not_arrived"
    assert w["counts"]["on_site"] == 1 and w["counts"]["verified_on_site"] == 1
    assert w["alerts"] == []


def test_leaving_through_the_staff_door_is_left_not_missing():
    v = _view()
    door_y = v.world.entrance.door_y
    nodes = [_node(n) for n in range(4)]
    v.compute([_ident("EMP-1002", 0.8, door_y, 100.0)], [], nodes, None, 100.0, None)
    w = v.compute([], [], nodes, None, 100.0 + v.cfg.left_after_s + 1, None)
    assert next(p for p in w["people"] if p["id"] == "EMP-1002")["status"] == "left"
    w = v.compute([], [], nodes, None, 100.0 + v.cfg.lost_after_s + 5, None)
    assert next(p for p in w["people"] if p["id"] == "EMP-1002")["status"] == "left"


def test_unseen_far_from_the_door_becomes_missing_with_an_alert():
    v = _view()
    nodes = [_node(n) for n in range(4)]
    v.compute([_ident("EMP-1033", 20.0, 3.0, 10.0)], [], nodes, None, 10.0, None)
    w = v.compute([], [], nodes, None, 10.0 + v.cfg.lost_after_s + 1, None)
    assert next(p for p in w["people"] if p["id"] == "EMP-1033")["status"] == "lost"
    assert any(a["kind"] == "employee_lost" for a in w["alerts"])


def test_camera_and_network_alerts_in_plain_words():
    v = _view()
    nodes = [
        _node(0),
        _node(1, coverage_healthy=False),
        _node(2, partitioned=True),
        _node(3, live=False),
    ]
    w = v.compute([], [], nodes, None, 50.0, [[0, 1], [2, 3]])
    kinds = {a["kind"] for a in w["alerts"]}
    assert {"camera_degraded", "network_split", "camera_offline"} <= kinds
    assert w["counts"]["cameras_ok"] == 2


def test_an_unnamed_person_seen_for_long_is_flagged():
    v = _view()
    ident = {**_ident("P-007", 22.0, 16.0, 30.0), "n_claims": v.cfg.unverified_min_claims}
    w = v.compute([ident], [], [_node(n) for n in range(4)], None, 30.0, None)
    assert w["unverified"] and any(a["kind"] == "unverified_person" for a in w["alerts"])


def test_a_person_only_an_untrusted_camera_reports_is_not_flagged():
    """A lying camera's fabricated sightings must not raise "unknown person" alerts."""
    v = _view()
    ident = {**_ident("P-008", 22.0, 16.0, 30.0), "n_claims": v.cfg.unverified_min_claims, "cameras": [2]}
    nodes = [_node(n) for n in range(4)]
    nodes[2]["reputation"] = v.cfg.lying_reputation_alert - 0.1
    assert v.compute([ident], [], nodes, None, 30.0, None)["unverified"] == []
    nodes[2]["reputation"] = 1.0
    assert v.compute([ident], [], nodes, None, 30.0, None)["unverified"]


def test_names_resolve_for_queries():
    v = _view()
    assert v.resolve_person("where is Priya?") == "EMP-1041"
    assert v.resolve_person("where is marcus bell?") == "EMP-1027"
    assert v.resolve_person("where is EMP-1002") == "EMP-1002"
    assert v.resolve_person("where is Bob") is None
