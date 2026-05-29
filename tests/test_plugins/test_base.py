import pytest
from ecfs.plugins.base import TransportStats, ThreatLevel, TransportStatus, TransportType


class TestTransportStatusEnum:
    def test_has_online(self) -> None:
        assert TransportStatus.ONLINE is TransportStatus.ONLINE

    def test_has_degraded(self) -> None:
        assert TransportStatus.DEGRADED is TransportStatus.DEGRADED

    def test_has_offline(self) -> None:
        assert TransportStatus.OFFLINE is TransportStatus.OFFLINE

    def test_has_error(self) -> None:
        assert TransportStatus.ERROR is TransportStatus.ERROR

    def test_all_members(self) -> None:
        members = set(TransportStatus)
        assert members == {TransportStatus.ONLINE, TransportStatus.DEGRADED,
                           TransportStatus.OFFLINE, TransportStatus.ERROR}


class TestThreatLevelOrdering:
    def test_low_is_one(self) -> None:
        assert ThreatLevel.LOW.value == 1

    def test_medium_is_two(self) -> None:
        assert ThreatLevel.MEDIUM.value == 2

    def test_high_is_three(self) -> None:
        assert ThreatLevel.HIGH.value == 3

    def test_critical_is_four(self) -> None:
        assert ThreatLevel.CRITICAL.value == 4

    def test_ordering(self) -> None:
        assert ThreatLevel.LOW.value < ThreatLevel.MEDIUM.value < ThreatLevel.HIGH.value < ThreatLevel.CRITICAL.value


class TestTransportStatsDefaults:
    def test_packets_sent_default(self) -> None:
        s = TransportStats()
        assert s.packets_sent == 0

    def test_packets_received_default(self) -> None:
        s = TransportStats()
        assert s.packets_received == 0

    def test_packets_failed_default(self) -> None:
        s = TransportStats()
        assert s.packets_failed == 0

    def test_bytes_sent_default(self) -> None:
        s = TransportStats()
        assert s.bytes_sent == 0

    def test_bytes_received_default(self) -> None:
        s = TransportStats()
        assert s.bytes_received == 0

    def test_avg_latency_default(self) -> None:
        s = TransportStats()
        assert s.avg_latency_ms == 0.0

    def test_last_seen_is_set(self) -> None:
        s = TransportStats()
        assert s.last_seen > 0

    def test_custom_values(self) -> None:
        s = TransportStats(packets_sent=10, bytes_sent=1024, avg_latency_ms=42.5)
        assert s.packets_sent == 10
        assert s.bytes_sent == 1024
        assert s.avg_latency_ms == 42.5
        assert s.packets_received == 0  # default unchanged
