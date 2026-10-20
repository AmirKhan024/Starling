"""The judge-facing layer: "ask any camera" (apps/node.py `replica_answer`),
the plain-English answers (apps/demo_dashboard/showcase.py), and the
observer's gossip feed."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from starling_consensus.attacks import PartitionControl
from starling_net.partition import PartitionTracker
from starling_node.config import NodeConfig
from starling_store.identity_store import LocalStore
from ulid import ULID

from apps.node import replica_answer


def _emb(vec) -> bytes:
    v = np.asarray(vec, dtype=np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32).tobytes()


def _claim(
    node_id: int,
    seq: int,
    t: float,
    xy: tuple[float, float],
    emb=(1.0, 0.0, 0.0, 0.0),
    anchor: str | None = None,
) -> dict[str, Any]:
    return {
        "claim_id": str(ULID.from_int(node_id * 100_000 + seq + 1)),
        "node_id": node_id,
        "seq": seq,
        "hlc_physical_ms": int(t * 1000),
        "hlc_logical": 0,
        "local_track_id": 1,
        "t_media": t,
        "embedding": _emb(emb),
        "embed_scale": 1.0,
        "world_x": xy[0],
        "world_y": xy[1],
        "pos_sigma": 0.3,
        "anchor_type": "FACE_ANCHOR" if anchor else "UNANCHORED",
        "identity_ref": anchor,
        "last_anchor_t": t if anchor else None,
        "confidence": 0.9,
        "quality": 0.8,
        "signature": None,
    }


def _claims() -> list[dict[str, Any]]:
    out = [_claim(0, 0, 1.0, (2.0, 2.0), anchor="EMP-1")]
    out += [_claim(0, i, 1.0 + i * 0.4, (2.0 + i * 0.3, 2.0)) for i in range(1, 12)]
    out += [
        _claim(1, i, 1.2 + i * 0.4, (20.0, 10.0 + i * 0.2), emb=(0.0, 1.0, 0.0, 0.0))
        for i in range(12)
    ]
    return out


def _node_cfg() -> NodeConfig:
    return NodeConfig(node_id=0, name="t", source="sim", db_path=":memory:")


def _answer(
    tmp: Path, name: str, claims: list[dict[str, Any]], query: dict[str, str]
) -> dict[str, Any]:
    store = LocalStore(db_path=str(tmp / f"{name}.db"), node_id=9)
    store.append_remote_claims(claims)
    try:
        return replica_answer(
            0, store, None, _node_cfg(), PartitionTracker([1, 2]), PartitionControl(), query
        )
    finally:
        store.close()


def test_replica_answer_is_identical_for_the_same_claims_in_any_arrival_order(
    tmp_path: Path,
) -> None:
    claims = _claims()
    shuffled = claims[:]
    random.Random(3).shuffle(shuffled)
    q = {"t_end": "6.0", "window_s": "60"}
    a, b = _answer(tmp_path, "a", claims, q), _answer(tmp_path, "b", shuffled, q)
    assert a["fingerprint"] == b["fingerprint"]
    assert a["identities"] == b["identities"]
    anchored = [i for i in a["identities"] if i["anchored"]]
    assert [i["ref"] for i in anchored] == ["EMP-1"]
    assert a["claims_in_window"] == len(claims)


def test_full_precision_and_gossiped_copies_give_the_same_answer(tmp_path: Path) -> None:
    """Regression: the origin node holds its own claims at full precision while
    peers hold the gossiped (float32 / millisecond) form; the answer must not
    depend on which copy a replica holds."""
    from starling_proto.convert import claim_proto_to_record, record_to_claim_proto

    rng = random.Random(7)
    raw = []
    for c in _claims():
        c = dict(c)
        c["t_media"] += rng.random() * 1e-4
        c["confidence"] = 0.6 + rng.random() * 0.3
        c["quality"] = 0.5 + rng.random() * 0.4
        c["world_x"] += rng.random() * 1e-3
        raw.append(c)
    wire = [claim_proto_to_record(record_to_claim_proto(c)) for c in raw]
    q = {"t_end": "6.0", "window_s": "60"}
    assert (
        _answer(tmp_path, "raw", raw, q)["fingerprint"]
        == _answer(tmp_path, "wire", wire, q)["fingerprint"]
    )


def test_replica_answer_differs_when_a_replica_is_missing_claims(tmp_path: Path) -> None:
    claims = _claims()
    q = {"t_end": "6.0", "window_s": "60"}
    full = _answer(tmp_path, "full", claims, q)
    partial = _answer(tmp_path, "part", [c for c in claims if c["node_id"] == 0], q)
    assert full["fingerprint"] != partial["fingerprint"]
    assert partial["claims_by_origin"] == {"0": 12}


def test_replica_window_end_pins_the_resolved_set(tmp_path: Path) -> None:
    claims = _claims()
    early = _answer(tmp_path, "e", claims, {"t_end": "2.0", "window_s": "60"})
    assert early["claims_in_window"] < len(claims)
    assert all(i["t_media"] <= 2.0 for i in early["identities"])


# ── plain-English answers ────────────────────────────────────────────────


@pytest.fixture(scope="module")
def showcase():
    from apps.demo_dashboard.config import load_demo_config
    from apps.demo_dashboard.engine import DashboardEngine

    cfg = load_demo_config(Path("configs/world/dashboard.yaml"))
    engine = DashboardEngine(cfg)  # never started: no sockets, no threads
    return engine.showcase


def _snap(
    showcase, people: list[dict[str, Any]], unverified: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    nodes = [{"id": n, "live": True, "dropped": []} for n in range(4)]
    return {
        "now_t_media": 100.0,
        "nodes": nodes,
        "regions": [],
        "world": {
            "people": people,
            "unverified": unverified or [],
            "clock": "07:01:40",
            "alerts": [],
        },
    }


def _person(
    emp: str, name: str, status: str, area: str, x: float, y: float, **kw
) -> dict[str, Any]:
    return {
        "id": emp,
        "name": name,
        "role": "r",
        "colour": "#888",
        "status": status,
        "area": area,
        "x": x,
        "y": y,
        "unseen_for_s": kw.pop("unseen", 0.5),
        **kw,
    }


def _allow(showcase, monkeypatch) -> None:
    """A valid purpose, and no live camera network to ask."""
    monkeypatch.setattr(showcase, "_purpose_refusal", lambda purpose: None)
    monkeypatch.setattr(showcase, "ask_cameras", lambda purpose="safety": None)


def test_node_refuses_without_a_valid_capability_token(tmp_path: Path) -> None:
    from starling_net.keys import load_keys

    from apps.demo_dashboard.tokens import issue_demo_tokens
    from apps.node import _check_capability

    keys = load_keys(1, keys_dir=Path("configs/keys"))
    issue_demo_tokens(Path("configs/keys"), tmp_path)
    safety = (tmp_path / "safety.json").read_text(encoding="utf-8")
    prod = (tmp_path / "productivity.json").read_text(encoding="utf-8")
    assert _check_capability({"token": safety}, keys) is None
    assert "productivity" in (_check_capability({"token": prod}, keys) or "")
    assert _check_capability({}, keys) == "no capability token presented"


def test_area_matching_understands_plurals_and_both_docks(showcase) -> None:
    assert showcase._areas_in("is anyone in the aisle?") == ["Storage aisles"]
    assert sorted(showcase._areas_in("anyone at the docks")) == ["North dock", "South dock"]
    assert showcase._areas_in("who's in the north dock") == ["North dock"]


def test_productivity_purpose_is_refused_before_anything_is_looked_up(showcase) -> None:
    a = showcase.answer("How productive was Daniel today?", "productivity")
    assert a["status"] == "refused"
    assert "productivity" in a["lines"][0]


def test_area_with_a_visible_person_says_yes(showcase, monkeypatch) -> None:
    snap = _snap(
        showcase,
        [
            _person(
                "EMP-1041", "Priya Sharma", "visible", "Packing", 3.0, 14.0, identity={"node": 2}
            )
        ],
    )
    monkeypatch.setattr(showcase.e, "snapshot", lambda: snap)
    _allow(showcase, monkeypatch)
    a = showcase.answer("Is anyone in Packing?", "safety")
    assert a["kind"] == "area" and a["headline"].startswith("Yes")
    assert a["focus"]["people"] == ["EMP-1041"]


def test_empty_area_without_attestations_is_never_called_empty(showcase, monkeypatch) -> None:
    """Silence is not evidence (CLAUDE.md rule 7): no attestation, no "empty"."""
    snap = _snap(showcase, [])
    monkeypatch.setattr(showcase.e, "snapshot", lambda: snap)
    _allow(showcase, monkeypatch)
    a = showcase.answer("Is anyone in Packing?", "safety")
    assert not a["headline"].startswith("No")
    assert any(e["tag"] == "SILENT" for e in a["evidence"])


def test_unknown_people_and_roll_call(showcase, monkeypatch) -> None:
    unk = [
        {
            "id": "P-007",
            "label": "Unknown #1",
            "area": "North dock",
            "x": 25.0,
            "y": 4.0,
            "n_claims": 40,
            "status": "visible",
            "unseen_for_s": 0.0,
            "cameras": [1, 3],
        }
    ]
    people = [
        _person(
            "EMP-1041",
            "Priya Sharma",
            "out_of_view",
            "Storage aisles",
            14.0,
            8.3,
            unseen=12.0,
            search={
                "area_m2": 17.0,
                "reachable_m2": 300.0,
                "in_aisles_fraction": 1.0,
                "healthy": [0, 1, 2, 3],
                "silent": [],
            },
        ),
        _person("EMP-1027", "Marcus Bell", "visible", "South dock", 27.0, 16.0),
        _person("EMP-1002", "Rahul Mehta", "not_arrived", "?", 0.0, 0.0),
    ]
    snap = _snap(showcase, people, unk)
    monkeypatch.setattr(showcase.e, "snapshot", lambda: snap)
    _allow(showcase, monkeypatch)
    u = showcase.answer("Is there anyone we don't know?", "safety")
    assert u["kind"] == "unknown" and "Unknown #1" in u["headline"]
    r = showcase.answer("Roll call", "safety")
    assert r["kind"] == "rollcall"
    assert r["inside"] == 3  # Priya (hidden), Marcus, the unknown person — not Rahul
    assert r["counts"] == {
        "confirmed": 1,
        "search": 1,
        "unknown": 0,
        "check": 0,
        "intruder": 1,
        "left": 0,
    }


def test_observer_feed_is_incremental() -> None:
    from apps.dashboard.observer import GossipObserver

    obs = GossipObserver({}, Path("configs/keys"))
    for i in range(3):
        obs._feed_seq += 1
        obs._feed.append((obs._feed_seq, float(i), 0, "claim", 300, 1, 0))
    first = obs.feed_since(0)
    assert first["seq"] == 3 and len(first["events"]) == 3
    assert obs.feed_since(first["seq"])["events"] == []
    obs.store.close()


def test_ask_cameras_compares_fingerprints(showcase, monkeypatch) -> None:
    monkeypatch.setattr(showcase.e, "snapshot", lambda: {"now_t_media": 50.0})

    class R:
        def __init__(self, fp: str) -> None:
            self.fp = fp

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {
                "node_id": 0,
                "fingerprint": self.fp,
                "claims_total": 1,
                "claims_in_window": 1,
                "identities": [],
            }

    fps = iter(["aaaa", "aaaa", "bbbb", "aaaa"])
    import apps.demo_dashboard.showcase as sc

    monkeypatch.setattr(sc.requests, "get", lambda *a, **k: R(next(fps)))
    out = showcase.ask_cameras()
    assert out["answered"] == 4 and not out["agree"]
    assert out["groups"][0] == {"fingerprint": "aaaa", "nodes": [0, 0, 0]}


def test_unknown_person_keeps_its_number_when_the_track_re_forms(showcase) -> None:
    wv = showcase.e.world_view
    cfg = showcase.cfg
    wv._listed_now = set()
    first = wv._unknown_number({"id": "P-020", "x": 25.0, "y": 10.0, "t_media": 100.0}, cfg)
    wv._listed_now = set()  # P-020 is no longer listed; a new track appears 4 m away, 3 s later
    again = wv._unknown_number({"id": "P-031", "x": 21.0, "y": 10.0, "t_media": 103.0}, cfg)
    wv._listed_now = set()
    far = wv._unknown_number({"id": "P-040", "x": 2.0, "y": 18.0, "t_media": 104.0}, cfg)
    assert again == first
    assert far != first


def test_an_unverified_employee_is_not_reported_as_absent(showcase, monkeypatch) -> None:
    """If the gate missed someone, "where is X" must not say "not arrived" while an
    unverified person is being followed: it says it cannot name them, and points there."""
    unk = [
        {
            "id": "P-002",
            "label": "Unknown #1",
            "area": "South dock",
            "x": 26.0,
            "y": 11.0,
            "n_claims": 98,
            "status": "visible",
            "unseen_for_s": 0.0,
            "cameras": [1, 2, 3],
        }
    ]
    snap = _snap(showcase, [_person("EMP-1027", "Marcus Bell", "not_arrived", "?", 0.0, 0.0)], unk)
    monkeypatch.setattr(showcase.e, "snapshot", lambda: snap)
    monkeypatch.setattr(
        showcase.e, "query", lambda text, purpose: {"status": "refused", "reason": "no claims"}
    )
    _allow(showcase, monkeypatch)
    a = showcase.answer("where is marcus", "safety")
    assert "may be Marcus" in a["headline"]
    assert a["focus"]["unknown"] == ["P-002"]


def test_compare_traditional_loses_what_starling_keeps(showcase) -> None:
    people = [
        _person(
            "EMP-1041",
            "Priya Sharma",
            "out_of_view",
            "Storage aisles",
            14.0,
            8.3,
            unseen=12.0,
            search={
                "area_m2": 17.0,
                "reachable_m2": 300.0,
                "in_aisles_fraction": 1.0,
                "healthy": [0, 1, 2, 3],
                "silent": [],
            },
        ),
        _person(
            "EMP-1027", "Marcus Bell", "visible", "South dock", 27.0, 16.0, identity={"node": 3}
        ),
        _person(
            "EMP-1033", "Daniel Kowalski", "visible", "Receiving", 12.0, 3.0, identity={"node": 0}
        ),
    ]
    snap = _snap(showcase, people)
    for n in snap["nodes"]:
        n["coverage_healthy"] = True
    cams = {
        str(n): {"streaming": n != 3} for n in range(4)
    }  # camera 3's video is cut off from the server
    snap["central"] = {"status": "UP", "cameras": cams, "cut_cameras": [3], "bytes_per_s": 1.2e6}
    c = showcase.compare(snap)
    trad = {p["id"]: p["state"] for p in c["traditional_people"]}
    star = {p["id"]: p["state"] for p in c["starling_people"]}
    assert trad == {"EMP-1041": "lost", "EMP-1027": "blind", "EMP-1033": "seen"}
    assert star == {"EMP-1041": "located", "EMP-1027": "seen", "EMP-1033": "seen"}
    assert c["score"] == {"traditional": 1, "starling": 3, "on_site": 3}
    snap["central"] = {"status": "DOWN"}
    down = showcase.compare(snap)
    assert down["score"]["traditional"] == 0 and "server room is down" in down["narration"]
