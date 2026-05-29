import pytest
from ecfs.plugins.base import TransportStatus, TransportType
from ecfs.plugins.null_transport import NullTransport


class TestSendStoresPacket:
    @pytest.mark.asyncio
    async def test_send_returns_true(self) -> None:
        t = NullTransport()
        result = await t.send_packet(b"hello")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_stores_in_sent_list(self) -> None:
        t = NullTransport()
        await t.send_packet(b"msg1")
        await t.send_packet(b"msg2")
        assert t.sent_packets == [b"msg1", b"msg2"]

    @pytest.mark.asyncio
    async def test_sent_packets_returns_copy(self) -> None:
        t = NullTransport()
        await t.send_packet(b"data")
        packets = t.sent_packets
        packets.append(b"injected")
        # Original list should not be mutated
        assert len(t.sent_packets) == 1


class TestReceiveReturnsQueued:
    @pytest.mark.asyncio
    async def test_receive_returns_queued_packet(self) -> None:
        t = NullTransport()
        t.queue_packet(b"incoming")
        result = await t.receive_packet()
        assert result == b"incoming"

    @pytest.mark.asyncio
    async def test_receive_fifo_order(self) -> None:
        t = NullTransport()
        t.queue_packet(b"first")
        t.queue_packet(b"second")
        first = await t.receive_packet()
        second = await t.receive_packet()
        assert first == b"first"
        assert second == b"second"

    @pytest.mark.asyncio
    async def test_receive_drains_queue(self) -> None:
        t = NullTransport()
        t.queue_packet(b"only")
        await t.receive_packet()
        result = await t.receive_packet()
        assert result is None


class TestReceiveEmptyReturnsNone:
    @pytest.mark.asyncio
    async def test_empty_queue_returns_none(self) -> None:
        t = NullTransport()
        result = await t.receive_packet()
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_after_drain_returns_none(self) -> None:
        t = NullTransport()
        t.queue_packet(b"x")
        await t.receive_packet()
        assert await t.receive_packet() is None


class TestInitialStatusIsOnline:
    @pytest.mark.asyncio
    async def test_get_status_returns_online(self) -> None:
        t = NullTransport()
        status = await t.get_status()
        assert status == TransportStatus.ONLINE

    @pytest.mark.asyncio
    async def test_health_check_returns_online(self) -> None:
        t = NullTransport()
        status = await t.health_check()
        assert status == TransportStatus.ONLINE


class TestNullTransportProperties:
    def test_name(self) -> None:
        t = NullTransport()
        assert t.name == "null"

    def test_transport_type(self) -> None:
        t = NullTransport()
        assert t.transport_type == TransportType.COVERT

    def test_priority(self) -> None:
        t = NullTransport()
        assert t.priority == 999

    def test_repr(self) -> None:
        t = NullTransport()
        assert "null" in repr(t)
        assert "covert" in repr(t)
