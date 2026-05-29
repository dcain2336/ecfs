"""ECFS — Autonomous Emergency Communication Failover System.

A delay-tolerant network (DTN) routing engine with modular transport
plugins for communications-degraded environments.
"""

__version__ = "0.6.0"

from ecfs.core.engine import ECFSEngine
from ecfs.core.orchestrator import MeshOrchestrator
from ecfs.core.fragmentation import FragmentManager, Fragment
from ecfs.relay.client import RelayClient
from ecfs.discovery.mesh import MeshNode

__all__ = ["ECFSEngine", "MeshOrchestrator", "FragmentManager", "Fragment", "RelayClient", "MeshNode"]
