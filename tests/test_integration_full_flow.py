"""Full integration tests for ECFS Phase 5."""

import asyncio
import struct
import pytest

from ecfs.core.engine import ECFSEngine
from ecfs.plugins.null_transport import NullTransport
from ecfs.plugins.base import TransportStatus
from ecfs.relay.client import RelayClient
from ecfs.plugins.relay_server import RelayServer


@pytest.mark.asyncio
async def test_engine_end_to_end():
    """Register two NullTransports, start, send, and receive."""
    engine = ECFSEngine(enable_dedup=False)
    null1 = NullTransport(name="e2e-1", priority=10)
    null2 = NullTransport(name="e2e-2", priority=20)
    engine.register_plugin(null1)
    engine.register_plugin(null2)

    await engine.start()
    assert engine.is_running

    # Send a packet
    payload = b"end-to-end test payload"
    result = await engine.send(payload)
    assert result is True

    # Both plugins should have received the packet
    assert payload in null1.sent_packets
    assert payload in null2.sent_packets

    # Inject a packet into one plugin for receive
    incoming = b"incoming e2e packet"
    null1.queue_packet(incoming)

    received = await engine.receive()
    assert received == incoming

    await engine.stop()
    assert not engine.is_running


@pytest.mark.asyncio
async def test_engine_stats_tracking():
    """Send multiple packets and verify stats are tracked correctly."""
    engine = ECFSEngine(enable_dedup=False)
    null = NullTransport(name="stats-null")
    engine.register_plugin(null)
    await engine.start()

    # Send 3 packets
    for i in range(3):
        result = await engine.send(f"packet-{i}".encode())
        assert result is True

    stats = engine.stats
    assert stats["packets_sent"] == 3
    assert stats["packets_dropped"] == 0
    assert stats["packets_deduped"] == 0


@pytest.mark.asyncio
async def test_engine_plugin_failure_handling():
    """One plugin fails, other succeeds — send still works."""
    engine = ECFSEngine(enable_dedup=False)

    class FailingTransport(NullTransport):
        @property
        def name(self):
            return "failing"

        async def send_packet(self, data):
            raise RuntimeError("Simulated failure")

    failing = FailingTransport(status=TransportStatus.ONLINE)
    working = NullTransport(name="working", priority=50)
    engine.register_plugin(failing)
    engine.register_plugin(working)
    await engine.start()

    result = await engine.send(b"partial success")
    assert result is True
    assert engine.stats["packets_sent"] == 1
    # The working plugin got it
    assert b"partial success" in working.sent_packets


@pytest.mark.asyncio
async def test_relay_server_client_roundtrip():
    """Start a relay server, connect client, send and receive data."""
    server = RelayServer(host="127.0.0.1", port=0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    client = RelayClient("127.0.0.1", port)
    connected = await client.connect()
    assert connected is True

    # Send data from client to server
    payload = b"relay roundtrip data"
    sent = await client.send(payload)
    assert sent is True

    # Give server time to process
    await asyncio.sleep(0.1)

    # Server receives the data
    received = await server.receive()
    assert received == payload

    await client.close()
    await server.stop()
