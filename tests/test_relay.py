"""Tests for ECFS mesh relay — the 'water' behavior.

Every node forwards fragments it hasn't seen before through all
available transports. This creates organic flow where packets move
through the mesh hop by hop, each node acting as both receiver and router.
"""

import asyncio
import time

import pytest

from ecfs.core.fragmentation import Fragment, FragmentManager
from ecfs.core.orchestrator import MeshEvent, MeshOrchestrator
from ecfs.core.queue import MessagePriority
from ecfs.plugins.base import TransportPlugin, TransportStatus, TransportType


# ── Fake Transport ─────────────────────────────────────────────────


class FakeTransport(TransportPlugin):
    """In-memory transport for testing relay behavior."""

    def __init__(
        self,
        name: str,
        transport_type: TransportType = TransportType.INTERNET,
        priority: int = 10,
        start_online: bool = True,
    ):
        self._name = name
        self._transport_type = transport_type
        self._priority = priority
        self._online = start_online
        self._inbox: list[bytes] = []
        self._outbox: list[bytes] = []
        self._send_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def transport_type(self) -> TransportType:
        return self._transport_type

    @property
    def priority(self) -> int:
        return self._priority

    async def initialize(self) -> None:
        pass

    async def teardown(self) -> None:
        pass

    async def send_packet(self, data: bytes) -> bool:
        if not self._online:
            return False
        self._outbox.append(data)
        self._send_count += 1
        return True

    async def receive_packet(self) -> bytes | None:
        if not self._inbox:
            return None
        return self._inbox.pop(0)

    async def get_status(self) -> TransportStatus:
        return TransportStatus.ONLINE if self._online else TransportStatus.OFFLINE

    def inject_packet(self, data: bytes) -> None:
        """Simulate receiving a packet from the network."""
        self._inbox.append(data)

    def set_status(self, online: bool) -> None:
        self._online = online


# ── Relay Tests ────────────────────────────────────────────────────


class TestRelayBehavior:
    @pytest.mark.asyncio
    async def test_relay_fragment_from_another_node(self):
        """Fragments from another node are forwarded through other transports."""
        relay = MeshOrchestrator(node_id=b"relay-node-aaaa", enable_relay=True)
        t1 = FakeTransport("lora", TransportType.RADIO)
        t2 = FakeTransport("ble", TransportType.RADIO, priority=5)
        relay.register_transport(t1)
        relay.register_transport(t2)

        # Remote sender creates a fragment (origin != relay's node_id)
        sender_fm = FragmentManager(node_id=b"remote-sender-zzzz", max_fragment_size=32)
        frags = sender_fm.fragment(b"hello from remote world, relay this please")
        assert len(frags) > 0

        # Fragment arrives on lora
        t1.inject_packet(frags[0].encode())
        await relay.receive()

        # It should be relayed through ble (the OTHER transport)
        assert t2._send_count == 1
        assert relay.stats["fragments_relayed"] == 1
        assert relay.stats["fragments_received"] == 1

    @pytest.mark.asyncio
    async def test_relay_does_not_send_back_to_source(self):
        """Relay never sends a fragment back through the transport it came from."""
        relay = MeshOrchestrator(node_id=b"relay-node-bbbb", enable_relay=True)
        t1 = FakeTransport("lora", TransportType.RADIO)
        t2 = FakeTransport("ble", TransportType.RADIO, priority=5)
        relay.register_transport(t1)
        relay.register_transport(t2)

        sender_fm = FragmentManager(node_id=b"remote-sender-zzzz", max_fragment_size=32)
        frags = sender_fm.fragment(b"relay test payload here yes")

        # Fragment arrives on lora
        t1.inject_packet(frags[0].encode())
        await relay.receive()

        # Should NOT be sent back through lora
        assert t1._send_count == 0
        # Should be sent through ble
        assert t2._send_count == 1

    @pytest.mark.asyncio
    async def test_relay_disabled_does_not_forward(self):
        """When relay is disabled, fragments from other nodes are NOT forwarded."""
        relay = MeshOrchestrator(node_id=b"relay-node-cccc", enable_relay=False)
        t1 = FakeTransport("lora", TransportType.RADIO)
        t2 = FakeTransport("ble", TransportType.RADIO, priority=5)
        relay.register_transport(t1)
        relay.register_transport(t2)

        sender_fm = FragmentManager(node_id=b"remote-sender-zzzz", max_fragment_size=32)
        frags = sender_fm.fragment(b"should not relay this")

        t1.inject_packet(frags[0].encode())
        await relay.receive()

        # Neither transport should have sent anything
        assert t1._send_count == 0
        assert t2._send_count == 0
        assert relay.stats["fragments_relayed"] == 0

    @pytest.mark.asyncio
    async def test_own_fragments_not_relayed(self):
        """Fragments originated by THIS node are reassembled, not relayed."""
        orch = MeshOrchestrator(node_id=b"self-node-dddd", enable_relay=True)
        t1 = FakeTransport("lora", TransportType.RADIO)
        t2 = FakeTransport("ble", TransportType.RADIO, priority=5)
        orch.register_transport(t1)
        orch.register_transport(t2)

        # Create fragments using the SAME node_id as the orchestrator
        fm = FragmentManager(node_id=b"self-node-dddd", max_fragment_size=32)
        frags = fm.fragment(b"my own fragments come back to me")

        for frag in frags:
            t1.inject_packet(frag.encode())

        # All fragments arrive, should be reassembled (not relayed)
        result = None
        for _ in frags:
            result = await orch.receive()

        assert result == b"my own fragments come back to me"
        # Fragments from self should NOT be relayed
        assert t2._send_count == 0
        assert orch.stats["fragments_relayed"] == 0

    @pytest.mark.asyncio
    async def test_relay_dedup_prevents_loops(self):
        """Same fragment is only relayed once, even if it arrives twice."""
        relay = MeshOrchestrator(node_id=b"relay-node-eeee", enable_relay=True)
        t1 = FakeTransport("lora", TransportType.RADIO)
        t2 = FakeTransport("ble", TransportType.RADIO, priority=5)
        t3 = FakeTransport("wifi", TransportType.INTERNET, priority=3)
        relay.register_transport(t1)
        relay.register_transport(t2)
        relay.register_transport(t3)

        sender_fm = FragmentManager(node_id=b"remote-sender-zzzz", max_fragment_size=32)
        frags = sender_fm.fragment(b"dedup relay test data payload")
        frag_bytes = frags[0].encode()

        # Fragment arrives on lora → relayed to ble + wifi
        t1.inject_packet(frag_bytes)
        await relay.receive()
        assert t2._send_count == 1
        assert t3._send_count == 1

        # Same fragment arrives on ble → should be deduped, NOT relayed again.
        # Dedup fires at the receive() level (_seen_fragments) before _relay_fragment.
        t2.inject_packet(frag_bytes)
        await relay.receive()
        assert t1._send_count == 0  # not sent back to lora
        assert t3._send_count == 1  # wifi count unchanged (not re-relayed)
        assert relay.stats["deduped"] >= 1  # deduped at receive level

    @pytest.mark.asyncio
    async def test_relay_to_all_available_transports(self):
        """Fragment is relayed through ALL available transports except source."""
        relay = MeshOrchestrator(node_id=b"relay-node-ffff", enable_relay=True)
        t1 = FakeTransport("lora", TransportType.RADIO)
        t2 = FakeTransport("ble", TransportType.RADIO, priority=5)
        t3 = FakeTransport("wifi", TransportType.INTERNET, priority=3)
        t4 = FakeTransport("net", TransportType.INTERNET, priority=1)
        relay.register_transport(t1)
        relay.register_transport(t2)
        relay.register_transport(t3)
        relay.register_transport(t4)

        sender_fm = FragmentManager(node_id=b"remote-sender-zzzz", max_fragment_size=32)
        frags = sender_fm.fragment(b"multi transport relay test")
        t1.inject_packet(frags[0].encode())
        await relay.receive()

        # Should be relayed to all 3 other transports
        assert t2._send_count == 1
        assert t3._send_count == 1
        assert t4._send_count == 1
        assert relay.stats["fragments_relayed"] == 1

    @pytest.mark.asyncio
    async def test_relay_events_emitted(self):
        """FRAGMENT_RELAYED event fires when a fragment is forwarded."""
        relay = MeshOrchestrator(node_id=b"relay-node-gggg", enable_relay=True)
        t1 = FakeTransport("lora", TransportType.RADIO)
        t2 = FakeTransport("ble", TransportType.RADIO, priority=5)
        relay.register_transport(t1)
        relay.register_transport(t2)

        events = []
        relay.on(MeshEvent.FRAGMENT_RELAYED, lambda **kw: events.append(kw))

        sender_fm = FragmentManager(node_id=b"remote-sender-zzzz", max_fragment_size=32)
        frags = sender_fm.fragment(b"event relay test")
        t1.inject_packet(frags[0].encode())
        await relay.receive()

        assert len(events) == 1
        assert events[0]["from_transport"] == "lora"
        assert "ble" in events[0]["relayed_via"]
        assert events[0]["origin"] == b"remote-sender-zzzz".hex()[:8]

    @pytest.mark.asyncio
    async def test_ttl_drop_old_fragments(self):
        """Fragments older than MAX_HOP_COUNT * 2s are dropped."""
        relay = MeshOrchestrator(node_id=b"relay-node-hhhh", enable_relay=True)
        t1 = FakeTransport("lora", TransportType.RADIO)
        t2 = FakeTransport("ble", TransportType.RADIO, priority=5)
        relay.register_transport(t1)
        relay.register_transport(t2)

        sender_fm = FragmentManager(node_id=b"remote-sender-zzzz", max_fragment_size=32)
        frags = sender_fm.fragment(b"old fragment ttl drop test")
        frag = frags[0]

        # Artificially age the fragment
        frag.timestamp = time.time() - 100.0  # 100 seconds old > 16*2 = 32s

        t1.inject_packet(frag.encode())
        await relay.receive()

        # Should be dropped, not relayed
        assert t2._send_count == 0
        assert relay.stats["fragments_dropped_ttl"] == 1

    @pytest.mark.asyncio
    async def test_health_check_includes_relay_stats(self):
        """Health check reports relay status."""
        orch = MeshOrchestrator(node_id=b"relay-node-iiii", enable_relay=True)
        t1 = FakeTransport("net", TransportType.INTERNET)
        orch.register_transport(t1)

        health = await orch.health_check()
        assert health["relay_enabled"] is True
        assert health["relay_cache_size"] == 0
        assert health["relay_forward_count"] == 0
        assert health["relay_drop_count"] == 0


class TestMultiHopRelay:
    @pytest.mark.asyncio
    async def test_three_node_chain(self):
        """A → B relay → C destination. Three nodes, chain never breaks."""
        # Create three nodes
        node_a = MeshOrchestrator(node_id=b"node-a-AAAAAAAAAAAAAAAA", enable_relay=True)
        node_b = MeshOrchestrator(node_id=b"node-b-BBBBBBBBBBBBBBBBBB", enable_relay=True)
        node_c = MeshOrchestrator(node_id=b"node-c-CCCCCCCCCCCCCCCC", enable_relay=True)

        # Node A has one transport (lora_a)
        t_a = FakeTransport("lora_a", TransportType.RADIO)
        node_a.register_transport(t_a)

        # Node B has two transports: lora_b (connected to A) and ble_b (connected to C)
        t_b_lora = FakeTransport("lora_b", TransportType.RADIO)
        t_b_ble = FakeTransport("ble_b", TransportType.RADIO, priority=5)
        node_b.register_transport(t_b_lora)
        node_b.register_transport(t_b_ble)

        # Node C has one transport (ble_c, connected to B)
        t_c = FakeTransport("ble_c", TransportType.RADIO)
        node_c.register_transport(t_c)

        # Node A sends a message
        message = b"chain test: A sends, B relays, C receives"
        await node_a.send(message)

        # Grab what A sent
        assert len(t_a._outbox) > 0
        frag_data = t_a._outbox[0]

        # Deliver to B (simulating the physical transport link)
        t_b_lora.inject_packet(frag_data)
        result_b = await node_b.receive()
        # B may or may not reassemble (depends on fragment count)
        # But B should have relayed to ble_b
        assert t_b_ble._send_count >= 1

        # Deliver to C (from B's relay)
        assert len(t_b_ble._outbox) > 0
        t_c.inject_packet(t_b_ble._outbox[0])
        result_c = await node_c.receive()

        # C should have reassembled the message
        assert result_c == message
        # C should not have relayed (no other transports)
        assert node_c.stats["fragments_relayed"] == 0

    @pytest.mark.asyncio
    async def test_shotgun_relay_multipath(self):
        """Fragments shotgunning through multiple transports are deduped at relay."""
        relay = MeshOrchestrator(node_id=b"relay-node-jjjj", enable_relay=True)
        t1 = FakeTransport("lora", TransportType.RADIO)
        t2 = FakeTransport("ble", TransportType.RADIO, priority=5)
        t3 = FakeTransport("wifi", TransportType.INTERNET, priority=3)
        relay.register_transport(t1)
        relay.register_transport(t2)
        relay.register_transport(t3)

        sender = MeshOrchestrator(
            node_id=b"remote-sender-zzzz", enable_relay=False
        )
        t_sender = FakeTransport("sender_lora", TransportType.RADIO)
        sender.register_transport(t_sender)

        # Sender shotguns with redundancy=2, so 2 transports
        t_sender2 = FakeTransport("sender_ble", TransportType.RADIO, priority=5)
        sender.register_transport(t_sender2)

        message = b"shotgun relay dedup test"
        await sender.send(message, priority=MessagePriority.NORMAL)

        # Two copies of the same fragment arrive at the relay (from different transports)
        assert len(t_sender._outbox) >= 1
        frag_data = t_sender._outbox[0]

        # First arrival → relayed
        t1.inject_packet(frag_data)
        await relay.receive()
        relay_count_after_first = t2._send_count + t3._send_count

        # Second arrival (same data, different transport) → deduped
        t2.inject_packet(frag_data)
        await relay.receive()

        # No additional relays from the duplicate
        relay_count_after_second = t2._send_count + t3._send_count
        assert relay_count_after_second == relay_count_after_first
        assert relay.stats["deduped"] >= 1  # deduped at receive level
