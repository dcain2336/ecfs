from typing import Dict, List, Optional, Type
from ecfs.plugins.base import TransportPlugin, TransportStatus, TransportType
import asyncio
import logging

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Manages registered transport plugins.

    Plugins register by type. The routing engine queries this
    registry to find available transports.
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, TransportPlugin] = {}
        self._initialized: Dict[str, bool] = {}

    def register(self, plugin: TransportPlugin) -> None:
        """Register a plugin instance."""
        if plugin.name in self._plugins:
            raise ValueError(f"Plugin '{plugin.name}' already registered")
        self._plugins[plugin.name] = plugin
        self._initialized[plugin.name] = False
        logger.info("Registered transport: %s (%s)", plugin.name, plugin.transport_type.value)

    def unregister(self, name: str) -> None:
        self._plugins.pop(name, None)
        self._initialized.pop(name, None)

    def get(self, name: str) -> Optional[TransportPlugin]:
        return self._plugins.get(name)

    def get_all(self) -> List[TransportPlugin]:
        """Return all registered plugins."""
        return list(self._plugins.values())

    @property
    def plugin_names(self) -> List[str]:
        return list(self._plugins.keys())

    def by_type(self, transport_type: TransportType) -> List[TransportPlugin]:
        return [p for p in self._plugins.values() if p.transport_type == transport_type]

    async def initialize_all(self) -> None:
        """Initialize all registered plugins concurrently."""

        async def _init_one(name: str, plugin: TransportPlugin) -> None:
            try:
                await plugin.initialize()
                self._initialized[name] = True
                logger.info("Initialized: %s", name)
            except Exception:
                logger.exception("Failed to initialize: %s", name)
                self._initialized[name] = False

        await asyncio.gather(*[_init_one(n, p) for n, p in self._plugins.items()])

    async def teardown_all(self) -> None:
        """Teardown all plugins."""
        for name, plugin in self._plugins.items():
            try:
                await plugin.teardown()
            except Exception:
                logger.exception("Error tearing down: %s", name)

    async def get_online_plugins(self) -> List[TransportPlugin]:
        """Return plugins that are initialized and reporting ONLINE or DEGRADED."""
        result = []
        for name, plugin in self._plugins.items():
            if not self._initialized.get(name, False):
                continue
            status = await plugin.get_status()
            if status in (TransportStatus.ONLINE, TransportStatus.DEGRADED):
                result.append(plugin)
        return sorted(result, key=lambda p: p.priority)

    async def health_check_all(self) -> Dict[str, TransportStatus]:
        """Check health of all plugins."""
        results: Dict[str, TransportStatus] = {}
        for name, plugin in self._plugins.items():
            try:
                results[name] = await plugin.health_check()
            except Exception:
                results[name] = TransportStatus.ERROR
        return results
