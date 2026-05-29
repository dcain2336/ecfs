"""HTTP/HTTPS transport for ECFS packets."""

import asyncio
import logging
from typing import Optional

import httpx

from ecfs.plugins.base import TransportPlugin, TransportStatus, TransportType

logger = logging.getLogger(__name__)


class InternetTransport(TransportPlugin):
    """HTTP/HTTPS transport for ECFS packets.

    Sends packets via HTTP POST to a relay server.
    Can also act as a relay server receiving packets.
    """

    def __init__(self, relay_url: str = None, timeout: float = 30.0) -> None:
        self._relay_url = relay_url
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._receive_queue: asyncio.Queue = asyncio.Queue()
        self._status = TransportStatus.OFFLINE

    @property
    def name(self) -> str:
        return "internet"

    @property
    def transport_type(self) -> TransportType:
        return TransportType.INTERNET

    @property
    def priority(self) -> int:
        return 10  # High priority — fastest transport

    @property
    def max_packet_size(self) -> int:
        return 1_048_576  # 1MB — HTTP can handle large payloads

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self._status = TransportStatus.ONLINE
        logger.info("Internet transport initialized, relay=%s", self._relay_url)

    async def teardown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._status = TransportStatus.OFFLINE

    async def send_packet(self, data: bytes) -> bool:
        if not self._client or not self._relay_url:
            return False
        try:
            resp = await self._client.post(
                self._relay_url,
                content=data,
                headers={"Content-Type": "application/octet-stream"},
            )
            return resp.status_code == 200
        except Exception:
            logger.exception("HTTP send failed")
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
        """For server mode: queue a received packet."""
        self._receive_queue.put_nowait(data)
