"""Bluetooth LE transport for ECFS — GATT service based packet exchange."""

import asyncio
import logging
from typing import Optional, Protocol

from ecfs.plugins.base import TransportPlugin, TransportStatus, TransportType

logger = logging.getLogger(__name__)


class BLEInterface(Protocol):
    async def start_advertising(self, service_uuid: str) -> None: ...
    async def stop_advertising(self) -> None: ...
    async def scan(self, duration: float) -> list[dict]: ...
    async def connect(self, address: str) -> None: ...
    async def writeCharacteristic(self, handle: int, data: bytes) -> None: ...
    async def readCharacteristic(self, handle: int) -> bytes: ...
    async def disconnect(self) -> None: ...
    @property
    def is_connected(self) -> bool: ...


class MockBLE:
    """Mock BLE for CI testing."""

    def __init__(self) -> None:
        self._connected = False
        self._advertising = False
        self._buffer: asyncio.Queue[bytes] = asyncio.Queue()
        self._written: list[bytes] = []

    async def start_advertising(self, service_uuid: str) -> None:
        self._advertising = True

    async def stop_advertising(self) -> None:
        self._advertising = False

    async def scan(self, duration: float) -> list[dict]:
        return []

    async def connect(self, address: str) -> None:
        self._connected = True

    async def writeCharacteristic(self, handle: int, data: bytes) -> None:
        self._written.append(data)
        await self._buffer.put(data)

    async def readCharacteristic(self, handle: int) -> bytes:
        return await self._buffer.get()

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


class BLETransport(TransportPlugin):
    """Bluetooth LE transport for ECFS.

    Short-range (~10m) but widely available.
    Uses GATT service for packet exchange.
    """

    ECFS_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
    PACKET_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"
    MAX_PACKET_SIZE = 512  # BLE MTU limit

    def __init__(self, ble: BLEInterface = None, address: str = None) -> None:
        self._ble = ble or MockBLE()
        self._address = address
        self._status = TransportStatus.OFFLINE
        self._receive_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._role: str = "peripheral"  # or "central"

    @property
    def name(self) -> str:
        return "ble"

    @property
    def transport_type(self) -> TransportType:
        return TransportType.RADIO

    @property
    def priority(self) -> int:
        return 25  # Higher priority than LoRa — faster but shorter range

    @property
    def max_packet_size(self) -> int:
        return self.MAX_PACKET_SIZE

    async def initialize(self) -> None:
        if self._role == "peripheral":
            await self._ble.start_advertising(self.ECFS_SERVICE_UUID)
        self._status = TransportStatus.ONLINE
        logger.info("BLE transport initialized, role=%s", self._role)

    async def teardown(self) -> None:
        if self._ble.is_connected:
            await self._ble.disconnect()
        if self._role == "peripheral":
            await self._ble.stop_advertising()
        self._status = TransportStatus.OFFLINE

    async def connect_to_peer(self, address: str) -> bool:
        """Central mode: connect to a peripheral."""
        try:
            await self._ble.connect(address)
            self._role = "central"
            return True
        except Exception:
            logger.exception("BLE connect failed")
            return False

    async def send_packet(self, data: bytes) -> bool:
        if len(data) > self.MAX_PACKET_SIZE:
            logger.warning("Packet too large for BLE: %d bytes", len(data))
            return False
        try:
            await self._ble.writeCharacteristic(self.PACKET_CHAR_UUID, data)
            return True
        except Exception:
            logger.exception("BLE send failed")
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
        self._receive_queue.put_nowait(data)
