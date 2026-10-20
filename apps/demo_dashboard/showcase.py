"""apps/demo_dashboard/showcase.py
------------------------------------
The judge-facing layer of the live-world dashboard, on top of
`DashboardEngine`:

  * "Ask Starling" — plain-English answers to the questions a site manager
    actually asks ("where is Priya", "is anyone in Packing", "is there
    anyone we don't know", "roll call"), each split into what is CONFIRMED
    (a signed sighting), what is ATTESTED (a camera vouching its area is
    clear — negative evidence, C4) and what is only INFERRED, and refused
    when the purpose is not authorised (C5's capability tokens);
  * "Ask every camera" — the same question put to each camera node
    directly; each answers from ITS OWN replica (`GET /replica` on its
    operator endpoint, apps/node.py `replica_answer`). Identical claim
    sets give identical answers (the same fingerprint): C1, made visible;
  * the live bandwidth meter (gossip bytes overheard per node, against
    the video a central server would have to ingest).

Knowledge comes from the same channels as the rest of the dashboard:
overheard gossip, and the nodes' own operator endpoints. Never a node's
database.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import requests
from nacl.signing import SigningKey
from starling_attest.negative_evidence import ZONE_REGION_BASE, healthy_zone_mask
from starling_net.keys import NodeKeys, load_peer_pubkeys
from starling_query.capability import Query, verify

if TYPE_CHECKING:
    from apps.demo_dashboard.engine import DashboardEngine

# Question words → intent. Language, not tuning: matched on whole words.
_ROLLCALL = re.compile(
    r"\b(roll ?call|evacuat\w*|fire|headcount|head count|who(?:'s| is)? (?:still )?(?:inside|on site|in the building|here))\b"
)
_UNKNOWN = re.compile(
    r"\b(unknown|unverified|stranger|intruder\w*|visitor\w*|not verified|unregistered|don'?t know|suspicious)\b"
)
_AREA = re.compile(r"\b(anyone|anybody|someone|somebody|who(?:'s| is)|empty|clear|people)\b")
_ARRIVE = re.compile(r"\b(arriv\w*|check(?:ed)?[ -]?in|came in|when did)\b")
_WORD = re.compile(r"[a-z]+")

EXAMPLES = [
    "Where is Priya?",
    "Is anyone in Packing?",
    "Is anyone in the aisles?",
    "Is there anyone we don't know?",
    "Roll call",
    "When did Marcus arrive?",
]


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 4 and w.endswith("s") else w


def _ago(s: float | None) -> str:
    if s is None:
        return "?"
    s = max(0.0, s)
    return "just now" if s < 1.5 else f"{s:.0f} s ago" if s < 90 else f"{s / 60:.0f} min ago"


def _join(items: list[str]) -> str:
    return (
        items[0]
        if len(items) == 1
        else ", ".join(items[:-1]) + " and " + items[-1]
        if items
        else ""
    )


class Showcase:
    def __init__(self, engine: DashboardEngine) -> None:
        self.e = engine
        self.cfg = engine.cfg
        self.wv = engine.world_view
        nm = engine.navmesh
        h, w = nm.grid.shape
        xs = nm.origin[0] + (np.arange(w) + 0.5) * nm.cell_size
        ys = nm.origin[1] + (np.arange(h) + 0.5) * nm.cell_size
        gx, gy = np.meshgrid(xs, ys)
        self.area_masks: dict[str, np.ndarray] = {}
        self.area_rects: dict[str, list[float]] = {}
        if self.wv is not None:
            for a in self.wv.world.areas:
                self.area_masks[a.name] = (
                    nm.grid & (gx >= a.x0) & (gx <= a.x1) & (gy >= a.y0) & (gy <= a.y1)
                )
                self.area_rects[a.name] = [a.x0, a.y0, a.x1, a.y1]
        self._bw: deque[tuple[float, dict[int, int]]] = deque()
        self._pool = ThreadPoolExecutor(
            max_workers=max(4, len(engine.node_ids)), thread_name_prefix="ask"
        )
        self.last_ask: dict[str, Any] | None = None
        # Public keys only (for verifying capability tokens); the dashboard never signs.
        self._keys = NodeKeys(
            node_id=-1,
            signing_key=SigningKey.generate(),
            peer_pubkeys=load_peer_pubkeys(Path(self.cfg.keys_dir)),
        )

    # ── bandwidth ────────────────────────────────────────────────────────

    def sample_bandwidth(self) -> dict[str, Any]:
        """Gossip bytes/s each node published (as overheard), averaged over
        `bandwidth_window_s`. A PUB message goes once to each neighbour, so
        each camera's uplink carries this times its neighbour count."""
        now = time.monotonic()
        self._bw.append((now, self.e.observer.bytes_by_sender()))
        while len(self._bw) > 2 and now - self._bw[0][0] > self.cfg.bandwidth_window_s:
            self._bw.popleft()
        t0, b0 = self._bw[0]
        t1, b1 = self._bw[-1]
        dt = t1 - t0
        per = {n: (b1.get(n, 0) - b0.get(n, 0)) / dt if dt > 0 else 0.0 for n in self.e.node_ids}
        return {
            "per_node_bytes_per_s": {str(n): round(v, 1) for n, v in per.items()},
            "total_bytes_per_s": round(sum(per.values()), 1),
            "window_s": round(dt, 1),
        }

    # ── ask every camera ────────────────────────────────────────────────

    def ask_cameras(self, purpose: str = "safety") -> dict[str, Any]:
        """Put "who is where?" to every camera node directly, over the same
        media-time window, and compare what their own replicas say. Each node
        verifies the presented capability token itself before answering."""
        snap = self.e.snapshot()
        now_t = float(snap.get("now_t_media") or 0.0)
        t_end = round(max(0.0, now_t - self.cfg.replica_settle_s), 2)
        token = self.e._load_token(purpose)
        params: dict[str, Any] = {"t_end": t_end, "window_s": self.cfg.replica_window_s}
        if token is not None:
            params["token"] = json.dumps(token.to_dict())

        def one(n: int) -> dict[str, Any]:
            t0 = time.monotonic()
            try:
                r = requests.get(
                    self.e._control_url(n, "/replica"),
                    params=params,
                    timeout=self.cfg.replica_timeout_s,
                )
                r.raise_for_status()
                d = r.json()
                d["ok"] = True
            except (
                requests.RequestException,
                ValueError,
            ) as exc:  # a powered-off node simply does not answer
                return {"node_id": n, "ok": False, "error": type(exc).__name__}
            d["ms"] = round((time.monotonic() - t0) * 1000.0)
            if d.get("refused"):
                return {
                    "node_id": n,
                    "ok": False,
                    "refused": True,
                    "reason": d.get("reason"),
                    "ms": d["ms"],
                }
            return self._digest_replica(d, t_end, unknown_labels)

        unknown_labels = {u["id"] for u in (snap.get("world") or {}).get("unverified", [])}

        answers = list(self._pool.map(one, self.e.node_ids))
        ok = [a for a in answers if a["ok"]]
        groups: dict[str, list[int]] = {}
        for a in ok:
            groups.setdefault(a["fingerprint"], []).append(a["node_id"])
        out = {
            "t_end": t_end,
            "clock": self.wv.clock(t_end) if self.wv else None,
            "window_s": self.cfg.replica_window_s,
            "nodes": answers,
            "answered": len(ok),
            "refused": [a["node_id"] for a in answers if a.get("refused")],
            "refusal_reason": next((a["reason"] for a in answers if a.get("refused")), None),
            "purpose": purpose,
            "total": len(answers),
            "groups": [
                {"fingerprint": f, "nodes": ns}
                for f, ns in sorted(groups.items(), key=lambda kv: -len(kv[1]))
            ],
            "agree": len(groups) == 1 and len(ok) > 0,
            "wall": time.monotonic(),
        }
        if purpose == "safety":
            self.last_ask = out
        return out

    def _digest_replica(
        self, d: dict[str, Any], t_end: float, unknown_labels: set[str]
    ) -> dict[str, Any]:
        """Name a node's own answer in the dashboard's terms. An anchored
        identity is an employee id already; an unanchored one is matched by
        its newest claim to the dashboard's label for that same claim (claims
        are the shared vocabulary): an employee, an unknown person, or a stale
        fragment (not shown)."""
        employees: dict[str, Any] = {}
        unknown = []
        for ident in d.get("identities", []):
            age = t_end - ident["t_media"]
            where = (
                self.wv.where(ident["x"], ident["y"]) if self.wv and ident["x"] is not None else {}
            )
            item = {
                "x": ident["x"],
                "y": ident["y"],
                "age_s": round(age, 1),
                "area": where.get("area"),
                "node": ident["node"],
            }
            label = (
                ident["ref"]
                if ident["anchored"]
                else self.e._claim_label.get(ident.get("last_claim", ""))
            )
            if label is not None and self.wv is not None and self.wv.is_employee(label):
                prev = employees.get(label)
                if prev is None or prev["age_s"] > item["age_s"]:
                    employees[label] = item
            elif label in unknown_labels and age <= self.cfg.replica_unknown_recent_s:
                unknown.append(item)
        return {
            "node_id": d["node_id"],
            "ok": True,
            "ms": d.get("ms"),
            "fingerprint": d["fingerprint"],
            "claims_total": d["claims_total"],
            "claims_in_window": d["claims_in_window"],
            "claims_by_origin": d.get("claims_by_origin", {}),
            "hears": d.get("hears", []),
            "ignoring": d.get("ignoring", []),
            "open_forks": d.get("open_forks", 0),
            "employees": employees,
            "unknown": unknown,
        }

    # ── plain-English answers ──────────────────────────────────────────

    def answer(self, text: str, purpose: str) -> dict[str, Any]:
        text = (text or "").strip()
        t = text.lower()
        snap0 = self.e.snapshot()
        clock = (snap0.get("world") or {}).get("clock")
        base = {"query": text, "purpose": purpose, "examples": EXAMPLES, "clock": clock}
        if not t:
            return {
                **base,
                "status": "help",
                "kind": "help",
                "headline": "Ask about a person, an area, or the whole site.",
            }
        refusal = self._purpose_refusal(purpose)
        if refusal is not None:
            return {**base, **refusal}
        if self.last_ask is None or time.monotonic() - self.last_ask["wall"] > self.cfg.ask_reuse_s:
            self.ask_cameras()
        snap = self.e.snapshot()
        w = snap.get("world") or {}
        person = self.wv.resolve_person(t) if self.wv else None
        areas = self._areas_in(t)
        if _ROLLCALL.search(t) and person is None:
            return {**base, **self.roll_call(snap)}
        if _UNKNOWN.search(t):
            return {**base, **self._unknown(snap)}
        if person is not None and _ARRIVE.search(t):
            return {**base, **self._arrival(person, w)}
        if person is not None:
            return {**base, **self._where(text, purpose, person, snap)}
        if areas:
            return {**base, **self._area(areas, snap)}
        if _AREA.search(t):
            return {**base, **self.roll_call(snap)}
        return {
            **base,
            "status": "help",
            "kind": "help",
            "headline": "I can answer questions about a person, a named area of the floor, unknown people, or a roll call.",
        }

    def _purpose_refusal(self, purpose: str) -> dict[str, Any] | None:
        """Verify the purpose's signed capability token here (the query layer)
        AND have every camera node verify it itself: a refused purpose is
        refused by each camera, not by a policy document."""
        token = self.e._load_token(purpose)
        if token is None:
            ok, reason = False, f"no capability token has been issued for purpose '{purpose}'"
        else:
            ok, reason = verify(token, Query(subject="*"), self._keys)
        if ok:
            return None
        lines = [
            (
                f"Reason: {reason}. Starling answers safety, incident and audit questions only — using "
                "the cameras to monitor how hard people work is not an authorised purpose."
            )
        ]
        if token is not None:
            asked = self.ask_cameras(purpose)
            n = len(asked["refused"])
            if n:
                lines.append(
                    f"The same request was put to every camera directly: {n} of {asked['total']} cameras "
                    "verified the signed purpose themselves and refused to answer. The refusal is in the "
                    "code on each camera, not in a policy someone can ignore."
                )
        return {
            "status": "refused",
            "kind": "refused",
            "headline": "Refused — not an authorised purpose.",
            "lines": lines,
        }

    def _areas_in(self, t: str) -> list[str]:
        words = {_stem(w) for w in _WORD.findall(t)}
        hits = []
        for name in self.area_masks:
            if any(_stem(w) in words for w in _WORD.findall(name.lower()) if len(w) > 3):
                hits.append(name)
        # "dock" names both docks; "north dock" only one — prefer the most specific matches.
        if len(hits) > 1:
            scored = [
                (sum(1 for w in _WORD.findall(n.lower()) if _stem(w) in words), n) for n in hits
            ]
            best = max(s for s, _ in scored)
            hits = [n for s, n in scored if s == best]
        return hits

    def _camera_label(self, node: int | None) -> str:
        if node is None or self.wv is None:
            return "a camera"
        from apps.demo_dashboard.world_view import area_name, camera_position

        name = self.wv.camera_names.get(node, f"Camera {node}")
        return f"the {camera_position(name)} ({area_name(name)}) camera"

    def _coverage(self, mask: np.ndarray, now_t: float) -> dict[str, Any]:
        """How much of `mask` cameras currently VOUCH for (a recent, confident,
        gossiped zone attestation), and which cameras those are."""
        e = self.e
        ne = self.cfg.negative_evidence
        atts = list(e.observer.attestations)
        healthy = healthy_zone_mask(
            atts,
            e.zone_masks,
            now_t,
            ne.tau_attest,
            self.cfg.attest_validity_s,
            e.navmesh.grid.shape,
        )
        total = e.navmesh.area_m2(mask)
        latest: dict[int, Any] = {}
        for a in atts:
            if ZONE_REGION_BASE + a.node_id in a.region_ids:
                end = a.t_end.physical_ms / 1000.0
                if a.node_id not in latest or end > latest[a.node_id][0]:
                    latest[a.node_id] = (end, a)
        vouching, silent = [], []
        for n, z in sorted(e.zone_masks.items()):
            if not (z & mask).any():
                continue
            entry = latest.get(n)
            ok = (
                entry is not None
                and entry[1].attest_confidence >= ne.tau_attest
                and now_t - entry[0] <= self.cfg.attest_validity_s
            )
            info = {
                "node": n,
                "camera": self._camera_label(n),
                "confidence": None
                if entry is None
                else round(float(entry[1].attest_confidence), 2),
                "age_s": None if entry is None else round(now_t - entry[0], 1),
            }
            (vouching if ok else silent).append(info)
        covered = e.navmesh.area_m2(mask & healthy)
        return {
            "area_m2": round(total, 1),
            "covered_m2": round(covered, 1),
            "fraction": covered / total if total > 0 else 0.0,
            "vouching": vouching,
            "silent": silent,
        }

    def _network_line(self, snap: dict[str, Any]) -> tuple[str, int, int]:
        nodes = snap.get("nodes", [])
        live = [n["id"] for n in nodes if n["live"]]
        cut = sorted({d for n in nodes for d in n.get("dropped", [])})
        down = [n["id"] for n in nodes if not n["live"]]
        bits = [f"{len(live)} of {len(nodes)} cameras reporting"]
        if down:
            bits.append(
                f"camera {_join([str(d) for d in down])} offline — its latest sightings may be missing"
            )
        if cut:
            bits.append("the network is split; each side answers with what it has")
        return "; ".join(bits) + ".", len(live), len(nodes)

    # where is X ---------------------------------------------------------

    def _where(self, text: str, purpose: str, emp: str, snap: dict[str, Any]) -> dict[str, Any]:
        w = snap["world"]
        p = next((x for x in w["people"] if x["id"] == emp), None)
        name = self.wv.employee_name(emp) or emp
        first = name.split()[0]
        res = self.e.query(text, purpose)
        net, live, total = self._network_line(snap)
        out: dict[str, Any] = {
            "kind": "where",
            "subject": emp,
            "name": name,
            "focus": {"people": [emp]},
            "nodes_responded": res.get("nodes_responded", live),
            "nodes_total": res.get("nodes_total", total),
        }
        # The person's status comes from the manager view's own record (world_view); the query
        # layer's answer only supplies the CONFIRMED sighting while it is still in its window
        # (someone who left on a break minutes ago has dropped out of it).
        known = p is not None and p["status"] in (
            "visible",
            "out_of_view",
            "left",
            "lost",
            "conflict",
        )
        if p is None or (res.get("status") == "refused" and not known):
            reason = res.get("reason") or "no sightings"
            if p is not None and p["status"] == "not_arrived":
                unv = w.get("unverified", [])
                if unv:
                    # Not verified is not the same as not here: an employee whose
                    # check-in was missed is tracked as an unverified person.
                    who = _join([f"{u['label']} in {u['area']}" for u in unv])
                    return {
                        **out,
                        "status": "answered",
                        "headline": f"No camera has verified {name} today — but there is an unverified person on site who may be {first}.",
                        "lines": [
                            (
                                f"{first} has no check-in this shift. The cameras are following {len(unv)} unverified "
                                f"{'person' if len(unv) == 1 else 'people'} ({who}). If {first} came in without the gate "
                                "recording a check-in, that is them: Starling never guesses a name, so a quick look "
                                "settles it."
                            )
                        ],
                        "evidence": [
                            {
                                "tag": "UNKNOWN",
                                "text": f"{u['label']}: {u['area']}, followed across {len(u.get('cameras', []))} cameras, never checked in.",
                            }
                            for u in unv
                        ]
                        + [{"tag": "NETWORK", "text": net}],
                        "focus": {"people": [emp], "unknown": [u["id"] for u in unv]},
                    }
                return {
                    **out,
                    "status": "answered",
                    "headline": f"{name} has not arrived on site today.",
                    "lines": [
                        f"No camera has verified {first} at the entrance gate this shift, and nobody unverified is on site either."
                    ],
                    "evidence": [{"tag": "NETWORK", "text": net}],
                }
            return {
                **out,
                "status": "refused",
                "headline": f"I can't place {name}.",
                "lines": [reason],
            }
        conf = (res.get("confirmed") or {}) if res.get("status") == "answered" else {}
        if conf.get("x") is None:
            out["nodes_responded"], out["nodes_total"] = live, total
        now_t = float(snap.get("now_t_media") or 0.0)
        status = p["status"]
        area = p.get("area", "the warehouse")
        cam = self._camera_label(
            conf["node"] if conf.get("node") is not None else (p.get("identity") or {}).get("node")
        )
        ev: list[dict[str, str]] = []
        if conf.get("x") is not None:
            ev.append(
                {
                    "tag": "CONFIRMED",
                    "text": (
                        f"Last signed sighting: ({conf['x']:.1f}, {conf['y']:.1f}) m in {self.wv.where(conf['x'], conf['y'])['area']}, "
                        f"by {cam} at {self.wv.clock(conf['t_media'])} ({_ago(conf.get('age_s'))}), confidence {conf.get('confidence') or 0:.2f}."
                    ),
                }
            )
        if p.get("verified"):
            ev.append(
                {
                    "tag": "IDENTITY",
                    "text": f"Named because the entrance camera verified {first} at the gate at {p['verified']['clock']} "
                    "(a signed check-in claim) — every later sighting is linked to it by appearance and physics.",
                }
            )
        lines = []
        region = None
        if status == "visible":
            head = f"{name} is in {area} — seen {_ago(p.get('unseen_for_s') or 0)} by {cam}."
        elif status == "left":
            head = f"{name} has left the building (out through the staff entrance {_ago(p.get('unseen_for_s'))})."
        elif status == "conflict":
            head = f"{name} was seen in two places that can't both be true — a human should check."
        elif status == "lost":
            head = f"{name} has not been seen for {_ago(p.get('unseen_for_s'))}; last in {area}."
        else:
            s = p.get("search") or {}
            if s.get("area_m2", 0) < self.cfg.unknown_min_region_m2:
                s = {}  # just out of view: no search area worth showing yet
            region = emp if s else None
            if s and s.get("in_aisles_fraction", 0) >= self.cfg.aisles_fraction_for_inside:
                head = f"{name} is in the storage aisles, where there are no cameras — {first} can only be inside the shaded {s['area_m2']:.0f} m²."
                lines.append(
                    f"How we know: every camera around the aisles is working and vouches it has not seen {first} come out. "
                    "That attested absence rules out the rest of the building."
                )
            else:
                head = f"{name} is out of camera view (last seen {_ago(p.get('unseen_for_s'))} in {area})."
            if s:
                ev.append(
                    {
                        "tag": "INFERRED",
                        "text": (
                            f"Search area {s['area_m2']:.0f} m² — physics alone (walking speed × time) would allow {s['reachable_m2']:.0f} m². "
                            f"Ruled out by cameras {_join([str(n) for n in s['healthy']]) or 'none'} vouching their areas are clear"
                            + (
                                f"; camera {_join([str(n) for n in s['silent']])} cannot vouch, so its area stays possible."
                                if s.get("silent")
                                else "."
                            )
                        ),
                    }
                )
        ev.append({"tag": "NETWORK", "text": net})
        if self.last_ask and time.monotonic() - self.last_ask["wall"] < self.cfg.ask_reuse_s:
            out["cameras"] = self._subject_from_ask(emp)
        return {
            **out,
            "status": "answered",
            "headline": head,
            "lines": lines,
            "evidence": ev,
            "focus": {"people": [emp], "region": region},
            "now_t": now_t,
        }

    def _subject_from_ask(self, emp: str) -> list[dict[str, Any]]:
        a = self.last_ask or {}
        rows = []
        for n in a.get("nodes", []):
            if not n["ok"]:
                rows.append({"node": n["node_id"], "ok": False})
                continue
            b = n["employees"].get(emp)
            rows.append(
                {
                    "node": n["node_id"],
                    "ok": True,
                    "fingerprint": n["fingerprint"],
                    "area": None if b is None else b["area"],
                    "age_s": None if b is None else b["age_s"],
                }
            )
        return rows

    # is anyone in <area> ---------------------------------------------------

    def _area(self, names: list[str], snap: dict[str, Any]) -> dict[str, Any]:
        w = snap["world"]
        now_t = float(snap.get("now_t_media") or 0.0)
        mask = np.zeros_like(self.e.navmesh.grid)
        for n in names:
            mask |= self.area_masks[n]
        label = _join(names)
        inside = [p for p in w["people"] if p["status"] == "visible" and p.get("area") in names]
        unknown = [u for u in w.get("unverified", []) if u.get("area") in names]
        maybe = []
        with self.e._lock:
            beliefs = dict(self.e._beliefs)
        for p in w["people"]:
            if p["status"] != "out_of_view":
                continue
            b = beliefs.get(p["id"])
            if (
                b is not None
                and self.e.navmesh.area_m2(b.belief.mask() & mask) >= self.cfg.area_maybe_min_m2
            ):
                maybe.append(p)
        cov = self._coverage(mask, now_t)
        pct = round(100 * cov["fraction"])
        net, live, total = self._network_line(snap)
        ev: list[dict[str, str]] = []
        for p in inside:
            ev.append(
                {
                    "tag": "CONFIRMED",
                    "text": f"{p['name']} — seen {_ago(p.get('unseen_for_s') or 0)} by {self._camera_label(p.get('identity', {}).get('node'))}.",
                }
            )
        for u in unknown:
            ev.append(
                {
                    "tag": "UNKNOWN",
                    "text": f"{u['label']} — seen by the cameras but never checked in at the entrance.",
                }
            )
        for v in cov["vouching"]:
            ev.append(
                {
                    "tag": "ATTESTED",
                    "text": f"{v['camera'].capitalize()} vouches its view is clear and healthy (confidence {v['confidence']:.2f}, {_ago(v['age_s'])}).",
                }
            )
        for s in cov["silent"]:
            why = (
                "no attestation"
                if s["confidence"] is None
                else f"confidence {s['confidence']:.2f} is below the threshold"
                if (s["age_s"] or 0) <= self.cfg.attest_validity_s
                else "its last attestation is stale"
            )
            ev.append(
                {
                    "tag": "SILENT",
                    "text": f"{s['camera'].capitalize()} cannot vouch ({why}) — its silence is NOT taken as 'empty'.",
                }
            )
        lines = []
        people_ids = [p["id"] for p in inside] + [p["id"] for p in maybe]
        if inside or unknown:
            who = [p["name"] for p in inside] + (["an unverified person"] * len(unknown))
            head = f"Yes — {_join(who)} {'is' if len(who) == 1 else 'are'} in {label} right now."
        elif maybe:
            head = f"Possibly — nobody is visible in {label}, but {_join([p['name'] for p in maybe])} could be there."
            lines.append(
                "Their last sighting and walking speed allow it, and no camera can rule that part out."
            )
        elif cov["fraction"] >= self.cfg.area_clear_coverage:
            head = f"No — {label} is empty. That's not a guess: the cameras vouch for {pct}% of it and saw nobody."
            lines.append(
                "This is negative evidence: a camera that is working (not covered, well lit, detector healthy) "
                "signs a statement that it saw nobody. Silence from a broken camera would never count."
            )
        elif cov["fraction"] > 0:
            head = f"Nobody is visible in {label}, but the cameras can vouch for only {pct}% of it — I can't say it's empty."
            lines.append(
                "The rest of the area is not covered by a working camera right now, and silence is never evidence of absence."
            )
        else:
            head = f"I can't tell — no working camera can see {label}. Silence is not evidence that it's empty."
        ev.append({"tag": "NETWORK", "text": net})
        return {
            "status": "answered",
            "kind": "area",
            "headline": head,
            "lines": lines,
            "evidence": ev,
            "focus": {
                "areas": [self.area_rects[n] for n in names],
                "people": people_ids,
                "unknown": [u["id"] for u in unknown],
            },
            "coverage": cov,
            "nodes_responded": live,
            "nodes_total": total,
        }

    # unknown people -----------------------------------------------------------

    def _unknown(self, snap: dict[str, Any]) -> dict[str, Any]:
        w = snap["world"]
        unv = w.get("unverified", [])
        net, live, total = self._network_line(snap)
        if not unv:
            return {
                "status": "answered",
                "kind": "unknown",
                "headline": "No — everyone the cameras can see was verified at the entrance gate.",
                "lines": [
                    "An unknown person shows up here as soon as cameras have tracked them for a few seconds without a gate check-in."
                ],
                "evidence": [{"tag": "NETWORK", "text": net}],
                "focus": {},
                "nodes_responded": live,
                "nodes_total": total,
            }
        ev = []
        for u in unv:
            cams = _join([self._camera_label(n) for n in u.get("cameras", [])]) or "the cameras"
            where = (
                f"now in {u['area']} ({u['x']:.1f}, {u['y']:.1f}) m"
                if u["status"] == "visible"
                else f"out of view for {_ago(u['unseen_for_s'])}, last in {u['area']}"
            )
            ev.append(
                {
                    "tag": "UNKNOWN",
                    "text": (
                        f"{u['label']}: {where} — followed across {cams}; "
                        f"{u['n_claims']} signed sightings, never verified at the gate."
                    ),
                }
            )
        ev.append({"tag": "NETWORK", "text": net})
        n = len(unv)
        head = (
            f"Yes — {n} unknown {'person is' if n == 1 else 'people are'} on site: "
            + _join(
                [
                    f"{u['label']} {'in' if u['status'] == 'visible' else 'last seen in'} {u['area']}"
                    for u in unv
                ]
            )
            + "."
        )
        return {
            "status": "answered",
            "kind": "unknown",
            "headline": head,
            "lines": [
                "They are tracked across cameras by appearance and physics — the cameras do not need to know who someone is to follow them.",
                "Unverified means no check-in: a stranger, or an employee whose check-in at the gate was missed. Starling never guesses a name.",
            ],
            "evidence": ev,
            "focus": {"unknown": [u["id"] for u in unv]},
            "nodes_responded": live,
            "nodes_total": total,
        }

    # arrival ------------------------------------------------------------

    def _arrival(self, emp: str, w: dict[str, Any]) -> dict[str, Any]:
        p = next((x for x in w["people"] if x["id"] == emp), None)
        name = self.wv.employee_name(emp) or emp
        if p is None or not p.get("verified"):
            return {
                "status": "answered",
                "kind": "arrival",
                "headline": f"{name} has not checked in at the entrance today.",
                "lines": [],
                "evidence": [],
                "focus": {"people": [emp]},
            }
        v, last = p["verified"], p.get("last_verified")
        lines = (
            [f"Most recent check-in: {last['clock']}."]
            if last and last["clock"] != v["clock"]
            else []
        )
        return {
            "status": "answered",
            "kind": "arrival",
            "headline": f"{name} checked in at the entrance gate at {v['clock']}.",
            "lines": lines,
            "evidence": [
                {
                    "tag": "CONFIRMED",
                    "text": f"Signed check-in claim by {self._camera_label(v['node'])}: face verification against the enrolled employee registry.",
                }
            ],
            "focus": {"people": [emp]},
        }

    # roll call ------------------------------------------------------------

    def roll_call(self, snap: dict[str, Any] | None = None) -> dict[str, Any]:
        snap = snap or self.e.snapshot()
        w = snap.get("world") or {}
        rows = []
        for p in w.get("people", []):
            st = p["status"]
            if st in ("not_arrived",):
                continue
            first = p["name"].split()[0]
            s = p.get("search") or {}
            if s.get("area_m2", 0) < self.cfg.unknown_min_region_m2:
                s = {}
            if st == "visible":
                state, action = (
                    "confirmed",
                    f"Seen {_ago(p.get('unseen_for_s') or 0)} in {p.get('area')}.",
                )
            elif st == "left":
                state, action = (
                    "left",
                    f"Left through the staff entrance {_ago(p.get('unseen_for_s'))}. Not inside.",
                )
            elif st == "out_of_view" and s:
                state = "search"
                where = (
                    "the storage aisles"
                    if s.get("in_aisles_fraction", 0) >= self.cfg.aisles_fraction_for_inside
                    else p.get("area", "?")
                )
                action = f"Must still be inside: search {where} — {s['area_m2']:.0f} m² (last seen {_ago(p.get('unseen_for_s'))})."
            elif st == "conflict":
                state, action = (
                    "check",
                    f"Conflicting sightings of {first} — send someone to check.",
                )
            else:
                state, action = (
                    "unknown",
                    f"Not seen {_ago(p.get('unseen_for_s'))} — last in {p.get('area', '?')}. Search there.",
                )
            rows.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "role": p["role"],
                    "colour": p["colour"],
                    "state": state,
                    "action": action,
                    "x": p.get("x"),
                    "y": p.get("y"),
                }
            )
        for u in w.get("unverified", []):
            rows.append(
                {
                    "id": u["id"],
                    "name": u["label"],
                    "role": "Not an employee",
                    "colour": "#d92d20",
                    "state": "intruder",
                    "action": f"Unverified person in {u['area']} — not on the staff list. Account for them too.",
                    "x": u["x"],
                    "y": u["y"],
                }
            )
        inside = [r for r in rows if r["state"] != "left"]
        counts = {
            k: sum(1 for r in rows if r["state"] == k)
            for k in ("confirmed", "search", "unknown", "check", "intruder", "left")
        }
        net, live, total = self._network_line(snap)
        bits = [f"{counts['confirmed']} confirmed by camera"]
        if counts["search"]:
            bits.append(f"{counts['search']} hidden but provably inside (search areas shown)")
        if counts["intruder"]:
            bits.append(
                f"{counts['intruder']} unknown {'person' if counts['intruder'] == 1 else 'people'}"
            )
        if counts["unknown"] + counts["check"]:
            bits.append(f"{counts['unknown'] + counts['check']} to find")
        head = (
            f"{len(inside)} {'person' if len(inside) == 1 else 'people'} inside: "
            + _join(bits)
            + "."
        )
        return {
            "status": "answered",
            "kind": "rollcall",
            "headline": head,
            "rows": rows,
            "counts": counts,
            "inside": len(inside),
            "clock": w.get("clock"),
            "lines": [],
            "evidence": [{"tag": "NETWORK", "text": net}],
            "focus": {
                "people": [r["id"] for r in inside if r["state"] != "intruder"],
                "unknown": [r["id"] for r in inside if r["state"] == "intruder"],
            },
            "nodes_responded": live,
            "nodes_total": total,
        }

    # ── traditional vs Starling, side by side ─────────────────────────────

    def compare(self, snap: dict[str, Any] | None = None) -> dict[str, Any]:
        """The same moment seen by two architectures, from the SAME camera
        detections (generous to the traditional design: its detection is
        assumed exactly as good). What differs is only the architecture:

        * traditional — one server that must receive every camera's video
          (the real ingest process: its measured streams decide which cameras
          it can see) and that has no notion of attested absence, so a person
          out of every camera's view is simply lost;
        * Starling — no server; out-of-view people keep a search area built
          from what healthy cameras did NOT see.
        """
        snap = snap or self.e.snapshot()
        w = snap.get("world") or {}
        c = snap.get("central") or {}
        up = c.get("status") == "UP"
        streaming = {int(n) for n, v in (c.get("cameras") or {}).items() if v.get("streaming")}
        net = snap.get("network") or {}
        nodes = snap.get("nodes", [])
        groups = self.cfg.partition_groups
        split = any(n.get("partitioned") for n in nodes)
        not_vouching = [n["id"] for n in nodes if n["live"] and not n["coverage_healthy"]]
        trad, star = [], []
        for p in w.get("people", []):
            if p["status"] == "not_arrived":
                continue
            base = {
                "id": p["id"],
                "name": p["name"],
                "colour": p["colour"],
                "x": p.get("x"),
                "y": p.get("y"),
            }
            node = (p.get("identity") or {}).get("node")
            unseen = p.get("unseen_for_s") or 0.0
            area = p.get("area", "?")
            s = p.get("search") or {}
            located = s.get("area_m2", 0) >= self.cfg.unknown_min_region_m2
            # A detector skips the odd frame: someone missed for a few seconds counts
            # as still placed on BOTH sides (any tracker coasts that long), so the
            # comparison is about long gaps and failures, where the designs differ.
            recent = (
                p["status"] == "out_of_view" and unseen <= self.cfg.compare_recent_s and not located
            )
            status = "visible" if recent else p["status"]
            # traditional
            if p["status"] == "left":
                t_state, t_text = "left", "Left the building"
            elif not up:
                t_state, t_text = "down", "Unknown — the server is down"
            elif status == "visible" and node is not None and node not in streaming:
                t_state, t_text = "blind", f"Lost: camera {node}'s video cannot reach the server"
            elif status == "visible":
                t_state, t_text = "seen", f"In {area}"
            else:
                t_state, t_text = (
                    "lost",
                    f"Lost: no camera has seen them for {_ago(unseen).replace(' ago', '')}",
                )
            trad.append({**base, "state": t_state, "text": t_text})
            # Starling
            if p["status"] == "left":
                s_state, s_text = "left", "Left through the staff entrance"
            elif status == "visible":
                half = ""
                if split and node is not None:
                    side = next((g for g in groups if node in g), None)
                    if side is not None:
                        half = f" (by cameras {' and '.join(map(str, side))}, on their side of the cut)"
                s_state, s_text = "seen", f"In {area}{half}"
            elif located:
                inside = s.get("in_aisles_fraction", 0) >= self.cfg.aisles_fraction_for_inside
                where = "the storage aisles" if inside else f"a small area near {area}"
                s_state, s_text = (
                    "located",
                    f"Hidden, but must be in {where} ({s['area_m2']:.0f} m²)",
                )
            else:
                s_state, s_text = (
                    "hidden",
                    (
                        f"Out of view for a moment, last in {area}"
                        if unseen <= self.cfg.compare_recent_s
                        else f"Out of view for {_ago(unseen).replace(' ago', '')}, last in {area}"
                    ),
                )
            star.append({**base, "state": s_state, "text": s_text, "search_m2": s.get("area_m2")})
        on_site = [x for x in star if x["state"] != "left"]
        t_known = sum(1 for x in trad if x["state"] == "seen")
        s_known = sum(1 for x in star if x["state"] in ("seen", "located"))
        video = c.get("bytes_per_s") if up else 0.0
        gossip = net.get("gossip_link_bytes_per_s")
        rows = [
            {
                "metric": "People it can place right now",
                "traditional": f"{t_known} of {len(on_site)}",
                "starling": f"{s_known} of {len(on_site)}",
                "better": "starling" if s_known > t_known else "same",
            },
            {
                "metric": "Someone no camera can see",
                "traditional": "Lost",
                "starling": "Located in a small search area",
                "better": "starling",
            },
            {
                "metric": "Video crossing the network",
                "traditional": _rate(video) + " — every camera's footage",
                "starling": "None — only signed facts" + (f" ({_rate(gossip)})" if gossip else ""),
                "better": "starling",
            },
            {
                "metric": "If the server room fails",
                "traditional": "Everyone is lost",
                "starling": "There is no server to fail",
                "better": "starling",
            },
            {
                "metric": "If the network is cut",
                "traditional": "Cameras on the far side go dark",
                "starling": "Both halves keep working, then merge",
                "better": "starling",
            },
            {
                "metric": "A camera that is covered",
                "traditional": "Its area just shows nobody",
                "starling": "Says it can't vouch; never assumes empty",
                "better": "starling",
            },
            {
                "metric": "Who can watch everyone's footage",
                "traditional": "Whoever controls the server",
                "starling": "Nobody — footage never leaves a camera",
                "better": "starling",
            },
        ]
        return {
            "clock": w.get("clock"),
            "central": {
                "status": c.get("status", "DOWN"),
                "streams_up": len(streaming) if up else 0,
                "cameras": len(nodes),
                "cut": c.get("cut_cameras", []),
                "bytes_per_s": video,
            },
            "starling": {
                "cameras_live": sum(1 for n in nodes if n["live"]),
                "cameras": len(nodes),
                "bytes_per_s": gossip,
                "split": split,
                "not_vouching": not_vouching,
            },
            "traditional_people": trad,
            "starling_people": star,
            "unknown": w.get("unverified", []),
            "score": {"traditional": t_known, "starling": s_known, "on_site": len(on_site)},
            "rows": rows,
            "narration": self._narrate(up, split, not_vouching, trad, star, video, gossip),
        }

    def _narrate(
        self,
        up: bool,
        split: bool,
        covered: list[int],
        trad: list[dict[str, Any]],
        star: list[dict[str, Any]],
        video: float | None,
        gossip: float | None,
    ) -> str:
        n_star = sum(1 for x in star if x["state"] in ("seen", "located"))
        if not up:
            return f"The server room is down: the traditional system sees nobody. Starling still places {n_star}."
        blind = [x["name"].split()[0] for x in trad if x["state"] == "blind"]
        if split and blind:
            return f"The network is cut: the server lost two cameras, so it loses {_join(blind)}. Starling keeps working on both sides."
        if split:
            return "The network is cut. Starling keeps working on both sides; the server has lost two cameras."
        if covered:
            return f"Camera {_join([str(c) for c in covered])} is covered. The traditional system shows an empty area; Starling says it cannot see there."
        hidden = [
            (t, x) for t, x in zip(trad, star) if t["state"] == "lost" and x["state"] == "located"
        ]
        if hidden:
            t, x = hidden[0]
            first = t["name"].split()[0]
            where = x["text"].split("must be in ", 1)[-1]
            return f"No camera can see {first}. The traditional system has lost {first}; Starling knows {first} must be in {where}."
        ratio = f"{video / gossip:.0f}x more data" if video and gossip else "far more data"
        return f"Right now both see the same people. But the traditional system needs {ratio}, all in one place. Try a scenario."


def _rate(b: float | None) -> str:
    if not b:
        return "0"
    bits = b * 8
    return f"{bits / 1e6:.1f} Mbit/s" if bits >= 1e6 else f"{bits / 1e3:.1f} kbit/s"
