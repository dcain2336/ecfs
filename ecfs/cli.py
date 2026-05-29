"""ECFS CLI — node management and diagnostics.

Usage:
    ecfs status       Show node status and available transports
    ecfs send <msg>   Send a message through the failover engine
    ecfs detect       Show detected hardware
    ecfs mesh start   Start auto-discovering mesh node
    ecfs mesh status  Show discovered peers and transport health
    ecfs mesh send    Send to any reachable peer
    ecfs mesh receive Listen for incoming messages
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


def cmd_detect(_args: argparse.Namespace) -> None:
    """Show detected hardware on this machine."""
    from ecfs.discovery.hardware import detect_hardware
    profile = detect_hardware()
    print(f"ECFS v{__version__} — Hardware Detection")
    print()
    print(f"  Network:    {'Yes' if profile.has_network else 'No'} ({len(profile.network_interfaces)} interfaces)")
    print(f"  Bluetooth:  {'Yes' if profile.has_bluetooth else 'No'}")
    print(f"  Serial:     {'Yes' if profile.has_serial else 'No'} ({', '.join(profile.serial_ports) if profile.serial_ports else 'none'})")
    print(f"  Speaker:    {'Yes' if profile.has_speaker else 'No'}")
    print(f"  Microphone: {'Yes' if profile.has_microphone else 'No'}")
    print(f"  NFC Reader: {'Yes' if profile.has_nfc_reader else 'No'}")
    print()
    print(f"Available transports: {profile.transport_count}")
    print(f"Summary: {profile.summary()}")


def cmd_mesh_start(args: argparse.Namespace) -> None:
    """Start an auto-discovering mesh node."""
    from ecfs.discovery.mesh import MeshNode

    async def _run():
        node = MeshNode(name=args.name)
        status = await node.start()
        print(f"Mesh node '{status['name']}' started (id: {status['node_id']})")
        print(f"Hardware: {status['hardware']}")
        print(f"Transports: {', '.join(status['transports']) if status['transports'] else 'none'}")
        print(f"Transport count: {status['transport_count']}")
        print()
        print("Node is running. Use Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
            await node.stop()
            print("Stopped.")

    asyncio.run(_run())


def cmd_mesh_status(_args: argparse.Namespace) -> None:
    """Show mesh status (placeholder — requires running node)."""
    print("Mesh status requires a running node.")
    print("Start one with: ecfs mesh start --name <name>")


def cmd_mesh_send(args: argparse.Namespace) -> None:
    """Send a message through the mesh."""
    from ecfs.discovery.mesh import MeshNode

    async def _run():
        node = MeshNode(name='ecfs-cli')
        status = await node.start()
        print(f"Sending via {status['transport_count']} transports...")
        success = await node.send(args.message.encode())
        print(f"Result: {'sent' if success else 'queued (no transport available)'}")
        await node.stop()

    asyncio.run(_run())


def cmd_mesh_receive(args: argparse.Namespace) -> None:
    """Listen for incoming mesh messages."""
    from ecfs.discovery.mesh import MeshNode

    async def _run():
        node = MeshNode(name='ecfs-cli-receiver')
        status = await node.start()
        print(f"Listening on {status['transport_count']} transports...")
        print("Waiting for messages (Ctrl+C to stop)...")
        try:
            while True:
                data = await node.receive()
                if data:
                    print(f"Received: {data.decode(errors='replace')}")
        except KeyboardInterrupt:
            print("\nStopping...")
            await node.stop()

    asyncio.run(_run())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecfs",
        description="Autonomous Emergency Communication Failover System",
    )
    parser.add_argument("--version", action="version", version=f"ecfs {__version__}")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("version", help="Print version")
    sub.add_parser("status", help="Show node status")
    sub.add_parser("detect", help="Detect hardware on this machine")

    send_p = sub.add_parser("send", help="Send a message")
    send_p.add_argument("message", help="Message to send")

    # Mesh subcommands
    mesh_parser = sub.add_parser("mesh", help="Mesh networking commands")
    mesh_sub = mesh_parser.add_subparsers(dest="mesh_command")

    mesh_start = mesh_sub.add_parser("start", help="Start auto-discovering mesh node")
    mesh_start.add_argument("--name", default="ecfs-node", help="Node name")

    mesh_sub.add_parser("status", help="Show mesh status")

    mesh_send = mesh_sub.add_parser("send", help="Send message through mesh")
    mesh_send.add_argument("message", help="Message to send")

    mesh_sub.add_parser("receive", help="Listen for mesh messages")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version" or getattr(args, "version", False):
        cmd_version(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "detect":
        cmd_detect(args)
    elif args.command == "mesh":
        if args.mesh_command == "start":
            cmd_mesh_start(args)
        elif args.mesh_command == "status":
            cmd_mesh_status(args)
        elif args.mesh_command == "send":
            cmd_mesh_send(args)
        elif args.mesh_command == "receive":
            cmd_mesh_receive(args)
        else:
            parser.parse_args([args.command, "--help"])
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
