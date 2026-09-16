"""starling_attest/admission.py
---------------------------------
Whether a received `CoverageAttestation` is admissible as negative
evidence (WP-09 Part 2). `starling_attest.negative_evidence` is the only
sanctioned caller of `admissible()` for the actual belief update — this
module just answers the question, uniformly, for that caller, the
dashboard's blind-spot display, and `starling_eval` metrics alike.

Ambiguous-choice note (CLAUDE.md: take the first option, comment,
continue): STARLING_BUILD_STATE.md's own signature is
`admissible(att, reputation, cfg) -> tuple[bool, str]`, which has no way
to express "stale relative to what 'now' is" or "verified against which
keyring" — both of which the spec explicitly requires this function to
check ("stale beyond the freshness window", "unsigned or invalid
signature"). Both are added as optional keyword-only parameters that
default to skipping the corresponding check, so every existing 3-positional
-argument call site keeps working, and a caller that has a live media
clock / keyring gets the full check.
"""

from __future__ import annotations

from typing import Mapping, Optional

from starling_net.keys import NodeKeys
from starling_node.config import AttestConfig
from starling_proto.generated import starling_pb2


def _unsigned_bytes(att: "starling_pb2.CoverageAttestation") -> bytes:
    unsigned = starling_pb2.CoverageAttestation()
    unsigned.CopyFrom(att)
    unsigned.signature = b""
    return unsigned.SerializeToString()


def admissible(
    att: "starling_pb2.CoverageAttestation",
    reputation: Optional[Mapping[int, float]],
    cfg: AttestConfig,
    *,
    now_physical_ms: Optional[int] = None,
    keys: Optional[NodeKeys] = None,
) -> tuple[bool, str]:
    """`(admissible, reason)`. `reason` is always populated — including on
    success ("admissible") — for logging and the dashboard's blind-spot
    display, per WP-09 task 2's explicit requirement.

    `reputation`: `{node_id: score}`, or `None` to skip the reputation
    check entirely (WP-10, which actually populates real scores, is not
    built yet — Part 3's `detect_omission` only emits the signal it will
    consume). A `node_id` absent from a provided mapping is treated as
    full trust (`1.0`), not zero — an unknown node is not evidence of
    misbehaviour.
    """
    if not att.signature:
        return False, "unsigned"

    if keys is not None and not keys.verify(att.node_id, _unsigned_bytes(att), att.signature):
        return False, "invalid_signature"

    if att.attest_confidence < cfg.tau_attest:
        return False, "below_tau_attest"

    if now_physical_ms is not None:
        age_s = (now_physical_ms - att.t_end.physical_ms) / 1000.0
        if age_s > cfg.freshness_window_s:
            return False, "stale"

    if reputation is not None:
        score = reputation.get(att.node_id, 1.0)
        if score < cfg.min_reputation:
            return False, "low_reputation"

    return True, "admissible"
