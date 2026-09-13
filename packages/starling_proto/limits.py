"""starling_proto/limits.py
----------------------------
The machine-checkable form of CLAUDE.md rule 3 / STARLING_BUILD_STATE.md
§5.4: no message on the wire may exceed a hard byte cap. 8192 B is
generous relative to every message type's own budget (IdentityClaim's own
budget is 1-4 KB) — it exists as a backstop against a future field being
added carelessly, not as the normal operating size.
"""

from __future__ import annotations

MAX_MESSAGE_BYTES = 8192


def assert_wire_safe(envelope) -> None:
    """Raise if `envelope`'s serialised size exceeds MAX_MESSAGE_BYTES."""
    size = envelope.ByteSize()
    if size > MAX_MESSAGE_BYTES:
        raise ValueError(
            f"Envelope serialises to {size} bytes, exceeding the "
            f"{MAX_MESSAGE_BYTES}-byte wire safety cap (CLAUDE.md rule 3)"
        )
