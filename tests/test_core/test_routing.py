"""Tests for ecfs.core.routing — RoutingEngine."""

import asyncio
from typing import List

import pytest

from ecfs.core.queue import MessagePriority
from ecfs.core.routing import RoutingEngine, RoutingStrategy
from ecfs.plugins.base import TransportStatus
from ecfs.plugins.null_transport import NullTransport


def _make_engines(
    plugins: List[NullTransport],
    strategy: str = RoutingStrategy.ADAPTIVE,
    **kwargs,
) -> RoutingEngine:
    return RoutingEngine(plugins=plugins, strategy=strategy, **kwargs)


class TestRoutingEngine:
    """Integration tests for the routing engine."""

    async def test_shotgun_sends_to_all_plugins(self) -> None:
        p1 = NullTransport(name="a", priority=1)
        p2 = NullTransport(name="b", priority=2)
        engine = _make_engines([p1, p2], strategy=RoutingStrategy.SHOTGUN)
        await engine.start()

        result = await engine.send(b"data", b"\x01", MessagePriority.NORMAL)
        assert result is True
        assert p1.sent_packets == [b"data"]
        assert p2.sent_packets == [b"data"]

    async def test_shortest_picks_lowest_latency(self) -> None:
        p1 = NullTransport(name="fast", priority=1)
        p2 = NullTransport(name="slow", priority=2)
        engine = _make_engines([p1, p2], strategy=RoutingStrategy.SHORTEST)
        await engine.start()

        # Simulate stats — fast plugin has lower latency
        engine._plugin_stats["fast"].total_latency_ms = 5.0
        engine._plugin_stats["fast"].sends_succeeded = 1
        engine._plugin_stats["slow"].total_latency_ms = 50.0
        engine._plugin_stats["slow"].sends_succeeded = 1

        await engine.send(b"payload", b"\x02")
        assert p1.sent_packets == [b"payload"]
        assert p2.sent_packets == []  # not sent to slow

    async def test_adaptive_critical_shotgun(self) -> None:
        p1 = NullTransport(name="a", priority=1)
        p2 = NullTransport(name="b", priority=2)
        engine = _make_engines([p1, p2], strategy=RoutingStrategy.ADAPTIVE)
        await engine.start()

        result = await engine.send(b"emergency", b"\x03", MessagePriority.CRITICAL)
        assert result is True
        assert p1.sent_packets == [b"emergency"]
        assert p2.sent_packets == [b"emergency"]

    async def test_adaptive_normal_picks_best(self) -> None:
        p1 = NullTransport(name="best", priority=1)
        p2 = NullTransport(name="worse", priority=2)
        engine = _make_engines([p1, p2], strategy=RoutingStrategy.ADAPTIVE)
        await engine.start()

        # Set up stats so best has lower latency
        engine._plugin_stats["best"].total_latency_ms = 1.0
        engine._plugin_stats["best"].sends_succeeded = 1
        engine._plugin_stats["worse"].total_latency_ms = 100.0
        engine._plugin_stats["worse"].sends_succeeded = 1

        await engine.send(b"msg", b"\x04", MessagePriority.NORMAL)
        assert p1.sent_packets == [b"msg"]
        assert p2.sent_packets == []

    async def test_dedup_rejects_duplicate(self) -> None:
        p1 = NullTransport(name="net1", priority=1)
        engine = _make_engines([p1], strategy=RoutingStrategy.SHOTGUN)
        await engine.start()

        first = await engine.send(b"data", b"\xAA")
        assert first is True
        # Same hash — should be deduped
        second = await engine.send(b"data", b"\xAA")
        assert second is False
        # Only one packet in the transport buffer
        assert len(p1.sent_packets) == 1

    async def test_send_when_no_plugins_online(self) -> None:
        p1 = NullTransport(name="offline", priority=1)
        p1._status_override = TransportStatus.OFFLINE
        engine = _make_engines([p1], strategy=RoutingStrategy.SHOTGUN)
        await engine.start()

        result = await engine.send(b"data", b"\x01")
        assert result is False
        # Message should be in the queue
        assert engine.message_queue.size == 1

    async def test_receive_delegates_to_plugin(self) -> None:
        p1 = NullTransport(name="net1", priority=1)
        engine = _make_engines([p1])
        await engine.start()

        # Put data in the receive queue
        p1.queue_packet(b"incoming")
        received = await engine.receive("net1")
        assert received == b"incoming"

    async def test_stats_tracking(self) -> None:
        p1 = NullTransport(name="tracked", priority=1)
        engine = _make_engines([p1], strategy=RoutingStrategy.SHOTGUN)
        await engine.start()

        await engine.send(b"first", b"\x01")
        await engine.send(b"second", b"\x02")

        stats = engine.get_stats()
        assert "tracked" in stats
        s = stats["tracked"]
        assert s["sends_attempted"] == 2
        assert s["sends_succeeded"] == 2
        assert s["success_rate"] == 1.0
        assert s["total_bytes"] == len(b"first") + len(b"second")
