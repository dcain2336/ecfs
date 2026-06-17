"""ecfs-lite.py — ECFS Lite gateway server.

HTTP gateway that connects lite users to the ECFS mesh relay.
Enforces multi-tenant isolation, API key validation, and encryption.

Lite users register their nodes here, send/receive encrypted messages,
and manage their personal sensors — cannot access other users' data.

Usage:
    python ecfs-lite.py --port 7703 --relay http://127.0.0.1:7700

Environment:
    ECFS_LITE_PORT      — Listen port (default: 7703)
    ECFS_LITE_RELAY     — ECFS relay URL (default: http://127.0.0.1:7700)
    ECFS_LITE_DB        — Database path (default: ~/.ecfs/lite.db)
    ECFS_ADMIN_KEY      — Master admin key (required for user registration)
"""

import asyncio
import json
import logging
import os
import sys
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ecfs-lite")


def main():
    """Entry point for ecfs-lite server."""
    import argparse
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
    
    # Import after adding parent to path
    try:
        from ecfs.lite.auth import AuthDB
        from ecfs.lite.hub import LiteHubAPI
        from ecfs.relay.client import RelayClient
    except ImportError as e:
        logger.error("Failed to import ECFS modules: %s", e)
        logger.error("Make sure ECFS is installed: pip install -e .")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        prog="ecfs-lite",
        description="ECFS Lite gateway — HTTP relay for lite users",
    )
    parser.add_argument("--port", type=int, default=int(os.getenv("ECFS_LITE_PORT", "7703")),
                        help="Listen port")
    parser.add_argument("--relay", default=os.getenv("ECFS_LITE_RELAY", "http://127.0.0.1:7700"),
                        help="ECFS relay URL")
    parser.add_argument("--db", default=os.getenv("ECFS_LITE_DB", "~/.ecfs/lite.db"),
                        help="Database path")
    parser.add_argument("--admin-key", default=os.getenv("ECFS_ADMIN_KEY", ""),
                        help="Master admin key (required)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")

    args = parser.parse_args()

    if not args.admin_key:
        logger.error("ECFS_ADMIN_KEY not set. Set via --admin-key or environment variable.")
        sys.exit(1)

    # Initialize components
    auth_db = AuthDB(args.db)
    relay_client = RelayClient(relay_url=args.relay, node_id="ecfs-lite-gateway", name="ECFS Lite")
    hub_api = LiteHubAPI(auth_db, relay_client, admin_key=args.admin_key)

    logger.info("ECFS Lite starting...")
    logger.info("  Port: %d", args.port)
    logger.info("  Relay: %s", args.relay)
    logger.info("  Database: %s", args.db)

    # ── HTTP Request Handler ─────────────────────────────────────────

    class LiteHTTPHandler(BaseHTTPRequestHandler):
        """HTTP handler for ECFS Lite API."""

        def log_message(self, format, *args):
            logger.debug("HTTP %s", format % args)

        def _send_json(self, data: dict, status: int = 200):
            """Send JSON response."""
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> Optional[dict]:
            """Read JSON request body."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length == 0:
                    return None
                body = self.rfile.read(length)
                return json.loads(body.decode())
            except Exception as e:
                logger.debug("Failed to parse JSON: %s", e)
                return None

        def _get_auth(self) -> Optional[str]:
            """Extract Authorization header."""
            return self.headers.get("Authorization")

        def do_OPTIONS(self):
            """Handle CORS preflight."""
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()

        def do_GET(self):
            """Handle GET requests."""
            path = urlparse(self.path).path
            params = parse_qs(urlparse(self.path).query)

            if path == "/health":
                self._send_json({
                    "status": "ok",
                    "version": "0.1.0",
                    "relay": args.relay,
                    "message": "ECFS Lite gateway is running"
                })

            elif path == "/api/v1/nodes":
                auth = self._get_auth()
                valid, user_id, scopes = hub_api.validate_request(auth, required_scope="send")
                
                if not valid or not user_id:
                    self._send_json({"error": "Unauthorized"}, 401)
                    return

                ok, resp = hub_api.get_user_nodes(user_id)
                self._send_json(resp, 200 if ok else 400)

            elif path == "/api/v1/sensors":
                auth = self._get_auth()
                valid, user_id, scopes = hub_api.validate_request(auth, required_scope="sensor")
                
                if not valid or not user_id:
                    self._send_json({"error": "Unauthorized"}, 401)
                    return

                ok, resp = hub_api.list_user_sensors(user_id)
                self._send_json(resp, 200 if ok else 400)

            else:
                self._send_json({"error": "Not found"}, 404)

        def do_POST(self):
            """Handle POST requests."""
            path = urlparse(self.path).path
            data = self._read_json()

            if path == "/api/v1/auth/register":
                """Register a new lite user (requires admin key)."""
                if not data:
                    self._send_json({"error": "Invalid JSON"}, 400)
                    return

                admin_key = data.get("admin_key", "")
                email = data.get("email", "")
                name = data.get("name", "")

                if not email or not name:
                    self._send_json({"error": "Missing email or name"}, 400)
                    return

                ok, resp = hub_api.register_user(email, name, admin_key)
                self._send_json(resp, 201 if ok else 403)

            elif path == "/api/v1/auth/keys":
                """Create an API key for authenticated user."""
                auth = self._get_auth()
                valid, user_id, scopes = hub_api.validate_request(auth, required_scope="admin")
                
                if not valid or not user_id:
                    self._send_json({"error": "Unauthorized"}, 401)
                    return

                if not data:
                    self._send_json({"error": "Invalid JSON"}, 400)
                    return

                key_name = data.get("name", "default")
                key_scopes = data.get("scopes", ["send", "receive", "sensor"])

                ok, resp = hub_api.create_api_key(user_id, key_name, key_scopes)
                self._send_json(resp, 201 if ok else 400)

            elif path == "/api/v1/nodes/register":
                """Register a new lite node."""
                auth = self._get_auth()
                valid, user_id, scopes = hub_api.validate_request(auth, required_scope="send")
                
                if not valid or not user_id:
                    self._send_json({"error": "Unauthorized"}, 401)
                    return

                if not data:
                    self._send_json({"error": "Invalid JSON"}, 400)
                    return

                node_name = data.get("name", "unnamed")
                device_type = data.get("device_type", "generic")
                config = data.get("config", {})

                ok, resp = hub_api.register_node(user_id, node_name, device_type, config)
                self._send_json(resp, 201 if ok else 400)

            elif path == "/api/v1/sensors/register":
                """Register a sensor for a node."""
                auth = self._get_auth()
                valid, user_id, scopes = hub_api.validate_request(auth, required_scope="sensor")
                
                if not valid or not user_id:
                    self._send_json({"error": "Unauthorized"}, 401)
                    return

                if not data:
                    self._send_json({"error": "Invalid JSON"}, 400)
                    return

                node_id = data.get("node_id", "")
                sensor_type = data.get("sensor_type", "unknown")
                sensor_name = data.get("name", "unnamed")

                if not node_id:
                    self._send_json({"error": "Missing node_id"}, 400)
                    return

                ok, resp = hub_api.register_sensor(user_id, node_id, sensor_type, sensor_name)
                self._send_json(resp, 201 if ok else 400)

            elif path == "/api/v1/nodes/heartbeat":
                """Node keepalive (lite node → hub)."""
                auth = self._get_auth()
                valid, user_id, scopes = hub_api.validate_request(auth, required_scope="send")
                
                if not valid or not user_id:
                    self._send_json({"error": "Unauthorized"}, 401)
                    return

                if not data or "node_id" not in data:
                    self._send_json({"error": "Missing node_id"}, 400)
                    return

                node_id = data.get("node_id")
                ok, resp = hub_api.heartbeat_node(node_id, user_id)
                self._send_json(resp, 200 if ok else 404)

            else:
                self._send_json({"error": "Not found"}, 404)

    # Start HTTP server
    server = HTTPServer((args.host, args.port), LiteHTTPHandler)
    logger.info("ECFS Lite listening on %s:%d", args.host, args.port)
    print(f"ECFS Lite running on http://{args.host}:{args.port}")
    print("Endpoints:")
    print(f"  POST /api/v1/auth/register      — Create new lite user")
    print(f"  POST /api/v1/auth/keys          — Create API key")
    print(f"  GET  /api/v1/nodes              — List user's nodes")
    print(f"  POST /api/v1/nodes/register     — Register new node")
    print(f"  POST /api/v1/nodes/heartbeat    — Node keepalive")
    print(f"  GET  /api/v1/sensors            — List user's sensors")
    print(f"  POST /api/v1/sensors/register   — Register sensor")
    print(f"  GET  /health                    — Hub health check")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
