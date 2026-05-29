"""Wire protocol for ECFS relay communication.

All messages are JSON over HTTP. Fragments are base64-encoded.
The relay is stateless — nodes register, send fragments, and poll.
"""

import base64
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Message Types ────────────────────────────────────────────────────

@dataclass
class RegisterMessage:
    """Node announces itself to the relay."""
    node_id: str  # hex-encoded node ID
    name: str  # human-readable name
    transports: list[str] = field(default_factory=list)  # ["internet", "ble", ...]

    def to_json(self) -> str:
        return json.dumps({
            "type": "register",
            "node_id": self.node_id,
            "name": self.name,
            "transports": self.transports,
            "timestamp": time.time(),
        })

    @classmethod
    def from_json(cls, data: dict) -> "RegisterMessage":
        return cls(
            node_id=data["node_id"],
            name=data.get("name", "unknown"),
            transports=data.get("transports", []),
        )


@dataclass
class FragmentMessage:
    """A fragment sent through the relay."""
    node_id: str  # sender's hex node ID
    fragment: str  # base64-encoded fragment bytes
    dest: str = "*"  # destination node ID hex, or "*" for broadcast

    def to_json(self) -> str:
        return json.dumps({
            "type": "fragment",
            "node_id": self.node_id,
            "fragment": self.fragment,
            "dest": self.dest,
            "timestamp": time.time(),
        })

    @classmethod
    def from_json(cls, data: dict) -> "FragmentMessage":
        return cls(
            node_id=data["node_id"],
            fragment=data["fragment"],
            dest=data.get("dest", "*"),
        )

    @property
    def fragment_bytes(self) -> bytes:
        return base64.b64decode(self.fragment)

    @classmethod
    def from_bytes(cls, node_id: str, data: bytes, dest: str = "*") -> "FragmentMessage":
        return cls(
            node_id=node_id,
            fragment=base64.b64encode(data).decode(),
            dest=dest,
        )


@dataclass
class HeartbeatMessage:
    """Node keepalive."""
    node_id: str

    def to_json(self) -> str:
        return json.dumps({
            "type": "heartbeat",
            "node_id": self.node_id,
            "timestamp": time.time(),
        })

    @classmethod
    def from_json(cls, data: dict) -> "HeartbeatMessage":
        return cls(node_id=data["node_id"])


@dataclass
class PollMessage:
    """Node requests pending fragments."""
    node_id: str  # requesting node's hex ID

    def to_json(self) -> str:
        return json.dumps({
            "type": "poll",
            "node_id": self.node_id,
        })

    @classmethod
    def from_json(cls, data: dict) -> "PollMessage":
        return cls(node_id=data["node_id"])


@dataclass
class RelayResponse:
    """Response from relay."""
    ok: bool
    data: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({"ok": self.ok, **self.data})

    @classmethod
    def ok_response(cls, **data) -> "RelayResponse":
        return cls(ok=True, data=data)

    @classmethod
    def error(cls, message: str) -> "RelayResponse":
        return cls(ok=False, data={"error": message})


@dataclass
class NodeInfo:
    """Information about a connected node."""
    node_id: str
    name: str
    transports: list[str] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.last_seen) > 60.0

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "transports": self.transports,
            "last_seen": self.last_seen,
        }


# ── Encoding Helpers ─────────────────────────────────────────────────

def encode_fragment_for_relay(data: bytes) -> str:
    """Encode raw fragment bytes for JSON transport."""
    return base64.b64encode(data).decode("ascii")


def decode_fragment_from_relay(encoded: str) -> bytes:
    """Decode base64 fragment from relay."""
    return base64.b64decode(encoded)


def parse_message(body: str) -> Optional[dict]:
    """Parse a JSON message body, returning the parsed dict or None."""
    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
