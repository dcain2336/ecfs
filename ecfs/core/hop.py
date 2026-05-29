"""Cross-medium hop tracking for ECFS packet routing."""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from ecfs.plugins.base import TransportType

logger = logging.getLogger(__name__)


@dataclass
class HopRecord:
    """Record of a single packet hop."""

    transport_name: str
    transport_type: TransportType
    timestamp: float = field(default_factory=time.time)
    latency_ms: float = 0.0
    success: bool = True


class HopTracker:
    """Tracks packet hops across different transport mediums.

    Measures cross-medium latency and provides stats for adaptive routing.
    """

    def __init__(self) -> None:
        self._hops: dict[str, list[HopRecord]] = {}  # packet_id -> hops

    def record_hop(
        self,
        packet_id: str,
        transport_name: str,
        transport_type: TransportType,
        latency_ms: float = 0.0,
        success: bool = True,
    ) -> None:
        if packet_id not in self._hops:
            self._hops[packet_id] = []
        self._hops[packet_id].append(
            HopRecord(
                transport_name=transport_name,
                transport_type=transport_type,
                latency_ms=latency_ms,
                success=success,
            )
        )

    def get_hops(self, packet_id: str) -> list[HopRecord]:
        return self._hops.get(packet_id, [])

    def get_medium_transitions(self, packet_id: str) -> int:
        """Count how many times the packet changed transport type."""
        hops = self._hops.get(packet_id, [])
        if len(hops) < 2:
            return 0
        transitions = 0
        for i in range(1, len(hops)):
            if hops[i].transport_type != hops[i - 1].transport_type:
                transitions += 1
        return transitions

    def get_total_latency(self, packet_id: str) -> float:
        hops = self._hops.get(packet_id, [])
        return sum(h.latency_ms for h in hops)

    def get_stats(self, transport_name: str) -> dict:
        """Get stats for a specific transport across all packets."""
        all_hops = []
        for hops in self._hops.values():
            all_hops.extend(h for h in hops if h.transport_name == transport_name)
        if not all_hops:
            return {"count": 0}
        return {
            "count": len(all_hops),
            "success_rate": sum(1 for h in all_hops if h.success) / len(all_hops),
            "avg_latency_ms": sum(h.latency_ms for h in all_hops) / len(all_hops),
        }

    def clear(self, packet_id: str = None) -> None:
        if packet_id:
            self._hops.pop(packet_id, None)
        else:
            self._hops.clear()
