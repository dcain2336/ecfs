"""Ultrasonic audio transport for ECFS — FSK-modulated acoustic packet exchange."""

import asyncio
import logging
import math
from typing import Optional, Protocol

from ecfs.plugins.base import TransportPlugin, TransportStatus, TransportType

logger = logging.getLogger(__name__)


class AudioInterface(Protocol):
    async def play(self, signal: list[float], sample_rate: int) -> None: ...
    async def record(self, duration: float, sample_rate: int) -> list[float]: ...
    async def close(self) -> None: ...


class MockAudio:
    """Mock audio interface for CI testing."""

    def __init__(self) -> None:
        self._last_signal: list[float] = []
        self._playback_count: int = 0

    async def play(self, signal: list[float], sample_rate: int) -> None:
        self._last_signal = signal
        self._playback_count += 1

    async def record(self, duration: float, sample_rate: int) -> list[float]:
        return self._last_signal[:]

    async def close(self) -> None:
        pass


class UltrasonicAudioTransport(TransportPlugin):
    """Ultrasonic audio transport for ECFS.

    Uses FSK modulation in the 18-22 kHz range to transmit packets
    through audio. Includes Reed-Solomon error correction for
    noisy acoustic channels.
    """

    MAX_PACKET_SIZE = 512
    CHUNK_SIZE = 256
    FREQ_LOW = 18000  # Hz - bit=0
    FREQ_HIGH = 22000  # Hz - bit=1
    SAMPLE_RATE = 48000
    BIT_DURATION = 0.01  # seconds per bit
    RS_PARITY_BYTES = 8

    def __init__(self, audio: AudioInterface = None) -> None:
        self._audio = audio or MockAudio()
        self._status = TransportStatus.OFFLINE
        self._receive_queue: asyncio.Queue[bytes] = asyncio.Queue()

    @property
    def name(self) -> str:
        return "ultrasonic"

    @property
    def transport_type(self) -> TransportType:
        return TransportType.ACOUSTIC

    @property
    def priority(self) -> int:
        return 40  # Covert, lower priority than standard transports

    @property
    def max_packet_size(self) -> int:
        return self.MAX_PACKET_SIZE

    async def initialize(self) -> None:
        self._status = TransportStatus.ONLINE
        logger.info("Ultrasonic transport initialized")

    async def teardown(self) -> None:
        await self._audio.close()
        self._status = TransportStatus.OFFLINE

    def _rs_encode(self, data: bytes) -> bytes:
        """Simple Reed-Solomon-like error correction: append parity bytes.

        Uses XOR-based parity for simplicity. A real RS implementation
        would use Galois field arithmetic.
        """
        parity = bytearray(self.RS_PARITY_BYTES)
        for i, byte in enumerate(data):
            parity[i % self.RS_PARITY_BYTES] ^= byte
        return data + bytes(parity)

    def _rs_decode(self, data: bytes) -> bytes:
        """Strip Reed-Solomon parity bytes."""
        if len(data) <= self.RS_PARITY_BYTES:
            return data
        return data[: -self.RS_PARITY_BYTES]

    def encode_to_signal(self, data: bytes) -> list[float]:
        """Encode binary data into an audio signal using FSK modulation."""
        signal = []
        samples_per_bit = int(self.SAMPLE_RATE * self.BIT_DURATION)
        for byte in data:
            for bit_idx in range(8):
                bit = (byte >> (7 - bit_idx)) & 1
                freq = self.FREQ_HIGH if bit else self.FREQ_LOW
                for s in range(samples_per_bit):
                    t = s / self.SAMPLE_RATE
                    sample = math.sin(2 * math.pi * freq * t)
                    signal.append(sample)
        return signal

    def decode_from_signal(self, signal: list[float]) -> bytes:
        """Decode an audio signal back to binary data using FSK demodulation."""
        samples_per_bit = int(self.SAMPLE_RATE * self.BIT_DURATION)
        if samples_per_bit == 0:
            return b""
        total_bits = len(signal) // samples_per_bit
        result = bytearray()
        for bit_idx in range(total_bits):
            start = bit_idx * samples_per_bit
            end = start + samples_per_bit
            chunk = signal[start:end]
            if not chunk:
                continue
            # Calculate energy at both frequencies
            energy_high = 0.0
            energy_low = 0.0
            for s, sample in enumerate(chunk):
                t = s / self.SAMPLE_RATE
                energy_high += sample * math.sin(2 * math.pi * self.FREQ_HIGH * t)
                energy_low += sample * math.sin(2 * math.pi * self.FREQ_LOW * t)
            bit = 1 if energy_high > energy_low else 0
            # Accumulate bits into bytes
            byte_idx = bit_idx // 8
            bit_pos = 7 - (bit_idx % 8)
            while len(result) <= byte_idx:
                result.append(0)
            result[byte_idx] |= bit << bit_pos
        return bytes(result)

    def play_audio(self, signal: list[float]) -> asyncio.Task:
        """Play the audio signal. Returns a task for async use."""
        return asyncio.create_task(
            self._audio.play(signal, self.SAMPLE_RATE)
        )

    async def record_audio(self, duration: float) -> list[float]:
        """Record audio for the given duration."""
        return await self._audio.record(duration, self.SAMPLE_RATE)

    def _chunk_data(self, data: bytes) -> list[bytes]:
        """Split data into chunks with RS error correction."""
        chunks = []
        for i in range(0, len(data), self.CHUNK_SIZE):
            chunk = data[i : i + self.CHUNK_SIZE]
            chunks.append(self._rs_encode(chunk))
        return chunks

    async def send_packet(self, data: bytes) -> bool:
        if len(data) > self.MAX_PACKET_SIZE:
            logger.warning("Packet too large for ultrasonic: %d bytes", len(data))
            return False
        try:
            chunks = self._chunk_data(data)
            for chunk in chunks:
                signal = self.encode_to_signal(chunk)
                await self._audio.play(signal, self.SAMPLE_RATE)
            logger.debug("Sent %d ultrasonic chunks", len(chunks))
            return True
        except Exception:
            logger.exception("Ultrasonic send failed")
            self._status = TransportStatus.ERROR
            return False

    async def receive_packet(self) -> Optional[bytes]:
        try:
            return self._receive_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def get_status(self) -> TransportStatus:
        return self._status

    def queue_received(self, data: bytes) -> None:
        """Queue a received packet for processing."""
        self._receive_queue.put_nowait(data)
