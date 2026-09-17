"""starling_query/capability.py
----------------------------------
Signed capability tokens for C5's query layer (WP-14, deliberately
minimal — STARLING_BUILD_STATE.md §12 rule 1). A token scopes:

  - PURPOSE: `safety` | `incident` | `audit`. Purpose limitation IS the
    enforceable form of the privacy argument (WP-14 task 1): a
    `productivity` purpose (or anything else outside the allow-list) is
    rejected structurally, here, not by a policy document someone can
    ignore. Safety/incident/audit answerable, productivity surveillance
    is not — that is the whole privacy claim, made checkable.
  - AREA: navmesh region/boundary ids the token authorises querying
    about. Empty means "no area restriction" — a token still has to name
    a purpose and a time window either way.
  - TIME WINDOW: the token itself is only valid within `[t_start, t_end]`
    (wall-clock — a real access-control expiry, not media time; CLAUDE.md's
    "no wall-clock reads in the identity path" governs reasoning about
    WHEN something was observed, not when an authorization document
    itself expires).

Every node that answers any part of a query verifies the token itself
before answering (STARLING_BUILD_STATE.md: "nodes refuse out-of-scope
queries") — `verify()` is the one function every one of them calls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from starling_net.keys import NodeKeys

ALLOWED_PURPOSES = frozenset({"safety", "incident", "audit"})


@dataclass(frozen=True)
class Query:
    subject: str
    area: tuple[int, ...] = ()
    t_start: float = 0.0  # media time, start of the window being asked about
    t_end: float = 0.0  # media time, end of the window being asked about


@dataclass(frozen=True)
class CapabilityToken:
    purpose: str
    area: tuple[int, ...] = ()
    t_start: float = 0.0  # wall-clock: when the TOKEN itself becomes valid
    t_end: float = 0.0  # wall-clock: when the TOKEN itself expires
    issued_by: int = 0  # enrolled node_id of the issuing authority
    signature: bytes = field(default=b"", compare=False)

    def signing_payload(self) -> bytes:
        return (
            f"{self.purpose}|{','.join(map(str, self.area))}|"
            f"{self.t_start}|{self.t_end}|{self.issued_by}"
        ).encode("utf-8")

    def to_dict(self) -> dict:
        return {
            "purpose": self.purpose,
            "area": list(self.area),
            "t_start": self.t_start,
            "t_end": self.t_end,
            "issued_by": self.issued_by,
            "signature": self.signature.hex(),
        }

    @staticmethod
    def from_dict(data: dict) -> "CapabilityToken":
        return CapabilityToken(
            purpose=data["purpose"],
            area=tuple(data.get("area", ())),
            t_start=data.get("t_start", 0.0),
            t_end=data.get("t_end", 0.0),
            issued_by=data.get("issued_by", 0),
            signature=bytes.fromhex(data.get("signature", "")),
        )


def issue(purpose: str, area: tuple[int, ...], t_start: float, t_end: float, keys: NodeKeys) -> CapabilityToken:
    """Mint and sign a token as `keys.node_id` (the enrolled issuing
    authority). Does NOT itself enforce `ALLOWED_PURPOSES` — `verify()` is
    the single enforcement point every node actually calls, so a
    malformed or out-of-policy token issued anywhere still gets refused
    at the point that matters.
    """
    unsigned = CapabilityToken(purpose=purpose, area=area, t_start=t_start, t_end=t_end, issued_by=keys.node_id)
    signature = keys.sign(unsigned.signing_payload())
    return CapabilityToken(purpose=purpose, area=area, t_start=t_start, t_end=t_end, issued_by=keys.node_id, signature=signature)


def verify(token: CapabilityToken, query: Query, keys: NodeKeys, now: float | None = None) -> tuple[bool, str]:
    """`(allow, reason)`. Every check is independent and returns the FIRST
    reason it finds, since a caller printing "Cannot answer: <reason>"
    needs exactly one specific reason, not a bag of them.
    """
    if token.purpose not in ALLOWED_PURPOSES:
        return False, (
            f"purpose '{token.purpose}' is not authorised for querying "
            f"(allowed: {sorted(ALLOWED_PURPOSES)})"
        )

    if not keys.verify(token.issued_by, token.signing_payload(), token.signature):
        return False, "capability token signature is invalid or its issuer is not enrolled"

    now = time.time() if now is None else now
    if now < token.t_start or now > token.t_end:
        return False, "capability token is expired or not yet valid"

    if token.area and not set(query.area) <= set(token.area):
        out_of_scope = sorted(set(query.area) - set(token.area))
        return False, f"query area {out_of_scope} is outside this token's authorised area {sorted(token.area)}"

    return True, "ok"
