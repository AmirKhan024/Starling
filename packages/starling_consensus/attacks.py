"""starling_consensus/attacks.py
----------------------------------
Byzantine attack injection (WP-10 Part 3, C2 — docs/threat_model.md §2).
Also implements the runtime control endpoint (`ControlServer`) that
`apps/node.py` starts per node — the demo's "Make node N lie" button, and
the target `starling_eval.netem_plan.plan_lie` POSTs to for the scenario
`lie` event.

Every injected claim is properly signed with the node's real key — this
class never signs anything itself. `apps/node.py` runs `apply_to_claims`
on the list of claim RECORDS (the same dict shape everywhere else in this
project — `starling_crdt.claims`, `starling_store.LocalStore`'s rows) it
is about to gossip, before converting them to `IdentityClaim` protos and
calling `starling_net.gossip.GossipNode.publish()`, which signs whatever
payload it is handed with this node's own real signing key — a fabricated
or replayed claim flows through exactly the same signing path a genuine
one does. This is deliberate, and it is the sentence that justifies the
entire C2 contribution: a compromised node retains its real, enrolled
credentials, so cryptographic signing alone cannot distinguish a
fabricated/suppressed/replayed claim from a genuine one — if signatures
were sufficient, reputation (`starling_consensus.reputation`) would be
unnecessary.
"""

from __future__ import annotations

import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

import numpy as np
from ulid import ULID

from starling_geometry.navmesh import NavMesh
from starling_net.logging import get_logger
from starling_node.config import AttackConfig

logger = get_logger(__name__)

_EMBED_DIM = 512
# Fabricated and replayed claims mint claim_ids/seqs OUTSIDE the node's own
# LocalStore-issued sequence (this injector deliberately has no dependency
# on the store, so it can be constructed and tested in isolation): offset
# far enough above any realistic per-node seq count for one eval run that
# a collision with a genuine claim is not a practical concern here. A
# production integration wiring this injector directly into a node's
# publish path for real (not just for this project's own scenario/demo
# use) would need to reserve this range from the store's own counter.
# Public (not underscore-prefixed) so a caller that needs to tell a
# genuine claim apart from an injected one — e.g. scripts/run_byzantine
# _sweep.py's own accuracy bookkeeping — can do so without reaching into
# this module's internals.
SYNTHETIC_SEQ_BASE = 10**15
_FABRICATED_TRACK_ID_BASE = 900_000  # CLAUDE.md rule 5: local_track_id is node-scoped only


class AttackInjector:
    """One node's live-switchable Byzantine behaviour. `attack` is one of
    "none" | "fabricate" | "suppress" | "replay" | "mixed".
    """

    def __init__(
        self,
        node_id: int,
        attack: str = "none",
        intensity: float = 0.0,
        cfg: Optional[AttackConfig] = None,
        seed: Optional[int] = None,
    ) -> None:
        self.node_id = node_id
        self.attack = attack
        self.intensity = intensity
        self.cfg = cfg or AttackConfig()
        self._rng = random.Random(seed)
        self._np_rng = np.random.default_rng(seed)
        self._synthetic_seq = 0

    def set_attack(self, attack: str, intensity: float) -> None:
        """LIVE switchable — the control endpoint's `POST /attack` and the
        scenario `lie` event both call only this.
        """
        self.attack = attack
        self.intensity = intensity

    def status(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "attack": self.attack, "intensity": self.intensity}

    def apply_to_claims(
        self, claims: list[dict[str, Any]], t_media: float, navmesh: Optional[NavMesh]
    ) -> list[dict[str, Any]]:
        if self.attack == "none" or self.intensity <= 0.0:
            return claims
        if self.attack == "fabricate":
            return self._fabricate(claims, t_media, navmesh)
        if self.attack == "suppress":
            return self._suppress(claims)
        if self.attack == "replay":
            return self._replay(claims, t_media)
        if self.attack == "mixed":
            claims = self._suppress(claims)
            claims = self._replay(claims, t_media)
            claims = self._fabricate(claims, t_media, navmesh)
            return claims
        return claims

    def apply_to_attestations(self, atts: list[Any]) -> list[Any]:
        """Pass-through for every attack this prompt implements. SUPPRESS's
        whole point is that the attestation stream stays healthy WHILE the
        claim stream is thinned — the attestation is deliberately left
        untouched here; `starling_attest.negative_evidence.detect_omission`
        is what notices the contradiction between an unaltered healthy
        attestation and the now-missing corroborating claims.
        """
        return list(atts)

    # ── individual attacks ────────────────────────────────────────────

    def _fabricate(
        self, claims: list[dict[str, Any]], t_media: float, navmesh: Optional[NavMesh]
    ) -> list[dict[str, Any]]:
        if navmesh is None or self._rng.random() >= self.intensity:
            return claims
        return [*claims, self._fabricated_claim(t_media, navmesh)]

    def _fabricated_claim(self, t_media: float, navmesh: NavMesh) -> dict[str, Any]:
        self._synthetic_seq += 1
        i, j = self._random_free_cell(navmesh)
        x, y = navmesh.cell_to_world(i, j)
        embedding = self._np_rng.normal(size=_EMBED_DIM).astype(np.float32)

        return {
            "claim_id": str(ULID()),
            "node_id": self.node_id,
            "seq": SYNTHETIC_SEQ_BASE + self._synthetic_seq,
            "hlc_physical_ms": int(t_media * 1000),
            "hlc_logical": 0,
            "local_track_id": _FABRICATED_TRACK_ID_BASE + self._synthetic_seq,
            "t_media": t_media,
            "embedding": embedding.tobytes(),
            "embed_scale": 1.0,
            "world_x": x,
            "world_y": y,
            "pos_sigma": 0.3,
            "anchor_type": "UNANCHORED",
            "identity_ref": None,
            "last_anchor_t": None,
            "confidence": 0.85,  # plausible-LOOKING: not an obviously low-confidence claim
            "quality": 0.8,
            "signature": None,
        }

    def _random_free_cell(self, navmesh: NavMesh) -> tuple[int, int]:
        free = np.argwhere(navmesh.grid)  # (j, i) pairs
        j, i = free[self._rng.randrange(len(free))]
        return int(i), int(j)

    def _suppress(self, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [c for c in claims if self._rng.random() >= self.intensity]

    def _replay(self, claims: list[dict[str, Any]], t_media: float) -> list[dict[str, Any]]:
        """For a fraction (= intensity) of `claims`, additionally emit a
        second, synthetic entry carrying the SAME observed content
        (embedding/position) but an embedded HLC/t_media from
        `cfg.replay_age_s` ago, under a fresh claim_id/seq — "re-emitting a
        stale claim with a fresh [gossip] timestamp": the wire envelope
        this rides in is sent now, but the claim's own embedded time is
        old, which is exactly what `starling_consensus.plausibility.check`'s
        FRESHNESS grading (claim HLC vs. the admitting node's "now")
        catches. The genuine claim is also still emitted unchanged —
        REPLAY adds a lie, it does not need to also suppress the truth.
        """
        stale_t_media = max(t_media - self.cfg.replay_age_s, 0.0)
        stale_ms = int(stale_t_media * 1000)

        out: list[dict[str, Any]] = []
        for claim in claims:
            out.append(claim)
            if self._rng.random() < self.intensity:
                self._synthetic_seq += 1
                replayed = dict(claim)
                replayed["claim_id"] = str(ULID())
                replayed["seq"] = SYNTHETIC_SEQ_BASE + self._synthetic_seq
                replayed["hlc_physical_ms"] = stale_ms
                replayed["hlc_logical"] = 0
                replayed["t_media"] = stale_t_media
                out.append(replayed)
        return out


# ── control endpoint ──────────────────────────────────────────────────────

def _handler_for(injector: AttackInjector) -> type:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            # Silence http.server's default stderr access log — structured
            # logging (starling_net.logging) is this project's one channel.
            pass

        def _respond_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 — http.server's own naming convention
            if self.path != "/status":
                self._respond_json(404, {"error": "not found"})
                return
            self._respond_json(200, injector.status())

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/attack":
                self._respond_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._respond_json(400, {"error": "invalid JSON"})
                return
            injector.set_attack(str(payload.get("attack", "none")), float(payload.get("intensity", 0.0)))
            self._respond_json(200, injector.status())

    return _Handler


class ControlServer:
    """Tiny stdlib `http.server` control endpoint for one node's
    `AttackInjector`. Demo-only (guarded by `AttackConfig.enable_control_endpoint`,
    default `True` in dev configs). `host` defaults to `127.0.0.1` —
    correct when the caller (e.g. `apps/dashboard/app.py`'s "make node N
    lie" button, WP-13) runs as a neighbour process on the SAME host,
    where loopback is shared. `AttackConfig.control_bind_host` overrides
    this to `"0.0.0.0"` in the docker-hostname node configs, where each
    container has its own independent loopback namespace — that still
    only exposes the endpoint on the private `starling-net` bridge
    network the dashboard container also sits on, never the public
    internet.

        POST /attack  {"attack": "fabricate", "intensity": 0.5}
        GET  /status
    """

    def __init__(self, injector: AttackInjector, port: int, host: str = "127.0.0.1") -> None:
        self.injector = injector
        self._server = ThreadingHTTPServer((host, port), _handler_for(injector))
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name=f"control-{injector.node_id}"
        )
        self._started = False

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def start(self) -> None:
        self._thread.start()
        self._started = True
        logger.info("control_endpoint_started", node_id=self.injector.node_id, port=self.port)

    def stop(self) -> None:
        """A no-op if `start()` was never called: `serve_forever()`'s
        `shutdown()` blocks until the loop it is shutting down is actually
        running, so calling it on a server that never started would hang
        forever rather than return.
        """
        if not self._started:
            self._server.server_close()
            return
        self._server.shutdown()
        self._server.server_close()
