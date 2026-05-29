"""Tests for ecfs.relay.server — RelayServer, RelayState, RelayHTTPHandler.

Uses a real HTTPServer on an ephemeral port per test.  Requests are made
with stdlib urllib (sync) against the running server thread.
"""

import asyncio
import base64
import json
import socket
import time
import threading
from http.server import HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import pytest

from ecfs.relay.protocol import (
    RegisterMessage,
    FragmentMessage,
    NodeInfo,
)
from ecfs.relay.server import RelayServer, RelayState


# ── Helpers ─────────────────────────────────────────────────────────

def _ephemeral_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(base_url: str, path: str, body: dict, expected_status: int = 200) -> dict:
    """POST JSON and return parsed response."""
    url = f"{base_url}{path}"
    data = json.dumps(body).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urlopen(req, timeout=5)
        return json.loads(resp.read().decode())
    except HTTPError as e:
        return json.loads(e.read().decode())


def _get(base_url: str, path: str, expected_status: int = 200) -> dict:
    """GET and return parsed JSON response."""
    url = f"{base_url}{path}"
    req = Request(url, method="GET")
    try:
        resp = urlopen(req, timeout=5)
        return json.loads(resp.read().decode())
    except HTTPError as e:
        return json.loads(e.read().decode())


def _get_raw(base_url: str, path: str):
    """GET without catching HTTPError (for tests that expect error codes)."""
    url = f"{base_url}{path}"
    req = Request(url, method="GET")
    return urlopen(req, timeout=5)


def _post_raw(base_url: str, path: str, body: dict):
    """POST without catching HTTPError (for tests that expect error codes)."""
    url = f"{base_url}{path}"
    data = json.dumps(body).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    return urlopen(req, timeout=5)


@pytest.fixture
def server_fixture():
    """Start a RelayServer on an ephemeral port, yield (server, base_url), stop after test."""
    port = _ephemeral_port()
    server = RelayServer(host="127.0.0.1", port=port)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(server.start())

    base_url = f"http://127.0.0.1:{port}"
    yield server, base_url, loop

    loop.run_until_complete(server.stop())
    loop.close()


# ── Basic server lifecycle ──────────────────────────────────────────

class TestServerLifecycle:
    def test_server_starts_and_is_running(self, server_fixture):
        server, base_url, _ = server_fixture
        assert server.is_running is True
        assert server.port > 0

    def test_health_endpoint_returns_running(self, server_fixture):
        _, base_url, _ = server_fixture
        resp = _get(base_url, "/health")
        assert resp["ok"] is True
        assert resp["status"] == "running"
        assert "stats" in resp
        assert "nodes" in resp
        assert "uptime" in resp

    def test_unknown_get_returns_404(self, server_fixture):
        _, base_url, _ = server_fixture
        with pytest.raises(HTTPError) as exc_info:
            _get_raw(base_url, "/nonexistent")
        assert exc_info.value.code == 404

    def test_unknown_post_returns_404(self, server_fixture):
        _, base_url, _ = server_fixture
        with pytest.raises(HTTPError) as exc_info:
            _post_raw(base_url, "/nonexistent", {})
        assert exc_info.value.code == 404


# ── Registration ────────────────────────────────────────────────────

class TestRegister:
    def test_register_node(self, server_fixture):
        _, base_url, _ = server_fixture
        resp = _post(base_url, "/register", {
            "type": "register",
            "node_id": "aabb",
            "name": "node-a",
            "transports": ["internet"],
        })
        assert resp["ok"] is True
        nodes = resp["nodes"]
        assert any(n["node_id"] == "aabb" for n in nodes)

    def test_register_returns_all_nodes(self, server_fixture):
        _, base_url, _ = server_fixture
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "aa",
            "name": "one",
        })
        resp = _post(base_url, "/register", {
            "type": "register",
            "node_id": "bb",
            "name": "two",
        })
        assert resp["ok"] is True
        node_ids = [n["node_id"] for n in resp["nodes"]]
        assert "aa" in node_ids
        assert "bb" in node_ids

    def test_register_missing_node_id_returns_400(self, server_fixture):
        _, base_url, _ = server_fixture
        with pytest.raises(HTTPError) as exc_info:
            _post_raw(base_url, "/register", {"type": "register"})
        assert exc_info.value.code == 400
        # Verify error body
        err_body = json.loads(exc_info.value.read().decode())
        assert err_body["ok"] is False

    def test_nodes_endpoint_returns_online_nodes(self, server_fixture):
        _, base_url, _ = server_fixture
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "xx",
            "name": "x-node",
            "transports": ["lora"],
        })
        resp = _get(base_url, "/nodes")
        assert resp["ok"] is True
        nodes = resp["nodes"]
        assert len(nodes) >= 1
        assert any(n["node_id"] == "xx" and n["name"] == "x-node" for n in nodes)


# ── Fragment handling ───────────────────────────────────────────────

class TestFragments:
    def test_send_fragment_ok(self, server_fixture):
        _, base_url, _ = server_fixture
        # Register sender first
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "sender1",
            "name": "sender",
        })
        frag_b64 = base64.b64encode(b"test data").decode()
        resp = _post(base_url, "/fragment", {
            "type": "fragment",
            "node_id": "sender1",
            "fragment": frag_b64,
            "dest": "*",
        })
        assert resp["ok"] is True
        assert "relay_id" in resp

    def test_fragment_missing_data_returns_400(self, server_fixture):
        _, base_url, _ = server_fixture
        with pytest.raises(HTTPError) as exc_info:
            _post_raw(base_url, "/fragment", {"type": "fragment"})
        assert exc_info.value.code == 400

    def test_fragment_broadcast_to_other_node(self, server_fixture):
        """Register A and B, send broadcast from A, B should receive it."""
        _, base_url, _ = server_fixture
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "nodeA",
            "name": "A",
        })
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "nodeB",
            "name": "B",
        })
        payload = b"broadcast message"
        frag_b64 = base64.b64encode(payload).decode()
        _post(base_url, "/fragment", {
            "type": "fragment",
            "node_id": "nodeA",
            "fragment": frag_b64,
            "dest": "*",
        })
        # B polls and should get the fragment
        resp = _get(base_url, "/poll?node_id=nodeB")
        assert resp["ok"] is True
        frags = resp["fragments"]
        assert len(frags) >= 1
        decoded = base64.b64decode(frags[0]["fragment"])
        assert decoded == payload

    def test_fragment_unicast_only_dest_receives(self, server_fixture):
        """Send with specific dest, only that node gets it."""
        _, base_url, _ = server_fixture
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "src",
            "name": "source",
        })
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "dest1",
            "name": "dest",
        })
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "other",
            "name": "other",
        })
        payload = b"unicast payload"
        frag_b64 = base64.b64encode(payload).decode()
        _post(base_url, "/fragment", {
            "type": "fragment",
            "node_id": "src",
            "fragment": frag_b64,
            "dest": "dest1",
        })
        # dest1 should get it
        resp = _get(base_url, "/poll?node_id=dest1")
        frags = resp["fragments"]
        assert len(frags) >= 1
        assert base64.b64decode(frags[0]["fragment"]) == payload

        # other should NOT get it
        resp2 = _get(base_url, "/poll?node_id=other")
        assert resp2["fragments"] == []

    def test_sender_does_not_receive_own_broadcast(self, server_fixture):
        """When a node sends a broadcast, it should NOT appear in its own poll."""
        _, base_url, _ = server_fixture
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "lonely",
            "name": "lonely",
        })
        frag_b64 = base64.b64encode(b"echo").decode()
        _post(base_url, "/fragment", {
            "type": "fragment",
            "node_id": "lonely",
            "fragment": frag_b64,
            "dest": "*",
        })
        resp = _get(base_url, "/poll?node_id=lonely")
        assert resp["fragments"] == []


# ── Heartbeat ───────────────────────────────────────────────────────

class TestHeartbeat:
    def test_heartbeat_updates_last_seen(self, server_fixture):
        server, base_url, _ = server_fixture
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "hb1",
            "name": "heartbeat-node",
        })
        # Record original last_seen
        original_seen = server.state.nodes["hb1"].last_seen
        time.sleep(0.05)

        _post(base_url, "/heartbeat", {
            "type": "heartbeat",
            "node_id": "hb1",
        })
        new_seen = server.state.nodes["hb1"].last_seen
        assert new_seen > original_seen

    def test_heartbeat_missing_node_id_returns_400(self, server_fixture):
        _, base_url, _ = server_fixture
        with pytest.raises(HTTPError) as exc_info:
            _post_raw(base_url, "/heartbeat", {"type": "heartbeat"})
        assert exc_info.value.code == 400


# ── Poll ────────────────────────────────────────────────────────────

class TestPoll:
    def test_poll_empty_returns_empty_list(self, server_fixture):
        _, base_url, _ = server_fixture
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "poller1",
            "name": "poller",
        })
        resp = _get(base_url, "/poll?node_id=poller1")
        assert resp["ok"] is True
        assert resp["fragments"] == []

    def test_poll_missing_node_id_returns_400(self, server_fixture):
        _, base_url, _ = server_fixture
        with pytest.raises(HTTPError) as exc_info:
            _get_raw(base_url, "/poll")
        assert exc_info.value.code == 400

    def test_poll_returns_fragments_once_then_clears(self, server_fixture):
        _, base_url, _ = server_fixture
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "sender2",
            "name": "sender",
        })
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "receiver",
            "name": "receiver",
        })
        payload = b"consume once"
        frag_b64 = base64.b64encode(payload).decode()
        _post(base_url, "/fragment", {
            "type": "fragment",
            "node_id": "sender2",
            "fragment": frag_b64,
            "dest": "receiver",
        })
        # First poll gets it
        resp1 = _get(base_url, "/poll?node_id=receiver")
        assert len(resp1["fragments"]) == 1
        # Second poll should be empty (consumed)
        resp2 = _get(base_url, "/poll?node_id=receiver")
        assert resp2["fragments"] == []


# ── Stale node eviction ─────────────────────────────────────────────

class TestStaleEviction:
    def test_stale_node_evicted_on_get_online_nodes(self):
        state = RelayState()
        # Register a node
        reg = RegisterMessage(node_id="stale1", name="stale-node")
        state.register_node(reg)

        # Set last_seen to 120 seconds ago
        state.nodes["stale1"].last_seen = time.time() - 120

        # get_online_nodes should evict it
        online = state.get_online_nodes()
        assert len(online) == 0
        assert "stale1" not in state.nodes

    def test_fresh_node_not_evicted(self):
        state = RelayState()
        reg = RegisterMessage(node_id="fresh1", name="fresh-node")
        state.register_node(reg)

        online = state.get_online_nodes()
        assert len(online) == 1
        assert online[0].node_id == "fresh1"

    def test_stale_eviction_removes_outgoing_queue(self):
        state = RelayState()
        reg = RegisterMessage(node_id="stale2", name="s")
        state.register_node(reg)
        state.outgoing["stale2"] = [b"data"]
        state.nodes["stale2"].last_seen = time.time() - 120

        state.get_online_nodes()  # triggers eviction
        assert "stale2" not in state.outgoing

    def test_server_evicts_stale_via_health_check(self, server_fixture):
        """Register a node, age it out, verify /nodes no longer lists it."""
        server, base_url, _ = server_fixture
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "aged",
            "name": "old-node",
        })
        # Manually age the node
        server.state.nodes["aged"].last_seen = time.time() - 120

        resp = _get(base_url, "/nodes")
        node_ids = [n["node_id"] for n in resp["nodes"]]
        assert "aged" not in node_ids


# ── Health stats ────────────────────────────────────────────────────

class TestHealthStats:
    def test_stats_update_after_operations(self, server_fixture):
        _, base_url, _ = server_fixture
        # Register 2 nodes
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "sa",
            "name": "A",
        })
        _post(base_url, "/register", {
            "type": "register",
            "node_id": "sb",
            "name": "B",
        })
        # Send a fragment
        frag_b64 = base64.b64encode(b"stats test").decode()
        _post(base_url, "/fragment", {
            "type": "fragment",
            "node_id": "sa",
            "fragment": frag_b64,
            "dest": "sb",
        })
        # Heartbeat
        _post(base_url, "/heartbeat", {"type": "heartbeat", "node_id": "sa"})

        resp = _get(base_url, "/health")
        stats = resp["stats"]
        assert stats["nodes_registered"] >= 2
        assert stats["fragments_received"] >= 1
        assert stats["fragments_relayed"] >= 1
        assert stats["heartbeats"] >= 1
