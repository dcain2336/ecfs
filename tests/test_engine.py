"""Tests for ecfs.core.engine — ECFSEngine orchestrator."""

import asyncio
import pytest

from ecfs.core.engine import ECFSEngine
from ecfs.core.dedup import DeduplicationCache
from ecfs.plugins.null_transport import NullTransport
from ecfs.plugins.base import TransportStatus


@pytest.fixture
def engine():
    return ECFSEngine(enable_dedup=True)


@pytest.fixture
def engine_no_dedup():
    return ECFSEngine(enable_dedup=False)


def test_initial_stats(engine):
    """Engine starts with zero stats."""
    stats = engine.stats
    assert stats["packets_sent"] == 0
    assert stats["packets_received"] == 0
    assert stats["packets_dropped"] == 0
    assert stats["packets_deduped"] == 0


def test_register_plugin(engine):
    """Plugins can be registered."""
    null = NullTransport(name="test-null")
    engine.register_plugin(null)
    assert "test-null" in engine.registry.plugin_names
    assert len(engine.registry.get_all()) == 1


@pytest.mark.asyncio
async def test_start_initializes_plugins(engine):
    """start() initializes all registered plugins."""
    null = NullTransport(name="init-null")
    engine.register_plugin(null)
    await engine.start()
    assert engine.is_running


@pytest.mark.asyncio
async def test_stop_teardowns_plugins(engine):
    """stop() tears down all plugins."""
    null = NullTransport(name="teardown-null")
    engine.register_plugin(null)
    await engine.start()
    await engine.stop()
    assert not engine.is_running


@pytest.mark.asyncio
async def test_send_with_online_plugin(engine):
    """send() succeeds when an online plugin is available."""
    null = NullTransport(name="send-null")
    engine.register_plugin(null)
    await engine.start()

    result = await engine.send(b"hello world")
    assert result is True
    assert engine.stats["packets_sent"] == 1
    assert null.sent_packets == [b"hello world"]


@pytest.mark.asyncio
async def test_send_no_online_plugins_returns_false(engine):
    """send() returns False and queues when no plugins are online."""
    null = NullTransport(name="offline-null", status=TransportStatus.OFFLINE)
    engine.register_plugin(null)
    await engine.start()

    result = await engine.send(b"queued data")
    assert result is False
    assert engine.stats["packets_dropped"] == 1


@pytest.mark.asyncio
async def test_receive_from_plugin(engine):
    """receive() returns data from a plugin that has incoming packets."""
    null = NullTransport(name="recv-null")
    engine.register_plugin(null)
    await engine.start()

    # Pre-load a packet into the receive queue
    null.queue_packet(b"incoming data")

    data = await engine.receive()
    assert data == b"incoming data"
    assert engine.stats["packets_received"] == 1


@pytest.mark.asyncio
async def test_receive_empty_when_none_available(engine):
    """receive() returns None when no plugins have data."""
    null = NullTransport(name="empty-null")
    engine.register_plugin(null)
    await engine.start()

    data = await engine.receive()
    assert data is None


@pytest.mark.asyncio
async def test_dedup_prevents_duplicate_send(engine):
    """Duplicate packets are rejected by dedup."""
    null = NullTransport(name="dedup-null")
    engine.register_plugin(null)
    await engine.start()

    # First send succeeds
    result1 = await engine.send(b"unique packet")
    assert result1 is True
    assert engine.stats["packets_sent"] == 1

    # Duplicate is deduped
    result2 = await engine.send(b"unique packet")
    assert result2 is False
    assert engine.stats["packets_deduped"] == 1
    # Only one packet actually sent
    assert engine.stats["packets_sent"] == 1


@pytest.mark.asyncio
async def test_health_check_all_plugins(engine):
    """health_check() returns status for all registered plugins."""
    null1 = NullTransport(name="hc1", priority=10)
    null2 = NullTransport(name="hc2", priority=20)
    engine.register_plugin(null1)
    engine.register_plugin(null2)

    health = await engine.health_check()
    assert "hc1" in health
    assert "hc2" in health
    assert health["hc1"]["status"] == TransportStatus.ONLINE.value
    assert health["hc1"]["priority"] == 10
    assert health["hc2"]["priority"] == 20
