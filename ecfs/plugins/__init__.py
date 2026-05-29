"""ECFS transport plugin system — base classes, registry, and transports."""

from ecfs.plugins.base import (
    TransportPlugin,
    TransportStatus,
    TransportType,
    ThreatLevel,
    TransportStats,
)
from ecfs.plugins.registry import PluginRegistry
from ecfs.plugins.null_transport import NullTransport
from ecfs.plugins.internet_transport import InternetTransport
from ecfs.plugins.dns_transport import DNSTunnelTransport
from ecfs.plugins.relay_server import RelayServer

__all__ = [
    "TransportPlugin",
    "TransportStatus",
    "TransportType",
    "ThreatLevel",
    "TransportStats",
    "PluginRegistry",
    "NullTransport",
    "InternetTransport",
    "DNSTunnelTransport",
    "RelayServer",
]
