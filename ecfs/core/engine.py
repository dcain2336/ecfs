"""ECFS Engine — main orchestrator for packet routing.

Coordinates plugin lifecycle, message queuing, routing,
and deduplication.
"""

import asyncio
import logging
from typing import Optional

from ecfs.plugins.registry import PluginRegistry
from ecfs.core.routing import RoutingEngine
from ecfs.core.queue import MessageQueue
from ecfs.core.dedup import DeduplicationCache
from ecfs.plugins.base import TransportPlugin, TransportStatus
from ecfs.core.queue import MessagePriority

logger = logging.getLogger(__name__)


class ECFSEngine:
    """Main orchestrator for ECFS packet routing.

    Coordinates plugin lifecycle, message queuing, routing,
    and deduplication.
    """

    def __init__(self, enable_dedup: bool = True) -> None:
        self.registry = PluginRegistry()
        self.routing: Optional[RoutingEngine] = None
        self.queue = MessageQueue()
        self.dedup = DeduplicationCache() if enable_dedup else None
        self._running = False
        self._stats = {
            "packets_sent": 0,
            "packets_received": 0,
            "packets_dropped": 0,
            "packets_deduped": 0,
        }

    def register_plugin(self, plugin: TransportPlugin) -> None:
        """Register a transport plugin with the engine."""
        self.registry.register(plugin)

    def _rebuild_routing(self) -> None:
        """Rebuild the routing engine from registered plugins."""
        plugins = self.registry.get_all()
        if plugins:
            self.routing = RoutingEngine(plugins)

    async def start(self) -> None:
        """Initialize all registered plugins."""
        self._running = True
        for plugin in self.registry.get_all():
            try:
                await plugin.initialize()
                logger.info("Initialized plugin: %s", plugin.name)
            except Exception:
                logger.exception("Failed to initialize plugin: %s", plugin.name)

    async def stop(self) -> None:
        """Teardown all plugins."""
        self._running = False
        for plugin in self.registry.get_all():
            try:
                await plugin.teardown()
            except Exception:
                logger.exception("Failed to teardown plugin: %s", plugin.name)

    async def send(self, data: bytes, priority: int = 0) -> bool:
        """Send data through available transports.

        Checks dedup first, then tries all online plugins.
        If no plugins are online, queues the packet.
        """
        if self.dedup and self.dedup.contains(data):
            self._stats["packets_deduped"] += 1
            return False

        online_plugins = [
            p for p in self.registry.get_all()
            if (await p.get_status()) == TransportStatus.ONLINE
        ]
        if not online_plugins:
            logger.warning("No online plugins available, queuing packet")
            await self.queue.enqueue(data, message_id=data, priority=MessagePriority.NORMAL)
            self._stats["packets_dropped"] += 1
            return False

        results = []
        for plugin in online_plugins:
            try:
                success = await plugin.send_packet(data)
                results.append(success)
            except Exception:
                logger.exception("Send failed on %s", plugin.name)
                results.append(False)

        sent = any(results)
        if sent:
            self._stats["packets_sent"] += 1
            if self.dedup:
                self.dedup.add(data)

        return sent

    async def receive(self) -> Optional[bytes]:
        """Receive a packet from any plugin."""
        for plugin in self.registry.get_all():
            try:
                data = await plugin.receive_packet()
                if data is not None:
                    if self.dedup and self.dedup.contains(data):
                        self._stats["packets_deduped"] += 1
                        continue
                    self._stats["packets_received"] += 1
                    if self.dedup:
                        self.dedup.add(data)
                    return data
            except Exception:
                logger.exception("Receive failed on %s", plugin.name)
        return None

    @property
    def stats(self) -> dict:
        """Return current engine statistics."""
        return dict(self._stats)

    async def health_check(self) -> dict:
        """Check health of all plugins."""
        health = {}
        for plugin in self.registry.get_all():
            try:
                status = await plugin.get_status()
                health[plugin.name] = {
                    "status": status.value,
                    "type": plugin.transport_type.value,
                    "priority": plugin.priority,
                }
            except Exception:
                health[plugin.name] = {"status": "error"}
        return health

    @property
    def is_running(self) -> bool:
        """Whether the engine is currently running."""
        return self._running
