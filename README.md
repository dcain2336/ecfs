# ECFS — Autonomous Emergency Communication Failover System

A **delay-tolerant network (DTN) routing engine** with modular transport plugins, designed for communications-degraded environments — hostile territories, disaster zones, or infrastructure-denied areas.

ECFS autonomously routes encrypted data payloads using any available ambient means. It acts as a **universal adapter for communication**, bridging the gap when traditional lines are severed — without requiring ECFS software on intermediary nodes.

## Architecture

```
┌─────────────────────────────────────────────┐
│            Core Orchestration Engine         │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Routing  │ │ Message  │ │ Dedup Cache  │ │
│  │ Engine   │ │ Queue    │ │ (bloom+LRU)  │ │
│  └──────────┘ └──────────┘ └──────────────┘ │
│  ┌──────────────────────────────────────────┐│
│  │        Cryptographic Envelope            ││
│  │  AES-256-GCM + Ed25519 + X25519 PFS     ││
│  └──────────────────────────────────────────┘│
└────────────────┬────────────────────────────┘
                 │ Plugin API
    ┌────────────┼────────────┬──────────┐
    ▼            ▼            ▼          ▼
┌────────┐ ┌────────┐ ┌──────────┐ ┌────────┐
│ LoRa   │ │Internet│ │Ultrasonic│ │  BLE   │
│Transport│ │Transport│ │Transport│ │Transport│
└────────┘ └────────┘ └──────────┘ └────────┘
```

### Core Engine

- **Packet Normalization**: All data wrapped in a standard ECFS envelope (Message ID, TTL, Destination Hash, Encrypted Payload)
- **Deduplication Cache**: TTL-based LRU with bloom filter fast-path — prevents infinite routing loops
- **Priority Queue**: Critical messages jump the queue; expired packets auto-dropped
- **Routing Strategies**: Shotgun (redundant flooding), Shortest-path, Adaptive (priority-aware)

### Cryptographic Envelope

- **AES-256-GCM** encryption with random nonces
- **Ed25519** signatures for packet authenticity
- **X25519 ECDH** key agreement with HKDF session key rotation (Perfect Forward Secrecy)
- **Binary format**: 81-byte fixed header + variable payload + signature

### Transport Plugins

Each transport implements a standard `TransportPlugin` ABC with `send_packet` / `receive_packet` / `get_status`:

| Plugin | Status | Description |
|--------|--------|-------------|
| NullTransport | ✅ Built | Mock transport for testing |
| InternetTransport | 🔲 Phase 2 | HTTPS + DNS tunneling |
| LoRaTransport | 🔲 Phase 3 | Meshtastic / raw serial |
| BLETransport | 🔲 Phase 3 | Bluetooth Low Energy |
| UltrasonicTransport | 🔲 Phase 4 | 18-22kHz FSK audio |
| RFIDTransport | 🔲 Phase 4 | NFC tag relay |

## Installation

```bash
# Core engine (no external deps beyond cryptography)
pip install -e .

# With internet transport
pip install -e ".[internet]"

# Everything
pip install -e ".[all]"
```

## Quick Start

```python
import asyncio
from ecfs.crypto import ECFSPacket, ECFSKeyPair, encrypt_packet_payload
from ecfs.core import RoutingEngine, RoutingStrategy
from ecfs.plugins import NullTransport

async def main():
    # Generate keys
    sender = ECFSKeyPair.generate()
    receiver = ECFSKeyPair.generate()

    # Create encrypted packet
    shared_secret = sender.derive_shared_secret(receiver.public_exchange)
    payload = encrypt_packet_payload(b"Mayday, Mayday!", shared_secret)

    packet = ECFSPacket(
        destination_hash=receiver.public_destination_hash(),
        payload=payload,
    )

    # Set up routing with a mock transport
    transport = NullTransport()
    engine = RoutingEngine(
        plugins=[transport],
        strategy=RoutingStrategy.SHOTGUN,
    )

    await engine.start()

    # Send (will be stored by NullTransport)
    success = await engine.send(
        data=packet.to_bytes(),
        packet_hash=packet.hash(),
    )
    print(f"Sent: {success}")

    # Receive on the other end
    received = await engine.receive()
    print(f"Received {len(received)} bytes")

    await engine.stop()

asyncio.run(main())
```

## CLI

```bash
ecfs status    # Show node status
ecfs send "Emergency message"  # Create + route a packet
ecfs version   # Print version
```

## Project Structure

```
ecfs/
├── ecfs/
│   ├── __init__.py          # Package version
│   ├── cli.py               # CLI entry point
│   ├── crypto/
│   │   ├── packet.py        # ECFSPacket — envelope format + serialization
│   │   ├── keys.py          # ECFSKeyPair — Ed25519 + X25519 key management
│   │   └── cipher.py        # AES-256-GCM encrypt/decrypt + key rotation
│   ├── core/
│   │   ├── routing.py       # RoutingEngine — strategy-based packet routing
│   │   ├── queue.py         # MessageQueue — priority queue with TTL
│   │   └── dedup.py         # DeduplicationCache — LRU + bloom filter
│   └── plugins/
│       ├── base.py          # TransportPlugin ABC + status enums
│       ├── registry.py      # PluginRegistry — discovery + lifecycle
│       └── null_transport.py # NullTransport — mock for testing
├── tests/
│   ├── test_crypto/         # 34 tests — packet, keys, cipher
│   ├── test_core/           # 21 tests — routing, queue, dedup
│   └── test_plugins/        # 48 tests — base, registry, null transport
├── pyproject.toml
└── .github/workflows/ci.yml
```

## Development

```bash
pip install -e ".[dev]"
pytest                    # Run all 103 tests
ruff check ecfs/ tests/  # Lint
mypy ecfs/               # Type check
```

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Core Engine + Crypto + Plugin System | ✅ Complete |
| 2 | Internet Transport (HTTPS/DNS tunneling) | 🔲 Next |
| 3 | Radio & Hardware (LoRa/BLE) | 🔲 Planned |
| 4 | Covert & Ambient (Ultrasonic/RFID) | 🔲 Planned |
| 5 | Autonomous Failover Engine | 🔲 Planned |

## License

MIT
