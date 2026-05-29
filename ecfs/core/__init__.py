"""ECFS core engine — routing, queuing, deduplication, hop tracking, and orchestration."""

from ecfs.core.routing import RoutingEngine, RoutingStrategy
from ecfs.core.queue import MessageQueue, MessagePriority, QueuedMessage
from ecfs.core.dedup import DeduplicationCache
from ecfs.core.hop import HopTracker, HopRecord
from ecfs.core.state_machine import StateMachine, State
from ecfs.core.threat_assessor import ThreatAssessor, ThreatLevel, ThreatReport
from ecfs.core.engine import ECFSEngine
from ecfs.core.dns import (
    encode_to_dns_label,
    decode_from_dns_label,
    generate_subdomain,
    extract_data_from_subdomain,
)

__all__ = [
    "RoutingEngine",
    "RoutingStrategy",
    "MessageQueue",
    "MessagePriority",
    "QueuedMessage",
    "DeduplicationCache",
    "HopTracker",
    "HopRecord",
    "StateMachine",
    "State",
    "ThreatAssessor",
    "ThreatLevel",
    "ThreatReport",
    "ECFSEngine",
    "encode_to_dns_label",
    "decode_from_dns_label",
    "generate_subdomain",
    "extract_data_from_subdomain",
]
