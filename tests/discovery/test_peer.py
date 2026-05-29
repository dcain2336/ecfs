import time
import pytest
from ecfs.discovery.peer import Peer, PeerTracker


class TestPeerCreation:
    def test_peer_creation(self):
        """Defaults are correct for a new Peer."""
        peer = Peer(node_id='abc123', name='test-peer')
        assert peer.node_id == 'abc123'
        assert peer.name == 'test-peer'
        assert peer.transports == []
        assert peer.signal_strength == 1.0
        assert peer.last_seen > 0

    def test_peer_hash_eq(self):
        """Peers with same node_id are equal and hashable."""
        p1 = Peer(node_id='abc', name='a')
        p2 = Peer(node_id='abc', name='b')
        assert p1 == p2
        assert hash(p1) == hash(p2)
        assert p1 != Peer(node_id='def', name='c')


class TestPeerStaleDetection:
    def test_peer_not_stale(self):
        """Recently seen peer is not stale."""
        peer = Peer(node_id='abc', name='test', last_seen=time.time())
        assert peer.is_stale is False

    def test_peer_is_stale(self):
        """Old peer is stale."""
        peer = Peer(node_id='abc', name='test', last_seen=time.time() - 60)
        assert peer.is_stale is True


class TestPeerTrackerUpdate:
    def test_peer_tracker_update_new(self):
        """New peer is tracked."""
        tracker = PeerTracker()
        tracker.update('p1', 'peer-one', 'ble')
        peers = tracker.get_all()
        assert len(peers) == 1
        assert peers[0].node_id == 'p1'
        assert 'ble' in peers[0].transports

    def test_peer_tracker_update_existing(self):
        """Existing peer gets updated timestamp and new transport."""
        tracker = PeerTracker()
        tracker.update('p1', 'peer-one', 'ble')
        tracker.update('p1', 'peer-one', 'lora')
        peers = tracker.get_all()
        assert len(peers) == 1
        assert 'ble' in peers[0].transports
        assert 'lora' in peers[0].transports


class TestPeerTrackerGetAll:
    def test_peer_tracker_get_all(self):
        """Returns non-stale peers."""
        tracker = PeerTracker(stale_timeout=0.01)
        tracker.update('p1', 'fresh', 'ble')
        time.sleep(0.02)
        tracker.update('p2', 'fresh2', 'lora')
        peers = tracker.get_all()
        assert len(peers) == 1
        assert peers[0].name == 'fresh2'


class TestPeerTrackerGetBestTransport:
    def test_peer_tracker_get_best_transport(self):
        """Returns lowest priority transport."""
        tracker = PeerTracker()
        tracker.update('p1', 'peer', 'network')
        tracker.update('p1', 'peer', 'ble')
        best = tracker.get_best_transport('p1')
        assert best == 'ble'

    def test_peer_tracker_get_best_transport_unknown(self):
        """Unknown peer returns None."""
        tracker = PeerTracker()
        assert tracker.get_best_transport('unknown') is None


class TestPeerTrackerCallbacks:
    def test_peer_tracker_on_peer_found(self):
        """on_peer_found is called when new peer appears."""
        found = []
        tracker = PeerTracker()
        tracker.on_peer_found(lambda p: found.append(p))
        tracker.update('p1', 'peer', 'ble')
        assert len(found) == 1
        assert found[0].node_id == 'p1'

    def test_peer_tracker_on_peer_lost(self):
        """on_peer_lost is called when stale peer evicted."""
        lost = []
        tracker = PeerTracker(stale_timeout=0.01)
        tracker.on_peer_lost(lambda p: lost.append(p))
        tracker.update('p1', 'peer', 'ble')
        time.sleep(0.02)
        tracker.get_all()  # triggers eviction
        assert len(lost) == 1
