"""Phase 2 integration tests."""

import asyncio
import pytest

from ecfs.plugins.dns_transport import DNSTunnelTransport
from ecfs.plugins.internet_transport import InternetTransport
from ecfs.plugins.null_transport import NullTransport
from ecfs.plugins.registry import PluginRegistry
from ecfs.plugins.base import TransportType


class TestDNSRoundTrip:
    def test_dns_encode_send_receive_round_trip(self):
        """Encode data → DNS chunks → decode → verify matches."""
        transport = DNSTunnelTransport(domain="covert.test")
        original = b"ECFS Phase 2 test payload"
        chunks = transport._encode_chunks(original)
        subdomain = ".".join(chunks)
        decoded = transport.decode_from_query(f"0.{subdomain}.ecfs.covert.test")
        assert decoded == original

    def test_dns_round_trip_various_sizes(self):
        transport = DNSTunnelTransport(domain="test.com")
        for size in [1, 10, 50, 100, 199]:
            data = bytes(range(256))[:size]
            chunks = transport._encode_chunks(data)
            decoded = transport._decode_chunks(chunks)
            assert decoded == data, f"Round-trip failed for size {size}"


class TestInternetTransportQueue:
    @pytest.mark.asyncio
    async def test_internet_transport_queue_and_receive(self):
        """Queue data → receive → verify."""
        transport = InternetTransport()
        await transport.initialize()

        transport.queue_received(b"packet_a")
        transport.queue_received(b"packet_b")

        a = await transport.receive_packet()
        b = await transport.receive_packet()
        none = await transport.receive_packet()

        assert a == b"packet_a"
        assert b == b"packet_b"
        assert none is None

        await transport.teardown()


class TestMultiplePluginsInRegistry:
    def test_multiple_plugins_in_registry(self):
        """Register NullTransport + InternetTransport, verify by_type filtering."""
        registry = PluginRegistry()

        null_t = NullTransport()
        internet_t = InternetTransport(relay_url="https://test.example.com")
        dns_t = DNSTunnelTransport(domain="test.com")

        registry.register(null_t)
        registry.register(internet_t)
        registry.register(dns_t)

        # Verify all registered
        assert len(registry.plugin_names) == 3

        # Filter by type
        internet_plugins = registry.by_type(TransportType.INTERNET)
        assert len(internet_plugins) == 1
        assert internet_plugins[0].name == "internet"

        # COVERT type — both NullTransport and DNSTunnelTransport are COVERT
        covert_plugins = registry.by_type(TransportType.COVERT)
        assert len(covert_plugins) == 2
        covert_names = {p.name for p in covert_plugins}
        assert "dns" in covert_names
        assert "null" in covert_names

        # PROXIMITY type — none registered
        proximity_plugins = registry.by_type(TransportType.PROXIMITY)
        assert len(proximity_plugins) == 0
