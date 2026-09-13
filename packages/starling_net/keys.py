"""starling_net/keys.py
------------------------
Ed25519 keypairs per node (pynacl), one per Starling node process.

Threat model note (formalized properly in a later work package's
docs/threat_model.md, recorded here at the point the assumption is
actually made): keys are enrolled at commissioning time — a node's
keypair is generated once, out of band, and its public key distributed to
every peer before the node ever joins the mesh. Sybil attacks (an
attacker minting arbitrary new node identities at will) are therefore
explicitly OUT OF SCOPE: this scheme defends against a node lying about
what it observed, not against an attacker who can freely enroll new keys.

CLI
---
    python -m starling_net.keys --generate 4
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

DEFAULT_KEYS_DIR = Path("configs/keys")


def generate_keypair(node_id: int, keys_dir: Path = DEFAULT_KEYS_DIR) -> tuple[Path, Path]:
    """Generate and write a node's ed25519 keypair. Returns (priv_path, pub_path)."""
    keys_dir.mkdir(parents=True, exist_ok=True)
    signing_key = SigningKey.generate()

    priv_path = keys_dir / f"node-{node_id:02d}.key"
    pub_path = keys_dir / f"node-{node_id:02d}.pub"
    priv_path.write_bytes(bytes(signing_key))
    pub_path.write_bytes(bytes(signing_key.verify_key))
    return priv_path, pub_path


class NodeKeys:
    """A node's own signing key plus every enrolled peer's public key
    (including its own — a node verifies its own re-gossiped claims the
    same way it verifies anyone else's).
    """

    def __init__(self, node_id: int, signing_key: SigningKey, peer_pubkeys: dict[int, VerifyKey]) -> None:
        self.node_id = node_id
        self.signing_key = signing_key
        self.peer_pubkeys = peer_pubkeys

    def sign(self, payload: bytes) -> bytes:
        return self.signing_key.sign(payload).signature

    def verify(self, node_id: int, payload: bytes, signature: bytes) -> bool:
        """True iff `signature` is a valid ed25519 signature over `payload`
        by `node_id`'s ENROLLED public key. False (never raises) for an
        unenrolled node_id, a malformed signature, or a mismatched one.
        """
        verify_key = self.peer_pubkeys.get(node_id)
        if verify_key is None:
            return False
        try:
            verify_key.verify(payload, signature)
            return True
        except (BadSignatureError, ValueError, TypeError):
            return False


def load_peer_pubkeys(keys_dir: Path = DEFAULT_KEYS_DIR) -> dict[int, VerifyKey]:
    """Read every enrolled `node-NN.pub` file in `keys_dir`."""
    pubkeys: dict[int, VerifyKey] = {}
    for pub_path in sorted(Path(keys_dir).glob("node-*.pub")):
        node_id = int(pub_path.stem.split("-")[1])
        pubkeys[node_id] = VerifyKey(pub_path.read_bytes())
    return pubkeys


def load_keys(node_id: int, keys_dir: Path = DEFAULT_KEYS_DIR) -> NodeKeys:
    priv_path = Path(keys_dir) / f"node-{node_id:02d}.key"
    signing_key = SigningKey(priv_path.read_bytes())
    peer_pubkeys = load_peer_pubkeys(keys_dir)
    return NodeKeys(node_id=node_id, signing_key=signing_key, peer_pubkeys=peer_pubkeys)


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Generate ed25519 keypairs for Starling nodes")
    parser.add_argument("--generate", type=int, required=True, help="generate keys for node ids 0..N-1")
    parser.add_argument("--keys-dir", type=Path, default=DEFAULT_KEYS_DIR)
    args = parser.parse_args(argv)

    for node_id in range(args.generate):
        priv_path, pub_path = generate_keypair(node_id, keys_dir=args.keys_dir)
        print(f"node-{node_id:02d}: {priv_path}  {pub_path}")


if __name__ == "__main__":
    main()
