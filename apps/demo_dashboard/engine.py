"""apps/demo_dashboard/engine.py
---------------------------------
The demo dashboard's brain. Everything it shows is learned from exactly two
channels (CLAUDE.md rule 8):

  1. gossip — a passive, SUB-only `GossipObserver` (claims, attestations,
     reputation opinions, anti-entropy digests/deltas);
  2. the simulator's ground-truth topic — drawn as faint, labelled markers
     for comparison only.

It never opens a node's database or directory. The only writes it makes are
HTTP calls to the nodes' own control endpoints (partition / lie), the same
endpoints an operator would use.

A background thread recomputes one JSON-able snapshot every
`compute_interval_s`; the HTTP layer just serves the latest one, so the page
refreshes smoothly regardless of how heavy a recompute is.
"""

from __future__ import annotations

import json
import re
import statistics
import threading
import time
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

import numpy as np
import requests
from nacl.signing import SigningKey

from apps.dashboard.observer import GossipObserver
from apps.demo_dashboard.config import DemoDashboardConfig
from apps.node import _ReputationLoop
from starling_attest.negative_evidence import CandidateBelief, healthy_zone_mask
from starling_consensus.reputation import ReputationTable
from starling_crdt.claims import claim_order_key
from starling_crdt.resolver import resolve
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_net.keys import NodeKeys, load_peer_pubkeys
from starling_node.config import ReputationConfig
from starling_query.answer import answer_query, render
from starling_query.capability import CapabilityToken, Query, verify
from starling_sim.messages import GROUND_TRUTH_TOPIC
from starling_sim.transport import SimSubscriber

_OBSERVER_ID = -1
_WORKER_RE = re.compile(r"worker[\s_-]*(\d+)", re.IGNORECASE)


class _Windowed:
    """Duck-types the one thing `resolve()` reads from a `ClaimSet`."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def ordered(self) -> list[dict[str, Any]]:
        return self._records


class _Belief:
    """One unseen identity's candidate-region state: `belief` uses negative
    evidence (healthy attested zones removed); `reach` is the SAME dilation with
    negative evidence switched off (what plain reachability alone would allow)."""

    def __init__(self, belief: CandidateBelief, reach: CandidateBelief, last_seen_t: float, origin: tuple[float, float]) -> None:
        self.belief = belief
        self.reach = reach
        self.last_seen_t = last_seen_t
        self.last_step_t = last_seen_t
        self.origin = origin
        self.started_t = last_seen_t
        self.healthy_nodes: list[int] = []
        self.area_history: deque[tuple[float, float, float]] = deque(maxlen=400)  # (media t, region m2, reachable m2)


class DashboardEngine:
    def __init__(self, cfg: DemoDashboardConfig) -> None:
        self.cfg = cfg
        self.node_ids = sorted(cfg.peers)
        self.navmesh = NavMesh.from_geojson(Path(cfg.navmesh_path), cell_size_m=cfg.geometry.cell_size_m)
        self.reachability = ReachabilityModel(self.navmesh)
        self.floorplan = json.loads(Path(cfg.navmesh_path).read_text(encoding="utf-8"))
        self.zone_masks = self.navmesh.zone_masks(cfg.navmesh_path)
        self.blind_mask = self.navmesh.grid & ~np.any(list(self.zone_masks.values()), axis=0)

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._started_wall = time.monotonic()

        self.observer = self._new_observer()
        self._gt: Optional[dict[str, Any]] = None
        self._gt_wall = 0.0
        self._gt_history: deque[tuple[float, dict[int, tuple[float, float]]]] = deque(maxlen=600)
        self._control: dict[int, dict[str, Any]] = {}
        self._central: Optional[dict[str, Any]] = None  # None = unreachable (DOWN)

        self._colour_of: dict[str, int] = {}
        self._name_votes: dict[str, dict[int, int]] = {}
        self._beliefs: dict[str, _Belief] = {}
        self._was_seen: dict[str, bool] = {}
        self._known_forks: set[str] = set()
        self._events: deque[dict[str, Any]] = deque(maxlen=cfg.event_log_size)
        self._loop = self._new_reputation_loop()

        self._resolved: Optional[dict[str, Any]] = None  # assignment/forks/claims_by_id cache
        self._resolved_count = -1
        self._resolved_wall = 0.0
        self._loop_wall = 0.0
        self._held: set[str] = set()  # far-side claims not yet visible from the vantage node's side
        self._seen_ids: set[str] = set()
        self._fork_memory: dict[str, dict[str, Any]] = {}
        self._conflict: dict[str, Any] = {}
        self._conflict_thread: Optional[threading.Thread] = None
        self._max_t = 0.0
        self._claim_label: dict[str, str] = {}
        self._label_seq = 0
        self._snapshot: dict[str, Any] = {"ready": False}
        self._tick = 0
        self._compute_ms = 0.0

    # ── lifecycle ──────────────────────────────────────────────────────

    def _new_observer(self) -> GossipObserver:
        peers = {n: addr for n, addr in self.cfg.peers.items()}
        return GossipObserver(peers, Path(self.cfg.keys_dir))

    def _new_reputation_loop(self) -> _ReputationLoop:
        loop = _ReputationLoop(
            node_id=_OBSERVER_ID,
            store=self.observer.store,
            geometry=self.reachability,
            cfg=self.cfg.plausibility,
            reputation_table=ReputationTable(node_id=_OBSERVER_ID, cfg=ReputationConfig()),
            lookback_s=self.cfg.resolve_window_s,
        )
        loop.catchup_ids = self.observer.catchup_ids
        return loop

    def start(self) -> None:
        self.observer.start()
        for target, name in (
            (self._gt_loop, "gt"),
            (self._control_loop, "control"),
            (self._compute_loop, "compute"),
        ):
            t = threading.Thread(target=target, daemon=True, name=f"demo-{name}")
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        self.observer.stop()

    # ── ground truth (simulator topic) ─────────────────────────────────

    def _gt_loop(self) -> None:
        sub = SimSubscriber(self.cfg.sim_endpoint, GROUND_TRUTH_TOPIC)
        try:
            while not self._stop.is_set():
                msg = sub.recv(timeout_ms=300)
                if msg is None:
                    continue
                with self._lock:
                    self._gt = msg
                    self._gt_wall = time.monotonic()
                    self._gt_history.append(
                        (msg["t_media"], {w["worker_id"]: (w["x"], w["y"]) for w in msg["workers"]})
                    )
        finally:
            sub.close()

    # ── node control endpoints (status poll + actions) ─────────────────

    def _control_url(self, node_id: int, path: str) -> str:
        port = int(self.cfg.peers[node_id].rsplit(":", 1)[1]) + self.cfg.control_port_offset
        return f"http://127.0.0.1:{port}{path}"

    def _control_loop(self) -> None:
        while not self._stop.is_set():
            for n in self.node_ids:
                try:
                    r = requests.get(self._control_url(n, "/status"), timeout=self.cfg.control_timeout_s)
                    status = r.json()
                    status["reachable"] = True
                except Exception:
                    status = {"reachable": False}
                with self._lock:
                    self._control[n] = status
            try:
                central = requests.get(self.cfg.central_url + "/state", timeout=self.cfg.control_timeout_s).json()
            except Exception:
                central = None
            with self._lock:
                self._central = central
            self._stop.wait(self.cfg.control_poll_interval_s)

    def _post(self, node_id: int, path: str, body: dict[str, Any]) -> bool:
        try:
            r = requests.post(self._control_url(node_id, path), json=body, timeout=self.cfg.control_timeout_s * 4)
            return r.ok
        except Exception:
            return False

    def _log_event(self, kind: str, text: str) -> None:
        with self._lock:
            self._events.append({"wall_s": round(time.monotonic() - self._started_wall, 1), "kind": kind, "text": text})

    def sim_post(self, path: str, body: dict[str, Any]) -> bool:
        try:
            return requests.post(self.cfg.sim_control_url + path, json=body, timeout=1.5).ok
        except Exception:
            return False

    def _central_post(self, path: str, body: dict[str, Any]) -> bool:
        try:
            return requests.post(self.cfg.central_url + path, json=body, timeout=1.0).ok
        except Exception:
            return False

    def kill_central(self) -> dict[str, Any]:
        """Terminate the centralised server PROCESS (it exits). Starling is untouched."""
        ok = self._central_post("/shutdown", {})
        self._log_event("central", f"CENTRAL SERVER killed ({'ok' if ok else 'it was already down'})")
        return {"ok": True}

    def restart_central(self) -> dict[str, Any]:
        if self._central is not None:
            return {"ok": True, "note": "already running"}
        import subprocess
        import sys

        repo = Path(__file__).resolve().parents[2]
        log = open(repo / "data" / "demo" / "logs" / "central.log", "ab", buffering=0)
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        env = dict(__import__("os").environ, PYTHONPATH=f"{repo}{__import__('os').pathsep}{repo / 'packages'}", PYTHONUNBUFFERED="1")
        subprocess.Popen(
            [sys.executable, str(repo / "apps" / "central_server_sim.py"), "--sim-endpoint", self.cfg.sim_endpoint, "--port", str(self.cfg.central_port)],
            cwd=repo, stdout=log, stderr=subprocess.STDOUT, env=env, **kwargs,
        )
        self._log_event("central", "CENTRAL SERVER restarted (it starts with EMPTY state)")
        return {"ok": True}

    def run_script(self, name: str) -> dict[str, Any]:
        """Start a scripted scenario in the simulator (an actor walks in, a
        camera is occluded, ...). The world does everything; nothing is drawn
        by the dashboard itself."""
        ok = self.sim_post("/script", {"name": name})
        self._log_event("script", f"SCRIPT {name}: {'started' if ok else 'FAILED (simulator unreachable?)'}")
        return {"ok": ok, "name": name}

    def run_conflict(self, variant: str) -> dict[str, Any]:
        """Scripted conflict: partition the network, spawn the two face-twins (one
        on each side; both are reported as the same identity by a face gate), then
        heal after `conflict_heal_after_s`. Everything is done by the real nodes,
        simulator and resolver; this thread only presses the same buttons."""
        script = {"resolvable": "conflict_resolvable", "ambiguous": "conflict_ambiguous"}.get(variant)
        if script is None:
            return {"ok": False, "error": "unknown variant"}
        if self._conflict_thread is not None and self._conflict_thread.is_alive():
            return {"ok": False, "error": "a conflict scenario is already running"}

        def run() -> None:
            t0 = time.monotonic()
            self._conflict = {"variant": variant, "phase": "starting"}
            self.heal()
            self._log_event("conflict", f"CONFLICT ({variant}): partitioning the network and sending the two face-twins in")
            self.partition()
            self.run_script(script)
            self._conflict = {"variant": variant, "phase": "partitioned", "since_s": 0}
            while time.monotonic() - t0 < self.cfg.conflict_heal_after_s and not self._stop.is_set():
                self._conflict = {"variant": variant, "phase": "partitioned", "since_s": round(time.monotonic() - t0)}
                self._stop.wait(1.0)
            self.heal()
            self._log_event("conflict", f"CONFLICT ({variant}): network healed; the two sides now merge their claims")
            self._conflict = {"variant": variant, "phase": "healed", "since_s": round(time.monotonic() - t0)}

        self._conflict_thread = threading.Thread(target=run, daemon=True, name="demo-conflict")
        self._conflict_thread.start()
        return {"ok": True, "variant": variant}

    def partition(self) -> dict[str, Any]:
        """Cut group A from group B. Receive-side drop on BOTH sides, since
        `POST /partition` only filters inbound traffic (see STATUS.md)."""
        a, b = self.cfg.partition_groups[0], self.cfg.partition_groups[1]
        ok = {n: self._post(n, "/partition", {"drop_node_ids": b}) for n in a}
        ok.update({n: self._post(n, "/partition", {"drop_node_ids": a}) for n in b})
        # The centralised server sits with group A: cameras on the far side cannot reach it.
        self._central_post("/partition", {"cut_cameras": b})
        self._log_event("partition", f"PARTITION {a} | {b} (ok={ok})")
        return {"ok": all(ok.values()), "nodes": ok}

    def heal(self) -> dict[str, Any]:
        ok = {n: self._post(n, "/partition", {"drop_node_ids": []}) for n in self.node_ids}
        self._central_post("/partition", {"cut_cameras": []})
        self._log_event("heal", f"HEAL all links (ok={ok})")
        return {"ok": all(ok.values()), "nodes": ok}

    def lie(self, node_id: int) -> dict[str, Any]:
        ok = self._post(node_id, "/attack", {"attack": self.cfg.lie_attack, "intensity": self.cfg.lie_intensity})
        self._log_event("lie", f"node {node_id} starts LYING ({self.cfg.lie_attack} @ {self.cfg.lie_intensity})")
        return {"ok": ok, "node_id": node_id}

    def stop_lying(self, node_id: Optional[int] = None) -> dict[str, Any]:
        targets = self.node_ids if node_id is None else [node_id]
        ok = {n: self._post(n, "/attack", {"attack": "none", "intensity": 0.0}) for n in targets}
        self._log_event("lie", f"STOP lying: nodes {targets}")
        return {"ok": all(ok.values()), "nodes": ok}

    def reset(self) -> dict[str, Any]:
        """Heal every link, stop every lie, and start the dashboard's own
        view afresh. Nodes' internal reputation EWMAs are not reset (they
        recover on their own as honest claims arrive)."""
        self.heal()
        self.stop_lying()
        self._fork_memory.clear()
        self._held.clear()
        self._conflict = {}
        with self._lock:
            old = self.observer
            self.observer = self._new_observer()
            self.observer.start()
            self._loop = self._new_reputation_loop()
            self._colour_of.clear()
            self._name_votes.clear()
            self._beliefs.clear()
            self._was_seen.clear()
            self._known_forks.clear()
            self._resolved = None
            self._resolved_count = -1
            self._max_t = 0.0
            self._claim_label.clear()
            self._label_seq = 0
        old.stop()
        self._log_event("reset", "RESET: healed links, stopped lies, cleared the dashboard's view")
        return {"ok": True}

    # ── snapshot ───────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot

    def _compute_loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                snap = self._compute()
                with self._lock:
                    self._snapshot = snap
            except Exception as exc:  # keep serving the last good snapshot
                import structlog

                structlog.get_logger("demo_dashboard").error("compute_failed", error=repr(exc))
                with self._lock:
                    self._snapshot = {**self._snapshot, "error": repr(exc)}
            self._compute_ms = (time.monotonic() - t0) * 1000.0
            self._stop.wait(max(0.05, self.cfg.compute_interval_s - (time.monotonic() - t0)))

    def _peer_reputation(self, node_id: int) -> Optional[float]:
        vals = list(self.observer.reputation.gossiped_opinions(node_id).values())
        return statistics.median(vals) if vals else None

    def _cut_nodes(self) -> set[int]:
        """Nodes the vantage node currently ignores (application-level partition)."""
        with self._lock:
            st = self._control.get(self.cfg.query_vantage_node, {})
        return set(st.get("partition", {}).get("dropped_node_ids", [])) if st.get("reachable") else set()

    def _resolve(self) -> dict[str, Any]:
        """Deterministic resolve over the last `resolve_window_s` of the merged
        claim set (a pure function of that set), recomputed only when the set
        grew and at most every `resolve_min_interval_s`. Window identities are
        given stable display labels (P-001, ...) by majority overlap of their
        claims with the previous window's labels.
        """
        count = self.observer.store.count_claims()
        now = time.monotonic()
        if self._resolved is not None and (
            count == self._resolved_count or now - self._resolved_wall < self.cfg.resolve_min_interval_s
        ):
            return self._resolved
        since = max(0.0, self._max_t - self.cfg.resolve_window_s)
        records = sorted(self.observer.store.local_observations(since, float("inf")), key=claim_order_key)
        max_t = max((r["t_media"] for r in records), default=self._max_t)
        records = [r for r in records if r["t_media"] >= max_t - self.cfg.resolve_window_s]
        self._max_t = max_t

        rep_map = {}
        for n in self.node_ids:
            r = self._peer_reputation(n)
            rep_map[n] = 1.0 if r is None else r
        assignment, forks = resolve(_Windowed(records), self.reachability, rep_map, None, self.cfg.match)

        # Fork view = what the VANTAGE node's side can see. While the vantage
        # node ignores some peers, claims those peers made are held back and only
        # released when the link heals: a conflict between the two halves of a
        # split network therefore appears on RECONNECTION, not before.
        cut = self._cut_nodes()
        if not cut:
            self._held.clear()
        else:
            for r in records:
                if r["claim_id"] not in self._seen_ids and r["node_id"] in cut:
                    self._held.add(r["claim_id"])
        self._seen_ids = {r["claim_id"] for r in records}
        forks_view = forks
        if self._held:
            visible = [r for r in records if r["claim_id"] not in self._held]
            _, forks_view = resolve(_Windowed(visible), self.reachability, rep_map, None, self.cfg.match)

        # Stable labels: each window identity takes the label most of its
        # claims already carried; otherwise it gets a fresh one.
        label_of_ref: dict[str, str] = {}
        taken: set[str] = set()
        for ref, cids in sorted(assignment.trajectories.items(), key=lambda kv: -len(kv[1])):
            votes: dict[str, int] = {}
            for cid in cids:
                lab = self._claim_label.get(cid)
                if lab:
                    votes[lab] = votes.get(lab, 0) + 1
            lab = next((l for l, _ in sorted(votes.items(), key=lambda kv: -kv[1]) if l not in taken), None)
            if lab is None:
                self._label_seq += 1
                lab = f"P-{self._label_seq:03d}"
            taken.add(lab)
            label_of_ref[ref] = lab
        window_ids = {r["claim_id"] for r in records}
        self._claim_label = {cid: l for cid, l in self._claim_label.items() if cid in window_ids}
        for ref, cids in assignment.trajectories.items():
            for cid in cids:
                self._claim_label[cid] = label_of_ref[ref]

        self._resolved = {
            "assignment": assignment,
            "forks": forks,
            "forks_view": forks_view,
            "held": len(self._held),
            "claims_by_id": {r["claim_id"]: r for r in records},
            "max_t": max_t,
            "label_of_ref": label_of_ref,
            "ref_of_label": {l: r for r, l in label_of_ref.items()},
        }
        self._resolved_count = count
        self._resolved_wall = now
        return self._resolved

    def _central_view(self, identities: list, gt: Optional[dict]) -> dict[str, Any]:
        with self._lock:
            c = self._central
        starling_now = sum(1 for i in identities if i["status"] == "seen")
        truth = len(gt["workers"]) if gt else None
        if c is None:
            return {"status": "DOWN", "tracked_now": 0, "tracked": [], "cut_cameras": [], "starling_tracked_now": starling_now, "truth_workers": truth}
        return {**c, "starling_tracked_now": starling_now, "truth_workers": truth}

    def _snap_to_free(self, xy: tuple[float, float]) -> Optional[tuple[float, float]]:
        i, j = self.navmesh.world_to_cell(*xy)
        h, w = self.navmesh.grid.shape
        for r in range(0, 9):
            for dj in range(-r, r + 1):
                for di in range(-r, r + 1):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < w and 0 <= nj < h and self.navmesh.grid[nj, ni]:
                        return self.navmesh.cell_to_world(ni, nj)
        return None

    def _mask_runs(self, mask: np.ndarray) -> list[list[int]]:
        runs: list[list[int]] = []
        for j in range(mask.shape[0]):
            row = mask[j]
            if not row.any():
                continue
            padded = np.concatenate(([False], row, [False]))
            edges = np.flatnonzero(padded[1:] != padded[:-1])
            for a, b in zip(edges[::2], edges[1::2]):
                runs.append([j, int(a), int(b - 1)])
        return runs

    def _update_names(self, ref: str, pos: tuple[float, float], gt_positions: dict[int, tuple[float, float]]) -> None:
        best, best_d = None, self.cfg.name_match_max_dist_m
        for wid, (gx, gy) in gt_positions.items():
            d = float(np.hypot(gx - pos[0], gy - pos[1]))
            if d < best_d:
                best, best_d = wid, d
        if best is not None:
            votes = self._name_votes.setdefault(ref, {})
            votes[best] = votes.get(best, 0) + 1

    def _display_worker(self, ref: str) -> Optional[int]:
        votes = self._name_votes.get(ref)
        if not votes:
            return None
        wid, n = max(votes.items(), key=lambda kv: kv[1])
        return wid if n >= self.cfg.name_min_votes else None

    def _compute(self) -> dict[str, Any]:
        cfg = self.cfg
        obs = self.observer
        self._tick += 1
        resolved = self._resolve()
        assignment, forks, by_id = resolved["assignment"], resolved["forks"], resolved["claims_by_id"]
        now_t = resolved["max_t"]

        with self._lock:
            gt = self._gt
            gt_age = time.monotonic() - self._gt_wall if gt else None
            control = dict(self._control)
        gt_positions = {w["worker_id"]: (w["x"], w["y"]) for w in gt["workers"]} if gt else {}
        gt_names = {w["worker_id"]: w["name"] for w in gt["workers"]} if gt else {}

        # Dashboard-side plausibility pass over what it overheard (same
        # check a node runs) — feeds the "rejected claims" counters.
        if time.monotonic() - self._loop_wall >= self.cfg.resolve_min_interval_s:
            self._loop.run_pass(now_t)
            self._loop_wall = time.monotonic()

        # ── identities ────────────────────────────────────────────────
        identities: list[dict[str, Any]] = []
        attestations = list(obs.attestations)
        label_of_ref = resolved["label_of_ref"]
        for wref, cids in assignment.trajectories.items():
            if len(cids) < cfg.min_identity_claims:
                continue
            ref = label_of_ref[wref]  # stable display label, e.g. P-003
            last = by_id.get(cids[-1])
            if last is None or last.get("world_x") is None:
                continue
            pos = (float(last["world_x"]), float(last["world_y"]))
            age = max(0.0, now_t - last["t_media"])
            if age > cfg.hide_unseen_after_s:
                self._beliefs.pop(ref, None)
                continue
            seen = age < cfg.unseen_after_s
            if seen and gt_positions:
                self._update_names(ref, pos, gt_positions)
            colour = self._colour_of.setdefault(ref, len(self._colour_of))
            wid = self._display_worker(ref)
            trail = []
            for cid in reversed(cids[-60:]):
                c = by_id.get(cid)
                if c is None or now_t - c["t_media"] > cfg.trail_span_s:
                    break
                if c.get("world_x") is not None:
                    trail.append([round(c["world_x"], 2), round(c["world_y"], 2)])
            trail = trail[::-1][:: max(1, len(trail) // cfg.trail_points or 1)]
            err = None
            if seen and wid is not None and wid in gt_positions:
                err = float(np.hypot(pos[0] - gt_positions[wid][0], pos[1] - gt_positions[wid][1]))
            identities.append(
                {
                    "id": ref,
                    "short": ref,
                    "colour": colour,
                    "worker_id": wid,
                    "name": gt_names.get(wid, f"worker-{wid}") if wid is not None else None,
                    "x": round(pos[0], 2),
                    "y": round(pos[1], 2),
                    "t_media": round(last["t_media"], 2),
                    "age_s": round(age, 2),
                    "status": "seen" if seen else "unseen",
                    "node": last["node_id"],
                    "n_claims": len(cids),
                    "confidence": round(float(assignment.confidence.get(wref, 0.0)), 3),
                    "error_m": None if err is None else round(err, 2),
                    "trail": trail,
                }
            )
        identities.sort(key=lambda d: d["colour"])

        # ── candidate regions for unseen identities ───────────────────
        occluded_now = set(gt.get("occluded_nodes", [])) if gt else set()
        # An identity with an OPEN fork has no single last position (two branches
        # claim it), so it gets no candidate region until the conflict is settled.
        forked = {m["identity"] for m in self._fork_memory.values() if m.get("status") == "OPEN"}
        regions = []
        for ident in identities:
            ref = ident["id"]
            b = self._beliefs.get(ref)
            if ref in forked:
                self._beliefs.pop(ref, None)
                ident["status"] = "forked"
                continue
            if ident["status"] == "unseen":
                if b is None:
                    origin = self._snap_to_free((ident["x"], ident["y"]))
                    if origin is not None:
                        ne_cfg = cfg.negative_evidence
                        cb = CandidateBelief(self.navmesh, self.reachability, ne_cfg)
                        cb.initialise(origin)
                        rb = CandidateBelief(self.navmesh, self.reachability, ne_cfg.model_copy(update={"negative_evidence_enabled": False}))
                        rb.initialise(origin)
                        b = self._beliefs[ref] = _Belief(cb, rb, ident["t_media"], origin)
                        self._log_event("unseen", f"{ident['name'] or ident['short']} went UNSEEN at ({ident['x']}, {ident['y']}) — candidate region opened")
                if b is not None:
                    self._advance_belief(b, now_t, attestations)
                    area, reach_area = b.belief.area_m2(), b.reach.area_m2()
                    b.area_history.append((now_t, area, reach_area))
                    mask = b.belief.mask()
                    healthy = sorted(b.healthy_nodes)
                    silent = [n for n in self.node_ids if n not in healthy]
                    leak = {n: round(self.navmesh.area_m2(mask & z), 1) for n, z in self.zone_masks.items() if (mask & z).any()}
                    blind_m2 = round(self.navmesh.area_m2(mask & self.blind_mask), 1)
                    hidden_s = now_t - b.started_t
                    name = ident["name"] or ident["short"]
                    why = []
                    for n in silent:
                        why.append(f"camera {n} is silent ({'occluded, ' if n in occluded_now else ''}no healthy attestation): its silence is not counted as evidence")
                    text = f"{name} unseen {hidden_s:.0f} s. "
                    text += (f"Cameras {', '.join(map(str, healthy))} are healthy and saw nobody, so their zones are ruled out. " if healthy else "No camera has a healthy attestation. ")
                    text += ("; ".join(why) + ". " if why else "")
                    if leak and silent:
                        text += f"The region therefore leaks into camera {', '.join(str(n) for n in leak if n in silent)}'s zone. " if any(n in silent for n in leak) else ""
                    text += f"Search area {area:.0f} m² instead of {reach_area:.0f} m² reachable."
                    regions.append(
                        {
                            "id": ref,
                            "colour": ident["colour"],
                            "area_m2": round(area, 2),
                            "reachable_area_m2": round(reach_area, 2),
                            "ratio": round(area / reach_area, 3) if reach_area > 0 else None,
                            "origin": [round(b.origin[0], 2), round(b.origin[1], 2)],
                            "unseen_for_s": round(hidden_s, 1),
                            "runs": self._mask_runs(mask),
                            "reach_runs": self._mask_runs(b.reach.mask()),
                            "healthy_nodes": healthy,
                            "silent_nodes": silent,
                            "occluded_nodes": sorted(n for n in silent if n in occluded_now),
                            "zone_overlap_m2": {str(n): a2 for n, a2 in leak.items()},
                            "healthy_zone_overlap_m2": round(sum(a2 for n, a2 in leak.items() if n in healthy), 2),
                            "blind_block_area_m2": blind_m2,
                            "explanation": text,
                            "history": [[round(t - b.started_t, 1), round(a3, 1), round(r3, 1)] for t, a3, r3 in list(b.area_history)[-120:]],
                        }
                    )
            elif b is not None:
                self._log_event(
                    "reseen",
                    f"{ident['name'] or ident['short']} RE-SEEN as the same identity after "
                    f"{now_t - b.started_t:.1f}s (region peaked/ended at {b.area_history[-1][1] if b.area_history else 0:.1f} m²)",
                )
                del self._beliefs[ref]
            was = self._was_seen.get(ref)
            self._was_seen[ref] = ident["status"] == "seen"
            if was is None:
                self._log_event("identity", f"new identity {ident['short']}")

        # ── forks ─────────────────────────────────────────────────────
        wall = time.monotonic()
        for f in resolved["forks_view"].all_forks():
            key = f"{f.identity_ref}@{f.opened_at.physical_ms}"
            branches = []
            for i, br in enumerate(f.branches):
                last = by_id.get(br.claim_ids[-1]) if br.claim_ids else None
                branches.append({
                    "index": i, "n_claims": len(br.claim_ids),
                    "x": None if br.last_position is None else round(br.last_position[0], 2),
                    "y": None if br.last_position is None else round(br.last_position[1], 2),
                    "node": None if last is None else last["node_id"],
                    "t_last": None if last is None else round(last["t_media"], 1),
                })
            status = str(f.status.name if hasattr(f.status, "name") else f.status)
            label = label_of_ref.get(f.identity_ref, f.identity_ref)
            mem = self._fork_memory.get(key)
            if mem is None:
                self._log_event("fork", f"FORK OPENED on {label} (face id {f.identity_ref}): {len(branches)} claim chains bind it to incompatible positions "
                                + " vs ".join(f"({b['x']}, {b['y']})" for b in branches))
                mem = {"first_wall": wall, "status": None}
                self._fork_memory[key] = mem
            if mem["status"] != status:
                if status != "OPEN":
                    self._log_event("fork", f"FORK RESOLVED on {label} by {status.replace('RESOLVED_', '').lower()}: {f.resolution_reason}")
                mem["status"] = status
            if status == "OPEN":
                expl = ("Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one "
                        "(never by score). It is an ambiguity for a human: " + " OR ".join(f"branch {b['index']} at ({b['x']}, {b['y']})" for b in branches) + ".")
            else:
                win = f.resolved_branch
                expl = (f"Resolved by {status.replace('RESOLVED_', '').lower()}: branch {win} kept. Rejected: {f.resolution_reason}.")
            mem.update({
                "key": key, "short": key.split("@")[0] + "@" + str(f.opened_at.physical_ms // 1000) + "s", "identity": label, "face_identity": f.identity_ref,
                "status": status, "reason": f.resolution_reason, "resolved_branch": f.resolved_branch, "branches": branches,
                "opened_media_s": round(f.opened_at.physical_ms / 1000.0, 1), "explanation": expl, "last_wall": wall, "in_window": True,
            })
        for key, mem in list(self._fork_memory.items()):
            if wall - mem.get("last_wall", wall) > cfg.fork_memory_s:
                del self._fork_memory[key]
            elif mem.get("last_wall") != wall:
                mem["in_window"] = False
        fork_list = [
            {k: v for k, v in m.items() if k not in ("first_wall", "last_wall")} for m in sorted(self._fork_memory.values(), key=lambda m: m["first_wall"])
        ]

        # ── nodes ─────────────────────────────────────────────────────
        healthy_all = healthy_zone_mask(attestations, self.zone_masks, now_t, cfg.negative_evidence.tau_attest, cfg.attest_validity_s, self.navmesh.grid.shape)
        coverage_ok = {n: bool((self.zone_masks[n] & healthy_all).any()) for n in self.zone_masks}
        live = obs.liveness(cfg.stale_after_s)
        counts = obs.node_claim_counts()
        holes = obs.node_holes()
        nodes = []
        for n in self.node_ids:
            st = control.get(n, {"reachable": False})
            peer_op = obs.reputation.gossiped_opinions(n)
            rep = statistics.median(peer_op.values()) if peer_op else None
            part = st.get("partition", {}).get("dropped_node_ids", []) if st.get("reachable") else []
            evaluated = self._loop.evaluated_by_node[n]
            nodes.append(
                {
                    "id": n,
                    "live": bool(live.get(n, False)),
                    "control_reachable": bool(st.get("reachable")),
                    "partitioned": bool(part),
                    "coverage_healthy": coverage_ok.get(n, False),
                    "occluded": bool(n in occluded_now),
                    "dropped": part,
                    "attack": st.get("attack", "unknown") if st.get("reachable") else "unknown",
                    "intensity": st.get("intensity", 0.0) if st.get("reachable") else 0.0,
                    "lying": bool(st.get("reachable") and st.get("attack", "none") != "none" and st.get("intensity", 0) > 0),
                    "claims": counts.get(n),
                    "holes": holes.get(n),
                    "reputation": None if rep is None else round(rep, 3),
                    "reputation_reporters": {str(k): round(v, 3) for k, v in sorted(peer_op.items())},
                    "rejected": int(self._loop.rejected_by_node[n]),
                    "evaluated": int(evaluated),
                }
            )
        live_counts = [nd["claims"] for nd in nodes if nd["live"] and nd["claims"] is not None]
        spread = (max(live_counts) - min(live_counts)) if len(live_counts) >= 2 else None
        live_holes = [nd["holes"] or 0 for nd in nodes if nd["live"]]
        converged = (
            spread is not None
            and spread <= cfg.converge_tolerance_claims
            and sum(live_holes) == 0
            and not any(nd["partitioned"] for nd in nodes)
        )

        errs = [i["error_m"] for i in identities if i["error_m"] is not None]
        return {
            "ready": True,
            "tick": self._tick,
            "compute_ms": round(self._compute_ms, 1),
            "wall_s": round(time.monotonic() - self._started_wall, 1),
            "now_t_media": round(now_t, 2),
            "gt": None
            if gt is None
            else {
                "t_media": gt["t_media"],
                "age_s": round(gt_age, 2) if gt_age is not None else None,
                "workers": [{"id": w["worker_id"], "name": w["name"], "x": round(w["x"], 2), "y": round(w["y"], 2)} for w in gt["workers"]],
                "occluded_nodes": gt.get("occluded_nodes", []),
            },
            "identities": identities,
            "regions": regions,
            "forks": fork_list,
            "forks_open": sum(1 for f in fork_list if f["status"] == "OPEN"),
            "held_back_claims": resolved.get("held", 0),
            "conflict": dict(self._conflict),
            "nodes": nodes,
            "convergence": {
                "spread": spread,
                "holes_total": sum(live_holes),
                "any_partitioned": any(nd["partitioned"] for nd in nodes),
                "converged": bool(converged),
                "tolerance": cfg.converge_tolerance_claims,
            },
            "central": self._central_view(identities, gt),
            "nodes_live": sum(1 for nd in nodes if nd["live"]),
            "mean_error_m": None if not errs else round(float(np.mean(errs)), 2),
            "events": list(self._events)[-25:],
            "claims_total": obs.store.count_claims(),
        }

    def _advance_belief(self, b: _Belief, now_t: float, attestations: list) -> None:
        """One tick: recompute which cameras are CURRENTLY healthy (gossiped,
        recent, confident zone attestations), forbid their zones, then dilate
        by the elapsed media time. A silent or unhealthy camera forbids nothing
        (silence is never evidence). Uses gossiped attestations only."""
        ne = self.cfg.negative_evidence
        forbidden = healthy_zone_mask(
            attestations, self.zone_masks, now_t, ne.tau_attest, self.cfg.attest_validity_s, self.navmesh.grid.shape
        )
        b.healthy_nodes = [n for n, z in self.zone_masks.items() if (forbidden & z).any() and (z & forbidden).sum() == z.sum()]
        b.belief.set_forbidden(forbidden)
        dt = now_t - b.last_step_t
        if dt > 0:
            b.belief.step(dt)
            b.reach.step(dt)
            b.last_step_t = now_t
        b.belief.normalise()

    # ── query ──────────────────────────────────────────────────────────

    def _load_token(self, purpose: str) -> Optional[CapabilityToken]:
        p = Path(self.cfg.token_dir) / f"{purpose}.json"
        if not p.exists():
            return None
        return CapabilityToken.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def query(self, text: str, purpose: str = "safety") -> dict[str, Any]:
        text = (text or "").strip()
        out: dict[str, Any] = {"query": text, "purpose": purpose}
        token = self._load_token(purpose)
        if token is None:
            return {**out, "status": "refused", "reason": f"no capability token issued for purpose '{purpose}'"}
        resolved = self._resolve()
        assignment = resolved["assignment"]
        now_t = resolved["max_t"]

        m = _WORKER_RE.search(text)
        subject = text.split()[-1] if text.split() else text
        display_note = None
        if m:
            wid = int(m.group(1))
            snap = self.snapshot()
            matches = [i for i in snap.get("identities", []) if i["worker_id"] == wid]
            if matches:
                best = max(matches, key=lambda i: i["n_claims"])
                subject = best["id"]
                display_note = f"'worker {wid}' → resolved identity {best['short']} (display mapping from the simulator's ground truth)"
            else:
                subject = f"worker {wid}"  # no identity matches: answer_query refuses with its own reason

        keys = NodeKeys(
            node_id=_OBSERVER_ID, signing_key=SigningKey.generate(),
            peer_pubkeys=load_peer_pubkeys(Path(self.cfg.keys_dir)),
        )
        subject_ref = resolved["ref_of_label"].get(subject, subject)  # display label -> window identity
        q = Query(subject=subject_ref, area=(), t_start=now_t - self.cfg.query_window_s, t_end=now_t)
        allowed, reason = verify(token, q, keys)
        if not allowed:
            return {**out, "status": "refused", "subject": subject, "reason": reason, "display_note": display_note}

        live = self.observer.liveness(self.cfg.stale_after_s)
        with self._lock:
            vantage = self._control.get(self.cfg.query_vantage_node, {})
        cut = set(vantage.get("partition", {}).get("dropped_node_ids", [])) if vantage.get("reachable") else set()
        liveness = {n: bool(live.get(n, False)) and n not in cut for n in self.node_ids}
        attested = frozenset(r for a in self.observer.attestations for r in a.region_ids)
        result = answer_query(
            q, assignment, resolved["claims_by_id"], resolved["forks"], liveness, now_t,
            self.cfg.match.retention_window_s, attested_region_ids=attested,
        )
        result = replace(result, subject=subject, refusal_reason=(result.refusal_reason or "").replace(subject_ref, subject) or None)
        if result.refused:
            return {**out, "status": "refused", "subject": subject, "reason": result.refusal_reason,
                    "blind_spots": [n for n, _ in result.blind_spots], "display_note": display_note,
                    "nodes_responded": result.nodes_responded, "nodes_total": result.nodes_total}

        with self._lock:
            b = self._beliefs.get(subject)
        if b is not None:
            result = replace(result, candidate_region_m2=b.belief.area_m2())
        lc = result.last_confirmed or {}
        age = now_t - lc.get("t_media", now_t)
        confirmed = {
            "x": lc.get("world_x"), "y": lc.get("world_y"), "t_media": lc.get("t_media"),
            "confidence": lc.get("confidence"), "node": lc.get("node_id"), "age_s": round(age, 1),
        }
        inferred = {"note": result.inferred_note, "candidate_region_m2": result.candidate_region_m2,
                    "currently_unseen": b is not None}
        return {
            **out, "status": "answered", "subject": subject, "display_note": display_note,
            "confirmed": confirmed, "inferred": inferred,
            "unreachable_nodes": [n for n, _ in result.blind_spots],
            "nodes_responded": result.nodes_responded, "nodes_total": result.nodes_total,
            "text": render(result),
        }
