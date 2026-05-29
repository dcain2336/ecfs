"""LoRa radio transport for ECFS — Meshtastic-compatible over serial."""

import asyncio
import logging
from typing import Optional, Protocol

from ecfs.plugins.base import TransportPlugin, TransportStatus, TransportType

logger = logging.getLogger(__name__)


class SerialInterface(Protocol):
    async def write(self, data: bytes) -> None: ...
    async def read(self, n: int) -> bytes: ...
    async def close(self) -> None: ...


class MockSerial:
    """Mock serial for CI testing."""

    def __init__(self) -> None:
        self._buffer: asyncio.Queue[bytes] = asyncio.Queue()

    async def write(self, data: bytes) -> None:
        await self._buffer.put(data)

    async def read(self, n: int) -> bytes:
        return await self._buffer.get()

    async def close(self) -> None:
        pass


class LoRaTransport(TransportPlugin):
    """LoRa radio transport for ECFS.

    Uses Meshtastic-compatible protocol over serial.
    Bandwidth-limited (~250 bytes/packet) but long-range.
    """

    MAX_PACKET_SIZE = 237  # LoRa MTU minus headers
    CHUNK_SIZE = 200  # Safe payload per chunk

    def __init__(self, serial: SerialInterface = None, port: str = None) -> None:
        self._serial = serial or MockSerial()
        self._port = port
        self._status = TransportStatus.OFFLINE
        self._receive_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._sequence: int = 0

    @property
    def name(self) -> str:
        return "lora"

    @property
    def transport_type(self) -> TransportType:
        return TransportType.RADIO

    @property
    def priority(self) -> int:
        return 30  # Medium priority — slow but reliable

    @property
    def max_packet_size(self) -> int:
        return self.CHUNK_SIZE

    async def initialize(self) -> None:
        self._status = TransportStatus.ONLINE
        self._sequence = 0
        logger.info("LoRa transport initialized, port=%s", self._port)

    async def teardown(self) -> None:
        await self._serial.close()
        self._status = TransportStatus.OFFLINE

    def _chunk_data(self, data: bytes) -> list[bytes]:
        """Split data into LoRa-sized chunks with headers."""
        chunks = []
        total = (len(data) + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE
        for i in range(0, len(data), self.CHUNK_SIZE):
            chunk = data[i : i + self.CHUNK_SIZE]
            # Header: seq(2) + total(2) + chunk_data
            header = self._sequence.to_bytes(2, "big") + total.to_bytes(2, "big")
            chunks.append(header + chunk)
        self._sequence += 1
        return chunks

    async def send_packet(self, data: bytes) -> bool:
        if len(data) > self.max_packet_size * 10:  # Allow multi-chunk up to 10 chunks
            logger.warning("Packet too large for LoRa: %d bytes", len(data))
            return False
        try:
            chunks = self._chunk_data(data)
            for chunk in chunks:
                await self._serial.write(chunk)
            logger.debug("Sent %d LoRa chunks", len(chunks))
            return True
        except Exception:
            logger.exception("LoRa send failed")
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
        """Queue a received packet from the serial listener."""
        self._receive_queue.put_nowait(data)
