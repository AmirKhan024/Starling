"""apps/demo_dashboard/tokens.py
---------------------------------
Issues the demo's capability tokens. Tokens are signed by node 0's key acting
as the issuing authority (`starling_query.capability.issue`); the launcher
writes them to disk and the dashboard only ever READS them — it never holds a
private key. A `productivity` token is issued on purpose: `verify()` refuses
it, which is the purpose-limitation refusal the demo shows.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from starling_net.keys import load_keys
from starling_query.capability import issue

DEMO_PURPOSES = ("safety", "productivity")
TOKEN_VALIDITY_S = 24 * 3600.0


def issue_demo_tokens(keys_dir: Path, token_dir: Path, issuer_node_id: int = 0) -> list[Path]:
    keys = load_keys(issuer_node_id, keys_dir=keys_dir)
    token_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()  # wall clock: a token's own expiry, not the identity path
    paths = []
    for purpose in DEMO_PURPOSES:
        token = issue(purpose, (), now - 60.0, now + TOKEN_VALIDITY_S, keys)
        path = token_dir / f"{purpose}.json"
        path.write_text(json.dumps(token.to_dict()), encoding="utf-8")
        paths.append(path)
    return paths
