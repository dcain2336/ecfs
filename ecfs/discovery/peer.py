import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class Peer:
    """A discovered peer node."""
    node_id: str
    name: str
    transports: list = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)
    signal_strength: float = 1.0

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.last_seen) > 30.0

    def __hash__(self):
        return hash(self.node_id)

    def __eq__(self, other):
        return isinstance(other, Peer) and self.node_id == other.node_id


class PeerTracker:
    """Track discovered peers across all transports."""

    def __init__(self, stale_timeout: float = 30.0):
        self._peers: dict[str, Peer] = {}
        self._stale_timeout = stale_timeout
        self._on_peer_found: Optional[Callable] = None
        self._on_peer_lost: Optional[Callable] = None

    def on_peer_found(self, callback: Callable) -> None:
        self._on_peer_found = callback

    def on_peer_lost(self, callback: Callable) -> None:
        self._on_peer_lost = callback

    def update(self, peer_id: str, name: str, transport: str, signal: float = 1.0) -> None:
        """Report a peer sighting from a specific transport."""
        if peer_id not in self._peers:
            peer = Peer(node_id=peer_id, name=name, transports=[transport], signal_strength=signal)
            self._peers[peer_id] = peer
            logger.info('Peer found: %s (%s) via %s', name, peer_id[:8], transport)
            if self._on_peer_found:
                self._on_peer_found(peer)
        else:
            peer = self._peers[peer_id]
            peer.last_seen = time.time()
            peer.signal_strength = signal
            if transport not in peer.transports:
                peer.transports.append(transport)

    def get_peer(self, peer_id: str) -> Optional[Peer]:
        return self._peers.get(peer_id)

    def get_all(self) -> list:
        """Get all non-stale peers."""
        self._evict_stale()
        return list(self._peers.values())

    def get_best_transport(self, peer_id: str) -> Optional[str]:
        """Get the best transport to reach a peer."""
        peer = self._peers.get(peer_id)
        if not peer:
            return None
        # Priority: BLE > LoRa > Ultrasonic > Network > RFID
        priority = {'ble': 10, 'lora': 20, 'ultrasonic': 30, 'network': 40, 'rfid': 50}
        best = None
        best_prio = 999
        for t in peer.transports:
            p = priority.get(t, 100)
            if p < best_prio:
                best = t
                best_prio = p
        return best

    def _evict_stale(self) -> None:
        now = time.time()
        stale = [pid for pid, p in self._peers.items()
                 if (now - p.last_seen) > self._stale_timeout]
        for pid in stale:
            peer = self._peers.pop(pid)
            logger.info('Peer lost: %s (%s)', peer.name, pid[:8])
            if self._on_peer_lost:
                self._on_peer_lost(peer)
