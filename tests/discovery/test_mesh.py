import asyncio
import pytest
from ecfs.discovery.mesh import MeshNode
from ecfs.plugins.null_transport import NullTransport
from ecfs.core.engine import ECFSEngine


class TestMeshNodeInit:
    def test_mesh_node_init(self):
        """Name and node_id are set correctly."""
        node = MeshNode(name='test-node')
        assert node.name == 'test-node'
        assert len(node.node_id) == 16

    def test_mesh_node_default_name(self):
        """Default name is 'ecfs-node'."""
        node = MeshNode()
        assert node.name == 'ecfs-node'


class TestMeshNodeStart:
    @pytest.mark.asyncio
    async def test_mesh_node_start_returns_status(self):
        """start() returns a status dict with expected keys."""
        node = MeshNode(name='test-start')
        status = await node.start()
        assert 'node_id' in status
        assert 'name' in status
        assert 'hardware' in status
        assert 'transports' in status
        assert 'transport_count' in status
        await node.stop()

    @pytest.mark.asyncio
    async def test_mesh_node_start_discovers_hardware(self):
        """start() populates the hardware field."""
        node = MeshNode(name='test-hw')
        status = await node.start()
        assert isinstance(status['hardware'], str)
        assert len(status['hardware']) > 0
        await node.stop()


class TestMeshNodeSend:
    @pytest.mark.asyncio
    async def test_mesh_node_send(self):
        """send() returns a bool."""
        node = MeshNode(name='test-send')
        await node.start()
        result = await node.send(b'hello')
        assert isinstance(result, bool)
        await node.stop()


class TestMeshNodeReceive:
    @pytest.mark.asyncio
    async def test_mesh_node_receive(self):
        """receive() returns None when nothing available."""
        node = MeshNode(name='test-recv')
        await node.start()
        result = await node.receive()
        assert result is None
        await node.stop()


class TestMeshNodeHealth:
    @pytest.mark.asyncio
    async def test_mesh_node_health(self):
        """health() returns a dict."""
        node = MeshNode(name='test-health')
        await node.start()
        health = await node.health()
        assert isinstance(health, dict)
        await node.stop()


class TestMeshNodeStop:
    @pytest.mark.asyncio
    async def test_mesh_node_stop(self):
        """stop() doesn't raise."""
        node = MeshNode(name='test-stop')
        await node.start()
        await node.stop()
        assert node._running is False
