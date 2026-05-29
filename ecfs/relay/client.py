"""Relay client for ECFS relay servers."""

import struct
import asyncio
import logging

logger = logging.getLogger(__name__)


class RelayClient:
    """Client for ECFS relay servers."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader = None
        self._writer: asyncio.StreamWriter = None

    async def connect(self) -> bool:
        """Connect to the relay server."""
        try:
            self._reader, self._writer = await asyncio.open_connection(
                self._host, self._port
            )
            return True
        except Exception:
            logger.exception("Failed to connect to relay")
            return False

    async def send(self, data: bytes) -> bool:
        """Send a length-prefixed packet to the relay."""
        if not self._writer:
            return False
        try:
            length = struct.pack('>I', len(data))
            self._writer.write(length + data)
            await self._writer.drain()
            return True
        except Exception:
            logger.exception("Relay send failed")
            return False

    async def receive(self) -> bytes:
        """Receive a length-prefixed packet from the relay."""
        if not self._reader:
            return b''
        try:
            length_bytes = await self._reader.readexactly(4)
            length = struct.unpack('>I', length_bytes)[0]
            data = await self._reader.readexactly(length)
            return data
        except Exception:
            logger.exception("Relay receive failed")
            return b''

    async def close(self) -> None:
        """Close the relay connection."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None

    @property
    def is_connected(self) -> bool:
        """Whether the client is currently connected."""
        return self._writer is not None
