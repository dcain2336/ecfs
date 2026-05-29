"""Tests for ecfs.crypto.cipher — AES-256-GCM encrypt/decrypt and key rotation."""

import os

import pytest
from cryptography.exceptions import InvalidTag

from ecfs.crypto.cipher import (
    decrypt_packet_payload,
    encrypt_packet_payload,
    rotate_session_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_key() -> bytes:
    return os.urandom(32)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEncryptDecrypt:

    def test_round_trip(self):
        """Encrypt then decrypt returns the original plaintext."""
        key = _random_key()
        plaintext = b"emergency payload \x00\x01\x02"
        ct = encrypt_packet_payload(plaintext, key)
        assert ct != plaintext
        assert decrypt_packet_payload(ct, key) == plaintext

    def test_nonce_is_random(self):
        """Two encryptions of the same plaintext produce different ciphertexts."""
        key = _random_key()
        pt = b"identical"
        ct1 = encrypt_packet_payload(pt, key)
        ct2 = encrypt_packet_payload(pt, key)
        assert ct1 != ct2

    def test_ciphertext_prefix_length(self):
        """Output starts with 12-byte nonce."""
        key = _random_key()
        ct = encrypt_packet_payload(b"data", key)
        assert len(ct[:12]) == 12

    def test_rejects_wrong_key(self):
        """Decryption with wrong key raises InvalidTag."""
        key1 = _random_key()
        key2 = _random_key()
        ct = encrypt_packet_payload(b"secret", key1)
        with pytest.raises(InvalidTag):
            decrypt_packet_payload(ct, key2)

    def test_decrypt_rejects_tampered(self):
        """Flipping a byte in the ciphertext causes InvalidTag."""
        key = _random_key()
        ct = bytearray(encrypt_packet_payload(b"payload", key))
        # Flip a byte near the end (inside the ciphertext/tag region)
        ct[-5] ^= 0xFF
        with pytest.raises(InvalidTag):
            decrypt_packet_payload(bytes(ct), key)

    def test_empty_payload(self):
        """Empty plaintext round-trips correctly."""
        key = _random_key()
        ct = encrypt_packet_payload(b"", key)
        assert decrypt_packet_payload(ct, key) == b""

    def test_large_payload(self):
        """100 kB payload encrypts and decrypts correctly."""
        key = _random_key()
        pt = os.urandom(100_000)
        ct = encrypt_packet_payload(pt, key)
        assert decrypt_packet_payload(ct, key) == pt


class TestRotateSessionKey:

    def test_produces_different_key(self):
        """Rotated key differs from the original."""
        old = _random_key()
        new = rotate_session_key(old)
        assert new != old
        assert len(new) == 32

    def test_deterministic_with_same_salt(self):
        """Same salt yields the same rotated key."""
        old = _random_key()
        salt = os.urandom(16)
        r1 = rotate_session_key(old, salt=salt)
        r2 = rotate_session_key(old, salt=salt)
        assert r1 == r2

    def test_different_salts_yield_different_keys(self):
        """Different salts yield different rotated keys."""
        old = _random_key()
        r1 = rotate_session_key(old, salt=os.urandom(16))
        r2 = rotate_session_key(old, salt=os.urandom(16))
        assert r1 != r2
