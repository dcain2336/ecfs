import asyncio
import hashlib
import logging
import time
from typing import Callable, Optional
from ecfs.core.engine import ECFSEngine
from ecfs.discovery.hardware import HardwareProfile, detect_hardware_async
from ecfs.discovery.transport_factory import create_transports
from ecfs.plugins.base import TransportPlugin

logger = logging.getLogger(__name__)


class MeshNode:
    """A single ECFS node that auto-discovers and connects.

    Usage::

        node = MeshNode(name='laptop')
        await node.start()
        await node.send(b'hello to any nearby device')
        data = await node.receive()
    """

    def __init__(self, name: str = 'ecfs-node'):
        self.name = name
        self.node_id = hashlib.sha256(name.encode()).hexdigest()[:16]
        self._engine = ECFSEngine(enable_dedup=True)
        self._profile: Optional[HardwareProfile] = None
        self._running = False
        self._message_handlers: list[Callable] = []

    async def start(self) -> dict:
        """Auto-detect hardware, create transports, start engine.

        Returns a status dict with what was discovered.
        """
        self._profile = await detect_hardware_async()

        transports = create_transports(self._profile)

        for t in transports:
            self._engine.register_plugin(t)

        await self._engine.start()
        self._running = True

        status = {
            'node_id': self.node_id,
            'name': self.name,
            'hardware': self._profile.summary(),
            'transports': [t.name for t in transports],
            'transport_count': len(transports),
        }
        logger.info('Mesh node %s started: %s', self.name, status)
        return status

    async def stop(self) -> None:
        """Stop all transports."""
        self._running = False
        await self._engine.stop()

    async def send(self, data: bytes, priority: int = 0) -> bool:
        """Send data to any reachable peer. Uses shotgun routing —
        sends on ALL available transports simultaneously."""
        return await self._engine.send(data, priority=priority)

    async def receive(self) -> Optional[bytes]:
        """Receive data from any transport."""
        return await self._engine.receive()

    async def health(self) -> dict:
        """Check which transports are online."""
        return await self._engine.health_check()

    @property
    def stats(self) -> dict:
        return self._engine.stats
