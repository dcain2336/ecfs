"""Tests for LoRa transport plugin."""

import asyncio
import pytest
from ecfs.plugins.lora_transport import LoRaTransport, MockSerial
from ecfs.plugins.base import TransportStatus, TransportType


@pytest.fixture
def mock_serial():
    return MockSerial()


@pytest.fixture
def lora(mock_serial):
    return LoRaTransport(serial=mock_serial, port="/dev/ttyUSB0")


@pytest.mark.asyncio
async def test_name_and_type(lora):
    assert lora.name == "lora"
    assert lora.transport_type == TransportType.RADIO


@pytest.mark.asyncio
async def test_priority(lora):
    assert lora.priority == 30


@pytest.mark.asyncio
async def test_max_packet_size(lora):
    assert lora.max_packet_size == 200  # CHUNK_SIZE


@pytest.mark.asyncio
async def test_initial_status_offline(lora):
    status = await lora.get_status()
    assert status == TransportStatus.OFFLINE


@pytest.mark.asyncio
async def test_initialize_sets_online(lora):
    await lora.initialize()
    status = await lora.get_status()
    assert status == TransportStatus.ONLINE


@pytest.mark.asyncio
async def test_teardown_sets_offline(lora):
    await lora.initialize()
    await lora.teardown()
    status = await lora.get_status()
    assert status == TransportStatus.OFFLINE


@pytest.mark.asyncio
async def test_send_single_chunk(lora):
    await lora.initialize()
    data = b"hello world"
    result = await lora.send_packet(data)
    assert result is True
    # Verify the serial received exactly one chunk
    chunk = await lora._serial._buffer.get()
    # Header (4 bytes) + data
    assert len(chunk) == 4 + len(data)
    # Seq number should be 0
    seq = int.from_bytes(chunk[:2], "big")
    assert seq == 0
    # Total chunks should be 1
    total = int.from_bytes(chunk[2:4], "big")
    assert total == 1


@pytest.mark.asyncio
async def test_send_multi_chunk(lora):
    await lora.initialize()
    data = b"x" * 350  # Needs 2 chunks (CHUNK_SIZE=200)
    result = await lora.send_packet(data)
    assert result is True
    # Should have 2 chunks
    chunks = []
    while not lora._serial._buffer.empty():
        chunks.append(await lora._serial._buffer.get())
    assert len(chunks) == 2
    # Both should have same seq number
    seq1 = int.from_bytes(chunks[0][:2], "big")
    seq2 = int.from_bytes(chunks[1][:2], "big")
    assert seq1 == seq2 == 0


@pytest.mark.asyncio
async def test_send_rejects_oversized(lora):
    await lora.initialize()
    data = b"x" * (lora.max_packet_size * 10 + 1)
    result = await lora.send_packet(data)
    assert result is False


@pytest.mark.asyncio
async def test_receive_empty_returns_none(lora):
    await lora.initialize()
    packet = await lora.receive_packet()
    assert packet is None


@pytest.mark.asyncio
async def test_queue_received(lora):
    await lora.initialize()
    test_data = b"received packet"
    lora.queue_received(test_data)
    packet = await lora.receive_packet()
    assert packet == test_data
