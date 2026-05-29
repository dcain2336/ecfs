"""Tests for ecfs.core.dedup — DeduplicationCache."""

import time

from ecfs.core.dedup import DeduplicationCache


class TestDeduplicationCache:
    """Unit tests for the TTL-based dedup cache."""

    def test_contains_false_when_empty(self) -> None:
        cache = DeduplicationCache()
        assert cache.contains(b"anything") is False

    def test_add_then_contains(self) -> None:
        cache = DeduplicationCache()
        h = b"\xaa\xbb\xcc"
        cache.add(h)
        assert cache.contains(h) is True

    def test_check_and_add_returns_false_first_time(self) -> None:
        cache = DeduplicationCache()
        h = b"\x01\x02\x03"
        result = cache.check_and_add(h)
        assert result is False
        assert cache.size == 1

    def test_check_and_add_returns_true_second_time(self) -> None:
        cache = DeduplicationCache()
        h = b"\x01\x02\x03"
        cache.check_and_add(h)  # first — not dup
        assert cache.check_and_add(h) is True  # second — dup

    def test_evicts_expired_entries(self) -> None:
        cache = DeduplicationCache(ttl_seconds=1)
        h = b"\xdd"
        cache.add(h)
        assert cache.size == 1
        # Force expiry
        cache._seen[h] = time.time() - 10  # backdate timestamp
        cache._evict_expired()
        assert cache.size == 0
        assert cache.contains(h) is False

    def test_lru_eviction_on_overflow(self) -> None:
        cache = DeduplicationCache(max_size=3)
        for i in range(5):
            cache.add(bytes([i]))
        assert cache.size == 3
        # The first two (0x00, 0x01) should have been evicted
        assert cache.contains(b"\x00") is False
        assert cache.contains(b"\x01") is False
        assert cache.contains(b"\x02") is True

    def test_hit_rate_calculation(self) -> None:
        cache = DeduplicationCache()
        h1 = b"\xaa"
        h2 = b"\xbb"
        cache.add(h1)
        cache.contains(h1)  # hit
        cache.contains(h2)  # miss
        assert cache.hit_rate == 0.5

    def test_clear(self) -> None:
        cache = DeduplicationCache()
        cache.add(b"\x01")
        cache.contains(b"\x01")  # hit
        cache.contains(b"\xff")  # miss
        cache.clear()
        assert cache.size == 0
        assert cache.hit_rate == 0.0
