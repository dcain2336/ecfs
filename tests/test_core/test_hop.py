"""Tests for cross-medium hop tracking."""

import pytest
from ecfs.core.hop import HopTracker, HopRecord
from ecfs.plugins.base import TransportType


@pytest.fixture
def tracker():
    return HopTracker()


def test_record_and_retrieve_hops(tracker):
    tracker.record_hop("pkt1", "lora", TransportType.RADIO, latency_ms=50.0)
    tracker.record_hop("pkt1", "ble", TransportType.RADIO, latency_ms=10.0)
    hops = tracker.get_hops("pkt1")
    assert len(hops) == 2
    assert hops[0].transport_name == "lora"
    assert hops[1].transport_name == "ble"
    assert hops[0].latency_ms == 50.0
    assert hops[1].latency_ms == 10.0


def test_medium_transitions_zero(tracker):
    # Two hops on the same type = no transitions
    tracker.record_hop("pkt1", "lora", TransportType.RADIO)
    tracker.record_hop("pkt1", "ble", TransportType.RADIO)
    transitions = tracker.get_medium_transitions("pkt1")
    assert transitions == 0


def test_medium_transitions_count(tracker):
    # LoRa (RADIO) → Internet (INTERNET) → BLE (RADIO) = 2 transitions
    tracker.record_hop("pkt1", "lora", TransportType.RADIO)
    tracker.record_hop("pkt1", "internet", TransportType.INTERNET)
    tracker.record_hop("pkt1", "ble", TransportType.RADIO)
    transitions = tracker.get_medium_transitions("pkt1")
    assert transitions == 2


def test_total_latency(tracker):
    tracker.record_hop("pkt1", "lora", TransportType.RADIO, latency_ms=50.0)
    tracker.record_hop("pkt1", "internet", TransportType.INTERNET, latency_ms=100.0)
    tracker.record_hop("pkt1", "ble", TransportType.RADIO, latency_ms=5.0)
    total = tracker.get_total_latency("pkt1")
    assert total == 155.0


def test_get_stats(tracker):
    tracker.record_hop("pkt1", "lora", TransportType.RADIO, latency_ms=50.0, success=True)
    tracker.record_hop("pkt2", "lora", TransportType.RADIO, latency_ms=100.0, success=False)
    tracker.record_hop("pkt3", "ble", TransportType.RADIO, latency_ms=10.0, success=True)
    stats = tracker.get_stats("lora")
    assert stats["count"] == 2
    assert stats["success_rate"] == 0.5
    assert stats["avg_latency_ms"] == 75.0


def test_clear(tracker):
    tracker.record_hop("pkt1", "lora", TransportType.RADIO)
    tracker.record_hop("pkt2", "ble", TransportType.RADIO)
    # Clear one packet
    tracker.clear("pkt1")
    assert tracker.get_hops("pkt1") == []
    assert len(tracker.get_hops("pkt2")) == 1
    # Clear all
    tracker.clear()
    assert tracker.get_hops("pkt2") == []
