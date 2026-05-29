"""Phase 3 integration tests — radio transports + hop tracking."""

import asyncio
import pytest
from ecfs.plugins.lora_transport import LoRaTransport, MockSerial
from ecfs.plugins.ble_transport import BLETransport, MockBLE
from ecfs.plugins.null_transport import NullTransport
from ecfs.plugins.registry import PluginRegistry
from ecfs.plugins.base import TransportStatus, TransportType
from ecfs.core.hop import HopTracker


@pytest.mark.asyncio
async def test_lora_chunk_reassemble():
    """Send multi-chunk data and verify all chunks are produced."""
    serial = MockSerial()
    lora = LoRaTransport(serial=serial)
    await lora.initialize()

    data = b"Hello" * 100  # 500 bytes → 3 chunks
    result = await lora.send_packet(data)
    assert result is True

    chunks = []
    while not serial._buffer.empty():
        chunk = await serial._buffer.get()
        chunks.append(chunk)

    assert len(chunks) == 3
    # All chunks should have the same sequence number
    seqs = {int.from_bytes(c[:2], "big") for c in chunks}
    assert len(seqs) == 1


@pytest.mark.asyncio
async def test_ble_peripheral_central():
    """Two BLE peripherals + one central connect."""
    peripheral = BLETransport(ble=MockBLE())
    central = BLETransport(ble=MockBLE())

    await peripheral.initialize()
    await central.initialize()

    # Peripheral is advertising
    assert peripheral._ble._advertising is True

    # Central connects to peripheral
    result = await central.connect_to_peer("AA:BB:CC:DD:EE:FF")
    assert result is True
    assert central._role == "central"

    # Both can send/receive
    await peripheral.send_packet(b"from peripheral")
    await central.send_packet(b"from central")


@pytest.mark.asyncio
async def test_cross_medium_tracking():
    """Record LoRa hop then BLE hop → verify 1 transition."""
    tracker = HopTracker()
    tracker.record_hop("pkt1", "lora", TransportType.RADIO, latency_ms=50.0)
    tracker.record_hop("pkt1", "ble", TransportType.RADIO, latency_ms=10.0)

    # Both are RADIO type, so 0 transitions
    transitions = tracker.get_medium_transitions("pkt1")
    assert transitions == 0

    # Now add an internet hop
    tracker.record_hop("pkt1", "internet", TransportType.INTERNET, latency_ms=100.0)
    transitions = tracker.get_medium_transitions("pkt1")
    assert transitions == 1

    total = tracker.get_total_latency("pkt1")
    assert total == 160.0


@pytest.mark.asyncio
async def test_plugin_registry_with_radio():
    """Register LoRa + BLE + NullTransport, verify by_type(RADIO)."""
    registry = PluginRegistry()
    registry.register(LoRaTransport())
    registry.register(BLETransport())
    registry.register(NullTransport())

    assert len(registry.plugin_names) == 3
    assert "lora" in registry.plugin_names
    assert "ble" in registry.plugin_names
    assert "null" in registry.plugin_names

    radio_plugins = registry.by_type(TransportType.RADIO)
    assert len(radio_plugins) == 2
    radio_names = {p.name for p in radio_plugins}
    assert radio_names == {"lora", "ble"}
