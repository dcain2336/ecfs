"""ECFS HTTP Relay Client — connects nodes to public relay servers.

Sends/receives fragments via HTTP POST. Works through firewalls,
NAT, and corporate proxies. Auto-reconnects on failure.

Usage:
    client = RelayClient("https://my-relay.example.com:7700", node_id="abc123")
    await client.connect()
    await client.send_fragment(fragment_bytes)
    frags = await client.poll_fragments()
    await client.disconnect()
"""

import asyncio
import base64
import json
import logging
import time
from typing import Optional

from ecfs.relay.protocol import (
    RegisterMessage,
    FragmentMessage,
    HeartbeatMessage,
    RelayResponse,
    parse_message,
)

logger = logging.getLogger(__name__)


class RelayClient:
    """HTTP client for ECFS relay servers.

    Connects to a relay server via HTTP, registers the node,
    sends/receives fragments, and maintains heartbeats.

    Works with stdlib only — uses urllib.request for HTTP.
    Falls back gracefully on connection failures.

    Usage:
        client = RelayClient(
            relay_url="http://localhost:7700",
            node_id="abc123def456",
            name="my-node",
        )
        await client.connect()
        await client.send_fragment(data, dest="target_node_id")
        fragments = await client.poll(timeout=30)
        await client.start_heartbeat()  # background heartbeat
        await client.disconnect()
    """

    def __init__(
        self,
        relay_url: str,
        node_id: str,
        name: str = "ecfs-node",
        transports: list[str] | None = None,
        timeout: float = 30.0,
        heartbeat_interval: float = 15.0,
    ) -> None:
        self._relay_url = relay_url.rstrip("/")
        self._node_id = node_id
        self._name = name
        self._transports = transports or ["internet"]
        self._timeout = timeout
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._connected = False
        self._stats = {
            "fragments_sent": 0,
            "fragments_received": 0,
            "heartbeats_sent": 0,
            "errors": 0,
        }

    async def connect(self) -> bool:
        """Register with the relay server."""
        try:
            msg = RegisterMessage(
                node_id=self._node_id,
                name=self._name,
                transports=self._transports,
            )
            resp = await self._http_post("/register", msg.to_json())
            if resp and resp.get("ok"):
                self._connected = True
                nodes = resp.get("nodes", [])
                logger.info(
                    "Connected to relay %s (%d nodes online)",
                    self._relay_url, len(nodes),
                )
                return True
            logger.warning("Relay rejected registration: %s", resp)
            return False
        except Exception:
            logger.exception("Failed to connect to relay")
            self._stats["errors"] += 1
            return False

    async def disconnect(self) -> None:
        """Stop heartbeat and mark as disconnected."""
        self._connected = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        logger.info("Disconnected from relay")

    async def send_fragment(self, data: bytes, dest: str = "*") -> bool:
        """Send a fragment to the relay for delivery."""
        if not self._connected:
            logger.warning("Not connected to relay")
            return False
        try:
            msg = FragmentMessage.from_bytes(
                node_id=self._node_id,
                data=data,
                dest=dest,
            )
            resp = await self._http_post("/fragment", msg.to_json())
            if resp and resp.get("ok"):
                self._stats["fragments_sent"] += 1
                return True
            logger.warning("Fragment rejected: %s", resp)
            return False
        except Exception:
            logger.exception("Failed to send fragment")
            self._stats["errors"] += 1
            return False

    async def poll(self, timeout: float = 5.0) -> list[bytes]:
        """Poll the relay for pending fragments."""
        if not self._connected:
            return []
        try:
            url = f"{self._relay_url}/poll?node_id={self._node_id}"
            resp = await self._http_get(url)
            if resp and resp.get("ok"):
                frags = resp.get("fragments", [])
                result = []
                for f in frags:
                    try:
                        result.append(base64.b64decode(f["fragment"]))
                    except (KeyError, ValueError):
                        continue
                self._stats["fragments_received"] += len(result)
                return result
            return []
        except Exception:
            logger.exception("Failed to poll relay")
            self._stats["errors"] += 1
            return []

    async def send_heartbeat(self) -> bool:
        """Send a single heartbeat to the relay."""
        try:
            msg = HeartbeatMessage(node_id=self._node_id)
            resp = await self._http_post("/heartbeat", msg.to_json())
            if resp and resp.get("ok"):
                self._stats["heartbeats_sent"] += 1
                return True
            return False
        except Exception:
            self._stats["errors"] += 1
            return False

    async def start_heartbeat(self) -> None:
        """Start background heartbeat loop."""
        if self._heartbeat_task:
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Background heartbeat at configured interval."""
        while self._connected:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                if self._connected:
                    await self.send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Heartbeat error")

    async def get_nodes(self) -> list[dict]:
        """Get list of online nodes from the relay."""
        try:
            url = f"{self._relay_url}/nodes"
            resp = await self._http_get(url)
            if resp and resp.get("ok"):
                return resp.get("nodes", [])
            return []
        except Exception:
            return []

    async def get_health(self) -> Optional[dict]:
        """Get relay health status."""
        try:
            url = f"{self._relay_url}/health"
            resp = await self._http_get(url)
            return resp
        except Exception:
            return None

    # ── HTTP Layer (stdlib only) ─────────────────────────────────────

    async def _http_post(self, path: str, body: str) -> Optional[dict]:
        """POST JSON to the relay server using stdlib urllib."""
        url = f"{self._relay_url}{path}"
        try:
            import urllib.request
            req = urllib.request.Request(
                url,
                data=body.encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # Run in executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, self._urlopen, req)
            return json.loads(resp)
        except Exception:
            logger.debug("HTTP POST failed: %s", url)
            return None

    async def _http_get(self, url: str) -> Optional[dict]:
        """GET JSON from the relay server using stdlib urllib."""
        try:
            import urllib.request
            req = urllib.request.Request(url, method="GET")
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, self._urlopen, req)
            return json.loads(resp)
        except Exception:
            logger.debug("HTTP GET failed: %s", url)
            return None

    @staticmethod
    def _urlopen(req: "urllib.request.Request") -> str:  # type: ignore[name-defined]
        """Open a URL and return the response body as a string."""
        import urllib.request
        with urllib.request.urlopen(req, timeout=30) as resp:  # type: ignore[arg-type]
            return resp.read().decode()

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> dict:
        return dict(self._stats)
