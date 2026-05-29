"""Tests for ecfs.relay.client — RelayClient over HTTP."""

import asyncio
import socket
import time

import pytest

from ecfs.relay.client import RelayClient
from ecfs.relay.server import RelayServer


# ── Helpers ─────────────────────────────────────────────────────────


def _free_port() -> int:
    """Get an ephemeral free port."""
    sock = socket.socket()
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture()
async def relay_server():
    """Start a RelayServer on an ephemeral port, yield (server, url), stop after."""
    port = _free_port()
    server = RelayServer(host="localhost", port=port)
    await server.start()
    url = f"http://localhost:{port}"
    yield server, url
    await server.stop()


def _make_client(url: str, node_id: str = "node_aaaa", name: str = "test-node") -> RelayClient:
    return RelayClient(
        relay_url=url,
        node_id=node_id,
        name=name,
        transports=["internet"],
        heartbeat_interval=999,  # effectively disable background heartbeats
    )


# ── connect() ───────────────────────────────────────────────────────


class TestConnect:
    async def test_connect_returns_true(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        result = await client.connect()
        assert result is True
        assert client.is_connected is True
        await client.disconnect()

    async def test_connect_registers_with_relay(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        await client.connect()

        nodes = await client.get_nodes()
        assert len(nodes) >= 1
        assert any(n["node_id"] == "node_aaaa" for n in nodes)
        await client.disconnect()

    async def test_connect_false_on_bad_url(self):
        client = RelayClient(
            relay_url="http://localhost:1",
            node_id="node_bad",
            name="bad-node",
        )
        result = await client.connect()
        assert result is False
        assert client.is_connected is False


# ── send_fragment() ─────────────────────────────────────────────────


class TestSendFragment:
    async def test_send_fragment_returns_true(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        await client.connect()
        result = await client.send_fragment(b"hello world")
        assert result is True
        await client.disconnect()

    async def test_send_fragment_when_not_connected(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        # Don't connect
        result = await client.send_fragment(b"should fail")
        assert result is False

    async def test_send_fragment_updates_stats(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        await client.connect()
        assert client.stats["fragments_sent"] == 0
        await client.send_fragment(b"data")
        assert client.stats["fragments_sent"] == 1
        await client.send_fragment(b"data2")
        assert client.stats["fragments_sent"] == 2
        await client.disconnect()

    async def test_send_fragment_with_dest(self, relay_server):
        server, url = relay_server
        client = _make_client(url, node_id="node_sender")
        await client.connect()
        result = await client.send_fragment(b"unicast data", dest="node_target")
        assert result is True
        await client.disconnect()


# ── poll() ──────────────────────────────────────────────────────────


class TestPoll:
    async def test_poll_returns_empty_when_no_fragments(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        await client.connect()
        frags = await client.poll()
        assert frags == []
        await client.disconnect()

    async def test_poll_returns_broadcast_fragments(self, relay_server):
        server, url = relay_server

        sender = _make_client(url, node_id="node_sender", name="sender")
        receiver = _make_client(url, node_id="node_receiver", name="receiver")

        await sender.connect()
        await receiver.connect()

        payload = b"broadcast message"
        await sender.send_fragment(payload, dest="*")
        # Give the server a moment to process
        await asyncio.sleep(0.05)

        frags = await receiver.poll()
        assert len(frags) == 1
        assert frags[0] == payload

        await sender.disconnect()
        await receiver.disconnect()

    async def test_poll_returns_unicast_fragments(self, relay_server):
        server, url = relay_server

        sender = _make_client(url, node_id="node_sender", name="sender")
        target = _make_client(url, node_id="node_target", name="target")
        bystander = _make_client(url, node_id="node_bystander", name="bystander")

        await sender.connect()
        await target.connect()
        await bystander.connect()

        payload = b"unicast message"
        await sender.send_fragment(payload, dest="node_target")
        await asyncio.sleep(0.05)

        target_frags = await target.poll()
        bystander_frags = await bystander.poll()

        assert len(target_frags) == 1
        assert target_frags[0] == payload
        assert len(bystander_frags) == 0

        await sender.disconnect()
        await target.disconnect()
        await bystander.disconnect()

    async def test_poll_increments_received_stats(self, relay_server):
        server, url = relay_server

        sender = _make_client(url, node_id="node_sender", name="sender")
        receiver = _make_client(url, node_id="node_receiver", name="receiver")

        await sender.connect()
        await receiver.connect()

        await sender.send_fragment(b"stats test")
        await asyncio.sleep(0.05)

        assert receiver.stats["fragments_received"] == 0
        await receiver.poll()
        assert receiver.stats["fragments_received"] == 1

        await sender.disconnect()
        await receiver.disconnect()

    async def test_poll_when_not_connected(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        # Don't connect
        frags = await client.poll()
        assert frags == []


# ── disconnect() ────────────────────────────────────────────────────


class TestDisconnect:
    async def test_disconnect_marks_disconnected(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        await client.connect()
        assert client.is_connected is True
        await client.disconnect()
        assert client.is_connected is False

    async def test_disconnect_stops_heartbeat(self, relay_server):
        server, url = relay_server
        client = RelayClient(
            relay_url=url,
            node_id="node_aaaa",
            name="test-node",
            heartbeat_interval=0.1,
        )
        await client.connect()
        await client.start_heartbeat()
        assert client._heartbeat_task is not None
        await asyncio.sleep(0.05)
        await client.disconnect()
        assert client._heartbeat_task is None

    async def test_disconnect_idempotent(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        await client.connect()
        await client.disconnect()
        # Second disconnect should not raise
        await client.disconnect()
        assert client.is_connected is False


# ── get_nodes() ─────────────────────────────────────────────────────


class TestGetNodes:
    async def test_get_nodes_empty_initially(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        await client.connect()
        nodes = await client.get_nodes()
        # Our own node should appear since we registered
        assert len(nodes) >= 1
        await client.disconnect()

    async def test_get_nodes_multiple(self, relay_server):
        server, url = relay_server

        c1 = _make_client(url, node_id="node_1111", name="node1")
        c2 = _make_client(url, node_id="node_2222", name="node2")
        c3 = _make_client(url, node_id="node_3333", name="node3")

        await c1.connect()
        await c2.connect()
        await c3.connect()

        nodes = await c1.get_nodes()
        node_ids = {n["node_id"] for n in nodes}
        assert "node_1111" in node_ids
        assert "node_2222" in node_ids
        assert "node_3333" in node_ids

        await c1.disconnect()
        await c2.disconnect()
        await c3.disconnect()


# ── get_health() ────────────────────────────────────────────────────


class TestGetHealth:
    async def test_get_health_returns_status(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        await client.connect()
        health = await client.get_health()
        assert health is not None
        assert health.get("ok") is True
        assert health.get("status") == "running"
        assert "nodes" in health
        assert "stats" in health
        await client.disconnect()

    async def test_get_health_on_bad_url(self):
        client = RelayClient(
            relay_url="http://localhost:1",
            node_id="node_bad",
        )
        health = await client.get_health()
        assert health is None


# ── heartbeat ───────────────────────────────────────────────────────


class TestHeartbeat:
    async def test_send_heartbeat(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        await client.connect()
        result = await client.send_heartbeat()
        assert result is True
        assert client.stats["heartbeats_sent"] == 1
        await client.disconnect()

    async def test_heartbeat_updates_server_state(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        await client.connect()
        initial_seen = server.state.nodes["node_aaaa"].last_seen
        await asyncio.sleep(0.05)
        await client.send_heartbeat()
        assert server.state.nodes["node_aaaa"].last_seen > initial_seen
        await client.disconnect()


# ── stats ───────────────────────────────────────────────────────────


class TestStats:
    async def test_stats_initial_values(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        stats = client.stats
        assert stats["fragments_sent"] == 0
        assert stats["fragments_received"] == 0
        assert stats["heartbeats_sent"] == 0
        assert stats["errors"] == 0

    async def test_stats_returns_copy(self, relay_server):
        server, url = relay_server
        client = _make_client(url)
        s1 = client.stats
        s2 = client.stats
        assert s1 is not s2  # should be a copy
        assert s1 == s2

    async def test_stats_after_operations(self, relay_server):
        server, url = relay_server
        sender = _make_client(url, node_id="node_sender", name="sender")
        receiver = _make_client(url, node_id="node_receiver", name="receiver")

        await sender.connect()
        await receiver.connect()

        await sender.send_fragment(b"test")
        await asyncio.sleep(0.05)
        await receiver.poll()
        await sender.send_heartbeat()

        assert sender.stats["fragments_sent"] == 1
        assert receiver.stats["fragments_received"] == 1
        assert sender.stats["heartbeats_sent"] == 1

        await sender.disconnect()
        await receiver.disconnect()
