"""Tests for InternetTransport plugin."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ecfs.plugins.internet_transport import InternetTransport
from ecfs.plugins.base import TransportStatus, TransportType


@pytest.fixture
def transport():
    return InternetTransport(relay_url="https://relay.example.com/packets")


class TestInternetTransportMetadata:
    def test_name(self, transport):
        assert transport.name == "internet"

    def test_transport_type(self, transport):
        assert transport.transport_type == TransportType.INTERNET

    def test_priority(self, transport):
        assert transport.priority == 10

    def test_max_packet_size(self, transport):
        assert transport.max_packet_size == 1_048_576


class TestInternetTransportLifecycle:
    @pytest.mark.asyncio
    async def test_initial_status_offline(self):
        t = InternetTransport()
        assert await t.get_status() == TransportStatus.OFFLINE

    @pytest.mark.asyncio
    async def test_initialize_sets_online(self, transport):
        await transport.initialize()
        assert await transport.get_status() == TransportStatus.ONLINE
        await transport.teardown()

    @pytest.mark.asyncio
    async def test_teardown_sets_offline(self, transport):
        await transport.initialize()
        await transport.teardown()
        assert await transport.get_status() == TransportStatus.OFFLINE


class TestInternetTransportSend:
    @pytest.mark.asyncio
    async def test_send_fails_without_relay_url(self):
        t = InternetTransport()
        await t.initialize()
        result = await t.send_packet(b"hello")
        assert result is False
        await t.teardown()

    @pytest.mark.asyncio
    async def test_send_fails_without_client(self):
        t = InternetTransport(relay_url="https://example.com")
        result = await t.send_packet(b"hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self, transport):
        await transport.initialize()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        transport._client.post = AsyncMock(return_value=mock_resp)
        result = await transport.send_packet(b"hello world")
        assert result is True
        transport._client.post.assert_called_once_with(
            "https://relay.example.com/packets",
            content=b"hello world",
            headers={"Content-Type": "application/octet-stream"},
        )
        await transport.teardown()

    @pytest.mark.asyncio
    async def test_send_http_error(self, transport):
        await transport.initialize()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        transport._client.post = AsyncMock(return_value=mock_resp)
        result = await transport.send_packet(b"hello")
        assert result is False
        # Status stays ONLINE — HTTP errors are not transport errors
        assert await transport.get_status() == TransportStatus.ONLINE
        await transport.teardown()

    @pytest.mark.asyncio
    async def test_send_network_error(self, transport):
        await transport.initialize()
        transport._client.post = AsyncMock(side_effect=ConnectionError("fail"))
        result = await transport.send_packet(b"hello")
        assert result is False
        assert await transport.get_status() == TransportStatus.ERROR
        await transport.teardown()


class TestInternetTransportReceive:
    @pytest.mark.asyncio
    async def test_receive_empty_returns_none(self, transport):
        await transport.initialize()
        result = await transport.receive_packet()
        assert result is None
        await transport.teardown()

    def test_queue_received(self, transport):
        transport.queue_received(b"packet1")
        transport.queue_received(b"packet2")
        assert transport._receive_queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_queue_then_receive(self, transport):
        await transport.initialize()
        transport.queue_received(b"data")
        result = await transport.receive_packet()
        assert result == b"data"
        # Queue should now be empty
        assert await transport.receive_packet() is None
        await transport.teardown()
