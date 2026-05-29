"""RFID/NFC transport for ECFS — tag-based sneakernet relay."""

import asyncio
import logging
from typing import Optional, Protocol

from ecfs.plugins.base import TransportPlugin, TransportStatus, TransportType

logger = logging.getLogger(__name__)


class RFIDInterface(Protocol):
    async def read(self, tag_id: str) -> bytes: ...
    async def write(self, tag_id: str, data: bytes) -> None: ...
    async def scan(self) -> list[dict]: ...
    async def close(self) -> None: ...


class MockRFID:
    """Mock RFID reader/writer for CI testing."""

    def __init__(self) -> None:
        self._tags: dict[str, bytes] = {}
        self._written: dict[str, bytes] = {}

    async def read(self, tag_id: str) -> bytes:
        return self._tags.get(tag_id, b"")

    async def write(self, tag_id: str, data: bytes) -> None:
        self._tags[tag_id] = data
        self._written[tag_id] = data

    async def scan(self) -> list[dict]:
        return [{"tag_id": tid, "type": "NTAG216"} for tid in self._tags]

    async def close(self) -> None:
        pass


class RFIDTransport(TransportPlugin):
    """RFID/NFC transport for ECFS.

    Uses NFC tags (NTAG216, MIFARE 1K) for physical sneakernet
    packet relay. Data is written to a tag, physically carried to
    the destination, and read back.
    """

    MAX_PACKET_SIZE = 144  # NTAG216 user memory
    TAG_SIZES = {
        "NTAG216": 888,  # Total usable memory
        "MIFARE_1K": 1024,
    }
    HEADER_SIZE = 4  # seq(2) + total(2) overhead per chunk

    def __init__(self, rfid: RFIDInterface = None, tag_type: str = "NTAG216") -> None:
        self._rfid = rfid or MockRFID()
        self._tag_type = tag_type
        self._status = TransportStatus.OFFLINE
        self._receive_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._sequence: int = 0

    @property
    def name(self) -> str:
        return "rfid"

    @property
    def transport_type(self) -> TransportType:
        return TransportType.PROXIMITY

    @property
    def priority(self) -> int:
        return 10  # Highest priority when available — very high bandwidth density

    @property
    def max_packet_size(self) -> int:
        return self.MAX_PACKET_SIZE

    async def initialize(self) -> None:
        self._status = TransportStatus.ONLINE
        self._sequence = 0
        logger.info("RFID transport initialized, tag_type=%s", self._tag_type)

    async def teardown(self) -> None:
        await self._rfid.close()
        self._status = TransportStatus.OFFLINE

    def _chunk_data(self, data: bytes) -> list[bytes]:
        """Split data into tag-sized chunks with headers."""
        payload_size = self.MAX_PACKET_SIZE - self.HEADER_SIZE
        chunks = []
        total = (len(data) + payload_size - 1) // payload_size
        for i in range(0, len(data), payload_size):
            chunk = data[i : i + payload_size]
            header = self._sequence.to_bytes(2, "big") + total.to_bytes(2, "big")
            chunks.append(header + chunk)
        self._sequence += 1
        return chunks

    async def write_tag(self, tag_id: str, data: bytes) -> bool:
        """Write packet data to an NFC tag."""
        if len(data) > self.MAX_PACKET_SIZE:
            logger.warning("Data too large for tag: %d bytes", len(data))
            return False
        try:
            await self._rfid.write(tag_id, data)
            return True
        except Exception:
            logger.exception("RFID write failed")
            return False

    async def read_tag(self, tag_id: str) -> Optional[bytes]:
        """Read packet data from an NFC tag."""
        try:
            return await self._rfid.read(tag_id)
        except Exception:
            logger.exception("RFID read failed")
            return None

    async def scan_tags(self) -> list[dict]:
        """Scan for available NFC tags."""
        try:
            return await self._rfid.scan()
        except Exception:
            logger.exception("RFID scan failed")
            return []

    async def send_packet(self, data: bytes) -> bool:
        if len(data) > self.max_packet_size * 10:
            logger.warning("Packet too large for RFID transport: %d bytes", len(data))
            return False
        try:
            chunks = self._chunk_data(data)
            tags = await self.scan_tags()
            if not tags:
                logger.warning("No tags available for RFID transport")
                return False
            tag_id = tags[0]["tag_id"]
            for i, chunk in enumerate(chunks):
                result = await self.write_tag(tag_id, chunk)
                if not result:
                    return False
            logger.debug("Wrote %d chunks to tag %s", len(chunks), tag_id)
            return True
        except Exception:
            logger.exception("RFID send failed")
            self._status = TransportStatus.ERROR
            return False

    async def receive_packet(self) -> Optional[bytes]:
        try:
            return self._receive_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def get_status(self) -> TransportStatus:
        return self._status

    def queue_received(self, data: bytes) -> None:
        """Queue a received packet from a tag read."""
        self._receive_queue.put_nowait(data)
