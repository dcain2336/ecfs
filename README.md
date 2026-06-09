# ECFS — Autonomous Emergency Communication Failover System

![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)
![Tests](https://img.shields.io/badge/Tests-408%2B-passing)
![Version](https://img.shields.io/badge/Version-0.6.0-blue)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Transports](https://img.shields.io/badge/Transports-13-orange)

A **delay-tolerant network (DTN) routing engine** with modular transport plugins, designed for communications-degraded environments — hostile territories, disaster zones, or infrastructure-denied areas.

ECFS autonomously routes encrypted data payloads using any available ambient means. It acts as a **universal adapter for communication**, bridging the gap when traditional lines are severed — without requiring ECFS software on intermediary nodes.

---

## Architecture

```
┌───────────────────────────────────────────────────────────┐
│                 MeshOrchestrator (Brain)                  │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Fragment   │  │   Message    │  │  Deduplication   │  │
│  │  Manager    │  │   Queue      │  │  Cache           │  │
│  │  (split/    │  │  (priority + │  │  (LRU + TTL)     │  │
│  │   reassem)  │  │   SQLite)    │  │                  │  │
│  └────────────┘  └──────────────┘  └──────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              State Machine                           │ │
│  │   NORMAL → DEGRADED → EMERGENCY → RECOVERY          │ │
│  └──────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────┐ │
│  │           Cryptographic Envelope                     │ │
│  │  AES-256-GCM + Ed25519 + X25519 ECDH (PFS)         │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────────┬────────────────────────────────┘
                           │  Plugin API
     ┌─────────┬───────────┼───────────┬──────────┐
     ▼         ▼           ▼           ▼          ▼
┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌──────────┐
│ Internet││  DNS    ││  LoRa   ││   BLE   ││Ultrasonic│
│ (HTTPS) ││ Tunnel  ││  Radio  ││  Radio  ││  Audio   │
└─────────┘└─────────┘└─────────┘└─────────┘└──────────┘
     ┌──────────┐┌──────────┐┌──────────┐┌──────────┐
     ▼          ▼          ▼          ▼          ▼
┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌──────────┐
│  RFID   ││ Stego   ││   Tor   ││   I2P   ││Yggdrasil │
│  (NFC)  ││  HTTP   ││ (SOCKS) ││ (Proxy) ││ (IPv6)   │
└─────────┘└─────────┘└─────────┘└─────────┘└──────────┘
     ┌──────────┐┌──────────┐┌──────────┐
     ▼          ▼          ▼          ▼
┌─────────┐┌─────────┐┌─────────┐┌──────────┐
│  Multi- ││Meshtastic││  Null   ││  Relay   │
│  Path   ││  (MQTT)  ││ (Mock)  ││  Server  │
└─────────┘└─────────┘└─────────┘└──────────┘
```

---

## Transport Plugins

ECFS ships with **13 transport plugins**, all implementing the `TransportPlugin` ABC:

| # | Plugin | File | Lines | Type | Description |
|---|--------|------|-------|------|-------------|
| 1 | `InternetTransport` | `internet_transport.py` | 85 | Network | HTTP/HTTPS packet relay via `httpx` |
| 2 | `DNSTunnelTransport` | `dns_transport.py` | 137 | Covert | DNS label encoding for covert data exfiltration |
| 3 | `SteganographicHTTP` | `stego_transport.py` | 198 | Covert | Hides ECFS packets in HTTP traffic metadata |
| 4 | `LoRaTransport` | `lora_transport.py` | 114 | Radio | Meshtastic-compatible serial radio (237-byte MTU) |
| 5 | `BLETransport` | `ble_transport.py` | 139 | Radio | Bluetooth Low Energy GATT service-based exchange |
| 6 | `UltrasonicAudioTransport` | `ultrasonic_transport.py` | 187 | Acoustic | 18-22 kHz FSK-modulated audio with Reed-Solomon ECC |
| 7 | `RFIDTransport` | `rfid_transport.py` | 160 | Proximity | NFC tag-based sneakernet relay (NTAG216/MIFARE) |
| 8 | `TorTransport` | `tor_transport.py` | 457 | Covert | Tor network via SOCKS5 proxy with health checks |
| 9 | `I2PTransport` | `i2p_transport.py` | 306 | Covert | I2P anonymity network via local HTTP proxy |
| 10 | `YggdrasilTransport` | `yggdrasil_transport.py` | 277 | Network | Yggdrasil IPv6 encrypted mesh with auto-crypto |
| 11 | `MultiPathTransport` | `multipath_transport.py` | 352 | Network | Shotgun across multiple relay endpoints simultaneously |
| 12 | `MeshtasticMQTTTransport` | `meshtastic_mqtt_transport.py` | 426 | Radio | Meshtastic via MQTT broker with channel encryption |
| 13 | `NullTransport` | `null_transport.py` | 66 | Mock | In-memory transport for testing — no hardware required |

All plugins share a common interface:

```python
class TransportPlugin(ABC):
    name: str
    transport_type: TransportType
    priority: int

    async def initialize(self) -> None: ...
    async def teardown(self) -> None: ...
    async def send_packet(self, data: bytes) -> bool: ...
    async def receive_packet(self) -> Optional[bytes]: ...
    async def get_status(self) -> TransportStatus: ...
```

### Transport Categories

- **Network** (clearnet): `InternetTransport`, `YggdrasilTransport`, `MultiPathTransport`
- **Covert** (anonymity): `TorTransport`, `I2PTransport`, `SteganographicHTTP`, `DNSTunnelTransport`
- **Radio** (wireless): `LoRaTransport`, `BLETransport`, `MeshtasticMQTTTransport`
- **Acoustic** (audio): `UltrasonicAudioTransport`
- **Proximity** (physical): `RFIDTransport`
- **Mock** (testing): `NullTransport`

---

## ECFS Lite — Commercial Agent Gateway

A separate 1,900-line server (`ecfs-lite.py`) that bridges commercial AI agents into the ECFS mesh:

- **Port 7703** — HTTP server with bearer-token auth
- **17 handlers**: health, pay, register, send, status, compute sharing, sensor mesh, task scheduling, credits, trust scoring, admin
- **NOWPayments integration** — crypto payments for agent access ($1/month)
- **Trust & credits** — agents earn credits by completing distributed compute tasks
- **Forwards to relay** — messages flow to the main ECFS relay on port 7700

```bash
# Run ECFS Lite
python ecfs-lite.py --port 7703 --relay http://127.0.0.1:7700
```

---

## Relay Server

The relay server (`ecfs/relay/server.py`, 592 lines) is the central hub for fragment forwarding:

- **Port 7700** — async TCP server for ECFS packet relay
- **Wire protocol**: Register → Fragment → Heartbeat messages
- **RelayClient** — Python client for connecting to relay servers
- **Fragment forwarding** — unknown fragments automatically relayed to other connected nodes

---

## Installation

```bash
# Core engine (minimal — only requires `cryptography`)
pip install -e .

# With internet transport (httpx, fastapi, uvicorn)
pip install -e ".[internet]"

# With radio transport (pyserial, bleak, paho-mqtt)
pip install -e ".[radio]"

# With audio transport (scipy, pyaudio)
pip install -e ".[audio]"

# With overlay networks (tor, i2p)
pip install -e ".[overlay]"

# Everything
pip install -e ".[all]"

# Development (pytest, ruff, mypy, coverage)
pip install -e ".[dev]"
```

### Requirements

- **Python** ≥ 3.11
- **Core**: `cryptography ≥ 42.0`
- **Internet**: `httpx ≥ 0.27`, `fastapi ≥ 0.111`, `uvicorn ≥ 0.29`
- **Radio**: `pyserial ≥ 3.5`, `bleak ≥ 0.22`, `paho-mqtt ≥ 1.6`
- **Audio**: `scipy ≥ 1.13`, `pyaudio ≥ 0.2.14`
- **Overlay**: `pysocks ≥ 1.7` (Tor SOCKS5), `i2plib ≥ 0.7` (I2P)

---

## Quick Start

```python
import asyncio
from ecfs import ECFSEngine
from ecfs.plugins import NullTransport

async def main():
    engine = ECFSEngine()

    # Register any available transport
    engine.register_plugin(NullTransport())
    await engine.start()

    # Send encrypted data
    success = await engine.send(b"Mayday, Mayday!")

    # Receive from any transport
    received = await engine.receive()

    await engine.stop()

asyncio.run(main())
```

### Mesh Node (auto-discovery)

```python
import asyncio
from ecfs.discovery import MeshNode

async def main():
    node = MeshNode(name="rescue-1")
    await node.start()

    # Auto-detects hardware and creates transports
    await node.send(b"Status report: all clear")
    message = await node.receive()

asyncio.run(main())
```

### MeshOrchestrator (full control)

```python
import asyncio
from ecfs.core.orchestrator import MeshOrchestrator
from ecfs.plugins import InternetTransport, TorTransport
from ecfs.crypto.keys import ECFSKeyPair

async def main():
    keypair = ECFSKeyPair.generate()

    orch = MeshOrchestrator(keypair=keypair, enable_relay=True)
    orch.register_transport(InternetTransport(relay_url="https://relay.example.com/mesh/ingest"))
    orch.register_transport(TorTransport(relay_url="http://onion-address.onion/mesh/ingest"))

    await orch.start()

    # Send — fragments across all transports simultaneously
    await orch.send(b"Emergency broadcast to all nodes")

    # Receive — reassembles from any transport
    message = await orch.receive()

    await orch.stop()

asyncio.run(main())
```

### MultiPath Transport (redundant routing)

```python
from ecfs.plugins.multipath_transport import MultiPathTransport

# Automatically loads endpoints from ecfs-transport-endpoints.json
# Sends to ALL connected paths simultaneously (shotgun)
# Falls back across paths automatically
multipath = MultiPathTransport(node_id="rescue-1")
```

### Tor Transport (covert routing)

```python
from ecfs.plugins.tor_transport import TorTransport

# Routes through Tor SOCKS5 proxy for anonymity
tor = TorTransport(
    relay_url="http://onion-address.onion/mesh/ingest",
    socks_proxy="127.0.0.1:9050",
)
```

---

## CLI

```bash
# Node management
ecfs node start              # Start a mesh node (auto-detects hardware)
ecfs node send "message"     # Send through the mesh
ecfs node receive            # Listen for incoming messages

# Relay server
ecfs relay start             # Start a public relay server
ecfs relay status            # Check if a relay is running

# Diagnostics
ecfs detect                  # Show detected hardware
ecfs status                  # Show node status and available transports
ecfs send "demo message"     # Demo mode — no relay needed
ecfs version                 # Print version
```

---

## Project Structure

```
ecfs/
├── ecfs/                          # Main package (v0.6.0)
│   ├── __init__.py                # Package exports
│   ├── cli.py                     # CLI entry point (365 lines)
│   ├── crypto/                    # Cryptographic envelope
│   │   ├── packet.py              #   ECFSPacket — binary envelope format (131 lines)
│   │   ├── keys.py                #   ECFSKeyPair — Ed25519 + X25519 (157 lines)
│   │   └── cipher.py              #   AES-256-GCM encrypt/decrypt (51 lines)
│   ├── core/                      # Core engine
│   │   ├── engine.py              #   ECFSEngine — main orchestrator
│   │   ├── orchestrator.py        #   MeshOrchestrator — fragmentation, relay, shotgun
│   │   ├── routing.py             #   RoutingEngine — strategies
│   │   ├── queue.py               #   MessageQueue — priority + SQLite
│   │   ├── dedup.py               #   DeduplicationCache — LRU + TTL
│   │   ├── fragmentation.py       #   FragmentManager — split/reassemble
│   │   ├── state_machine.py       #   StateMachine — NORMAL→EMERGENCY
│   │   ├── threat_assessor.py     #   ThreatAssessor — risk scoring
│   │   ├── dns.py                 #   DNS label encoding
│   │   └── hop.py                 #   HopRecord — cross-medium tracking
│   ├── plugins/                   # Transport plugins (3,198 lines total)
│   │   ├── base.py                #   TransportPlugin ABC (100 lines)
│   │   ├── registry.py            #   PluginRegistry (87 lines)
│   │   ├── __init__.py            #   Package exports (41 lines)
│   │   ├── null_transport.py      #   NullTransport — mock (66 lines)
│   │   ├── internet_transport.py  #   InternetTransport — HTTP/HTTPS (85 lines)
│   │   ├── dns_transport.py       #   DNSTunnelTransport — DNS covert (137 lines)
│   │   ├── stego_transport.py     #   SteganographicHTTP — metadata stego (198 lines)
│   │   ├── lora_transport.py      #   LoRaTransport — Meshtastic serial (114 lines)
│   │   ├── ble_transport.py       #   BLETransport — Bluetooth LE GATT (139 lines)
│   │   ├── ultrasonic_transport.py#   UltrasonicAudioTransport — FSK audio (187 lines)
│   │   ├── rfid_transport.py      #   RFIDTransport — NFC tag relay (160 lines)
│   │   ├── tor_transport.py       #   TorTransport — SOCKS5 proxy (457 lines)
│   │   ├── i2p_transport.py       #   I2PTransport — I2P proxy (306 lines)
│   │   ├── yggdrasil_transport.py #   YggdrasilTransport — IPv6 mesh (277 lines)
│   │   ├── multipath_transport.py #   MultiPathTransport — shotgun relay (352 lines)
│   │   ├── meshtastic_mqtt_transport.py  # MeshtasticMQTTTransport (426 lines)
│   │   └── relay_server.py        #   RelayServer — TCP relay (66 lines)
│   ├── discovery/                 # Auto-discovery & mesh
│   │   ├── hardware.py            #   HardwareProfile — detect hardware
│   │   ├── transport_factory.py   #   create_transports() — auto-create plugins
│   │   ├── peer.py                #   Peer / PeerTracker
│   │   └── mesh.py                #   MeshNode — zero-config mesh
│   └── relay/                     # HTTP relay system
│       ├── protocol.py            #   Wire protocol (203 lines)
│       ├── server.py              #   RelayServer — TCP relay (592 lines)
│       └── client.py              #   RelayClient (275 lines)
├── ecfs-lite.py                   # Commercial Agent Gateway (1,922 lines)
├── tests/                         # 408+ test functions
│   ├── test_crypto/               #   34 tests
│   ├── test_core/                 #   41 tests
│   ├── test_plugins/              #  140 tests
│   ├── discovery/                 #   42 tests
│   ├── test_dns.py                #    8 tests
│   ├── test_engine.py             #   10 tests
│   ├── test_relay*.py             #  104 tests
│   └── test_integration_*.py      #   27 tests
├── pyproject.toml                 # Build config (hatchling) + optional deps
└── .github/workflows/ci.yml      # GitHub Actions CI
```

---

## Testing

```bash
# Run the full suite (408+ tests)
pytest

# Run with coverage
pytest --cov=ecfs --cov-report=term-missing

# Run a specific module
pytest tests/test_plugins/ -v
pytest tests/test_core/ -v
pytest tests/test_crypto/ -v
```

### Test Breakdown

| Category | Tests | Coverage |
|----------|-------|----------|
| Crypto (packet, keys, cipher) | 34 | Envelope format, key exchange, AES-256-GCM |
| Core (routing, queue, dedup, state machine, threats, hops) | 41 | Strategies, TTL queue, bloom filter, failover states |
| Plugins (all transports + integration) | 140 | Each plugin + phase 2/3/4 integration tests |
| Discovery (hardware, mesh, peer, factory) | 42 | Hardware detection, auto-transport creation |
| DNS encoding | 8 | Label encoding/decoding roundtrip |
| Engine orchestration | 10 | ECFSEngine lifecycle, send/receive |
| Relay system | 104 | Protocol, server, client, end-to-end |
| Integration (full-flow + mesh) | 27 | Multi-node, fragmentation, reassembly |

---

## Core Engine

- **Packet Normalization**: All data wrapped in a standard ECFS envelope (Message ID, TTL, Destination Hash, Encrypted Payload)
- **Fragmentation**: Large messages split into numbered fragments (128-byte default) that survive independent delivery across heterogeneous transports
- **Deduplication Cache**: TTL-based LRU with bloom filter fast-path — prevents infinite routing loops
- **Priority Queue**: Critical messages jump the queue; optional SQLite persistence survives restarts; expired packets auto-dropped
- **Routing Strategies**: Shotgun (redundant flooding), Shortest-path, Adaptive (priority-aware)
- **State Machine**: `NORMAL` → `DEGRADED` → `EMERGENCY` → `RECOVERY` with callback hooks
- **Threat Assessment**: Risk scoring from packet loss, latency, error count, and jamming detection

## Cryptographic Envelope

- **AES-256-GCM** encryption with random nonces
- **Ed25519** signatures for packet authenticity
- **X25519 ECDH** key agreement with HKDF session key rotation (Perfect Forward Secrecy)
- **Binary format**: 81-byte fixed header + variable payload + signature

## MeshOrchestrator

The "living brain" that makes ECFS behave as one adaptive organism:

- **Shotgun routing**: Fires fragments through ALL available transports simultaneously
- **Automatic failover**: When a transport dies, seamlessly shifts to others
- **Store-and-forward**: Queues packets and retries when new paths appear
- **Fragment relay**: Every node forwards unknown fragments — each node is also a router
- **Fragment reassembly**: Pieces reassembled at destination regardless of order or transport
- **Event system**: Observable events for transport up/down, fragment sent/received, reassembly

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Lint
ruff check ecfs/ tests/

# Type check
mypy ecfs/

# Format
ruff format ecfs/ tests/
```

---

## License

MIT
