"""ECFS CLI — node management and diagnostics.

Usage:
    ecfs status       Show node status and available transports
    ecfs send <msg>   Send a message through the failover engine
    ecfs version      Print version
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ecfs import __version__
from ecfs.crypto.keys import ECFSKeyPair
from ecfs.plugins.null_transport import NullTransport
from ecfs.core.routing import RoutingEngine, RoutingStrategy


def cmd_version(_args: argparse.Namespace) -> None:
    print(f"ecfs {__version__}")


def cmd_status(_args: argparse.Namespace) -> None:
    print(f"ECFS v{__version__}")
    print("Node key: (no key generated yet)")
    print("Transports: none registered")
    print("Strategy: adaptive")
    print()
    print("Phase 1 core engine is functional.")
    print("Install optional deps for real transports:")
    print("  pip install 'ecfs[internet]'   — HTTPS/DNS tunneling")
    print("  pip install 'ecfs[radio]'      — LoRa/BLE")
    print("  pip install 'ecfs[audio]'       — Ultrasonic")
    print("  pip install 'ecfs[all]'         — Everything")


def cmd_send(args: argparse.Namespace) -> None:
    """Demo: create a packet, encrypt it, and route through available transports."""
    keypair = ECFSKeyPair.generate()
    print(f"Generated ephemeral keypair: {keypair.key_id.hex()[:16]}...")

    from ecfs.crypto.packet import ECFSPacket
    from ecfs.crypto.cipher import encrypt_packet_payload

    packet = ECFSPacket(
        destination_hash=keypair.public_destination_hash(),
        payload=encrypt_packet_payload(
            args.message.encode(), keypair.derive_shared_secret(keypair.public_exchange)
        ),
    )
    print(f"Packet ID: {packet.message_id}")
    print(f"Size: {len(packet.to_bytes())} bytes")
    print(f"Payload: {args.message}")
    print()
    print("No transport plugins registered — packet created but not sent.")
    print("Register a transport plugin to actually send packets.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecfs",
        description="Autonomous Emergency Communication Failover System",
    )
    parser.add_argument("--version", action="version", version=f"ecfs {__version__}")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("version", help="Print version")
    sub.add_parser("status", help="Show node status")

    send_p = sub.add_parser("send", help="Send a message")
    send_p.add_argument("message", help="Message to send")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version" or args.version:
        cmd_version(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "send":
        cmd_send(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
