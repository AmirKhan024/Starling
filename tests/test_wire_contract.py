"""Permanent architectural test for starling_proto (CLAUDE.md rule 3 /
STARLING_BUILD_STATE.md §5.4): no raw media ever crosses the wire, and
every message stays inside its byte budget.

Two of the spec's header size figures ("IdentityClaim — 1-4 KB",
"ReputationUpdate — < 100 B") turn out not to survive contact with the
concrete implementation once int8 quantisation and a mandatory 64-byte
ed25519 signature are both accounted for — see the comments on
`test_identity_claim_size_is_small_and_bounded` and
`test_reputation_update_is_small` for the measured numbers and why this
test asserts honestly-measured bounds instead of silently forcing the
original estimates to "pass" (which would require either padding a message
with meaningless bytes or under-signing it — both worse than documenting
the discrepancy).
"""

from __future__ import annotations

import numpy as np
import pytest

from starling_proto.codec import dequantise, quantise
from starling_proto.generated import starling_pb2
from starling_proto.limits import MAX_MESSAGE_BYTES, assert_wire_safe

FORBIDDEN_FIELD_SUBSTRINGS = ("image", "frame", "crop", "jpeg", "png", "video")


def _hlc(physical_ms: int = 1_750_000_000_123, logical: int = 2, node_id: int = 3):
    return starling_pb2.HLC(physical_ms=physical_ms, logical=logical, node_id=node_id)


def _max_identity_claim():
    emb_bytes, scale = quantise(np.ones(512, dtype=np.float32))
    return starling_pb2.IdentityClaim(
        claim_id=bytes(16),
        node_id=2**32 - 1,
        seq=2**64 - 1,
        t_start=_hlc(),
        t_end=_hlc(physical_ms=1_750_000_060_123),
        local_track_id=2**32 - 1,
        embedding=emb_bytes,
        embed_scale=scale,
        world_pos=starling_pb2.Point2D(x=123.456, y=-123.456),
        pos_sigma=1.0,
        anchor=starling_pb2.FACE_ANCHOR,
        identity_ref="P-" + "0" * 34,  # a realistic max-length identity reference
        last_anchor_t=_hlc(),
        confidence=1.0,
        quality=1.0,
        signature=bytes(64),
    )


def _max_coverage_attestation():
    return starling_pb2.CoverageAttestation(
        node_id=2**32 - 1,
        t_start=_hlc(),
        t_end=_hlc(physical_ms=1_750_000_060_123),
        region_ids=list(range(32)),
        occlusion_ratio=1.0,
        illumination_score=1.0,
        detector_health=1.0,
        crossing_observed=False,
        attest_confidence=1.0,
        signature=bytes(64),
    )


def _max_reputation_update():
    return starling_pb2.ReputationUpdate(
        from_node=2**32 - 1,
        about_node=2**32 - 1,
        window_start=_hlc(),
        window_end=_hlc(physical_ms=1_750_000_060_123),
        score=1.0,
        evidence_claim_ids=[bytes(16)] * 3,
        signature=bytes(64),
    )


def _max_topology_observation():
    return starling_pb2.TopologyObservation(
        node_a=2**32 - 1,
        node_b=2**32 - 1,
        transit_secs=999.0,
        handoff_confidence=1.0,
        signature=bytes(64),
    )


def _envelope(payload_field: str, message):
    env = starling_pb2.Envelope(msg_id=bytes(16), sender_node_id=2**32 - 1, sent_hlc=_hlc())
    getattr(env, payload_field).CopyFrom(message)
    return env


ALL_PAYLOADS = [
    ("claim", _max_identity_claim),
    ("attestation", _max_coverage_attestation),
    ("reputation", _max_reputation_update),
    ("topology", _max_topology_observation),
]


@pytest.mark.parametrize("field, builder", ALL_PAYLOADS)
def test_every_message_type_is_wire_safe_under_8192_bytes(field, builder):
    env = _envelope(field, builder())
    assert_wire_safe(env)  # raises ValueError if over MAX_MESSAGE_BYTES
    assert env.ByteSize() < MAX_MESSAGE_BYTES


def test_identity_claim_size_is_small_and_bounded():
    """Spec header: "IdentityClaim — 1-4 KB". Measured, with a fully
    populated int8-quantised 512-d embedding: ~700-900 B — under the
    spec's own 1 KB floor. That floor was a pre-quantisation ballpark;
    quantisation (this module's whole purpose) makes the wire format more
    efficient than budgeted, which is strictly better for the "bytes per
    node-hour" eval metric. The invariant that actually matters — staying
    far below the 8192 B hard cap and the spec's 4 KB ceiling — holds.
    """
    size = _max_identity_claim().ByteSize()
    assert size < 4096
    assert size > 500  # sanity: the embedding should dominate the message


def test_coverage_attestation_is_under_200_bytes():
    assert _max_coverage_attestation().ByteSize() < 200


def test_reputation_update_is_small():
    """Spec header: "ReputationUpdate — < 100 B". Measured, fully
    populated: ~101-155 B depending on evidence_claim_ids count. The
    mandatory 64-byte ed25519 signature (Part 2) alone is already
    ~66 wire bytes — more than half the stated budget — before the two
    mandatory HLC timestamps are even counted. Still tiny next to
    IdentityClaim's ~700-900 B, so this asserts the honestly-measured
    bound rather than the pre-signing estimate.
    """
    size = _max_reputation_update().ByteSize()
    assert size < 200


def test_topology_observation_is_under_500_bytes():
    assert _max_topology_observation().ByteSize() < 500


def test_no_message_field_name_references_raw_media():
    """The machine-checked form of CLAUDE.md rule 3: reflect over every
    generated message descriptor and assert no field name could plausibly
    carry image/video data.
    """
    offenders = []
    for msg_desc in starling_pb2.DESCRIPTOR.message_types_by_name.values():
        for field in msg_desc.fields:
            lname = field.name.lower()
            if any(bad in lname for bad in FORBIDDEN_FIELD_SUBSTRINGS):
                offenders.append(f"{msg_desc.name}.{field.name}")
    assert not offenders, f"forbidden field names found: {offenders}"


def test_quantise_dequantise_roundtrip_cosine_error_under_threshold():
    rng = np.random.default_rng(0)
    for _ in range(50):
        vec = rng.normal(size=512).astype(np.float32)
        vec /= np.linalg.norm(vec)

        packed, scale = quantise(vec)
        restored = dequantise(packed, scale)

        cos_sim = float(np.dot(vec, restored))
        assert 1.0 - cos_sim < 0.01
