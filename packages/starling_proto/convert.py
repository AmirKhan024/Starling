"""starling_proto/convert.py
-----------------------------
Bidirectional mapping between `starling_store.LocalStore`'s `claims` table
row shape (a plain dict) and the wire `IdentityClaim` protobuf message.

This is the one place that schema lives, so `apps/node.py` (publishing a
claim this node just observed) and `starling_net.anti_entropy` (ingesting
claims received from a peer) share the exact same mapping instead of two
subtly-diverging copies of it.
"""

from __future__ import annotations

from typing import Any, Optional

from ulid import ULID

from starling_proto.generated import starling_pb2


def claim_id_to_bytes(claim_id: str) -> bytes:
    """A LocalStore claim_id is a 26-char ULID string; the wire schema
    wants its raw 16-byte form (spec: "bytes claim_id = 1; // 16B").
    """
    return ULID.from_str(claim_id).bytes


def claim_id_from_bytes(claim_id: bytes) -> str:
    return str(ULID.from_bytes(claim_id))


def record_to_claim_proto(record: dict[str, Any]) -> starling_pb2.IdentityClaim:
    """Build a wire `IdentityClaim` from a `LocalStore` claims-table row.

    A freshly-observed claim is a single instant, so `t_end` is set equal
    to `t_start` here — a later work package (confidence decay /
    re-anchoring) is what would ever make them differ.
    """
    claim = starling_pb2.IdentityClaim(
        claim_id=claim_id_to_bytes(record["claim_id"]),
        node_id=record["node_id"],
        seq=record["seq"],
        local_track_id=record["local_track_id"],
        embedding=bytes(record["embedding"]),
        embed_scale=record["embed_scale"],
        confidence=record["confidence"],
        quality=record["quality"],
    )
    claim.t_start.physical_ms = record["hlc_physical_ms"]
    claim.t_start.logical = record["hlc_logical"]
    claim.t_start.node_id = record["node_id"]
    claim.t_end.CopyFrom(claim.t_start)

    if record.get("world_x") is not None and record.get("world_y") is not None:
        claim.world_pos.x = record["world_x"]
        claim.world_pos.y = record["world_y"]
    if record.get("pos_sigma") is not None:
        claim.pos_sigma = record["pos_sigma"]

    claim.anchor = starling_pb2.AnchorType.Value(record.get("anchor_type") or "UNANCHORED")
    if record.get("identity_ref"):
        claim.identity_ref = record["identity_ref"]
    if record.get("last_anchor_t") is not None:
        claim.last_anchor_t.physical_ms = int(record["last_anchor_t"])

    signature = record.get("signature")
    if signature:
        claim.signature = bytes(signature)

    return claim


def claim_proto_to_record(claim: starling_pb2.IdentityClaim) -> dict[str, Any]:
    """The inverse of `record_to_claim_proto`, for ingesting a claim
    received from a peer (anti-entropy / gossip) into this node's own
    `claims` table via `LocalStore.append_remote_claims`.
    """
    has_world_pos = claim.HasField("world_pos")
    return {
        "claim_id": claim_id_from_bytes(claim.claim_id),
        "node_id": claim.node_id,
        "seq": claim.seq,
        "hlc_physical_ms": claim.t_start.physical_ms,
        "hlc_logical": claim.t_start.logical,
        "local_track_id": claim.local_track_id,
        "t_media": claim.t_start.physical_ms / 1000.0,
        "embedding": claim.embedding,
        "embed_scale": claim.embed_scale,
        "world_x": claim.world_pos.x if has_world_pos else None,
        "world_y": claim.world_pos.y if has_world_pos else None,
        "pos_sigma": claim.pos_sigma if claim.HasField("world_pos") else None,
        "anchor_type": starling_pb2.AnchorType.Name(claim.anchor),
        "identity_ref": claim.identity_ref or None,
        "last_anchor_t": (
            claim.last_anchor_t.physical_ms / 1000.0
            if claim.HasField("last_anchor_t") and claim.last_anchor_t.physical_ms
            else None
        ),
        "confidence": claim.confidence,
        "quality": claim.quality,
        "signature": claim.signature or None,
    }


def make_claim_envelope(
    claim: starling_pb2.IdentityClaim,
    sender_node_id: int,
    sent_hlc: Optional[starling_pb2.HLC] = None,
) -> starling_pb2.Envelope:
    """Wrap `claim` in a fresh `Envelope`. `msg_id` identifies this
    particular gossip transmission (a re-gossiped claim could get a new
    one on each hop) and is distinct from the claim's own stable
    `claim_id`.
    """
    env = starling_pb2.Envelope(msg_id=bytes(ULID()), sender_node_id=sender_node_id)
    if sent_hlc is not None:
        env.sent_hlc.CopyFrom(sent_hlc)
    env.claim.CopyFrom(claim)
    return env


def make_attestation_envelope(
    attestation: starling_pb2.CoverageAttestation,
    sender_node_id: int,
    sent_hlc: Optional[starling_pb2.HLC] = None,
) -> starling_pb2.Envelope:
    """Wrap a `CoverageAttestation` (WP-09 Part 2,
    `starling_attest.attestation.Attestor.tick`'s return value) in a fresh
    `Envelope`, mirroring `make_claim_envelope` exactly.
    """
    env = starling_pb2.Envelope(msg_id=bytes(ULID()), sender_node_id=sender_node_id)
    if sent_hlc is not None:
        env.sent_hlc.CopyFrom(sent_hlc)
    env.attestation.CopyFrom(attestation)
    return env
