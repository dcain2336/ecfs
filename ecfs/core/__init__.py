"""ECFS core engine — routing, queuing, deduplication, and hop tracking."""

from ecfs.core.routing import RoutingEngine, RoutingStrategy
from ecfs.core.queue import MessageQueue, MessagePriority, QueuedMessage
from ecfs.core.dedup import DeduplicationCache
from ecfs.core.hop import HopTracker, HopRecord

__all__ = [
    "RoutingEngine",
    "RoutingStrategy",
    "MessageQueue",
    "MessagePriority",
    "QueuedMessage",
    "DeduplicationCache",
    "HopTracker",
    "HopRecord",
]
