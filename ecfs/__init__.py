"""ECFS — Autonomous Emergency Communication Failover System.

A delay-tolerant network (DTN) routing engine with modular transport
plugins for communications-degraded environments.
"""

__version__ = "0.5.0"

from ecfs.core.engine import ECFSEngine
from ecfs.relay.client import RelayClient

__all__ = ["ECFSEngine", "RelayClient"]
