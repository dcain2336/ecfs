"""ECFS core engine — routing, queuing, and deduplication."""

from ecfs.core.routing import RoutingEngine, RoutingStrategy
from ecfs.core.queue import MessageQueue, MessagePriority, QueuedMessage
from ecfs.core.dedup import DeduplicationCache

__all__ = [
    "RoutingEngine",
    "RoutingStrategy",
    "MessageQueue",
    "MessagePriority",
    "QueuedMessage",
    "DeduplicationCache",
]
