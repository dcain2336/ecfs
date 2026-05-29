"""Tests for BLE transport plugin."""

import asyncio
import pytest
from ecfs.plugins.ble_transport import BLETransport, MockBLE
from ecfs.plugins.base import TransportStatus, TransportType


@pytest.fixture
def mock_ble():
    return MockBLE()


@pytest.fixture
def ble(mock_ble):
    return BLETransport(ble=mock_ble, address="AA:BB:CC:DD:EE:FF")


@pytest.mark.asyncio
async def test_name_and_type(ble):
    assert ble.name == "ble"
    assert ble.transport_type == TransportType.RADIO


@pytest.mark.asyncio
async def test_priority(ble):
    assert ble.priority == 25


@pytest.mark.asyncio
async def test_max_packet_size(ble):
    assert ble.max_packet_size == 512


@pytest.mark.asyncio
async def test_initial_status_offline(ble):
    status = await ble.get_status()
    assert status == TransportStatus.OFFLINE


@pytest.mark.asyncio
async def test_initialize_starts_advertising(ble, mock_ble):
    await ble.initialize()
    status = await ble.get_status()
    assert status == TransportStatus.ONLINE
    assert mock_ble._advertising is True


@pytest.mark.asyncio
async def test_teardown_disconnects(ble, mock_ble):
    await ble.initialize()
    # Simulate a connection
    await mock_ble.connect("AA:BB:CC:DD:EE:FF")
    assert mock_ble._connected is True
    await ble.teardown()
    assert mock_ble._connected is False
    assert mock_ble._advertising is False
    status = await ble.get_status()
    assert status == TransportStatus.OFFLINE


@pytest.mark.asyncio
async def test_connect_to_peer(ble, mock_ble):
    await ble.initialize()
    result = await ble.connect_to_peer("11:22:33:44:55:66")
    assert result is True
    assert ble._role == "central"
    assert mock_ble._connected is True


@pytest.mark.asyncio
async def test_send_packet(ble, mock_ble):
    await ble.initialize()
    data = b"ble payload"
    result = await ble.send_packet(data)
    assert result is True
    assert data in mock_ble._written


@pytest.mark.asyncio
async def test_send_rejects_oversized(ble):
    await ble.initialize()
    data = b"x" * (ble.MAX_PACKET_SIZE + 1)
    result = await ble.send_packet(data)
    assert result is False


@pytest.mark.asyncio
async def test_receive_empty_returns_none(ble):
    await ble.initialize()
    packet = await ble.receive_packet()
    assert packet is None
