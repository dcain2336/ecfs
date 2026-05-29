"""Core routing engine — decides HOW to send packets across transports."""

import asyncio
import logging
import time
from typing import Dict, List, Optional

from ecfs.core.dedup import DeduplicationCache
from ecfs.core.queue import MessagePriority, MessageQueue, QueuedMessage
from ecfs.plugins.base import TransportPlugin, TransportStatus

logger = logging.getLogger(__name__)


class RoutingStrategy:
    """Built-in routing strategy constants."""

    SHOTGUN = "shotgun"  # flood all plugins simultaneously
    SHORTEST = "shortest"  # prefer lowest-latency path
    ADAPTIVE = "adaptive"  # switch based on real-time conditions


class RoutingEngine:
    """Core routing engine. Decides HOW to send packets.

    The engine maintains a live view of available plugins and
    routes packets through the best available path(s).
    """

    MAX_HOPS = 30  # prevent infinite routing loops

    def __init__(
        self,
        plugins: List[TransportPlugin],
        strategy: str = RoutingStrategy.ADAPTIVE,
        dedup_cache_size: int = 10000,
        dedup_ttl: int = 7200,
        queue_max_size: int = 5000,
    ) -> None:
        self._plugins = {p.name: p for p in plugins}
        self._strategy = strategy
        self._dedup = DeduplicationCache(max_size=dedup_cache_size, ttl_seconds=dedup_ttl)
        self._queue = MessageQueue(max_size=queue_max_size)
        self._plugin_stats: Dict[str, _PluginStats] = {
            p.name: _PluginStats() for p in plugins
        }
        self._running = False

    async def start(self) -> None:
        """Initialize all plugins and start background health monitoring."""
        self._running = True
        for plugin in self._plugins.values():
            try:
                await plugin.initialize()
            except Exception:
                logger.exception("Failed to initialize plugin: %s", plugin.name)

    async def stop(self) -> None:
        """Shutdown all plugins."""
        self._running = False
        for plugin in self._plugins.values():
            try:
                await plugin.teardown()
            except Exception:
                logger.exception("Error tearing down: %s", plugin.name)

    async def send(
        self,
        data: bytes,
        packet_hash: bytes,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> bool:
        """Send data through available transports.

        1. Check dedup (skip if already seen)
        2. Check max hops (drop if too many)
        3. Route based on strategy
        """
        # Dedup check
        if self._dedup.check_and_add(packet_hash):
            logger.debug("Dropping duplicate packet %s", packet_hash[:8].hex())
            return False

        # Get online plugins
        online = await self._get_online_plugins()
        if not online:
            logger.warning("No online plugins available, queueing")
            await self._queue.enqueue(data, packet_hash, priority)
            return False

        # Route based on strategy
        if self._strategy == RoutingStrategy.SHOTGUN:
            return await self._send_shotgun(data, online)
        elif self._strategy == RoutingStrategy.SHORTEST:
            return await self._send_shortest(data, online)
        else:  # ADAPTIVE
            return await self._send_adaptive(data, online, priority)

    async def receive(self, plugin_name: Optional[str] = None) -> Optional[bytes]:
        """Receive a packet from any (or specific) plugin."""
        plugins = [self._plugins[plugin_name]] if plugin_name else self._plugins.values()
        for plugin in plugins:
            try:
                data = await plugin.receive_packet()
                if data is not None:
                    return data
            except Exception:
                logger.exception("Error receiving from %s", plugin.name)
        return None

    async def _send_shotgun(self, data: bytes, plugins: List[TransportPlugin]) -> bool:
        """Send to ALL online plugins simultaneously."""
        results = await asyncio.gather(
            *[self._send_via(p, data) for p in plugins],
            return_exceptions=True,
        )
        successes = sum(1 for r in results if r is True)
        return successes > 0

    async def _send_shortest(
        self, data: bytes, plugins: List[TransportPlugin]
    ) -> bool:
        """Send to the plugin with lowest estimated latency."""
        if plugins:
            best = min(
                plugins, key=lambda p: self._plugin_stats[p.name].avg_latency_ms
            )
            return await self._send_via(best, data)
        return False

    async def _send_adaptive(
        self,
        data: bytes,
        plugins: List[TransportPlugin],
        priority: MessagePriority,
    ) -> bool:
        """Send to top N plugins based on priority and health."""
        if priority == MessagePriority.CRITICAL:
            # Critical: shotgun to all
            return await self._send_shotgun(data, plugins)
        elif priority == MessagePriority.HIGH:
            # High: top 2 plugins
            return await self._send_shotgun(data, plugins[:2])
        else:
            # Normal/Low: best single plugin
            return await self._send_shortest(data, plugins)

    async def _send_via(self, plugin: TransportPlugin, data: bytes) -> bool:
        """Send through one plugin, tracking stats."""
        stats = self._plugin_stats[plugin.name]
        start = time.monotonic()
        try:
            success = await plugin.send_packet(data)
            elapsed_ms = (time.monotonic() - start) * 1000
            stats.record_send(success, elapsed_ms, len(data))
            return success
        except Exception:
            stats.record_send(False, 0, 0)
            logger.exception("Send failed via %s", plugin.name)
            return False

    async def _get_online_plugins(self) -> List[TransportPlugin]:
        """Get plugins that are currently available."""
        result = []
        for plugin in self._plugins.values():
            try:
                status = await plugin.get_status()
                if status in (TransportStatus.ONLINE, TransportStatus.DEGRADED):
                    result.append(plugin)
            except Exception:
                pass
        return sorted(result, key=lambda p: p.priority)

    def get_stats(self) -> Dict[str, dict]:
        """Return per-plugin statistics."""
        return {name: s.to_dict() for name, s in self._plugin_stats.items()}

    @property
    def dedup_cache(self) -> DeduplicationCache:
        return self._dedup

    @property
    def message_queue(self) -> MessageQueue:
        return self._queue


class _PluginStats:
    """Internal stats tracker for one plugin."""

    def __init__(self) -> None:
        self.sends_attempted: int = 0
        self.sends_succeeded: int = 0
        self.total_bytes: int = 0
        self.total_latency_ms: float = 0.0

    def record_send(self, success: bool, latency_ms: float, byte_count: int) -> None:
        self.sends_attempted += 1
        if success:
            self.sends_succeeded += 1
            self.total_bytes += byte_count
            # Exponential moving average
            self.total_latency_ms = self.total_latency_ms * 0.8 + latency_ms * 0.2

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms if self.sends_succeeded > 0 else float("inf")

    @property
    def success_rate(self) -> float:
        return (
            self.sends_succeeded / self.sends_attempted
            if self.sends_attempted > 0
            else 0.0
        )

    def to_dict(self) -> dict:
        return {
            "sends_attempted": self.sends_attempted,
            "sends_succeeded": self.sends_succeeded,
            "success_rate": round(self.success_rate, 3),
            "avg_latency_ms": round(self.total_latency_ms, 1),
            "total_bytes": self.total_bytes,
        }
