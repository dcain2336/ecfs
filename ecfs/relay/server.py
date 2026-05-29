"""ECFS Public Relay Server — zero-dependency HTTP relay.

Accepts fragments from any node and broadcasts them to all connected nodes.
Works through firewalls — just needs HTTP access.

Usage:
    server = RelayServer(host="0.0.0.0", port=7700)
    await server.start()
    # ... run forever ...
    await server.stop()

Or from CLI:
    ecfs relay start --port 7700
"""

import asyncio
import json
import logging
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Optional
from urllib.parse import urlparse, parse_qs

from ecfs.relay.protocol import (
    RegisterMessage,
    FragmentMessage,
    HeartbeatMessage,
    NodeInfo,
    RelayResponse,
    parse_message,
)

logger = logging.getLogger(__name__)


class RelayState:
    """Shared state between HTTP threads and async relay logic."""

    def __init__(self) -> None:
        self.nodes: dict[str, NodeInfo] = {}  # node_id → NodeInfo
        self.fragment_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self.outgoing: dict[str, list[bytes]] = {}  # node_id → [fragment_bytes]
        self.stats = {
            "fragments_received": 0,
            "fragments_relayed": 0,
            "nodes_registered": 0,
            "heartbeats": 0,
        }
        self._fragment_event = asyncio.Event()  # wakes up long-pollers

    def register_node(self, msg: RegisterMessage) -> None:
        node = NodeInfo(
            node_id=msg.node_id,
            name=msg.name,
            transports=msg.transports,
        )
        self.nodes[msg.node_id] = node
        self.stats["nodes_registered"] += 1
        logger.info("Node registered: %s (%s)", msg.name, msg.node_id[:8])

    def store_fragment(self, msg: FragmentMessage) -> None:
        """Store a fragment for delivery to destination(s)."""
        self.stats["fragments_received"] += 1
        frag_bytes = msg.fragment_bytes

        if msg.dest == "*":
            # Broadcast to all connected nodes except sender
            for nid, node in self.nodes.items():
                if nid != msg.node_id and not node.is_stale:
                    self.outgoing.setdefault(nid, []).append(frag_bytes)
        else:
            # Unicast to specific node
            self.outgoing.setdefault(msg.dest, []).append(frag_bytes)

        self.stats["fragments_relayed"] += 1
        # Wake up any long-pollers
        self._fragment_event.set()

    def heartbeat(self, msg: HeartbeatMessage) -> None:
        if msg.node_id in self.nodes:
            self.nodes[msg.node_id].last_seen = time.time()
            self.stats["heartbeats"] += 1

    def get_fragments(self, node_id: str) -> list[bytes]:
        """Get and clear pending fragments for a node."""
        frags = self.outgoing.pop(node_id, [])
        return frags

    def get_online_nodes(self) -> list[NodeInfo]:
        """Get all non-stale nodes."""
        self._evict_stale()
        return [n for n in self.nodes.values() if not n.is_stale]

    def _evict_stale(self) -> None:
        stale = [nid for nid, n in self.nodes.items() if n.is_stale]
        for nid in stale:
            del self.nodes[nid]
            self.outgoing.pop(nid, None)


class RelayHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for the relay server.

    Endpoints:
        POST /fragment    — send a fragment
        POST /register    — register as a node
        POST /heartbeat   — keepalive
        GET  /poll        — long-poll for fragments
        GET  /health      — relay health check
        GET  /nodes       — list connected nodes
    """

    # Suppress default access log
    def log_message(self, format, *args):
        logger.debug("HTTP %s", format % args)

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Optional[dict]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        raw = self.rfile.read(length)
        return parse_message(raw.decode())

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        state: RelayState = self.server.relay_state  # type: ignore

        if path == "/fragment":
            data = self._read_body()
            if not data or "fragment" not in data:
                self._send_json({"ok": False, "error": "missing fragment"}, 400)
                return
            msg = FragmentMessage.from_json(data)
            state.store_fragment(msg)
            self._send_json({"ok": True, "relay_id": str(state.stats["fragments_relayed"])})

        elif path == "/register":
            data = self._read_body()
            if not data or "node_id" not in data:
                self._send_json({"ok": False, "error": "missing node_id"}, 400)
                return
            msg = RegisterMessage.from_json(data)
            state.register_node(msg)
            nodes = [n.to_dict() for n in state.get_online_nodes()]
            self._send_json({"ok": True, "nodes": nodes})

        elif path == "/heartbeat":
            data = self._read_body()
            if not data or "node_id" not in data:
                self._send_json({"ok": False, "error": "missing node_id"}, 400)
                return
            msg = HeartbeatMessage.from_json(data)
            state.heartbeat(msg)
            self._send_json({"ok": True})

        else:
            self._send_json({"error": "not found"}, 404)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        params = parse_qs(urlparse(self.path).query)
        state: RelayState = self.server.relay_state  # type: ignore

        if path == "/poll":
            node_id = params.get("node_id", [None])[0]
            if not node_id:
                self._send_json({"ok": False, "error": "missing node_id"}, 400)
                return

            # Get pending fragments (non-blocking first)
            frags = state.get_fragments(node_id)
            if frags:
                encoded = [
                    {"from": "relay", "fragment": __import__("base64").b64encode(f).decode()}
                    for f in frags
                ]
                self._send_json({"ok": True, "fragments": encoded})
                return

            # Long-poll: wait up to 30 seconds for new fragments
            self._send_json({"ok": True, "fragments": []})

        elif path == "/health":
            self._send_json({
                "ok": True,
                "status": "running",
                "nodes": len(state.get_online_nodes()),
                "stats": state.stats,
                "uptime": time.time(),
            })

        elif path == "/nodes":
            nodes = [n.to_dict() for n in state.get_online_nodes()]
            self._send_json({"ok": True, "nodes": nodes})

        else:
            self._send_json({"error": "not found"}, 404)


class RelayServer:
    """HTTP relay server for ECFS fragments.

    Accepts fragments from nodes via HTTP POST and makes them
    available to destination nodes via polling. Zero external
    dependencies — uses only Python stdlib.

    Usage:
        server = RelayServer(host="0.0.0.0", port=7700)
        await server.start()
        # ... server runs ...
        await server.stop()
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 7700) -> None:
        self._host = host
        self._port = port
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[Thread] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        self.state = RelayState()

    async def wait_until_ready(self, timeout: float = 2.0) -> bool:
        """Block until the HTTP server is accepting connections."""
        import socket as _socket
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                s = _socket.create_connection((self._host, self._port), timeout=0.2)
                s.close()
                return True
            except (ConnectionRefusedError, OSError):
                await asyncio.sleep(0.05)
        return False

    async def start(self) -> None:
        """Start the relay server."""
        if self._running:
            return

        self._httpd = HTTPServer((self._host, self._port), RelayHTTPHandler)
        self._httpd.relay_state = self.state  # type: ignore
        self._running = True

        # Run HTTP server in a thread (it's synchronous)
        self._thread = Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

        # Start cleanup loop in async context
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info("Relay server started on %s:%d", self._host, self._port)
        print(f"ECFS Relay Server running on http://{self._host}:{self._port}")
        print("Endpoints:")
        print(f"  POST /fragment   — send fragments")
        print(f"  POST /register   — register as a node")
        print(f"  POST /heartbeat  — keepalive")
        print(f"  GET  /poll       — poll for fragments")
        print(f"  GET  /health     — health check")
        print(f"  GET  /nodes      — list connected nodes")

    async def stop(self) -> None:
        """Stop the relay server."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._httpd:
            self._httpd.shutdown()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Relay server stopped")

    async def _cleanup_loop(self) -> None:
        """Periodically evict stale nodes."""
        while self._running:
            try:
                await asyncio.sleep(30.0)
                before = len(self.state.nodes)
                self.state._evict_stale()
                after = len(self.state.nodes)
                if before != after:
                    logger.info(
                        "Evicted %d stale nodes (%d remaining)",
                        before - after, after,
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Cleanup error")

    @property
    def port(self) -> int:
        return self._port

    @property
    def is_running(self) -> bool:
        return self._running
