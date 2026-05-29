"""Tests for RelayServer."""

import asyncio
import struct
import pytest

from ecfs.plugins.relay_server import RelayServer


@pytest.fixture
def free_port():
    """Get a free port for testing."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def server(free_port):
    s = RelayServer(host="127.0.0.1", port=free_port)
    yield s
    await s.stop()


class TestRelayServerBasics:
    def test_active_connections_default_zero(self, server):
        assert server.active_connections == 0

    @pytest.mark.asyncio
    async def test_receive_empty_returns_none(self, server):
        result = await server.receive()
        assert result is None

    @pytest.mark.asyncio
    async def test_server_starts_and_stops(self, free_port):
        s = RelayServer(host="127.0.0.1", port=free_port)
        await s.start()
        assert s._server is not None
        await s.stop()


class TestRelayServerProtocol:
    @pytest.mark.asyncio
    async def test_length_prefixed_send_receive(self, free_port):
        s = RelayServer(host="127.0.0.1", port=free_port)
        await s.start()

        try:
            # Connect as a client and send a length-prefixed packet
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", free_port
            )

            payload = b"hello from client"
            length_prefix = struct.pack(">I", len(payload))
            writer.write(length_prefix + payload)
            await writer.drain()

            # Give server time to process
            await asyncio.sleep(0.1)

            received = await s.receive()
            assert received == payload

            writer.close()
            await writer.wait_closed()
        finally:
            await s.stop()

    @pytest.mark.asyncio
    async def test_multiple_packets(self, free_port):
        s = RelayServer(host="127.0.0.1", port=free_port)
        await s.start()

        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", free_port
            )

            for i in range(3):
                payload = f"packet_{i}".encode()
                length_prefix = struct.pack(">I", len(payload))
                writer.write(length_prefix + payload)
                await writer.drain()

            await asyncio.sleep(0.1)

            for i in range(3):
                received = await s.receive()
                assert received == f"packet_{i}".encode()

            writer.close()
            await writer.wait_closed()
        finally:
            await s.stop()
