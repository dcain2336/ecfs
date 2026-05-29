from collections import deque
from typing import Optional

from ecfs.plugins.base import TransportPlugin, TransportStatus, TransportType


class NullTransport(TransportPlugin):
    """Mock transport for testing the core engine without real hardware.

    Sent packets are stored in an internal list. Receive pops from a
    pre-loaded queue, allowing test setup to inject incoming packets.
    """

    def __init__(
        self,
        name: str = "null",
        priority: int = 999,
        status: TransportStatus = TransportStatus.ONLINE,
    ) -> None:
        self._name = name
        self._priority = priority
        self._status_override: TransportStatus = status
        self._sent: list[bytes] = []
        self._receive_queue: deque[bytes] = deque()

    @property
    def name(self) -> str:
        return self._name

    @property
    def transport_type(self) -> TransportType:
        return TransportType.COVERT

    @property
    def priority(self) -> int:
        return self._priority

    async def initialize(self) -> None:
        pass

    async def teardown(self) -> None:
        self._sent.clear()
        self._receive_queue.clear()

    async def get_status(self) -> TransportStatus:
        return self._status_override

    async def send_packet(self, data: bytes) -> bool:
        if self._status_override == TransportStatus.OFFLINE:
            return False
        self._sent.append(data)
        return True

    async def receive_packet(self) -> Optional[bytes]:
        if self._receive_queue:
            return self._receive_queue.popleft()
        return None

    def queue_packet(self, data: bytes) -> None:
        """Add a packet to the receive queue (for test setup)."""
        self._receive_queue.append(data)

    @property
    def sent_packets(self) -> list[bytes]:
        """Inspect what was sent."""
        return list(self._sent)
