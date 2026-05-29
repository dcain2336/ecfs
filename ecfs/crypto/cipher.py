"""AES-256-GCM encryption helpers and session key rotation for ECFS.

All ciphertext is prefixed with a 12-byte random nonce.  Key rotation uses
HKDF to derive a fresh 32-byte key from the previous session key.
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def encrypt_packet_payload(payload: bytes, key: bytes) -> bytes:
    """Encrypt *payload* with AES-256-GCM.

    Returns ``nonce(12) || ciphertext || tag(16)``.
    """
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, payload, None)
    return nonce + ct


def decrypt_packet_payload(encrypted: bytes, key: bytes) -> bytes:
    """Decrypt AES-256-GCM data produced by :func:`encrypt_packet_payload`.

    Raises ``cryptography.exceptions.InvalidTag`` on tampered data.
    """
    nonce = encrypted[:12]
    ct = encrypted[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None)


def rotate_session_key(old_key: bytes, salt: bytes | None = None) -> bytes:
    """Derive a fresh 32-byte session key from *old_key* using HKDF.

    If *salt* is not provided a random 16-byte salt is generated.
    """
    if salt is None:
        salt = os.urandom(16)
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"ecfs-session-rotate",
    )
    return hkdf.derive(old_key)
