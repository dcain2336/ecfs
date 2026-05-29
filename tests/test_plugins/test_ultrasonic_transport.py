"""Tests for ultrasonic audio transport plugin."""

import asyncio
import pytest
from ecfs.plugins.ultrasonic_transport import UltrasonicAudioTransport, MockAudio
from ecfs.plugins.base import TransportStatus, TransportType


@pytest.fixture
def mock_audio():
    return MockAudio()


@pytest.fixture
def ultrasonic(mock_audio):
    return UltrasonicAudioTransport(audio=mock_audio)


@pytest.mark.asyncio
async def test_name_and_type(ultrasonic):
    assert ultrasonic.name == "ultrasonic"
    assert ultrasonic.transport_type == TransportType.ACOUSTIC


@pytest.mark.asyncio
async def test_priority(ultrasonic):
    assert ultrasonic.priority == 40


@pytest.mark.asyncio
async def test_max_packet_size(ultrasonic):
    assert ultrasonic.max_packet_size == 512


@pytest.mark.asyncio
async def test_encode_decode_roundtrip(ultrasonic):
    """Test that encoding to signal and decoding back produces original data."""
    data = b"Hello ECFS!"
    signal = ultrasonic.encode_to_signal(data)
    decoded = ultrasonic.decode_from_signal(signal)
    assert decoded == data


@pytest.mark.asyncio
async def test_send_receive(ultrasonic, mock_audio):
    """Test send_packet encodes data and play is called."""
    await ultrasonic.initialize()
    data = b"ultrasonic payload"
    result = await ultrasonic.send_packet(data)
    assert result is True
    assert mock_audio._playback_count >= 1


@pytest.mark.asyncio
async def test_signal_encoding_length(ultrasonic):
    """Test that signal length is proportional to data size."""
    data = b"test"
    signal = ultrasonic.encode_to_signal(data)
    # Each byte = 8 bits, each bit = samples_per_bit samples
    samples_per_bit = int(ultrasonic.SAMPLE_RATE * ultrasonic.BIT_DURATION)
    expected_samples = len(data) * 8 * samples_per_bit
    assert len(signal) == expected_samples


@pytest.mark.asyncio
async def test_chunk_data(ultrasonic):
    """Test that data is properly chunked with RS parity."""
    data = b"x" * 512  # Should be chunked into 2 chunks
    chunks = ultrasonic._chunk_data(data)
    assert len(chunks) == 2
    # Each chunk should have RS parity appended
    for chunk in chunks:
        assert len(chunk) == ultrasonic.CHUNK_SIZE + ultrasonic.RS_PARITY_BYTES


@pytest.mark.asyncio
async def test_initialize_and_teardown(ultrasonic):
    """Test initialize sets online and teardown sets offline."""
    await ultrasonic.initialize()
    status = await ultrasonic.get_status()
    assert status == TransportStatus.ONLINE

    await ultrasonic.teardown()
    status = await ultrasonic.get_status()
    assert status == TransportStatus.OFFLINE


@pytest.mark.asyncio
async def test_receive_empty_returns_none(ultrasonic):
    """Test receive_packet returns None when queue is empty."""
    await ultrasonic.initialize()
    packet = await ultrasonic.receive_packet()
    assert packet is None
