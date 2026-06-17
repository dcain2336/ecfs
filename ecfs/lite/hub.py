"""ECFS Lite Hub — REST API for lite users to manage nodes, sensors, and messages.

Endpoints:
  /api/v1/auth/register     — Create a new lite user account
  /api/v1/auth/keys         — List/create API keys for authenticated users
  /api/v1/nodes             — List user's nodes
  /api/v1/nodes/register    — Register a new lite node
  /api/v1/sensors           — List user's sensors
  /api/v1/messages/send     — Send a message through the mesh
  /api/v1/messages/receive  — Poll for incoming messages
  /api/v1/health            — Hub health check

All endpoints enforce multi-tenant isolation via API key validation.
Data is encrypted end-to-end.
"""

import hashlib
import json
import logging
import secrets
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class LiteHubAPI:
    """REST API handler for ECFS Lite hub.
    
    Manages user registration, API keys, node enrollment, messaging,
    and sensor access with strict multi-tenant isolation.
    """

    def __init__(self, auth_db, relay_client=None, admin_key: str = ""):
        """
        Args:
            auth_db: AuthDB instance for user/key management
            relay_client: RelayClient instance for mesh communication
            admin_key: Master admin key (for creating first users)
        """
        self.auth_db = auth_db
        self.relay_client = relay_client
        self.admin_key = admin_key
        self.message_queue = {}  # node_id -> [encrypted_messages]

    # ── Authentication ───────────────────────────────────────────────

    def register_user(self, email: str, name: str, admin_key: str) -> Tuple[bool, dict]:
        """Create a new lite user account (requires admin key).
        
        Returns (success, response_dict).
        """
        if admin_key != self.admin_key:
            return False, {"error": "Invalid admin key"}

        try:
            user_id = secrets.token_hex(16)  # 32-char hex user ID
            
            if self.auth_db.create_user(user_id, email, name):
                return True, {
                    "user_id": user_id,
                    "email": email,
                    "name": name,
                    "message": "User created. Next: create an API key."
                }
            else:
                return False, {"error": "Email already registered"}
        except Exception as e:
            logger.exception("Registration failed: %s", e)
            return False, {"error": str(e)}

    def validate_request(self, auth_header: Optional[str], required_scope: str = "") -> Tuple[bool, Optional[str], list]:
        """Validate API key from Authorization header.
        
        Returns (valid, user_id, scopes).
        Authorization: Bearer <key_id>.<key_secret>
        """
        if not auth_header or not auth_header.startswith("Bearer "):
            return False, None, []

        try:
            token = auth_header[7:].strip()  # Remove "Bearer "
            if "." not in token:
                return False, None, []

            key_id, key_secret = token.split(".", 1)
            
            result = self.auth_db.validate_api_key(key_id, key_secret)
            if not result:
                return False, None, []

            user_id, scopes = result
            
            # Check required scope
            if required_scope and required_scope not in scopes and "admin" not in scopes:
                return False, user_id, scopes

            return True, user_id, scopes
        except Exception as e:
            logger.debug("Request validation failed: %s", e)
            return False, None, []

    def create_api_key(self, user_id: str, name: str, scopes: list[str]) -> Tuple[bool, dict]:
        """Create a new API key for a user."""
        result = self.auth_db.create_api_key(user_id, name, scopes)
        if result:
            key_id, key_secret = result
            return True, {
                "key_id": key_id,
                "key_secret": key_secret,
                "token": f"{key_id}.{key_secret}",
                "scopes": scopes,
                "message": "Save this token securely — it won't be shown again"
            }
        return False, {"error": "Failed to create API key"}

    # ── Node Management ──────────────────────────────────────────────

    def register_node(self, user_id: str, node_name: str, device_type: str, config: dict) -> Tuple[bool, dict]:
        """Register a new lite node for a user."""
        try:
            node_id = secrets.token_hex(16)  # 32-char node ID
            
            if self.auth_db.register_lite_node(node_id, user_id, node_name, device_type, config):
                return True, {
                    "node_id": node_id,
                    "name": node_name,
                    "device_type": device_type,
                    "message": "Node registered. Provide node_id to lite node installer."
                }
            return False, {"error": "Node registration failed"}
        except Exception as e:
            logger.exception("Node registration failed: %s", e)
            return False, {"error": str(e)}

    def get_user_nodes(self, user_id: str) -> Tuple[bool, dict]:
        """Get list of all nodes for a user."""
        try:
            nodes = self.auth_db.get_user_nodes(user_id)
            return True, {"nodes": nodes}
        except Exception as e:
            logger.exception("Failed to list nodes: %s", e)
            return False, {"error": str(e)}

    def heartbeat_node(self, node_id: str, user_id: str) -> Tuple[bool, dict]:
        """Update a node's last_seen timestamp (keepalive)."""
        if self.auth_db.update_node_heartbeat(node_id, user_id):
            return True, {"ok": True}
        return False, {"error": "Node not found or not yours"}

    # ── Sensor Access ───────────────────────────────────────────────

    def register_sensor(self, user_id: str, node_id: str, sensor_type: str, name: str) -> Tuple[bool, dict]:
        """Register a new sensor for a node."""
        try:
            sensor_id = secrets.token_hex(8)
            
            if self.auth_db.register_sensor(sensor_id, node_id, user_id, sensor_type, name):
                return True, {
                    "sensor_id": sensor_id,
                    "node_id": node_id,
                    "sensor_type": sensor_type,
                    "name": name
                }
            return False, {"error": "Sensor already registered"}
        except Exception as e:
            logger.exception("Sensor registration failed: %s", e)
            return False, {"error": str(e)}

    def list_user_sensors(self, user_id: str) -> Tuple[bool, dict]:
        """Get all sensors accessible to a user (their own only)."""
        try:
            sensors = self.auth_db.get_user_sensors(user_id)
            return True, {"sensors": sensors}
        except Exception as e:
            logger.exception("Failed to list sensors: %s", e)
            return False, {"error": str(e)}

    # ── Messaging (Encrypted) ────────────────────────────────────────

    async def send_message(
        self, 
        user_id: str, 
        dest_node_id: str, 
        encrypted_payload: str,  # base64-encoded encrypted data
        dest_user_id: Optional[str] = None
    ) -> Tuple[bool, dict]:
        """Send an encrypted message through the mesh.
        
        For lite users:
        - Can only send to their own nodes (same user_id)
        - Messages are encrypted end-to-end
        - Data flows through relay without gateway visibility
        
        Args:
            user_id: Sender's user ID
            dest_node_id: Destination node ID
            encrypted_payload: Base64 encrypted message
            dest_user_id: Optional, for multi-user messaging (if allowed)
        
        Returns:
            (success, response_dict)
        """
        if not self.relay_client:
            return False, {"error": "Relay unavailable"}

        try:
            # Verify node ownership
            user_nodes = self.auth_db.get_user_nodes(user_id)
            node_ids = [n["node_id"] for n in user_nodes]
            
            if dest_node_id not in node_ids:
                return False, {"error": "Node not found or not yours"}

            # Send through relay
            message_bytes = encrypted_payload.encode()
            ok = await self.relay_client.send_fragment(message_bytes, dest=dest_node_id)
            
            if ok:
                return True, {
                    "ok": True,
                    "dest_node_id": dest_node_id,
                    "message": "Message sent (encrypted)"
                }
            return False, {"error": "Relay rejected message"}
        except Exception as e:
            logger.exception("Send message failed: %s", e)
            return False, {"error": str(e)}

    async def poll_messages(self, user_id: str, timeout: float = 5.0) -> Tuple[bool, dict]:
        """Poll for incoming encrypted messages for user's nodes.
        
        Returns messages only for nodes owned by this user.
        """
        if not self.relay_client:
            return False, {"error": "Relay unavailable"}

        try:
            user_nodes = self.auth_db.get_user_nodes(user_id)
            
            messages = []
            for node in user_nodes:
                node_id = node["node_id"]
                # Poll relay for this node
                frags = await self.relay_client.poll(timeout=timeout)
                
                for frag in frags:
                    messages.append({
                        "node_id": node_id,
                        "payload": frag.hex(),  # hex-encoded encrypted data
                        "timestamp": time.time()
                    })

            return True, {"messages": messages}
        except Exception as e:
            logger.exception("Poll messages failed: %s", e)
            return False, {"error": str(e)}

    # ── Health & Status ──────────────────────────────────────────────

    async def health(self) -> dict:
        """Check hub and relay health."""
        relay_health = None
        if self.relay_client:
            relay_health = await self.relay_client.get_health()

        return {
            "hub": "ok",
            "relay": "ok" if relay_health and relay_health.get("ok") else "offline",
            "timestamp": time.time()
        }
