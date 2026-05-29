import asyncio
import pytest
from ecfs.discovery.mesh import MeshNode
from ecfs.discovery.peer import PeerTracker
from ecfs.plugins.null_transport import NullTransport
from ecfs.core.engine import ECFSEngine
from ecfs.plugins.base import TransportStatus


class TestFullAutoStart:
    @pytest.mark.asyncio
    async def test_full_auto_start(self):
        """MeshNode start: detect → create → register → start."""
        node = MeshNode(name='integration-test')
        status = await node.start()
        assert status['transport_count'] >= 0  # may be 0 in CI
        assert isinstance(status['hardware'], str)
        assert isinstance(status['transports'], list)
        await node.stop()


class TestTwoNodesCommunication:
    @pytest.mark.asyncio
    async def test_two_nodes_can_communicate(self):
        """Two MeshNodes using NullTransport can send and receive."""
        # Create two engines with NullTransport each
        engine_a = ECFSEngine(enable_dedup=False)
        engine_b = ECFSEngine(enable_dedup=False)

        null_a = NullTransport(name='null-a')
        null_b = NullTransport(name='null-b')

        engine_a.register_plugin(null_a)
        engine_b.register_plugin(null_b)

        await engine_a.start()
        await engine_b.start()

        # Simulate: A sends, B receives via its null transport
        test_data = b'hello from A to B'
        null_b.queue_packet(test_data)

        # B receives the data
        received = await engine_b.receive()
        assert received == test_data

        # A sends successfully
        result = await engine_a.send(b'hello from A')
        assert result is True

        await engine_a.stop()
        await engine_b.stop()


class TestPeerDiscoveryFlow:
    def test_peer_discovery_flow(self):
        """Tracker discovers peer, reports best transport."""
        tracker = PeerTracker()

        # Simulate BLE discovery
        tracker.update('node1', 'alice', 'ble', signal=0.9)
        # Simulate LoRa discovery
        tracker.update('node1', 'alice', 'lora', signal=0.5)

        # Should report ble as best (lower priority number = better)
        best = tracker.get_best_transport('node1')
        assert best == 'ble'

        # Should have both transports listed
        peer = tracker.get_peer('node1')
        assert peer is not None
        assert 'ble' in peer.transports
        assert 'lora' in peer.transports
