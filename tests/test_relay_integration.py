"""End-to-end integration tests for the ECFS HTTP relay.

Two (or more) RelayClient instances communicate through a real RelayServer,
proving the full message path works.
"""

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


def _make_client(url: str, node_id: str, name: str = "ecfs-node") -> RelayClient:
    return RelayClient(
        relay_url=url,
        node_id=node_id,
        name=name,
        transports=["internet"],
        heartbeat_interval=999,  # disable background heartbeats for tests
    )


async def _sleep():
    """Small yield to let the relay process HTTP requests."""
    await asyncio.sleep(0.05)


# ── Basic Two-Node Communication ────────────────────────────────────


class TestTwoNodeCommunication:
    async def test_node_a_broadcast_node_b_receives(self, relay_server):
        """node_a sends a broadcast fragment; node_b polls and receives it."""
        server, url = relay_server

        node_a = _make_client(url, node_id="node_aaaa", name="node-a")
        node_b = _make_client(url, node_id="node_bbbb", name="node-b")

        await node_a.connect()
        await node_b.connect()

        payload = b"hello from node_a to everyone"
        sent = await node_a.send_fragment(payload, dest="*")
        assert sent is True

        await _sleep()

        frags = await node_b.poll()
        assert len(frags) == 1
        assert frags[0] == payload

        # node_a should NOT receive its own broadcast
        frags_a = await node_a.poll()
        assert len(frags_a) == 0

        await node_a.disconnect()
        await node_b.disconnect()

    async def test_bidirectional_communication(self, relay_server):
        """A sends to B, then B sends to A."""
        server, url = relay_server

        node_a = _make_client(url, node_id="node_aaaa", name="node-a")
        node_b = _make_client(url, node_id="node_bbbb", name="node-b")

        await node_a.connect()
        await node_b.connect()

        # A → B
        msg_ab = b"ping from A"
        await node_a.send_fragment(msg_ab, dest="*")
        await _sleep()

        frags_b = await node_b.poll()
        assert len(frags_b) == 1
        assert frags_b[0] == msg_ab

        # B → A
        msg_ba = b"pong from B"
        await node_b.send_fragment(msg_ba, dest="*")
        await _sleep()

        frags_a = await node_a.poll()
        assert len(frags_a) == 1
        assert frags_a[0] == msg_ba

        await node_a.disconnect()
        await node_b.disconnect()

    async def test_directed_unicast(self, relay_server):
        """node_a sends directly to node_b; bystander node_c gets nothing."""
        server, url = relay_server

        node_a = _make_client(url, node_id="node_aaaa", name="node-a")
        node_b = _make_client(url, node_id="node_bbbb", name="node-b")
        node_c = _make_client(url, node_id="node_cccc", name="node-c")

        await node_a.connect()
        await node_b.connect()
        await node_c.connect()

        payload = b"secret message for B only"
        await node_a.send_fragment(payload, dest="node_bbbb")
        await _sleep()

        frags_b = await node_b.poll()
        frags_c = await node_c.poll()

        assert len(frags_b) == 1
        assert frags_b[0] == payload
        assert len(frags_c) == 0

        await node_a.disconnect()
        await node_b.disconnect()
        await node_c.disconnect()


# ── Multi-Node Broadcast ────────────────────────────────────────────


class TestMultiNode:
    async def test_three_nodes_one_sender_two_receivers(self, relay_server):
        """One node broadcasts, two others receive the same fragment."""
        server, url = relay_server

        sender = _make_client(url, node_id="node_send", name="sender")
        recv1 = _make_client(url, node_id="node_recv1", name="receiver1")
        recv2 = _make_client(url, node_id="node_recv2", name="receiver2")

        await sender.connect()
        await recv1.connect()
        await recv2.connect()

        payload = b"broadcast to all"
        await sender.send_fragment(payload, dest="*")
        await _sleep()

        frags1 = await recv1.poll()
        frags2 = await recv2.poll()

        assert len(frags1) == 1
        assert frags1[0] == payload
        assert len(frags2) == 1
        assert frags2[0] == payload

        # Sender doesn't get its own broadcast
        sender_frags = await sender.poll()
        assert len(sender_frags) == 0

        await sender.disconnect()
        await recv1.disconnect()
        await recv2.disconnect()

    async def test_three_nodes_each_sends(self, relay_server):
        """Each of three nodes sends a broadcast; the other two receive it."""
        server, url = relay_server

        nodes = [
            _make_client(url, node_id=f"node_{i:04d}", name=f"node-{i}")
            for i in range(3)
        ]

        for n in nodes:
            await n.connect()

        messages = [f"message from node {i}".encode() for i in range(3)]
        for i, n in enumerate(nodes):
            await n.send_fragment(messages[i], dest="*")

        await _sleep()

        # Each node should receive 2 fragments (from the other 2 nodes)
        for i, n in enumerate(nodes):
            frags = await n.poll()
            assert len(frags) == 2, f"node-{i} expected 2 fragments, got {len(frags)}"

        for n in nodes:
            await n.disconnect()


# ── Fragment Ordering ───────────────────────────────────────────────


class TestFragmentOrdering:
    async def test_multiple_fragments_all_arrive(self, relay_server):
        """Send multiple fragments; all arrive at the receiver."""
        server, url = relay_server

        sender = _make_client(url, node_id="node_send", name="sender")
        receiver = _make_client(url, node_id="node_recv", name="receiver")

        await sender.connect()
        await receiver.connect()

        payloads = [f"fragment-{i}".encode() for i in range(10)]
        for p in payloads:
            await sender.send_fragment(p, dest="*")

        await _sleep()

        frags = await receiver.poll()
        assert len(frags) == 10
        assert frags == payloads  # order should be preserved

        await sender.disconnect()
        await receiver.disconnect()

    async def test_large_fragment(self, relay_server):
        """A large fragment (64KB) is correctly relayed."""
        server, url = relay_server

        sender = _make_client(url, node_id="node_send", name="sender")
        receiver = _make_client(url, node_id="node_recv", name="receiver")

        await sender.connect()
        await receiver.connect()

        large_payload = b"x" * 65536
        await sender.send_fragment(large_payload, dest="*")
        await _sleep()

        frags = await receiver.poll()
        assert len(frags) == 1
        assert frags[0] == large_payload

        await sender.disconnect()
        await receiver.disconnect()

    async def test_empty_fragment(self, relay_server):
        """An empty fragment is relayed correctly."""
        server, url = relay_server

        sender = _make_client(url, node_id="node_send", name="sender")
        receiver = _make_client(url, node_id="node_recv", name="receiver")

        await sender.connect()
        await receiver.connect()

        await sender.send_fragment(b"", dest="*")
        await _sleep()

        frags = await receiver.poll()
        assert len(frags) == 1
        assert frags[0] == b""

        await sender.disconnect()
        await receiver.disconnect()


# ── Relay Health During Communication ────────────────────────────────


class TestHealthDuringCommunication:
    async def test_health_reflects_active_nodes(self, relay_server):
        """Health endpoint reports correct node count during active communication."""
        server, url = relay_server

        clients = []
        for i in range(5):
            c = _make_client(url, node_id=f"node_{i:04d}", name=f"node-{i}")
            await c.connect()
            clients.append(c)

        health = await clients[0].get_health()
        assert health is not None
        assert health["nodes"] == 5

        # Simulate two nodes going stale (server evicts after 60s)
        for nid in ("node_0000", "node_0001"):
            if nid in server.state.nodes:
                server.state.nodes[nid].last_seen = time.time() - 120

        health = await clients[2].get_health()
        assert health is not None
        assert health["nodes"] == 3

        for c in clients[2:]:
            await c.disconnect()

    async def test_health_stats_increase_during_communication(self, relay_server):
        """Server stats increase as fragments flow through the relay."""
        server, url = relay_server

        sender = _make_client(url, node_id="node_send", name="sender")
        receiver = _make_client(url, node_id="node_recv", name="receiver")

        await sender.connect()
        await receiver.connect()

        initial_fragments = server.state.stats["fragments_received"]

        for i in range(5):
            await sender.send_fragment(f"msg-{i}".encode(), dest="*")

        await _sleep()
        await receiver.poll()

        assert server.state.stats["fragments_received"] == initial_fragments + 5
        assert server.state.stats["fragments_relayed"] >= 5

        await sender.disconnect()
        await receiver.disconnect()

    async def test_concurrent_senders(self, relay_server):
        """Multiple senders can transmit simultaneously."""
        server, url = relay_server

        receiver = _make_client(url, node_id="node_recv", name="receiver")
        senders = [
            _make_client(url, node_id=f"sender_{i:04d}", name=f"sender-{i}")
            for i in range(3)
        ]

        await receiver.connect()
        for s in senders:
            await s.connect()

        # Each sender sends a unique message
        for i, s in enumerate(senders):
            await s.send_fragment(f"from-sender-{i}".encode(), dest="*")

        await _sleep()

        frags = await receiver.poll()
        assert len(frags) == 3

        for s in senders:
            await s.disconnect()
        await receiver.disconnect()
