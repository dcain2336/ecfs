"""Packet fragmentation and reassembly for ECFS.

Breaks large messages into numbered fragments that can be shot across
different transports simultaneously and reassembled at the destination.
Each fragment carries enough metadata to survive independent delivery.
"""

import hashlib
import struct
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Fragment header: version(1) + msg_id(16) + frag_idx(2) + frag_total(2) + total_size(4) + timestamp(8) + origin(32)
# Total header: 65 bytes
HEADER_FORMAT = "!B16sHHI d 32s"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
CURRENT_VERSION = 1

# Max payload per fragment (conservative to fit LoRa's 255-byte limit minus crypto overhead)
DEFAULT_MAX_FRAGMENT_SIZE = 128


@dataclass
class Fragment:
    """A single fragment of a larger message."""

    version: int
    message_id: bytes  # 16-byte UUID
    fragment_index: int
    fragment_total: int
    total_size: int
    timestamp: float
    origin: bytes  # 32-byte node ID
    payload: bytes

    def encode(self) -> bytes:
        """Serialize fragment to bytes for transmission."""
        header = struct.pack(
            HEADER_FORMAT,
            self.version,
            self.message_id,
            self.fragment_index,
            self.fragment_total,
            self.total_size,
            self.timestamp,
            self.origin,
        )
        return header + self.payload

    @classmethod
    def decode(cls, data: bytes) -> "Fragment":
        """Deserialize a fragment from bytes."""
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Fragment too small: {len(data)} bytes, need {HEADER_SIZE}")

        (
            version,
            message_id,
            frag_idx,
            frag_total,
            total_size,
            timestamp,
            origin,
        ) = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])

        payload = data[HEADER_SIZE:]
        return cls(
            version=version,
            message_id=message_id,
            fragment_index=frag_idx,
            fragment_total=frag_total,
            total_size=total_size,
            timestamp=timestamp,
            origin=origin,
            payload=payload,
        )

    @property
    def fragment_hash(self) -> bytes:
        """Hash for deduplication — same fragment from different transports gets deduped."""
        return hashlib.sha256(
            self.message_id + struct.pack("!H", self.fragment_index)
        ).digest()[:16]


@dataclass
class IncomingMessage:
    """Tracks reassembly state for a fragmented message being received."""

    message_id: bytes
    total_fragments: int
    total_size: int
    origin: bytes
    timestamp: float
    received_fragments: Dict[int, bytes] = field(default_factory=dict)
    first_received_at: float = 0.0
    last_received_at: float = 0.0

    @property
    def is_complete(self) -> bool:
        return len(self.received_fragments) >= self.total_fragments

    @property
    def completeness_ratio(self) -> float:
        return len(self.received_fragments) / self.total_fragments if self.total_fragments > 0 else 0.0

    @property
    def age_seconds(self) -> float:
        """How long we've been collecting fragments."""
        if self.first_received_at == 0:
            return 0.0
        return time.time() - self.first_received_at

    def add_fragment(self, frag: Fragment) -> bool:
        """Add a fragment. Returns True if this is a new fragment."""
        if frag.fragment_index in self.received_fragments:
            return False  # duplicate

        self.received_fragments[frag.fragment_index] = frag.payload

        if self.first_received_at == 0:
            self.first_received_at = frag.timestamp
        self.last_received_at = frag.timestamp

        return True

    def reassemble(self) -> Optional[bytes]:
        """Reassemble the complete message if all fragments arrived."""
        if not self.is_complete:
            return None

        parts = []
        for i in range(self.total_fragments):
            if i not in self.received_fragments:
                return None  # shouldn't happen if is_complete, but guard
            parts.append(self.received_fragments[i])

        return b"".join(parts)


class FragmentManager:
    """Manages fragmentation for outgoing messages and reassembly for incoming ones.

    This is the core of the 'virus-like' movement: large messages are broken
    into fragments that can each take different paths (LoRa, BLE, internet, etc.)
    and reassemble at the destination regardless of order or delivery method.
    """

    def __init__(
        self,
        node_id: bytes,
        max_fragment_size: int = DEFAULT_MAX_FRAGMENT_SIZE,
        reassembly_timeout: float = 300.0,  # 5 minutes
        max_pending_messages: int = 100,
    ) -> None:
        self.node_id = node_id[:32].ljust(32, b"\x00") if len(node_id) < 32 else node_id[:32]
        self.max_fragment_size = max_fragment_size
        self.reassembly_timeout = reassembly_timeout
        self._pending: Dict[bytes, IncomingMessage] = {}  # message_id → reassembly state
        self._stats = {
            "fragmented": 0,
            "reassembled": 0,
            "expired": 0,
            "total_fragments_out": 0,
            "total_fragments_in": 0,
        }

    def fragment(self, data: bytes, message_id: Optional[bytes] = None) -> List[Fragment]:
        """Break data into fragments for transmission.

        Each fragment is self-contained: it carries enough metadata
        for any transport to deliver it independently.
        """
        if message_id is None:
            message_id = hashlib.sha256(data + str(time.time()).encode()).digest()[:16]

        total_size = len(data)
        fragments = []

        for i in range(0, total_size, self.max_fragment_size):
            chunk = data[i : i + self.max_fragment_size]
            frag_idx = i // self.max_fragment_size
            frag = Fragment(
                version=CURRENT_VERSION,
                message_id=message_id,
                fragment_index=frag_idx,
                fragment_total=0,  # filled below
                total_size=total_size,
                timestamp=time.time(),
                origin=self.node_id,
                payload=chunk,
            )
            fragments.append(frag)

        # Set total fragment count
        for frag in fragments:
            frag.fragment_total = len(fragments)

        self._stats["fragmented"] += 1
        self._stats["total_fragments_out"] += len(fragments)

        return fragments

    def receive_fragment(self, frag: Fragment) -> Optional[bytes]:
        """Process an incoming fragment.

        Returns the complete reassembled message when all fragments arrive,
        or None if still collecting.
        """
        # Expire stale reassembly states
        self._expire_stale()

        mid = frag.message_id

        if mid not in self._pending:
            self._pending[mid] = IncomingMessage(
                message_id=mid,
                total_fragments=frag.fragment_total,
                total_size=frag.total_size,
                origin=frag.origin,
                timestamp=frag.timestamp,
            )

        msg = self._pending[mid]
        msg.add_fragment(frag)
        self._stats["total_fragments_in"] += 1

        if msg.is_complete:
            assembled = msg.reassemble()
            del self._pending[mid]
            self._stats["reassembled"] += 1
            return assembled

        return None

    def _expire_stale(self) -> None:
        """Remove reassembly states that have timed out."""
        now = time.time()
        expired = [
            mid
            for mid, msg in self._pending.items()
            if now - msg.last_received_at > self.reassembly_timeout
            if msg.last_received_at > 0
        ]
        for mid in expired:
            del self._pending[mid]
            self._stats["expired"] += 1

    def get_pending_info(self) -> List[dict]:
        """Return info about messages currently being reassembled."""
        return [
            {
                "message_id": mid.hex(),
                "fragments_received": len(msg.received_fragments),
                "fragments_total": msg.total_fragments,
                "completeness": round(msg.completeness_ratio * 100, 1),
                "age_seconds": round(msg.age_seconds, 1),
            }
            for mid, msg in self._pending.items()
        ]

    @property
    def stats(self) -> dict:
        return dict(self._stats)
