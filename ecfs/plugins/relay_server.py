"""Simple async TCP relay server for ECFS packets."""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RelayServer:
    """Simple async TCP relay server for ECFS packets.

    Accepts connections and stores received packets.
    Lightweight — no framework dependency.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 7700) -> None:
        self._host = host
        self._port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self._receive_queue: asyncio.Queue = asyncio.Queue()
        self._connected: set = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, self._host, self._port
        )
        logger.info("Relay server listening on %s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self._connected.clear()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        addr = writer.get_extra_info("peername")
        self._connected.add(addr)
        logger.info("Client connected: %s", addr)
        try:
            while True:
                # Read length-prefixed packet
                length_bytes = await reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")
                if length > 10 * 1024 * 1024:  # 10MB max
                    break
                data = await reader.readexactly(length)
                await self._receive_queue.put(data)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            self._connected.discard(addr)
            writer.close()
            logger.info("Client disconnected: %s", addr)

    async def receive(self) -> Optional[bytes]:
        try:
            return self._receive_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    @property
    def active_connections(self) -> int:
        return len(self._connected)
