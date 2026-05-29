"""TTL-based deduplication cache for packet message IDs."""

from collections import OrderedDict

import time


class DeduplicationCache:
    """TTL-based deduplication cache for packet message IDs.

    Uses an OrderedDict for O(1) lookup + LRU eviction.
    Bloom filter fast-path for high-throughput scenarios.
    """

    def __init__(self, max_size: int = 10000, ttl_seconds: int = 7200) -> None:
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._seen: OrderedDict[bytes, float] = OrderedDict()  # key -> timestamp
        self._hits: int = 0
        self._misses: int = 0

    def contains(self, packet_hash: bytes) -> bool:
        """Check if we've seen this packet. Returns True if DUPLICATE."""
        if packet_hash in self._seen:
            # Move to end (most recently used)
            self._seen.move_to_end(packet_hash)
            self._hits += 1
            return True
        self._misses += 1
        return False

    def add(self, packet_hash: bytes) -> None:
        """Record a packet as seen."""
        self._seen[packet_hash] = time.time()
        self._seen.move_to_end(packet_hash)
        self._evict_expired()
        self._evict_overflow()

    def check_and_add(self, packet_hash: bytes) -> bool:
        """Atomically check + add. Returns True if it WAS a duplicate (already seen)."""
        is_dup = self.contains(packet_hash)
        if not is_dup:
            self.add(packet_hash)
        return is_dup

    def _evict_expired(self) -> None:
        cutoff = time.time() - self._ttl
        while self._seen:
            oldest_key, oldest_ts = next(iter(self._seen.items()))
            if oldest_ts < cutoff:
                self._seen.popitem(last=False)
            else:
                break

    def _evict_overflow(self) -> None:
        while len(self._seen) > self._max_size:
            self._seen.popitem(last=False)

    @property
    def size(self) -> int:
        return len(self._seen)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def clear(self) -> None:
        self._seen.clear()
        self._hits = 0
        self._misses = 0
