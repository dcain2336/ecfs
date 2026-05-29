"""Tests for ecfs.relay.protocol — message types, serialization, encoding helpers."""

import base64
import json
import time

import pytest

from ecfs.relay.protocol import (
    RegisterMessage,
    FragmentMessage,
    HeartbeatMessage,
    PollMessage,
    RelayResponse,
    NodeInfo,
    encode_fragment_for_relay,
    decode_fragment_from_relay,
    parse_message,
)


# ── RegisterMessage ─────────────────────────────────────────────────

class TestRegisterMessage:
    def test_to_json_roundtrip(self):
        msg = RegisterMessage(
            node_id="aabbccdd",
            name="test-node",
            transports=["internet", "ble"],
        )
        raw = msg.to_json()
        data = json.loads(raw)

        assert data["type"] == "register"
        assert data["node_id"] == "aabbccdd"
        assert data["name"] == "test-node"
        assert data["transports"] == ["internet", "ble"]
        assert "timestamp" in data

    def test_from_json(self):
        data = {
            "type": "register",
            "node_id": "11223344",
            "name": "peer-one",
            "transports": ["lora"],
        }
        msg = RegisterMessage.from_json(data)
        assert msg.node_id == "11223344"
        assert msg.name == "peer-one"
        assert msg.transports == ["lora"]

    def test_from_json_defaults(self):
        data = {"type": "register", "node_id": "99"}
        msg = RegisterMessage.from_json(data)
        assert msg.name == "unknown"
        assert msg.transports == []


# ── FragmentMessage ─────────────────────────────────────────────────

class TestFragmentMessage:
    def test_to_json(self):
        payload = b"hello world"
        encoded = base64.b64encode(payload).decode()
        msg = FragmentMessage(node_id="aa", fragment=encoded, dest="bb")
        raw = msg.to_json()
        data = json.loads(raw)

        assert data["type"] == "fragment"
        assert data["node_id"] == "aa"
        assert data["fragment"] == encoded
        assert data["dest"] == "bb"
        assert "timestamp" in data

    def test_from_json(self):
        payload = b"\x00\x01\x02"
        encoded = base64.b64encode(payload).decode()
        data = {
            "type": "fragment",
            "node_id": "ff",
            "fragment": encoded,
            "dest": "*",
        }
        msg = FragmentMessage.from_json(data)
        assert msg.node_id == "ff"
        assert msg.fragment == encoded
        assert msg.dest == "*"

    def test_from_json_default_dest(self):
        data = {
            "type": "fragment",
            "node_id": "aa",
            "fragment": "AAAA",
        }
        msg = FragmentMessage.from_json(data)
        assert msg.dest == "*"

    def test_from_bytes_creates_base64(self):
        raw = b"\xde\xad\xbe\xef"
        msg = FragmentMessage.from_bytes("sender1", raw, dest="recv1")
        assert msg.node_id == "sender1"
        assert msg.dest == "recv1"
        assert msg.fragment_bytes == raw
        # Verify it's valid base64
        assert base64.b64decode(msg.fragment) == raw

    def test_from_bytes_default_dest(self):
        msg = FragmentMessage.from_bytes("x", b"yz")
        assert msg.dest == "*"

    def test_fragment_bytes_property(self):
        payload = b"\x42" * 100
        encoded = base64.b64encode(payload).decode()
        msg = FragmentMessage(node_id="n", fragment=encoded)
        assert msg.fragment_bytes == payload

    def test_large_fragment(self):
        payload = bytes(range(256)) * 100  # 25 600 bytes
        msg = FragmentMessage.from_bytes("big", payload)
        assert msg.fragment_bytes == payload
        # Roundtrip through JSON
        data = json.loads(msg.to_json())
        rebuilt = FragmentMessage.from_json(data)
        assert rebuilt.fragment_bytes == payload


# ── HeartbeatMessage ────────────────────────────────────────────────

class TestHeartbeatMessage:
    def test_to_json(self):
        msg = HeartbeatMessage(node_id="abcd")
        data = json.loads(msg.to_json())
        assert data["type"] == "heartbeat"
        assert data["node_id"] == "abcd"
        assert "timestamp" in data

    def test_from_json(self):
        data = {"type": "heartbeat", "node_id": "1234", "timestamp": 1.0}
        msg = HeartbeatMessage.from_json(data)
        assert msg.node_id == "1234"


# ── PollMessage ─────────────────────────────────────────────────────

class TestPollMessage:
    def test_to_json_roundtrip(self):
        msg = PollMessage(node_id="poller1")
        data = json.loads(msg.to_json())
        assert data["type"] == "poll"
        assert data["node_id"] == "poller1"

        rebuilt = PollMessage.from_json(data)
        assert rebuilt.node_id == "poller1"


# ── RelayResponse ───────────────────────────────────────────────────

class TestRelayResponse:
    def test_ok_response(self):
        resp = RelayResponse.ok_response(count=5)
        data = json.loads(resp.to_json())
        assert data["ok"] is True
        assert data["count"] == 5

    def test_ok_response_no_extra(self):
        resp = RelayResponse.ok_response()
        data = json.loads(resp.to_json())
        assert data == {"ok": True}

    def test_error(self):
        resp = RelayResponse.error("something broke")
        data = json.loads(resp.to_json())
        assert data["ok"] is False
        assert data["error"] == "something broke"


# ── NodeInfo ────────────────────────────────────────────────────────

class TestNodeInfo:
    def test_is_stale_false_when_recent(self):
        node = NodeInfo(node_id="n1", name="fresh", last_seen=time.time())
        assert node.is_stale is False

    def test_is_stale_true_when_old(self):
        node = NodeInfo(node_id="n1", name="stale", last_seen=time.time() - 120)
        assert node.is_stale is True

    def test_is_stale_boundary_just_under(self):
        node = NodeInfo(node_id="n1", name="b", last_seen=time.time() - 59.9)
        assert node.is_stale is False

    def test_is_stale_boundary_exactly_60(self):
        # The protocol uses > 60.0. We compute last_seen so that
        # time.time() - last_seen will be slightly > 60.0 due to
        # elapsed time between the two time.time() calls.
        node = NodeInfo(node_id="n1", name="b", last_seen=time.time() - 60.0)
        # With floating point, the second time.time() call is always
        # slightly later, so the node IS stale (difference > 60.0).
        assert node.is_stale is True

    def test_is_stale_boundary_just_over_60(self):
        node = NodeInfo(node_id="n1", name="b", last_seen=time.time() - 60.1)
        assert node.is_stale is True

    def test_to_dict(self):
        node = NodeInfo(node_id="n1", name="x", transports=["ble"])
        d = node.to_dict()
        assert d["node_id"] == "n1"
        assert d["name"] == "x"
        assert d["transports"] == ["ble"]
        assert "last_seen" in d

    def test_default_last_seen_is_recent(self):
        before = time.time()
        node = NodeInfo(node_id="n1", name="x")
        after = time.time()
        assert before <= node.last_seen <= after


# ── Encoding helpers ────────────────────────────────────────────────

class TestEncodingHelpers:
    def test_encode_fragment_for_relay(self):
        raw = b"\x01\x02\x03"
        encoded = encode_fragment_for_relay(raw)
        assert isinstance(encoded, str)
        assert base64.b64decode(encoded) == raw

    def test_decode_fragment_from_relay(self):
        raw = b"\xff\xfe\xfd"
        encoded = base64.b64encode(raw).decode("ascii")
        decoded = decode_fragment_from_relay(encoded)
        assert decoded == raw

    def test_roundtrip(self):
        data = b"test data for relay encoding \x00\x01"
        encoded = encode_fragment_for_relay(data)
        assert decode_fragment_from_relay(encoded) == data

    def test_empty_bytes(self):
        assert encode_fragment_for_relay(b"") == ""
        assert decode_fragment_from_relay("") == b""

    def test_binary_data(self):
        data = bytes(range(256))
        encoded = encode_fragment_for_relay(data)
        assert len(encoded) > 0
        assert decode_fragment_from_relay(encoded) == data


# ── parse_message ───────────────────────────────────────────────────

class TestParseMessage:
    def test_valid_json(self):
        result = parse_message('{"type": "register"}')
        assert result == {"type": "register"}

    def test_invalid_json(self):
        result = parse_message("not json at all {{{")
        assert result is None

    def test_empty_string(self):
        result = parse_message("")
        assert result is None

    def test_none_input(self):
        result = parse_message(None)
        assert result is None

    def test_valid_array(self):
        result = parse_message("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_nested_json(self):
        inner = json.dumps({"a": {"b": 1}})
        result = parse_message(inner)
        assert result["a"]["b"] == 1

    def test_boolean_and_null(self):
        result = parse_message("true")
        assert result is True
        result = parse_message("null")
        assert result is None
