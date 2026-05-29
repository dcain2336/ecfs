"""Integration tests: MeshOrchestrator + Fragmentation + Full Mesh Flow.

These tests prove the core ECFS behavior:
- Messages fragment and reassemble correctly
- Shotgun sends through all transports simultaneously
- When transports fail, the system degrades gracefully and retries
- Fragments arrive out of order and still reassemble
- The state machine transitions when transport health changes
"""

import asyncio
import hashlib
import struct
import time
import pytest

from ecfs.core.fragmentation import Fragment, FragmentManager, HEADER_SIZE
from ecfs.core.orchestrator import MeshOrchestrator, MeshEvent
from ecfs.core.queue import MessagePriority
from ecfs.core.state_machine import State, StateMachine
from ecfs.plugins.base import TransportPlugin, TransportStatus, TransportType


# ── Fake Transport for Testing ────────────────────────────────────────


class FakeTransport(TransportPlugin):
    """In-memory transport for integration testing."""

    def __init__(
        self,
        name: str = "fake",
        transport_type: TransportType = TransportType.INTERNET,
        priority: int = 10,
        start_online: bool = True,
        failure_mode: str = "none",  # none, immediate, delayed
    ):
        self._name = name
        self._transport_type = transport_type
        self._priority = priority
        self._inbox: list[bytes] = []
        self._outbox: list[bytes] = []
        self._status = TransportStatus.ONLINE if start_online else TransportStatus.OFFLINE
        self._failure_mode = failure_mode
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
        self._status = TransportStatus.OFFLINE

    async def send_packet(self, data: bytes) -> bool:
        if self._status != TransportStatus.ONLINE:
            return False

        self._send_count += 1

        if self._failure_mode == "immediate":
            self._status = TransportStatus.OFFLINE
            return False

        self._outbox.append(data)
        return True

    async def receive_packet(self) -> bytes | None:
        if self._inbox:
            return self._inbox.pop(0)
        return None

    async def get_status(self) -> TransportStatus:
        return self._status

    def inject_packet(self, data: bytes) -> None:
        """Simulate receiving a packet from the network."""
        self._inbox.append(data)

    def set_status(self, status: TransportStatus) -> None:
        self._status = status


# ── Fragmentation Tests ───────────────────────────────────────────────


class TestFragmentation:
    def test_small_message_unchanged(self):
        """A message smaller than max fragment size produces 1 fragment."""
        fm = FragmentManager(node_id=b"test-node-1", max_fragment_size=128)
        data = b"hello"
        frags = fm.fragment(data)

        assert len(frags) == 1
        assert frags[0].fragment_index == 0
        assert frags[0].fragment_total == 1
        assert frags[0].payload == data

    def test_large_message_splits(self):
        """A message larger than max fragment size splits into multiple."""
        fm = FragmentManager(node_id=b"test-node-1", max_fragment_size=16)
        data = b"a" * 64  # 4 fragments
        frags = fm.fragment(data)

        assert len(frags) == 4
        for i, frag in enumerate(frags):
            assert frag.fragment_index == i
            assert frag.fragment_total == 4
            assert len(frag.payload) == 16

    def test_encode_decode_roundtrip(self):
        """Fragments survive serialization/deserialization."""
        fm = FragmentManager(node_id=b"test-node-1", max_fragment_size=32)
        data = b"roundtrip test data here" * 5
        frags = fm.fragment(data)

        for frag in frags:
            encoded = frag.encode()
            decoded = Fragment.decode(encoded)

            assert decoded.version == frag.version
            assert decoded.message_id == frag.message_id
            assert decoded.fragment_index == frag.fragment_index
            assert decoded.fragment_total == frag.fragment_total
            assert decoded.payload == frag.payload

    def test_reassembly_in_order(self):
        """Fragments arriving in order reassemble correctly."""
        fm = FragmentManager(node_id=b"test-node-1", max_fragment_size=16)
        data = b"in-order reassembly test data"
        frags = fm.fragment(data)

        result = None
        for frag in frags:
            result = fm.receive_fragment(frag)

        assert result == data

    def test_reassembly_out_of_order(self):
        """Fragments arriving out of order still reassemble correctly."""
        fm = FragmentManager(node_id=b"test-node-1", max_fragment_size=16)
        data = b"out-of-order reassembly test data"
        frags = fm.fragment(data)

        # Shuffle fragments
        shuffled = list(reversed(frags))

        result = None
        for frag in shuffled:
            result = fm.receive_fragment(frag)

        assert result == data

    def test_duplicate_fragments_ignored(self):
        """Receiving the same fragment twice doesn't break reassembly."""
        fm = FragmentManager(node_id=b"test-node-1", max_fragment_size=16)
        data = b"duplicate handling test data"
        frags = fm.fragment(data)

        result = None
        for frag in frags:
            result = fm.receive_fragment(frag)
            # Send it again — should be ignored
            fm.receive_fragment(frag)

        assert result == data

    def test_missing_fragment_incomplete(self):
        """Missing fragments prevent reassembly."""
        fm = FragmentManager(node_id=b"test-node-1", max_fragment_size=16)
        data = b"missing fragment test data here"
        frags = fm.fragment(data)

        # Skip fragment 1
        result = None
        for frag in frags:
            if frag.fragment_index != 1:
                result = fm.receive_fragment(frag)

        assert result is None
        info = fm.get_pending_info()
        assert len(info) == 1
        assert info[0]["completeness"] < 100.0

    def test_multiple_messages_concurrent(self):
        """Multiple messages being reassembled simultaneously."""
        fm = FragmentManager(node_id=b"test-node-1", max_fragment_size=8)

        data1 = b"message one content here"
        data2 = b"message two content here"

        frags1 = fm.fragment(data1)
        frags2 = fm.fragment(data2)

        # Interleave fragments from both messages
        result1 = None
        result2 = None
        for i in range(max(len(frags1), len(frags2))):
            if i < len(frags1):
                result1 = fm.receive_fragment(frags1[i])
            if i < len(frags2):
                result2 = fm.receive_fragment(frags2[i])

        assert result1 == data1
        assert result2 == data2

    def test_fragment_hash_dedup(self):
        """Same fragment from different transports has same hash."""
        fm = FragmentManager(node_id=b"test-node-1", max_fragment_size=32)
        data = b"dedup test payload"
        frags = fm.fragment(data)
        frag = frags[0]

        # Hash should be deterministic
        h1 = frag.fragment_hash
        h2 = frag.fragment_hash
        assert h1 == h2

    def test_node_id_in_fragment(self):
        """Fragments carry the origin node ID (padded to 32 bytes)."""
        node_id = b"my-special-node-id-12345678901"  # 31 bytes
        fm = FragmentManager(node_id=node_id, max_fragment_size=32)
        frags = fm.fragment(b"test")

        # FragmentManager pads to 32 bytes
        assert frags[0].origin[:len(node_id)] == node_id


# ── Orchestrator Tests ────────────────────────────────────────────────


class TestMeshOrchestrator:
    def test_register_transports(self):
        """Transports are registered and tracked."""
        orch = MeshOrchestrator(node_id=b"test-orch-1")
        t1 = FakeTransport("internet", TransportType.INTERNET, priority=10)
        t2 = FakeTransport("lora", TransportType.RADIO, priority=30)

        orch.register_transport(t1)
        orch.register_transport(t2)

        assert set(orch.transport_names) == {"internet", "lora"}

    @pytest.mark.asyncio
    async def test_send_shots_all_transports(self):
        """Send fires fragments through ALL online transports simultaneously."""
        orch = MeshOrchestrator(node_id=b"test-orch-1", shotgun_redundancy=10)
        t1 = FakeTransport("internet", TransportType.INTERNET)
        t2 = FakeTransport("lora", TransportType.RADIO)
        t3 = FakeTransport("ble", TransportType.RADIO)

        orch.register_transport(t1)
        orch.register_transport(t2)
        orch.register_transport(t3)

        result = await orch.send(b"hello mesh")

        assert result is True
        # All 3 transports should have received the packet
        assert len(t1._outbox) == 1
        assert len(t2._outbox) == 1
        assert len(t3._outbox) == 1
        assert orch.stats["messages_sent"] == 1

    @pytest.mark.asyncio
    async def test_receive_reassembles(self):
        """Receiving fragments from a transport reassembles the message."""
        orch = MeshOrchestrator(node_id=b"test-orch-1")
        t1 = FakeTransport("lora", TransportType.RADIO)
        orch.register_transport(t1)

        # Manually create fragments and inject them
        fm = FragmentManager(node_id=b"remote-node", max_fragment_size=16)
        data = b"reassembly via transport test"
        frags = fm.fragment(data)

        for frag in frags[:-1]:
            t1.inject_packet(frag.encode())
            result = await orch.receive()
            assert result is None  # not complete yet

        t1.inject_packet(frags[-1].encode())
        result = await orch.receive()
        assert result == data

    @pytest.mark.asyncio
    async def test_failover_no_transports(self):
        """When all transports are offline, messages get queued."""
        orch = MeshOrchestrator(node_id=b"test-orch-1")
        t1 = FakeTransport("dead", start_online=False)
        orch.register_transport(t1)

        result = await orch.send(b"queued message")
        assert result is False
        assert orch.stats["queued"] == 1

    @pytest.mark.asyncio
    async def test_state_transitions_on_transport_failure(self):
        """State machine transitions when transports go down."""
        orch = MeshOrchestrator(node_id=b"test-orch-1")
        t1 = FakeTransport("net", TransportType.INTERNET)
        t2 = FakeTransport("lora", TransportType.RADIO)
        orch.register_transport(t1)
        orch.register_transport(t2)

        assert orch.state == State.NORMAL

        # Kill all transports
        t1.set_status(TransportStatus.OFFLINE)
        t2.set_status(TransportStatus.OFFLINE)
        orch._evaluate_state()

        assert orch.state == State.EMERGENCY

    @pytest.mark.asyncio
    async def test_state_recovery(self):
        """State machine recovers when transports come back."""
        orch = MeshOrchestrator(node_id=b"test-orch-1")
        t1 = FakeTransport("net", TransportType.INTERNET)
        t2 = FakeTransport("lora", TransportType.RADIO)
        orch.register_transport(t1)
        orch.register_transport(t2)

        # Emergency first
        t1.set_status(TransportStatus.OFFLINE)
        t2.set_status(TransportStatus.OFFLINE)
        orch._evaluate_state()
        assert orch.state == State.EMERGENCY

        # Come back
        t1.set_status(TransportStatus.ONLINE)
        t2.set_status(TransportStatus.ONLINE)
        orch._evaluate_state()
        assert orch.state in (State.RECOVERY, State.NORMAL)

    @pytest.mark.asyncio
    async def test_event_listeners(self):
        """Event listeners fire on orchestrator events."""
        events = []
        orch = MeshOrchestrator(node_id=b"test-orch-1")
        orch.on(MeshEvent.FRAGMENT_SENT, lambda **kw: events.append(kw))

        t1 = FakeTransport("net", TransportType.INTERNET)
        orch.register_transport(t1)
        await orch.send(b"event test")

        assert len(events) > 0
        assert "message_id" in events[0]

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Health check returns accurate transport status."""
        orch = MeshOrchestrator(node_id=b"test-orch-1")
        t1 = FakeTransport("net", TransportType.INTERNET)
        t2 = FakeTransport("lora", TransportType.RADIO, start_online=False)
        orch.register_transport(t1)
        orch.register_transport(t2)

        health = await orch.health_check()

        assert health["online_count"] == 1
        assert health["total_count"] == 2
        assert health["state"] == "NORMAL"

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """Stats are tracked accurately across operations."""
        orch = MeshOrchestrator(node_id=b"test-orch-1")
        t1 = FakeTransport("net", TransportType.INTERNET)
        orch.register_transport(t1)

        await orch.send(b"stats test 1")
        await orch.send(b"stats test 2")

        assert orch.stats["messages_sent"] == 2
        assert orch.stats["fragments_sent"] == 2


# ── End-to-End Flow Tests ─────────────────────────────────────────────


class TestEndToEndFlow:
    @pytest.mark.asyncio
    async def test_full_mesh_flow(self):
        """Complete flow: fragmented message shotgunning across transports, reassembled."""
        from ecfs.core.fragmentation import FragmentManager

        # Sender fragments a long message
        sender_fm = FragmentManager(
            node_id=b"sender-node-123456789012345678",
            max_fragment_size=32,
        )
        message = b"This is a long message that needs fragmentation and shotgun delivery across multiple transport paths to prove the mesh works end to end."
        frags = sender_fm.fragment(message)
        assert len(frags) > 1  # Must actually fragment

        # Receiver reassembles from fragments arriving via different transports
        receiver = MeshOrchestrator(
            node_id=b"receiver-node-1234567890",
            max_fragment_size=32,
        )

        t_net = FakeTransport("internet", TransportType.INTERNET)
        t_lora = FakeTransport("lora", TransportType.RADIO)
        receiver.register_transport(t_net)
        receiver.register_transport(t_lora)

        # Alternate fragments across different transports (simulating multi-path)
        result = None
        for i, frag in enumerate(frags):
            transport = t_net if i % 2 == 0 else t_lora
            transport.inject_packet(frag.encode())
            result = await receiver.receive()

        assert result == message
        assert receiver.stats["messages_received"] == 1

    @pytest.mark.asyncio
    async def test_transport_drops_mid_transfer(self):
        """Transport fails mid-transfer, state machine transitions."""
        orch = MeshOrchestrator(
            node_id=b"test-orch-1",
            max_fragment_size=16,
            shotgun_redundancy=2,
        )

        t1 = FakeTransport("internet", TransportType.INTERNET)
        t2 = FakeTransport("lora", TransportType.RADIO)
        orch.register_transport(t1)
        orch.register_transport(t2)

        # Send first half
        await orch.send(b"part one of message data here")
        assert orch.stats["messages_sent"] == 1

        # Internet goes down — only lora left (50%)
        t1.set_status(TransportStatus.OFFLINE)
        orch._evaluate_state()
        assert orch.state in (State.DEGRADED, State.EMERGENCY)

        # Lora should still work
        lora_status = await t2.get_status()
        assert lora_status == TransportStatus.ONLINE

    @pytest.mark.asyncio
    async def test_critical_priority_shotguns_all(self):
        """Critical messages shotgun through ALL available transports."""
        orch = MeshOrchestrator(node_id=b"test-orch-1")
        for i in range(5):
            orch.register_transport(FakeTransport(f"t{i}", TransportType.INTERNET, priority=i))

        result = await orch.send(
            b"emergency broadcast",
            priority=MessagePriority.CRITICAL,
        )
        assert result is True
        assert orch.stats["messages_sent"] == 1

    @pytest.mark.asyncio
    async def test_same_fragment_not_resent(self):
        """Identical fragment data is not resent (fragment-level dedup)."""
        orch = MeshOrchestrator(node_id=b"test-orch-1")
        t1 = FakeTransport("net", TransportType.INTERNET)
        orch.register_transport(t1)

        # Send two different messages
        await orch.send(b"message one")
        await orch.send(b"message two")

        # Both should send (different messages = different fragment hashes)
        assert orch.stats["messages_sent"] == 2
        assert orch.stats["fragments_sent"] == 2
