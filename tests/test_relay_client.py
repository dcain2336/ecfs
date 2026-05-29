"""Tests for ecfs.relay.client — RelayClient."""

import asyncio
import struct
import pytest

from ecfs.relay.client import RelayClient
from ecfs.plugins.relay_server import RelayServer


@pytest.mark.asyncio
async def test_connect_success():
    """Client can connect to a running relay server."""
    server = RelayServer(host="127.0.0.1", port=0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    client = RelayClient("127.0.0.1", port)

    result = await client.connect()
    assert result is True
    assert client.is_connected

    await client.close()
    await server.stop()


@pytest.mark.asyncio
async def test_send_receives_length_prefixed():
    """Client send produces a length-prefixed packet on the server."""
    server = RelayServer(host="127.0.0.1", port=0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    client = RelayClient("127.0.0.1", port)
    await client.connect()

    payload = b"hello relay"
    result = await client.send(payload)
    assert result is True

    # Give server time to process
    await asyncio.sleep(0.1)

    received = await server.receive()
    assert received == payload

    await client.close()
    await server.stop()


@pytest.mark.asyncio
async def test_receive_when_not_connected():
    """Receiving when not connected returns empty bytes."""
    client = RelayClient("127.0.0.1", 9999)
    data = await client.receive()
    assert data == b''


@pytest.mark.asyncio
async def test_send_when_not_connected():
    """Sending when not connected returns False."""
    client = RelayClient("127.0.0.1", 9999)
    result = await client.send(b"test")
    assert result is False


@pytest.mark.asyncio
async def test_close_cleans_up():
    """Close() cleans up connection state."""
    server = RelayServer(host="127.0.0.1", port=0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    client = RelayClient("127.0.0.1", port)
    await client.connect()
    assert client.is_connected

    await client.close()
    assert not client.is_connected
    assert client._writer is None
    assert client._reader is None

    await server.stop()


@pytest.mark.asyncio
async def test_multiple_sends():
    """Multiple sends all arrive at the server."""
    server = RelayServer(host="127.0.0.1", port=0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    client = RelayClient("127.0.0.1", port)
    await client.connect()

    payloads = [b"msg1", b"msg2", b"msg3"]
    for p in payloads:
        await client.send(p)

    await asyncio.sleep(0.2)

    received = []
    for _ in range(3):
        data = await server.receive()
        if data:
            received.append(data)

    assert len(received) == 3
    assert received == payloads

    await client.close()
    await server.stop()
