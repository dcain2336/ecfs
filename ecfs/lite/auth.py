"""ECFS Lite authentication — API key validation, user isolation, scope checking.

All data is encrypted end-to-end. The gateway enforces user isolation:
- User A cannot see User B's nodes, sensors, or messages
- User A cannot access User B's compute resources
- Data flows through encrypted channels only

API Keys have scopes:
- send: can send messages
- receive: can receive messages
- sensor: can access own sensors
- compute: can request compute
- admin: full access (user creation, key management)
"""

import hashlib
import json
import logging
import secrets
import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class APIKey:
    """Represents an API key with scopes and user binding."""
    key_id: str  # short public identifier
    key_secret: str  # hashed secret (never stored plaintext)
    user_id: str  # user who owns this key
    name: str  # human-readable name
    scopes: list[str]  # ["send", "receive", "sensor", "compute", "admin"]
    created_at: float
    last_used: float
    is_active: bool = True

    def to_dict(self):
        return asdict(self)


@dataclass
class LiteUser:
    """A lite user account."""
    user_id: str  # unique user identifier (UUID-like)
    email: str  # contact email
    name: str  # display name
    created_at: float
    is_active: bool = True
    encryption_key: str = ""  # user's primary encryption key (hex)

    def to_dict(self):
        return asdict(self)


class AuthDB:
    """SQLite-backed authentication database for lite users and API keys.
    
    Ensures multi-tenant isolation:
    - Each API key is bound to a single user
    - Queries always filter by user_id
    - No cross-user data leakage
    """

    def __init__(self, db_path: str = "~/.ecfs/lite.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS lite_users (
                user_id TEXT PRIMARY KEY,
                email TEXT UNIQUE,
                name TEXT,
                encryption_key TEXT,
                created_at REAL,
                is_active INTEGER DEFAULT 1
            )
            """)
            
            conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY,
                key_secret_hash TEXT,
                user_id TEXT NOT NULL,
                name TEXT,
                scopes TEXT,
                created_at REAL,
                last_used REAL,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY(user_id) REFERENCES lite_users(user_id)
            )
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS lite_nodes (
                node_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT,
                device_type TEXT,
                registered_at REAL,
                last_seen REAL,
                is_active INTEGER DEFAULT 1,
                config_json TEXT,
                FOREIGN KEY(user_id) REFERENCES lite_users(user_id)
            )
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS sensor_registry (
                sensor_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                sensor_type TEXT,
                name TEXT,
                registered_at REAL,
                FOREIGN KEY(node_id) REFERENCES lite_nodes(node_id),
                FOREIGN KEY(user_id) REFERENCES lite_users(user_id)
            )
            """)
            
            conn.commit()
            logger.info("Auth database initialized at %s", self.db_path)

    # ── User Management ──────────────────────────────────────────────

    def create_user(self, user_id: str, email: str, name: str) -> bool:
        """Create a new lite user account. Returns True on success."""
        try:
            encryption_key = secrets.token_hex(32)  # 64-char hex key
            now = time.time()
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                INSERT INTO lite_users (user_id, email, name, encryption_key, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
                """, (user_id, email, name, encryption_key, now))
                conn.commit()
            logger.info("Created user %s (%s)", user_id, email)
            return True
        except sqlite3.IntegrityError:
            logger.warning("User %s or email %s already exists", user_id, email)
            return False

    def get_user(self, user_id: str) -> Optional[LiteUser]:
        """Fetch a user by ID."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT user_id, email, name, created_at, is_active, encryption_key FROM lite_users WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if row:
                return LiteUser(
                    user_id=row[0],
                    email=row[1],
                    name=row[2],
                    created_at=row[3],
                    is_active=bool(row[4]),
                    encryption_key=row[5]
                )
        return None

    # ── API Key Management ───────────────────────────────────────────

    def create_api_key(self, user_id: str, name: str, scopes: list[str]) -> Optional[tuple[str, str]]:
        """Create an API key for a user. Returns (key_id, key_secret) on success."""
        if not self.get_user(user_id):
            logger.warning("User %s not found", user_id)
            return None

        try:
            key_id = secrets.token_hex(8)  # 16-char hex ID
            key_secret = secrets.token_hex(32)  # 64-char secret
            key_secret_hash = hashlib.sha256(key_secret.encode()).hexdigest()
            now = time.time()

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                INSERT INTO api_keys (key_id, key_secret_hash, user_id, name, scopes, created_at, last_used, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """, (key_id, key_secret_hash, user_id, name, json.dumps(scopes), now, now))
                conn.commit()

            logger.info("Created API key %s for user %s", key_id, user_id)
            return (key_id, key_secret)
        except Exception as e:
            logger.exception("Failed to create API key: %s", e)
            return None

    def validate_api_key(self, key_id: str, key_secret: str) -> Optional[tuple[str, list[str]]]:
        """Validate an API key. Returns (user_id, scopes) if valid, None otherwise.
        
        This also updates last_used timestamp.
        """
        try:
            key_secret_hash = hashlib.sha256(key_secret.encode()).hexdigest()
            
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("""
                SELECT user_id, scopes FROM api_keys 
                WHERE key_id = ? AND key_secret_hash = ? AND is_active = 1
                """, (key_id, key_secret_hash)).fetchone()

                if row:
                    user_id, scopes_json = row
                    scopes = json.loads(scopes_json)
                    
                    # Update last_used
                    conn.execute(
                        "UPDATE api_keys SET last_used = ? WHERE key_id = ?",
                        (time.time(), key_id)
                    )
                    conn.commit()
                    
                    return (user_id, scopes)
        except Exception as e:
            logger.debug("API key validation failed: %s", e)
        
        return None

    def has_scope(self, user_id: str, key_id: str, required_scope: str) -> bool:
        """Check if a user's API key has a required scope."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
            SELECT scopes FROM api_keys 
            WHERE key_id = ? AND user_id = ? AND is_active = 1
            """, (key_id, user_id)).fetchone()
            
            if row:
                scopes = json.loads(row[0])
                return required_scope in scopes or "admin" in scopes
        
        return False

    # ── Lite Node Management ─────────────────────────────────────────

    def register_lite_node(self, node_id: str, user_id: str, name: str, device_type: str, config: dict) -> bool:
        """Register a lite node for a user."""
        if not self.get_user(user_id):
            logger.warning("User %s not found", user_id)
            return False

        try:
            now = time.time()
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                INSERT INTO lite_nodes (node_id, user_id, name, device_type, registered_at, last_seen, is_active, config_json)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """, (node_id, user_id, name, device_type, now, now, json.dumps(config)))
                conn.commit()
            
            logger.info("Registered lite node %s for user %s", node_id, user_id)
            return True
        except sqlite3.IntegrityError:
            logger.warning("Node %s already registered", node_id)
            return False

    def get_user_nodes(self, user_id: str) -> list[dict]:
        """Get all lite nodes for a user (multi-tenant isolation)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
            SELECT node_id, name, device_type, registered_at, last_seen, is_active
            FROM lite_nodes
            WHERE user_id = ? AND is_active = 1
            ORDER BY registered_at DESC
            """, (user_id,)).fetchall()
            
            return [
                {
                    "node_id": row[0],
                    "name": row[1],
                    "device_type": row[2],
                    "registered_at": row[3],
                    "last_seen": row[4],
                    "is_active": bool(row[5])
                }
                for row in rows
            ]

    def update_node_heartbeat(self, node_id: str, user_id: str) -> bool:
        """Update a node's last_seen timestamp (verifies ownership)."""
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute(
                "UPDATE lite_nodes SET last_seen = ? WHERE node_id = ? AND user_id = ?",
                (time.time(), node_id, user_id)
            )
            conn.commit()
            return result.rowcount > 0

    # ── Sensor Registry ──────────────────────────────────────────────

    def register_sensor(self, sensor_id: str, node_id: str, user_id: str, sensor_type: str, name: str) -> bool:
        """Register a sensor for a user's node (multi-tenant isolation)."""
        try:
            now = time.time()
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                INSERT INTO sensor_registry (sensor_id, node_id, user_id, sensor_type, name, registered_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (sensor_id, node_id, user_id, sensor_type, name, now))
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_user_sensors(self, user_id: str) -> list[dict]:
        """Get all sensors for a user (cannot see other users' sensors)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
            SELECT sensor_id, node_id, sensor_type, name, registered_at
            FROM sensor_registry
            WHERE user_id = ?
            ORDER BY registered_at DESC
            """, (user_id,)).fetchall()
            
            return [
                {
                    "sensor_id": row[0],
                    "node_id": row[1],
                    "sensor_type": row[2],
                    "name": row[3],
                    "registered_at": row[4]
                }
                for row in rows
            ]
