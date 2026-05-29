"""ECFSPacket — binary-serializable packet for ECFS message transport.

Binary format (little-endian):
    version        1 byte   (PACKET_VERSION)
    msg_id        16 bytes  (UUID4)
    session_id    16 bytes  (UUID4, nil-padded)
    ttl            4 bytes  (uint32, seconds)
    dest_hash     32 bytes  (SHA-256 of recipient public key)
    hop_count      2 bytes  (uint16)
    timestamp      8 bytes  (float64, seconds since epoch)
    payload_len    4 bytes  (uint32)
    payload        N bytes  (encrypted data)
    sig_len        2 bytes  (uint16)
    sig            M bytes  (Ed25519 signature)
"""

from __future__ import annotations

import hashlib
import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

PACKET_VERSION: int = 1

# struct helpers
_HDR_FMT = "<1s16s16sI32sHd"  # ver, msg_id, session_id, ttl, dest_hash, hops, ts
_HDR_SIZE = struct.calcsize(_HDR_FMT)  # 81 bytes
_UINT32 = struct.Struct("<I")
_UINT16 = struct.Struct("<H")


@dataclass
class ECFSPacket:
    """An ECFS network packet with binary serialisation support."""

    destination_hash: bytes  # 32 bytes – SHA-256 of recipient public key
    payload: bytes           # encrypted payload
    message_id: uuid.UUID = field(default_factory=uuid.uuid4)
    ttl: int = 3600
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    hop_count: int = 0
    signature: bytes = b""
    session_id: uuid.UUID | None = None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Canonical little-endian binary representation."""
        ts_epoch = self.timestamp.timestamp()
        sid_bytes = self.session_id.bytes if self.session_id else b"\x00" * 16

        header = struct.pack(
            _HDR_FMT,
            PACKET_VERSION.to_bytes(1, "little"),
            self.message_id.bytes,
            sid_bytes,
            self.ttl,
            self.destination_hash,
            self.hop_count,
            ts_epoch,
        )

        payload_len_bytes = _UINT32.pack(len(self.payload))
        sig_len_bytes = _UINT16.pack(len(self.signature))

        return header + payload_len_bytes + self.payload + sig_len_bytes + self.signature

    @classmethod
    def from_bytes(cls, data: bytes) -> "ECFSPacket":
        """Deserialise from the canonical binary format."""
        if len(data) < _HDR_SIZE + 4 + 2:  # header + payload_len + sig_len minimum
            raise ValueError("Packet data too short")

        (
            ver_byte,
            msg_id_raw,
            sid_raw,
            ttl,
            dest_hash,
            hop_count,
            ts_epoch,
        ) = struct.unpack(_HDR_FMT, data[:_HDR_SIZE])

        version = int.from_bytes(ver_byte, "little")
        if version != PACKET_VERSION:
            raise ValueError(f"Unsupported packet version {version}")

        payload_len = _UINT32.unpack_from(data, _HDR_SIZE)[0]
        offset = _HDR_SIZE + 4

        payload = data[offset : offset + payload_len]
        offset += payload_len

        sig_len = _UINT16.unpack_from(data, offset)[0]
        offset += 2
        signature = data[offset : offset + sig_len]

        session_id = uuid.UUID(bytes=sid_raw) if sid_raw != b"\x00" * 16 else None

        return cls(
            message_id=uuid.UUID(bytes=msg_id_raw),
            ttl=ttl,
            destination_hash=dest_hash,
            payload=payload,
            timestamp=datetime.fromtimestamp(ts_epoch, tz=timezone.utc),
            hop_count=hop_count,
            signature=signature,
            session_id=session_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_expired(self) -> bool:
        """Return True if the packet's TTL has elapsed."""
        elapsed = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        return elapsed > self.ttl

    def increment_hop(self) -> "ECFSPacket":
        """Increment hop_count and return *self* for chaining."""
        self.hop_count += 1
        return self

    def hash(self) -> bytes:
        """SHA-256 of the serialised packet (used for dedup)."""
        return hashlib.sha256(self.to_bytes()).digest()
