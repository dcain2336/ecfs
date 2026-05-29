import pytest
from ecfs.plugins.base import TransportStatus, TransportType
from ecfs.plugins.null_transport import NullTransport
from ecfs.plugins.registry import PluginRegistry


class TestRegisterAndGet:
    def test_register_and_retrieve(self) -> None:
        reg = PluginRegistry()
        t = NullTransport()
        reg.register(t)
        assert reg.get("null") is t

    def test_get_nonexistent_returns_none(self) -> None:
        reg = PluginRegistry()
        assert reg.get("nope") is None

    def test_plugin_names(self) -> None:
        reg = PluginRegistry()
        reg.register(NullTransport())
        assert reg.plugin_names == ["null"]


class TestRegisterDuplicateRaises:
    def test_duplicate_raises_valueerror(self) -> None:
        reg = PluginRegistry()
        reg.register(NullTransport())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(NullTransport())


class TestUnregister:
    def test_unregister_removes_plugin(self) -> None:
        reg = PluginRegistry()
        reg.register(NullTransport())
        reg.unregister("null")
        assert reg.get("null") is None
        assert "null" not in reg.plugin_names

    def test_unregister_nonexistent_is_noop(self) -> None:
        reg = PluginRegistry()
        reg.unregister("ghost")  # should not raise


class TestByTypeFilter:
    def test_filter_covert(self) -> None:
        reg = PluginRegistry()
        t = NullTransport()
        reg.register(t)
        result = reg.by_type(TransportType.COVERT)
        assert len(result) == 1
        assert result[0] is t

    def test_filter_empty_for_wrong_type(self) -> None:
        reg = PluginRegistry()
        reg.register(NullTransport())
        assert reg.by_type(TransportType.INTERNET) == []


class TestInitializeAll:
    @pytest.mark.asyncio
    async def test_initialize_all(self) -> None:
        reg = PluginRegistry()
        t = NullTransport()
        reg.register(t)
        await reg.initialize_all()
        assert reg._initialized["null"] is True

    @pytest.mark.asyncio
    async def test_failed_init_marks_uninitialized(self) -> None:
        reg = PluginRegistry()
        t = NullTransport()
        # Patch initialize to raise
        async def bad_init() -> None:
            raise RuntimeError("boom")

        t.initialize = bad_init  # type: ignore[assignment]
        reg.register(t)
        await reg.initialize_all()
        assert reg._initialized["null"] is False


class TestGetOnlinePlugins:
    @pytest.mark.asyncio
    async def test_online_plugin_returned(self) -> None:
        reg = PluginRegistry()
        t = NullTransport()
        reg.register(t)
        await reg.initialize_all()
        online = await reg.get_online_plugins()
        assert len(online) == 1
        assert online[0].name == "null"

    @pytest.mark.asyncio
    async def test_uninitialized_not_returned(self) -> None:
        reg = PluginRegistry()
        reg.register(NullTransport())
        # Don't initialize
        online = await reg.get_online_plugins()
        assert len(online) == 0


class TestHealthCheckAll:
    @pytest.mark.asyncio
    async def test_health_check_all(self) -> None:
        reg = PluginRegistry()
        t = NullTransport()
        reg.register(t)
        results = await reg.health_check_all()
        assert results["null"] == TransportStatus.ONLINE

    @pytest.mark.asyncio
    async def test_health_check_error_reports_error(self) -> None:
        reg = PluginRegistry()
        t = NullTransport()

        async def bad_health() -> TransportStatus:
            raise RuntimeError("probe failed")

        t.health_check = bad_health  # type: ignore[assignment]
        reg.register(t)
        results = await reg.health_check_all()
        assert results["null"] == TransportStatus.ERROR


class TestTeardownAll:
    @pytest.mark.asyncio
    async def test_teardown_all(self) -> None:
        reg = PluginRegistry()
        t = NullTransport()
        reg.register(t)
        await reg.teardown_all()  # should not raise

    @pytest.mark.asyncio
    async def test_teardown_error_handled(self) -> None:
        reg = PluginRegistry()
        t = NullTransport()

        async def bad_teardown() -> None:
            raise RuntimeError("cannot close")

        t.teardown = bad_teardown  # type: ignore[assignment]
        reg.register(t)
        await reg.teardown_all()  # should not raise
