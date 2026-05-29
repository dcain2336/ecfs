"""Tests for RFID transport plugin."""

import asyncio
import pytest
from ecfs.plugins.rfid_transport import RFIDTransport, MockRFID
from ecfs.plugins.base import TransportStatus, TransportType


@pytest.fixture
def mock_rfid():
    return MockRFID()


@pytest.fixture
def rfid(mock_rfid):
    return RFIDTransport(rfid=mock_rfid)


@pytest.mark.asyncio
async def test_name_and_type(rfid):
    assert rfid.name == "rfid"
    assert rfid.transport_type == TransportType.PROXIMITY


@pytest.mark.asyncio
async def test_priority(rfid):
    assert rfid.priority == 10


@pytest.mark.asyncio
async def test_max_packet_size(rfid):
    assert rfid.max_packet_size == 144


@pytest.mark.asyncio
async def test_write_read_tag(rfid, mock_rfid):
    """Test writing and reading data from a tag."""
    data = b"ECFS packet data"
    result = await rfid.write_tag("TAG001", data)
    assert result is True

    read_data = await rfid.read_tag("TAG001")
    assert read_data == data


@pytest.mark.asyncio
async def test_scan_tags(rfid, mock_rfid):
    """Test scanning for available tags."""
    mock_rfid._tags = {"TAG001": b"data1", "TAG002": b"data2"}
    tags = await rfid.scan_tags()
    assert len(tags) == 2
    tag_ids = [t["tag_id"] for t in tags]
    assert "TAG001" in tag_ids
    assert "TAG002" in tag_ids


@pytest.mark.asyncio
async def test_chunk_data_for_tag(rfid):
    """Test data chunking for tag memory limits."""
    data = b"x" * 300  # Larger than single tag
    chunks = rfid._chunk_data(data)
    assert len(chunks) == 3  # 300 bytes / (144-4) per chunk
    # Each chunk should have 4-byte header
    for chunk in chunks:
        assert len(chunk) <= 144


@pytest.mark.asyncio
async def test_oversized_rejection(rfid):
    """Test that oversized writes are rejected."""
    result = await rfid.write_tag("TAG001", b"x" * (rfid.MAX_PACKET_SIZE + 1))
    assert result is False


@pytest.mark.asyncio
async def test_initialize_and_teardown(rfid):
    """Test initialize sets online and teardown sets offline."""
    await rfid.initialize()
    status = await rfid.get_status()
    assert status == TransportStatus.ONLINE

    await rfid.teardown()
    status = await rfid.get_status()
    assert status == TransportStatus.OFFLINE
