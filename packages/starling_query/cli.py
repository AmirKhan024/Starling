"""starling_query/cli.py
---------------------------
`starling query "where is P-003" --token <path>` (WP-14, C5).
DELIBERATELY MINIMAL — STARLING_BUILD_STATE.md §12 rule 1: no LLM here.
The template in `starling_query.answer.render` already demonstrates the
property that matters (separating confirmed from inferred, stating the
extent of its own blindness); a language model is a later presentation
layer over the same structure, not built this session.

Architecture note (an ambiguous-choice resolution, recorded per CLAUDE.md):
there is no dedicated `Query`/`QueryResponse` wire message this session —
adding one would mean extending `starling_proto`'s schema and regenerating
it, a bigger change than a "roughly 80 line" capability-token stub
warrants. Instead this CLI joins the mesh the same way
`apps/dashboard/observer.GossipObserver` does: as a passive, SUB-only
listener connected directly to every configured peer, for a bounded
window derived from `--hop-budget` (`hop_budget * HOP_ROUND_S` seconds —
more hops away evidence originates, the more anti-entropy rounds must
elapse for it to have propagated). It then answers ENTIRELY from what it
collected in that window, honestly reporting which nodes never responded.
`packages/` does not import from `apps/` (wrong dependency direction), so
the passive-listener mechanics are a small, self-contained duplicate of
`GossipObserver`'s — the same amount of code either module would need
regardless of who owns the shared copy.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

import yaml
import zmq
from nacl.signing import SigningKey

from starling_attest.negative_evidence import CandidateBelief
from starling_crdt.claims import ClaimSet
from starling_crdt.resolver import resolve
from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel
from starling_net.keys import NodeKeys, load_peer_pubkeys
from starling_node.config import MatchConfig, NegativeEvidenceConfig
from starling_proto.convert import claim_proto_to_record
from starling_proto.generated import starling_pb2
from starling_query.answer import answer_query, render
from starling_query.capability import CapabilityToken, Query, verify
from starling_store.identity_store import LocalStore

HOP_ROUND_S = 2.0  # matches NetConfig.gossip_interval_s's default
_OBSERVER_NODE_ID = -1


class _PassiveCollector:
    """A minimal, query-CLI-local passive listener — see module docstring
    for why this duplicates rather than imports
    `apps.dashboard.observer.GossipObserver`.
    """

    def __init__(self, peers: dict[int, str], keys_dir: Path) -> None:
        self.peers = dict(peers)
        peer_pubkeys = load_peer_pubkeys(keys_dir)
        self._keys = NodeKeys(node_id=_OBSERVER_NODE_ID, signing_key=SigningKey.generate(), peer_pubkeys=peer_pubkeys)
        self.store = LocalStore(db_path=":memory:", node_id=_OBSERVER_NODE_ID)
        self.claims = ClaimSet(self.store)
        self.attested_region_ids: set[int] = set()
        self._last_seen: dict[int, float] = {}
        self._ctx = zmq.Context.instance()
        self._subs: list[zmq.Socket] = []
        self._poller = zmq.Poller()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        for addr in self.peers.values():
            sub = self._ctx.socket(zmq.SUB)
            sub.connect(f"tcp://{addr}")
            sub.setsockopt(zmq.SUBSCRIBE, b"")
            self._subs.append(sub)
            self._poller.register(sub, zmq.POLLIN)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="query-collector")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        for sub in self._subs:
            sub.close(linger=0)
        self._subs = []

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                socks = dict(self._poller.poll(timeout=200))
            except zmq.ZMQError:
                return
            for sub in self._subs:
                if socks.get(sub) == zmq.POLLIN:
                    try:
                        raw = sub.recv(zmq.NOBLOCK)
                    except zmq.Again:
                        continue
                    self._handle_raw(raw)

    def _handle_raw(self, raw: bytes) -> None:
        envelope = starling_pb2.Envelope()
        try:
            envelope.ParseFromString(raw)
        except Exception:
            return
        kind = envelope.WhichOneof("payload")
        if kind is None:
            return
        inner = getattr(envelope, kind)
        sig = getattr(inner, "signature", b"")
        if not sig:
            return
        unsigned = type(inner)()
        unsigned.CopyFrom(inner)
        unsigned.signature = b""
        if not self._keys.verify(envelope.sender_node_id, unsigned.SerializeToString(deterministic=True), sig):
            return

        self._last_seen[envelope.sender_node_id] = time.monotonic()
        if kind == "claim":
            self.claims.add(claim_proto_to_record(envelope.claim))
        elif kind == "attestation":
            self.attested_region_ids.update(envelope.attestation.region_ids)

    def liveness(self, stale_after_s: float) -> dict[int, bool]:
        now = time.monotonic()
        return {
            node_id: (node_id in self._last_seen and now - self._last_seen[node_id] < stale_after_s)
            for node_id in self.peers
        }


def _extract_subject(query_text: str) -> str:
    """No NLP here by design (WP-14 rule 2: template, not generated
    text) — the subject is simply the last whitespace-separated token,
    which is exactly right for "where is P-003" and is the CLI's whole
    concession to being handed a sentence instead of a bare identity ref.
    """
    tokens = query_text.strip().split()
    return tokens[-1] if tokens else query_text.strip()


def _load_peers_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run_query(
    query_text: str,
    token_path: Path,
    peers_config_path: Path,
    hop_budget: int = 3,
    area: tuple[int, ...] = (),
    window_s: float = 600.0,
    stale_after_s: float = 10.0,
) -> tuple[int, str]:
    """Returns `(exit_code, message)` — `main()`'s thin wrapper prints
    `message` and exits with `exit_code`. Factored out so tests call this
    directly without spawning a subprocess.
    """
    subject = _extract_subject(query_text)
    peers_cfg = _load_peers_config(peers_config_path)
    peers: dict[int, str] = {int(k): v for k, v in peers_cfg.get("peers", {}).items()}
    keys_dir = Path(peers_cfg.get("keys_dir", "configs/keys"))
    navmesh_path = peers_cfg.get("navmesh_path")
    match_cfg = MatchConfig(**peers_cfg.get("match", {}))
    lost_threshold_s = peers_cfg.get("lost_threshold_s", 120.0)
    retention_window_s = match_cfg.retention_window_s

    token = CapabilityToken.from_dict(json.loads(Path(token_path).read_text(encoding="utf-8")))
    verify_keys = NodeKeys(node_id=_OBSERVER_NODE_ID, signing_key=SigningKey.generate(), peer_pubkeys=load_peer_pubkeys(keys_dir))

    collector = _PassiveCollector(peers=peers, keys_dir=keys_dir)
    collector.start()
    try:
        time.sleep(max(0.0, hop_budget) * HOP_ROUND_S)

        claims = collector.claims
        records = claims.ordered()
        now_t_media = max((r["t_media"] for r in records), default=0.0)
        query = Query(subject=subject, area=area, t_start=now_t_media - window_s, t_end=now_t_media)

        allowed, reason = verify(token, query, verify_keys)
        if not allowed:
            return 1, f"Cannot answer: {reason}"

        navmesh = None
        reachability = None
        if navmesh_path and Path(navmesh_path).exists():
            navmesh = NavMesh.from_geojson(Path(navmesh_path))
            reachability = ReachabilityModel(navmesh)

        assignment, forks = resolve(claims, reachability, reputation=None, topology=None, cfg=match_cfg)
        claims_by_id = {r["claim_id"]: r for r in records}
        liveness = collector.liveness(stale_after_s=stale_after_s)

        result = answer_query(
            query, assignment, claims_by_id, forks, liveness, now_t_media, retention_window_s,
            attested_region_ids=frozenset(collector.attested_region_ids),
        )

        if result.refused:
            return 1, f"Cannot answer: {result.refusal_reason}"

        if navmesh is not None and reachability is not None:
            last = result.last_confirmed or {}
            age = now_t_media - last.get("t_media", now_t_media)
            if age >= lost_threshold_s and last.get("world_x") is not None:
                belief = CandidateBelief(navmesh, reachability, NegativeEvidenceConfig())
                belief.initialise((last["world_x"], last["world_y"]))
                belief.step(age)
                belief.normalise()
                result = replace(result, candidate_region_m2=belief.area_m2())

        return 0, render(result)
    finally:
        collector.stop()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="starling query", description="Scoped, structured query over the gossiped claim set (WP-14, C5)")
    parser.add_argument("query_text", help='e.g. "where is P-003"')
    parser.add_argument("--token", type=Path, required=True, help="path to a signed capability token JSON file")
    parser.add_argument("--peers-config", type=Path, default=Path("configs/dashboard.local.yaml"))
    parser.add_argument("--hop-budget", type=int, default=3)
    parser.add_argument("--area", type=int, nargs="*", default=[])
    parser.add_argument("--window-s", type=float, default=600.0)
    args = parser.parse_args(argv)

    exit_code, message = run_query(
        args.query_text, args.token, args.peers_config,
        hop_budget=args.hop_budget, area=tuple(args.area), window_s=args.window_s,
    )
    print(message)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
