"""Steganographic HTTP transport for ECFS — covert data in web traffic metadata."""

import asyncio
import hashlib
import logging
import os
from typing import Optional

from ecfs.plugins.base import TransportPlugin, TransportStatus, TransportType

logger = logging.getLogger(__name__)


class SteganographicHTTP(TransportPlugin):
    """Steganographic HTTP transport for ECFS.

    Embeds ECFS packets in HTTP traffic metadata: custom headers,
    query parameters, and DNS subdomain patterns. Includes traffic
    padding to match normal web traffic sizes.
    """

    MAX_PACKET_SIZE = 4096
    MAX_HEADER_VALUE = 512  # Max bytes per header value
    MAX_DNS_LABEL = 63  # DNS label max length
    PADDING_TARGETS = [256, 512, 1024, 2048, 4096]

    def __init__(self) -> None:
        self._status = TransportStatus.OFFLINE
        self._receive_queue: asyncio.Queue[bytes] = asyncio.Queue()

    @property
    def name(self) -> str:
        return "stego"

    @property
    def transport_type(self) -> TransportType:
        return TransportType.COVERT

    @property
    def priority(self) -> int:
        return 45  # Covert — lower priority than standard transports

    @property
    def max_packet_size(self) -> int:
        return self.MAX_PACKET_SIZE

    async def initialize(self) -> None:
        self._status = TransportStatus.ONLINE
        logger.info("Steganographic HTTP transport initialized")

    async def teardown(self) -> None:
        self._status = TransportStatus.OFFLINE

    def encode_in_headers(self, data: bytes) -> dict[str, str]:
        """Encode packet data into fake HTTP headers.

        Splits data into chunks and encodes each in a custom X-ECFS-* header.
        Uses hex encoding for safety in HTTP header values.
        """
        import base64
        headers = {}
        # Split data into chunks that fit in headers
        chunk_size = self.MAX_HEADER_VALUE // 2  # hex encoding doubles size
        chunks = []
        for i in range(0, len(data), chunk_size):
            chunks.append(data[i : i + chunk_size])

        for i, chunk in enumerate(chunks):
            header_name = f"X-ECFS-{i:04d}"
            headers[header_name] = chunk.hex()

        return headers

    def decode_from_headers(self, headers: dict[str, str]) -> bytes:
        """Decode packet data from X-ECFS-* headers."""
        ecfs_headers = sorted(
            [(k, v) for k, v in headers.items() if k.startswith("X-ECFS-")],
            key=lambda x: x[0],
        )
        if not ecfs_headers:
            return b""

        data = bytearray()
        for _, value in ecfs_headers:
            try:
                data.extend(bytes.fromhex(value))
            except ValueError:
                logger.warning("Invalid hex in header %s", ecfs_headers[0][0])
                continue
        return bytes(data)

    def encode_in_dns(self, data: bytes) -> list[str]:
        """Encode data as DNS subdomain labels.

        Uses base64-like encoding split into DNS-safe label chunks.
        """
        import base64
        encoded = base64.b32encode(data).decode().lower().rstrip("=")
        labels = []
        for i in range(0, len(encoded), self.MAX_DNS_LABEL):
            labels.append(encoded[i : i + self.MAX_DNS_LABEL])
        return labels

    def decode_from_dns(self, labels: list[str]) -> bytes:
        """Decode DNS labels back to packet data."""
        import base64
        encoded = "".join(labels)
        # Re-add padding
        padding = (8 - len(encoded) % 8) % 8
        encoded += "=" * padding
        return base64.b32decode(encoded.upper())

    def pad_to_normal(self, data: bytes, target_size: int = None) -> bytes:
        """Pad data to match normal web traffic sizes.

        Adds random padding bytes preceded by a 4-byte length prefix
        so the receiver can strip it.
        """
        if target_size is None:
            # Find the smallest padding target that fits
            target_size = self.PADDING_TARGETS[0]
            for t in self.PADDING_TARGETS:
                if t >= len(data) + 4:
                    target_size = t
                    break
            else:
                target_size = max(self.PADDING_TARGETS[-1], len(data) + 4)

        # 4-byte length prefix + data + padding
        prefix = len(data).to_bytes(4, "big")
        padded = prefix + data
        if len(padded) < target_size:
            padding = os.urandom(target_size - len(padded))
            padded += padding
        return padded

    def unpad(self, padded_data: bytes) -> bytes:
        """Remove padding added by pad_to_normal."""
        if len(padded_data) < 4:
            return padded_data
        length = int.from_bytes(padded_data[:4], "big")
        return padded_data[4 : 4 + length]

    def calculate_chi_squared(self, encrypted_data: bytes) -> float:
        """Calculate chi-squared statistic for data randomness.

        Returns ~0.0 for truly random data, higher (~1.0) for structured data.
        Normalized by N*num_bins so results fall in [0, 1] range.
        """
        if not encrypted_data:
            return 0.0

        # Count byte frequencies
        counts = [0] * 256
        for byte in encrypted_data:
            counts[byte] += 1

        # Expected frequency for uniform distribution
        expected = len(encrypted_data) / 256.0

        # Chi-squared calculation
        chi_sq = 0.0
        for count in counts:
            if expected > 0:
                chi_sq += ((count - expected) ** 2) / expected

        # Normalize so random data → ~0.0, structured data → ~1.0
        # chi_sq for uniform random ≈ df (255), for max skew ≈ N * 255
        # Dividing by (N * 256) maps: 0 → 0.0, uniform → ~0.001, max → ~1.0
        return chi_sq / (len(encrypted_data) * 256.0)

    async def send_packet(self, data: bytes) -> bool:
        if len(data) > self.MAX_PACKET_SIZE:
            logger.warning("Packet too large for stego transport: %d bytes", len(data))
            return False
        try:
            # Pad data to look like normal traffic
            padded = self.pad_to_normal(data)
            # Encode in headers
            headers = self.encode_in_headers(padded)
            # Store for receive simulation
            decoded = self.decode_from_headers(headers)
            self._receive_queue.put_nowait(self.unpad(decoded))
            logger.debug("Sent stego packet with %d headers", len(headers))
            return True
        except Exception:
            logger.exception("Stego send failed")
            self._status = TransportStatus.ERROR
            return False

    async def receive_packet(self) -> Optional[bytes]:
        try:
            return self._receive_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def get_status(self) -> TransportStatus:
        return self._status
