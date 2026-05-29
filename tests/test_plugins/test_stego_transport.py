"""Tests for steganographic HTTP transport plugin."""

import asyncio
import pytest
from ecfs.plugins.stego_transport import SteganographicHTTP
from ecfs.plugins.base import TransportStatus, TransportType


@pytest.fixture
def stego():
    return SteganographicHTTP()


@pytest.mark.asyncio
async def test_name_and_type(stego):
    assert stego.name == "stego"
    assert stego.transport_type == TransportType.COVERT


@pytest.mark.asyncio
async def test_priority(stego):
    assert stego.priority == 45


@pytest.mark.asyncio
async def test_encode_decode_headers_roundtrip(stego):
    """Test encoding in headers and decoding back."""
    data = b"ECFS covert message"
    headers = stego.encode_in_headers(data)
    assert all(k.startswith("X-ECFS-") for k in headers)

    decoded = stego.decode_from_headers(headers)
    assert decoded == data


@pytest.mark.asyncio
async def test_encode_decode_dns_roundtrip(stego):
    """Test encoding in DNS labels and decoding back."""
    data = b"DNS steganography test"
    labels = stego.encode_in_dns(data)
    assert isinstance(labels, list)
    assert all(isinstance(l, str) for l in labels)

    decoded = stego.decode_from_dns(labels)
    assert decoded == data


@pytest.mark.asyncio
async def test_pad_to_normal_size(stego):
    """Test padding to normal web traffic sizes."""
    data = b"small"
    padded = stego.pad_to_normal(data, target_size=256)
    assert len(padded) == 256

    # Verify data can be recovered
    recovered = stego.unpad(padded)
    assert recovered == data


@pytest.mark.asyncio
async def test_chi_squared_random_is_low(stego):
    """Test that chi-squared of random-looking data is low."""
    import os
    random_data = os.urandom(1024)
    chi_sq = stego.calculate_chi_squared(random_data)
    # Random data should have chi-squared close to 0
    assert chi_sq < 0.1


@pytest.mark.asyncio
async def test_initialize_and_teardown(stego):
    """Test initialize sets online and teardown sets offline."""
    await stego.initialize()
    status = await stego.get_status()
    assert status == TransportStatus.ONLINE

    await stego.teardown()
    status = await stego.get_status()
    assert status == TransportStatus.OFFLINE


@pytest.mark.asyncio
async def test_encode_in_headers_many_chunks(stego):
    """Test encoding large data across multiple headers."""
    data = b"x" * 2000  # Should require multiple headers
    headers = stego.encode_in_headers(data)
    assert len(headers) > 1

    decoded = stego.decode_from_headers(headers)
    assert decoded == data


@pytest.mark.asyncio
async def test_send_receive_roundtrip(stego):
    """Test full send/receive cycle."""
    await stego.initialize()
    data = b"covert payload"
    result = await stego.send_packet(data)
    assert result is True

    received = await stego.receive_packet()
    assert received == data
