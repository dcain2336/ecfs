"""Tests for ecfs.crypto.keys — ECFSKeyPair generation, signing, agreement."""

import hashlib

import pytest

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey

from ecfs.crypto.keys import ECFSKeyPair


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestECFSKeyPair:

    def test_generate_unique_keys(self):
        """Two generate() calls produce distinct keypairs."""
        kp1 = ECFSKeyPair.generate()
        kp2 = ECFSKeyPair.generate()
        assert kp1.key_id != kp2.key_id
        assert kp1.signing_key != kp2.signing_key
        assert kp1.exchange_key != kp2.exchange_key

    def test_sign_and_verify(self):
        """sign() → verify_signature() round-trips correctly."""
        kp = ECFSKeyPair.generate()
        msg = b"emergency-message-42"
        sig = kp.sign(msg)
        assert kp.verify_signature(msg, sig) is True

    def test_verify_rejects_tampered_data(self):
        """Signature fails verification when data is altered."""
        kp = ECFSKeyPair.generate()
        sig = kp.sign(b"original")
        assert kp.verify_signature(b"tampered", sig) is False

    def test_verify_rejects_wrong_key(self):
        """Signature from key A is rejected by key B."""
        kp_a = ECFSKeyPair.generate()
        kp_b = ECFSKeyPair.generate()
        sig = kp_a.sign(b"secret")
        assert kp_b.verify_signature(b"secret", sig) is False

    def test_derive_shared_secret(self):
        """Two keypairs derive the same shared secret via X25519 ECDH."""
        alice = ECFSKeyPair.generate()
        bob = ECFSKeyPair.generate()

        secret_a = alice.derive_shared_secret(bob.public_exchange)
        secret_b = bob.derive_shared_secret(alice.public_exchange)

        assert secret_a == secret_b
        assert len(secret_a) == 32

    def test_derive_shared_secret_different_peers(self):
        """Different peers produce different shared secrets."""
        alice = ECFSKeyPair.generate()
        bob1 = ECFSKeyPair.generate()
        bob2 = ECFSKeyPair.generate()

        s1 = alice.derive_shared_secret(bob1.public_exchange)
        s2 = alice.derive_shared_secret(bob2.public_exchange)
        assert s1 != s2

    def test_destination_hash_deterministic(self):
        """public_destination_hash() is stable across calls."""
        kp = ECFSKeyPair.generate()
        h1 = kp.public_destination_hash()
        h2 = kp.public_destination_hash()
        assert h1 == h2
        assert len(h1) == 32  # SHA-256 output

    def test_destination_hash_differs_per_key(self):
        """Different keys produce different destination hashes."""
        h1 = ECFSKeyPair.generate().public_destination_hash()
        h2 = ECFSKeyPair.generate().public_destination_hash()
        assert h1 != h2

    def test_to_dict_round_trip(self):
        """to_dict() → from_dict() restores the keypair exactly."""
        orig = ECFSKeyPair.generate()
        d = orig.to_dict()

        restored = ECFSKeyPair.from_dict(d)

        # Signing key matches
        test_msg = b"round-trip-test"
        sig = orig.sign(test_msg)
        assert restored.verify_signature(test_msg, sig) is True

        # Exchange key produces same shared secret
        peer = ECFSKeyPair.generate()
        s_orig = orig.derive_shared_secret(peer.public_exchange)
        s_restored = restored.derive_shared_secret(peer.public_exchange)
        assert s_orig == s_restored

        # key_id and dest hash match
        assert restored.key_id == orig.key_id
        assert restored.public_destination_hash() == orig.public_destination_hash()

    def test_key_id_is_first_8_bytes_of_hash(self):
        """key_id matches first 8 bytes of SHA-256(verify_key)."""
        from cryptography.hazmat.primitives import serialization as _ser

        kp = ECFSKeyPair.generate()
        raw_pub = kp.verify_key.public_bytes(
            _ser.Encoding.Raw,
            _ser.PublicFormat.Raw,
        )
        full_hash = hashlib.sha256(raw_pub).digest()
        assert kp.key_id == full_hash[:8]
