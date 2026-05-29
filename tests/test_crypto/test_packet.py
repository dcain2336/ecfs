"""Tests for ecfs.crypto.packet — ECFSPacket serialisation and helpers."""

import hashlib
import struct
import time
import uuid
from datetime import datetime, timezone

import pytest

from ecfs.crypto.packet import ECFSPacket, PACKET_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_packet(**overrides) -> ECFSPacket:
    """Create a deterministic packet for testing."""
    defaults = dict(
        destination_hash=hashlib.sha256(b"peer").digest(),
        payload=b"hello-ecfs",
        ttl=3600,
        hop_count=0,
        signature=b"",
    )
    defaults.update(overrides)
    return ECFSPacket(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestECFSPacket:

    def test_round_trip(self):
        """Serialise → deserialise produces identical packet."""
        orig = _make_packet(
            session_id=uuid.uuid4(),
            signature=b"\x00" * 64,
            hop_count=3,
        )
        data = orig.to_bytes()
        restored = ECFSPacket.from_bytes(data)

        assert restored.message_id == orig.message_id
        assert restored.session_id == orig.session_id
        assert restored.ttl == orig.ttl
        assert restored.destination_hash == orig.destination_hash
        assert restored.hop_count == orig.hop_count
        assert restored.payload == orig.payload
        assert restored.signature == orig.signature
        # Timestamp precision: allow 1 ms rounding tolerance
        assert abs((restored.timestamp - orig.timestamp).total_seconds()) < 0.001

    def test_round_trip_no_session(self):
        """Round-trip works when session_id is None."""
        orig = _make_packet(session_id=None)
        data = orig.to_bytes()
        restored = ECFSPacket.from_bytes(data)
        assert restored.session_id is None
        assert restored.payload == orig.payload

    def test_version_byte(self):
        """Serialised data starts with PACKET_VERSION."""
        pkt = _make_packet()
        raw = pkt.to_bytes()
        assert raw[0] == PACKET_VERSION

    def test_is_expired_future(self):
        """Packet with future timestamp is not expired."""
        pkt = _make_packet(
            timestamp=datetime.now(timezone.utc),
            ttl=3600,
        )
        assert pkt.is_expired() is False

    def test_is_expired_past(self):
        """Packet with timestamp well in the past is expired."""
        pkt = _make_packet(
            timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ttl=3600,
        )
        assert pkt.is_expired() is True

    def test_is_expired_boundary(self):
        """Packet exactly at TTL boundary is expired (> ttl, not >=)."""
        pkt = _make_packet(
            timestamp=datetime.now(timezone.utc),
            ttl=1,
        )
        time.sleep(1.1)
        assert pkt.is_expired() is True

    def test_increment_hop(self):
        """increment_hop bumps hop_count and returns self."""
        pkt = _make_packet(hop_count=0)
        ret = pkt.increment_hop()
        assert ret is pkt
        assert pkt.hop_count == 1
        pkt.increment_hop().increment_hop()
        assert pkt.hop_count == 3

    def test_hash_determinism(self):
        """hash() returns the same SHA-256 for the same packet."""
        pkt = _make_packet()
        h1 = pkt.hash()
        h2 = pkt.hash()
        assert h1 == h2
        assert len(h1) == 32  # SHA-256

    def test_hash_differs_for_different_payloads(self):
        """Packets with different payloads have different hashes."""
        h1 = _make_packet(payload=b"aaa").hash()
        h2 = _make_packet(payload=b"bbb").hash()
        assert h1 != h2

    def test_tamper_detection(self):
        """Changing a field after hashing produces a different hash."""
        pkt = _make_packet()
        original_hash = pkt.hash()

        pkt.hop_count = 99
        tampered_hash = pkt.hash()
        assert original_hash != tampered_hash

    def test_from_bytes_too_short(self):
        """Deserialising truncated data raises ValueError."""
        with pytest.raises(ValueError, match="too short"):
            ECFSPacket.from_bytes(b"\x01\x02\x03")

    def test_from_bytes_bad_version(self):
        """Deserialising data with wrong version raises ValueError."""
        pkt = _make_packet()
        raw = bytearray(pkt.to_bytes())
        raw[0] = 99  # corrupt version
        with pytest.raises(ValueError, match="Unsupported packet version"):
            ECFSPacket.from_bytes(bytes(raw))

    def test_empty_payload(self):
        """Packet with empty payload serialises and round-trips."""
        pkt = _make_packet(payload=b"")
        restored = ECFSPacket.from_bytes(pkt.to_bytes())
        assert restored.payload == b""

    def test_large_payload(self):
        """Packet with 100 kB payload serialises correctly."""
        big = b"\xab" * 100_000
        pkt = _make_packet(payload=big)
        restored = ECFSPacket.from_bytes(pkt.to_bytes())
        assert restored.payload == big
