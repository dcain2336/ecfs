"""ECFSKeyPair — Ed25519 signing + X25519 key agreement for ECFS nodes.

Provides generation, signing/verification, PFS key derivation, and
serialisation for persistent storage.
"""

from __future__ import annotations

import hashlib
from base64 import standard_b64decode, standard_b64encode
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _verify_key_id(pub: Ed25519PublicKey) -> bytes:
    """First 8 bytes of SHA-256(serialised public key)."""
    raw = pub.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return hashlib.sha256(raw).digest()[:8]


def _dest_hash(pub: Ed25519PublicKey) -> bytes:
    """Full SHA-256 of the serialised Ed25519 public key (32 bytes)."""
    raw = pub.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return hashlib.sha256(raw).digest()


@dataclass
class ECFSKeyPair:
    """Cryptographic identity for an ECFS node.

    Contains an Ed25519 signing key pair and an X25519 key-agreement key pair
    suitable for PFS (Perfect Forward Secrecy).
    """

    signing_key: Ed25519PrivateKey
    verify_key: Ed25519PublicKey
    exchange_key: X25519PrivateKey
    public_exchange: X25519PublicKey
    key_id: bytes = field(default=b"")

    def __post_init__(self) -> None:
        if not self.key_id:
            self.key_id = _verify_key_id(self.verify_key)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    @classmethod
    def generate(cls) -> "ECFSKeyPair":
        """Generate a fresh, random keypair."""
        signing_key = Ed25519PrivateKey.generate()
        verify_key = signing_key.public_key()
        exchange_key = X25519PrivateKey.generate()
        public_exchange = exchange_key.public_key()
        return cls(
            signing_key=signing_key,
            verify_key=verify_key,
            exchange_key=exchange_key,
            public_exchange=public_exchange,
        )

    # ------------------------------------------------------------------
    # Signing / verification
    # ------------------------------------------------------------------

    def sign(self, data: bytes) -> bytes:
        """Sign *data* with the Ed25519 private key."""
        return self.signing_key.sign(data)

    def verify_signature(self, data: bytes, signature: bytes) -> bool:
        """Return True if *signature* is valid for *data*."""
        try:
            self.verify_key.verify(signature, data)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Key agreement (PFS)
    # ------------------------------------------------------------------

    def derive_shared_secret(self, peer_public_exchange: X25519PublicKey) -> bytes:
        """X25519 ECDH → HKDF → 32-byte shared session key."""
        raw_shared = self.exchange_key.exchange(peer_public_exchange)
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"ecfs-pfs-v1",
        )
        return hkdf.derive(raw_shared)

    # ------------------------------------------------------------------
    # Addressing
    # ------------------------------------------------------------------

    def public_destination_hash(self) -> bytes:
        """SHA-256 of the Ed25519 public key (32 bytes)."""
        return _dest_hash(self.verify_key)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise to a JSON-friendly dict (base64-encoded keys)."""
        return {
            "signing_key": standard_b64encode(
                self.signing_key.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                )
            ).decode(),
            "exchange_key": standard_b64encode(
                self.exchange_key.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                )
            ).decode(),
            "key_id": standard_b64encode(self.key_id).decode(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ECFSKeyPair":
        """Restore a keypair from the dict produced by ``to_dict``."""
        signing_bytes = standard_b64decode(d["signing_key"])
        exchange_bytes = standard_b64decode(d["exchange_key"])

        signing_key = Ed25519PrivateKey.from_private_bytes(signing_bytes)
        verify_key = signing_key.public_key()
        exchange_key = X25519PrivateKey.from_private_bytes(exchange_bytes)
        public_exchange = exchange_key.public_key()

        return cls(
            signing_key=signing_key,
            verify_key=verify_key,
            exchange_key=exchange_key,
            public_exchange=public_exchange,
            key_id=standard_b64decode(d["key_id"]),
        )
